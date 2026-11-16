"""The API, and the web app's static files, from one FastAPI service."""

import hashlib
import hmac
import os
import pathlib
import secrets
import threading
import re
from contextlib import asynccontextmanager, contextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from datetime import timedelta, timezone

from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from collections import OrderedDict

from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import connector, github, grounding, limits, llm, secrets_scan, tts
from app.db import engine, get_session, init_db
from app.models import Clip, Project, RepoSnapshot, Usage, now
from app.storyboard import Storyboard, normalize


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    # The claude.ai connector at /mcp. Its session manager can only run once, so each start of
    # the app gets a fresh one (and a fresh /mcp route bound to it).
    fresh = connector.routes()
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/mcp"]
    app.router.routes[0:0] = fresh
    async with connector.server.session_manager.run():
        yield


app = FastAPI(title="Video Learn", lifespan=lifespan)


class LimitImportBody:
    """Read an import body before anything parses it, refusing it as soon as it passes the
    limit. Counting the bytes (not trusting Content-Length) also covers chunked uploads."""

    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/api/import":
            return await self.app(scope, receive, send)
        chunks, size, more = [], 0, True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.limit:
                await JSONResponse({"error": {"code": "too_big", "message": "That lesson is too large to upload."}},
                                   status_code=413)(scope, receive, send)
                return
            chunks.append(chunk)
            more = message.get("more_body", False)
        body = b"".join(chunks)
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)


app.add_middleware(LimitImportBody, limit=300_000)


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
    # what they want to learn (for a repository, their question about it), stripped before
    # the length check so "   " isn't a topic
    topic: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
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


def iso(dt) -> str:
    """UTC with an explicit offset. SQLite hands datetimes back without one, and a browser
    reads an offset-less time as its own local time."""
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
        "repo": project.repo or "",
        "repo_ref": project.repo_ref or "",
        "repo_sha": project.repo_sha or "",
        "progress": (project.progress or [])[-PROGRESS_KEEP:],
        "voices": voices or {},
        "is_owner": owner is not None and bool(project.owner) and owner == project.owner,
        "origin": project.origin or "web",
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
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
    if project.status == "writing":
        raise ApiError(409, "being_written", "This lesson is being written. Your changes can be saved once it's done.")
    try:
        board = normalize(Storyboard.model_validate(body.storyboard))
        # Re-ground only lessons whose code came from a snapshot (written here, or through the
        # connector). A /lesson upload's code came from the person's own files, which the
        # server doesn't have; a cached snapshot of the same commit may be trimmed.
        if ((project.origin or "web") != "local" and project.repo and project.repo_sha
                and (snap := load_snapshot(session, f"{project.repo}@{project.repo_sha}"))):
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


def settle_calls(session: Session, usage_id: int, calls: list[llm.Call], error: str = "") -> None:
    """Fill in a reserved write or edit with every Claude request it made, summed, including
    the ones that failed: they cost money too. The reservation is one row, so a repo lesson
    that took 30 requests still counts as one lesson."""
    calls = calls or []
    # priced per request before summing: a fallback can answer with a different model
    costs = [llm.cost_usd(c.model, c.input_tokens, c.output_tokens, c.cache_write_tokens, c.cache_read_tokens) for c in calls]
    limits.settle(session, usage_id, model=calls[-1].model if calls else llm.model(), ok=not error, error=error,
                  cost_usd=round(sum(c for c in costs if c is not None), 4) if calls and None not in costs else None,
                  requests=len(calls), input_tokens=sum(c.input_tokens for c in calls),
                  output_tokens=sum(c.output_tokens for c in calls),
                  cache_write_tokens=sum(c.cache_write_tokens for c in calls),
                  cache_read_tokens=sum(c.cache_read_tokens for c in calls), ms=sum(c.ms for c in calls))


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
_snapshots_lock = threading.Lock()  # routes run in a thread pool
SNAPSHOT_CACHE = 8  # each is up to 8 MB of text


def remember(snap: github.Snapshot) -> github.Snapshot:
    with _snapshots_lock:
        _snapshots[snap.key] = snap
        _snapshots.move_to_end(snap.key)
        while len(_snapshots) > SNAPSHOT_CACHE:
            _snapshots.popitem(last=False)
    return snap


