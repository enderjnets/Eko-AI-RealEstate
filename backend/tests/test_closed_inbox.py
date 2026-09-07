"""Who may write to the Inbox, and who hears about a lead.

Four decisions the owner took on 6-Sep-2026, all in one place because they are
one question — *whose mail becomes a lead, and who is told* — and because the
answer to each only makes sense next to the others:

* the brand domain receives on its ROOT, so **only the mapped mailboxes are
  real**; everything else at that domain is refused before it is written;
* a refusal is not silence: the owner hears about it, out of the Inbox;
* every new-lead notice is copied to whoever OPERATES the install, as its own
  message, from a setting the agency cannot edit away;
* and the agency's own address, replying from their own mail client, is not a
  lead — which became reachable the day the notice started arriving from an
  address the product itself receives.

Everything here drives the real ASGI stack. A test that called the resolver
directly would prove the rule and not the route, and the route is where the
old behaviour lived: `webhook_org_or_refuse` returning the only tenant there
is, quietly, with a 200.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.api.v1.public import reset_rate_limits
from app.config import get_settings
from app.db.base import get_bypass_session_factory
from app.main import app
from app.models.channel_route import CHANNEL_EMAIL
from app.services import lead_notify, unrouted_notice

ORG = 1
BRAND = "closed-inbox.test"
MAPPED = f"hello@{BRAND}"
AGENCY_EMAIL = "closed-inbox-agency@example.com"
OWNER_EMAIL = "closed-inbox-owner@example.com"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _clean_rate_limits() -> None:
    reset_rate_limits()
    unrouted_notice.reset_state()
    yield
    reset_rate_limits()
    unrouted_notice.reset_state()


@pytest.fixture(autouse=True)
async def brand_route(database_url: str):  # noqa: ANN201
    """One mapped mailbox on the brand domain — the whole premise of the rule.

    Removed afterwards, because a route left behind would close that domain for
    every other test file in the suite.
    """
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO channel_routes (org_id, channel, destination, label) "
                "VALUES (:o, :c, :d, 'closed-inbox probe')"
            ),
            {"o": ORG, "c": CHANNEL_EMAIL, "d": MAPPED},
        )
        await db.commit()
    yield
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM channel_routes WHERE destination = :d"), {"d": MAPPED}
        )
        await db.commit()


@pytest.fixture(autouse=True)
async def agency_mailbox(database_url: str):  # noqa: ANN201
    """`booking_contact_email` set, and restored: a probe address left behind
    would redirect real notices."""
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


async def _set_agency_email(value: str | None) -> None:
    from app.models.agent_settings import AgentSettings
    from app.services.tenant_context import org_scope

    with org_scope(ORG):
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
            ).scalar_one_or_none()
            if row is not None:
                row.booking_contact_email = value
                await db.commit()


async def _deliver(to: str, *, sender: str, subject: str = "hola", ident: str) -> dict:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/webhooks/email",
            json={
                "type": "email.received",
                "data": {
                    "id": ident,
                    "to": [to],
                    "from": sender,
                    "subject": subject,
                    "text": "Estoy buscando casa en Denver.",
                    "headers": {"message-id": f"<{ident}@{BRAND}>"},
                },
            },
        )
    return {"status_code": response.status_code, "json": response.json()}


async def _lead_count(pattern: str) -> int:
    """Leads matching this probe only.

    Scoped rather than `count(*)`: another session running its own suite against
    the same Postgres would otherwise move this number between the two reads,
    and this repo has already lost an afternoon to exactly that.
    """
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text("SELECT count(*) FROM leads WHERE phone LIKE :p OR email LIKE :p"),
                {"p": pattern},
            )
        ).scalar_one()


async def _post_form(payload: dict) -> int:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/public/leads", json=payload)
    return response.status_code


async def _cleanup_leads(pattern: str) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM leads WHERE phone LIKE :p OR email LIKE :p"), {"p": pattern}
        )
        await db.commit()


# --------------------------------------------------------------------------
# A domain with a route is a closed domain
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unmapped_mailbox_on_the_brand_domain_is_not_a_lead() -> None:
    """The rule, and the reason the whole phase exists.

    The MX sits on the ROOT of the brand domain, so the product receives every
    address at it. Before this, an address matching no route fell through to
    the single-tenant fallback — one agency, so it was always "theirs" — and a
    typo, a scrape or an `admin@` probe became a lead with a thread the
    assistant then answered.
    """
    probe = "%stranger@gmail.test%"
    before = await _lead_count(probe)
    try:
        result = await _deliver(
            f"anything-else@{BRAND}", sender="stranger@gmail.test", ident="closed-1"
        )
        # 200, not 503: the refusal is permanent, and a provider that keeps
        # seeing failures disables the endpoint for every tenant.
        assert result["status_code"] == 200
        assert result["json"]["status"] == "unrouted"
        assert await _lead_count(probe) == before, "an unmapped mailbox wrote a lead"
    finally:
        await _cleanup_leads("%stranger@gmail.test%")


@pytest.mark.asyncio
async def test_the_mapped_mailbox_still_arrives() -> None:
    """The other half. A rule that closed the mapped address too would be a
    quiet outage of the only channel the brand publishes."""
    probe = "%buyer@gmail.test%"
    before = await _lead_count(probe)
    try:
        result = await _deliver(MAPPED, sender="buyer@gmail.test", ident="closed-2")
        assert result["status_code"] == 200
        assert result["json"]["status"] == "ok"
        assert await _lead_count(probe) == before + 1
    finally:
        await _cleanup_leads(probe)


@pytest.mark.asyncio
async def test_a_domain_nobody_has_mapped_is_untouched() -> None:
    """The no-regression, asserted rather than assumed.

    The rule closes what an operator has explicitly opened and NOTHING else. A
    fresh single-customer install has no routes at all and the fallback is its
    whole routing story; widening this to "an address with no route is refused"
    would take inbound email away from every install on the day it shipped.
    """
    probe = "%neighbour@gmail.test%"
    before = await _lead_count(probe)
    try:
        result = await _deliver(
            "info@some-other-domain.test", sender="neighbour@gmail.test", ident="closed-3"
        )
        assert result["status_code"] == 200
        assert result["json"]["status"] == "ok"
        assert await _lead_count(probe) == before + 1
    finally:
        await _cleanup_leads(probe)


# --------------------------------------------------------------------------
# Out of the Inbox, but not out of sight
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_owner_is_told_once_per_sender_per_day() -> None:
    """Told, and told ONCE.

    Anyone who knows the domain can post to it. Without the dedup, a sender who
    retries — or any loop on the far side — turns the owner's phone into an
    alarm he learns to ignore, which is worse than no notice at all.
    """
    telegram = AsyncMock(return_value=True)
    probe = "%@gmail.test%"
    before = await _lead_count(probe)
    try:
        with (
            patch("app.services.telegram_notify.send_operator_telegram", telegram),
            patch("app.services.telegram_notify.undeliverable_reason", lambda: None),
        ):
            await _deliver(f"sales@{BRAND}", sender="spammer@gmail.test", ident="closed-4a")
            assert telegram.await_count == 1
            await _deliver(f"jobs@{BRAND}", sender="spammer@gmail.test", ident="closed-4b")
            assert telegram.await_count == 1, "the same sender nagged twice in one day"
            # A DIFFERENT sender is news again.
            await _deliver(f"sales@{BRAND}", sender="other@gmail.test", ident="closed-4c")
            assert telegram.await_count == 2
        assert await _lead_count(probe) == before
    finally:
        await _cleanup_leads(probe)


@pytest.mark.asyncio
async def test_the_daily_budget_is_its_own_and_it_holds() -> None:
    """Its own budget, deliberately not `ops_alert`'s.

    That module's ceiling is three alerts a UTC day across EVERY subject, and it
    is what the LLM safety-net monitor spends to reach a human. Sharing it would
    let a stranger with the domain silence the alarm that watches the product.
    """
    telegram = AsyncMock(return_value=True)
    with (
        patch("app.services.telegram_notify.send_operator_telegram", telegram),
        patch("app.services.telegram_notify.undeliverable_reason", lambda: None),
        patch.object(unrouted_notice, "MAX_NOTICES_PER_DAY", 2),
    ):
        for n in range(5):
            await unrouted_notice.tell_the_owner_about_unrouted(
                sender=f"sender{n}@gmail.test",
                mailboxes=[f"x{n}@{BRAND}"],
                subject="hi",
                reason="unmapped",
            )
    assert telegram.await_count == 2


@pytest.mark.asyncio
async def test_the_notice_carries_the_envelope_and_never_the_body() -> None:
    """What it says, and what it must not.

    Driven through the REAL route with a real body in the payload, because the
    honest version of "never the body" has to be a message that HAS one. Called
    directly — which is how this was written first — the assertion was vacuous:
    the function has no body parameter, so the string could not have been there
    whatever the code did, and it would have stayed green against the exact
    future change the docstring warns about.
    """
    telegram = AsyncMock(return_value=True)
    probe = "%curious@gmail.test%"
    try:
        with (
            patch("app.services.telegram_notify.send_operator_telegram", telegram),
            patch("app.services.telegram_notify.undeliverable_reason", lambda: None),
        ):
            await _deliver(
                f"admin@{BRAND}",
                sender="curious@gmail.test",
                subject="Your website",
                ident="closed-6",
            )
        assert telegram.await_count == 1
        text_sent = " ".join(str(a) for a in telegram.await_args.args)
        assert "curious@gmail.test" in text_sent
        assert f"admin@{BRAND}" in text_sent
        assert "Your website" in text_sent
        # The body `_deliver` really sent. At this point in the webhook the
        # message has deliberately not been fetched, and this is what keeps it
        # that way.
        assert "Estoy buscando" not in text_sent
    finally:
        await _cleanup_leads(probe)


@pytest.mark.asyncio
async def test_the_refusal_never_spends_the_operator_alert_budget() -> None:
    """The independence, asserted rather than described.

    `ops_alert` allows three alerts a UTC day across EVERY subject and it is
    what the LLM safety-net monitor spends to reach a human. An implementation
    that reached for it — even one keeping its own private counter — would let
    anyone who knows the domain silence the alarm that watches the product.
    """
    alert = AsyncMock(return_value=True)
    telegram = AsyncMock(return_value=True)
    with (
        patch("app.services.ops_alert.send_operator_alert", alert),
        patch("app.services.telegram_notify.send_operator_telegram", telegram),
        patch("app.services.telegram_notify.undeliverable_reason", lambda: None),
    ):
        for n in range(5):
            await unrouted_notice.tell_the_owner_about_unrouted(
                sender=f"s{n}@gmail.test",
                mailboxes=[f"x{n}@{BRAND}"],
                subject="hi",
                reason="unmapped",
            )
    assert telegram.await_count == 5
    assert alert.await_count == 0, "a refusal spent the operator-alarm budget"


@pytest.mark.asyncio
async def test_the_last_notice_of_the_day_says_it_is_the_last() -> None:
    """A budget must not become a way to SILENCE the owner.

    Dedup is per sender and the ceiling is a dozen, so twelve throwaway
    addresses would otherwise buy a whole day in which every genuine refusal
    reaches the log and nothing reaches his phone — and he would have no way to
    know that had happened.
    """
    telegram = AsyncMock(return_value=True)
    # A repeated sender on purpose: it is refused and deduplicated, so it costs
    # no budget. That is what makes the count worth carrying — it counts what
    # was REFUSED, not what was sent, and the two are only equal when every
    # sender is new.
    senders = ["a@gmail.test", "a@gmail.test", "b@gmail.test", "c@gmail.test"]
    with (
        patch("app.services.telegram_notify.send_operator_telegram", telegram),
        patch("app.services.telegram_notify.undeliverable_reason", lambda: None),
        patch.object(unrouted_notice, "MAX_NOTICES_PER_DAY", 2),
    ):
        for who in senders:
            await unrouted_notice.tell_the_owner_about_unrouted(
                sender=who,
                mailboxes=[f"x@{BRAND}"],
                subject="hi",
                reason="unmapped",
            )
    assert telegram.await_count == 2, "the budget did not hold"
    last = " ".join(str(a) for a in telegram.await_args.args)
    assert "last of today" in last
    # Three refused by the time the budget ran out, two notices sent. The
    # number the owner needs is the first one.
    assert "3 refused" in last, "the owner must be told HOW MUCH he is not seeing"


@pytest.mark.asyncio
async def test_a_delivery_that_names_nobody_is_not_a_lead_either() -> None:
    """The hole the first version of the rule left open.

    `_mailboxes` returns NOTHING for several real shapes — a genuine BCC
    delivery, whose header is the literal `undisclosed-recipients:;`, and any
    header the address parser reports defects on. With no keys there is no
    domain, so a rule that only looked at domains saw nothing to close, and the
    message walked into the single-tenant fallback: a lead in org 1 from mail
    addressed to nobody we know. The recipient list is written by the SENDER
    unless the provider hands us an envelope, so this was reachable on purpose.
    """
    probe = "%nameless@gmail.test%"
    before = await _lead_count(probe)
    try:
        for n, recipients in enumerate(
            ("undisclosed-recipients:;", f"a@b@{BRAND}", "")
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/webhooks/email",
                    json={
                        "type": "email.received",
                        "data": {
                            "id": f"closed-nameless-{n}",
                            "to": recipients,
                            "from": "nameless@gmail.test",
                            "subject": "hi",
                            "text": "hola",
                        },
                    },
                )
            assert response.status_code == 200
            assert response.json()["status"] == "unrouted", recipients
        assert await _lead_count(probe) == before
    finally:
        await _cleanup_leads(probe)


@pytest.mark.asyncio
async def test_a_sub_domain_of_a_routed_domain_is_closed_too() -> None:
    """A zone whose mail we receive, not one label of it.

    A wildcard or a `mail.` MX would otherwise be a side door into the same
    fallback. The reverse does not hold, and must not: a route at a sub-domain
    says nothing about the parent, which may belong to somebody else entirely.
    """
    probe = "%subdomain@gmail.test%"
    before = await _lead_count(probe)
    try:
        result = await _deliver(
            f"x@mail.{BRAND}", sender="subdomain@gmail.test", ident="closed-sub"
        )
        assert result["json"]["status"] == "unrouted"
        assert await _lead_count(probe) == before
    finally:
        await _cleanup_leads(probe)


# --------------------------------------------------------------------------
# The operator's copy of the notice
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_operator_gets_his_own_copy() -> None:
    """Two messages, two recipients — never one message with two `to`.

    A second recipient on the agency's mail would put the operator's personal
    address in the header of every notice Natalia receives, where a "Reply all"
    finds it.
    """
    sender = AsyncMock(return_value={"id": "re_copy_1"})
    try:
        with (
            patch("app.services.lead_notify.send_email", sender),
            patch.object(get_settings(), "OWNER_NOTICE_EMAIL", OWNER_EMAIL),
        ):
            assert await _post_form(
                {"name": "Copy Probe", "email": "copy@closed.test"}
            ) == 202
        recipients = [c.kwargs["to"] for c in sender.await_args_list]
        assert sorted(recipients) == sorted([AGENCY_EMAIL, OWNER_EMAIL])
        # And each `to` names exactly one person.
        for who in recipients:
            assert isinstance(who, str) and "," not in who
        # The agency's copy must not mention the operator anywhere — not in the
        # header, not in the body.
        agency = next(c for c in sender.await_args_list if c.kwargs["to"] == AGENCY_EMAIL)
        assert OWNER_EMAIL not in agency.kwargs["body_text"]
    finally:
        await _cleanup_leads("%@closed.test%")


@pytest.mark.asyncio
async def test_no_copy_when_the_setting_is_empty() -> None:
    """Empty is inert — v0.89 behaviour, unchanged."""
    sender = AsyncMock(return_value={"id": "re_copy_2"})
    try:
        with (
            patch("app.services.lead_notify.send_email", sender),
            patch.object(get_settings(), "OWNER_NOTICE_EMAIL", ""),
        ):
            assert await _post_form(
                {"name": "No Copy", "email": "nocopy@closed.test"}
            ) == 202
        assert sender.await_count == 1
        assert sender.await_args.kwargs["to"] == AGENCY_EMAIL
    finally:
        await _cleanup_leads("%@closed.test%")


@pytest.mark.asyncio
async def test_no_copy_when_the_operator_is_the_agency() -> None:
    """One person, one mail.

    Not hypothetical: the owner pointed `booking_contact_email` at himself for
    the Fase 4 rehearsal, and every rehearsal after this one will do it again.
    Case-folded, because a mailbox is not case-sensitive and two spellings of
    one address are still one person.
    """
    sender = AsyncMock(return_value={"id": "re_copy_3"})
    try:
        with (
            patch("app.services.lead_notify.send_email", sender),
            patch.object(get_settings(), "OWNER_NOTICE_EMAIL", AGENCY_EMAIL.upper()),
        ):
            assert await _post_form(
                {"name": "Same Person", "email": "same@closed.test"}
            ) == 202
        assert sender.await_count == 1
        # WHICH one, not just how many: a regression that suppressed the
        # agency's send instead of the duplicate copy leaves the count at 1.
        assert sender.await_args.kwargs["to"] == AGENCY_EMAIL
    finally:
        await _cleanup_leads("%@closed.test%")


@pytest.mark.asyncio
async def test_the_operator_still_hears_when_the_agency_address_is_missing() -> None:
    """The net doing the one job it was added for.

    An empty `booking_contact_email` used to mean nobody was told at all — a
    log line, a captured lead, and silence. The operator's copy is exactly what
    should survive that, so it is asserted here rather than assumed.
    """
    sender = AsyncMock(return_value={"id": "re_copy_4"})
    try:
        await _set_agency_email("")
        with (
            patch("app.services.lead_notify.send_email", sender),
            patch.object(get_settings(), "OWNER_NOTICE_EMAIL", OWNER_EMAIL),
        ):
            assert await _post_form(
                {"name": "Orphan", "email": "orphan@closed.test"}
            ) == 202
        assert sender.await_count == 1
        assert sender.await_args.kwargs["to"] == OWNER_EMAIL
        # And it SAYS so, because "a copy arrived" must not be read as "the
        # agency was told".
        assert "NOBODY at the agency" in sender.await_args.kwargs["body_text"]
    finally:
        await _set_agency_email(AGENCY_EMAIL)
        await _cleanup_leads("%@closed.test%")


# --------------------------------------------------------------------------
# The agency talking to itself
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_agencys_own_reply_is_not_a_new_lead() -> None:
    """The consequence of the brand address receiving its own mail.

    The notice now arrives from `hello@<brand>`, which the product itself
    receives. The realtor presses Reply in their own mail client — the natural
    thing to do — and their answer arrives as a stranger: a new lead named
    after them, carrying their brokerage address, which the assistant then
    answers. The agency talking to itself, in front of the agency.
    """
    probe = f"%{AGENCY_EMAIL}%"
    before = await _lead_count(probe)
    try:
        result = await _deliver(MAPPED, sender=AGENCY_EMAIL, ident="closed-agency")
        assert result["status_code"] == 200
        statuses = [r.get("status") for r in result["json"]["results"]]
        assert statuses == ["ignored_agency_address"]
        assert await _lead_count(probe) == before, "the agency's own reply became a lead"
    finally:
        await _cleanup_leads(f"%{AGENCY_EMAIL}%")


@pytest.mark.asyncio
async def test_the_agencys_reply_is_caught_even_with_a_display_name() -> None:
    """`From` is a HEADER, not an address.

    Every real mail client sends `Natalia Ruiz <natalia@brokerage.com>`, and
    `parsed.from_identifier` carries that string verbatim. A guard comparing it
    against a bare address is inert against every message a human actually
    sends — which is to say, against the only case it was written for. The
    first version of this test posted a bare address and was green over exactly
    that hole.
    """
    probe = f"%{AGENCY_EMAIL}%"
    before = await _lead_count(probe)
    telegram = AsyncMock(return_value=True)
    try:
        with (
            patch("app.services.telegram_notify.send_operator_telegram", telegram),
            patch("app.services.telegram_notify.undeliverable_reason", lambda: None),
        ):
            result = await _deliver(
                MAPPED,
                sender=f"Natalia Ruiz <{AGENCY_EMAIL}>",
                ident="closed-agency-display",
            )
        statuses = [r.get("status") for r in result["json"]["results"]]
        assert statuses == ["ignored_agency_address"]
        assert await _lead_count(probe) == before
        # And it is not silent. A forwarded inquiry lands here too, and a lead
        # dropped with nothing but a log line is a lead lost.
        assert telegram.await_count == 1
    finally:
        await _cleanup_leads(probe)


@pytest.mark.asyncio
async def test_the_row_says_the_agency_was_not_told() -> None:
    """The internal note is what the agency reads in their own panel.

    With no `booking_contact_email`, Telegram still succeeds — it goes to the
    OPERATOR's chat, never to the agency — so the row used to be filed as SENT
    with `email failed (…); telegram carried the notice`, which reads as a
    provider hiccup about a message that was never addressed to them at all.
    Reachable only with Telegram configured, which the suite blanks, so it is
    patched here on purpose: the production shape is the one nothing tested.
    """
    sender = AsyncMock(return_value={"id": "re_row_1"})
    telegram = AsyncMock(return_value=True)
    try:
        await _set_agency_email("")
        with (
            patch("app.services.lead_notify.send_email", sender),
            patch("app.services.lead_notify.undeliverable_reason", lambda: None),
            patch("app.services.lead_notify.send_operator_telegram", telegram),
            patch.object(get_settings(), "OWNER_NOTICE_EMAIL", OWNER_EMAIL),
        ):
            assert await _post_form({"name": "Row", "email": "row@closed.test"}) == 202
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT m.delivery_status, m.last_error FROM messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "JOIN leads l ON l.id = c.lead_id "
                        "WHERE l.email = :e AND m.internal = true"
                    ),
                    {"e": "row@closed.test"},
                )
            ).mappings().one()
        assert "NOBODY at the agency was told" in row["last_error"]
        assert "operator's copy went out" in row["last_error"]
    finally:
        await _set_agency_email(AGENCY_EMAIL)
        await _cleanup_leads("%@closed.test%")


@pytest.mark.asyncio
async def test_a_slow_operator_copy_cannot_bury_a_delivered_notice() -> None:
    """One clock per transport, not one around all three.

    A single `wait_for` over the whole `gather` cancels every child when it
    fires, so a stalled copy threw away the result of a send that had already
    succeeded: the agency was told at two seconds, and the row said FAILED with
    its retry budget spent, about a mail that went out.
    """
    import asyncio as _asyncio

    async def _slow_or_fast(**kwargs):
        if kwargs["to"] == OWNER_EMAIL:
            await _asyncio.sleep(30)
        return {"id": "re_fast_agency"}

    try:
        with (
            patch("app.services.lead_notify.send_email", AsyncMock(side_effect=_slow_or_fast)),
            patch.object(get_settings(), "OWNER_NOTICE_EMAIL", OWNER_EMAIL),
            patch.object(lead_notify, "NOTICE_TIMEOUT_SECONDS", 1.0),
        ):
            assert await _post_form({"name": "Slow", "email": "slow@closed.test"}) == 202
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT m.delivery_status, m.external_id FROM messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "JOIN leads l ON l.id = c.lead_id "
                        "WHERE l.email = :e AND m.internal = true"
                    ),
                    {"e": "slow@closed.test"},
                )
            ).mappings().one()
        assert row["external_id"] == "re_fast_agency"
        assert row["delivery_status"] == "sent"
    finally:
        await _cleanup_leads("%@closed.test%")


@pytest.mark.asyncio
async def test_a_failed_operator_copy_is_a_line_in_the_log_and_nothing_else() -> None:
    """A copy that fails must cost the copy and nothing else.

    Both shapes, because the provider has produced both: a raise, and — the one
    this repo has actually been bitten by — a 200 carrying no id, which is an
    acceptance nobody can trace.
    """
    with patch(
        "app.services.lead_notify.send_email", AsyncMock(return_value={"ok": True})
    ):
        assert await lead_notify._notify_owner_by_email(
            OWNER_EMAIL, "s", "b", 1, AGENCY_EMAIL
        ) is False
    with patch(
        "app.services.lead_notify.send_email", AsyncMock(side_effect=RuntimeError("nope"))
    ):
        assert await lead_notify._notify_owner_by_email(
            OWNER_EMAIL, "s", "b", 1, None
        ) is False


@pytest.mark.asyncio
async def test_a_stalled_agency_send_is_recorded_as_a_timeout() -> None:
    """The other half of the per-leg budget: when it is the AGENCY that stalls.

    The row has to say the mail timed out — not that no transport answered,
    which is what a single clock around all three used to report whichever leg
    was slow.
    """
    import asyncio as _asyncio

    async def _stall(**kwargs):
        await _asyncio.sleep(30)

    try:
        with (
            patch("app.services.lead_notify.send_email", AsyncMock(side_effect=_stall)),
            patch.object(get_settings(), "OWNER_NOTICE_EMAIL", ""),
            patch.object(lead_notify, "NOTICE_TIMEOUT_SECONDS", 1.0),
        ):
            assert await _post_form({"name": "Stall", "email": "stall@closed.test"}) == 202
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT m.delivery_status, m.last_error FROM messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "JOIN leads l ON l.id = c.lead_id "
                        "WHERE l.email = :e AND m.internal = true"
                    ),
                    {"e": "stall@closed.test"},
                )
            ).mappings().one()
        assert "did not answer within 8s" in row["last_error"]
        assert row["delivery_status"] == "failed"
    finally:
        await _cleanup_leads("%@closed.test%")


def test_the_sender_is_read_from_every_shape_resend_uses() -> None:
    """`from` arrives as three different things, and this only names a stranger.

    Forgiving where `_addresses_in` is strict, and the asymmetry is deliberate:
    a routing key decides which agency owns a message and must refuse anything a
    sender can bend, while this ends up in one line of text the owner reads.
    Getting it wrong costs a confusing nudge; getting a routing key wrong costs
    a cross-tenant write.
    """
    from app.api.v1.webhooks.email import _sender, _subject

    assert _sender({"data": {"from": "a@x.test"}}) == "a@x.test"
    assert _sender({"data": {"from": "Nat <a@x.test>"}}) == "a@x.test"
    assert _sender({"data": {"from": [{"email": "a@x.test"}]}}) == "a@x.test"
    assert _sender({"data": {"from": {"address": "a@x.test"}}}) == "a@x.test"
    assert _sender({"data": {"from": []}}) == ""
    assert _sender({"data": {}}) == ""
    assert _sender({}) == ""
    # Not an address, and kept anyway: the owner is better served by the raw
    # text than by an empty line.
    assert _sender({"data": {"from": "postmaster"}}) == "postmaster"

    assert _subject({"data": {"subject": "hi"}}) == "hi"
    assert _subject({"data": {}}) == ""
    assert _subject({}) == ""


@pytest.mark.asyncio
async def test_a_broken_notice_never_costs_the_provider_its_200() -> None:
    """The guard around the nudge, on both paths.

    Resend disables an endpoint that keeps seeing failures, and it would do it
    for every tenant on the install — so a notification that raises must cost
    the notification and nothing else. Asserted for the refusal path and for
    the dropped-agency-mail path, because they are two call sites and a guard
    is only present where it is written.
    """
    probe = "%boom@gmail.test%"
    try:
        with patch(
            "app.api.v1.webhooks.email.tell_the_owner_about_unrouted",
            AsyncMock(side_effect=RuntimeError("telegram is on fire")),
        ):
            refused = await _deliver(
                f"nope@{BRAND}", sender="boom@gmail.test", ident="closed-boom-1"
            )
            assert refused["status_code"] == 200
            assert refused["json"]["status"] == "unrouted"

            dropped = await _deliver(
                MAPPED, sender=AGENCY_EMAIL, ident="closed-boom-2"
            )
            assert dropped["status_code"] == 200
    finally:
        await _cleanup_leads(probe)
        await _cleanup_leads(f"%{AGENCY_EMAIL}%")
