"""Who is a platform operator, and who merely holds an admin session.

These sit below the routes in `test_platform_routes.py`: that file asks whether
the gate rejects the wrong caller, this one asks whether the right caller can
ever get in, and whether the fences around the operator's own tools hold.

Every case here comes from an audit finding where the answer was no.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.v1.auth import COOKIE_NAME
from app.db.base import get_bypass_session_factory
from app.models.organization import DEFAULT_ORG_ID, DEMO_ORG_ID
from app.services import tenant_resolver
from app.services.auth import decode_token, make_token

SECOND_ORG_ID = 610
SECOND_SLUG = "second-agency-access"


def _fake_settings(**overrides) -> SimpleNamespace:
    """A stand-in for Settings covering only what the auth routes read."""
    base = dict(
        AUTH_ENABLED=True,
        AUTH_SECRET="platform-access-test-secret",
        AUTH_TTL_HOURS=168,
        DASHBOARD_PASSWORD="office-password",
        COOKIE_SECURE=False,
        GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com",
        GOOGLE_ALLOWED_DOMAIN="",
        google_admin_emails_list=[],
        google_allowed_emails_list=[],
        platform_admin_emails_list=[],
        is_production=False,
        REGISTRATION_ENABLED=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


async def _client(**cookies) -> AsyncClient:
    from app.main import app

    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies=cookies
    )


async def _make_org(org_id: int, slug: str, status: str = "active") -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, plan) "
                "VALUES (:i, :n, :s, :st, 'pilot') ON CONFLICT (id) DO UPDATE "
                "SET status = EXCLUDED.status"
            ),
            {"i": org_id, "n": slug, "s": slug, "st": status},
        )
        await db.commit()
    tenant_resolver.reset_cache()


async def _drop_org(org_id: int) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM allowed_users WHERE org_id = :i"), {"i": org_id})
        await db.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org_id})
        await db.commit()
    tenant_resolver.reset_cache()


async def _set_status(org_id: int, status: str) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE organizations SET status = :s WHERE id = :i"),
            {"s": status, "i": org_id},
        )
        await db.commit()
    tenant_resolver.reset_cache()


@pytest.fixture(autouse=True)
def _auth_on(monkeypatch) -> object:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "AUTH_ENABLED", True)
    monkeypatch.setattr(get_settings(), "AUTH_SECRET", "platform-access-test-secret")
    # The platform gate re-reads the operator list on every request, so a
    # token is not enough on its own — designating the caller is part of the
    # configuration these tests are exercising.
    monkeypatch.setattr(
        get_settings(), "PLATFORM_ADMIN_EMAILS", "op@eko.com"
    )
    yield
    tenant_resolver.reset_cache()


# ── N1: there has to BE a way to become an operator ──────────────────────────


@pytest.mark.asyncio
async def test_a_platform_admin_email_signing_in_gets_the_superuser_claim() -> None:
    """Before this, the only issuer of `su` was the shared-password login.

    docs/setup-google-signin.md tells a Google-only deployment to set
    DASHBOARD_PASSWORD to a random string nobody knows — so in the configuration
    the docs recommend, no platform token could ever exist and onboarding a
    second agency was impossible. The gate was correct and unreachable.
    """
    fake = _fake_settings(
        platform_admin_emails_list=["operator@eko.com"],
        google_admin_emails_list=["operator@eko.com"],
    )
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake), \
         patch("app.api.v1.auth.verify_google_id_token", return_value="operator@eko.com"), \
         patch("app.api.v1.auth.resolve_email_access", return_value="admin"):
        async with await _client() as c:
            r = await c.post("/api/v1/auth/login/google", json={"id_token": "tok"})

    assert r.status_code == 200, r.text
    cookie = r.headers.get("set-cookie", "")
    token = cookie.split(f"{COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    with patch("app.services.auth.get_settings", return_value=fake):
        claims = decode_token(token)
    assert claims is not None
    assert claims.get("su") is True, "a listed operator did not receive platform access"


@pytest.mark.asyncio
async def test_an_ordinary_admin_signing_in_does_not_get_the_superuser_claim() -> None:
    """The list is the whole boundary; being an org admin is not enough."""
    fake = _fake_settings(
        platform_admin_emails_list=["operator@eko.com"],
        google_admin_emails_list=["natalia@agency.com"],
    )
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake), \
         patch("app.api.v1.auth.verify_google_id_token", return_value="natalia@agency.com"), \
         patch("app.api.v1.auth.resolve_email_access", return_value="admin"):
        async with await _client() as c:
            r = await c.post("/api/v1/auth/login/google", json={"id_token": "tok"})

    assert r.status_code == 200, r.text
    token = r.headers["set-cookie"].split(f"{COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    with patch("app.services.auth.get_settings", return_value=fake):
        claims = decode_token(token)
    assert claims.get("su") is not True


@pytest.mark.asyncio
async def test_the_shared_password_is_never_a_platform_key() -> None:
    """Not even as a fallback when no operator is configured.

    That fallback is how C1 came back. `DASHBOARD_PASSWORD` is the agency's
    password — install.sh calls it "protects /leads" and the office shares it
    with whoever answers the phone — and PLATFORM_ADMIN_EMAILS is empty by
    default, so client zero's receptionist could list every tenant, read every
    agency's routed numbers and impersonate into any of them. Through the front
    door, with no attack.

    There is no lockout to trade against: an operator with no
    PLATFORM_ADMIN_EMAILS set has an empty platform, and setting an environment
    variable is something only they can do.
    """
    for configured in ([], ["operator@eko.com"]):
        fake = _fake_settings(platform_admin_emails_list=configured)
        with patch("app.api.v1.auth.get_settings", return_value=fake), \
             patch("app.services.auth.get_settings", return_value=fake):
            async with await _client() as c:
                r = await c.post(
                    "/api/v1/auth/login", json={"password": "office-password"}
                )
            assert r.status_code == 200, r.text
            token = r.headers["set-cookie"].split(f"{COOKIE_NAME}=", 1)[1]
            token = token.split(";", 1)[0]
            assert decode_token(token).get("su") is not True, (
                f"the shared password minted platform access "
                f"(PLATFORM_ADMIN_EMAILS={configured})"
            )


# ── N3: access and organization are resolved separately, both must succeed ───


@pytest.mark.asyncio
async def test_an_allowed_email_with_no_organization_is_refused() -> None:
    """`resolve_email_access` can say yes from env alone — GOOGLE_ALLOWED_DOMAIN.

    The org half used to fall back to DEFAULT_ORG_ID for anyone without an
    `allowed_users` row, so setting that domain to a second agency while
    onboarding them signed their whole staff in as members of the *first*
    agency, reading its leads. The two answers are never cross-checked, so the
    org side has to fail closed on its own.
    """
    fake = _fake_settings(GOOGLE_ALLOWED_DOMAIN="agency-b.com")
    with patch("app.api.v1.auth.get_settings", return_value=fake), \
         patch("app.services.auth.get_settings", return_value=fake), \
         patch("app.api.v1.auth.verify_google_id_token", return_value="new.hire@agency-b.com"), \
         patch("app.api.v1.auth.resolve_email_access", return_value="member"):
        async with await _client() as c:
            r = await c.post("/api/v1/auth/login/google", json={"id_token": "tok"})

    assert r.status_code == 401, r.text
    assert COOKIE_NAME not in r.headers.get("set-cookie", "")


# ── N4: the demo org is public, so it must never receive real traffic ────────


@pytest.mark.asyncio
async def test_a_route_cannot_be_pointed_at_the_demo_org() -> None:
    """`POST /auth/register` drops any anonymous visitor into the demo org as a
    viewer. A live destination mapped there publishes the lead's phone number
    and their whole transcript, and org ids are small integers to mistype."""
    token = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    async with await _client(**{COOKIE_NAME: token}) as c:
        r = await c.post(
            "/api/v1/platform/routes",
            json={
                "org_id": DEMO_ORG_ID,
                "channel": "sms",
                "destination": "+13035550123",
            },
        )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "cannot_route_to_demo_org"


@pytest.mark.asyncio
async def test_an_existing_route_to_the_demo_org_still_refuses_inbound() -> None:
    """Defence in depth for rows that predate the guard or arrive via SQL.

    The demo exclusion lived only on the fallback branch, so once a destination
    matched a route the resolver returned it without ever asking which org it
    was — and the test that claimed to cover this only exercised the fallback.
    """
    from app.models.channel_route import normalize_destination

    dest = normalize_destination("+13035559999")
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO channel_routes (org_id, channel, destination) "
                "VALUES (:o, 'sms', :d) ON CONFLICT DO NOTHING"
            ),
            {"o": DEMO_ORG_ID, "d": dest},
        )
        await db.commit()
    try:
        with pytest.raises(tenant_resolver.WebhookOrgUnresolved):
            await tenant_resolver.webhook_org_or_refuse("sms", "+1 303 555 9999")
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM channel_routes WHERE destination = :d"), {"d": dest}
            )
            await db.commit()


# ── N6: the operator must not be able to lock themselves out ─────────────────


@pytest.mark.asyncio
async def test_an_operator_can_undo_suspending_their_own_organization() -> None:
    """The operator's token names organization 1 like everyone else's.

    Suspending it — one PATCH, no confirmation — used to 403 every subsequent
    request from that session *including the one that would undo it*, because
    the suspension gate runs in the middleware before any route. Recovery meant
    direct database access.
    """
    token = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    try:
        async with await _client(**{COOKIE_NAME: token}) as c:
            suspend = await c.patch(
                f"/api/v1/platform/organizations/{DEFAULT_ORG_ID}",
                json={"status": "suspended"},
            )
            assert suspend.status_code == 200, suspend.text

            back = await c.patch(
                f"/api/v1/platform/organizations/{DEFAULT_ORG_ID}",
                json={"status": "active"},
            )
        assert back.status_code == 200, (
            f"operator locked out of their own recovery route: {back.text}"
        )
    finally:
        await _set_status(DEFAULT_ORG_ID, "active")


@pytest.mark.asyncio
async def test_impersonation_can_still_enter_a_suspended_agency() -> None:
    """A suspended agency is exactly when an operator needs to look inside.

    The impersonation token is deliberately *not* a superuser one, so without
    its own mark it hit the same suspension wall on the very next request — the
    endpoint's docstring promised access it did not deliver.
    """
    await _make_org(SECOND_ORG_ID, SECOND_SLUG, status="suspended")
    operator = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    try:
        async with await _client(**{COOKIE_NAME: operator}) as c:
            entered = await c.post(f"/api/v1/platform/impersonate/{SECOND_ORG_ID}")
            assert entered.status_code == 200, entered.text
            scoped = entered.headers["set-cookie"].split(f"{COOKIE_NAME}=", 1)[1]
            scoped = scoped.split(";", 1)[0]

        async with await _client(**{COOKIE_NAME: scoped}) as c:
            inside = await c.get("/api/v1/leads")
        assert inside.status_code != 403, (
            "impersonating a suspended agency 403s on the next request"
        )
    finally:
        await _drop_org(SECOND_ORG_ID)


# ── N9: auth off pins every request to one org, so one org is all there may be ─


@pytest.mark.asyncio
async def test_single_tenant_mode_refuses_to_serve_a_second_agency(monkeypatch) -> None:
    """AUTH_ENABLED=false is the docker-compose default, and it resolves every
    request to organization 1 regardless of who sent it. Seeding a second agency
    made their dashboard unreachable and every write they made land in the
    first. The comment said "exactly one tenant is expected"; nothing enforced
    it."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "AUTH_ENABLED", False)
    await _make_org(SECOND_ORG_ID, SECOND_SLUG)
    try:
        with pytest.raises(tenant_resolver.SingleTenantModeViolated):
            await tenant_resolver.resolve_org_for_request("/api/v1/leads", None)
    finally:
        await _drop_org(SECOND_ORG_ID)

    # And with the second agency gone it goes back to working, rather than
    # leaving a single-customer install permanently refusing.
    assert (
        await tenant_resolver.resolve_org_for_request("/api/v1/leads", None)
        == DEFAULT_ORG_ID
    )


