"""Whose number does the reply come from.

Inbound has been attributed by destination for several rounds, but outbound had
one global identity per channel. The failure needed no adversary: agency B's
lead was answered from agency A's Twilio number, replied to that number, and
`To` then matched A's route — so the rest of B's conversation was written into
A's tenant. It was the last thing blocking a second agency.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.models.channel_route import (
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    CHANNEL_WHATSAPP,
    normalize_destination,
)
from app.models.organization import DEFAULT_ORG_ID
from app.services import tenant_resolver
from app.services.channel_identity import (
    known_verify_tokens,
    resolve_inbound_secret,
    resolve_outbound_identity,
)
from app.services.tenant_context import org_scope

AGENCY_B = 810
B_NUMBER = "+13035551234"
B_MAILBOX = "leads@agency-b.test"


async def _seed_agency_b(**route_fields: object) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, plan) "
                "VALUES (:i, 'Agency B', 'agency-b-identity', 'active', 'pilot') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"i": AGENCY_B},
        )
        columns = ["org_id", "channel", "destination", *route_fields]
        values = [f":{c}" for c in columns]
        await db.execute(
            text(
                f"INSERT INTO channel_routes ({', '.join(columns)}) "
                f"VALUES ({', '.join(values)})"
            ),
            {
                "org_id": AGENCY_B,
                "channel": CHANNEL_SMS,
                "destination": normalize_destination(B_NUMBER),
                **route_fields,
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


@pytest.fixture(autouse=True)
def _clear_cache() -> object:
    yield
    tenant_resolver.reset_cache()


@pytest.mark.asyncio
async def test_an_agency_with_its_own_account_replies_from_its_own_number(
    monkeypatch,
) -> None:
    """The fix, stated plainly: B's reply leaves from B's number on B's account.

    Before this, `send_sms` read TWILIO_* straight out of the global settings,
    so B's lead saw A's number, answered A's number, and became A's lead.
    """
    monkeypatch.setenv("TWILIO_AUTH_TOKEN_AGENCY_B", "b-auth-token")
    monkeypatch.setenv("TWILIO_SID_AGENCY_B", "AC_agency_b")
    await _seed_agency_b(
        credential_ref="TWILIO_AUTH_TOKEN_AGENCY_B",
        provider_account_ref="TWILIO_SID_AGENCY_B",
    )
    try:
        with org_scope(AGENCY_B):
            identity = await resolve_outbound_identity(CHANNEL_SMS)
        assert identity.destination == normalize_destination(B_NUMBER)
        assert identity.credential == "b-auth-token"
        assert identity.provider_account == "AC_agency_b"
        assert identity.is_own_account
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_default_organization_keeps_using_the_env_configuration() -> None:
    """A single-customer install must not need a route row to keep working.

    This is what makes the change safe to deploy: nothing moves until an agency
    is deliberately given its own account.
    """
    from app.config import get_settings

    s = get_settings()
    with org_scope(DEFAULT_ORG_ID):
        identity = await resolve_outbound_identity(CHANNEL_SMS)
    assert identity.credential == (s.TWILIO_AUTH_TOKEN or None)
    assert identity.destination == (s.TWILIO_PHONE_NUMBER or None)
    assert not identity.is_own_account or s.TWILIO_AUTH_TOKEN


@pytest.mark.asyncio
async def test_a_route_without_credentials_borrows_the_shared_account() -> None:
    """An extra number on the operator's own Twilio is a real arrangement: the
    agency owns the destination but not the account."""
    await _seed_agency_b()
    try:
        with org_scope(AGENCY_B):
            identity = await resolve_outbound_identity(CHANNEL_SMS)
        # Their number, the operator's credentials.
        assert identity.destination == normalize_destination(B_NUMBER)
        from app.config import get_settings

        assert identity.credential == (get_settings().TWILIO_AUTH_TOKEN or None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_reference_to_an_unset_variable_refuses_rather_than_falling_back(
    monkeypatch,
) -> None:
    """The dangerous failure would be silent.

    If a missing environment variable quietly meant "use the global account",
    then a typo in the variable name would send B's replies from A's number —
    which is the entire bug, reintroduced through a configuration mistake
    nobody would see.
    """
    from app.config import get_settings

    monkeypatch.delenv("TWILIO_AUTH_TOKEN_TYPO", raising=False)
    monkeypatch.delenv("WA_SECRET_TYPO", raising=False)
    monkeypatch.setattr(get_settings(), "TWILIO_AUTH_TOKEN", "the-operators-token")
    await _seed_agency_b(
        credential_ref="TWILIO_AUTH_TOKEN_TYPO",
        inbound_secret_ref="WA_SECRET_TYPO",
    )
    try:
        with org_scope(AGENCY_B):
            identity = await resolve_outbound_identity(CHANNEL_SMS)
        # Nothing, rather than the operator's. `send_sms` then refuses to
        # dispatch and every verifier rejects an empty secret, so both halves
        # fail closed.
        assert identity.credential is None
        assert identity.inbound_secret is None
        assert identity.credential != "the-operators-token"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_inbound_ref_whose_variable_vanished_never_borrows_the_shared_secret(
    monkeypatch,
) -> None:
    """The branch that had no test, and the one that reaches production.

    An agency with its own Meta app and no outbound credential — the exact
    configuration this work exists for — takes the `plain` branch. When the
    named variable is later dropped, renamed or rotated, substituting the
    operator's secret means anyone holding *that* can sign a message into this
    agency's tenant. `_validate_refs` only checks the environment when the route
    is saved, so nothing notices the drift afterwards.
    """
    from app.config import get_settings

    monkeypatch.delenv("WA_APP_SECRET_GONE", raising=False)
    monkeypatch.setattr(get_settings(), "TWILIO_AUTH_TOKEN", "the-operators-token")
    await _seed_agency_b(inbound_secret_ref="WA_APP_SECRET_GONE")
    try:
        with org_scope(AGENCY_B):
            identity = await resolve_outbound_identity(CHANNEL_SMS)
        assert identity.inbound_secret is None, (
            "a named-but-missing agency secret fell back to the operator's"
        )
        # Sending still works: that half was never in question, and breaking it
        # over an inbound variable is what the previous attempt got wrong.
        assert identity.credential == "the-operators-token"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_inbound_is_verified_with_the_secret_of_the_agency_written_to(
    monkeypatch,
) -> None:
    """An agency on its own provider account signs with its own secret.

    Without this every inbound message from a second agency's number failed
    signature verification with a 403 — so the channel simply did not work for
    them, whatever the routing said.
    """
    monkeypatch.setenv("TWILIO_AUTH_TOKEN_AGENCY_B", "b-auth-token")
    await _seed_agency_b(
        credential_ref="TWILIO_AUTH_TOKEN_AGENCY_B",
        inbound_secret_ref="TWILIO_AUTH_TOKEN_AGENCY_B",
    )
    try:
        theirs = await resolve_inbound_secret(CHANNEL_SMS, B_NUMBER)
        assert theirs.inbound_secret == "b-auth-token"

        # An unrouted number is the operator's own, so the global secret stands.
        from app.config import get_settings

        ours = await resolve_inbound_secret(CHANNEL_SMS, "+19998887777")
        assert ours.inbound_secret == (get_settings().TWILIO_AUTH_TOKEN or None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_whatsapp_handshake_accepts_any_configured_agency(
    monkeypatch,
) -> None:
    """The setup handshake carries mode, token and challenge — no destination.

    There is nothing to resolve an organization from, so an agency with its own
    WABA could never complete setup against a single global token. Accepting any
    configured one is safe: the exchange only echoes back a challenge Meta
    itself sent.
    """
    monkeypatch.setenv("WHATSAPP_VERIFY_AGENCY_B", "b-handshake-token")
    await _seed_agency_b(verify_token_ref="WHATSAPP_VERIFY_AGENCY_B")
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE channel_routes SET channel = :c WHERE org_id = :i"),
            {"c": CHANNEL_WHATSAPP, "i": AGENCY_B},
        )
        await db.commit()
    try:
        tokens = await known_verify_tokens(CHANNEL_WHATSAPP)
        assert "b-handshake-token" in tokens
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_email_self_loop_guard_uses_the_agencys_own_address(
    monkeypatch,
) -> None:
    """A global guard tests against somebody else's address.

    Agency B's own bounces would sail past it and the assistant would answer
    itself in a loop, while a genuine message from agency A's address would be
    dropped inside agency B.
    """
    monkeypatch.setenv("RESEND_KEY_AGENCY_B", "b-resend-key")
    await _seed_agency_b(
        credential_ref="RESEND_KEY_AGENCY_B", sender_override=B_MAILBOX
    )
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "UPDATE channel_routes SET channel = :c, destination = :d "
                "WHERE org_id = :i"
            ),
            {"c": CHANNEL_EMAIL, "d": B_MAILBOX, "i": AGENCY_B},
        )
        await db.commit()
    tenant_resolver.reset_cache()
    try:
        with org_scope(AGENCY_B):
            identity = await resolve_outbound_identity(CHANNEL_EMAIL)
        assert identity.sender_override == B_MAILBOX
        assert identity.credential == "b-resend-key"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_unmapped_destination_is_refused_once_the_agency_owns_its_account(
    monkeypatch,
) -> None:
    """The single-tenant fallback must stop where the shared secret stops.

    With one routable agency, an unmapped destination fell through to that
    agency. But the *secret* used to verify such a message is the operator's
    global one — so whoever holds it (staff of a churned or suspended tenant
    who had console access to the shared provider account) could post a validly
    signed message with an unmapped `To` and have a lead, a transcript and an
    AI reply appear inside the live agency, with the reply sent from their
    number. The principal that proved authenticity was not the tenant receiving
    the write.
    """
    monkeypatch.setenv("TWILIO_TOKEN_AGENCY_B", "b-token")
    monkeypatch.setenv("TWILIO_INBOUND_AGENCY_B", "b-token")
    async with get_bypass_session_factory()() as db:
        # Client zero is suspended so exactly one agency is routable, which is
        # the state every install has after onboarding its first client.
        await db.execute(
            text("UPDATE organizations SET status = 'suspended' WHERE id = :i"),
            {"i": DEFAULT_ORG_ID},
        )
        await db.commit()
    # `inbound_secret_ref` is what decides this, not `credential_ref`: the
    # question is whether the agency authenticated the message, and that is the
    # inbound secret. Keying it on the outbound credential left the guard inert
    # for an agency with its own Meta app still replying through the shared
    # account, and made it refuse wrongly for the reverse.
    await _seed_agency_b(
        credential_ref="TWILIO_TOKEN_AGENCY_B",
        inbound_secret_ref="TWILIO_INBOUND_AGENCY_B",
    )
    try:
        # Their own number still routes.
        assert await tenant_resolver.webhook_org_or_refuse(CHANNEL_SMS, B_NUMBER) == (
            AGENCY_B
        )
        # An unmapped one does not fall through to them.
        with pytest.raises(tenant_resolver.WebhookOrgUnresolved):
            await tenant_resolver.webhook_org_or_refuse(CHANNEL_SMS, "+19998887777")
    finally:
        await _cleanup()
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE organizations SET status = 'active' WHERE id = :i"),
                {"i": DEFAULT_ORG_ID},
            )
            await db.commit()
        tenant_resolver.reset_cache()


@pytest.mark.asyncio
async def test_the_fallback_still_works_for_an_agency_on_the_shared_account() -> None:
    """The refusal above must not break the ordinary single-customer install,
    which has no routes at all and relies on that fallback for every message.

    Asserts the state it depends on first. Reading `webhook_org_or_refuse` alone
    made this the tripwire for any other test that leaked an organization: the
    failure surfaced here, in a file that had nothing to do with the leak.
    """
    routable = tenant_resolver.routable_candidates(await tenant_resolver.active_orgs())
    assert routable == [DEFAULT_ORG_ID], (
        f"another test leaked an organization: {routable}"
    )
    assert await tenant_resolver.webhook_org_or_refuse(CHANNEL_SMS, "+19998887777") == (
        DEFAULT_ORG_ID
    )


@pytest.mark.asyncio
async def test_an_inbound_only_agency_keeps_its_own_signing_secret(
    monkeypatch,
) -> None:
    """Its own Meta app, replies still through the shared account.

    A supported configuration — `set_route_identity` invites it by clearing
    unnamed fields — and the one where the fallback guard was inert. Reading
    only `credential_ref` discarded the agency's `inbound_secret_ref`, so their
    genuine traffic failed verification against the operator's secret while a
    message signed with that shared secret sailed straight into their tenant.
    """
    monkeypatch.setenv("WA_APP_SECRET_AGENCY_B", "b-app-secret")
    await _seed_agency_b(inbound_secret_ref="WA_APP_SECRET_AGENCY_B")
    try:
        with org_scope(AGENCY_B):
            identity = await resolve_outbound_identity(CHANNEL_SMS)
        # Theirs for verifying...
        assert identity.inbound_secret == "b-app-secret"
        # ...and the operator's for sending, which is what they asked for.
        from app.config import get_settings

        assert identity.credential == (get_settings().TWILIO_AUTH_TOKEN or None)
        assert not identity.is_own_account

        # And the fallback refuses for them, because the shared secret is no
        # longer their authority.
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE organizations SET status = 'suspended' WHERE id = :i"),
                {"i": DEFAULT_ORG_ID},
            )
            await db.commit()
        tenant_resolver.reset_cache()
        with pytest.raises(tenant_resolver.WebhookOrgUnresolved):
            await tenant_resolver.webhook_org_or_refuse(CHANNEL_SMS, "+19998887777")
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE organizations SET status = 'active' WHERE id = :i"),
                {"i": DEFAULT_ORG_ID},
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_an_outbound_only_agency_is_not_refused(monkeypatch) -> None:
    """The mirror case: inbound genuinely still signed by the operator.

    Refusing here drops real leads for a configuration that is perfectly
    authentic. The example is WhatsApp on purpose — Meta's app secret and
    access token are different things, so owning the token says nothing about
    who signs. For Twilio they are one value, and an agency naming it *does*
    verify with its own secret, so the fallback correctly refuses there; that
    is the case above.
    """
    monkeypatch.setenv("WA_TOKEN_AGENCY_B", "b-access-token")
    await _seed_agency_b(credential_ref="WA_TOKEN_AGENCY_B")
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE channel_routes SET channel = :c WHERE org_id = :i"),
            {"c": CHANNEL_WHATSAPP, "i": AGENCY_B},
        )
        await db.commit()
    tenant_resolver.reset_cache()
    try:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE organizations SET status = 'suspended' WHERE id = :i"),
                {"i": DEFAULT_ORG_ID},
            )
            await db.commit()
        tenant_resolver.reset_cache()
        assert await tenant_resolver.webhook_org_or_refuse(
            CHANNEL_WHATSAPP, "999000111"
        ) == AGENCY_B
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE organizations SET status = 'active' WHERE id = :i"),
                {"i": DEFAULT_ORG_ID},
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_two_numbers_on_one_channel_each_verify_with_their_own_secret(
    monkeypatch,
) -> None:
    """An agency may hold two numbers on one channel — only `(channel,
    destination)` is unique, not `(channel, org)`.

    Identity resolution picked the lowest-id route regardless, so inbound to
    the second number was verified against the first one's secret: the HMAC
    fails, the message 403s, and a real lead is dropped with nothing to explain
    it. The destination now selects the row.
    """
    second_number = "+13035554321"
    monkeypatch.setenv("WA_SECRET_LINE_ONE", "secret-one")
    monkeypatch.setenv("WA_SECRET_LINE_TWO", "secret-two")
    await _seed_agency_b(inbound_secret_ref="WA_SECRET_LINE_ONE")
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO channel_routes "
                "(org_id, channel, destination, inbound_secret_ref) "
                "VALUES (:o, :c, :d, 'WA_SECRET_LINE_TWO')"
            ),
            {
                "o": AGENCY_B,
                "c": CHANNEL_SMS,
                "d": normalize_destination(second_number),
            },
        )
        await db.commit()
    tenant_resolver.reset_cache()
    try:
        first = await resolve_inbound_secret(CHANNEL_SMS, B_NUMBER)
        second = await resolve_inbound_secret(CHANNEL_SMS, second_number)
        assert first.inbound_secret == "secret-one"
        assert second.inbound_secret == "secret-two", (
            "the second number was verified against the first one's secret"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_destination_the_agency_does_not_own_yields_the_global_identity(
    monkeypatch,
) -> None:
    """"Not yours" must answer the shared configuration, never a sibling route.

    Defensive: the inbound path resolves the org *from* a matching route, so
    today nothing calls this with a foreign destination. But the previous shape
    fell back to the agency's whole row set and re-picked the lowest-id route's
    secret — the round-12 defect, one caller away.
    """
    monkeypatch.setenv("WA_SECRET_OWNED", "owned-secret")
    monkeypatch.setattr(
        __import__("app.config", fromlist=["get_settings"]).get_settings(),
        "TWILIO_AUTH_TOKEN",
        "the-operators-token",
    )
    await _seed_agency_b(inbound_secret_ref="WA_SECRET_OWNED")
    try:
        with org_scope(AGENCY_B):
            theirs = await resolve_outbound_identity(
                CHANNEL_SMS, destination=B_NUMBER
            )
            foreign = await resolve_outbound_identity(
                CHANNEL_SMS, destination="+19995551111"
            )
        assert theirs.inbound_secret == "owned-secret"
        assert foreign.inbound_secret == "the-operators-token", (
            "a destination the agency does not own borrowed one of its routes"
        )
        assert foreign.destination != theirs.destination
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_sms_route_verifies_with_the_token_it_already_names(
    monkeypatch,
) -> None:
    """Twilio signs inbound with the same auth token used to send.

    So a route naming `credential_ref` and leaving `inbound_secret_ref` NULL is
    the natural onboarding shape — and it silently 403'd every inbound message
    for that agency as Twilio error 11200, which `_validate_refs` cannot detect
    because both fields are individually valid. It reuses what the same row
    already names, never the operator's.
    """
    from app.config import get_settings

    monkeypatch.setenv("TWILIO_TOKEN_ONLY", "their-own-token")
    monkeypatch.setattr(get_settings(), "TWILIO_AUTH_TOKEN", "the-operators-token")
    await _seed_agency_b(credential_ref="TWILIO_TOKEN_ONLY")
    try:
        identity = await resolve_inbound_secret(CHANNEL_SMS, B_NUMBER)
        assert identity.inbound_secret == "their-own-token"
        assert identity.inbound_secret != "the-operators-token"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_sms_agency_on_its_own_token_is_not_handed_unmapped_traffic(
    monkeypatch,
) -> None:
    """The round-13 guard, for the natural SMS onboarding shape.

    Twilio's auth token is both the sending credential and the inbound signing
    secret, so a route naming only `credential_ref` verifies with its own key.
    The guard asked whether `inbound_secret_ref` was set, answered no, and left
    the fallback open for exactly the agency it exists to protect: a message
    signed with the *operator's* global token would have been filed into theirs.
    """
    monkeypatch.setenv("TWILIO_TOKEN_OWN", "their-own-token")
    await _seed_agency_b(credential_ref="TWILIO_TOKEN_OWN")
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE organizations SET status = 'suspended' WHERE id = :i"),
            {"i": DEFAULT_ORG_ID},
        )
        await db.commit()
    tenant_resolver.reset_cache()
    try:
        assert await tenant_resolver.webhook_org_or_refuse(CHANNEL_SMS, B_NUMBER) == (
            AGENCY_B
        )
        with pytest.raises(tenant_resolver.WebhookOrgUnresolved):
            await tenant_resolver.webhook_org_or_refuse(CHANNEL_SMS, "+19998887777")
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE organizations SET status = 'active' WHERE id = :i"),
                {"i": DEFAULT_ORG_ID},
            )
            await db.commit()
        await _cleanup()