def load_snapshot(session: Session, key: str) -> github.Snapshot | None:
    """A stored repository, from memory if this server read it recently."""
    with _snapshots_lock:
        snap = _snapshots.get(key)
        if snap is not None:
            _snapshots.move_to_end(key)
            return snap
    row = session.get(RepoSnapshot, key)
    if not row:
        return None
    return remember(github.Snapshot.unpack(row.owner, row.repo, row.sha, row.ref, row.description, row.files))


def fetch_snapshot(session: Session, repo: str, ref: str = "") -> github.Snapshot:
    """The repository at its current commit: from storage when that commit was read before
    (one small API call to learn the commit), otherwise downloaded."""
    owner, name = repo.split("/", 1)
    # settle which part of a tree/blob path is the branch first, so the cache lookup and the
    # download ask about the same ref ("main", not "main/app.py")
    branch = github.resolve_ref(owner, name, ref or None)
    sha = github.head_sha(owner, name, branch)
    if sha:
        row = session.exec(select(RepoSnapshot).where(col(RepoSnapshot.sha) == sha, func.lower(RepoSnapshot.owner) == owner.lower(),
                                                      func.lower(RepoSnapshot.repo) == name.lower())).first()
        if row and (snap := load_snapshot(session, row.key)):
            return snap
    session.close()  # no database connection held while GitHub sends the archive
    snap = github.download(owner, name, branch)
    if not session.get(RepoSnapshot, snap.key):
        session.add(RepoSnapshot(key=snap.key, owner=snap.owner, repo=snap.repo, sha=snap.sha, ref=snap.ref,
                                 description=snap.description, file_count=len(snap.files), files=snap.pack()))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()  # another request stored the same commit first
    session.close()
    return remember(snap)


# Every step of a write is kept, so the waiting screen's file and search counts never shrink.
# A write is at most 40 rounds of a few tool calls; the lines are short.
PROGRESS_KEEP = 200


def progress_writer(project_id: str):
    """Records what Claude is doing, in its own short transaction, for the waiting screen."""

    def write(text: str) -> None:
        with Session(engine) as s:
            p = s.get(Project, project_id)
            if p:
                p.progress = [*(p.progress or [])[-(PROGRESS_KEEP - 1):], text]
                p.updated_at = now()  # a heartbeat: a write that's still reading isn't stale
                s.add(p)
                s.commit()

    return write


