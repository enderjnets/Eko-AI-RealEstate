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
    from app.api.v1.webhooks.email import _mailboxes
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
    assert _mailboxes(email_payload) == ["Leads@AgencyB.com"]
    assert _mailboxes({"data": {}}) == []

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
    from app.api.v1.webhooks.voice import _dialled_numbers
    from app.models.channel_route import CHANNEL_VOICE

    assert _dialled_numbers({"call": {"phoneNumber": {"number": "+15553330000"}}}) == (
        ["+15553330000"]
    )
    assert _dialled_numbers({"call": {"phoneNumberId": "pn_abc123"}}) == ["pn_abc123"]
    assert _dialled_numbers({"phoneNumber": "+15553330000"}) == ["+15553330000"]
    # Both keys for one line, because VAPI does not send the same one every
    # time: the end-of-call report inlines the number while a tool-call message
    # for that same call may carry only the id. Returning one of them meant a
    # route mapped by number 503'd the tool calls mid-conversation.
    both = _dialled_numbers(
        {"call": {"phoneNumber": {"number": "+15553330000", "id": "pn_abc123"}}}
    )
    assert set(both) == {"+15553330000", "pn_abc123"}
    # The shape the fixtures actually carry has no destination at all.
    assert _dialled_numbers({"call": {"customer": {"number": "+1555999"}}}) == []
    assert _dialled_numbers({}) == []

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


@pytest.mark.asyncio
async def test_routing_works_with_auth_on_which_is_production(monkeypatch) -> None:
    """The configuration that actually ships.

    An independent audit found every webhook 503'd with AUTH_ENABLED=true and
    two tenants, no matter how well channel_routes was configured: the
    middleware resolved webhooks by PATH before the handler could look at the
    destination, and raised as soon as a second org existed. So the whole
    routing feature was dead in production.

    The suite missed it because it runs at the default AUTH_ENABLED=false, where
    an early return skips that branch entirely. This test turns auth on and goes
    through HTTP, which is the only combination that would have caught it.
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "AUTH_ENABLED", True)
    monkeypatch.setattr(get_settings(), "AUTH_SECRET", "routing-prod-secret")

    org_a, org_b = await _seed_two_agencies()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.post(
                "/api/v1/webhooks/sms",
                data={
                    "From": "+15557770011",
                    "To": AGENCY_B_NUMBER,
                    "Body": "hola",
                    "MessageSid": "SMprodauth",
                },
            )
        assert resp.status_code == 200, (
            f"routing is unreachable with auth on: {resp.status_code}"
        )

        async with get_bypass_session_factory()() as db:
            org_of_lead = (
                await db.execute(
                    text("SELECT org_id FROM leads WHERE phone = :p"),
                    {"p": "+15557770011"},
                )
            ).scalar_one_or_none()
        assert org_of_lead == org_b, f"landed in org {org_of_lead}, expected {org_b}"
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM leads WHERE phone = '+15557770011'")
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_a_suspended_agency_stops_receiving_inbound(monkeypatch) -> None:
    """Status was checked only on the fallback branch, so a routed destination
    kept delivering into a suspended agency. Suspension has to stop the product
    working for them, not just stop their background sweeps."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "AUTH_ENABLED", True)
    monkeypatch.setattr(get_settings(), "AUTH_SECRET", "routing-prod-secret")

    _, org_b = await _seed_two_agencies()
    try:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE organizations SET status='suspended' WHERE id = :i"),
                {"i": org_b},
            )
            await db.commit()
        tenant_resolver.reset_cache()

        with pytest.raises(tenant_resolver.WebhookOrgUnresolved):
            await tenant_resolver.webhook_org_or_refuse(CHANNEL_SMS, AGENCY_B_NUMBER)
    finally:
        await _cleanup()


# ── Several destinations on one message ──────────────────────────────────────


