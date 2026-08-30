"""The watcher over a machine this process cannot see.

The distinction that makes this alert worth reading: **silence is only a fault
when there is work waiting.** A worker idle overnight because nobody filmed
anything is not broken, and an alert that fires on that is an alert people stop
opening — which this project has already paid for once.

The delivery invariant is the one from v0.54.4 and it is not re-derived here: a
state is only consumed when the mail was accepted, so an alert nobody could
send is retried rather than forgotten.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory
from app.models import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentStatus,
    RenderJob,
    RenderJobKind,
)
from app.models.monitor_state import MonitorState
from app.services import render_watch
from app.services.render_watch import KEY, record_heartbeat, run_render_watch_tick

ORG = 1


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — render watch tests need live Postgres")
    return url


@pytest.fixture(autouse=True)
async def _clean(database_url: str):
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM render_jobs"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.execute(text("DELETE FROM monitor_state WHERE key = :k"), {"k": KEY})
        await db.commit()
    yield
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM render_jobs"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.execute(text("DELETE FROM monitor_state WHERE key = :k"), {"k": KEY})
        await db.commit()


async def _queue_a_job() -> None:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.RECORDED,
            language=ContentLanguage.EN,
            status=ContentStatus.DRAFT,
            hook="A clip",
            media_path="f" * 32 + ".mp4",
        )
        db.add(piece)
        await db.commit()
        db.add(RenderJob(org_id=ORG, piece_id=piece.id, kind=RenderJobKind.SUBTITLE_A))
        await db.commit()


async def _row() -> MonitorState:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(select(MonitorState).where(MonitorState.key == KEY))
        ).scalar_one()


async def _age_the_heartbeat(hours: float) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE monitor_state SET last_heartbeat_at = :t WHERE key = :k"),
            {"t": datetime.now(UTC) - timedelta(hours=hours), "k": KEY},
        )
        await db.commit()


class _Mailbox:
    def __init__(self, accept: bool = True) -> None:
        self.accept = accept
        self.sent: list[str] = []

    async def __call__(self, subject: str, body: str) -> bool:
        self.sent.append(subject)
        return self.accept


@pytest.mark.asyncio
async def test_an_idle_worker_with_an_empty_queue_is_not_a_fault(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The distinction this whole watcher exists to make. Nobody filmed
    anything today; that is not an outage."""
    mail = _Mailbox()
    monkeypatch.setattr(render_watch, "send_operator_alert", mail)
    await record_heartbeat("rog-1")
    await _age_the_heartbeat(30)  # silent for a day and a bit
    await run_render_watch_tick()
    assert mail.sent == []
    assert (await _row()).state == "ok"


@pytest.mark.asyncio
async def test_silence_with_work_waiting_is_reported_once(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    mail = _Mailbox()
    monkeypatch.setattr(render_watch, "send_operator_alert", mail)
    await record_heartbeat("rog-1")
    await run_render_watch_tick()  # baseline: ok
    await _queue_a_job()
    await _age_the_heartbeat(5)

    await run_render_watch_tick()
    assert len(mail.sent) == 1
    # And the second tick in the same state says nothing. Six correct alerts
    # about the same thing are how people learn to ignore the seventh.
    await run_render_watch_tick()
    assert len(mail.sent) == 1


@pytest.mark.asyncio
async def test_an_alert_that_could_not_be_sent_is_retried(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fault nobody heard about is not a fault that was reported."""
    mail = _Mailbox(accept=False)
    monkeypatch.setattr(render_watch, "send_operator_alert", mail)
    await record_heartbeat("rog-1")
    await run_render_watch_tick()
    await _queue_a_job()
    await _age_the_heartbeat(5)

    await run_render_watch_tick()
    await run_render_watch_tick()
    assert len(mail.sent) == 2
    # Unconsumed, because it never arrived.
    assert (await _row()).alerted_state == "ok"


@pytest.mark.asyncio
async def test_recovery_is_reported_too(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    mail = _Mailbox()
    monkeypatch.setattr(render_watch, "send_operator_alert", mail)
    await record_heartbeat("rog-1")
    await run_render_watch_tick()
    await _queue_a_job()
    await _age_the_heartbeat(5)
    await run_render_watch_tick()

    await record_heartbeat("rog-1")
    await run_render_watch_tick()
    assert len(mail.sent) == 2
    assert (await _row()).state == "ok"


@pytest.mark.asyncio
async def test_a_worker_that_never_checked_in_with_work_waiting_is_a_fault(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never installed and dead look the same from here, and both mean the
    clips are not moving."""
    mail = _Mailbox()
    monkeypatch.setattr(render_watch, "send_operator_alert", mail)
    await run_render_watch_tick()  # baseline with an empty queue: ok
    await _queue_a_job()
    await run_render_watch_tick()
    assert len(mail.sent) == 1


@pytest.mark.asyncio
async def test_the_budget_stops_a_flapping_worker(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It shares a mail quota with the replies clients are waiting on."""
    mail = _Mailbox()
    monkeypatch.setattr(render_watch, "send_operator_alert", mail)
    await record_heartbeat("rog-1")
    await run_render_watch_tick()
    await _queue_a_job()

    for _ in range(6):
        await _age_the_heartbeat(5)
        await run_render_watch_tick()
        await record_heartbeat("rog-1")
        await run_render_watch_tick()
    assert len(mail.sent) <= 3
