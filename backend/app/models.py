"""Tables.

- Project: one lesson. Its storyboard is stored whole, as JSON.
- Clip: one voiced piece of narration. Keyed by a hash of (voice, model, text), so the
  same sentence is never paid for twice and editing one scene re-voices only that scene.
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
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


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
    provider: str  # anthropic | elevenlabs
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    characters: int = 0
    ms: int = 0
    ok: bool = True
    error: str = ""
    created_at: datetime = Field(default_factory=now, index=True)
