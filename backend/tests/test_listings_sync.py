"""DB-backed tests for RESO incremental replication (_sync_reso).

Covers the cursor advance, status reconciliation (delta-delete), and per-page
crash-safety. The HTTP feed is faked by monkeypatching `_fetch_reso_pages` to yield
controlled pages of ListingDTO, so no network/token is needed. Skips without a
DATABASE_URL (Postgres) just like the other DB tests.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Property, PropertySource, PropertyStatus, SyncState
from app.services import listings as L
from app.services.listings import ListingDTO


@pytest.fixture
def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — DB test")
    return url


def _sessionmaker(url):
    engine = create_async_engine(url, future=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _reset(Session) -> None:
    async with Session() as s:
        await s.execute(delete(Property).where(Property.source == PropertySource.RESO))
        await s.execute(delete(SyncState).where(SyncState.source == "reso"))
        await s.commit()


def _dto(external_id, status, modified_at, *, price="500000", zone="Aurora"):
    return ListingDTO(
        external_id=external_id,
        title=f"Home {external_id}",
        price=Decimal(price),
        status=status,
        zone=zone,
        source_modified_at=modified_at,
        raw={"listing_type": "sale"},
    )


async def test_reso_cursor_advances_and_reconciles_status(monkeypatch, database_url):
    engine, Session = _sessionmaker(database_url)
    try:
        await _reset(Session)
        t1 = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)

        async def pages_v1(*a, **k):
            yield [_dto("RX1", PropertyStatus.ACTIVE, t1)]

        monkeypatch.setattr(L, "_fetch_reso_pages", pages_v1)
        async with Session() as s:
            res = await L._sync_reso(s, full=False)
        assert (res["created"], res["updated"]) == (1, 0)

        async with Session() as s:
            st = (
                await s.execute(select(SyncState).where(SyncState.source == "reso"))
            ).scalar_one()
            assert st.cursor_modified_at == t1
            assert st.last_error is None
            p = (
                await s.execute(
                    select(Property).where(
                        Property.source == PropertySource.RESO,
                        Property.external_id == "RX1",
                    )
                )
            ).scalar_one()
            assert p.status is PropertyStatus.ACTIVE

        # same listing goes Closed → SOLD; cursor advances to t2 (delta-delete)
        t2 = datetime(2026, 7, 2, 9, 0, 0, tzinfo=UTC)

        async def pages_v2(*a, **k):
            yield [_dto("RX1", PropertyStatus.SOLD, t2)]

        monkeypatch.setattr(L, "_fetch_reso_pages", pages_v2)
        async with Session() as s:
            res = await L._sync_reso(s, full=False)
        assert (res["created"], res["updated"]) == (0, 1)

        async with Session() as s:
            p = (
                await s.execute(
                    select(Property).where(
                        Property.source == PropertySource.RESO,
                        Property.external_id == "RX1",
                    )
                )
            ).scalar_one()
            assert p.status is PropertyStatus.SOLD
            st = (
                await s.execute(select(SyncState).where(SyncState.source == "reso"))
            ).scalar_one()
            assert st.cursor_modified_at == t2
    finally:
        await _reset(Session)
        await engine.dispose()


async def test_reso_crash_safety_commits_per_page(monkeypatch, database_url):
    engine, Session = _sessionmaker(database_url)
    try:
        await _reset(Session)
        t1 = datetime(2026, 7, 3, 8, 0, 0, tzinfo=UTC)

        async def pages_crash(*a, **k):
            yield [_dto("RC1", PropertyStatus.ACTIVE, t1, zone="Denver")]
            raise RuntimeError("boom mid-run")

        monkeypatch.setattr(L, "_fetch_reso_pages", pages_crash)
        async with Session() as s:
            with pytest.raises(RuntimeError):
                await L._sync_reso(s)

        # page 1 durably committed; cursor at t1; error recorded
        async with Session() as s:
            p = (
                await s.execute(
                    select(Property).where(
                        Property.source == PropertySource.RESO,
                        Property.external_id == "RC1",
                    )
                )
            ).scalar_one_or_none()
            assert p is not None
            st = (
                await s.execute(select(SyncState).where(SyncState.source == "reso"))
            ).scalar_one()
            assert st.cursor_modified_at == t1
            assert st.last_error is not None

        # resume: next run picks up the next page and clears the error
        t2 = datetime(2026, 7, 4, 8, 0, 0, tzinfo=UTC)

        async def pages_resume(*a, **k):
            yield [_dto("RC2", PropertyStatus.ACTIVE, t2, zone="Denver")]

        monkeypatch.setattr(L, "_fetch_reso_pages", pages_resume)
        async with Session() as s:
            res = await L._sync_reso(s)
        assert res["created"] == 1

        async with Session() as s:
            st = (
                await s.execute(select(SyncState).where(SyncState.source == "reso"))
            ).scalar_one()
            assert st.cursor_modified_at == t2
            assert st.last_error is None
    finally:
        await _reset(Session)
        await engine.dispose()