@app.post("/api/projects/{project_id}/write")
def write_project(project_id: str, session: SessionDep, owner: OwnerDep):
    """Claude writes the lesson. Runs on the person's click, never on page load."""
    project = owned_project(session, project_id, owner)
    expire_stale_write(session, project)
    if project.status == "writing":
        raise ApiError(409, "already_writing", "This lesson is already being written.")
    try:
        usage_id = limits.reserve(session, owner, project_id, "write", "anthropic", llm.model())
    except limits.LimitError as exc:
        if project.status != "ready":
            set_project(session, project_id, status="failed", error=exc.message)
        raise ApiError(429, "limit", exc.message) from exc

    # Claim the lesson in one statement, so two clicks can't start two paid writes.
    claimed = session.exec(
        update(Project)
        .where(col(Project.id) == project_id, col(Project.status) != "writing")
        .values(status="writing", error="", updated_at=now())
    ).rowcount
    session.commit()
    if not claimed:
        limits.settle(session, usage_id, ok=False, error="already_writing")
        raise ApiError(409, "already_writing", "This lesson is already being written.")

    project = session.get(Project, project_id)
    topic, notes, level, minutes, repo, ref = project.topic, project.notes, project.level, project.minutes, project.repo, project.repo_ref or ""
    voice_id = project.voice_id or tts.voice_id()
    session.close()  # don't hold a database connection while GitHub or Claude works
    progress = progress_writer(project_id)
    repo_sha, repo_name = "", repo
    try:
        if repo:
            set_project(session, project_id, progress=[f"Downloading github.com/{repo}"])
            session.close()
            snap = fetch_snapshot(session, repo, ref)
            repo_sha, repo_name = snap.sha, snap.name
            # The commit is saved with the new storyboard only when the write succeeds, so a
            # failed rewrite never points the old lesson at different code.
            set_project(session, project_id, progress=[f"Read {len(snap.files)} files from github.com/{snap.name}"])
            session.close()
            board, calls = llm.write_repo_lesson(snap, topic, level, minutes, progress)
        else:
            board, call = llm.write_storyboard(topic, notes, level, minutes)
            calls = [call]
    except github.RepoError as exc:
        settle_calls(session, usage_id, [], error=exc.code)  # cost nothing: the allowance comes back
        set_project(session, project_id, status="failed", error=exc.message)
        raise ApiError(exc.status, exc.code, exc.message) from exc
    except llm.AIError as exc:
        settle_calls(session, usage_id, exc.calls, error=exc.code)
        set_project(session, project_id, status="failed", error=exc.message)
        raise ApiError(exc.status, exc.code, exc.message) from exc
    except Exception as exc:
        # anything unplanned still ends the write, so the page doesn't wait ten minutes
        session.rollback()
        settle_calls(session, usage_id, [], error="write_failed")
        set_project(session, project_id, status="failed", error="Something went wrong while writing. Try again.")
        raise ApiError(500, "write_failed", "Something went wrong while writing. Try again.") from exc

    settle_calls(session, usage_id, calls)
    # Saved only if the lesson is still the one being written (a hand save is refused while
    # it's writing, so nothing newer can be overwritten), and the commit only together with
    # the storyboard written from it.
    values: dict[str, Any] = {"storyboard": board.model_dump(), "title": board.title, "voice_id": voice_id,
                              "status": "ready", "error": "", "updated_at": now()}
    if repo_sha:
        values.update(repo=repo_name, repo_sha=repo_sha)
    saved = session.exec(
        update(Project).where(col(Project.id) == project_id, col(Project.status) == "writing").values(**values)
    ).rowcount
    session.commit()
    if not saved:
        raise ApiError(409, "changed_meanwhile", "The lesson changed while Claude was writing it, so this version wasn't saved.")
    project = session.get(Project, project_id)
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
    prev_text = scenes[i - 1]["narration"] if i > 0 else ""
    next_text = scenes[i + 1]["narration"] if i + 1 < len(scenes) else ""

    # One request per narration pays ElevenLabs; another asking for the same words waits
    # here and then finds the clip the first one stored. The session is closed before
    # waiting, so waiters don't hold database connections the paying request needs.
    session.close()
    with clip_lock(h):
        if clip := session.get(Clip, h):
            return clip_out(clip)
        try:
            usage_id = limits.reserve(session, owner, project_id, "voice", "elevenlabs", model, characters=len(narration))
        except limits.LimitError as exc:
            raise ApiError(429, "limit", exc.message) from exc
        session.close()  # don't hold a database connection while ElevenLabs speaks
        try:
            spoken = tts.speak(narration, voice, model, prev_text, next_text)
        except tts.VoiceError as exc:
            limits.settle(session, usage_id, ok=False, characters=0, error=exc.code)
            raise ApiError(exc.status, exc.code, exc.message) from exc
        limits.settle(session, usage_id, ms=spoken.ms)
        return store_clip(session, Clip(hash=h, voice_id=voice, model_id=model, text=narration, audio=spoken.audio,
                                        words=spoken.words, duration=spoken.duration))


def store_clip(session: Session, clip: Clip) -> dict[str, Any]:
    h = clip.hash
    session.add(clip)
    try:
        session.commit()
    except IntegrityError:
        # Another server stored the same narration a moment ago: use that one.
        session.rollback()
        clip = session.get(Clip, h)
        if not clip:
            raise
    else:
        session.refresh(clip)
    return clip_out(clip)


_clip_locks: dict[str, threading.Lock] = {}
_clip_locks_guard = threading.Lock()


