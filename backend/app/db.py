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

    eng = eng or engine
    SQLModel.metadata.create_all(eng)
    add_missing_columns(eng)


def add_missing_columns(eng) -> None:
    """create_all makes new tables but never changes existing ones. When a model gains a
    column, add it to the live table here (nullable, so old rows stay valid). Additive only:
    this never drops or alters anything."""
    from sqlalchemy import inspect, text

    insp = inspect(eng)
    with eng.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(dialect=eng.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
