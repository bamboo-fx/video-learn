"""The API, and the web app's static files, from one FastAPI service."""

import os
import pathlib
import re
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from datetime import timedelta, timezone

from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, col, select

from app import limits, llm, tts
from app.db import get_session, init_db
from app.models import Clip, Project, Usage, now
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


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"error": {"code": "http_error", "message": str(exc.detail)}}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    msg = f"{where}: {first.get('msg', 'invalid request')}" if where else first.get("msg", "invalid request")
    return JSONResponse({"error": {"code": "invalid_request", "message": msg}}, status_code=422)


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
    topic: str = Field(min_length=3, max_length=200)
    notes: str = Field(default="", max_length=12000)
    level: str = Field(default="intro", pattern="^(intro|intermediate|advanced)$")
    minutes: int = Field(default=3, ge=1, le=5)


def aware(dt):
    """SQLite hands datetimes back without a timezone; they were stored as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def clip_url(h: str) -> str:
    return f"/api/clips/{h}.mp3"


def voices_for(session: Session, project: Project) -> dict[str, Any]:
    """The voiced narration for each scene whose current text has been voiced."""
    scenes = (project.storyboard or {}).get("scenes", [])
    voice, model = project.voice_id or tts.voice_id(), tts.model_id()
    wanted = {tts.clip_hash(voice, model, s["narration"]): s["id"] for s in scenes}
    if not wanted:
        return {}
    rows = session.exec(select(Clip.hash, Clip.text, Clip.words, Clip.duration).where(col(Clip.hash).in_(list(wanted)))).all()
    return {
        wanted[h]: {"hash": h, "text": text, "url": clip_url(h), "duration": duration, "words": words}
        for h, text, words, duration in rows
    }


def expire_stale_write(session: Session, project: Project) -> None:
    """A write that started more than five minutes ago isn't coming back (the server
    restarted, or the request died). Say so instead of spinning forever."""
    if project.status == "writing" and now() - aware(project.updated_at) > timedelta(minutes=5):
        project.status = "failed"
        project.error = "Writing took too long and stopped. Try again."
        session.add(project)
        session.commit()
        session.refresh(project)


def project_out(project: Project, owner: str | None, voices: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": project.id,
        "topic": project.topic,
        "notes": project.notes,
        "level": project.level,
        "minutes": project.minutes,
        "title": project.title or project.topic,
        "status": project.status,
        "error": project.error,
        "storyboard": project.storyboard,
        "voices": voices or {},
        "is_owner": owner is not None and owner == project.owner,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


def project_summary(project: Project) -> dict[str, Any]:
    scenes = (project.storyboard or {}).get("scenes", [])
    return {
        "id": project.id,
        "title": project.title or project.topic,
        "topic": project.topic,
        "status": project.status,
        "scenes": len(scenes),
        "updated_at": project.updated_at.isoformat(),
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
    expire_stale_write(session, project)
    return project_out(project, owner, voices_for(session, project))


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
    return project_out(project, owner, voices_for(session, project))


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: str, session: SessionDep, owner: OwnerDep):
    project = owned_project(session, project_id, owner)
    session.delete(project)
    session.commit()


def log_usage(session: Session, project: Project, kind: str, provider: str, model: str, **fields: Any) -> None:
    session.add(Usage(project_id=project.id, owner=project.owner, kind=kind, provider=provider, model=model, **fields))
    session.commit()


@app.post("/api/projects/{project_id}/write")
def write_project(project_id: str, session: SessionDep, owner: OwnerDep):
    """Claude writes the lesson. Runs on the person's click, never on page load."""
    project = owned_project(session, project_id, owner)
    expire_stale_write(session, project)
    if project.status == "writing":
        raise ApiError(409, "already_writing", "This lesson is already being written.")
    if why := limits.check(session, owner, "write"):
        raise ApiError(429, "limit", why)

    project.status, project.error, project.updated_at = "writing", "", now()
    session.add(project)
    session.commit()

    try:
        board, call = llm.write_storyboard(project.topic, project.notes, project.level, project.minutes)
    except llm.AIError as exc:
        log_usage(session, project, "write", "anthropic", llm.model(), ok=False, error=exc.code)
        project.status, project.error, project.updated_at = "failed", exc.message, now()
        session.add(project)
        session.commit()
        raise ApiError(exc.status, exc.code, exc.message) from exc

    log_usage(session, project, "write", "anthropic", call.model, input_tokens=call.input_tokens, output_tokens=call.output_tokens, ms=call.ms)
    project.storyboard = board.model_dump()
    project.title = board.title
    project.voice_id = project.voice_id or tts.voice_id()
    project.status, project.error, project.updated_at = "ready", "", now()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project_out(project, owner, voices_for(session, project))


