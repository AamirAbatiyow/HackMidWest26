"""SQLAlchemy 2.x engine/session helpers. Works with Managed Postgres, local Docker, or sqlite in tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from hm_storage.settings import get_storage_settings


class Base(DeclarativeBase):
    """Declarative base for project models: `class Invoice(Base): __tablename__ = ...`."""


def make_engine(url: str | None = None, **kwargs: object) -> Engine:
    url = url or get_storage_settings().database_url
    if url.startswith("postgresql"):
        kwargs.setdefault("pool_pre_ping", True)
        kwargs.setdefault("pool_size", 5)
    return create_engine(url, **kwargs)  # type: ignore[arg-type]


@lru_cache
def get_engine() -> Engine:
    return make_engine()


def make_sessionmaker(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on error."""
    session = make_sessionmaker(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping(engine: Engine | None = None) -> bool:
    """Readiness check for `create_app(readiness_checks={"db": ping})`."""
    with (engine or get_engine()).connect() as conn:
        conn.execute(text("SELECT 1"))
    return True


def create_all(engine: Engine | None = None) -> None:
    """Hackathon-speed schema management. Swap for Alembic only if migrations become painful."""
    Base.metadata.create_all(engine or get_engine())


def enable_pgvector(engine: Engine | None = None) -> None:
    """Run once against Postgres (needs the `pgvector` extension available, e.g. pgvector/pgvector image)."""
    with (engine or get_engine()).begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
