"""A lesson's history: every version of its storyboard, like commits on a branch.

A version is the whole storyboard at one moment, who made it, and what changed since the
one before. Nothing is ever edited out of the history: going back to an old version adds a
new version on top (a revert, not a reset), so that can be undone too.

When versions are made:
- Claude writes or rewrites the lesson, or makes an AI edit: one version each.
- Hand edits save every second while someone types, which would be hundreds of versions,
  so hand saves within a few minutes of each other fold into one (by everyone editing in
  that stretch, like a commit with co-authors).
- Someone names the current state on purpose ("before the review"): that version is kept
  apart and never folded into or pruned.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import defer
from sqlmodel import Session, col, select

from app.merge import LESSON_FIELDS, SCENE_FIELDS
from app.models import Version, now

FOLD = timedelta(minutes=10)  # a hand save this soon after the last one joins its version
FOLD_AT_MOST = timedelta(hours=1)  # ...but a long sitting still leaves a version every hour
KEEP = 200  # versions per lesson; the oldest unnamed ones go first


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def diff(old: dict[str, Any] | None, new: dict[str, Any]) -> list[dict[str, Any]]:
    """What changed between two storyboards, for the history list: which scenes were added,
    removed or changed (and which parts of them), and whether the order changed."""
    if old is None:
        return []
    changes: list[dict[str, Any]] = []
    lesson = [word for field, word in LESSON_FIELDS.items() if old.get(field) != new.get(field)]
    if lesson:
        changes.append({"kind": "lesson", "scene_id": "", "heading": "", "fields": lesson})
    before = {s["id"]: s for s in old.get("scenes", [])}
    after = {s["id"]: s for s in new.get("scenes", [])}
    for sid, scene in after.items():
        if sid not in before:
            changes.append({"kind": "added", "scene_id": sid, "heading": scene["heading"], "fields": []})
            continue
        fields = [word for field, word in SCENE_FIELDS.items() if before[sid].get(field) != scene.get(field)]
        if fields:
            changes.append({"kind": "changed", "scene_id": sid, "heading": scene["heading"], "fields": fields})
    for sid, scene in before.items():
        if sid not in after:
            changes.append({"kind": "removed", "scene_id": sid, "heading": scene["heading"], "fields": []})
    if [i for i in before if i in after] != [i for i in after if i in before]:
        changes.append({"kind": "reordered", "scene_id": "", "heading": "", "fields": []})
    return changes


def latest(session: Session, project_id: str) -> Version | None:
    return session.exec(select(Version).where(Version.project_id == project_id).order_by(col(Version.id).desc()).limit(1)).first()


def _before(session: Session, version: Version) -> Version | None:
    return session.exec(select(Version).where(Version.project_id == version.project_id, col(Version.id) < version.id)
                        .order_by(col(Version.id).desc()).limit(1)).first()


def _authors(have: list[str], author: str) -> list[str]:
    return have if not author or author in have else [*have, author]


def record(session: Session, project_id: str, board: dict[str, Any], *, kind: str, message: str = "", author: str = "",
           repo_sha: str = "", before: dict[str, Any] | None = None) -> Version | None:
    """Add the lesson's new storyboard to its history. Doesn't commit: the caller saves the
    version in the same transaction as the lesson, so the two can't disagree.

    `before` is the storyboard this change replaced. A lesson from before there was a
    history has no versions yet, so its old storyboard becomes the first one, and the
    first change to it can be undone."""
    last = latest(session, project_id)
    if last is None and before is not None and before != board:
        last = Version(project_id=project_id, number=1, kind="start", message="Where the history starts",
                       storyboard=before, title=before.get("title", ""), repo_sha=repo_sha)
        session.add(last)
        session.flush()
    if last is not None and last.storyboard == board:
        return last  # a save that changed nothing isn't a version
    t = now()
    if (kind == "hand" and last is not None and last.kind == "hand" and not last.name
            and t - _aware(last.updated_at) < FOLD and t - _aware(last.created_at) < FOLD_AT_MOST):
        parent = _before(session, last)
        if parent is not None and parent.storyboard == board:
            # the edits in this stretch were undone by hand: there's nothing left to record
            session.delete(last)
            return parent
        last.storyboard = board
        last.title = board.get("title", "")
        last.authors = _authors(last.authors or [], author)
        last.changes = diff(parent.storyboard if parent else None, board)
        last.updated_at = t
        session.add(last)
        return last
    version = Version(project_id=project_id, number=(last.number + 1 if last else 1), kind=kind, message=message,
                      authors=_authors([], author), storyboard=board, title=board.get("title", ""), repo_sha=repo_sha,
                      changes=diff(last.storyboard if last else None, board))
    session.add(version)
    session.flush()
    _prune(session, project_id)
    return version


def _prune(session: Session, project_id: str) -> None:
    ids = session.exec(select(Version.id).where(Version.project_id == project_id, col(Version.name) == "")
                       .order_by(col(Version.id).desc()).offset(KEEP)).all()
    for version_id in ids:
        if row := session.get(Version, version_id):
            session.delete(row)


def name_current(session: Session, project_id: str, board: dict[str, Any], name: str, author: str, repo_sha: str) -> Version:
    """Keep the lesson as it is now under a name someone chose. Doesn't commit."""
    last = latest(session, project_id)
    if last is None or last.storyboard != board:
        last = Version(project_id=project_id, number=(last.number + 1 if last else 1), kind="hand",
                       storyboard=board, title=board.get("title", ""), repo_sha=repo_sha,
                       changes=diff(last.storyboard if last else None, board))
    last.name = name
    last.authors = _authors(last.authors or [], author)
    session.add(last)
    session.flush()
    return last


def listing(session: Session, project_id: str, limit: int = 100) -> list[Version]:
    """The newest versions, without their storyboards (the list doesn't show them)."""
    return list(session.exec(select(Version).where(Version.project_id == project_id).options(defer(Version.storyboard))  # type: ignore[arg-type]
                             .order_by(col(Version.id).desc()).limit(limit)).all())


def meta(version: Version, current: bool = False) -> dict[str, Any]:
    """A version without its storyboard, for the list."""
    return {
        "id": version.id,
        "number": version.number,
        "kind": version.kind,
        "name": version.name or "",
        "message": version.message or "",
        "authors": version.authors or [],
        "changes": version.changes or [],
        "current": current,
        "created_at": _aware(version.created_at).isoformat(),
        "updated_at": _aware(version.updated_at).isoformat(),
    }
