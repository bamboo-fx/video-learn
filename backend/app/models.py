"""Tables.

- Project: one lesson. Its storyboard is stored whole, as JSON.
- Clip: one voiced piece of narration. Keyed by a hash of (voice, model, text), so the
  same sentence is never paid for twice and editing one scene re-voices only that scene.
- RepoSnapshot: a GitHub repository's source files at one commit, for lessons about code.
- Usage: one row per paid call (Claude or ElevenLabs), for the cost-benefit analysis
  and for the daily spending limits.
"""

import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, LargeBinary
from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return secrets.token_urlsafe(8)


class Project(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    owner: str = Field(index=True, description="Random id the browser keeps; only the owner can edit.")
    topic: str
    notes: str = ""
    level: str = "intro"
    minutes: int = 3
    voice_id: str = ""
    title: str = ""
    status: str = "new"  # new | writing | ready | failed
    error: str = ""
    storyboard: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    # the codebase this lesson teaches ("owner/repo" at a commit), when it teaches one
    repo: str = ""
    repo_ref: str = ""  # a branch or tag from the pasted link; empty = the default branch
    repo_sha: str = ""
    # what Claude is doing right now while it writes ("Reading app/main.py"), newest last
    progress: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # where it was made: "web" (Claude on our server), "local" (the /lesson skill, from code on
    # the person's computer) or "connector" (Claude in claude.ai, from a public repository)
    origin: str = "web"
    # a lesson made outside the browser belongs to nobody until its one-time claim link is
    # opened; only a hash of the link's token is kept
    claim_hash: str = ""
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class RepoSnapshot(SQLModel, table=True):
    """A repository's source files at one commit, gzipped. Downloaded once per commit."""

    key: str = Field(primary_key=True)  # owner/repo@sha
    owner: str
    repo: str
    sha: str
    ref: str
    description: str = ""
    file_count: int = 0
    files: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(default_factory=now)


class Clip(SQLModel, table=True):
    hash: str = Field(primary_key=True)
    voice_id: str
    model_id: str
    text: str
    audio: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    words: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    duration: float = 0.0
    created_at: datetime = Field(default_factory=now)


class Usage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: str = Field(index=True)
    owner: str = Field(index=True)
    kind: str  # write | edit | voice
    requests: int = 1  # Claude requests in this write or edit (a repo lesson makes many)
    provider: str  # anthropic | elevenlabs
    model: str
    input_tokens: int = 0  # uncached input
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float | None = None  # Claude's price for this write or edit, summed per request
    characters: int = 0
    ms: int = 0
    ok: bool = True
    error: str = ""
    created_at: datetime = Field(default_factory=now, index=True)
