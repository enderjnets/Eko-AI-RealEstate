"""The public form is the only unauthenticated write that is not a webhook.

Every test here goes through `ASGITransport(app)` rather than calling the
service directly, and that is the point rather than a style choice. The suite's
`conftest` binds the default organization into every test by an autouse
fixture — the same fixture that once hid eleven production bugs — so a capture
test that called `capture_lead` itself would be handed, for free, exactly the
thing production does not have: a bound tenant. It would pass while the
endpoint was incapable of writing a row.

Driving the real ASGI stack means `TenantMiddleware` runs first and sets the
organization to None for `/api/v1/public`, so anything that gets written proves
the handler resolved and bound a tenant on its own.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.v1.public import (
    GLOBAL_LIMIT,
    PER_IP_LIMIT,
    client_ip,
    reset_rate_limits,
)
from app.db.base import get_bypass_session_factory
from app.main import app
from app.models.channel_route import CHANNEL_WEB
from app.services import tenant_resolver
from app.services.capture import (
    MAX_ATTRIBUTION_VALUE,
    MAX_MESSAGE,
    clean_attribution,
    clean_text,
    normalize_email,
    normalize_phone,
)

FORM_A = "capture-agency-a"
FORM_B = "capture-agency-b"
FORM_DEMO = "capture-demo-form"
SLUG_A = "capture-agency-a"
SLUG_B = "capture-agency-b"


@pytest.fixture(autouse=True)
def _clean_rate_limits() -> None:
    # Module-level counters would otherwise leak between tests and make the
    # order of the file part of its meaning.
    reset_rate_limits()
    yield
    reset_rate_limits()


async def _post(payload: dict, **headers: str) -> tuple[int, dict]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/public/leads", json=payload, headers=headers or None
        )
    body = response.json() if response.content else {}
    return response.status_code, body


async def _seed(*, agencies: bool = True, demo_route: bool = False) -> tuple[int, int]:
    """Two extra agencies, each with its own form key. Returns their ids."""
    ids: list[int] = []
    async with get_bypass_session_factory()() as db:
        if agencies:
            for slug, form in ((SLUG_A, FORM_A), (SLUG_B, FORM_B)):
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
                    {"o": org_id, "c": CHANNEL_WEB, "d": form},
                )
                ids.append(org_id)
        if demo_route:
            await db.execute(
                text(
                    "INSERT INTO channel_routes (org_id, channel, destination) "
                    "VALUES (2, :c, :d)"
                ),
                {"c": CHANNEL_WEB, "d": FORM_DEMO},
            )
        await db.commit()
    tenant_resolver.reset_cache()
    return (ids[0], ids[1]) if ids else (0, 0)


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        # Leads first and by organization: `organizations` cascades, but the
        # single-tenant leads created against org 1 have no parent to cascade
        # from and would leak into the next test's uniqueness checks.
        # Narrow on purpose. This ran as `phone LIKE '+1999555%'`, which is a
        # strict prefix of test_channel_routing's +19995550000 and of
        # test_consent_gate's MARK — and it runs on the BYPASS session, so it
        # deletes across every tenant with RLS off. It already ate rows a
        # manual browser verification was inspecting. Match only what this file
        # creates.
        await db.execute(
            text("DELETE FROM leads WHERE email LIKE :pat"),
            {"pat": "%@capture.test"},
        )
        await db.execute(
            text("DELETE FROM organizations WHERE slug IN (:a, :b)"),
            {"a": SLUG_A, "b": SLUG_B},
        )
        await db.execute(
            text("DELETE FROM channel_routes WHERE destination = :d"), {"d": FORM_DEMO}
        )
        await db.commit()
    tenant_resolver.reset_cache()


async def _lead_row(email: str) -> dict | None:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(
                text(
                    "SELECT id, org_id, name, phone, email, meta, consent_at, "
                    "consent_text, consent_ip, consent_user_agent "
                    "FROM leads WHERE email = :e"
                ),
                {"e": email},
            )
        ).mappings().first()
    return dict(row) if row else None


# ── Pure input handling ──────────────────────────────────────────────────


def test_phone_normalises_to_one_identifier() -> None:
    # The whole reason this exists: all four are the same person, and if the
    # form stored them differently it would manufacture a duplicate of every
    # lead who later replies by SMS.
    for typed in ("(303) 555-1234", "303-555-1234", "+1 303 555 1234", "0013035551234"):
        assert normalize_phone(typed) == "+13035551234", typed


def test_phone_rejects_what_is_not_a_number() -> None:
    assert normalize_phone("") is None
    assert normalize_phone("hello") is None
    assert normalize_phone("12345") is None  # too short to reach anyone
    assert normalize_phone("1" * 20) is None  # longer than E.164 allows


def test_email_is_structural_not_deliverability() -> None:
    assert normalize_email("  Jane@Example.COM ") == "jane@example.com"
    assert normalize_email("jane@example") is None
    assert normalize_email("not an address") is None
    assert normalize_email("x" * 250 + "@example.com") is None


def test_attribution_keeps_only_the_whitelist() -> None:
    cleaned = clean_attribution(
        {
            "utm_source": "tiktok",
            "utm_content": "denver-washpark-01",
            "evil": "dropped",
            "note": "also dropped",
        }
    )
    assert cleaned == {"utm_source": "tiktok", "utm_content": "denver-washpark-01"}


def test_attribution_caps_value_length() -> None:
    cleaned = clean_attribution({"utm_campaign": "x" * 5_000})
    assert len(cleaned["utm_campaign"]) == MAX_ATTRIBUTION_VALUE


def test_clean_text_caps_and_collapses() -> None:
    assert clean_text("  a   b \n c ", 100) == "a b c"
    assert len(clean_text("x" * 9_000, MAX_MESSAGE)) == MAX_MESSAGE
    assert clean_text("   ", 100) is None
    assert clean_text(None, 100) is None


def test_attribution_survives_junk_input() -> None:
    assert clean_attribution(None) == {}
    assert clean_attribution("not a dict") == {}
    assert clean_attribution({"utm_source": {"nested": "thing"}}) == {}
    assert clean_attribution({"utm_source": True}) == {}


# ── Client address ───────────────────────────────────────────────────────


class _FakeRequest:
    def __init__(self, headers: dict[str, str], host: str | None = "10.0.0.1") -> None:
        self.headers = headers
        self.client = type("C", (), {"host": host})() if host else None


def test_client_ip_prefers_cloudflare_over_forwarded() -> None:
    request = _FakeRequest(
        {"cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "1.2.3.4, 5.6.7.8"}
    )
    assert client_ip(request) == "203.0.113.7"


def test_client_ip_falls_back_through_forwarded_then_socket() -> None:
    assert client_ip(_FakeRequest({"x-forwarded-for": "1.2.3.4, 5.6.7.8"})) == "1.2.3.4"
    assert client_ip(_FakeRequest({})) == "10.0.0.1"
    assert client_ip(_FakeRequest({}, host=None)) == "unknown"


# ── Tenant resolution ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_form_key_is_refused() -> None:
    await _seed()
    try:
        status, _ = await _post(
            {"form": "no-such-form", "email": "ghost@capture.test"}
        )
        assert status == 404
        assert await _lead_row("ghost@capture.test") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_form_mapped_to_the_demo_org_is_refused() -> None:
    # `POST /auth/register` drops any anonymous visitor into the demo org as a
    # viewer, so a lead filed there is a lead published.
    await _seed(agencies=False, demo_route=True)
    try:
        status, _ = await _post({"form": FORM_DEMO, "email": "public@capture.test"})
        assert status == 404
        assert await _lead_row("public@capture.test") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_each_form_key_writes_into_its_own_agency() -> None:
    org_a, org_b = await _seed()
    try:
        assert (await _post({"form": FORM_A, "email": "a@capture.test"}))[0] == 202
        assert (await _post({"form": FORM_B, "email": "b@capture.test"}))[0] == 202
        assert (await _lead_row("a@capture.test"))["org_id"] == org_a
        assert (await _lead_row("b@capture.test"))["org_id"] == org_b
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_no_form_key_is_refused_once_a_second_agency_exists() -> None:
    # The single-tenant fallback is a convenience for an install with one
    # agency. With more than one it is a coin flip, and a coin flip here files
    # somebody's lead in a stranger's dashboard.
    await _seed()
    try:
        status, _ = await _post({"email": "ambiguous@capture.test"})
        assert status == 404
        assert await _lead_row("ambiguous@capture.test") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_single_tenant_install_needs_no_form_key() -> None:
    """Natalia's install has one agency and no routes. It must work as-is.

    Asserting `org_id == 1` alone would be decorative: 1 is exactly what the
    conftest autouse fixture binds, so the assertion cannot tell "the handler
    resolved the single-tenant fallback" from "the fixture leaked". What makes
    it real is that the middleware sets the org to None for this prefix before
    the handler runs — so the row proves the handler resolved a tenant itself.
    Pinned below by asserting the fixture's binding is NOT what reached the
    database: the lead is written against the only routable agency, which the
    seeded-agencies test shows is not always 1.
    """
    try:
        status, _ = await _post({"email": "solo@capture.test", "name": "Solo"})
        assert status == 202
        row = await _lead_row("solo@capture.test")
        assert row is not None
        async with get_bypass_session_factory()() as db:
            only = (
                await db.execute(
                    text(
                        "SELECT id FROM organizations WHERE status = 'active' "
                        "AND id <> 2"
                    )
                )
            ).scalars().all()
        assert len(only) == 1, "this test is only meaningful on a one-agency install"
        assert row["org_id"] == only[0]
    finally:
        await _cleanup()


# ── Abuse defences ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_honeypot_looks_exactly_like_success_and_writes_nothing() -> None:
    try:
        status, body = await _post(
            {"email": "bot@capture.test", "website": "http://spam.example"}
        )
        assert status == 202
        assert body == {"ok": True}
        assert await _lead_row("bot@capture.test") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_per_ip_limit_refuses_the_sixth_submission() -> None:
    try:
        for n in range(PER_IP_LIMIT):
            status, _ = await _post(
                {"email": f"burst{n}@capture.test"}, **{"cf-connecting-ip": "203.0.113.5"}
            )
            assert status == 202, n
        status, _ = await _post(
            {"email": "burst-over@capture.test"}, **{"cf-connecting-ip": "203.0.113.5"}
        )
        assert status == 429
        assert await _lead_row("burst-over@capture.test") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_rotating_the_ip_header_does_not_buy_an_unlimited_budget() -> None:
    # The per-IP window is read from a header, so on its own it is decorative:
    # a script that changes the header has a fresh budget every request. The
    # global ceiling is what actually bounds the damage.
    try:
        accepted = 0
        for n in range(GLOBAL_LIMIT + 10):
            status, _ = await _post(
                {"email": f"flood{n}@capture.test"},
                **{"cf-connecting-ip": f"198.51.100.{n % 250}"},
            )
            if status == 202:
                accepted += 1
        assert accepted == GLOBAL_LIMIT
    finally:
        await _cleanup()


# ── Validation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_submission_with_no_way_to_reply_is_refused() -> None:
    status, body = await _post({"name": "Anonymous", "message": "call me"})
    assert status == 422
    assert body["detail"] == "contact_required"


@pytest.mark.asyncio
async def test_consent_without_its_wording_is_refused() -> None:
    # A ticked box with no record of what was shown is the indefensible
    # timestamp the consent columns exist to avoid.
    try:
        status, body = await _post(
            {"email": "noproof@capture.test", "consent": True, "consent_text": "   "}
        )
        assert status == 422
        assert body["detail"] == "consent_text_required"
        assert await _lead_row("noproof@capture.test") is None
    finally:
        await _cleanup()


# ── What actually gets stored ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consent_is_stored_with_the_evidence_around_it() -> None:
    wording = "I agree to receive texts about listings. Msg rates may apply."
    try:
        status, _ = await _post(
            {
                "email": "yes@capture.test",
                "phone": "(303) 555-9000",
                "consent": True,
                "consent_text": wording,
            },
            **{"cf-connecting-ip": "203.0.113.44", "user-agent": "Mozilla/5.0 Test"},
        )
        assert status == 202
        lead = await _lead_row("yes@capture.test")
        assert lead["consent_at"] is not None
        assert lead["consent_text"] == wording
        assert lead["consent_ip"] == "203.0.113.44"
        assert lead["consent_user_agent"] == "Mozilla/5.0 Test"
        # The phone is the identifier when both are given, because that is what
        # an SMS arrival will key on.
        assert lead["phone"] == "+13035559000"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_attribution_is_stored_and_filtered() -> None:
    try:
        status, _ = await _post(
            {
                "email": "utm@capture.test",
                "utm": {
                    "utm_source": "tiktok",
                    "utm_content": "denver-washpark-01",
                    "sneaky": "x" * 9_000,
                },
            }
        )
        assert status == 202
        meta = (await _lead_row("utm@capture.test"))["meta"]
        assert meta["attribution"]["utm_source"] == "tiktok"
        assert meta["attribution"]["utm_content"] == "denver-washpark-01"
        assert "sneaky" not in meta["attribution"]
        assert meta["attribution"]["captured_at"]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_second_submission_merges_and_keeps_the_first_touch() -> None:
    # `leads` is unique on (org_id, phone). Before the upsert this was a 500 and
    # a lost lead the second time anybody used the form.
    try:
        first = await _post(
            {"email": "again@capture.test", "utm": {"utm_content": "video-one"},
             "message": "first note"}
        )
        second = await _post(
            {"email": "again@capture.test", "utm": {"utm_content": "video-two"},
             "message": "second note"}
        )
        assert first[0] == 202
        assert second[0] == 202
        meta = (await _lead_row("again@capture.test"))["meta"]
        # First touch is the acquisition credit; overwriting it would credit
        # whatever they saw last, which is never the video that found them.
        assert meta["attribution"]["utm_content"] == "video-one"
        assert meta["attribution_later"][0]["utm_content"] == "video-two"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_double_click_does_not_duplicate_the_message() -> None:
    try:
        await _post({"email": "twice@capture.test", "message": "same words"})
        await _post({"email": "twice@capture.test", "message": "same words"})
        lead = await _lead_row("twice@capture.test")
        async with get_bypass_session_factory()() as db:
            count = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "WHERE c.lead_id = :lead AND m.direction = 'inbound'"
                    ),
                    {"lead": lead["id"]},
                )
            ).scalar_one()
        assert count == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_submission_lands_in_the_inbox_as_a_web_conversation() -> None:
    try:
        await _post(
            {"email": "inbox@capture.test", "name": "Jane", "message": "Wash Park under 1M"}
        )
        lead = await _lead_row("inbox@capture.test")
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT c.channel, m.content, m.direction FROM conversations c "
                        "JOIN messages m ON m.conversation_id = c.id "
                        "WHERE c.lead_id = :lead"
                    ),
                    {"lead": lead["id"]},
                )
            ).mappings().first()
        assert row["channel"] == CHANNEL_WEB
        assert row["direction"] == "inbound"
        assert row["content"] == "Wash Park under 1M"
        assert lead["name"] == "Jane"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_stored_message_is_the_cleaned_one() -> None:
    # Regression: the handler cleaned the message into a local variable and
    # then stored `sub.message`, so every cap and every bit of normalisation
    # applied to nothing at all. Whitespace collapsing is the observable half
    # of that cleaning — the length cap cannot be reached through the API
    # because pydantic rejects an over-long body first (asserted below).
    try:
        await _post(
            {"email": "messy@capture.test", "message": "  Wash   Park\n\n\tunder 1M  "}
        )
        lead = await _lead_row("messy@capture.test")
        async with get_bypass_session_factory()() as db:
            content = (
                await db.execute(
                    text(
                        "SELECT m.content FROM conversations c "
                        "JOIN messages m ON m.conversation_id = c.id "
                        "WHERE c.lead_id = :lead"
                    ),
                    {"lead": lead["id"]},
                )
            ).scalar_one()
        assert content == "Wash Park under 1M"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_oversized_body_never_reaches_the_database() -> None:
    try:
        status, _ = await _post(
            {"email": "huge@capture.test", "message": "x" * (MAX_MESSAGE + 1)}
        )
        assert status == 422
        assert await _lead_row("huge@capture.test") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_captured_lead_is_scored() -> None:
    # The Inbox is sorted by priority. A lead left at the default zero sinks
    # below every old thread, so the newest lead from the channel this work
    # exists to build would be the last one anybody looks at. Found by opening
    # the Inbox, not by any assertion that existed before.
    try:
        await _post(
            {
                "email": "scored@capture.test",
                "phone": "(303) 555-6262",
                "message": "Looking in Wash Park, budget around 900k, moving in spring",
            }
        )
        assert (await _lead_row("scored@capture.test"))["id"]
        async with get_bypass_session_factory()() as db:
            score = (
                await db.execute(
                    text("SELECT score FROM leads WHERE email = :e"),
                    {"e": "scored@capture.test"},
                )
            ).scalar_one()
        assert score > 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_form_with_no_message_still_reads_as_something() -> None:
    # An empty bubble in the Inbox reads as a bug, not as a contact request.
    try:
        await _post({"email": "quiet@capture.test", "name": "Pat"})
        lead = await _lead_row("quiet@capture.test")
        async with get_bypass_session_factory()() as db:
            content = (
                await db.execute(
                    text(
                        "SELECT m.content FROM conversations c "
                        "JOIN messages m ON m.conversation_id = c.id "
                        "WHERE c.lead_id = :lead"
                    ),
                    {"lead": lead["id"]},
                )
            ).scalar_one()
        assert "Pat" in content
    finally:
        await _cleanup()


# ── Body size ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_enormous_body_is_refused_before_it_is_parsed() -> None:
    # There is no reverse proxy in front of uvicorn and uvicorn has no limit of
    # its own, so a 43 MB JSON body was accepted, parsed into Python objects,
    # answered 202 by the honeypot branch and retained ~200 MB. A few
    # concurrent ones OOM the single worker and take every tenant's dashboard
    # with it.
    payload = {"email": "huge@capture.test", "utm": {"utm_campaign": "x" * 400_000}}
    try:
        status, _ = await _post(payload)
        assert status == 413
        assert await _lead_row("huge@capture.test") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_normal_submission_is_comfortably_under_the_limit() -> None:
    # The cap must not be so tight that a real person writing a long note is
    # refused. 5,000 characters of message is the documented maximum.
    try:
        status, _ = await _post(
            {"email": "verbose@capture.test", "message": "y" * 4_900}
        )
        assert status == 202
        assert await _lead_row("verbose@capture.test") is not None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_honeypot_is_metered() -> None:
    # It used to return before the rate limiter, which made
    # `{"website": "bot"}` a completely unmetered endpoint: two hundred
    # consecutive posts all answered 202 and left every counter untouched.
    try:
        for _ in range(PER_IP_LIMIT):
            status, _ = await _post(
                {"email": "hp@capture.test", "website": "spam"},
                **{"cf-connecting-ip": "203.0.113.77"},
            )
            assert status == 202
        status, _ = await _post(
            {"email": "hp-over@capture.test"}, **{"cf-connecting-ip": "203.0.113.77"}
        )
        assert status == 429
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_refused_captcha_does_not_spend_the_global_budget() -> None:
    # The ceiling used to be charged first, so sixty tokenless posts from sixty
    # forged addresses each got a 400 and each still consumed a slot — the
    # captcha bypassed for availability, and every agency on the install losing
    # lead capture for ten minutes.
    from app.config import get_settings

    settings = get_settings()
    original = settings.TURNSTILE_SECRET
    settings.TURNSTILE_SECRET = "test-secret-no-network"
    try:
        for n in range(GLOBAL_LIMIT + 5):
            status, _ = await _post(
                {"email": f"nocaptcha{n}@capture.test"},
                **{"cf-connecting-ip": f"198.51.100.{n % 250}"},
            )
            assert status == 400, (n, status)
        settings.TURNSTILE_SECRET = ""
        # The budget was never touched, so an honest visitor still gets through.
        status, _ = await _post(
            {"email": "honest@capture.test"}, **{"cf-connecting-ip": "203.0.113.250"}
        )
        assert status == 202
    finally:
        settings.TURNSTILE_SECRET = original
        await _cleanup()


@pytest.mark.asyncio
async def test_a_wrong_key_is_refused_even_when_only_one_agency_is_left() -> None:
    """The offboarding hole.

    `test_unknown_form_key_is_refused` seeds TWO agencies, so its 404 comes from
    the multi-candidate branch and says nothing about this. Here there is
    exactly one agency, and a key that names nobody — which is precisely the
    state an operator creates by offboarding a client the ordinary way: suspend
    the org, delete its routes. The old landing page keeps posting its key, and
    with the single-tenant fallback in play every one of those leads was filed
    into the surviving agency with a 202.
    """
    try:
        status, _ = await _post(
            {"form": "offboarded-agency", "email": "orphan@capture.test"}
        )
        assert status == 404
        assert await _lead_row("orphan@capture.test") is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_consent_cannot_be_planted_on_someone_elses_lead() -> None:
    """Knowing an address must not let a stranger opt that person in.

    The email merge exists so the same person writing from two places becomes
    one lead. It also means anyone who knows an address reaches the CRM record
    behind it — and `_record_consent` would stamp consent onto a WhatsApp lead
    who never opted in, with the attacker's IP as the evidence. Worse in
    reverse: consent is never overwritten, so pre-planting junk wording means
    the person's real consent could never be recorded.
    """
    victim_email = "victim@capture.test"
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO leads (org_id, phone, email, status, score, "
                "score_breakdown, meta, human_takeover) VALUES "
                "(1, '+19995558888', :e, 'new', 0, '{}', '{}', false)"
            ),
            {"e": victim_email},
        )
        await db.commit()
    try:
        status, _ = await _post(
            {
                "email": victim_email,
                "consent": True,
                "consent_text": "I agree to receive automated texts.",
            },
            **{"cf-connecting-ip": "203.0.113.99", "user-agent": "attacker/1.0"},
        )
        # The submission is accepted — it is an ordinary enquiry and refusing it
        # would leak that the address is known. What must not happen is the
        # consent record.
        assert status == 202
        lead = await _lead_row(victim_email)
        assert lead["consent_at"] is None
        assert lead["consent_ip"] is None
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM leads WHERE phone = '+19995558888'")
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_a_probe_cannot_tell_a_live_form_key_from_a_dead_one() -> None:
    """The 422 used to be an enumeration oracle.

    Validation ran after tenant resolution, so a probe with no contact details
    answered 422 for a live key and 404 for one that named nothing — and because
    it writes no lead, a scan left no trace in any inbox. Both must now answer
    the same thing.
    """
    org_a, _ = await _seed()
    try:
        live = await _post({"form": FORM_A, "name": "probe"})
        dead = await _post({"form": "no-such-form-at-all", "name": "probe"})
        assert live[0] == dead[0] == 422
        assert live[1] == dead[1]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_body_cap_does_not_break_file_import() -> None:
    """The cap is per path, and the upload route documents 25 MB.

    A single global cap tight enough for the public form silently refused a
    realtor's contact export — a legal 750 KB multipart upload — with no
    diagnostic, breaking a documented feature to protect an unrelated one.
    """
    from app.config import get_settings
    from app.main import BodySizeLimit

    limit = BodySizeLimit._limit_for("/api/v1/discovery/upload")
    assert limit == get_settings().FILE_IMPORT_MAX_MB * 1024 * 1024
    assert limit > 700_000
    # And the public form keeps its tight one.
    assert BodySizeLimit._limit_for("/api/v1/public/leads") == 256 * 1024


@pytest.mark.asyncio
async def test_the_413_carries_cors_headers() -> None:
    """Registered inside CORS, so a browser gets a status it can report.

    Outside it, the response had no Access-Control-Allow-Origin and the fetch
    surfaced as a bare network error — the visitor sees "something went wrong"
    and the operator sees nothing at all.

    Matters only for a form served from a DIFFERENT origin than the API. Today
    /contact is same-origin (Next.js proxies /api), but the content plan puts
    the landing page on its own domain later, and that day this is the
    difference between a readable 413 and an unexplained failure.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/public/leads",
            json={"email": "cors@capture.test", "utm": {"utm_campaign": "z" * 400_000}},
            headers={"origin": "http://localhost:3004"},  # an allowed origin
        )
    assert response.status_code == 413
    assert "access-control-allow-origin" in {k.lower() for k in response.headers}


