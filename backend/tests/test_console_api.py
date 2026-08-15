"""The console API: logging a call, and the list of today.

The list matters because two of its three sections surface state that was
previously invisible — a follow-up nobody can send, and a follow-up being held
for want of consent. Both used to exist only as a log line, which is the same
as not existing.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1 import visits as visits_module
from app.main import app
from app.models import (
    Conversation,
    ConversationStatus,
    FollowUp,
    FollowUpKind,
    FollowUpStatus,
    Lead,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
    Property,
    PropertyStatus,
    Visit,
)
from app.models.lead import LeadStatus, PreferredChannel


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — console API tests need live Postgres")
    return url


def _session(url: str):
    engine = create_async_engine(url, echo=False, future=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _lead(url: str, **kw) -> int:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            sfx = uuid.uuid4().hex[:8].upper()
            lead = Lead(phone=f"+1720CON{sfx}"[:20], name="Console Tester", **kw)
            s.add(lead)
            await s.flush()
            conv = Conversation(
                lead_id=lead.id, channel="sms", status=ConversationStatus.ACTIVE
            )
            s.add(conv)
            await s.flush()
            s.add(
                Message(
                    conversation_id=conv.id,
                    direction=MessageDirection.INBOUND,
                    sender=MessageSender.LEAD,
                    content="hello",
                    external_id=f"in-con-{sfx}",
                    delivery_status=MessageStatus.DELIVERED,
                )
            )
            await s.commit()
            return lead.id
    finally:
        await engine.dispose()


async def _cleanup(url: str, *ids: int) -> None:
    engine, Session = _session(url)
    try:
        async with Session() as s:
            for i in ids:
                await s.execute(text("DELETE FROM leads WHERE id = :i"), {"i": i})
            await s.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_logging_a_call_updates_the_lead_and_returns_the_new_score(
    database_url: str,
) -> None:
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={
                    "outcome": "wants_listings",
                    "intent": "buy",
                    "zone": "Berkeley",
                    "budget_max": 725000,
                    "preferred_channel": "sms",
                    "note": "Pre-approved, wants a yard.",
                    "follow_up_in_days": 3,
                },
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["call"]["outcome"] == "wants_listings"
        assert body["follow_up_scheduled_for"] is not None
        assert isinstance(body["score"], int)

        async with await _client() as c:
            r = await c.get(f"/api/v1/leads/{lead_id}/calls")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["note"] == "Pre-approved, wants a yard."
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_logging_a_call_for_a_missing_lead_is_404(database_url: str) -> None:
    async with await _client() as c:
        r = await c.post("/api/v1/leads/99999999/calls", json={"outcome": "no_answer"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_an_unknown_outcome_is_refused(database_url: str) -> None:
    """The outcome is the trigger. A typo must not become a silently
    unhandled branch."""
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls", json={"outcome": "maybe_later"}
            )
        assert r.status_code == 422
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_an_absurd_follow_up_interval_is_refused(database_url: str) -> None:
    """A fat-fingered interval should not park a lead past the point anyone
    would look for them."""
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={"outcome": "follow_up", "follow_up_in_days": 9000},
            )
        assert r.status_code == 422
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_today_lists_a_call_task_that_nothing_can_send(
    database_url: str,
) -> None:
    lead_id = await _lead(
        database_url, preferred_channel=PreferredChannel.CALL, status=LeadStatus.QUALIFIED
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(hours=2),
                )
            )
            await s.commit()

        async with await _client() as c:
            r = await c.get("/api/v1/console/today")
        assert r.status_code == 200, r.text
        mine = [t for t in r.json()["tasks"] if t["lead"]["id"] == lead_id]
        assert len(mine) == 1
        assert mine[0]["channel"] == "call"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_today_shows_a_follow_up_held_for_want_of_consent(
    database_url: str,
) -> None:
    """Previously this existed only as a log line, so the office could not tell
    "we are nurturing them" from "we have been unable to say anything for a
    week"."""
    lead_id = await _lead(database_url, status=LeadStatus.QUALIFIED)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) + timedelta(hours=6),
                    attempts=3,
                )
            )
            await s.commit()

        async with await _client() as c:
            r = await c.get("/api/v1/console/today")
        mine = [h for h in r.json()["held"] if h["lead"]["id"] == lead_id]
        assert len(mine) == 1
        assert mine[0]["holds"] == 3
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_lead_who_opted_out_appears_nowhere_on_the_list(
    database_url: str,
) -> None:
    """The list is a list of things to do. Doing any of them to somebody who
    asked us to stop is the failure that costs $500 a message."""
    lead_id = await _lead(
        database_url,
        preferred_channel=PreferredChannel.CALL,
        status=LeadStatus.QUALIFIED,
        score=95,
    )
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            lead.opted_out_at = datetime.now(UTC)
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.PENDING,
                    scheduled_for=datetime.now(UTC) - timedelta(hours=2),
                    attempts=2,
                )
            )
            await s.commit()

        async with await _client() as c:
            body = (await c.get("/api/v1/console/today")).json()
        assert [t for t in body["tasks"] if t["lead"]["id"] == lead_id] == []
        assert [h for h in body["held"] if h["lead"]["id"] == lead_id] == []
        assert [x for x in body["untouched_hot"] if x["id"] == lead_id] == []
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_hot_lead_leaves_the_untouched_list_once_it_is_called(
    database_url: str,
) -> None:
    lead_id = await _lead(
        database_url,
        status=LeadStatus.QUALIFIED,
        score=88,
        last_message_at=datetime.now(UTC) - timedelta(days=30),
    )
    try:
        async with await _client() as c:
            body = (await c.get("/api/v1/console/today")).json()
        assert any(x["id"] == lead_id for x in body["untouched_hot"])

        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls", json={"outcome": "no_answer"}
            )
            assert r.status_code == 201, r.text
            body = (await c.get("/api/v1/console/today")).json()
        assert not any(x["id"] == lead_id for x in body["untouched_hot"]), (
            "a lead that was just called is not untouched"
        )
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_failed_follow_up_shows_on_the_list(database_url: str) -> None:
    """A provider outage marks every due message FAILED. Filtering the section
    to PENDING left the list reassuringly empty on the one morning it should
    have been full — the exact blindness this section exists to remove."""
    lead_id = await _lead(database_url, status=LeadStatus.QUALIFIED)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.FAILED,
                    scheduled_for=datetime.now(UTC) - timedelta(hours=1),
                )
            )
            await s.commit()

        async with await _client() as c:
            body = (await c.get("/api/v1/console/today")).json()
        mine = [h for h in body["held"] if h["lead"]["id"] == lead_id]
        assert len(mine) == 1, "a failed follow-up was invisible"
        assert mine[0]["status"] == "failed"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_not_a_number_budget_is_refused_rather_than_stored(
    database_url: str,
) -> None:
    """NaN passed validation, stored as Decimal('NaN'), and then every
    subsequent GET /leads returned 500 for that agency because the response
    model demands a finite number. The write path must not accept what the
    read path cannot render."""
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                content='{"outcome":"follow_up","budget_max":NaN}',
                headers={"content-type": "application/json"},
            )
            assert r.status_code == 422, r.text
            # And the list still renders.
            assert (await c.get("/api/v1/leads?limit=5")).status_code == 200
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_an_over_long_value_is_refused_rather_than_lost_as_a_500(
    database_url: str,
) -> None:
    """`urgency` is only 40 characters wide. Reaching Postgres with more raised
    StringDataRightTruncation and threw away the whole call — after the advisor
    had already had the conversation."""
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={"outcome": "follow_up", "urgency": "x" * 500},
            )
            assert r.status_code == 422, r.text
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={"outcome": "follow_up", "zone": "z" * 5000},
            )
            assert r.status_code == 422, r.text
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_malformed_email_is_refused(database_url: str) -> None:
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={"outcome": "follow_up", "email": "not-an-email"},
            )
            assert r.status_code == 422, r.text
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_booking_records_which_property_it_is_for(database_url: str) -> None:
    """`visits.property_id` was added by migration 029 and nothing wrote it —
    a column in the schema that no code path fills is the dead-field pattern,
    and it is the reason the post-visit follow-up cannot name the house."""
    lead_id = await _lead(database_url)
    engine, Session = _session(database_url)
    prop_id = None
    try:
        async with Session() as s:
            prop = Property(
                source="manual",
                external_id=f"console-test-{uuid.uuid4().hex[:8]}",
                title="Test bungalow",
                address="1200 S Downing St",
                city="Denver",
                state="CO",
                price=Decimal("650000"),
                status=PropertyStatus.ACTIVE,
            )
            s.add(prop)
            await s.commit()
            prop_id = prop.id

        async with await _client() as c:
            r = await c.post(
                "/api/v1/visits",
                json={
                    "lead_id": lead_id,
                    "title": "Showing",
                    "scheduled_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
                    "property_address": "1200 S Downing St",
                    "property_id": prop_id,
                },
            )
        assert r.status_code == 201, r.text
        assert r.json()["property_id"] == prop_id

        async with Session() as s:
            visit = (
                await s.execute(select(Visit).where(Visit.lead_id == lead_id))
            ).scalars().first()
            assert visit is not None
            assert visit.property_id == prop_id
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)
        if prop_id:
            async with Session() as s:
                await s.execute(
                    text("DELETE FROM properties WHERE id = :i"), {"i": prop_id}
                )
                await s.commit()


