"""Async SQLAlchemy 2.x setup — engine, session, FastAPI dep, declarative Base.

Patterns adapted from Eko-AI-Business-Automation's backend/app/db/base.py but simplified:
no RLS multi-tenant workspace (1 deploy = 1 inmobiliaria), no Celery proxy session.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import get_settings
from app.services.tenant_context import get_org_id


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
_bypass_engine: AsyncEngine | None = None
_BypassSessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazy singleton — avoids creating the engine at import time (useful for tests / CLIs)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.DATABASE_URL_APP or settings.DATABASE_URL,
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


def get_bypass_engine() -> AsyncEngine:
    """Engine for the three callers that legitimately act outside one org.

    Login resolves a user's org *before* an org is known, and the background
    workers sweep every org. Both would see zero rows under default-deny RLS.
    The superuser panel is the third.

    Everything else must use get_engine(). Reaching for this to "make a query
    work" removes the tenant boundary for that query.
    """
    global _bypass_engine
    if _bypass_engine is None:
        settings = get_settings()
        # Falls back to DATABASE_URL, which owns the tables. That only bypasses
        # RLS while the owner is a superuser — and every tenant table is FORCE,
        # so a non-superuser owner is still subject to the policies. In that
        # configuration this engine stops bypassing and the failure is silent:
        # run_for_every_org would sweep zero orgs and every login would be
        # denied, with nothing in the logs. See the startup assertion in main.py.
        _bypass_engine = create_async_engine(
            settings.DATABASE_URL_BYPASS or settings.DATABASE_URL,
            echo=settings.DEBUG and settings.APP_ENV == "development",
            future=True,
            pool_pre_ping=True,
        )
    return _bypass_engine


def get_bypass_session_factory() -> async_sessionmaker[AsyncSession]:
    global _BypassSessionLocal
    if _BypassSessionLocal is None:
        _BypassSessionLocal = async_sessionmaker(
            get_bypass_engine(),
            expire_on_commit=False,
            autoflush=False,
            class_=AsyncSession,
            info={"bypass_rls": True},
        )
    return _BypassSessionLocal


@event.listens_for(Session, "before_flush")
def _stamp_org_id(session: Session, flush_context: Any, instances: Any) -> None:
    """Fill in `org_id` on new rows from the acting org.

    Without this every INSERT would have to remember to set the column, and the
    one that forgot would be rejected by the RLS WITH CHECK at runtime — correct,
    but only discovered in production. Stamping here means callers cannot forget,
    and the policy stays as the backstop rather than the primary mechanism.

    An explicit value is never overwritten: the workers legitimately write into
    a specific org while iterating many of them.
    """
    if session.info.get("bypass_rls"):
        return
    org_id = get_org_id()
    if org_id is None:
        return
    for obj in session.new:
        if hasattr(type(obj), "org_id") and getattr(obj, "org_id", None) is None:
            obj.org_id = org_id


@event.listens_for(Session, "after_begin")
def _inject_org_id(session: Session, transaction: Any, connection: Any) -> None:
    """Stamp the acting org onto every transaction, for the RLS policies to read.

    `after_begin` rather than session creation because `set_config(..., true)` is
    transaction-local: it is discarded at COMMIT. Flows here commit repeatedly
    inside one request — conversation.py commits five times, listings.py four —
    so a value set once at session open would silently vanish after the first
    one and every later statement would run with no org, seeing nothing.

    Parameterised, never interpolated: the org id reaches this from a token.
    """
    if connection.engine.url.get_backend_name() != "postgresql":
        return
    if session.info.get("bypass_rls"):
        return
    org_id = get_org_id()
    connection.execute(
        text("SELECT set_config('app.current_org_id', :v, true)"),
        {"v": "" if org_id is None else str(org_id)},
    )


async def first_or_create(db: AsyncSession, stmt: Any, build: Callable[[], Any]) -> Any:
    """Return the row `stmt` selects, creating it once if it is not there yet.

    The plain read-then-insert loses data here, and loses it silently. Two
    inbound messages arriving together both see nothing, both insert, and one
    loses the unique index — but the loser's IntegrityError takes down the
    *whole* transaction, which by then also holds a brand-new lead, its
    conversation and the message itself. The webhook handler then catches that
    error, reads it as an idempotent duplicate, and answers 200, so the provider
    never retries and the lead is gone with a log line that says nothing is
    wrong. Four concurrent first-contacts to a fresh tenant lost three leads
    exactly this way.

    A savepoint keeps the failure to the insert, and the loser adopts the
    winner's row. Postgres blocks the second insert until the first transaction
    resolves, so by the time the violation surfaces the winner is committed and
    visible to the re-read under READ COMMITTED.
    """
    existing = (await db.execute(stmt)).scalars().first()
    if existing is not None:
        return existing
    try:
        async with db.begin_nested():
            created = build()
            db.add(created)
            await db.flush()
        return created
    except IntegrityError:
        found = (await db.execute(stmt)).scalars().first()
        if found is None:
            # Not the race, then — some other constraint. Let it surface rather
            # than turning an unexplained failure into a missing row.
            raise
        return found


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
    global _engine, _SessionLocal, _bypass_engine, _BypassSessionLocal
    if _engine is not None:
        await _engine.dispose()
    if _bypass_engine is not None:
        await _bypass_engine.dispose()
    _engine = None
    _SessionLocal = None
    _bypass_engine = None
    _BypassSessionLocal = None


async def get_bypass_db() -> AsyncIterator[AsyncSession]:
    """Session that ignores RLS. See get_bypass_engine for who may use it."""
    session = get_bypass_session_factory()()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


__all__: list[str] = [
    "Base",
    "get_engine",
    "get_session_factory",
    "get_db",
    "dispose_engine",
    "pg_enum",
]


_ = Any  # keep typing imports stable across editors
