"""Buffer refusing the token is told to the operator, not to a log.

26-sep to 3-oct 2026: five days of 401 "Access token is not valid", one
WARNING every fifteen minutes, nobody told. The queue inside Buffer kept
posting, so the accounts looked alive while eight approved pieces sat unsent.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory
from app.models.monitor_state import MonitorState
from app.services import buffer_publisher, buffer_watch
from app.services.buffer_watch import KEY, record_answer, run_buffer_watch_tick

T0 = datetime(2026, 9, 26, 14, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_streak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(buffer_watch, "_refused_since", None)


def test_one_refusal_is_not_yet_an_alert() -> None:
    record_answer(401, now=T0)
    assert buffer_watch.status(T0 + timedelta(minutes=5)) == "ok"
    assert buffer_watch.status(T0 + buffer_watch.REFUSED_FOR) == "refused"


def test_the_streak_starts_at_the_first_refusal() -> None:
    record_answer(401, now=T0)
    record_answer(401, now=T0 + timedelta(minutes=15))
    assert buffer_watch.refused_since() == T0


def test_an_accepted_call_ends_the_streak() -> None:
    record_answer(401, now=T0)
    record_answer(200, now=T0 + timedelta(minutes=15))
    assert buffer_watch.refused_since() is None
    assert buffer_watch.status(T0 + timedelta(days=1)) == "ok"


def test_a_quota_refusal_is_not_a_token_refusal() -> None:
    """429 has its own brake in `_graphql`; it says nothing about the token."""
    record_answer(429, now=T0)
    assert buffer_watch.refused_since() is None
    record_answer(401, now=T0)
    record_answer(429, now=T0 + timedelta(minutes=15))
    assert buffer_watch.refused_since() == T0


@pytest.mark.asyncio
async def test_graphql_reports_what_buffer_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [
        httpx.Response(
            401,
            json={"errors": [{"message": "Access token is not valid",
                              "extensions": {"code": "UNAUTHENTICATED"}}]},
        ),
        httpx.Response(200, json={"data": {}}),
    ]
    real = httpx.AsyncClient

    def _client(**kw):
        return real(transport=httpx.MockTransport(lambda request: answers.pop(0)), **kw)

    monkeypatch.setattr(buffer_publisher.httpx, "AsyncClient", _client)
    monkeypatch.setattr(buffer_publisher, "_quota_remaining", None)

    with pytest.raises(buffer_publisher.BufferRefused):
        await buffer_publisher._graphql("query { x }", {})
    assert buffer_watch.refused_since() is not None

    await buffer_publisher._graphql("query { x }", {})
    assert buffer_watch.refused_since() is None


# --- the alert itself: needs the monitor_state table -------------------------


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — buffer watch tests need live Postgres")
    return url


@pytest.fixture
async def _clean(database_url: str):
    async def _wipe() -> None:
        async with get_bypass_session_factory()() as db:
            await db.execute(text("DELETE FROM monitor_state WHERE key = :k"), {"k": KEY})
            await db.commit()

    await _wipe()
    yield
    await _wipe()


async def _row() -> MonitorState:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(select(MonitorState).where(MonitorState.key == KEY))
        ).scalar_one()


class _Mailbox:
    def __init__(self, accept: bool = True) -> None:
        self.accept = accept
        self.sent: list[tuple[str, str]] = []

    async def __call__(self, subject: str, body: str) -> bool:
        self.sent.append((subject, body))
        return self.accept


@pytest.mark.asyncio
async def test_a_refused_token_is_reported_once(_clean, monkeypatch: pytest.MonkeyPatch) -> None:
    mail = _Mailbox()
    monkeypatch.setattr(buffer_watch, "send_operator_alert", mail)
    await run_buffer_watch_tick(now=T0)  # baseline: ok

    record_answer(401, now=T0)
    await run_buffer_watch_tick(now=T0 + timedelta(minutes=5))
    assert mail.sent == []  # one pass is not a streak

    await run_buffer_watch_tick(now=T0 + timedelta(minutes=20))
    await run_buffer_watch_tick(now=T0 + timedelta(minutes=25))
    assert len(mail.sent) == 1
    subject, body = mail.sent[0]
    assert "Buffer is refusing the access token" in subject
    assert "2026-09-26 14:30 UTC" in body
    assert "dhs-buffer-token.sh" in body
    assert (await _row()).alerted_state == "refused"


@pytest.mark.asyncio
async def test_a_refusal_that_lasts_is_repeated_once_a_day(
    _clean, monkeypatch: pytest.MonkeyPatch
) -> None:
    mail = _Mailbox()
    monkeypatch.setattr(buffer_watch, "send_operator_alert", mail)
    await run_buffer_watch_tick(now=T0)
    record_answer(401, now=T0)
    await run_buffer_watch_tick(now=T0 + timedelta(minutes=20))
    await run_buffer_watch_tick(now=T0 + timedelta(hours=23))
    assert len(mail.sent) == 1
    await run_buffer_watch_tick(now=T0 + timedelta(hours=24, minutes=25))
    assert len(mail.sent) == 2


@pytest.mark.asyncio
async def test_recovery_is_reported(_clean, monkeypatch: pytest.MonkeyPatch) -> None:
    mail = _Mailbox()
    monkeypatch.setattr(buffer_watch, "send_operator_alert", mail)
    await run_buffer_watch_tick(now=T0)
    record_answer(401, now=T0)
    await run_buffer_watch_tick(now=T0 + timedelta(minutes=20))
    record_answer(200, now=T0 + timedelta(minutes=30))
    await run_buffer_watch_tick(now=T0 + timedelta(minutes=35))
    assert [s for s, _ in mail.sent][-1] == "Buffer accepts the token again"
    assert (await _row()).state == "ok"


@pytest.mark.asyncio
async def test_an_alert_that_could_not_be_sent_is_retried(
    _clean, monkeypatch: pytest.MonkeyPatch
) -> None:
    mail = _Mailbox(accept=False)
    monkeypatch.setattr(buffer_watch, "send_operator_alert", mail)
    await run_buffer_watch_tick(now=T0)
    record_answer(401, now=T0)
    await run_buffer_watch_tick(now=T0 + timedelta(minutes=20))
    await run_buffer_watch_tick(now=T0 + timedelta(minutes=25))
    assert len(mail.sent) == 2
    assert (await _row()).alerted_state == "ok"