@pytest.mark.asyncio
async def test_an_email_copied_to_two_agencies_is_refused_not_given_to_the_first() -> None:
    """A lead writes to agency B and copies agency A — realtors get cc'd
    constantly, and `to` has no meaningful order.

    The extractor returned the *first* address, with a comment right above it
    admitting the agency's own is not always first, so B's thread, lead row and
    entire transcript were filed under A. Refusing is recoverable; a
    cross-tenant write is not.
    """
    from app.models.channel_route import CHANNEL_EMAIL

    org_a, org_b = await _seed_two_agencies()
    try:
        async with get_bypass_session_factory()() as db:
            for org_id, mailbox in (
                (org_a, "leads@agency-a.test"),
                (org_b, "leads@agency-b.test"),
            ):
                await db.execute(
                    text(
                        "INSERT INTO channel_routes (org_id, channel, destination) "
                        "VALUES (:o, :c, :d)"
                    ),
                    {"o": org_id, "c": CHANNEL_EMAIL, "d": mailbox},
                )
            await db.commit()
        tenant_resolver.reset_cache()

        from app.api.v1.webhooks.email import _mailboxes

        # Agency A first in `to`, agency B on cc — the ordering that used to
        # decide the answer.
        copied = {
            "data": {
                "to": ["Leads@Agency-A.test"],
                "cc": ["leads@agency-b.test"],
                "from": "buyer@gmail.test",
            }
        }
        assert len(_mailboxes(copied)) == 2, _mailboxes(copied)
        with pytest.raises(tenant_resolver.WebhookOrgUnresolved):
            await tenant_resolver.webhook_org_or_refuse(
                CHANNEL_EMAIL, _mailboxes(copied)
            )

        # One agency addressed and an unrelated recipient alongside is still
        # unambiguous — the lead's own address must not turn into a refusal,
        # and it must not matter that theirs comes first.
        ordinary = {
            "data": {"to": ["buyer@gmail.test", "Leads@Agency-B.test"]}
        }
        assert (
            await tenant_resolver.webhook_org_or_refuse(
                CHANNEL_EMAIL, _mailboxes(ordinary)
            )
            == org_b
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_voice_line_is_found_by_either_of_its_keys() -> None:
    """One `channel_routes` row, two payload shapes.

    VAPI's end-of-call report inlines the E.164 number; a `tool-calls` message
    for that same live call may carry only the opaque phone-number id. With one
    key per lookup, a route mapped by number matched the report and missed the
    tool call — so the assistant 503'd mid-conversation and could not book a
    visit, while the transcript still filed correctly afterwards.
    """
    from app.models.channel_route import CHANNEL_VOICE

    _org_a, org_b = await _seed_two_agencies()
    try:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text(
                    "INSERT INTO channel_routes (org_id, channel, destination) "
                    "VALUES (:o, :c, :d)"
                ),
                {"o": org_b, "c": CHANNEL_VOICE, "d": normalize_destination("+15553330000")},
            )
            await db.commit()
        tenant_resolver.reset_cache()

        from app.api.v1.webhooks.voice import _dialled_numbers

        report = {"call": {"phoneNumber": {"number": "+1 555 333 0000", "id": "pn_x1"}}}
        tool_call = {"call": {"phoneNumber": {"number": "+15553330000"}, "phoneNumberId": "pn_x1"}}

        for payload in (report, tool_call):
            assert (
                await tenant_resolver.webhook_org_or_refuse(
                    CHANNEL_VOICE, _dialled_numbers(payload)
                )
                == org_b
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_malformed_voice_body_is_a_400_not_a_crash() -> None:
    """`json.loads` returns a list for `[]`, and `.get` on that raised
    AttributeError — an unhandled 500 where the honest answer is 400."""
    from app.api.v1.webhooks.voice import _message

    assert _message([]) == {}
    assert _message("nonsense") == {}
    assert _message(None) == {}
    assert _message({"message": {"type": "hang"}}) == {"type": "hang"}


@pytest.mark.asyncio
async def test_informational_voice_events_do_not_need_a_route() -> None:
    """VAPI narrates a call with status updates, speech updates and a hangup.

    They are dropped without touching the database, so gating them on routing
    only produced a stream of 503s and provider retries for events that were
    never going to be stored.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    await _seed_two_agencies()  # two tenants: the fallback cannot resolve
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/api/v1/webhooks/voice",
                json={"message": {"type": "status-update", "status": "in-progress"}},
            )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ignored"
    finally:
        await _cleanup()


# ── Regressions for the edge cases fixed in d3d0232, which shipped untested ───


def test_a_batched_envelope_naming_two_agencies_is_refused() -> None:
    """Meta batches entries per app delivery, and one app serving two WhatsApp
    Business accounts is the documented multi-tenant setup — so a single
    envelope really can carry two agencies.

    Returning the first filed both under it. This is the case the fix was for,
    and it shipped with a test that only ever passed one number in.
    """
    from app.api.v1.webhooks.whatsapp import _business_number

    two_agencies = {
        "entry": [
            {"changes": [{"value": {"metadata": {"phone_number_id": "111"}}}]},
            {"changes": [{"value": {"metadata": {"phone_number_id": "222"}}}]},
        ]
    }
    assert _business_number(two_agencies) is None

    # The same number twice is not an ambiguity — Meta batches several messages
    # to one line constantly, and refusing those would break the common case.
    same_line_twice = {
        "entry": [
            {
                "changes": [
                    {"value": {"metadata": {"phone_number_id": "111"}}},
                    {"value": {"metadata": {"phone_number_id": "111"}}},
                ]
            }
        ]
    }
    assert _business_number(same_line_twice) == "111"

    # `display_phone_number` is the fallback when the id is absent.
    assert (
        _business_number(
            {"entry": [{"changes": [{"value": {"metadata": {"display_phone_number": "+1 555"}}}]}]}
        )
        == "+1 555"
    )


def test_addresses_are_stripped_of_display_names_before_matching() -> None:
    """Senders and providers both add them, and a lookup that kept the name
    never matched a stored route — turning a routable message into a refusal."""
    from app.api.v1.webhooks.email import _addresses_in, _mailboxes

    assert _addresses_in("Agency B <leads@agency-b.test>") == ["leads@agency-b.test"]
    assert _addresses_in("  leads@agency-b.test ") == ["leads@agency-b.test"]
    # A display name containing angle brackets, quoted as RFC 5322 requires.
    assert _addresses_in('"A <b>" <real@x.test>') == ["real@x.test"]

    # Shapes the RFC parser gives up on entirely and that arrive every day. It
    # returning nothing for these lost real leads on the routing path — and, in
    # the fetch-scope check, a message with no readable recipients had nothing
    # to compare against and was waved through.
    assert _addresses_in("b@y.com,") == ["b@y.com"]
    assert _addresses_in("a@x.com; b@y.com") == ["a@x.com", "b@y.com"]
    # Genuinely nothing addressable stays empty, so it matches no route.
    assert _addresses_in("undisclosed-recipients:;") == []
    assert _addresses_in("<>") == []

    # The case that matters: one header naming two agencies must produce BOTH,
    # so the resolver sees the ambiguity. Taking the last angle-bracket pair
    # returned one address, the two lookups agreed on it, and the "two agencies
    # were addressed" refusal never fired.
    assert _mailboxes(
        {"data": {"to": "Agency A <a@agency-a.test>, Agency B <b@agency-b.test>"}}
    ) == ["a@agency-a.test", "b@agency-b.test"]
    # A comma inside a quoted display name is not a separator.
    assert _mailboxes({"data": {"to": '"Smith, John" <j@x.test>'}}) == ["j@x.test"]

    # Dict entries, the shape Resend actually delivers.
    assert _mailboxes({"data": {"to": [{"email": "Leads@Agency-B.test"}]}}) == [
        "Leads@Agency-B.test"
    ]
    # A bare string rather than a list.
    assert _mailboxes({"data": {"recipient": "Agency <x@y.test>"}}) == ["x@y.test"]
    # Not a dict at all — a malformed payload must not 500 the webhook.
    assert _mailboxes({"data": "nonsense"}) == []
    assert _mailboxes({}) == []


def test_destinations_normalise_to_one_key_whatever_the_provider_sends() -> None:
    """Providers spell the same number several ways across their own callbacks.

    Each variant that normalised differently was a route that silently stopped
    matching — which reads as "the second agency's webhook is broken" with
    nothing in the logs to say why.
    """
    from app.models.channel_route import normalize_destination

    canonical = normalize_destination("+1 (555) 111-0000")
    for variant in (
        "+15551110000",
        "15551110000",
        "+1-555-111-0000",
        "0015551110000",      # international 00 prefix
        "+15551110000;ext=42",  # SIP-style extension
        "+15551110000,123",     # pause-dial suffix
        "+15551110000 x99",     # spoken extension
    ):
        assert normalize_destination(variant) == canonical, variant

    # Opaque provider ids are identifiers, not numbers: stripping non-digits
    # would turn "pn_abc123" into "123" and collide it with a phone number.
    assert normalize_destination("pn_abc123") == "pn_abc123"
    assert normalize_destination("wamid.HBgL") == "wamid.hbgl"
    # Email keeps its shape, lowercased.
    assert normalize_destination("Leads@Agency-B.test") == "leads@agency-b.test"
    assert normalize_destination(None) == ""
    assert normalize_destination("   ") == ""


# ── An unroutable message must be dropped, not redelivered forever ───────────


@pytest.mark.asyncio
async def test_an_unroutable_message_is_acknowledged_and_not_written() -> None:
    """200, and nothing stored — on the three channels whose providers retry.

    Meta redelivers a non-2xx for days and then disables the subscription,
    which would take that channel down for every tenant rather than for the one
    unmapped destination. The refusal itself is what protects isolation; the
    status code only decides whether the provider keeps asking. Both halves are
    asserted here, because asserting the status alone would pass if the refusal
    were removed.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    org_a, _org_b = await _seed_two_agencies()  # two tenants: no fallback exists
    try:
        async with get_bypass_session_factory()() as db:
            before = (
                await db.execute(text("SELECT count(*) FROM leads"))
            ).scalar_one()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            whatsapp = await c.post(
                "/api/v1/webhooks/whatsapp",
                json={
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "metadata": {"phone_number_id": "999000999"},
                                        "messages": [
                                            {
                                                "id": "wamid.unrouted1",
                                                "from": "+13035550001",
                                                "type": "text",
                                                "text": {"body": "hola"},
                                            }
                                        ],
                                    }
                                }
                            ]
                        }
                    ]
                },
            )
            email = await c.post(
                "/api/v1/webhooks/email",
                json={
                    "type": "email.received",
                    "data": {
                        "id": "eml-unrouted",
                        "to": ["nobody@unmapped.test"],
                        "from": "buyer@gmail.test",
                        "subject": "hi",
                        "text": "hello",
                    },
                },
            )
            voice = await c.post(
                "/api/v1/webhooks/voice",
                json={
                    "message": {
                        "type": "end-of-call-report",
                        "call": {
                            "id": "call-unrouted",
                            "phoneNumber": {"number": "+19995550000"},
                        },
                    }
                },
            )

        for name, resp in (("whatsapp", whatsapp), ("email", email), ("voice", voice)):
            assert resp.status_code == 200, f"{name}: {resp.status_code} {resp.text}"

        async with get_bypass_session_factory()() as db:
            after = (await db.execute(text("SELECT count(*) FROM leads"))).scalar_one()
        assert after == before, "an unroutable message was written to a tenant"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_email_naming_two_agencies_is_acknowledged_not_retried() -> None:
    """The ambiguous case specifically, end to end through the handler.

    It used to raise 503 while picking the secret — *before* the handler could
    refuse — which made the 200 refusal unreachable in exactly the situation it
    was written for, and let an unauthenticated caller tell 503 from 403 and so
    learn which addresses belong to which agency.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.models.channel_route import CHANNEL_EMAIL

    org_a, org_b = await _seed_two_agencies()
    try:
        async with get_bypass_session_factory()() as db:
            for org_id, mailbox in (
                (org_a, "leads@amb-a.test"),
                (org_b, "leads@amb-b.test"),
            ):
                await db.execute(
                    text(
                        "INSERT INTO channel_routes (org_id, channel, destination) "
                        "VALUES (:o, :c, :d)"
                    ),
                    {"o": org_id, "c": CHANNEL_EMAIL, "d": mailbox},
                )
            before = (await db.execute(text("SELECT count(*) FROM leads"))).scalar_one()
            await db.commit()
        tenant_resolver.reset_cache()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/api/v1/webhooks/email",
                json={
                    "type": "email.received",
                    "data": {
                        "id": "eml-ambiguous",
                        "to": ["leads@amb-a.test"],
                        "cc": ["leads@amb-b.test"],
                        "from": "buyer@gmail.test",
                        "subject": "hi",
                        "text": "hello",
                    },
                },
            )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "unrouted"

        async with get_bypass_session_factory()() as db:
            after = (await db.execute(text("SELECT count(*) FROM leads"))).scalar_one()
        assert after == before, "an ambiguous message was filed under an agency"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_choosing_a_secret_never_short_circuits_the_handlers_refusal() -> None:
    """An ambiguous destination must not become a 503 while picking the key.

    Asserted at this level because the handlers skip verification entirely in
    simulated mode, which is what the suite runs in — so the end-to-end test
    above cannot reach this branch, and would pass with it reverted.

    Raising here had two costs: the handler's 200 refusal became unreachable in
    exactly the case it exists for, so a provider kept retrying and could
    disable the endpoint for every tenant; and the 503 arrived before any
    signature check, letting an unauthenticated caller tell it from a 403 and
    map which destinations belong to which agency.
    """
    from fastapi import HTTPException

    from app.models.channel_route import CHANNEL_EMAIL
    from app.services.channel_identity import inbound_secret_or_503

    org_a, org_b = await _seed_two_agencies()
    try:
        async with get_bypass_session_factory()() as db:
            for org_id, mailbox in (
                (org_a, "leads@sec-a.test"),
                (org_b, "leads@sec-b.test"),
            ):
                await db.execute(
                    text(
                        "INSERT INTO channel_routes (org_id, channel, destination) "
                        "VALUES (:o, :c, :d)"
                    ),
                    {"o": org_id, "c": CHANNEL_EMAIL, "d": mailbox},
                )
            await db.commit()
        tenant_resolver.reset_cache()

        try:
            identity = await inbound_secret_or_503(
                CHANNEL_EMAIL, ["leads@sec-a.test", "leads@sec-b.test"]
            )
        except HTTPException as exc:  # pragma: no cover - the defect
            raise AssertionError(
                f"picking a secret raised {exc.status_code} instead of falling "
                "back, so the handler never got to refuse"
            ) from exc

        # The operator's secret, so a forged payload simply fails the signature
        # check with a plain 403 and a genuine one reaches the 200 refusal.
        assert identity.org_id is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_header_naming_two_agencies_is_refused_end_to_end() -> None:
    """The string form of the CC case, through the resolver.

    Both the secret lookup and the attribution read the same header, so
    collapsing it to one address made them agree — and agreeing is exactly what
    silences the ambiguity refusal.
    """
    from app.api.v1.webhooks.email import _mailboxes
    from app.models.channel_route import CHANNEL_EMAIL

    org_a, org_b = await _seed_two_agencies()
    try:
        async with get_bypass_session_factory()() as db:
            for org_id, mailbox in (
                (org_a, "leads@str-a.test"),
                (org_b, "leads@str-b.test"),
            ):
                await db.execute(
                    text(
                        "INSERT INTO channel_routes (org_id, channel, destination) "
                        "VALUES (:o, :c, :d)"
                    ),
                    {"o": org_id, "c": CHANNEL_EMAIL, "d": mailbox},
                )
            await db.commit()
        tenant_resolver.reset_cache()

        joined = {
            "data": {"to": "Agency A <leads@str-a.test>, Agency B <leads@str-b.test>"}
        }
        with pytest.raises(tenant_resolver.WebhookOrgUnresolved):
            await tenant_resolver.webhook_org_or_refuse(
                CHANNEL_EMAIL, _mailboxes(joined)
            )
    finally:
        await _cleanup()


def test_a_display_name_cannot_smuggle_in_another_agencys_address() -> None:
    """Header text a sender controls must never become a routing key.

    A regex scan over the raw header was tried as a floor under the RFC parser
    and had to be removed: it harvested addresses out of quoted display names
    and comments — exactly the text the parser discards, and exactly the text a
    sender writes. Anyone could then mail an unrouted address on the operator's
    own domain with `To: "leads@agencyb.com" <hello@operator.com>`, have the
    message verify against the operator's secret because that is genuinely who
    it was delivered to, and land a lead, a transcript and an AI reply inside
    agency B.
    """
    from app.api.v1.webhooks.email import _addresses_in

    assert _addresses_in('"leads@agencyb.com" <hello@operator.test>') == [
        "hello@operator.test"
    ]
    assert _addresses_in("Support (leads@agencyb.com) <hello@operator.test>") == [
        "hello@operator.test"
    ]
    # And the separator shapes the floor was introduced for still work, because
    # they are fixed in the input rather than scanned out of it.
    assert _addresses_in("b@y.test,") == ["b@y.test"]
    assert _addresses_in("a@x.test; b@y.test") == ["a@x.test", "b@y.test"]