# ── N10: an invite must mean what the operator typed ─────────────────────────


@pytest.mark.asyncio
async def test_a_read_only_invite_is_rejected_rather_than_silently_promoted() -> None:
    """`viewer` is a role of `accounts`, not of `allowed_users`.

    `resolve_email_access` reads anything that is not "admin" as a member, so
    inviting a read-only auditor as `viewer` handed them write access to the
    agency's leads while the operator believed otherwise.
    """
    token = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    await _make_org(SECOND_ORG_ID, SECOND_SLUG)
    try:
        async with await _client(**{COOKIE_NAME: token}) as c:
            r = await c.post(
                f"/api/v1/platform/organizations/{SECOND_ORG_ID}/members",
                json={"email": "auditor@agency.com", "role": "viewer"},
            )
        assert r.status_code == 422, r.text
    finally:
        await _drop_org(SECOND_ORG_ID)


@pytest.mark.asyncio
async def test_a_malformed_invite_email_does_not_consume_the_slot() -> None:
    """`allowed_users.email` is globally unique, so a typo permanently occupies
    the address it was meant to be, removable only by an admin of that org —
    who may be the person being invited."""
    token = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    await _make_org(SECOND_ORG_ID, SECOND_SLUG)
    try:
        async with await _client(**{COOKIE_NAME: token}) as c:
            r = await c.post(
                f"/api/v1/platform/organizations/{SECOND_ORG_ID}/members",
                json={"email": "not-an-email", "role": "member"},
            )
        assert r.status_code == 400, r.text

        async with get_bypass_session_factory()() as db:
            left = (
                await db.execute(
                    text("SELECT count(*) FROM allowed_users WHERE org_id = :i"),
                    {"i": SECOND_ORG_ID},
                )
            ).scalar_one()
        assert left == 0
    finally:
        await _drop_org(SECOND_ORG_ID)


