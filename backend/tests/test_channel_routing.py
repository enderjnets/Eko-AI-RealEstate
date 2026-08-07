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
