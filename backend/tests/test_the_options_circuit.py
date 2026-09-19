"""The circuit that turns "show me places" into six listings a person chose.

Four of these tests are about a licence rather than about behaviour, and that is
worth saying out loud because they look like ordinary assertions:

  * REcolorado §11.2 lets a Participant reproduce and distribute listing
    information to a prospective purchaser, and forbids displaying or publishing
    it without prior written consent. So the shortlist may go in an email and
    may NOT go on a page — `test_the_options_page_shows_no_listing_data`.
  * The Full export carries 394 columns, and ten of them are notes between
    brokers about someone else's client. The email prints an allow-list —
    `test_the_shortlist_never_carries_what_the_other_broker_wrote`.
  * Colorado Rule 6.10.A.4 requires the brokerage to be named wherever the
    listing reaches a consumer — same test, other half.
  * Every notice that asks for a search is one search asked of a human being
    against a 500-record allowance that renews every 30 days, and whose penalty
    lands on her licence. So the ask is capped, and opened once per lead.

The one that is NOT about a licence is `test_a_callback_is_never_capped`, and it
is the most important of the set: it keeps a stranger from being able to switch
off the one event in this circuit worth interrupting somebody's day for.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import (
    Conversation,
    Lead,
    LeadIntent,
    ListingRequest,
    ListingRequestStatus,
    Property,
    PropertySource,
    PropertyStatus,
)
from app.models.message import Message, MessageDirection, MessageSender, MessageStatus
from app.services.listing_requests import (
    build_options_email,
    clean_callback_text,
    open_request,
)
from app.services.tenant_context import org_scope, set_org_id

ORG = 1
ADDRESS = "123 Test Ave Ste 1, Denver, CO 80200"
MARK = "%@circuit.test"

# One row of the real Full export, trimmed to the columns that matter here and
# with the confidential ones left IN on purpose: what the allow-list has to keep
# out cannot be tested by a fixture that never contained it.
EXPORT_ROW = {
    "list_office_name": "HomeSmart",
    "private_remarks": "Seller is motivated, will take 3.75M. Do not share.",
    "showing_contact_phone": "303-555-0142",
    "list_agent_email": "agent@othershop.example",
    "public_remarks": "Beautiful home in a safe neighborhood with great schools.",
    "listing_type": "sale",
}


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("POSTAL_ADDRESS", ADDRESS)
    monkeypatch.setenv("CONTENT_CTA_URL", "https://example.test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def agency_mailbox(database_url: str):  # noqa: ANN201
    """Nothing in this file may reach the realtor. See `test_the_open_door.py`:
    on 2026-09-19 this address was repointed in PRODUCTION to keep a rehearsal
    away from her, and a probe address left behind is a real notice that never
    arrives."""
    from app.models.agent_settings import AgentSettings

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
            row.booking_contact_email = "circuit-probe@example.com"
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


async def _seed_lead(email: str, *, zone: str = "Wash Park") -> tuple[int, int, int]:
    """Returns `(lead id, conversation id, inbound message id)`."""
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG,
            phone=email,
            email=email,
            name="Probe",
            intent=LeadIntent.BUY,
            zone=zone,
        )
        db.add(lead)
        await db.flush()
        conv = Conversation(org_id=ORG, lead_id=lead.id, channel="email")
        db.add(conv)
        await db.flush()
        msg = Message(
            org_id=ORG,
            conversation_id=conv.id,
            direction=MessageDirection.INBOUND,
            sender=MessageSender.LEAD,
            content="Can you send me some places in Wash Park?",
            delivery_status=MessageStatus.DELIVERED,
        )
        db.add(msg)
        await db.commit()
        return int(lead.id), int(conv.id), int(msg.id)


async def _seed_property(external: str) -> int:
    async with get_bypass_session_factory()() as db:
        row = Property(
            source=PropertySource.MLS,
            external_id=external,
            status=PropertyStatus.ACTIVE,
            title="482 S Gilpin Street",
            address="482 S Gilpin Street",
            city="Denver",
            state="CO",
            zip_code="80209",
            zone="Wash Park",
            price=3985000,
            bedrooms=5,
            bathrooms=5,
            sqft=5187,
            url="https://tour.example/482",
            photos=[],
            raw=dict(EXPORT_ROW),
        )
        db.add(row)
        await db.commit()
        return int(row.id)


async def _fill_notice_budget(conversation_id: int, how_many: int) -> None:
    async with get_bypass_session_factory()() as db:
        for _ in range(how_many):
            db.add(
                Message(
                    org_id=ORG,
                    conversation_id=conversation_id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="(previous notice)",
                    delivery_status=MessageStatus.SENT,
                    internal=True,
                )
            )
        await db.commit()


async def _cleanup(external: str | None = None) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads WHERE email LIKE :p"), {"p": MARK})
        if external is not None:
            await db.execute(
                text("DELETE FROM properties WHERE external_id = :e"), {"e": external}
            )
        await db.commit()


# ──────────────────────────────────────────────────────────────────────────
# The email — what may leave, and what may not
# ──────────────────────────────────────────────────────────────────────────


def test_the_shortlist_never_carries_what_the_other_broker_wrote() -> None:
    """The allow-list, against a row that actually contains the forbidden text.

    `Private Remarks` on a real Wash Park listing is the seller's floor price
    and an instruction not to share it. `Public Remarks` is the other broker's
    marketing copy, and the line in this fixture — "safe neighborhood with great
    schools" — is one our own Fair Housing screen blocks on the email lane, so
    printing it would make us refuse our own message over someone else's
    sentence.
    """

    class P:
        address = "482 S Gilpin Street"
        city = "Denver"
        state = "CO"
        zip_code = "80209"
        price = 3985000
        bedrooms = 5
        bathrooms = 5
        sqft = 5187
        url = "https://tour.example/482"
        raw = dict(EXPORT_ROW)
        source = PropertySource.MLS
        title = "482 S Gilpin Street"

    _, body = build_options_email(
        lead_name="Ender",
        zone="Wash Park",
        properties=[P()],
        agent_name="Natalia",
        page_url="https://example.test/api/v1/public/options/tok",
    )

    assert "482 S Gilpin Street" in body
    assert "$3,985,000" in body
    # Rule 6.10.A.4 — the condition on which another firm's listing may be put
    # in front of a consumer at all.
    assert "HomeSmart" in body

    assert "Seller is motivated" not in body
    assert "303-555-0142" not in body
    assert "agent@othershop.example" not in body
    assert "great schools" not in body

    from app.services.fair_housing import find_violations

    assert find_violations(body, None) == [], (
        "our own screen must not flag the message we compose"
    )


def test_the_callback_text_is_flattened_and_cut() -> None:
    """Their words reach a human inbox, so they are bounded before they are stored.

    The multi-line case is the one that matters: the field is reachable by
    anyone holding a link we emailed, and newlines are what turn a free-text
    answer into something that can impersonate the rest of the notice.
    """
    assert clean_callback_text("Thursday\nafter 4pm") == "Thursday after 4pm"
    assert clean_callback_text("   ") is None
    assert clean_callback_text(None) is None
    assert len(clean_callback_text("x" * 500) or "") == 200


# ──────────────────────────────────────────────────────────────────────────
# The rule that protects somebody else's MLS allowance
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_lead_cannot_hold_two_open_requests(database_url: str) -> None:
    """Four emails in an afternoon are ONE search, not four.

    The second call has to hand back the first request rather than filing a new
    one, and `created` has to be False — that flag is what the caller keys the
    notice off, so getting it wrong is how the realtor is told four times.
    """
    set_org_id(ORG)
    lead_id, _, _ = await _seed_lead("twice@circuit.test")
    try:
        first_id, first_created = await open_request(lead_id, origin="message")
        second_id, second_created = await open_request(lead_id, origin="message")

        assert first_created is True
        assert second_created is False
        assert second_id == first_id

        async with get_bypass_session_factory()() as db:
            rows = (
                await db.execute(
                    select(ListingRequest).where(ListingRequest.lead_id == lead_id)
                )
            ).scalars().all()
        assert len(rows) == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_options_notice_is_capped_like_the_other_stranger_origins(
    database_url: str, agency_mailbox: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The expensive origin is the one that most needs the cap.

    An options notice does not merely land in her inbox — every one she acts on
    is a search against a metered allowance whose penalty falls on her licence.
    """
    from app.config import get_settings
    from app.services.lead_notify import send_new_lead_notice

    monkeypatch.setenv("AGENCY_NOTICE_DAILY_CAP", "3")
    get_settings.cache_clear()
    set_org_id(ORG)
    lead_id, conv_id, msg_id = await _seed_lead("flood@circuit.test")
    try:
        await _fill_notice_budget(conv_id, 4)  # already past a cap of 3
        request_id, _ = await open_request(lead_id, origin="message")

        sender = AsyncMock(return_value={"id": "resend.c1", "simulated": False})
        with patch("app.services.lead_notify.send_email", new=sender):
            await send_new_lead_notice(
                lead_id,
                msg_id,
                origin="options",
                conversation_id=conv_id,
                request_id=request_id,
            )
        sender.assert_not_awaited()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_callback_is_never_capped(
    database_url: str, agency_mailbox: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The conversion point of the circuit, and it cannot be switched off.

    A budget that untrusted traffic can exhaust on behalf of the one event worth
    interrupting her day for is a kill switch — the exact shape `public.py`
    shipped once and had to undo.
    """
    from app.config import get_settings
    from app.services.lead_notify import send_new_lead_notice

    monkeypatch.setenv("AGENCY_NOTICE_DAILY_CAP", "3")
    get_settings.cache_clear()
    set_org_id(ORG)
    lead_id, conv_id, _ = await _seed_lead("callback@circuit.test")
    try:
        await _fill_notice_budget(conv_id, 40)
        request_id, _ = await open_request(lead_id, origin="message")
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    select(ListingRequest).where(ListingRequest.id == request_id)
                )
            ).scalar_one()
            row.callback_text = "Thursday after 4pm"
            await db.commit()

        sender = AsyncMock(return_value={"id": "resend.c2", "simulated": False})
        with patch("app.services.lead_notify.send_email", new=sender):
            await send_new_lead_notice(
                lead_id,
                None,
                origin="callback",
                conversation_id=conv_id,
                request_id=request_id,
            )
        sender.assert_awaited()
        body = sender.await_args_list[0].kwargs["body_text"]
        assert "Thursday after 4pm" in body, "her note is quoted as they typed it"
    finally:
        await _cleanup()


# ──────────────────────────────────────────────────────────────────────────
# The page — §11.2, in a test
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_options_page_shows_no_listing_data(database_url: str) -> None:
    """This is the licence, not a style preference.

    An email to the person who asked is distribution, which §11.2 permits. A URL
    anybody can open is publishing, which it forbids without prior written
    consent. So the page knows there was a shortlist and knows nothing about it.
    """
    set_org_id(ORG)
    external = f"circuit-{uuid.uuid4().hex[:8]}"
    lead_id, _, _ = await _seed_lead("page@circuit.test")
    try:
        property_id = await _seed_property(external)
        request_id, _ = await open_request(lead_id, origin="message")
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    select(ListingRequest).where(ListingRequest.id == request_id)
                )
            ).scalar_one()
            row.status = ListingRequestStatus.SENT
            row.selected_property_ids = [property_id]
            token = row.token
            await db.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/v1/public/options/{token}")

        assert resp.status_code == 200
        page = resp.text
        for forbidden in (
            "482 S Gilpin",
            "3985000",
            "3,985,000",
            "HomeSmart",
            "80209",
            "5187",
            "tour.example",
            "Seller is motivated",
        ):
            assert forbidden not in page, f"the page published {forbidden!r}"
        # And it is still the page it is meant to be.
        assert "Show me a different set" in page
        assert "Ask for a call" in page
    finally:
        await _cleanup(external)


@pytest.mark.asyncio
async def test_an_unknown_token_is_answered_like_a_known_one(database_url: str) -> None:
    """Same status, same shape, nothing learned. A stranger probing tokens gets
    the same page whether or not the one they tried exists."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/public/options/" + "a" * 40)
    assert resp.status_code == 200
    assert "expired" in resp.text