@pytest.mark.asyncio
async def test_inviting_into_a_suspended_agency_is_refused_not_silently_useless() -> None:
    """The row would be created and the sign-in would then 403 at the
    suspension gate, which reads as "the invite did nothing"."""
    token = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    await _make_org(SECOND_ORG_ID, SECOND_SLUG, status="suspended")
    try:
        async with await _client(**{COOKIE_NAME: token}) as c:
            r = await c.post(
                f"/api/v1/platform/organizations/{SECOND_ORG_ID}/members",
                json={"email": "someone@agency.com", "role": "member"},
            )
        assert r.status_code == 409, r.text
    finally:
        await _drop_org(SECOND_ORG_ID)


# ── N7: an invalidation must not be undone by a read that started before it ──


@pytest.mark.asyncio
async def test_a_read_in_flight_during_an_invalidation_does_not_restore_it() -> None:
    """`active_orgs` is a check-then-act across an await.

    A read that sampled the database before a tenant was created, and wrote its
    snapshot back after `reset_cache()` ran, kept the new agency invisible for a
    further 15 seconds. During that window `webhook_org_or_refuse` sees a single
    candidate and files their unrouted inbound message into the first agency —
    a permanent cross-tenant write that the cache expiring does not undo.
    """
    import asyncio
    import contextlib

    tenant_resolver.reset_cache()
    before = await tenant_resolver.active_orgs()
    assert SECOND_ORG_ID not in before

    released = asyncio.Event()
    sampled = asyncio.Event()

    class _StaleResult:
        def all(self) -> list[tuple[int, str]]:
            return [(k, v) for k, v in before.items()]

    class _StaleSession:
        async def execute(self, *_a, **_kw) -> _StaleResult:
            # The database has been read; the snapshot is now pre-creation.
            sampled.set()
            await released.wait()
            return _StaleResult()

    @contextlib.asynccontextmanager
    async def _stale_factory_cm():
        yield _StaleSession()

    def _stale_factory():
        return _stale_factory_cm

    tenant_resolver.reset_cache()
    with patch("app.db.base.get_bypass_session_factory", _stale_factory):
        racing = asyncio.create_task(tenant_resolver.active_orgs())
        await asyncio.wait_for(sampled.wait(), timeout=5)

        # The tenant is created *after* that read sampled the database.
        await _make_org(SECOND_ORG_ID, SECOND_SLUG)

        # Now let the racing read finish and install its snapshot.
        released.set()
        stale = await asyncio.wait_for(racing, timeout=5)
    assert SECOND_ORG_ID not in stale  # correct: it did not exist when it read

    try:
        fresh = await tenant_resolver.active_orgs()
        assert SECOND_ORG_ID in fresh, (
            "a snapshot taken before the invalidation was written back after it, "
            "hiding the new tenant for a further TTL"
        )
    finally:
        await _drop_org(SECOND_ORG_ID)


