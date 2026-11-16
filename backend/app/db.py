"""Database connection. Postgres in production (Railway sets DATABASE_URL), SQLite locally."""

import os
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine


def database_url() -> str:
    url = os.environ.get("DATABASE_URL") or "sqlite:///./video-learn.db"
    # Railway hands out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str | None = None):
    url = url or database_url()
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


engine = make_engine()


def init_db(eng=None) -> None:
    from app import models  # noqa: F401  (registers the tables)

    SQLModel.metadata.create_all(eng or engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