@pytest.mark.asyncio
async def test_asking_for_a_call_records_their_words_and_tells_the_agency(
    database_url: str, agency_mailbox: None
) -> None:
    set_org_id(ORG)
    lead_id, conv_id, _ = await _seed_lead("ring@circuit.test")
    try:
        request_id, _ = await open_request(lead_id, origin="message")
        async with get_bypass_session_factory()() as db:
            token = (
                await db.execute(
                    select(ListingRequest.token).where(ListingRequest.id == request_id)
                )
            ).scalar_one()

        sender = AsyncMock(return_value={"id": "resend.c3", "simulated": False})
        with patch("app.services.lead_notify.send_email", new=sender):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v1/public/options/{token}/call",
                    data={"when": "Friday\nmorning, before ten"},
                )

        assert resp.status_code == 200
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    select(ListingRequest).where(ListingRequest.id == request_id)
                )
            ).scalar_one()
        assert row.status == ListingRequestStatus.CALLBACK_REQUESTED
        assert row.callback_text == "Friday morning, before ten"
        sender.assert_awaited()
    finally:
        await _cleanup()


# ──────────────────────────────────────────────────────────────────────────
# Sending the shortlist
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_opted_out_lead_gets_no_shortlist(database_url: str) -> None:
    """Stop means stop, and it is checked before anything is composed."""
    from datetime import UTC, datetime

    from app.services.listing_requests import send_options_email

    set_org_id(ORG)
    external = f"circuit-{uuid.uuid4().hex[:8]}"
    lead_id, _, _ = await _seed_lead("gone@circuit.test")
    try:
        property_id = await _seed_property(external)
        request_id, _ = await open_request(lead_id, origin="message")
        async with get_bypass_session_factory()() as db:
            lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
            lead.opted_out_at = datetime.now(UTC)
            await db.commit()

        sender = AsyncMock(return_value={"id": "resend.c4", "simulated": False})
        with patch("app.services.email.send_email", new=sender):
            result = await send_options_email(request_id, [property_id])

        assert result["status"] == "opted_out"
        sender.assert_not_awaited()
    finally:
        await _cleanup(external)