@pytest.mark.asyncio
async def test_the_api_says_when_it_refused_to_record_consent(
    database_url: str,
) -> None:
    """A refusal reported as plain success is worse than the refusal.

    The advisor ticks "they asked for texts", gets a 201, and walks away
    believing texting is permitted — while every queued message is quietly
    held back and nothing anywhere says why.
    """
    lead_id = await _lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            lead.opted_out_at = datetime.now(UTC) - timedelta(days=1)
            await s.commit()

        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={"outcome": "follow_up", "asked_for_texts": True},
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["consent_recorded"] is False
        assert body["consent_refused_opted_out"] is True
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_consent_recorded_is_true_when_it_actually_was(
    database_url: str,
) -> None:
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            body = (
                await c.post(
                    f"/api/v1/leads/{lead_id}/calls",
                    json={"outcome": "wants_listings", "asked_for_texts": True},
                )
            ).json()
        assert body["consent_recorded"] is True
        assert body["consent_refused_opted_out"] is False
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_backwards_budget_is_refused(database_url: str) -> None:
    """Accepting it hands the matcher an empty range, and the advisor is told
    truthfully that nothing matches with no hint that they typed the two the
    wrong way up."""
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={"outcome": "follow_up", "budget_min": 900000, "budget_max": 1000},
            )
        assert r.status_code == 422, r.text
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_an_email_pasted_with_a_leading_space_still_saves(
    database_url: str,
) -> None:
    """It arrives that way from a contact card. Rejecting it lost the whole
    call after the advisor had already had the conversation."""
    lead_id = await _lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={"outcome": "follow_up", "email": "  marisol@example.com "},
            )
        assert r.status_code == 201, r.text
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.email == "marisol@example.com"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_failure_from_long_ago_is_not_on_todays_list(
    database_url: str,
) -> None:
    """FAILED is terminal — nothing ever moves a follow-up back out of it — so
    without a window the section becomes an ever-growing archive and the rows
    that are stuck today fall off the end of the page."""
    lead_id = await _lead(database_url, status=LeadStatus.QUALIFIED)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            fu = FollowUp(
                lead_id=lead_id,
                kind=FollowUpKind.CALL_FOLLOW_UP,
                status=FollowUpStatus.FAILED,
                scheduled_for=datetime.now(UTC) - timedelta(days=90),
            )
            s.add(fu)
            await s.commit()
            # `updated_at` has onupdate=now(), so age it directly.
            await s.execute(
                text("UPDATE follow_ups SET updated_at = :t WHERE id = :i"),
                {"t": datetime.now(UTC) - timedelta(days=90), "i": fu.id},
            )
            await s.commit()

        async with await _client() as c:
            body = (await c.get("/api/v1/console/today")).json()
        assert [h for h in body["held"] if h["lead"]["id"] == lead_id] == []
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_row_that_failed_today_shows_even_if_it_was_due_weeks_ago(
    database_url: str,
) -> None:
    """After a backlog the sweep picks up rows whose due date is weeks old and
    fails them today. Windowing on the due date hid them from the moment they
    broke, in the one place they could ever have appeared."""
    lead_id = await _lead(database_url, status=LeadStatus.QUALIFIED)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.FAILED,
                    scheduled_for=datetime.now(UTC) - timedelta(days=45),
                )
            )
            await s.commit()

        async with await _client() as c:
            body = (await c.get("/api/v1/console/today")).json()
        mine = [h for h in body["held"] if h["lead"]["id"] == lead_id]
        assert len(mine) == 1, "a failure from this morning was invisible"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_booking_against_a_listing_that_no_longer_exists_is_refused(
    database_url: str,
) -> None:
    """A match can be purged by the MLS sync between the card rendering and the
    click. Writing the id blind hit the foreign key as a 500 — and on the
    Cal.com route the booking is made first, so the lead would have received a
    real calendar invite for a showing the CRM never recorded."""
    lead_id = await _lead(database_url)
    try:
        async with await _client() as c:
            r = await c.post(
                "/api/v1/visits",
                json={
                    "lead_id": lead_id,
                    "title": "Showing",
                    "scheduled_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                    "property_id": 999_999_999,
                },
            )
        assert r.status_code == 400, r.text
        assert "unknown_property" in r.text
    finally:
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_lowering_the_maximum_below_a_stored_minimum_is_refused(
    database_url: str,
) -> None:
    """The console only offers a maximum, so the inversion arrives one field at
    a time and any body-level check passes trivially — while the lead is left
    with a range that can never match anything."""
    lead_id = await _lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            lead.budget_min = Decimal("900000")
            await s.commit()

        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={"outcome": "follow_up", "budget_max": 1000},
            )
        assert r.status_code == 400, r.text

        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.budget_max is None, "an inverted range was stored anyway"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_rejected_call_writes_nothing_at_all(database_url: str) -> None:
    """`register_call` flushes the CallLog before it validates the budget, so
    the refusal happens with a row already in the transaction. If that were not
    rolled back the call history would fill with calls that never saved, and
    the advisor would see their failed attempt logged as if it had worked."""
    lead_id = await _lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            lead.budget_min = Decimal("900000")
            await s.commit()

        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calls",
                json={"outcome": "follow_up", "budget_max": 1000, "note": "should vanish"},
            )
            assert r.status_code == 400, r.text
            history = (await c.get(f"/api/v1/leads/{lead_id}/calls")).json()
        assert history == [], "a rejected call was recorded anyway"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_burst_of_failures_does_not_bury_the_consent_holds(
    database_url: str,
) -> None:
    """The two kinds share one page. A provider outage fails every due message
    in a single sweep, and each of those rows is newer than a consent hold that
    has been waiting since yesterday — so on one shared budget the holds fall
    off the end on the exact morning the page matters most. Ordering cannot fix
    it: whichever column leads, the losing kind is the one that vanishes."""
    held_lead = await _lead(database_url, status=LeadStatus.QUALIFIED)
    noisy_leads: list[int] = []
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            # Yesterday's hold: consent refused, nothing sent, a person can act.
            s.add(
                FollowUp(
                    lead_id=held_lead,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.PENDING,
                    attempts=1,
                    scheduled_for=datetime.now(UTC) - timedelta(days=1),
                )
            )
            await s.commit()
            await s.execute(
                text(
                    "UPDATE follow_ups SET updated_at = :t WHERE lead_id = :i",
                ),
                {"t": datetime.now(UTC) - timedelta(days=1), "i": held_lead},
            )
            await s.commit()

        # This morning's outage, larger than one page.
        for _ in range(60):
            noisy_leads.append(await _lead(database_url, status=LeadStatus.QUALIFIED))
        async with Session() as s:
            for lid in noisy_leads:
                s.add(
                    FollowUp(
                        lead_id=lid,
                        kind=FollowUpKind.CALL_FOLLOW_UP,
                        status=FollowUpStatus.FAILED,
                        scheduled_for=datetime.now(UTC) - timedelta(hours=2),
                    )
                )
            await s.commit()

        async with await _client() as c:
            body = (await c.get("/api/v1/console/today?limit=50")).json()

        held_ids = [h["lead"]["id"] for h in body["held"]]
        assert held_lead in held_ids, "the consent hold was buried by the outage"
        assert any(lid in held_ids for lid in noisy_leads), "the failures vanished too"
    finally:
        await engine.dispose()
        for lid in [held_lead, *noisy_leads]:
            await _cleanup(database_url, lid)