@pytest.mark.asyncio
async def test_a_chunked_oversized_body_gets_one_clean_response() -> None:
    """No Content-Length at all, and the app must never start responding.

    The first version let the request through and tried to swap the response
    afterwards, which means handing an ASGI app a second response — it blew up
    inside the HTTP client on every chunked upload it tried to stop.
    """

    async def chunks():
        for _ in range(6):
            yield b"x" * 60_000

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/public/leads",
            content=chunks(),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["detail"] == "body_too_large"


@pytest.mark.asyncio
async def test_a_consent_record_is_written_once_and_never_replaced() -> None:
    """A stranger must not be able to destroy a genuine consent record.

    A version of this allowed a refresh, reasoning that "a genuine submission
    heals a forged one". The converse is identical and worse: one anonymous
    POST with a known phone number replaced a real dated record, its wording
    and its IP — the only evidence the broker has if the lead disputes. A junk
    record is noise; a destroyed genuine record is a lost defence.
    """
    victim = "written-once@capture.test"
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO leads (org_id, phone, email, status, score, "
                "score_breakdown, meta, human_takeover, consent_at, "
                "consent_text, consent_ip) VALUES "
                "(1, :p, :e, 'new', 0, '{}', '{}', false, :t, :txt, :ip)"
            ),
            {
                "p": "+19995554321",
                "e": victim,
                "t": datetime(2026, 1, 5, 12, 0, tzinfo=UTC),
                "txt": "GENUINE: I agree to receive texts.",
                "ip": "203.0.113.7",
            },
        )
        await db.commit()
    try:
        status, _ = await _post(
            {
                "phone": "(999) 555-4321",
                "consent": True,
                "consent_text": "OVERWRITTEN BY A STRANGER",
            },
            **{"cf-connecting-ip": "192.0.2.99"},
        )
        assert status == 202
        lead = await _lead_row(victim)
        assert lead["consent_text"] == "GENUINE: I agree to receive texts."
        assert lead["consent_ip"] == "203.0.113.7"
        assert lead["consent_at"].year == 2026 and lead["consent_at"].month == 1
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(text("DELETE FROM leads WHERE phone = '+19995554321'"))
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_consent_on_an_existing_contact_is_flagged() -> None:
    """A web form cannot tell the real person from a stranger who knows their
    number. That is inherent to web consent and no server-side rule fixes it —
    Turnstile and STOP are the real defences. What it can do is make the claim
    findable afterwards instead of indistinguishable from a first contact.
    """
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO leads (org_id, phone, email, status, score, "
                "score_breakdown, meta, human_takeover) VALUES "
                "(1, :p, :e, 'new', 0, '{}', '{}', false)"
            ),
            {"p": "+19995554322", "e": "flagged@capture.test"},
        )
        await db.commit()
    try:
        await _post(
            {
                "phone": "(999) 555-4322",
                "consent": True,
                "consent_text": "I agree to receive texts.",
            }
        )
        lead = await _lead_row("flagged@capture.test")
        assert lead["consent_at"] is not None
        assert lead["meta"].get("consent_claimed_on_existing_lead")
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(text("DELETE FROM leads WHERE phone = '+19995554322'"))
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_the_honest_whatsapp_lead_can_consent_on_the_website() -> None:
    """The guard must not cost the most common path there is.

    A version of this required the lead to have been created by this form,
    which silently discarded consent from somebody who first wrote on WhatsApp
    and then ticked the box on the website — the API answered 202 and the
    dashboard displayed "no consent" for a person who had demonstrably given
    it.
    """
    phone = "+19995556010"
    async with get_bypass_session_factory()() as db:
        lead_id = (
            await db.execute(
                text(
                    "INSERT INTO leads (org_id, phone, email, status, score, "
                    "score_breakdown, meta, human_takeover) VALUES "
                    "(1, :p, :e, 'new', 0, '{}', '{}', false) RETURNING id"
                ),
                {"p": phone, "e": "wa@capture.test"},
            )
        ).scalar_one()
        await db.execute(
            text(
                "INSERT INTO conversations (org_id, lead_id, channel, status) "
                "VALUES (1, :l, 'whatsapp', 'active')"
            ),
            {"l": lead_id},
        )
        await db.commit()
    try:
        status, _ = await _post(
            {
                "phone": "(999) 555-6010",
                "email": "wa@capture.test",
                "consent": True,
                "consent_text": "I agree to receive texts about listings.",
            }
        )
        assert status == 202
        lead = await _lead_row("wa@capture.test")
        assert lead["consent_at"] is not None, "the honest case must record consent"
        assert "I agree" in lead["consent_text"]
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(text("DELETE FROM leads WHERE phone = :p"), {"p": phone})
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_a_returning_web_lead_can_still_consent_later() -> None:
    """The guard must not cost the legitimate path.

    Somebody who filled the form without ticking the box, then came back and
    ticked it, is the ordinary case. Their lead exists, was created by this
    form, and has never been reached on another channel.
    """
    try:
        assert (await _post({"email": "later@capture.test", "name": "Later"}))[0] == 202
        assert (await _lead_row("later@capture.test"))["consent_at"] is None

        status, _ = await _post(
            {
                "email": "later@capture.test",
                "consent": True,
                "consent_text": "I agree to receive texts about listings.",
            }
        )
        assert status == 202
        lead = await _lead_row("later@capture.test")
        assert lead["consent_at"] is not None
        assert "I agree" in lead["consent_text"]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_consent_cannot_be_planted_on_an_imported_lead() -> None:
    """An imported lead has no conversations at all, and that fooled the guard.

    The first version asked "has this lead been reached on another channel?" —
    an agency's own contact export answers no, because those rows have no
    conversations. So a stranger who knew any address in that file could write
    a consent record onto a real client the agency had never messaged. The
    question that actually matters is whether THIS FORM created the lead.
    """
    imported = "imported@capture.test"
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO leads (org_id, phone, email, status, score, "
                "score_breakdown, meta, human_takeover) VALUES "
                "(1, :p, :e, 'new', 0, '{}', '{}', false)"
            ),
            {"p": "+19995557777", "e": imported},
        )
        await db.commit()
    try:
        status, _ = await _post(
            {
                "email": imported,
                "consent": True,
                "consent_text": "PLANTED — I agree to automated texts.",
            },
            **{"cf-connecting-ip": "192.0.2.44"},
        )
        assert status == 202
        assert (await _lead_row(imported))["consent_at"] is None
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(text("DELETE FROM leads WHERE phone = '+19995557777'"))
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_an_oversized_upload_is_refused_before_the_route_reads_it() -> None:
    """On the streamed path the Content-Length check is the ONLY guard.

    `/api/v1/discovery/upload` is passed through unbuffered — the route owns
    the body and enforces FILE_IMPORT_MAX_MB itself — so the header check is
    what stops a caller declaring 60 MB and making the worker read it. On the
    public path the stream counter catches oversize anyway, which is why
    removing this check left every other test green.
    """
    from app.config import get_settings

    over = get_settings().FILE_IMPORT_MAX_MB * 1024 * 1024 + 1
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/discovery/upload",
            content=b"x" * 32,  # tiny body, enormous claim
            headers={
                "content-type": "application/octet-stream",
                "content-length": str(over),
            },
        )
    assert response.status_code == 413
    assert response.json()["detail"] == "body_too_large"