@pytest.mark.asyncio
async def test_the_shortlist_is_recorded_after_the_provider_answers(
    database_url: str,
) -> None:
    """A PENDING row written first is what `delivery.py` sweeps up and re-sends.

    So the row lands after the send, carrying the provider's id — and a person
    who chose six listings by hand never has them mailed twice.
    """
    from app.services.listing_requests import send_options_email

    set_org_id(ORG)
    external = f"circuit-{uuid.uuid4().hex[:8]}"
    lead_id, conv_id, _ = await _seed_lead("sent@circuit.test")
    try:
        property_id = await _seed_property(external)
        request_id, _ = await open_request(lead_id, origin="message")

        sender = AsyncMock(return_value={"id": "resend.c5", "simulated": False})
        with patch("app.services.email.send_email", new=sender):
            result = await send_options_email(
                request_id, [property_id], agent_name="Natalia"
            )

        assert result["status"] == "sent", result
        sender.assert_awaited()

        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    select(ListingRequest).where(ListingRequest.id == request_id)
                )
            ).scalar_one()
            assert row.status == ListingRequestStatus.SENT
            assert row.selected_property_ids == [property_id]

            recorded = (
                await db.execute(
                    select(Message).where(
                        Message.conversation_id == conv_id,
                        Message.direction == MessageDirection.OUTBOUND,
                    )
                )
            ).scalars().all()
        assert len(recorded) == 1
        assert recorded[0].external_id == "resend.c5"
        assert recorded[0].delivery_status == MessageStatus.SENT
    finally:
        await _cleanup(external)