@pytest.mark.asyncio
async def test_the_edit_form_cannot_invert_a_budget_either(database_url: str) -> None:
    """The call console grew four defences around budgets and this route, which
    writes the same two columns, had none — so the harm they describe stayed
    reachable one door over. An inverted range makes the matches page return
    zero results with no explanation."""
    lead_id = await _lead(database_url)
    engine, Session = _session(database_url)
    try:
        async with await _client() as c:
            inverted = await c.patch(
                f"/api/v1/leads/{lead_id}",
                json={"budget_min": 900000, "budget_max": 100000},
            )
            assert inverted.status_code == 400, inverted.text

            negative = await c.patch(f"/api/v1/leads/{lead_id}", json={"budget_max": -50000})
            assert negative.status_code == 422, negative.text

            # NUMERIC(12,2) — this used to reach the driver and 500.
            huge = await c.patch(f"/api/v1/leads/{lead_id}", json={"budget_max": 1e14})
            assert huge.status_code == 422, huge.text

        async with Session() as s:
            lead = await s.get(Lead, lead_id)
            assert lead.budget_min is None and lead.budget_max is None
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_ghost_listing_is_refused_before_calcom_is_called(
    database_url: str,
) -> None:
    """This is the half that matters. On the slot route the calendar booking is
    created BEFORE the row is written, so an unchecked id meant the lead got a
    real invite by email for a showing the CRM never recorded — and nothing
    reconciles the two. The manual route only risked a 500."""
    lead_id = await _lead(database_url)
    engine, Session = _session(database_url)
    try:
        # A fixed future time, not one from the slots endpoint: what is under
        # test is the ORDER of the guard against the calendar call, and going
        # through the slots list makes it depend on office hours that other
        # tests in this suite rewrite.
        when = (datetime.now(UTC) + timedelta(days=3)).replace(
            minute=0, second=0, microsecond=0
        )

        # Watching the booking itself is the whole point. Asserting "400 and no
        # row" passes just as happily when the invite has already gone out and
        # the refusal comes afterwards — which is the exact failure being
        # guarded against, and it is what the first version of this test did.
        called: list[object] = []
        real_create_booking = visits_module.create_booking

        async def _spy(*args: object, **kwargs: object) -> object:
            called.append(kwargs)
            return await real_create_booking(*args, **kwargs)

        visits_module.create_booking = _spy
        try:
            async with await _client() as c:
                r = await c.post(
                    f"/api/v1/leads/{lead_id}/calendar/book",
                    json={
                        "start_time": when.isoformat(),
                        "duration_minutes": 30,
                        "property_id": 999_999_999,
                    },
                )
        finally:
            visits_module.create_booking = real_create_booking

        assert r.status_code == 400, r.text
        assert "unknown_property" in r.text
        assert called == [], "the calendar was booked before the listing was checked"

        async with Session() as s:
            rows = (
                await s.execute(select(Visit).where(Visit.lead_id == lead_id))
            ).scalars().all()
        assert rows == [], "a visit was written for a listing that does not exist"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_the_add_lead_form_cannot_invert_a_budget_either(
    database_url: str,
) -> None:
    """Third route, same defect. This is the one a realtor actually uses: the
    add-lead form takes both budgets as free text with no range check of its
    own, so it is the likeliest place for a range to arrive backwards."""
    async with await _client() as c:
        inverted = await c.post(
            "/api/v1/leads",
            json={
                "phone": f"+1720ADD{uuid.uuid4().hex[:6].upper()}",
                "budget_min": 900000,
                "budget_max": 100000,
            },
        )
        assert inverted.status_code == 422, inverted.text

        negative = await c.post(
            "/api/v1/leads",
            json={"phone": f"+1720ADD{uuid.uuid4().hex[:6].upper()}", "budget_max": -50000},
        )
        assert negative.status_code == 422, negative.text

        huge = await c.post(
            "/api/v1/leads",
            json={"phone": f"+1720ADD{uuid.uuid4().hex[:6].upper()}", "budget_max": 1e14},
        )
        assert huge.status_code == 422, huge.text