@contextmanager
def clip_lock(h: str):
    with _clip_locks_guard:
        lock = _clip_locks.setdefault(h, threading.Lock())
    with lock:
        yield
    with _clip_locks_guard:
        if not lock.locked():
            _clip_locks.pop(h, None)


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
    if project.status == "writing":
        raise ApiError(409, "being_written", "This lesson is being written. Edit it once it's done.")
    if (project.origin or "web") != "web":
        # Made by the person's own Claude: the server has no copy of local code to check edits
        # against, and editing here would put the AI cost on the site.
        raise ApiError(409, "edit_where_made", "This lesson was made by your own Claude. Ask it there for changes "
                       "(run /lesson again), or edit any scene by hand here.")
    board = Storyboard.model_validate(project.storyboard)
    started_from = project.updated_at
    notes = project.notes
    snap = load_snapshot(session, f"{project.repo}@{project.repo_sha}") if project.repo and project.repo_sha else None
    try:
        usage_id = limits.reserve(session, owner, project_id, "edit", "anthropic", llm.model())
    except limits.LimitError as exc:
        raise ApiError(429, "limit", exc.message) from exc
    session.close()  # don't hold a database connection while Claude edits
    try:
        outcome = llm.edit_storyboard(board, body.instruction.strip(), body.scene_id, notes, snap=snap)
    except llm.AIError as exc:
        settle_calls(session, usage_id, exc.calls, error=exc.code)
        raise ApiError(exc.status, exc.code, exc.message) from exc
    settle_calls(session, usage_id, outcome.calls)

    # Applied only if nothing was saved since the edit started, checked in the same UPDATE,
    # so two edits (or an edit and a hand save) can't silently erase each other.
    applied = session.exec(
        update(Project)
        .where(col(Project.id) == project_id, col(Project.updated_at) == started_from)
        .values(storyboard=outcome.board.model_dump(), title=outcome.board.title, updated_at=now())
    ).rowcount
    session.commit()
    if not applied:
        raise ApiError(409, "changed_meanwhile", "The lesson changed while Claude was editing it, so the edit wasn't applied. Ask again.")
    project = session.get(Project, project_id)
    return {"project": project_out(project, owner, voices_for(session, project)), "summary": outcome.summary, "changes": outcome.changes}


@app.get("/api/projects/{project_id}/usage")
def project_usage(project_id: str, session: SessionDep, owner: OwnerDep):
    """What this lesson has cost so far, in tokens and characters (for the cost analysis)."""
    project = owned_project(session, project_id, owner)
    rows = session.exec(select(Usage).where(Usage.project_id == project.id).order_by(Usage.created_at)).all()
    calls = []
    for r in rows:
        row = r.model_dump(mode="json")
        if r.provider == "anthropic" and r.cost_usd is None:
            row["cost_usd"] = llm.cost_usd(r.model, r.input_tokens, r.output_tokens, r.cache_write_tokens or 0, r.cache_read_tokens or 0)
        elif r.provider == "elevenlabs":
            row["credits"] = r.characters  # about one credit per character on eleven_multilingual_v2
        calls.append(row)
    return {"calls": calls}


# ---------------------------------------------------------------- lessons made elsewhere

MAX_IMPORT_BYTES = 300_000