# ──────────────────────────────────────────────────────────────────────────
# The trigger, through the real webhook
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_asking_for_places_opens_one_task_and_tells_the_agency(
    database_url: str, agency_mailbox: None
) -> None:
    """End to end from an inbound email, because the wiring is the risk here.

    The trigger reads a BOOLEAN from the classifier's structured output, never a
    sentence from the generated reply — so this patches the classifier, not the
    text. And it is asserted from the webhook rather than from the service
    because the turn has two early returns that could swallow it, and a unit
    test of the helper would pass while the real path stayed silent.
    """
    from app.services.classifier import IntentEntities, IntentResult
    from app.services.llm import LLMResult

    suffix = uuid.uuid4().hex[:8]
    identifier = f"wants+{suffix}@circuit.test"
    payload = {
        "type": "email.received",
        "data": {
            "id": f"resend_opt_{suffix}",
            "from": identifier,
            "from_name": "Probe",
            "to": ["info@realtor-demo.com"],
            "subject": "Wash Park",
            "text": "Can you send me a few places in Wash Park?",
            "headers": {"message-id": f"<opt-{suffix}@circuit.test>"},
        },
    }
    intent = IntentResult(
        intent="buy",  # type: ignore[arg-type]
        confidence=0.95,
        entities=IntentEntities(zone="Wash Park", wants_listings=True),
    )
    reply = LLMResult(
        text="A shortlist is on its way by email.",
        provider="minimax",
        model="MiniMax-M3",
        input_tokens=10,
        output_tokens=10,
    )
    sender = AsyncMock(return_value={"id": f"resend.opt.{suffix}", "simulated": False})
    try:
        with patch(
            "app.services.conversation.classify_intent", AsyncMock(return_value=intent)
        ), patch(
            "app.services.conversation.generate_reply", AsyncMock(return_value=reply)
        ), patch(
            "app.services.lead_notify.send_email", new=sender
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/v1/webhooks/email", json=payload)

        assert resp.status_code == 200, resp.text

        async with get_bypass_session_factory()() as db:
            lead_id = (
                await db.execute(select(Lead.id).where(Lead.email == identifier))
            ).scalar_one()
            rows = (
                await db.execute(
                    select(ListingRequest).where(ListingRequest.lead_id == lead_id)
                )
            ).scalars().all()
        assert len(rows) == 1, "exactly one task, and it exists at all"
        assert rows[0].status == ListingRequestStatus.OPEN

        sender.assert_awaited()
        subject = sender.await_args_list[0].kwargs["subject"]
        assert "asked to see actual listings" in subject, subject
    finally:
        await _cleanup()


def test_the_options_page_cannot_reach_the_listings_table() -> None:
    """The licence test above is only as strong as this one.

    `test_the_options_page_shows_no_listing_data` passes because the handler has
    no code path to `properties` — not because anything stops one being added.
    So the handler is read as a tree: any name that could put a listing in front
    of the reader fails here, and the assertion that the page is clean stops
    depending on the page staying the shape it happens to have today.
    """
    import ast
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "public.py"
    ).read_text()
    tree = ast.parse(source)
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "options_page"
    )
    names = {
        inner.id for inner in ast.walk(handler) if isinstance(inner, ast.Name)
    } | {
        alias.name for inner in ast.walk(handler)
        if isinstance(inner, ast.ImportFrom)
        for alias in inner.names
    }
    for forbidden in ("Property", "match_properties_for_lead", "listing_broker"):
        assert forbidden not in names, (
            f"{forbidden} reached the public options page — §11.2 forbids "
            "publishing listing information, and this page is public"
        )