@pytest.mark.asyncio
async def test_the_database_itself_refuses_a_backwards_range(
    database_url: str,
) -> None:
    """Three rounds of audit found this same defect at three different routes,
    one per round. That pattern means the rule was being kept in the wrong
    place. The constraint holds for every writer, including the classifier —
    which extracts budgets from free text — and the ones nobody has written."""
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            lead = Lead(
                org_id=1,
                phone=f"+1720CK{uuid.uuid4().hex[:6].upper()}",
                budget_min=Decimal("900000"),
                budget_max=Decimal("100000"),
            )
            s.add(lead)
            with pytest.raises(IntegrityError) as inverted:
                await s.commit()
            assert "ck_leads_budget_not_inverted" in str(inverted.value)
            await s.rollback()

        async with Session() as s:
            s.add(
                Lead(
                    org_id=1,
                    phone=f"+1720CK{uuid.uuid4().hex[:6].upper()}",
                    budget_max=Decimal("-1"),
                )
            )
            with pytest.raises(IntegrityError) as negative:
                await s.commit()
            assert "ck_leads_budget_non_negative" in str(negative.value)
            await s.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_page_returns_the_number_of_rows_it_was_asked_for(
    database_url: str,
) -> None:
    """Giving each kind its own budget made the response up to twice the limit,
    with a slice that looked like a cap and could never truncate. A caller
    asking for three rows should get three — while still seeing both kinds."""
    leads: list[int] = []
    engine, Session = _session(database_url)
    try:
        for _ in range(4):
            leads.append(await _lead(database_url, status=LeadStatus.QUALIFIED))
        async with Session() as s:
            for i, lid in enumerate(leads):
                s.add(
                    FollowUp(
                        lead_id=lid,
                        kind=FollowUpKind.CALL_FOLLOW_UP,
                        status=FollowUpStatus.PENDING if i < 2 else FollowUpStatus.FAILED,
                        attempts=1 if i < 2 else 0,
                        scheduled_for=datetime.now(UTC) - timedelta(hours=1),
                    )
                )
            await s.commit()

        async with await _client() as c:
            body = (await c.get("/api/v1/console/today?limit=3")).json()

        mine = [h for h in body["held"] if h["lead"]["id"] in leads]
        assert len(body["held"]) <= 3, f"asked for 3, got {len(body['held'])}"
        assert len({h["follow_up_id"] for h in body["held"]}) == len(body["held"]), (
            "a row was listed twice"
        )
        assert mine, "the fair split returned none of the rows under test"
    finally:
        await engine.dispose()
        for lid in leads:
            await _cleanup(database_url, lid)


