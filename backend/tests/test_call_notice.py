"""Clara answers the phone — so somebody has to be told she did.

The form has had a notice since v0.79. The phone did not: an end-of-call report
wrote the caller, the transcript and the summary into the panel and nobody was
informed, so the only way to learn a stranger had just described the house they
want to sell was to go and look. A caller who talks to an assistant and never
hears back is worse off than one who reached voicemail.

These tests pin the four properties that make the call notice honest:

  * a finished call with something in it produces exactly ONE notice;
  * VAPI redelivers end-of-call reports, and a redelivery produces none —
    including the redelivery of a report that has an analysis summary and NO
    transcript, which is the case the idempotency key cannot see;
  * a hang-up (no turns, no summary) produces none;
  * the body carries what the call-back needs, including the link.

Everything drives the real webhook through the ASGI stack, so the notice is
proven to fire from the endpoint VAPI actually posts to — the org is resolved
and bound by that middleware, and a notice that reads `AgentSettings` off a
ContextVar nobody set is a notice that silently does nothing.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.api.v1.webhooks.voice import _tell_the_agency
from app.config import get_settings
from app.db.base import get_bypass_session_factory
from app.main import app

ORG = 1
AGENCY_EMAIL = "call-notice-agency@example.com"
PANEL = "https://panel.test"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
async def agency_mailbox(database_url: str):  # noqa: ANN201
    """The notice only exists when `booking_contact_email` is set. Restored
    afterwards — a probe address left behind would redirect real notices, and
    in this install the real value is a person's work mailbox."""
    from app.models.agent_settings import AgentSettings
    from app.services.tenant_context import org_scope

    with org_scope(ORG):
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
            ).scalar_one_or_none()
            created = row is None
            if created:
                row = AgentSettings(org_id=ORG)
                db.add(row)
            previous = row.booking_contact_email
            row.booking_contact_email = AGENCY_EMAIL
            await db.commit()
    yield
    with org_scope(ORG):
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
            ).scalar_one_or_none()
            if row is not None:
                if created:
                    await db.delete(row)
                else:
                    row.booking_contact_email = previous
                await db.commit()


def _report(call_id: str, phone: str, *, turns: bool = True, summary: bool = True) -> dict:
    msg: dict = {
        "type": "end-of-call-report",
        "call": {"id": call_id, "customer": {"number": phone}},
        "durationSeconds": 94,
    }
    if turns:
        msg["artifact"] = {
            "messages": [
                {"role": "bot", "message": "Are you looking to buy, rent, or sell?"},
                {"role": "user", "message": "I want to sell my place in Wash Park."},
            ]
        }
    if summary:
        msg["analysis"] = {
            "summary": "Caller wants to sell a condo in Washington Park this fall.",
            "structuredData": {"intent": "sell", "zone": "Washington Park", "name": "Dana Ruiz"},
        }
    return {"message": msg}


async def _post(payload: dict) -> int:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/webhooks/voice", json=payload)
    return response.status_code


async def _cleanup(phone: str) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": phone})
        await db.commit()


async def _internal_rows(phone: str) -> list[dict]:
    async with get_bypass_session_factory()() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT m.subject, m.content, m.internal, m.delivery_status, c.channel "
                    "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                    "JOIN leads l ON l.id = c.lead_id "
                    "WHERE l.phone = :p AND m.internal IS TRUE ORDER BY m.id"
                ),
                {"p": phone},
            )
        ).mappings().all()
        return [dict(r) for r in rows]


@pytest.mark.asyncio
async def test_a_finished_call_tells_the_agency() -> None:
    """One end-of-call report → one notice, for the lead the call created."""
    sfx = uuid.uuid4().hex[:8]
    phone = f"+1303555{sfx[:4]}"
    notice = AsyncMock()
    try:
        # Patched where it is USED, not where it is defined: `voice.py` imported
        # the name at module load, so patching `app.services.lead_notify` would
        # replace an object this code never looks at — and the test would pass
        # having proved nothing.
        with patch("app.api.v1.webhooks.voice.send_new_lead_notice", notice):
            assert await _post(_report(f"call_{sfx}", phone)) == 200
        assert notice.await_count == 1
        args, kwargs = notice.await_args
        assert isinstance(args[0], int)
        assert kwargs["origin"] == "call"
        assert isinstance(kwargs["conversation_id"], int)
        assert kwargs["call"]["summary"].startswith("Caller wants to sell")
    finally:
        await _cleanup(phone)


