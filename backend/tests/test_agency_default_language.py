"""A brand-new agency must write to its clients in English.

`AgentSettings.languages` is an ordered list, and `languages[0]` is what the
system writes in when the lead has never written to us — the exact case of a
visit booked from the landing form or over the phone, where the invitation goes
out before anybody has typed a word.

The default used to be `["es", "en"]`. The live agency never saw it because its
row was written by hand, which is precisely why the defect could sit there: it
only reaches an organization created later, and this product is sold as
multi-tenant. These tests fix the order so it cannot quietly flip back.

They test the BEHAVIOUR (what language the system would write in), not the
literal, because the literal is not the promise — the language the client reads
is.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.agent_settings import AgentSettings
from app.models.lead import Lead, LeadStatus
from app.models.organization import STATUS_ACTIVE, Organization
from app.services.tenant_context import org_scope

_SLUG = "lang-default-probe"
_PHONE = "+19995550311"


@pytest.fixture
def _needs_db() -> None:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — this needs live Postgres")


async def _fresh_org() -> int:
    """An organization with NO settings row, which is the state every new
    tenant starts in."""
    await _cleanup()
    async with get_bypass_session_factory()() as db:
        org = Organization(name="Language Default Probe", slug=_SLUG, status=STATUS_ACTIVE)
        db.add(org)
        await db.commit()
        return org.id


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": _PHONE})
        await db.execute(
            text(
                "DELETE FROM agent_settings WHERE org_id IN "
                "(SELECT id FROM organizations WHERE slug = :s)"
            ),
            {"s": _SLUG},
        )
        await db.execute(text("DELETE FROM organizations WHERE slug = :s"), {"s": _SLUG})
        await db.commit()


@pytest.mark.asyncio
async def test_a_new_agency_starts_in_english(_needs_db: None) -> None:
    """The settings row the API creates on demand (`_get_or_create` builds a
    bare `AgentSettings()`) must come out English-first."""
    org_id = await _fresh_org()
    try:
        with org_scope(org_id):
            async with get_session_factory()() as db:
                db.add(AgentSettings())
                await db.commit()
                row = (await db.execute(select(AgentSettings))).scalars().one()
                assert row.languages, "a new agency was created with no language at all"
                assert row.languages[0] == "en", (
                    "a brand-new agency would write to its clients in "
                    f"{row.languages[0]!r}; the head of this list is the language "
                    "they read"
                )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_lead_who_never_wrote_is_answered_in_english(_needs_db: None) -> None:
    """The behaviour that actually reaches a person.

    `_lead_language` detects the language of the lead's last inbound message;
    with no inbound — a form submission or a phone booking — it falls back to
    the agency's first language. This is the path the .ics invitation takes.
    """
    from app.services.followups import _lead_language

    org_id = await _fresh_org()
    try:
        with org_scope(org_id):
            async with get_session_factory()() as db:
                db.add(AgentSettings())
                lead = Lead(org_id=org_id, phone=_PHONE, status=LeadStatus.NEW)
                db.add(lead)
                await db.commit()
                assert await _lead_language(lead, db) == "en"
    finally:
        await _cleanup()
