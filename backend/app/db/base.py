"""Async SQLAlchemy 2.x setup — engine, session, FastAPI dep, declarative Base.

Patterns adapted from Eko-AI-Business-Automation's backend/app/db/base.py but simplified:
no RLS multi-tenant workspace (1 deploy = 1 inmobiliaria), no Celery proxy session.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import Enum as SqlEnum
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models. Alembic autogenerate scans Base.metadata."""

    pass


def pg_enum(enum_cls: type, *, name: str) -> SqlEnum:
    """SQLAlchemy Enum column that uses the enum members' `.value` (lowercase)
    as the Postgres enum members, NOT the Python NAME (which is UPPERCASE by
    convention). Without this, SQLAlchemy serializes `LeadStatus.NEW` as `"NEW"`
    but the Postgres type only accepts `"new"` (the value we declared in the
    migration). Always wrap str-enums with this helper.
    """
    return SqlEnum(enum_cls, name=name, values_callable=lambda x: [e.value for e in x])


_engine: AsyncEngine | None = None
_SessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazy singleton — avoids creating the engine at import time (useful for tests / CLIs)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.DEBUG and settings.APP_ENV == "development",
            future=True,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            autoflush=False,
            class_=AsyncSession,
        )
    return _SessionLocal


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Yields a session, rolls back on exception, always closes."""
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Call from app shutdown hooks or test teardown to release pool."""
    global _engine, _SessionLocal
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _SessionLocal = None


__all__: list[str] = [
    "Base",
    "get_engine",
    "get_session_factory",
    "get_db",
    "dispose_engine",
    "pg_enum",
]


_ = Any  # keep typing imports stable across editors