@pytest.mark.asyncio
async def test_the_call_notice_carries_what_the_call_back_needs() -> None:
    """The real body, with only the transport mocked: subject names Clara, and
    the mail carries the caller, the length, the summary and the link."""
    sfx = uuid.uuid4().hex[:8]
    phone = f"+1303555{sfx[:4]}"
    sender = AsyncMock(return_value={"id": "re_call_1"})
    try:
        with (
            patch("app.services.lead_notify.send_email", sender),
            patch.object(get_settings(), "PANEL_URL", PANEL),
        ):
            assert await _post(_report(f"call_{sfx}", phone)) == 200
        assert sender.await_count == 1
        kwargs = sender.await_args.kwargs
        assert kwargs["to"] == AGENCY_EMAIL
        assert "Clara" in kwargs["subject"]
        # Distinguishable from the form's subject at a glance in a mail list.
        assert "New lead from the website" not in kwargs["subject"]
        body = kwargs["body_text"]
        for fact in (phone, "1:34", "Washington Park", "Dana Ruiz"):
            assert fact in body, f"the call back needs {fact!r} in hand"

        rows = await _internal_rows(phone)
        assert len(rows) == 1, "the notice is filed once, in the call's own thread"
        assert rows[0]["channel"] == "voice"
        assert rows[0]["delivery_status"] == "sent"
    finally:
        await _cleanup(phone)


@pytest.mark.asyncio
async def test_the_notice_links_to_the_call_in_the_panel() -> None:
    """The link is the lead's page, exactly — a trailing slash on the setting
    must not produce `//leads/12`."""
    sfx = uuid.uuid4().hex[:8]
    phone = f"+1303555{sfx[:4]}"
    sender = AsyncMock(return_value={"id": "re_call_2"})
    try:
        with (
            patch("app.services.lead_notify.send_email", sender),
            patch.object(get_settings(), "PANEL_URL", PANEL + "/"),
        ):
            assert await _post(_report(f"call_{sfx}", phone)) == 200
        async with get_bypass_session_factory()() as db:
            lead_id = (
                await db.execute(text("SELECT id FROM leads WHERE phone = :p"), {"p": phone})
            ).scalar_one()
        assert f"{PANEL}/leads/{lead_id}" in sender.await_args.kwargs["body_text"]
    finally:
        await _cleanup(phone)


@pytest.mark.asyncio
async def test_a_redelivered_report_does_not_nag_the_agency() -> None:
    """VAPI redelivers. The agency hears about the call once, not once per try."""
    sfx = uuid.uuid4().hex[:8]
    phone = f"+1303555{sfx[:4]}"
    call_id = f"call_{sfx}"
    notice = AsyncMock()
    try:
        with patch("app.api.v1.webhooks.voice.send_new_lead_notice", notice):
            assert await _post(_report(call_id, phone)) == 200
            assert await _post(_report(call_id, phone)) == 200
        assert notice.await_count == 1
    finally:
        await _cleanup(phone)


@pytest.mark.asyncio
async def test_a_summary_only_report_is_also_told_only_once() -> None:
    """The case the idempotency key cannot see.

    Idempotency is keyed on `<call_id>#0`, the first transcript row. A report
    that carries an analysis summary and NO turns never writes that row, so it
    comes back `status: "ok"` on every redelivery — a guard that trusted the
    status alone would mail the agency the same call for as long as VAPI kept
    retrying.
    """
    sfx = uuid.uuid4().hex[:8]
    phone = f"+1303555{sfx[:4]}"
    call_id = f"call_{sfx}"
    notice = AsyncMock()
    try:
        with patch("app.api.v1.webhooks.voice.send_new_lead_notice", notice):
            assert await _post(_report(call_id, phone, turns=False)) == 200
            assert notice.await_count == 1, "a summary with no transcript is still a lead"
            assert await _post(_report(call_id, phone, turns=False)) == 200
        assert notice.await_count == 1
    finally:
        await _cleanup(phone)


@pytest.mark.asyncio
async def test_a_hang_up_tells_nobody() -> None:
    """No transcript and no summary is a hang-up. Mailing an agent about a
    hang-up is how they learn to ignore the notice that matters."""
    sfx = uuid.uuid4().hex[:8]
    phone = f"+1303555{sfx[:4]}"
    notice = AsyncMock()
    try:
        with patch("app.api.v1.webhooks.voice.send_new_lead_notice", notice):
            assert await _post(_report(f"call_{sfx}", phone, turns=False, summary=False)) == 200
        assert notice.await_count == 0
    finally:
        await _cleanup(phone)


@pytest.mark.asyncio
async def test_a_duplicate_verdict_is_obeyed_even_when_the_counts_disagree() -> None:
    """The `status` guard, tested on its own — and it needs to be.

    Through the endpoint it is unreachable: a redelivery also reports zero
    stored turns and no new summary, so the SECOND guard already catches every
    case and removing the first one changes nothing a webhook test can see.
    That is precisely the shape of a check nobody would notice going wrong.

    `ingest_voice_call` has one branch that returns `duplicate` from a race
    without the counting keys at all, and a future change to what it counts
    would land here first. So the verdict is asked directly, with counts that
    say the opposite: `duplicate` wins.
    """
    from app.services.voice import VoiceCallReport

    report = VoiceCallReport(
        call_id="call_direct",
        from_identifier="+13035550100",
        from_name=None,
        summary="Anything at all.",
        turns=[("user", "hello")],
        duration_seconds=42,
    )
    notice = AsyncMock()
    with patch("app.api.v1.webhooks.voice.send_new_lead_notice", notice):
        await _tell_the_agency(
            {
                "status": "duplicate",
                "lead_id": 1,
                "conversation_id": 1,
                "turns_stored": 3,
                "summary_was_new": True,
            },
            report,
        )
    assert notice.await_count == 0