# ── Round 8: the boundary has to exist in the configuration that ships ───────


@pytest.mark.asyncio
async def test_platform_routes_are_not_anonymous_when_auth_is_off(monkeypatch) -> None:
    """`AUTH_ENABLED=false` is the docker-compose default, and it turns
    `require_admin` into a no-op — which turned every platform route into an
    unauthenticated one.

    An anonymous POST could create an organization, and doing so then made the
    resolver refuse every request in the install, including the route that
    would undo it. Creating tenants is not something an unauthenticated caller
    does in any configuration.
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "AUTH_ENABLED", False)
    try:
        async with await _client() as c:
            listed = await c.get("/api/v1/platform/organizations")
            created = await c.post(
                "/api/v1/platform/organizations",
                json={"name": "Rogue", "slug": "rogue-anon"},
            )
        assert listed.status_code == 403, listed.text
        assert created.status_code == 403, created.text
    finally:
        # Cleaned up even when the assertion fails, because if it ever does the
        # row is exactly the one that bricks the deployment: a second active org
        # with auth off makes the resolver refuse every subsequent request. That
        # is not a hypothetical — reverting this fix to check the test bites
        # left the row behind and the whole suite went 503.
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM organizations WHERE slug = 'rogue-anon'")
            )
            await db.commit()
        tenant_resolver.reset_cache()


@pytest.mark.asyncio
async def test_an_operator_email_outranks_a_row_another_agency_planted() -> None:
    """`allowed_users.email` is globally unique and any agency's admin can add a
    row through the ordinary team page.

    So agency B's admin could add the operator's own address to *their* org. The
    operator's next sign-in would then resolve `member` from that row while the
    platform list still granted the org — minting a session that
    `require_platform_admin` rejects, locking the operator out of the platform
    for good with one authenticated POST and no route able to undo it.
    """
    from app.models import AllowedUser
    from app.services.auth import ROLE_ADMIN, resolve_email_access

    fake = _fake_settings(platform_admin_emails_list=["operator@eko.com"])
    await _make_org(SECOND_ORG_ID, SECOND_SLUG)
    try:
        async with get_bypass_session_factory()() as db:
            db.add(
                AllowedUser(
                    email="operator@eko.com",
                    role="member",
                    added_by="agency-b-admin",
                    org_id=SECOND_ORG_ID,
                )
            )
            await db.commit()

            with patch("app.services.auth.get_settings", return_value=fake):
                assert await resolve_email_access("operator@eko.com", db) == ROLE_ADMIN
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM allowed_users WHERE email = 'operator@eko.com'")
            )
            await db.commit()
        await _drop_org(SECOND_ORG_ID)


@pytest.mark.asyncio
async def test_an_operator_can_free_an_email_another_agency_is_holding() -> None:
    """The other half: the row still has to be removable.

    The team router's delete runs under RLS and cannot see a row in someone
    else's organization, and the platform router could only ever invite — so a
    squatted address was permanent, and the remedy was psql.
    """
    from app.models import AllowedUser

    token = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    await _make_org(SECOND_ORG_ID, SECOND_SLUG)
    try:
        async with get_bypass_session_factory()() as db:
            # The squatting agency has an admin of its own, as any operating
            # agency does — freeing the squat must not disturb it.
            db.add(
                AllowedUser(
                    email="real.admin@agency-b.test",
                    role="admin",
                    added_by="platform",
                    org_id=SECOND_ORG_ID,
                )
            )
            db.add(
                AllowedUser(
                    email="owner@agency-a.test",
                    role="admin",
                    added_by="agency-b-admin",
                    org_id=SECOND_ORG_ID,
                )
            )
            await db.commit()

        async with await _client(**{COOKIE_NAME: token}) as c:
            freed = await c.delete("/api/v1/platform/members/Owner@Agency-A.test")
            assert freed.status_code == 200, freed.text
            assert freed.json()["was_held_by_org"] == SECOND_ORG_ID
            # And it is gone, so the rightful organization can claim it.
            assert (
                await c.delete("/api/v1/platform/members/owner@agency-a.test")
            ).status_code == 404

            # Their own admin is untouched, and removing THAT one is refused —
            # an agency with no admin cannot reach /settings or /team, so its
            # staff are locked out of their own dashboard.
            last = await c.delete("/api/v1/platform/members/real.admin@agency-b.test")
            assert last.status_code == 409, last.text
            assert last.json()["detail"]["error"] == (
                "would_leave_organization_without_an_admin"
            )
            # Unless the operator says so explicitly: the squat and the last
            # admin can be the same row, and refusing outright would make the
            # squat permanent again.
            forced = await c.delete(
                "/api/v1/platform/members/real.admin@agency-b.test?force=true"
            )
            assert forced.status_code == 200, forced.text
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text(
                    "DELETE FROM allowed_users WHERE email IN "
                    "('owner@agency-a.test', 'real.admin@agency-b.test')"
                )
            )
            await db.commit()
        await _drop_org(SECOND_ORG_ID)


@pytest.mark.asyncio
async def test_a_route_cannot_reference_a_deployment_secret() -> None:
    """The referenced value is sent to the provider as a bearer token.

    Pointing a route at AUTH_SECRET or DATABASE_URL would post the deployment's
    own secrets to Twilio or Meta. The operator is trusted, but this is one
    typo away and a typo has no undo.
    """
    from app.models.channel_route import CHANNEL_SMS, normalize_destination

    token = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    await _make_org(SECOND_ORG_ID, SECOND_SLUG)
    try:
        async with await _client(**{COOKIE_NAME: token}) as c:
            created = await c.post(
                "/api/v1/platform/routes",
                json={
                    "org_id": SECOND_ORG_ID,
                    "channel": CHANNEL_SMS,
                    "destination": "+13035558123",
                },
            )
            assert created.status_code == 201, created.text
            route_id = created.json()["id"]

            blocked = await c.patch(
                f"/api/v1/platform/routes/{route_id}/identity",
                json={"credential_ref": "AUTH_SECRET"},
            )
        assert blocked.status_code == 400, blocked.text
        assert blocked.json()["detail"]["error"] == "refers_to_a_deployment_secret"
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM channel_routes WHERE destination = :d"),
                {"d": normalize_destination("+13035558123")},
            )
            await db.commit()
        await _drop_org(SECOND_ORG_ID)


# ── Round 9: the claim is only as good as the key that signs it ──────────────


def test_the_signing_key_is_never_derived_from_the_agencys_password() -> None:
    """The platform boundary is an HMAC, so it is worth exactly what its key is.

    The key used to fall back to `sha256("eko-auth::" + DASHBOARD_PASSWORD)`.
    That password is the *agency's* — install.sh calls it "protects /leads" and
    the office shares it with whoever answers the phone — so its holder could
    derive the key offline and sign themselves a token claiming `su` and any
    organization they liked. Removing `superuser=True` from the password login
    achieved nothing while that stood: the same person could mint the claim.
    """
    from app.config import get_settings
    from app.services.auth import InsecureAuthConfig, _secret

    s = get_settings()
    with patch.object(s, "AUTH_ENABLED", True), \
         patch.object(s, "AUTH_SECRET", ""), \
         patch.object(s, "DASHBOARD_PASSWORD", "office-password"):
        with pytest.raises(InsecureAuthConfig):
            _secret()

    # And with a real secret it does not mix the password in, so changing the
    # office password cannot silently invalidate or weaken every session.
    with patch.object(s, "AUTH_ENABLED", True), \
         patch.object(s, "AUTH_SECRET", "a-real-secret"), \
         patch.object(s, "DASHBOARD_PASSWORD", "office-password"):
        first = _secret()
    with patch.object(s, "AUTH_ENABLED", True), \
         patch.object(s, "AUTH_SECRET", "a-real-secret"), \
         patch.object(s, "DASHBOARD_PASSWORD", "a-different-password"):
        assert _secret() == first


@pytest.mark.asyncio
async def test_a_token_forged_with_the_dev_key_reaches_nothing(monkeypatch) -> None:
    """With auth off the key is a constant published in this repository.

    Anyone could compute sha256(b"eko-auth::insecure-dev-only"), sign
    {"role":"admin","org":1,"su":true}, and — while the gate trusted the claim
    alone — read every tenant, re-point another agency's phone number at an org
    they created, and impersonate into any of them. The gate refuses in this
    mode outright, because a signature nobody has to know is not evidence.
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "AUTH_ENABLED", False)
    # Forged AS a designated operator. Their address is not a secret — it is in
    # the deployment's own configuration and on their business card — so a test
    # that forges some other name would pass on the email check alone and prove
    # nothing about the key.
    monkeypatch.setattr(get_settings(), "PLATFORM_ADMIN_EMAILS", "op@eko.com")
    forged = make_token(
        email="op@eko.com",
        role="admin",
        org_id=DEFAULT_ORG_ID,
        superuser=True,
    )
    async with await _client(**{COOKIE_NAME: forged}) as c:
        for method, path in (
            ("get", "/api/v1/platform/organizations"),
            ("get", "/api/v1/platform/routes"),
            ("post", f"/api/v1/platform/impersonate/{DEFAULT_ORG_ID}"),
        ):
            r = await getattr(c, method)(path)
            assert r.status_code == 403, f"{method.upper()} {path} → {r.status_code}"


