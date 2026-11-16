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
from collections import OrderedDict

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app import github, grounding, limits, llm, tts
from app.db import engine, get_session, init_db
from app.models import Clip, Project, RepoSnapshot, Usage, now
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
    topic: str = Field(min_length=3, max_length=200, description="What they want to learn; for a repository, their question about it.")
    repo: str = Field(default="", max_length=300, description="A public GitHub repository link, or empty for a topic lesson.")
    notes: str = Field(default="", max_length=12000)
    level: str = Field(default="intro", pattern="^(intro|intermediate|advanced)$")
    minutes: int = Field(default=3, ge=1, le=5)


def aware(dt):
    """SQLite hands datetimes back without a timezone; they were stored as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def clip_url(h: str) -> str:
    return f"/api/clips/{h}.mp3"


def voices_for(session: Session, project: Project) -> dict[str, Any]:
    """The voiced narration for each scene whose current text has been voiced. Two scenes
    with the same narration share one clip."""
    scenes = (project.storyboard or {}).get("scenes", [])
    voice, model = project.voice_id or tts.voice_id(), tts.model_id()
    by_hash: dict[str, list[str]] = {}
    for scene in scenes:
        by_hash.setdefault(tts.clip_hash(voice, model, scene["narration"]), []).append(scene["id"])
    if not by_hash:
        return {}
    rows = session.exec(select(Clip.hash, Clip.text, Clip.words, Clip.duration).where(col(Clip.hash).in_(list(by_hash)))).all()
    return {
        scene_id: {"hash": h, "text": text, "url": clip_url(h), "duration": duration, "words": words}
        for h, text, words, duration in rows
        for scene_id in by_hash[h]
    }


# Longer than the slowest possible write (two Claude attempts of up to 240 s each), so a
# write that is still running is never declared dead.
WRITE_EXPIRES = timedelta(minutes=10)


def expire_stale_write(session: Session, project: Project) -> None:
    """A write that started long ago isn't coming back (the server restarted, or the
    request died). Say so instead of spinning forever."""
    if project.status == "writing" and now() - aware(project.updated_at) > WRITE_EXPIRES:
        project.status = "failed"
        project.error = "Writing took too long and stopped. Try again."
        session.add(project)
        session.commit()
        session.refresh(project)


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
        "repo": project.repo or "",
        "repo_ref": project.repo_ref or "",
        "repo_sha": project.repo_sha or "",
        "progress": (project.progress or [])[-12:],
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
        "repo": project.repo or "",
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
    repo = ""
    if body.repo.strip():
        try:
            o, r, ref = github.parse_repo(body.repo)
        except github.RepoError as exc:
            raise ApiError(exc.status, exc.code, exc.message) from exc
        repo = f"{o}/{r}"
    project = Project(owner=owner, topic=body.topic.strip(), notes=body.notes.strip(), level=body.level, minutes=body.minutes,
                      repo=repo, repo_ref=(ref or "") if repo else "")
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
        if project.repo and project.repo_sha and (snap := load_snapshot(session, f"{project.repo}@{project.repo_sha}")):
            board = grounding.ground(board, snap, hand=True)  # code on screen always comes from the file
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


def log_calls(session: Session, project_id: str, owner: str, kind: str, calls: list[llm.Call], error: str = "") -> None:
    """One row per write or edit, with every Claude request it made summed in, including the
    ones that failed: they cost money too. Limits count rows, so a repo lesson that took 30
    requests still counts as one lesson."""
    calls = calls or []
    session.add(Usage(project_id=project_id, owner=owner, kind=kind, provider="anthropic",
                      model=calls[-1].model if calls else llm.model(), requests=len(calls),
                      input_tokens=sum(c.input_tokens for c in calls), output_tokens=sum(c.output_tokens for c in calls),
                      ms=sum(c.ms for c in calls), ok=not error, error=error))
    session.commit()


def set_project(session: Session, project_id: str, **fields: Any) -> Project:
    """Reload the lesson and change it. Used after a slow outside call, during which the
    request held no database connection."""
    project = session.get(Project, project_id)
    if not project:
        raise ApiError(404, "not_found", "That lesson was deleted while it was being worked on.")
    for k, v in fields.items():
        setattr(project, k, v)
    project.updated_at = now()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


_snapshots: "OrderedDict[str, github.Snapshot]" = OrderedDict()
SNAPSHOT_CACHE = 8  # each is up to 8 MB of text


def remember(snap: github.Snapshot) -> github.Snapshot:
    _snapshots[snap.key] = snap
    _snapshots.move_to_end(snap.key)
    while len(_snapshots) > SNAPSHOT_CACHE:
        _snapshots.popitem(last=False)
    return snap


def load_snapshot(session: Session, key: str) -> github.Snapshot | None:
    """A stored repository, from memory if this server read it recently."""
    if key in _snapshots:
        _snapshots.move_to_end(key)
        return _snapshots[key]
    row = session.get(RepoSnapshot, key)
    if not row:
        return None
    return remember(github.Snapshot.unpack(row.owner, row.repo, row.sha, row.ref, row.description, row.files))


def fetch_snapshot(session: Session, repo: str, ref: str = "") -> github.Snapshot:
    """The repository at its current commit: from storage when that commit was read before
    (one small API call to learn the commit), otherwise downloaded."""
    owner, name = repo.split("/", 1)
    sha = github.head_sha(owner, name, ref or None)
    if sha:
        row = session.exec(select(RepoSnapshot).where(col(RepoSnapshot.sha) == sha, func.lower(RepoSnapshot.owner) == owner.lower(),
                                                      func.lower(RepoSnapshot.repo) == name.lower())).first()
        if row and (snap := load_snapshot(session, row.key)):
            return snap
    snap = github.download(owner, name, ref or None)
    if not session.get(RepoSnapshot, snap.key):
        session.add(RepoSnapshot(key=snap.key, owner=snap.owner, repo=snap.repo, sha=snap.sha, ref=snap.ref,
                                 description=snap.description, file_count=len(snap.files), files=snap.pack()))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()  # another request stored the same commit first
    return remember(snap)


def progress_writer(project_id: str):
    """Records what Claude is doing, in its own short transaction, for the waiting screen."""

    def write(text: str) -> None:
        with Session(engine) as s:
            p = s.get(Project, project_id)
            if p:
                p.progress = [*(p.progress or [])[-30:], text]
                p.updated_at = now()  # a heartbeat: a write that's still reading isn't stale
                s.add(p)
                s.commit()

    return write


@app.post("/api/projects/{project_id}/write")
def write_project(project_id: str, session: SessionDep, owner: OwnerDep):
    """Claude writes the lesson. Runs on the person's click, never on page load."""
    project = owned_project(session, project_id, owner)
    expire_stale_write(session, project)
    if why := limits.check(session, owner, "write"):
        if project.status != "ready":
            set_project(session, project_id, status="failed", error=why)
        raise ApiError(429, "limit", why)

    # Claim the lesson in one statement, so two clicks can't start two paid writes.
    claimed = session.exec(
        update(Project)
        .where(col(Project.id) == project_id, col(Project.status) != "writing")
        .values(status="writing", error="", updated_at=now())
    ).rowcount
    session.commit()
    if not claimed:
        raise ApiError(409, "already_writing", "This lesson is already being written.")

    topic, notes, level, minutes, repo, ref = project.topic, project.notes, project.level, project.minutes, project.repo, project.repo_ref or ""
    voice_id = project.voice_id or tts.voice_id()
    session.close()  # don't hold a database connection while GitHub or Claude works
    progress = progress_writer(project_id)
    repo_sha = ""
    try:
        if repo:
            set_project(session, project_id, progress=[f"Downloading github.com/{repo}"])
            session.close()
            snap = fetch_snapshot(session, repo, ref)
            repo_sha = snap.sha
            # GitHub's spelling of the name, so the snapshot is found again for edits and saves
            set_project(session, project_id, repo=snap.name, repo_sha=snap.sha,
                        progress=[f"Read {len(snap.files)} files from github.com/{snap.name}"])
            session.close()
            board, calls = llm.write_repo_lesson(snap, topic, level, minutes, progress)
        else:
            board, call = llm.write_storyboard(topic, notes, level, minutes)
            calls = [call]
    except github.RepoError as exc:
        set_project(session, project_id, status="failed", error=exc.message)
        raise ApiError(exc.status, exc.code, exc.message) from exc
    except llm.AIError as exc:
        log_calls(session, project_id, owner, "write", exc.calls, error=exc.code)
        set_project(session, project_id, status="failed", error=exc.message)
        raise ApiError(exc.status, exc.code, exc.message) from exc
    except Exception as exc:
        # anything unplanned still ends the write, so the page doesn't wait ten minutes
        session.rollback()
        set_project(session, project_id, status="failed", error="Something went wrong while writing. Try again.")
        raise ApiError(500, "write_failed", "Something went wrong while writing. Try again.") from exc

    log_calls(session, project_id, owner, "write", calls)
    project = set_project(session, project_id, storyboard=board.model_dump(), title=board.title,
                          voice_id=voice_id, status="ready", error="", **({"repo_sha": repo_sha} if repo_sha else {}))
    return project_out(project, owner, voices_for(session, project))