@pytest.mark.asyncio
async def test_a_lead_told_about_once_is_not_handed_over_twice(
    database_url: str, agency_mailbox: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two turns, one notice.

    The first turn is BLOCKED — no postal address, so Clara cannot answer — and
    that branch returns before the end of the turn, where the once-only handoff
    marker is written. Without the marker being stamped when the options notice
    goes out, the next turn from the same person produces a second mail about
    somebody the agency has already been handed.
    """
    from app.config import get_settings
    from app.services.classifier import IntentEntities, IntentResult
    from app.services.llm import LLMResult

    suffix = uuid.uuid4().hex[:8]
    identifier = f"twice+{suffix}@circuit.test"

    def _payload(n: int) -> dict:
        return {
            "type": "email.received",
            "data": {
                "id": f"resend_twice_{suffix}_{n}",
                "from": identifier,
                "from_name": "Probe",
                "to": ["info@realtor-demo.com"],
                "subject": "Wash Park",
                "text": "Send me a few places in Wash Park, budget around 700k.",
                "headers": {"message-id": f"<twice-{suffix}-{n}@circuit.test>"},
            },
        }

    intent = IntentResult(
        intent="buy",  # type: ignore[arg-type]
        confidence=0.95,
        entities=IntentEntities(
            zone="Wash Park", budget_max=700000, urgency="months", wants_listings=True
        ),
    )
    reply = LLMResult(
        text="A shortlist is on its way.",
        provider="minimax",
        model="MiniMax-M3",
        input_tokens=10,
        output_tokens=10,
    )
    sender = AsyncMock(return_value={"id": f"resend.tw.{suffix}", "simulated": False})
    try:
        with patch(
            "app.services.conversation.classify_intent", AsyncMock(return_value=intent)
        ), patch(
            "app.services.conversation.generate_reply", AsyncMock(return_value=reply)
        ), patch(
            "app.services.lead_notify.send_email", new=sender
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Turn one: blocked, because no compliant footer can be built.
                monkeypatch.setenv("POSTAL_ADDRESS", "")
                get_settings.cache_clear()
                first = await client.post("/api/v1/webhooks/email", json=_payload(1))
                assert first.status_code == 200, first.text

                # Turn two: the address is configured, so the turn runs to the
                # end — and `qualified_now` would fire here.
                monkeypatch.setenv("POSTAL_ADDRESS", ADDRESS)
                get_settings.cache_clear()
                second = await client.post("/api/v1/webhooks/email", json=_payload(2))
                assert second.status_code == 200, second.text

        subjects = [c.kwargs["subject"] for c in sender.await_args_list]
        assert len(subjects) == 1, f"the agency was told twice: {subjects}"
        assert "asked to see actual listings" in subjects[0]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_second_round_does_not_read_as_a_new_person(
    database_url: str, agency_mailbox: None
) -> None:
    """"They asked to see actual listings" about somebody she already knows
    sends her looking for a lead that does not exist. `origin` is on the row
    for this line and no other."""
    from app.services.lead_notify import send_new_lead_notice

    set_org_id(ORG)
    lead_id, conv_id, msg_id = await _seed_lead("again@circuit.test")
    try:
        request_id, _ = await open_request(lead_id, origin="more")

        sender = AsyncMock(return_value={"id": "resend.c6", "simulated": False})
        with patch("app.services.lead_notify.send_email", new=sender):
            await send_new_lead_notice(
                lead_id,
                msg_id,
                origin="options",
                conversation_id=conv_id,
                request_id=request_id,
            )
        subject = sender.await_args_list[0].kwargs["subject"]
        assert "different set" in subject, subject
        assert "asked to see actual listings" not in subject
    finally:
        await _cleanup()