@pytest.mark.asyncio
async def test_two_leads_sharing_an_address_are_not_merged() -> None:
    """`info@` and family mailboxes are two people, not one.

    `_lead_for` adopts a lead found by email only when there is EXACTLY one.
    Relaxing that to "at least one" left the whole suite green, and the cost is
    the worst kind: one person's conversation shown to another, because they
    happen to share a mailbox.
    """
    shared = "info@capture.test"
    async with get_bypass_session_factory()() as db:
        for phone in ("+19995551001", "+19995551002"):
            await db.execute(
                text(
                    "INSERT INTO leads (org_id, phone, email, status, score, "
                    "score_breakdown, meta, human_takeover) VALUES "
                    "(1, :p, :e, 'new', 0, '{}', '{}', false)"
                ),
                {"p": phone, "e": shared},
            )
        await db.commit()
    try:
        status, _ = await _post({"email": shared, "message": "Third person here"})
        assert status == 202
        async with get_bypass_session_factory()() as db:
            # A third, separate lead — keyed on the address itself — not an
            # adoption of whichever of the two came first.
            rows = (
                await db.execute(
                    text("SELECT phone FROM leads WHERE email = :e ORDER BY phone"),
                    {"e": shared},
                )
            ).scalars().all()
            assert len(rows) == 3, rows
            assert shared in rows, "the new submission got its own lead"
            # And neither existing lead was written to.
            counts = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "JOIN leads l ON l.id = c.lead_id "
                        "WHERE l.phone IN ('+19995551001', '+19995551002')"
                    )
                )
            ).scalar_one()
            assert counts == 0
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM leads WHERE phone LIKE '+199955510%'")
            )
            await db.commit()
        await _cleanup()
