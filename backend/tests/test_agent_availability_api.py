"""«My availability»: whose schedule a request can reach, and whose it cannot.

The security property under test is unusual and worth naming, because the test
that proves it looks like it is testing nothing: **there is no way to address
another agent's schedule.** Not "an authorisation check rejects it" — there is
no parameter to put a victim's address in. The email is read from the session
token, every schema is `extra="forbid"`, and no path carries it.

So the assertion is a 422 on a body that tries, plus a positive test showing
that two different sessions reach two different rows. A test that only asserted
403 would be testing a check that does not exist, and would go green if somebody
later added `PUT /availability/{email}` beside this one.

Cal.com is stubbed at `_call`, the single request function of the service.
Nothing here reaches the network — and the fact that one function is enough to
stub is itself the reason the service has exactly one.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.api.v1.auth import COOKIE_NAME
from app.config import get_settings
from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import AgentCalendar, AllowedUser, AppointmentActivity
from app.services.agent_calendar import Window, validate_windows
from app.services.auth import ROLE_MEMBER, make_token

ORG = 1
NATALIA = "availability-natalia@example.com"
ROBBIE = "availability-robbie@example.com"
OUTSIDER = "availability-outsider@example.com"

# What Cal.com answers. Ids differ per call so a test can tell a schedule from
# an event type; the availability echo is what `set_windows` returns.
SCHEDULE = {"id": 900001, "availability": []}
EVENT_TYPE = {"id": 700001}


@contextmanager
def _auth_on():
    """The configuration these routes actually require.

    The suite default is AUTH_ENABLED=false, where `current_email` returns None
    by design — the signing key in that mode is a constant published in this
    repository, so a claim proves nothing. These routes refuse outright there,
    which is correct and is why the tests have to turn auth on rather than the
    routes having to work without it. Production runs with it on (verified).

    Cal.com is configured here too, for the same reason: the suite default is
    CALENDAR_SIMULATED=true, where `undeliverable_reason` correctly reports that
    nothing can be provisioned. `_call` is stubbed, so no request leaves.
    """
    s = get_settings()
    with (
        patch.object(s, "AUTH_ENABLED", True),
        patch.object(s, "AUTH_SECRET", "availability-test-secret"),
        patch.object(s, "CALENDAR_SIMULATED", False),
        patch.object(s, "CALCOM_API_KEY", "cal_test_not_a_real_key"),
    ):
        yield


def _cookies(email: str) -> dict[str, str]:
    """Minted inside `_auth_on`, so it is signed with the patched secret."""
    return {COOKIE_NAME: make_token(role=ROLE_MEMBER, email=email, org_id=ORG)}


async def _allow(*emails: str) -> None:
    async with get_bypass_session_factory()() as db:
        for email in emails:
            db.add(AllowedUser(org_id=ORG, email=email, role=ROLE_MEMBER))
        await db.commit()


async def _cleanup(*emails: str) -> None:
    async with get_bypass_session_factory()() as db:
        for email in emails:
            await db.execute(
                text("DELETE FROM agent_calendars WHERE email = :e"), {"e": email}
            )
            await db.execute(
                text("DELETE FROM allowed_users WHERE email = :e"), {"e": email}
            )
        await db.commit()


def _fake_call(stored: list[dict] | None = None):
    """Stands in for `agent_calendar._call`, answering by path and method."""

    async def _inner(method: str, path: str, *, api_version: str, json=None):
        if path == "/v2/schedules" and method == "POST":
            return dict(SCHEDULE)
        if path.startswith("/v2/schedules/") and method == "GET":
            return {"availability": stored or []}
        if path.startswith("/v2/schedules/") and method == "PATCH":
            # Echo what was sent, which is what the real API does — the route
            # returns Cal.com's copy rather than the caller's on purpose.
            return {"availability": (json or {}).get("availability", [])}
        if path == "/v2/event-types" and method == "POST":
            return dict(EVENT_TYPE)
        raise AssertionError(f"unexpected Cal.com call: {method} {path}")

    return AsyncMock(side_effect=_inner)


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── The property: another agent cannot be named ──────────────────────────────


@pytest.mark.asyncio
async def test_a_body_that_names_someone_else_is_refused_by_the_schema() -> None:
    """`extra="forbid"` is the guard, and this is what makes it a guard.

    Mutation that must turn this red: allowing extra fields on `WindowsPut`.
    Without it the field would be accepted and silently ignored today — which is
    safe today and is exactly the kind of thing a later refactor turns into
    `email or current_email(request)`.
    """
    await _allow(NATALIA)
    try:
        with _auth_on(), patch("app.services.agent_calendar._call", _fake_call()):
            async with await _client() as c:
                r = await c.put(
                    "/api/v1/availability/me/showing",
                    json={"windows": [], "email": ROBBIE},
                    cookies=_cookies(NATALIA),
                )
        assert r.status_code == 422, r.text
    finally:
        await _cleanup(NATALIA)


@pytest.mark.asyncio
async def test_two_agents_write_to_two_different_rows() -> None:
    """The positive half. Without it, a router that wrote everything to one row
    would pass the test above."""
    await _allow(NATALIA, ROBBIE)
    try:
        with _auth_on(), patch("app.services.agent_calendar._call", _fake_call()):
            async with await _client() as c:
                for email in (NATALIA, ROBBIE):
                    r = await c.put(
                        "/api/v1/availability/me/showing",
                        json={"windows": [{"days": [1], "start": "10:00", "end": "12:00"}]},
                        cookies=_cookies(email),
                    )
                    assert r.status_code == 200, r.text
        async with get_bypass_session_factory()() as db:
            rows = (
                await db.execute(
                    select(AgentCalendar).where(AgentCalendar.email.in_([NATALIA, ROBBIE]))
                )
            ).scalars().all()
        assert {r.email for r in rows} == {NATALIA, ROBBIE}
    finally:
        await _cleanup(NATALIA, ROBBIE)


@pytest.mark.asyncio
async def test_an_address_that_is_not_on_the_team_gets_no_schedule() -> None:
    """The schema comment says a row "cannot belong to somebody who cannot sign
    in" and the migration enforces nothing — no FK, no CHECK. An audit said so.
    This route is the only writer, so this is where the claim becomes true."""
    try:
        with _auth_on(), patch("app.services.agent_calendar._call", _fake_call()) as spy:
            async with await _client() as c:
                r = await c.get("/api/v1/availability/me", cookies=_cookies(OUTSIDER))
        assert r.status_code == 403, r.text
        assert spy.await_count == 0, "Cal.com was called for someone off the team"
        async with get_bypass_session_factory()() as db:
            rows = (
                await db.execute(
                    select(AgentCalendar).where(AgentCalendar.email == OUTSIDER)
                )
            ).scalars().all()
        assert rows == []
    finally:
        await _cleanup(OUTSIDER)


# ── Provisioning ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_opening_the_page_twice_does_not_create_two_schedules() -> None:
    """`ensure_calendar` runs on every read. If it were not idempotent, a person
    refreshing the page would collect Cal.com schedules, and the newest would
    silently win — they would edit hours nothing books against."""
    await _allow(NATALIA)
    try:
        fake = _fake_call()
        with _auth_on(), patch("app.services.agent_calendar._call", fake):
            async with await _client() as c:
                first = await c.get("/api/v1/availability/me", cookies=_cookies(NATALIA))
                assert first.status_code == 200, first.text
                creations = sum(
                    1
                    for call in fake.await_args_list
                    if call.args[1] == "/v2/schedules" and call.args[0] == "POST"
                )
                assert creations == len(AppointmentActivity)
                await c.get("/api/v1/availability/me", cookies=_cookies(NATALIA))
        creations_after = sum(
            1
            for call in fake.await_args_list
            if call.args[1] == "/v2/schedules" and call.args[0] == "POST"
        )
        assert creations_after == len(AppointmentActivity), (
            "the second visit created more schedules — provisioning is not idempotent"
        )
        async with get_bypass_session_factory()() as db:
            rows = (
                await db.execute(
                    select(AgentCalendar).where(AgentCalendar.email == NATALIA)
                )
            ).scalars().all()
        assert len(rows) == len(AppointmentActivity)
    finally:
        await _cleanup(NATALIA)


@pytest.mark.asyncio
async def test_the_page_says_why_it_is_inert_instead_of_spinning() -> None:
    """With the calendar simulated there is nothing to provision. The route must
    still answer, and say so in words — an empty week that looks like a
    deliberate "never available" is the failure being avoided."""
    await _allow(NATALIA)
    try:
        # The real `undeliverable_reason`, driven by the real setting. The first
        # version of this test patched the function by its defining module,
        # which the router does not go through — it imported the name, so the
        # patch was invisible and the test asserted on the unpatched path.
        with _auth_on(), patch.object(
            get_settings(), "CALENDAR_SIMULATED", True
        ), patch("app.services.agent_calendar._call", _fake_call()) as spy:
            async with await _client() as c:
                r = await c.get("/api/v1/availability/me", cookies=_cookies(NATALIA))
        assert r.status_code == 200, r.text
        assert "simulated" in (r.json()["unavailable_reason"] or "")
        assert spy.await_count == 0, "it went to Cal.com anyway"
    finally:
        await _cleanup(NATALIA)


# ── The windows themselves ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overlapping_windows_are_refused_with_a_reason() -> None:
    await _allow(NATALIA)
    try:
        with _auth_on(), patch("app.services.agent_calendar._call", _fake_call()):
            async with await _client() as c:
                r = await c.put(
                    "/api/v1/availability/me/showing",
                    json={
                        "windows": [
                            {"days": [1], "start": "10:00", "end": "12:00"},
                            {"days": [1], "start": "11:00", "end": "13:00"},
                        ]
                    },
                    cookies=_cookies(NATALIA),
                )
        assert r.status_code == 422, r.text
        assert "overlap" in r.text.lower()
    finally:
        await _cleanup(NATALIA)


@pytest.mark.asyncio
async def test_what_comes_back_is_what_calcom_stored() -> None:
    """Returning the submitted value would hide any normalisation Cal.com does,
    and the agent would believe hours that are not in force."""
    await _allow(NATALIA)
    try:
        with _auth_on(), patch("app.services.agent_calendar._call", _fake_call()):
            async with await _client() as c:
                r = await c.put(
                    "/api/v1/availability/me/valuation",
                    json={
                        "windows": [{"days": [0, 2], "start": "09:00", "end": "11:30"}],
                        "duration_minutes": 90,
                    },
                    cookies=_cookies(NATALIA),
                )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["activity"] == "valuation"
        assert body["duration_minutes"] == 90
        assert body["windows"] == [{"days": [0, 2], "start": "09:00", "end": "11:30"}]
    finally:
        await _cleanup(NATALIA)


@pytest.mark.asyncio
async def test_the_team_view_is_admin_only_and_never_provisions() -> None:
    """Two properties in one place, because they fail together.

    A member opening a colleague's hours is a privacy question. But the second
    half matters more operationally: this page must not call Cal.com. Reading a
    team of five would otherwise provision four activities each — twenty
    schedules and twenty event types — as a side effect of somebody looking.
    """
    await _allow(NATALIA, ROBBIE)
    try:
        with _auth_on(), patch("app.services.agent_calendar._call", _fake_call()):
            async with await _client() as c:
                # Seed one row through the normal path so there is something to list.
                await c.put(
                    "/api/v1/availability/me/showing",
                    json={"windows": [{"days": [3], "start": "14:00", "end": "16:00"}]},
                    cookies=_cookies(NATALIA),
                )
        with _auth_on(), patch("app.services.agent_calendar._call", _fake_call()) as spy:
            async with await _client() as c:
                denied = await c.get("/api/v1/availability", cookies=_cookies(ROBBIE))
                allowed = await c.get(
                    "/api/v1/availability",
                    cookies={
                        COOKIE_NAME: make_token(role="admin", email=NATALIA, org_id=ORG)
                    },
                )
        assert denied.status_code == 403, denied.text
        assert allowed.status_code == 200, allowed.text
        # The shared office password mints an admin token with NO email. It must
        # not reach the roster: an audit found it did, while the module
        # docstring said otherwise.
        with _auth_on(), patch("app.services.agent_calendar._call", _fake_call()):
            async with await _client() as c:
                anonymous_admin = await c.get(
                    "/api/v1/availability",
                    cookies={COOKIE_NAME: make_token(role="admin", org_id=ORG)},
                )
        assert anonymous_admin.status_code == 403, anonymous_admin.text
        assert any(m["email"] == NATALIA for m in allowed.json())
        assert spy.await_count == 0, (
            "the team view called Cal.com — reading a page must not provision"
        )
    finally:
        await _cleanup(NATALIA, ROBBIE)


@pytest.mark.asyncio
async def test_a_reply_with_no_id_does_not_poison_the_row_forever() -> None:
    """The blocker an audit found, reproduced.

    `read_my_availability` commits on a Cal.com error on purpose, to keep
    partial provisioning. So anything written before the error is permanent —
    and the code used to write `str(data.get("id") or "")`, i.e. the empty
    string, before raising. The resume guard then read `is None`, which `""` is
    not, so the next attempt skipped creation and ran `int("")` → ValueError,
    which no caller catches. That agent's page 500'd forever, recoverable only
    by a manual UPDATE.

    The fix is to never write the sentinel. What this asserts is the behaviour
    that matters: after the failure the row is still *resumable*, and a healthy
    retry finishes the job.
    """
    await _allow(NATALIA)
    try:
        broken = AsyncMock(
            side_effect=lambda method, path, *, api_version, json=None: (
                {} if path == "/v2/schedules" else {"id": 1}
            )
        )
        with _auth_on(), patch("app.services.agent_calendar._call", broken):
            async with await _client() as c:
                first = await c.get("/api/v1/availability/me", cookies=_cookies(NATALIA))
        assert first.status_code == 502, first.text

        async with get_bypass_session_factory()() as db:
            rows = (
                await db.execute(
                    select(AgentCalendar).where(AgentCalendar.email == NATALIA)
                )
            ).scalars().all()
        assert all(not r.calcom_schedule_id for r in rows), (
            "a row was committed with an empty schedule id — the resume guard "
            "will skip it and int('') will raise on every later request"
        )

        # Cal.com healthy again: the same agent must recover with no manual fix.
        with _auth_on(), patch("app.services.agent_calendar._call", _fake_call()):
            async with await _client() as c:
                again = await c.get("/api/v1/availability/me", cookies=_cookies(NATALIA))
        assert again.status_code == 200, again.text
        assert all(a["configured"] for a in again.json()["activities"])
    finally:
        await _cleanup(NATALIA)


@pytest.mark.asyncio
async def test_a_timeout_is_reported_not_raised_through() -> None:
    """`_call` sets a 20s timeout, so `httpx.ReadTimeout` is an expected result,
    not an exception nobody considered. Left as httpx it escaped every caller's
    `except CalComScheduleError` and became an uncaught 500."""
    import httpx as _httpx

    await _allow(NATALIA)
    try:
        timing_out = AsyncMock(side_effect=_httpx.ReadTimeout("too slow"))
        with _auth_on(), patch(
            "app.services.agent_calendar.httpx.AsyncClient"
        ) as client_cls:
            client_cls.return_value.__aenter__.return_value.request = timing_out
            async with await _client() as c:
                r = await c.get("/api/v1/availability/me", cookies=_cookies(NATALIA))
        assert r.status_code == 502, r.text
        assert "did not answer" in r.text
    finally:
        await _cleanup(NATALIA)


def test_two_colleagues_do_not_share_a_calcom_slug() -> None:
    """Proved by an audit: the local part alone collides. Same first name at two
    domains, or dotted vs dashed, produced one slug — and a rejected event-type
    creation leaves the row with no id, so every retry fails identically."""
    from app.services.agent_calendar import _slug

    a = _slug("natalia@gmail.com", AppointmentActivity.SHOWING)
    b = _slug("natalia@remaxdenver.com", AppointmentActivity.SHOWING)
    c = _slug("Natalia.Perez@x.com", AppointmentActivity.CALL)
    d = _slug("natalia-perez@y.com", AppointmentActivity.CALL)
    assert a != b and c != d
    # Still readable, and stable across calls — a random suffix would create a
    # second Cal.com object on every retry.
    assert a.startswith("natalia-") and a.endswith("-showing")
    assert _slug("natalia@gmail.com", AppointmentActivity.SHOWING) == a


def test_an_evening_shift_can_end_at_midnight() -> None:
    """Cal.com writes end-of-day as "00:00", so reading a schedule back and
    saving it untouched used to fail our own validation. An agent also simply
    could not say "18:00 until midnight" except as 23:59."""
    validate_windows([Window(days=(1,), start="18:00", end="00:00")])
    # And it is still a real end: 18:00–17:00 is not.
    with pytest.raises(ValueError, match="ends before it starts"):
        validate_windows([Window(days=(1,), start="18:00", end="17:00")])
    # A repeated day is one day, not a window overlapping itself.
    validate_windows([Window(days=(1, 1), start="10:00", end="12:00")])


@pytest.mark.asyncio
async def test_saving_hours_activates_and_clearing_them_deactivates() -> None:
    """Saving IS the switch. Rows provision inactive (an empty schedule must
    never beat the agency default), so the natural flow — type hours, press
    Save — has to turn the calendar on without a second control, and clearing
    every window has to turn it off again."""
    await _allow(NATALIA)
    try:
        with _auth_on(), patch("app.services.agent_calendar._call", _fake_call()):
            async with await _client() as c:
                saved = await c.put(
                    "/api/v1/availability/me/showing",
                    json={"windows": [{"days": [1], "start": "10:00", "end": "12:00"}]},
                    cookies=_cookies(NATALIA),
                )
                assert saved.status_code == 200, saved.text
                assert saved.json()["active"] is True, "saving hours did not activate"
                cleared = await c.put(
                    "/api/v1/availability/me/showing",
                    json={"windows": []},
                    cookies=_cookies(NATALIA),
                )
                assert cleared.status_code == 200, cleared.text
        assert cleared.json()["active"] is False, (
            "an agent who removed all their hours is still marked bookable"
        )
    finally:
        await _cleanup(NATALIA)


def test_the_validator_rejects_what_calcom_would_accept() -> None:
    """Cal.com takes a backwards window and stores availability nobody can
    explain. These are the shapes refused at our door instead."""
    with pytest.raises(ValueError, match="ends before it starts"):
        validate_windows([Window(days=(1,), start="12:00", end="10:00")])
    with pytest.raises(ValueError, match="overlapping"):
        validate_windows(
            [
                Window(days=(1,), start="10:00", end="12:00"),
                Window(days=(1,), start="11:00", end="13:00"),
            ]
        )
    with pytest.raises(ValueError, match="24-hour"):
        validate_windows([Window(days=(1,), start="9:00", end="17:00")])
    with pytest.raises(ValueError, match="at least one day"):
        validate_windows([Window(days=(), start="09:00", end="17:00")])
    # Adjacent, not overlapping: 10-12 then 12-14 is a real way to say a break
    # ends at noon, and refusing it would be wrong.
    validate_windows(
        [
            Window(days=(1,), start="10:00", end="12:00"),
            Window(days=(1,), start="12:00", end="14:00"),
        ]
    )
    # Same hours on different days never collide.
    validate_windows(
        [
            Window(days=(0,), start="10:00", end="12:00"),
            Window(days=(1,), start="10:00", end="12:00"),
        ]
    )
