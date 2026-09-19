"""Sending the breakdown: when it goes, when it does not, and what it leaves behind.

The wording and the arithmetic are held in `test_calculator_breakdown_email.py`,
which needs no database. This file is about the decisions around the send — the
opt-out, the missing postal address, and the row in the lead's file — and drives
them against live Postgres.

The state this ships in is **dark**: with `POSTAL_ADDRESS` unset nothing is sent
and a log line says so. That is a tested behaviour here, not an accident.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.models.lead import Lead
from app.services.calculator import build_snapshot
from app.services.calculator_email import send_calculator_breakdown
from app.services.tenant_context import set_org_id

ORG = 1
MARK = "%@breakdown.test"
ADDRESS = "123 Test Ave Ste 1, Denver, CO 80200"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _fresh_settings() -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _seed(email: str, *, snapshot: dict | None = None, opted_out: bool = False) -> int:
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG,
            phone=f"+1988{os.urandom(3).hex()}",
            email=email,
            calculator_snapshot=snapshot,
        )
        db.add(lead)
        await db.flush()
        if opted_out:
            from datetime import UTC, datetime

            lead.opted_out_at = datetime.now(UTC)
        await db.commit()
        return int(lead.id)


async def _messages(lead_id: int) -> list[dict]:
    async with get_bypass_session_factory()() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT m.subject, m.internal, m.delivery_status, m.external_id, "
                    "m.send_attempts, m.fair_housing_flags, c.channel "
                    "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                    "WHERE c.lead_id = :i ORDER BY m.id"
                ),
                {"i": lead_id},
            )
        ).mappings().all()
        return [dict(r) for r in rows]


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads WHERE email LIKE :p"), {"p": MARK})
        await db.commit()


def _snap() -> dict:
    return build_snapshot({"rent": 2100, "savings": 15000, "credit": "good"}, None, lang="en")


@pytest.mark.asyncio
async def test_without_a_postal_address_nothing_is_sent(
    database_url: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The dark state, and the log line that makes it findable. A footer with a
    hole in it would be the CAN-SPAM violation; not sending is the correct
    outcome until the agency supplies the address."""
    monkeypatch.setenv("POSTAL_ADDRESS", "")
    from app.config import get_settings

    get_settings.cache_clear()
    set_org_id(ORG)
    lead_id = await _seed("dark@breakdown.test", snapshot=_snap())
    try:
        with patch("app.services.calculator_email.send_email", new=AsyncMock()) as sender, caplog.at_level(
            "INFO"
        ):
            await send_calculator_breakdown(lead_id)
        sender.assert_not_awaited()
        assert not await _messages(lead_id)
        assert "POSTAL_ADDRESS" in caplog.text
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_opted_out_lead_is_not_written_to(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`may_send_automated` reads `opted_out_at` first, for every channel. The
    unsubscribe link this same feature adds has to actually stop it."""
    monkeypatch.setenv("POSTAL_ADDRESS", ADDRESS)
    from app.config import get_settings

    get_settings.cache_clear()
    set_org_id(ORG)
    lead_id = await _seed("stopped@breakdown.test", snapshot=_snap(), opted_out=True)
    try:
        with patch("app.services.calculator_email.send_email", new=AsyncMock()) as sender:
            await send_calculator_breakdown(lead_id)
        sender.assert_not_awaited()
        assert not await _messages(lead_id)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_lead_who_never_used_the_calculator_gets_nothing(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTAL_ADDRESS", ADDRESS)
    from app.config import get_settings

    get_settings.cache_clear()
    set_org_id(ORG)
    lead_id = await _seed("nocalc@breakdown.test", snapshot=None)
    try:
        with patch("app.services.calculator_email.send_email", new=AsyncMock()) as sender:
            await send_calculator_breakdown(lead_id)
        sender.assert_not_awaited()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_it_sends_and_files_the_copy_in_the_lead_s_thread(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTAL_ADDRESS", ADDRESS)
    monkeypatch.setenv("CONTENT_CTA_URL", "https://www.denverhomestory.com")
    from app.config import get_settings

    get_settings.cache_clear()
    set_org_id(ORG)
    lead_id = await _seed("sent@breakdown.test", snapshot=_snap())
    try:
        sender = AsyncMock(return_value={"id": "resend.abc", "simulated": False})
        with patch("app.services.calculator_email.send_email", new=sender):
            await send_calculator_breakdown(lead_id)

        sender.assert_awaited_once()
        kwargs = sender.await_args.kwargs
        assert kwargs["to"] == "sent@breakdown.test"
        # The footer rides in the body …
        assert ADDRESS in kwargs["body_text"]
        assert "/api/v1/public/unsubscribe/" in kwargs["body_text"]
        # … and the header is what a mail client turns into its own button.
        assert kwargs["unsubscribe_url"].startswith(
            "https://www.denverhomestory.com/api/v1/public/unsubscribe/"
        )

        rows = await _messages(lead_id)
        assert len(rows) == 1
        row = rows[0]
        assert row["internal"] is False  # it is addressed to the lead
        assert row["delivery_status"] == "sent"
        assert row["external_id"] == "resend.abc"
        assert row["send_attempts"] == 0
        # `[]` means screened and clean; NULL would mean never screened at all.
        assert row["fair_housing_flags"] == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_failed_send_is_not_filed_as_a_sent_one(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And its attempts are spent, so `delivery.py::_still_owed` does not sweep
    it up and send a message whose body it cannot rebuild."""
    monkeypatch.setenv("POSTAL_ADDRESS", ADDRESS)
    from app.config import get_settings

    get_settings.cache_clear()
    set_org_id(ORG)
    lead_id = await _seed("failed@breakdown.test", snapshot=_snap())
    try:
        boom = AsyncMock(side_effect=RuntimeError("resend said no"))
        with patch("app.services.calculator_email.send_email", new=boom):
            await send_calculator_breakdown(lead_id)  # must not raise

        rows = await _messages(lead_id)
        assert len(rows) == 1
        assert rows[0]["delivery_status"] == "failed"
        assert rows[0]["external_id"] is None
        assert rows[0]["send_attempts"] > 0
    finally:
        await _cleanup()