def clip_out(clip: Clip) -> dict[str, Any]:
    return {"hash": clip.hash, "text": clip.text, "url": clip_url(clip.hash), "duration": clip.duration, "words": clip.words}


@app.post("/api/projects/{project_id}/scenes/{scene_id}/voice")
def voice_scene(project_id: str, scene_id: str, session: SessionDep, owner: OwnerDep):
    """ElevenLabs voices one scene's narration, unless that exact text was voiced before."""
    project = owned_project(session, project_id, owner)
    scenes = (project.storyboard or {}).get("scenes", [])
    i = next((k for k, s in enumerate(scenes) if s["id"] == scene_id), None)
    if i is None:
        raise ApiError(404, "no_scene", "That scene isn't in the lesson any more.")
    narration = scenes[i]["narration"]
    if not narration.strip():
        raise ApiError(422, "empty_narration", "This scene has no narration to voice.")

    voice, model = project.voice_id or tts.voice_id(), tts.model_id()
    h = tts.clip_hash(voice, model, narration)
    if clip := session.get(Clip, h):
        return clip_out(clip)
    if why := limits.check(session, owner, "voice", characters=len(narration)):
        raise ApiError(429, "limit", why)

    prev_text = scenes[i - 1]["narration"] if i > 0 else ""
    next_text = scenes[i + 1]["narration"] if i + 1 < len(scenes) else ""
    session.close()  # don't hold a database connection while ElevenLabs speaks
    try:
        spoken = tts.speak(narration, voice, model, prev_text, next_text)
    except tts.VoiceError as exc:
        session.add(Usage(project_id=project_id, owner=owner, kind="voice", provider="elevenlabs", model=model, ok=False, error=exc.code))
        session.commit()
        raise ApiError(exc.status, exc.code, exc.message) from exc

    session.add(Usage(project_id=project_id, owner=owner, kind="voice", provider="elevenlabs", model=model, characters=len(narration), ms=spoken.ms))
    session.commit()
    clip = Clip(hash=h, voice_id=voice, model_id=model, text=narration, audio=spoken.audio, words=spoken.words, duration=spoken.duration)
    session.add(clip)
    try:
        session.commit()
    except IntegrityError:
        # The same narration was voiced by another request a moment ago: use that one.
        session.rollback()
        clip = session.get(Clip, h)
        if not clip:
            raise
    else:
        session.refresh(clip)
    return clip_out(clip)


