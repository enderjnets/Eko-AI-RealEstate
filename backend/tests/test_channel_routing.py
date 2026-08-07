"""Inbound messages must reach the agency they were actually sent to.

This is the defect that made multi-tenancy non-functional: with no destination
mapping, every webhook defaulted to the first organization, so a second
agency's leads and their entire conversation transcript were written into the
first agency's dashboard while the real recipient saw nothing.

The tests below are the ones that would have caught it — they need TWO tenants
to say anything at all, which is exactly why nothing in the original suite did.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models.channel_route import CHANNEL_SMS, normalize_destination
from app.services import tenant_resolver
from app.services.tenant_resolver import resolve_org_by_destination

AGENCY_A_NUMBER = "+15551110000"
AGENCY_B_NUMBER = "+15552220000"
SLUG_A = "routing-agency-a"
SLUG_B = "routing-agency-b"


async def _seed_two_agencies() -> tuple[int, int]:
    async with get_bypass_session_factory()() as db:
        ids = []
        for slug, number in ((SLUG_A, AGENCY_A_NUMBER), (SLUG_B, AGENCY_B_NUMBER)):
            org_id = (
                await db.execute(
                    text(
                        "INSERT INTO organizations (name, slug, status, plan) "
                        "VALUES (:n, :s, 'active', 'pilot') RETURNING id"
                    ),
                    {"n": slug, "s": slug},
                )
            ).scalar_one()
            await db.execute(
                text(
                    "INSERT INTO channel_routes (org_id, channel, destination) "
                    "VALUES (:o, :c, :d)"
                ),
                {"o": org_id, "c": CHANNEL_SMS, "d": normalize_destination(number)},
            )
            ids.append(org_id)
        await db.commit()
    tenant_resolver.reset_cache()
    return ids[0], ids[1]


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM organizations WHERE slug IN (:a, :b)"),
            {"a": SLUG_A, "b": SLUG_B},
        )
        await db.commit()
    tenant_resolver.reset_cache()


@pytest.mark.asyncio
async def test_destination_lookup_picks_the_right_agency() -> None:
    org_a, org_b = await _seed_two_agencies()
    try:
        assert await resolve_org_by_destination(CHANNEL_SMS, AGENCY_A_NUMBER) == org_a
        assert await resolve_org_by_destination(CHANNEL_SMS, AGENCY_B_NUMBER) == org_b
        assert await resolve_org_by_destination(CHANNEL_SMS, "+15559999999") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_destination_matching_survives_provider_formatting() -> None:
    """Twilio sends +1555…, a form post may arrive as 1555…, and an address in
    mixed case. A routing miss that should have matched becomes a 503, so the
    comparison cannot be byte-for-byte."""
    org_a, _ = await _seed_two_agencies()
    try:
        for variant in ("+1 (555) 111-0000", "15551110000", "+15551110000"):
            assert await resolve_org_by_destination(CHANNEL_SMS, variant) == org_a
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_two_agencies_texted_at_once_do_not_cross() -> None:
    """The end-to-end shape of the defect: one message per agency, each landing
    only in its own tenant."""
    org_a, org_b = await _seed_two_agencies()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            for to, frm, sid in (
                (AGENCY_A_NUMBER, "+15557770001", "SMroutea"),
                (AGENCY_B_NUMBER, "+15557770002", "SMrouteb"),
            ):
                resp = await c.post(
                    "/api/v1/webhooks/sms",
                    data={"From": frm, "To": to, "Body": "hola", "MessageSid": sid},
                )
                assert resp.status_code == 200, resp.text

        async with get_bypass_session_factory()() as db:
            rows = dict(
                (
                    await db.execute(
                        text(
                            "SELECT phone, org_id FROM leads "
                            "WHERE phone IN ('+15557770001', '+15557770002')"
                        )
                    )
                ).all()
            )
        assert rows.get("+15557770001") == org_a, "agency A's lead went elsewhere"
        assert rows.get("+15557770002") == org_b, "agency B's lead went elsewhere"
        assert rows["+15557770001"] != rows["+15557770002"], "both landed in one tenant"
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM leads WHERE phone IN ('+15557770001','+15557770002')")
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_unmapped_destination_with_two_tenants_is_refused_not_misfiled() -> None:
    """Refusing is recoverable — providers retry and the operator sees it.
    Misfiling is discovered when a client reads another agency's data."""
    await _seed_two_agencies()
    try:
        async with get_bypass_session_factory()() as db:
            before = (await db.execute(text("SELECT count(*) FROM leads"))).scalar_one()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.post(
                "/api/v1/webhooks/sms",
                data={
                    "From": "+15557770003",
                    "To": "+15550000000",
                    "Body": "hola",
                    "MessageSid": "SMunmapped",
                },
            )
        assert resp.status_code == 503, f"expected refusal, got {resp.status_code}"

        async with get_bypass_session_factory()() as db:
            after = (await db.execute(text("SELECT count(*) FROM leads"))).scalar_one()
        assert after == before, "a refused message still wrote a lead"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_whatsapp_and_email_route_by_their_own_destination() -> None:
    """Each channel carries its destination in a different place: WhatsApp in
    changes[].value.metadata, email in data.to. Getting either wrong sends an
    agency's messages to another tenant, so both are asserted explicitly."""
    from app.api.v1.webhooks.email import _mailbox
    from app.api.v1.webhooks.whatsapp import _business_number
    from app.models.channel_route import CHANNEL_EMAIL, CHANNEL_WHATSAPP

    wa_payload = {
        "entry": [
            {
                "changes": [
                    {"value": {"metadata": {"phone_number_id": "109988776655"}}}
                ]
            }
        ]
    }
    assert _business_number(wa_payload) == "109988776655"
    assert _business_number({"entry": []}) is None

    email_payload = {"data": {"to": ["Leads@AgencyB.com"], "from": "x@y.com"}}
    assert _mailbox(email_payload) == "Leads@AgencyB.com"
    assert _mailbox({"data": {}}) is None

    org_a, org_b = await _seed_two_agencies()
    try:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text(
                    "INSERT INTO channel_routes (org_id, channel, destination) "
                    "VALUES (:o1, :c1, :d1), (:o2, :c2, :d2)"
                ),
                {
                    "o1": org_a,
                    "c1": CHANNEL_WHATSAPP,
                    "d1": normalize_destination("109988776655"),
                    "o2": org_b,
                    "c2": CHANNEL_EMAIL,
                    "d2": normalize_destination("Leads@AgencyB.com"),
                },
            )
            await db.commit()
        tenant_resolver.reset_cache()

        assert (
            await resolve_org_by_destination(CHANNEL_WHATSAPP, "109988776655") == org_a
        )
        # Case-insensitive: providers do not preserve the sender's capitals.
        assert (
            await resolve_org_by_destination(CHANNEL_EMAIL, "leads@agencyb.com") == org_b
        )
        # And they do not bleed into each other's channel.
        assert await resolve_org_by_destination(CHANNEL_EMAIL, "109988776655") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_voice_routes_by_the_dialled_number() -> None:
    """Voice was the last channel on a different code path. A channel that is
    special is a channel that silently misfiles, so it uses the same defensive
    extractor: unknown shape → None → fall back or refuse, never guess."""
    from app.api.v1.webhooks.voice import _dialled_number
    from app.models.channel_route import CHANNEL_VOICE

    assert _dialled_number({"call": {"phoneNumber": {"number": "+15553330000"}}}) == (
        "+15553330000"
    )
    assert _dialled_number({"call": {"phoneNumberId": "pn_abc123"}}) == "pn_abc123"
    assert _dialled_number({"phoneNumber": "+15553330000"}) == "+15553330000"
    # The shape the fixtures actually carry has no destination at all.
    assert _dialled_number({"call": {"customer": {"number": "+1555999"}}}) is None
    assert _dialled_number({}) is None

    org_a, _ = await _seed_two_agencies()
    try:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text(
                    "INSERT INTO channel_routes (org_id, channel, destination) "
                    "VALUES (:o, :c, :d)"
                ),
                {
                    "o": org_a,
                    "c": CHANNEL_VOICE,
                    "d": normalize_destination("+15553330000"),
                },
            )
            await db.commit()
        tenant_resolver.reset_cache()
        assert (
            await resolve_org_by_destination(CHANNEL_VOICE, "+1 (555) 333-0000") == org_a
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_call_lands_in_the_agency_that_was_dialled() -> None:
    """End to end, because the isolated extractor test passed against a mutation
    that made the handler read the CALLER instead of the dialled number — the
    same declared-but-not-consumed shape this codebase keeps hitting. Only a
    two-agency round trip can tell the difference."""
    from app.models.channel_route import CHANNEL_VOICE

    org_a, org_b = await _seed_two_agencies()
    caller = "+15557770009"
    try:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text(
                    "INSERT INTO channel_routes (org_id, channel, destination) "
                    "VALUES (:o, :c, :d)"
                ),
                # Agency B owns the dialled number...
                {"o": org_b, "c": CHANNEL_VOICE, "d": normalize_destination(AGENCY_B_NUMBER)},
            )
            # ...while the CALLER's number is agency A's SMS route, so reading
            # the wrong field sends the call to agency A.
            await db.execute(
                text(
                    "INSERT INTO channel_routes (org_id, channel, destination) "
                    "VALUES (:o, :c, :d)"
                ),
                {"o": org_a, "c": CHANNEL_VOICE, "d": normalize_destination(caller)},
            )
            await db.commit()
        tenant_resolver.reset_cache()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.post(
                "/api/v1/webhooks/voice",
                json={
                    "message": {
                        "type": "end-of-call-report",
                        "call": {
                            "id": "call_routing_probe",
                            "customer": {"number": caller},
                            "phoneNumber": {"number": AGENCY_B_NUMBER},
                        },
                        "artifact": {"messages": []},
                    }
                },
            )
            assert resp.status_code == 200, resp.text

        async with get_bypass_session_factory()() as db:
            org_of_lead = (
                await db.execute(
                    text("SELECT org_id FROM leads WHERE phone = :p"), {"p": caller}
                )
            ).scalar_one_or_none()
        assert org_of_lead == org_b, (
            f"call to agency B's number landed in org {org_of_lead}, not {org_b} — "
            "the handler is reading the caller, not the dialled number"
        )
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": caller})
            await db.commit()
        await _cleanup()