@pytest.mark.asyncio
async def test_a_retired_operator_loses_access_on_their_next_request() -> None:
    """The gate re-reads the list rather than trusting the `su` bit.

    Sessions last a week. Trusting the claim alone meant removing someone from
    PLATFORM_ADMIN_EMAILS did nothing until their cookie happened to expire,
    which is not what an operator believes they are doing when they take a name
    off that list.
    """
    from app.config import get_settings

    s = get_settings()
    token = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    async with await _client(**{COOKIE_NAME: token}) as c:
        assert (await c.get("/api/v1/platform/organizations")).status_code == 200

    with patch.object(s, "PLATFORM_ADMIN_EMAILS", "someone.else@eko.com"):
        async with await _client(**{COOKIE_NAME: token}) as c:
            assert (await c.get("/api/v1/platform/organizations")).status_code == 403


@pytest.mark.asyncio
async def test_creating_a_route_validates_refs_the_same_way_patching_does(
    monkeypatch,
) -> None:
    """The denylist lived only on the patch endpoint.

    So the control was bypassed by using the other one: create the route with
    `credential_ref: AUTH_SECRET` and the deployment's signing key is handed to
    Twilio as a basic-auth password on the next reply.
    """
    from app.models.channel_route import CHANNEL_SMS

    token = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    await _make_org(SECOND_ORG_ID, SECOND_SLUG)
    try:
        async with await _client(**{COOKIE_NAME: token}) as c:
            secret = await c.post(
                "/api/v1/platform/routes",
                json={
                    "org_id": SECOND_ORG_ID,
                    "channel": CHANNEL_SMS,
                    "destination": "+13035558200",
                    "credential_ref": "AUTH_SECRET",
                },
            )
            assert secret.status_code == 400, secret.text
            assert secret.json()["detail"]["error"] == "refers_to_a_deployment_secret"

            # The global provider variables are refused too: an agency's
            # credential belongs in a variable of its own, and pointing one
            # agency's route at another's would let that one sign inbound
            # messages into this one.
            # Set, so "not set" cannot be the reason it is refused — that is
            # what made the first version of this assertion pass against a
            # denylist that did not contain the name at all.
            monkeypatch.setenv("TWILIO_AUTH_TOKEN", "the-operators-own-token")
            shared = await c.post(
                "/api/v1/platform/routes",
                json={
                    "org_id": SECOND_ORG_ID,
                    "channel": CHANNEL_SMS,
                    "destination": "+13035558201",
                    "credential_ref": "TWILIO_AUTH_TOKEN",
                },
            )
            assert shared.status_code == 400, shared.text
            assert shared.json()["detail"]["error"] == "refers_to_a_deployment_secret"

            # And a name that is simply not set fails here, not at a lead's
            # first message.
            unset = await c.post(
                "/api/v1/platform/routes",
                json={
                    "org_id": SECOND_ORG_ID,
                    "channel": CHANNEL_SMS,
                    "destination": "+13035558202",
                    "credential_ref": "TWILIO_TOKEN_NOT_SET_ANYWHERE",
                },
            )
            assert unset.status_code == 400, unset.text
            assert unset.json()["detail"]["error"] == "environment_variables_not_set"
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM channel_routes WHERE org_id = :i"),
                {"i": SECOND_ORG_ID},
            )
            await db.commit()
        await _drop_org(SECOND_ORG_ID)