@app.api_route("/api/clips/{name}", methods=["GET", "HEAD"])
def get_clip(name: str, request: Request, session: SessionDep, range: Annotated[str | None, Header()] = None):
    """The MP3. Supports byte ranges, which Safari needs before it will play or seek audio."""
    h = name.removesuffix(".mp3")
    clip = session.get(Clip, h)
    if not clip:
        raise ApiError(404, "not_found", "That audio doesn't exist.")
    data = clip.audio
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=31536000, immutable"}
    status, body = 200, data
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
        status, body = 206, data[start : end + 1]
    if request.method == "HEAD":
        headers["Content-Length"] = str(len(body))
        return Response(status_code=status, media_type="audio/mpeg", headers=headers)
    return Response(body, status_code=status, media_type="audio/mpeg", headers=headers)


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
    started_from = project.updated_at
    notes = project.notes
    snap = load_snapshot(session, f"{project.repo}@{project.repo_sha}") if project.repo and project.repo_sha else None
    session.close()  # don't hold a database connection while Claude edits
    try:
        outcome = llm.edit_storyboard(board, body.instruction.strip(), body.scene_id, notes, snap=snap)
    except llm.AIError as exc:
        log_calls(session, project_id, owner, "edit", exc.calls, error=exc.code)
        raise ApiError(exc.status, exc.code, exc.message) from exc
    log_calls(session, project_id, owner, "edit", outcome.calls)

    current = session.get(Project, project_id)
    if current and aware(current.updated_at) != aware(started_from):
        raise ApiError(409, "changed_meanwhile", "The lesson changed while Claude was editing it, so the edit wasn't applied. Ask again.")
    project = set_project(session, project_id, storyboard=outcome.board.model_dump(), title=outcome.board.title)
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
