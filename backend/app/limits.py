"""Daily limits. The site is public and every lesson costs real money, so each browser
and the whole server get a daily allowance. Numbers come from the environment so they
can be raised for a demo without a code change."""

import os
import threading
from datetime import timedelta

from sqlalchemy import func, or_, text
from sqlmodel import Session, col, select

from app.models import Usage, now

_lock = threading.Lock()


class LimitError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def check(session: Session, owner: str, kind: str, characters: int = 0) -> str | None:
    """None if this call is allowed, otherwise a sentence saying why not."""
    since = now() - timedelta(days=1)

    def count(*where) -> int:
        # A failed Claude call still costs money when it used tokens, so it counts. A failure
        # that cost nothing (no key, unreachable) doesn't use up anyone's allowance.
        paid = or_(col(Usage.ok), col(Usage.input_tokens) > 0, col(Usage.output_tokens) > 0)
        return session.exec(select(func.count()).select_from(Usage).where(Usage.created_at >= since, paid, *where)).one()

    def chars(*where) -> int:
        return session.exec(select(func.coalesce(func.sum(Usage.characters), 0)).where(Usage.created_at >= since, Usage.ok, *where)).one()

    if kind == "write":
        if count(Usage.owner == owner, Usage.kind == "write") >= _int("LIMIT_WRITES_PER_BROWSER", 10):
            return "You've made the most lessons allowed in a day. Come back tomorrow, or edit one you have."
        if count(Usage.kind == "write") >= _int("LIMIT_WRITES_PER_DAY", 80):
            return "The site has made as many lessons today as it can afford. Try again tomorrow."
    elif kind == "edit":
        if count(Usage.owner == owner, Usage.kind == "edit") >= _int("LIMIT_EDITS_PER_BROWSER", 60):
            return "You've used today's AI edits. You can still edit every scene by hand."
        # a browser id is easy to change, so the site has its own ceiling too
        if count(Usage.kind == "edit") >= _int("LIMIT_EDITS_PER_DAY", 400):
            return "The site has made as many AI edits today as it can afford. You can still edit every scene by hand."
    elif kind == "voice":
        if chars(Usage.owner == owner, Usage.kind == "voice") + characters > _int("LIMIT_VOICE_CHARS_PER_BROWSER", 12000):
            return "You've used today's voice allowance. The lesson still plays with captions."
        if chars(Usage.kind == "voice") + characters > _int("LIMIT_VOICE_CHARS_PER_DAY", 40000):
            return "The site has used today's voice allowance. The lesson still plays with captions."
    return None


def reserve(session: Session, owner: str, project_id: str, kind: str, provider: str, model: str, characters: int = 0) -> int:
    """Check the allowance and claim a share of it in one step, before any paid call starts.

    The claim is a Usage row written now (it counts at once), and settle() fills in what the
    call really used. A lock (a Postgres advisory lock across servers, and a thread lock here)
    makes check-and-claim atomic, so requests running at the same time can't all pass against
    the same remaining allowance. Raises LimitError with a sentence when there's no room."""
    with _lock:
        if session.get_bind().dialect.name == "postgresql":
            session.exec(text("SELECT pg_advisory_xact_lock(190190)"))  # released at commit
        why = check(session, owner, kind, characters)
        if why:
            session.rollback()
            raise LimitError(why)
        row = Usage(project_id=project_id, owner=owner, kind=kind, provider=provider, model=model,
                    characters=characters, ok=True, error="pending")
        session.add(row)
        session.commit()
        return row.id  # type: ignore[return-value]


def settle(session: Session, usage_id: int, **fields) -> None:
    """Record what a reserved call actually used. A failure that cost nothing (ok=False with
    no tokens) stops counting toward the allowance."""
    row = session.get(Usage, usage_id)
    if row is None:
        return
    for k, v in {"error": "", **fields}.items():
        setattr(row, k, v)
    session.add(row)
    session.commit()
