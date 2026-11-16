"""The API, and the web app's static files, from one FastAPI service."""

import os
import pathlib
import re
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlmodel import Session, select

from app.db import get_session, init_db
from app.models import Project, now
from app.storyboard import Storyboard, normalize


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Video Learn", lifespan=lifespan)


# ---------------------------------------------------------------- errors


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


@app.exception_handler(ApiError)
async def api_error(_: Request, exc: ApiError):
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    """Starlette's base class, so routing errors (405 on OPTIONS, say) use the envelope too."""
    return JSONResponse({"error": {"code": "http_error", "message": str(exc.detail)}}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    msg = f"{where}: {first.get('msg', 'invalid request')}" if where else first.get("msg", "invalid request")
    return JSONResponse({"error": {"code": "invalid_request", "message": msg}}, status_code=422)


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception):
    """Anything unplanned still answers in the same shape, so the page can say something."""
    import logging

    logging.getLogger("video-learn").exception("unhandled error", exc_info=exc)
    return JSONResponse({"error": {"code": "server_error", "message": "Something went wrong on the server. Try again."}}, status_code=500)


# ---------------------------------------------------------------- who is asking

OWNER_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def owner_header(x_owner: Annotated[str | None, Header()] = None) -> str | None:
    """The browser keeps a random id in localStorage and sends it on every request.
    There are no accounts: whoever holds the id owns the lessons made with it."""
    if x_owner and OWNER_RE.match(x_owner):
        return x_owner
    return None


def require_owner(owner: Annotated[str | None, Depends(owner_header)]) -> str:
    if not owner:
        raise ApiError(400, "no_owner", "This browser has no id yet. Reload the page and try again.")
    return owner


SessionDep = Annotated[Session, Depends(get_session)]
OwnerDep = Annotated[str, Depends(require_owner)]
MaybeOwner = Annotated[str | None, Depends(owner_header)]


def load_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise ApiError(404, "not_found", "That lesson doesn't exist, or it was deleted.")
    return project


def owned_project(session: Session, project_id: str, owner: str) -> Project:
    project = load_project(session, project_id)
    if project.owner != owner:
        raise ApiError(403, "not_owner", "Only the person who made this lesson can change it.")
    return project


# ---------------------------------------------------------------- shapes


class ProjectIn(BaseModel):
    # stripped before the length check, so "   " isn't a topic
    topic: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    notes: str = Field(default="", max_length=12000)
    level: str = Field(default="intro", pattern="^(intro|intermediate|advanced)$")
    minutes: int = Field(default=3, ge=1, le=5)


def iso(dt) -> str:
    """UTC with an explicit offset. SQLite hands datetimes back without one, and a browser
    reads an offset-less time as its own local time."""
    from datetime import timezone

    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def project_out(project: Project, owner: str | None, voices: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": project.id,
        "topic": project.topic,
        # notes are the owner's own material; a share link shows the lesson, not the notes
        "notes": project.notes if owner is not None and owner == project.owner else "",
        "level": project.level,
        "minutes": project.minutes,
        "title": project.title or project.topic,
        "status": project.status,
        "error": project.error,
        "storyboard": project.storyboard,
        "voices": voices or {},
        "is_owner": owner is not None and owner == project.owner,
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
    }


def project_summary(project: Project) -> dict[str, Any]:
    scenes = (project.storyboard or {}).get("scenes", [])
    return {
        "id": project.id,
        "title": project.title or project.topic,
        "topic": project.topic,
        "status": project.status,
        "scenes": len(scenes),
        "updated_at": iso(project.updated_at),
    }


# ---------------------------------------------------------------- routes


@app.get("/api/health")
def health(session: SessionDep):
    session.exec(select(1)).one()
    return {"ok": True}


@app.get("/api/config")
def config():
    """What this server can do, so the page can say so before anyone clicks."""
    return {"ai": bool(os.environ.get("ANTHROPIC_API_KEY")), "voice": bool(os.environ.get("ELEVENLABS_API_KEY"))}


@app.get("/api/projects")
def list_projects(session: SessionDep, owner: OwnerDep):
    rows = session.exec(select(Project).where(Project.owner == owner).order_by(Project.updated_at.desc()).limit(50)).all()
    return {"projects": [project_summary(p) for p in rows]}


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectIn, session: SessionDep, owner: OwnerDep):
    project = Project(owner=owner, topic=body.topic.strip(), notes=body.notes.strip(), level=body.level, minutes=body.minutes)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project_out(project, owner)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str, session: SessionDep, owner: MaybeOwner):
    project = load_project(session, project_id)
    return project_out(project, owner)


class StoryboardIn(BaseModel):
    storyboard: dict[str, Any]


@app.put("/api/projects/{project_id}/storyboard")
def save_storyboard(project_id: str, body: StoryboardIn, session: SessionDep, owner: OwnerDep):
    project = owned_project(session, project_id, owner)
    try:
        board = normalize(Storyboard.model_validate(body.storyboard))
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise ApiError(422, "invalid_storyboard", f"The lesson couldn't be saved: {where}: {first['msg']}") from exc
    project.storyboard = board.model_dump()
    project.title = board.title
    project.status = "ready"
    project.error = ""
    project.updated_at = now()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project_out(project, owner)


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: str, session: SessionDep, owner: OwnerDep):
    project = owned_project(session, project_id, owner)
    session.delete(project)
    session.commit()


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def api_not_found(rest: str):
    raise ApiError(404, "not_found", f"No API route /api/{rest}")


# ---------------------------------------------------------------- the web app

WEB = pathlib.Path(__file__).resolve().parents[2] / "web" / "dist"

if (WEB / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets", html=False), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def web_app(path: str):
    target = (WEB / path).resolve()
    if path and target.is_file() and WEB in target.parents:
        return FileResponse(target)
    index = WEB / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"error": {"code": "no_web_build", "message": "The web app isn't built yet."}}, status_code=503)