@pytest.mark.asyncio
async def test_a_follow_up_is_never_listed_twice(database_url: str) -> None:
    """The two kinds are two separate statements, so they are two snapshots. A
    row the worker flips PENDING→FAILED between them satisfies both predicates
    and comes back twice, as two cards with contradictory badges — during the
    outage this page exists for. Simulated here by matching both predicates at
    once, which is what that race produces."""
    lead_id = await _lead(database_url, status=LeadStatus.QUALIFIED)
    engine, Session = _session(database_url)
    try:
        async with Session() as s:
            s.add(
                FollowUp(
                    lead_id=lead_id,
                    kind=FollowUpKind.CALL_FOLLOW_UP,
                    status=FollowUpStatus.PENDING,
                    attempts=1,
                    scheduled_for=datetime.now(UTC) - timedelta(hours=1),
                )
            )
            await s.commit()

        async with await _client() as c:
            first = (await c.get("/api/v1/console/today")).json()
        assert len([h for h in first["held"] if h["lead"]["id"] == lead_id]) == 1

        # Now the same row is FAILED — the state the second query would see.
        async with Session() as s:
            await s.execute(
                text("UPDATE follow_ups SET status = 'failed' WHERE lead_id = :i"),
                {"i": lead_id},
            )
            await s.commit()

        async with await _client() as c:
            body = (await c.get("/api/v1/console/today")).json()
        ids = [h["follow_up_id"] for h in body["held"]]
        assert len(ids) == len(set(ids)), "the same follow-up was listed twice"
    finally:
        await engine.dispose()
        await _cleanup(database_url, lead_id)


