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
        await db.execute(
            text("DELETE FROM leads WHERE phone LIKE '+1999555%' OR email LIKE '%@capture.test'")
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
    # Natalia's install has one agency and no routes configured. It has to work
    # out of the box or the feature is unreachable for the only customer.
    try:
        status, _ = await _post({"email": "solo@capture.test", "name": "Solo"})
        assert status == 202
        assert (await _lead_row("solo@capture.test"))["org_id"] == 1
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
