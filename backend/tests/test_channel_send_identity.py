"""The wiring: what actually goes out on the wire, per agency.

`test_outbound_identity.py` covers the resolver. This covers the three senders
that consume it, because resolving the right identity and then sending with the
global one would look identical in every test that stops at the resolver — and
that is exactly the bug being fixed.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.models.channel_route import (
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    CHANNEL_WHATSAPP,
    normalize_destination,
)
from app.services import tenant_resolver
from app.services.tenant_context import org_scope

AGENCY_B = 820
B_SMS = "+13035559090"
B_WABA = "111222333444"
B_MAILBOX = "hello@agency-b.test"


async def _seed(channel: str, destination: str, **fields: object) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, plan) "
                "VALUES (:i, 'Agency B', 'agency-b-send', 'active', 'pilot') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"i": AGENCY_B},
        )
        cols = ["org_id", "channel", "destination", *fields]
        await db.execute(
            text(
                f"INSERT INTO channel_routes ({', '.join(cols)}) "
                f"VALUES ({', '.join(':' + c for c in cols)})"
            ),
            {
                "org_id": AGENCY_B,
                "channel": channel,
                "destination": normalize_destination(destination),
                **fields,
            },
        )
        await db.commit()
    tenant_resolver.reset_cache()


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM channel_routes WHERE org_id = :i"), {"i": AGENCY_B})
        await db.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": AGENCY_B})
        await db.commit()
    tenant_resolver.reset_cache()


class _Captured:
    """Stands in for httpx.AsyncClient and records the one request made."""

    def __init__(self) -> None:
        self.url: str | None = None
        self.auth: tuple[str, str] | None = None
        self.data: dict | None = None
        self.json: dict | None = None
        self.headers: dict | None = None

    async def __aenter__(self) -> _Captured:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def post(self, url, *, data=None, json=None, auth=None, headers=None):
        self.url, self.data, self.json, self.auth, self.headers = (
            url, data, json, auth, headers,
        )

        class _Resp:
            status_code = 200

            @staticmethod
            def json() -> dict:
                return {"sid": "SM_real", "id": "resend_real", "messages": [{"id": "wamid.x"}]}

            @staticmethod
            def raise_for_status() -> None:
                return None

        return _Resp()


@pytest.fixture(autouse=True)
def _real_mode(monkeypatch) -> object:
    """Simulated mode short-circuits before the identity is ever consulted, so
    these have to run as if the providers were real."""
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "SMS_SIMULATED", False)
    monkeypatch.setattr(s, "WHATSAPP_SIMULATED", False)
    monkeypatch.setattr(s, "EMAIL_SIMULATED", False)
    yield
    tenant_resolver.reset_cache()


@pytest.mark.asyncio
async def test_sms_sends_on_the_acting_agencys_account(monkeypatch) -> None:
    """Their account SID in the URL, their auth token, their From number.

    The whole failure was here: the reply went out on the operator's account, so
    the lead saw the operator's number and answered it, and `To` then matched
    the operator's route — moving the rest of the conversation to their tenant.
    """
    monkeypatch.setenv("TWILIO_SID_B", "AC_bbbb")
    monkeypatch.setenv("TWILIO_TOKEN_B", "tok_bbbb")
    await _seed(
        CHANNEL_SMS,
        B_SMS,
        provider_account_ref="TWILIO_SID_B",
        credential_ref="TWILIO_TOKEN_B",
    )
    captured = _Captured()
    try:
        from app.services.sms import send_sms

        with patch("app.services.sms.httpx", SimpleNamespace(AsyncClient=lambda **_kw: captured)), \
             org_scope(AGENCY_B):
            await send_sms(to="+13035550001", body="hello")

        assert "AC_bbbb" in captured.url, captured.url
        assert captured.auth == ("AC_bbbb", "tok_bbbb")
        assert captured.data["From"] == normalize_destination(B_SMS)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_whatsapp_sends_from_the_agencys_own_line(monkeypatch) -> None:
    monkeypatch.setenv("WA_TOKEN_B", "wa_tok_bbbb")
    await _seed(CHANNEL_WHATSAPP, B_WABA, credential_ref="WA_TOKEN_B")
    captured = _Captured()
    try:
        from app.services.whatsapp import send_text_message

        with patch("app.services.whatsapp.httpx", SimpleNamespace(AsyncClient=lambda **_kw: captured)), \
             org_scope(AGENCY_B):
            await send_text_message("+13035550001", "hello")

        assert f"/{B_WABA}/messages" in captured.url, captured.url
        assert captured.headers["Authorization"] == "Bearer wa_tok_bbbb"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_email_sends_from_the_agencys_own_mailbox(monkeypatch) -> None:
    monkeypatch.setenv("RESEND_KEY_B", "re_bbbb")
    await _seed(CHANNEL_EMAIL, B_MAILBOX, credential_ref="RESEND_KEY_B")
    captured = _Captured()
    try:
        from app.services.email import send_email

        with patch("app.services.email.httpx", SimpleNamespace(AsyncClient=lambda **_kw: captured)), \
             org_scope(AGENCY_B):
            await send_email(to="buyer@gmail.test", subject="Re: Wash Park", body_text="hi")

        assert captured.json["from"] == B_MAILBOX
        assert captured.headers["Authorization"] == "Bearer re_bbbb"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_default_organization_still_sends_on_the_env_account(
    monkeypatch,
) -> None:
    """No route, no change. This is what makes the migration safe to deploy to
    the running single-customer install."""
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "TWILIO_ACCOUNT_SID", "AC_global")
    monkeypatch.setattr(s, "TWILIO_AUTH_TOKEN", "tok_global")
    monkeypatch.setattr(s, "TWILIO_PHONE_NUMBER", "+13030000000")
    monkeypatch.setattr(s, "TWILIO_MESSAGING_SERVICE_SID", "")

    captured = _Captured()
    from app.models.organization import DEFAULT_ORG_ID
    from app.services.sms import send_sms

    with patch("app.services.sms.httpx", SimpleNamespace(AsyncClient=lambda **_kw: captured)), \
         org_scope(DEFAULT_ORG_ID):
        await send_sms(to="+13035550001", body="hello")

    assert captured.auth == ("AC_global", "tok_global")
    assert captured.data["From"] == "+13030000000"


@pytest.mark.asyncio
async def test_the_reply_leaves_from_the_number_the_lead_wrote_to(monkeypatch) -> None:
    """End to end, the loop that misfiled the conversation.

    A text arrives at agency B's number; the org is resolved from it; the reply
    must go back out on that same number, or the lead's next message resolves to
    the wrong agency and the transcript splits across two tenants.
    """
    monkeypatch.setenv("TWILIO_SID_B", "AC_bbbb")
    monkeypatch.setenv("TWILIO_TOKEN_B", "tok_bbbb")
    await _seed(
        CHANNEL_SMS,
        B_SMS,
        provider_account_ref="TWILIO_SID_B",
        credential_ref="TWILIO_TOKEN_B",
    )
    captured = _Captured()
    try:
        from app.services.sms import send_sms

        inbound_to = "+1 (303) 555-9090"  # the same line, as Twilio formats it
        org_id = await tenant_resolver.webhook_org_or_refuse(CHANNEL_SMS, inbound_to)
        assert org_id == AGENCY_B

        with patch("app.services.sms.httpx", SimpleNamespace(AsyncClient=lambda **_kw: captured)), \
             org_scope(org_id):
            await send_sms(to="+13035550001", body="hello back")

        assert captured.data["From"] == normalize_destination(inbound_to), (
            "the reply went out from a different number than the lead texted"
        )
    finally:
        await _cleanup()