@pytest.mark.asyncio
async def test_a_booking_we_cannot_record_is_undone_not_abandoned(
    database_url: str,
) -> None:
    """The appointment exists before the row does.

    `external_booking_id` is the only handle that can cancel it later, so it
    cannot be trimmed to fit — a shortened reference names no booking — and it
    cannot be dropped, because then the appointment is real and invisible to
    everyone here. If it will not fit, the only move that leaves the world
    consistent is to undo the booking we just made.
    """
    lead_id = await _lead(database_url)
    engine, Session = _session(database_url)

    cancelled: list[str] = []

    class _LongIdBooking:
        external_booking_id = "cal-" + "x" * 200
        scheduled_at = datetime.now(UTC) + timedelta(days=2)
        duration_minutes = 30
        meeting_url = "https://cal.example/x"

    async def _fake_create(*a: object, **k: object) -> object:
        return _LongIdBooking()

    async def _fake_cancel(booking_id: str, **k: object) -> bool:
        cancelled.append(booking_id)
        return True

    real_create = visits_module.create_booking
    real_cancel = visits_module.cancel_booking
    visits_module.create_booking = _fake_create
    visits_module.cancel_booking = _fake_cancel
    try:
        async with await _client() as c:
            r = await c.post(
                f"/api/v1/leads/{lead_id}/calendar/book",
                json={
                    "start_time": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
                    "duration_minutes": 30,
                },
            )
    finally:
        visits_module.create_booking = real_create
        visits_module.cancel_booking = real_cancel

    assert r.status_code == 502, r.text
    assert "calendar_id_too_long" in r.text
    assert cancelled == [_LongIdBooking.external_booking_id], (
        "the appointment was left on the calendar with nothing recording it"
    )

    async with Session() as s:
        rows = (
            await s.execute(select(Visit).where(Visit.lead_id == lead_id))
        ).scalars().all()
    assert rows == [], "a half-recorded visit was written"
    await engine.dispose()
    await _cleanup(database_url, lead_id)