@app.post("/api/projects/{project_id}/scenes/{scene_id}/voice")
def voice_scene(project_id: str, scene_id: str, session: SessionDep, owner: OwnerDep):
    """ElevenLabs voices one scene's narration, unless that exact text was voiced before."""
    project = owned_project(session, project_id, owner)
    scenes = (project.storyboard or {}).get("scenes", [])
    i = next((k for k, s in enumerate(scenes) if s["id"] == scene_id), None)
    if i is None:
        raise ApiError(404, "no_scene", "That scene isn't in the lesson any more.")
    text = scenes[i]["narration"].strip()
    if not text:
        raise ApiError(422, "empty_narration", "This scene has no narration to voice.")

    voice, model = project.voice_id or tts.voice_id(), tts.model_id()
    h = tts.clip_hash(voice, model, scenes[i]["narration"])
    clip = session.get(Clip, h)
    if not clip:
        if why := limits.check(session, owner, "voice", characters=len(text)):
            raise ApiError(429, "limit", why)
        prev_text = scenes[i - 1]["narration"] if i > 0 else ""
        next_text = scenes[i + 1]["narration"] if i + 1 < len(scenes) else ""
        try:
            spoken = tts.speak(scenes[i]["narration"], voice, model, prev_text, next_text)
        except tts.VoiceError as exc:
            log_usage(session, project, "voice", "elevenlabs", model, characters=0, ok=False, error=exc.code)
            raise ApiError(exc.status, exc.code, exc.message) from exc
        log_usage(session, project, "voice", "elevenlabs", model, characters=len(scenes[i]["narration"]), ms=spoken.ms)
        clip = Clip(hash=h, voice_id=voice, model_id=model, text=scenes[i]["narration"], audio=spoken.audio, words=spoken.words, duration=spoken.duration)
        session.add(clip)
        session.commit()
        session.refresh(clip)
    return {"hash": clip.hash, "text": clip.text, "url": clip_url(clip.hash), "duration": clip.duration, "words": clip.words}


@app.get("/api/clips/{name}")
def get_clip(name: str, session: SessionDep, range: Annotated[str | None, Header()] = None):
    """The MP3. Supports byte ranges, which Safari needs before it will play or seek audio."""
    h = name.removesuffix(".mp3")
    clip = session.get(Clip, h)
    if not clip:
        raise ApiError(404, "not_found", "That audio doesn't exist.")
    data = clip.audio
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=31536000, immutable"}
    if range and range.startswith("bytes="):
        start_s, _, end_s = range[6:].partition("-")
        try:
            start = int(start_s) if start_s else max(0, len(data) - int(end_s))
            end = int(end_s) if (end_s and start_s) else len(data) - 1
        except ValueError:
            start, end = 0, len(data) - 1
        end = min(end, len(data) - 1)
        if start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{len(data)}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
        return Response(data[start : end + 1], status_code=206, media_type="audio/mpeg", headers=headers)
    return Response(data, media_type="audio/mpeg", headers=headers)


class EditIn(BaseModel):
    instruction: str = Field(min_length=2, max_length=600)
    scene_id: str | None = None


@app.post("/api/projects/{project_id}/edit")
def edit_project(project_id: str, body: EditIn, session: SessionDep, owner: OwnerDep):
    """Claude changes the storyboard through tools; the answer is the list of changes."""
    project = owned_project(session, project_id, owner)
    if not project.storyboard:
        raise ApiError(409, "not_written", "There's no lesson to edit yet.")
    if why := limits.check(session, owner, "edit"):
        raise ApiError(429, "limit", why)
    board = Storyboard.model_validate(project.storyboard)
    try:
        outcome = llm.edit_storyboard(board, body.instruction.strip(), body.scene_id, project.notes)
    except llm.AIError as exc:
        log_usage(session, project, "edit", "anthropic", llm.model(), ok=False, error=exc.code)
        raise ApiError(exc.status, exc.code, exc.message) from exc
    for call in outcome.calls:
        session.add(Usage(project_id=project.id, owner=owner, kind="edit", provider="anthropic", model=call.model,
                          input_tokens=call.input_tokens, output_tokens=call.output_tokens, ms=call.ms))
    project.storyboard = outcome.board.model_dump()
    project.title = outcome.board.title
    project.updated_at = now()
    session.add(project)
    session.commit()
    session.refresh(project)
    return {"project": project_out(project, owner, voices_for(session, project)), "summary": outcome.summary, "changes": outcome.changes}


@app.get("/api/projects/{project_id}/usage")
def project_usage(project_id: str, session: SessionDep, owner: OwnerDep):
    """What this lesson has cost so far, in tokens and characters (for the cost analysis)."""
    project = owned_project(session, project_id, owner)
    rows = session.exec(select(Usage).where(Usage.project_id == project.id).order_by(Usage.created_at)).all()
    return {"calls": [r.model_dump(mode="json") for r in rows]}


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