@pytest.mark.asyncio
async def test_a_route_cannot_borrow_another_agencys_credential(monkeypatch) -> None:
    """A credential belongs to one agency.

    The manual onboarding flow is copy-and-edit JSON, so copying agency two's
    route to make agency three's leaves three pointing at two's token — and two
    then holds the secret that authenticates three's inbound messages and can
    inject leads and transcripts into their tenant. The validator's own comment
    claimed this was prevented; nothing checked it.
    """
    from app.models.channel_route import CHANNEL_SMS

    third_org = SECOND_ORG_ID + 1
    monkeypatch.setenv("TWILIO_TOKEN_AGENCY_TWO", "two-token")
    token = make_token(
        email="op@eko.com", role="admin", org_id=DEFAULT_ORG_ID, superuser=True
    )
    await _make_org(SECOND_ORG_ID, SECOND_SLUG)
    await _make_org(third_org, f"{SECOND_SLUG}-three")
    try:
        async with await _client(**{COOKIE_NAME: token}) as c:
            mine = await c.post(
                "/api/v1/platform/routes",
                json={
                    "org_id": SECOND_ORG_ID,
                    "channel": CHANNEL_SMS,
                    "destination": "+13035558300",
                    "credential_ref": "TWILIO_TOKEN_AGENCY_TWO",
                },
            )
            assert mine.status_code == 201, mine.text

            borrowed = await c.post(
                "/api/v1/platform/routes",
                json={
                    "org_id": third_org,
                    "channel": CHANNEL_SMS,
                    "destination": "+13035558301",
                    "credential_ref": "TWILIO_TOKEN_AGENCY_TWO",
                },
            )
            assert borrowed.status_code == 409, borrowed.text
            assert borrowed.json()["detail"]["error"] == (
                "credential_belongs_to_another_organization"
            )

            # And the same check on the patch path, which is where an operator
            # editing an existing route would hit it.
            plain = await c.post(
                "/api/v1/platform/routes",
                json={
                    "org_id": third_org,
                    "channel": CHANNEL_SMS,
                    "destination": "+13035558302",
                },
            )
            assert plain.status_code == 201, plain.text
            patched = await c.patch(
                f"/api/v1/platform/routes/{plain.json()['id']}/identity",
                json={"credential_ref": "TWILIO_TOKEN_AGENCY_TWO"},
            )
            assert patched.status_code == 409, patched.text
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM channel_routes WHERE org_id IN (:a, :b)"),
                {"a": SECOND_ORG_ID, "b": third_org},
            )
            await db.commit()
        await _drop_org(third_org)
        await _drop_org(SECOND_ORG_ID)