@pytest.mark.asyncio
async def test_a_notice_failure_never_reaches_vapi() -> None:
    """The report is already committed when this runs. An exception escaping
    here would turn a stored call into a 500, and VAPI answers a 500 by
    redelivering — so a broken notice would cost the transcript it is about."""
    from app.services.voice import VoiceCallReport

    report = VoiceCallReport(
        call_id="call_boom",
        from_identifier="+13035550101",
        from_name=None,
        summary="Anything at all.",
        turns=[("user", "hello")],
    )
    exploding = AsyncMock(side_effect=RuntimeError("the mailer is down"))
    with patch("app.api.v1.webhooks.voice.send_new_lead_notice", exploding):
        await _tell_the_agency(
            {"status": "ok", "lead_id": 1, "conversation_id": 1, "turns_stored": 1}, report
        )
    assert exploding.await_count == 1


def test_a_duration_that_is_not_a_number_costs_the_line_and_nothing_else() -> None:
    """`duration_seconds` comes from the provider, and it is the field VAPI has
    already renamed once — `_call_extras` has a comment about it. None of these
    shapes may reach the mail as a literal `Duration: None`, and none of them may
    cost the notice: the number is a courtesy, the call is the point."""
    from app.services.lead_notify import _spoken_duration

    assert _spoken_duration(94) == "1:34"
    assert _spoken_duration(94.7) == "1:34", "seconds are floor'd, not rounded up"
    assert _spoken_duration("94") == "1:34", "a numeric string is still a number"
    assert _spoken_duration(59) == "0:59"
    assert _spoken_duration(3661) == "61:01", "minutes are not wrapped into hours"
    # Everything below produces no line at all.
    assert _spoken_duration(None) is None
    assert _spoken_duration(0) is None
    assert _spoken_duration(-5) is None, "a negative duration is a parsing bug, not a call"
    assert _spoken_duration("a minute and a half") is None
    assert _spoken_duration({"seconds": 94}) is None
    # `1e400` is a valid JSON number and parses to `inf`; `int(float("inf"))`
    # raises OverflowError, which is NOT a ValueError. Uncaught it happened
    # before either transport, so one bad field cost the whole notice.
    assert _spoken_duration(float("inf")) is None
    assert _spoken_duration(float("-inf")) is None
    assert _spoken_duration(float("nan")) is None
    import json

    assert _spoken_duration(json.loads('{"d": 1e400}')["d"]) is None


def test_the_panel_link_is_built_from_the_setting_or_not_at_all() -> None:
    """`https:///leads/12` is what a naive f-string produces on a default
    install, and a broken link in the one mail that has to be trusted is worse
    than no link."""
    from app.services.lead_notify import _panel_link

    with patch.object(get_settings(), "PANEL_URL", "https://panel.test"):
        assert _panel_link(12) == "https://panel.test/leads/12"
    with patch.object(get_settings(), "PANEL_URL", "https://panel.test///"):
        assert _panel_link(12) == "https://panel.test/leads/12"
    with patch.object(get_settings(), "PANEL_URL", "  https://panel.test/  "):
        assert _panel_link(12) == "https://panel.test/leads/12"
    for empty in ("", "   "):
        with patch.object(get_settings(), "PANEL_URL", empty):
            assert _panel_link(12) is None


@pytest.mark.asyncio
async def test_a_web_call_is_not_reported_as_an_email_address() -> None:
    """A web call carries no caller number, so the lead is keyed on
    `voice:<call id>` — an internal handle. The notice's fallback was written
    when that column could only hold a number or an address, and it printed
    `Email: voice:0c3a9b12-…` and put the same string in the subject, telling
    the agent to write to something that is not an address."""
    sfx = uuid.uuid4().hex[:8]
    call_id = f"call_web_{sfx}"
    identifier = f"voice:{call_id}"
    sender = AsyncMock(return_value={"id": "re_call_web"})
    payload = _report(call_id, "")
    # No `customer.number` at all — this is what a web call posts.
    payload["message"]["call"].pop("customer", None)
    payload["message"]["analysis"]["structuredData"].pop("name", None)
    try:
        with (
            patch("app.services.lead_notify.send_email", sender),
            patch.object(get_settings(), "PANEL_URL", PANEL),
        ):
            assert await _post(payload) == 200
        assert sender.await_count == 1
        subject = sender.await_args.kwargs["subject"]
        body = sender.await_args.kwargs["body_text"]
        assert identifier not in body, "an internal handle is not a contact"
        assert identifier not in subject
        assert "Email:" not in body
        # And the notice still happens, still with the summary and the link:
        # dropping a bad label must not drop the call.
        assert "Washington Park" in body
        assert f"{PANEL}/leads/" in body
    finally:
        await _cleanup(identifier)