def client_key(request: Request) -> str:
    """A stand-in for "who is this" when there's no browser id: a hash of the caller's address
    (the first hop Railway's proxy reports), so limits work without storing addresses."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return "addr:" + hashlib.sha256(ip.encode()).hexdigest()[:24]


def check_lesson_content(board: Storyboard, question: str = "") -> None:
    """Size and secret checks for a lesson whose text and code came from outside the server.
    Everything that will be shown is checked: the title, summary and question too."""
    if len(board.title) > 200 or len(board.summary) > 400:
        raise ApiError(422, "too_big", "The title must be under 200 characters and the summary under 400.")
    for label, text in (("The title", board.title), ("The summary", board.summary), ("The question", question)):
        if found := secrets_scan.find_secret(text):
            raise ApiError(422, "looks_like_a_secret", f"{label} seems to contain {found}. It wasn't saved.")
    for i, scene in enumerate(board.scenes, 1):
        fields = [scene.heading, scene.subheading, scene.narration, scene.code] + [f"{it.text} {it.detail}" for it in scene.items]
        if len(scene.narration) > 1200 or len(scene.heading) > 200 or len(scene.code) > 4000 or scene.code.count("\n") >= 14:
            raise ApiError(422, "too_big", f"Scene {i} is too long: keep narration under 1,200 characters and code to 14 lines.")
        for text in fields:
            if found := secrets_scan.find_secret(text):
                raise ApiError(422, "looks_like_a_secret",
                               f"Scene {i} seems to contain {found}. It wasn't saved; cite different lines or remove it.")


def public_base(request: Request) -> str:
    """This site's address as the caller reached it (https behind Railway's proxy)."""
    base = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto") == "https" and base.startswith("http://"):
        base = "https://" + base[len("http://"):]
    return base


def create_imported(session: Session, board: Storyboard, question: str, origin: str, who: str, base: str,
                    repo: str = "", repo_sha: str = "") -> dict[str, Any]:
    """Store a finished lesson made by someone's own Claude, owned by nobody until its
    one-time claim link is opened. Costs no AI; voicing waits for the owner to click Voice."""
    check_lesson_content(board, question)
    try:
        usage_id = limits.reserve(session, who, "-", "import", "none", origin)
    except limits.LimitError as exc:
        raise ApiError(429, "limit", exc.message) from exc
    token = secrets.token_urlsafe(24)
    project = Project(owner="", claim_hash=hashlib.sha256(token.encode()).hexdigest(), origin=origin,
                      topic=question, title=board.title, storyboard=board.model_dump(), status="ready",
                      voice_id=tts.voice_id(), repo=repo, repo_sha=repo_sha)
    session.add(project)
    session.commit()
    session.refresh(project)
    limits.settle(session, usage_id, project_id=project.id)
    return {"id": project.id, "url": f"{base}/l/{project.id}?claim={token}", "title": board.title}


class ImportIn(BaseModel):
    storyboard: dict[str, Any]
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
    # the public GitHub repository and commit the code came from, when there is one, for links
    repo: str = Field(default="", max_length=200, pattern=r"^$|^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    sha: str = Field(default="", pattern=r"^$|^[0-9a-f]{40}$")
    client: str = Field(default="", max_length=60)


@app.post("/api/import", status_code=201)
def import_lesson(body: ImportIn, request: Request, session: SessionDep):
    """A lesson from the /lesson skill: the person's own Claude Code researched their code, and
    the skill already filled every code scene from their files and refused secret files. Only
    the storyboard (with the cited lines) arrives here, never the repository."""
    try:
        board = normalize(Storyboard.model_validate(body.storyboard))
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ApiError(422, "invalid_storyboard", f"The lesson isn't valid: {'.'.join(str(p) for p in first['loc'])}: {first['msg']}") from exc
    return create_imported(session, board, body.question, "local", client_key(request), public_base(request),
                           repo=body.repo if body.sha else "", repo_sha=body.sha)


class ClaimIn(BaseModel):
    token: str = Field(min_length=10, max_length=100)


@app.post("/api/projects/{project_id}/claim")
def claim_project(project_id: str, body: ClaimIn, session: SessionDep, owner: OwnerDep):
    """The browser that opens a lesson's claim link first becomes its owner. The link works once."""
    project = load_project(session, project_id)
    if project.owner == owner:
        return project_out(project, owner, voices_for(session, project))
    if project.owner or not project.claim_hash:
        raise ApiError(409, "already_claimed", "This lesson already belongs to someone. You can still watch it.")
    if not hmac.compare_digest(project.claim_hash, hashlib.sha256(body.token.encode()).hexdigest()):
        raise ApiError(403, "bad_claim", "That claim link isn't valid for this lesson.")
    claimed = session.exec(
        update(Project).where(col(Project.id) == project_id, col(Project.owner) == "", col(Project.claim_hash) == project.claim_hash)
        .values(owner=owner, claim_hash="", updated_at=now())
    ).rowcount
    session.commit()
    if not claimed:
        raise ApiError(409, "already_claimed", "This lesson already belongs to someone. You can still watch it.")
    project = session.get(Project, project_id)
    session.refresh(project)
    return project_out(project, owner, voices_for(session, project))


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

