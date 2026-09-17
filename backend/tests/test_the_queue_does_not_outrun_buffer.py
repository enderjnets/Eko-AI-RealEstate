"""Buffer's ten slots per channel, and what happens when the queue fills them.

Measured in production on 15-sep-2026, not imagined. The publisher had booked
Instagram out to 26 October — ten scheduled posts, Buffer's whole allowance for
a channel — and everything behind them was refused with `LimitReachedError`.
The refusal arrives per platform, so a full queue did not stop the rail; it
shredded it:

* pieces 33, 34 and 36 were refused on all three channels, went to FAILED, and
  FAILED transitions only to DRAFT — three approved pieces dead until a person
  noticed, and nothing told anybody;
* piece 37 got into Instagram and lost YouTube and TikTok, 38 lost YouTube.
  Both will close as published having gone out on fewer channels than they were
  approved for, because a FAILED row is only retried when somebody re-approves
  the whole piece.

Three properties are held here, and they are one idea from three sides: **the
rail must not spend what it does not have.**

* A window six weeks out does not take a slot today. That is the cause, and
  `CONTENT_SCHEDULE_HORIZON_DAYS` is the whole fix — the rest is damage
  control.
* A full queue is a fact about the calendar, not about the piece, so it leaves
  the platform PENDING the way a quota pause does, and the next tick tries
  again. It must never be FAILED.
* The request quota is read from the header Buffer already sends, and the rail
  stops one short of the edge rather than discovering it with a real post.

The parser returns `(None, None)` rather than zeros for anything it cannot
read, and that is tested on purpose: an unreadable header is not news that the
quota is spent, and treating it as spent would stop publishing over a string.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentStatus,
    PublicationStatus,
)
from app.services import buffer_publisher
from app.services.buffer_publisher import (
    BufferRefused,
    QuotaReached,
    parse_rate_limit,
    publish_approved,
    slots_are_full,
)
from app.services.tenant_context import org_scope

ORG = 1

YT = "6a8f371eccaf649a67208cd0"
TT = "6a8f37efccaf649a6720a2a9"
IG = "6a8f36edccaf649a6720882a"

#: Buffer's own words, copied off `content_publications.last_error` in
#: production rather than paraphrased. The match is on this string.
FULL = "[LimitReachedError] Scheduled posts limit reached. You have 10 scheduled posts out of 10 allowed."


# ─────────────────────────────── the header ────────────────────────────────


def test_the_real_header_is_read() -> None:
    """Exactly as Buffer sends it: `"100-in-15min"; r=98; t=897`."""
    assert parse_rate_limit('"100-in-15min"; r=98; t=897') == (98, 897)


def test_a_missing_header_is_not_an_empty_quota() -> None:
    """The distinction the rail depends on. `None` means "no news"; zero would
    mean "stop", and a response without the header is not a refusal."""
    assert parse_rate_limit(None) == (None, None)
    assert parse_rate_limit("") == (None, None)


def test_an_unreadable_header_is_not_an_empty_quota_either() -> None:
    assert parse_rate_limit('"100-in-15min"; r=lots; t=897') == (None, None)
    assert parse_rate_limit("something else entirely") == (None, None)


def test_a_header_with_only_a_remainder_still_answers() -> None:
    """Buffer is not promised to send both halves, and the remainder alone is
    the half that decides whether to stop."""
    assert parse_rate_limit('"100-in-15min"; r=3') == (3, None)


#: The header off the real 429 of 16-sep-2026, copied from the probe rather
#: than paraphrased — two policies in one header, comma separated.
TWO_WINDOWS = '"100-in-15min"; r=98; t=146, "250-in-1day"; r=0; t=47729'


def test_the_daily_window_is_the_one_that_binds() -> None:
    """The bug that let the rail run into a wall it was built to see coming.

    Splitting on `;` alone makes ` t=146, "250-in-1day"` a fragment that is not
    an integer, so the whole header read as `(None, None)`: no news, no brake,
    and the daily ceiling discovered by hitting it every fifteen minutes for
    fourteen hours. What binds is the policy with the least left — with **its
    own** refill, not the other one's.
    """
    assert parse_rate_limit(TWO_WINDOWS) == (0, 47729)
    # One policy still reads exactly as it did.
    assert parse_rate_limit('"100-in-15min"; r=98; t=897') == (98, 897)
    # And the tighter window is not always the daily one.
    assert parse_rate_limit('"100-in-15min"; r=3; t=5, "250-in-1day"; r=200; t=10') == (
        3,
        5,
    )


def test_a_tie_between_the_windows_takes_the_longer_wait() -> None:
    """Both spent at once is the case that punishes a careless `min`: it would
    return the first policy, lift the brake after 146 seconds, and walk into a
    thirteen-hour wall. The longer wait is the one that is true of both."""
    assert parse_rate_limit('"100-in-15min"; r=0; t=146, "250-in-1day"; r=0; t=47729') == (
        0,
        47729,
    )
    assert parse_rate_limit('"250-in-1day"; r=0; t=47729, "100-in-15min"; r=0; t=146') == (
        0,
        47729,
    )


def test_the_space_the_grammar_allows_does_not_lose_the_field() -> None:
    """The header's own grammar permits space around `=`. Buffer does not use
    it, but dropping the field silently reads exactly like a header with no
    remainder in it — no news, no brake."""
    assert parse_rate_limit('  "100-in-15min" ;  r = 98 ;  t = 146 ') == (98, 146)


@pytest.mark.asyncio
async def test_a_refill_in_the_past_is_not_a_brake() -> None:
    """`t` is a number Buffer chooses. A negative one puts the refill behind
    us, and the pre-check needs it ahead: the brake would read as armed and
    never engage, which is the same silence as having no brake at all."""

    class _Resp:
        status_code = 200
        headers = {"ratelimit": '"100-in-15min"; r=0; t=-5'}

        def json(self) -> dict:
            return {"data": {"ok": True}}

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kw: object) -> Any:
            return _Resp()

    before = buffer_publisher.monotonic()
    with patch("app.services.buffer_publisher.httpx.AsyncClient", return_value=_Client()):
        await buffer_publisher._graphql("query {}", {})

    assert buffer_publisher._quota_remaining == 0
    # Not "in the future" — the clamp floors it at the instant of the call, and
    # microseconds pass. What must never happen is landing five seconds behind it.
    assert buffer_publisher._quota_refills_at >= before


def test_a_header_that_states_no_remainder_at_all_is_not_a_brake() -> None:
    """The other way to reach `(None, …)`: every policy parses, none of them
    says what is left. It has to stay "no news" — the same answer as garbage,
    but reached by a different branch, and only one of the two was covered."""
    assert parse_rate_limit('"100-in-15min"; t=897') == (None, 897)
    assert parse_rate_limit('"100-in-15min"; t=897, "250-in-1day"; t=40000') == (None, 897)
    assert parse_rate_limit("something else entirely") == (None, None)


def test_a_policy_that_states_its_refill_wins_a_tie_with_one_that_does_not() -> None:
    """A tie between a stated wait and an unstated one is not a real tie: the
    number is the only thing that can hold the brake."""
    assert parse_rate_limit('"a"; r=3, "b"; r=3; t=900') == (3, 900)
    assert parse_rate_limit('"a"; r=3; t=900, "b"; r=3') == (3, 900)


def test_one_unreadable_policy_still_means_no_news() -> None:
    """A header this rail cannot fully parse is not evidence of an empty quota,
    however many policies it carries."""
    assert parse_rate_limit('"100-in-15min"; r=98; t=146, "250-in-1day"; r=lots') == (
        None,
        None,
    )


# ──────────────────────────── the proactive brake ──────────────────────────


@pytest.fixture(autouse=True)
def _fresh_quota() -> Any:
    """Module state, so it must not leak between tests — or between a test and
    the rest of the suite, which is how one exhausted-quota test would stop
    every publisher test that ran after it."""
    buffer_publisher._quota_remaining = None
    buffer_publisher._quota_refills_at = 0.0
    yield
    buffer_publisher._quota_remaining = None
    buffer_publisher._quota_refills_at = 0.0


@pytest.mark.asyncio
async def test_the_rail_stops_before_the_last_requests_are_spent() -> None:
    """No HTTP call at all: the point is not to discover the ceiling."""
    buffer_publisher._quota_remaining = 1
    buffer_publisher._quota_refills_at = buffer_publisher.monotonic() + 600

    with patch("app.services.buffer_publisher.httpx.AsyncClient") as client:
        with pytest.raises(QuotaReached, match="1 Buffer requests left"):
            await buffer_publisher._graphql("query {}", {})
    assert not client.called, "the brake sent the request it was meant to withhold"


@pytest.mark.asyncio
async def test_the_brake_lifts_once_the_window_has_refilled() -> None:
    """A spent window is spent for fifteen minutes, not forever. Holding past
    the refill would be a rail that stops itself permanently."""
    buffer_publisher._quota_remaining = 0
    buffer_publisher._quota_refills_at = buffer_publisher.monotonic() - 1

    sent: list[str] = []

    class _Resp:
        status_code = 200
        headers = {"ratelimit": '"100-in-15min"; r=99; t=900'}

        def json(self) -> dict:
            return {"data": {"ok": True}}

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kw: object) -> _Resp:
            sent.append(url)
            return _Resp()

    with patch("app.services.buffer_publisher.httpx.AsyncClient", return_value=_Client()):
        assert await buffer_publisher._graphql("query {}", {}) == {"data": {"ok": True}}
    assert sent, "the brake held past its own refill"
    assert buffer_publisher._quota_remaining == 99


def _refusal(retry_after: str | None, ratelimit: str | None = None) -> Any:
    """Buffer's 429, with the body it actually sends."""

    class _Resp:
        status_code = 429
        headers = {
            k: v
            for k, v in (("Retry-After", retry_after), ("ratelimit", ratelimit))
            if v is not None
        }

        def json(self) -> dict:
            return {
                "errors": [
                    {
                        "message": "Too many requests from this client. "
                        "Please try again later.",
                        "extensions": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "window": "24h",
                        },
                    }
                ]
            }

    return _Resp


@pytest.mark.asyncio
async def test_a_429_stops_the_next_request_before_it_leaves() -> None:
    """One refusal is a fact about the window, not about that one request.

    Until this, a 429 raised and left `_quota_remaining` untouched, so the next
    tick asked again — and the next, every fifteen minutes, all of 16-sep. The
    request that is never sent is the whole point.
    """
    resp = _refusal("100")
    calls: list[str] = []

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kw: object) -> Any:
            calls.append(url)
            return resp()

    with patch("app.services.buffer_publisher.httpx.AsyncClient", return_value=_Client()):
        with pytest.raises(QuotaReached, match="24h"):
            await buffer_publisher._graphql("query {}", {})
        assert len(calls) == 1

        with pytest.raises(QuotaReached):
            await buffer_publisher._graphql("query {}", {})
    assert len(calls) == 1, "the second tick spent a request to be told the same thing"


@pytest.mark.asyncio
async def test_the_brake_never_holds_longer_than_an_hour() -> None:
    """Buffer's daily `Retry-After` is thirteen hours. Holding for all of it in
    process memory is a rail that cannot come back if that number is wrong or
    the reset lands early — and a rejected request costs no quota, so asking
    again an hour later is cheap. The cap is the way back."""
    resp = _refusal("47729")

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kw: object) -> Any:
            return resp()

    with patch("app.services.buffer_publisher.httpx.AsyncClient", return_value=_Client()):
        with pytest.raises(QuotaReached):
            await buffer_publisher._graphql("query {}", {})

    held = buffer_publisher._quota_refills_at - buffer_publisher.monotonic()
    assert held <= buffer_publisher._QUOTA_BRAKE_MAX_SECONDS
    assert held > 0, "the brake has to hold for something"


@pytest.mark.asyncio
async def test_retry_after_overrules_the_header_it_arrived_with() -> None:
    """They can disagree, and `Retry-After` is the one Buffer commits to. The
    header is read first, a few lines earlier, so without this the refusal
    would be timed by the number it was meant to correct."""
    resp = _refusal("2400", ratelimit='"100-in-15min"; r=0; t=5')

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kw: object) -> Any:
            return resp()

    with patch("app.services.buffer_publisher.httpx.AsyncClient", return_value=_Client()):
        with pytest.raises(QuotaReached):
            await buffer_publisher._graphql("query {}", {})

    held = buffer_publisher._quota_refills_at - buffer_publisher.monotonic()
    # Three distinguishable numbers on purpose: 5s is the header, 900s is the
    # fallback for a refusal with no timing, 2400s is what Retry-After says.
    # Only the last one can land here, or the test would pass on the fallback.
    assert 1200 < held <= buffer_publisher._QUOTA_BRAKE_MAX_SECONDS, (
        f"neither the header ({5}s) nor the fallback "
        f"({buffer_publisher._QUOTA_BRAKE_FALLBACK_SECONDS}s) may win: {held}s"
    )


# ───────────────────────── a full queue is not a failure ───────────────────


def test_buffers_own_words_are_recognised() -> None:
    assert slots_are_full(FULL)


def test_the_match_survives_the_casing_buffer_chooses() -> None:
    assert slots_are_full("SCHEDULED POSTS LIMIT REACHED")


def test_an_ordinary_refusal_is_not_mistaken_for_a_full_queue() -> None:
    """The one that must stay FAILED: a caption the platform will refuse again
    tomorrow is about the piece, and leaving it pending would retry it forever."""
    assert not slots_are_full(
        "[InvalidInputError] Instagram posts require at least one image or video."
    )
    assert not slots_are_full("")


# ──────────────────────────── against the database ─────────────────────────


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _publishing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "CONTENT_PUBLISH_ENABLED", True, raising=False)
    monkeypatch.setattr(s, "CONTENT_PUBLISH_MAX_PER_DAY", 8, raising=False)
    monkeypatch.setattr(s, "BUFFER_SIMULATED", False, raising=False)
    monkeypatch.setattr(s, "BUFFER_ACCESS_TOKEN", "tok", raising=False)
    monkeypatch.setattr(s, "BUFFER_ORG_ID", "org-1", raising=False)
    monkeypatch.setattr(s, "BUFFER_CHANNEL_YOUTUBE", YT, raising=False)
    monkeypatch.setattr(s, "BUFFER_CHANNEL_TIKTOK", TT, raising=False)
    monkeypatch.setattr(s, "BUFFER_CHANNEL_INSTAGRAM", IG, raising=False)
    monkeypatch.setattr(s, "CONTENT_ORG_ID", ORG, raising=False)
    monkeypatch.setattr(
        s, "CONTENT_PUBLIC_BASE_URL", "https://panel.example.com", raising=False
    )
    monkeypatch.setattr(s, "CONTENT_SCHEDULE_ENABLED", False, raising=False)
    monkeypatch.setattr(s, "CONTENT_SCHEDULE_HORIZON_DAYS", 10, raising=False)
    monkeypatch.setattr(s, "CONTENT_CTA_URL", "", raising=False)


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_publications"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.execute(
            text(
                "UPDATE agent_settings SET brokerage_line='Engel & Völkers' "
                "WHERE org_id=1"
            )
        )
        await db.commit()


async def _piece(window: date | None) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.APPROVED,
            hook="What a Denver home is worth today.",
            script="Three numbers decide the price.",
            caption="Three numbers decide the price. denverhomestory.com",
            media_path="a" * 32 + ".mp4",
            approved_by="office",
            publish_window_start=window,
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _rows(piece_id: int) -> list[tuple]:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text(
                    "SELECT platform, status, last_error FROM content_publications "
                    "WHERE piece_id=:p ORDER BY platform"
                ),
                {"p": piece_id},
            )
        ).all()


@pytest.mark.asyncio
async def test_a_full_buffer_queue_leaves_the_platform_pending_not_failed(
    database_url: str,
) -> None:
    """The bug that killed three approved pieces, stated as a test.

    FAILED is terminal for a platform — `publish_piece` only releases failed
    rows when a person approves the piece again — so recording a full calendar
    as a content failure loses the piece for good.
    """
    await _cleanup()
    try:
        piece_id = await _piece(None)
        with patch(
            "app.services.buffer_publisher.verify_organization", new=AsyncMock()
        ):
            with patch(
                "app.services.buffer_publisher._send",
                new=AsyncMock(side_effect=BufferRefused(FULL)),
            ):
                with org_scope(ORG):
                    async with get_session_factory()() as db:
                        await publish_approved(db)

        rows = await _rows(piece_id)
        assert rows, "no publication row was created at all"
        for platform, status, last_error in rows:
            assert status == PublicationStatus.PENDING.value, (
                f"{platform} was recorded as {status}; FAILED here is the death "
                "sentence this test exists to prevent"
            )
            assert "limit reached" in (last_error or "").lower(), (
                "the reason was dropped, so nobody can tell a full queue from "
                "a piece nobody ever tried"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_window_beyond_the_horizon_does_not_take_a_slot_today(
    database_url: str,
) -> None:
    """The cause, not the symptom. Six weeks out is what filled Instagram."""
    await _cleanup()
    try:
        far = await _piece(date.today() + timedelta(days=42))
        with patch(
            "app.services.buffer_publisher.verify_organization", new=AsyncMock()
        ):
            with patch(
                "app.services.buffer_publisher._send",
                new=AsyncMock(return_value="post-1"),
            ) as send:
                with org_scope(ORG):
                    async with get_session_factory()() as db:
                        await publish_approved(db)

        assert not send.called, "a piece six weeks out was handed to Buffer today"
        assert not await _rows(far), "it even claimed a row"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_window_inside_the_horizon_goes_out(database_url: str) -> None:
    """The other half: a horizon that held everything would be a rail that
    never publishes, and would pass the test above just as well."""
    await _cleanup()
    try:
        near = await _piece(date.today() + timedelta(days=2))
        with patch(
            "app.services.buffer_publisher.verify_organization", new=AsyncMock()
        ):
            with patch(
                "app.services.buffer_publisher._send",
                new=AsyncMock(return_value="post-1"),
            ) as send:
                with org_scope(ORG):
                    async with get_session_factory()() as db:
                        await publish_approved(db)

        assert send.called, "a piece due in two days was held back"
        assert await _rows(near)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_piece_with_no_window_is_never_held_by_the_horizon(
    database_url: str,
) -> None:
    """The calculator pieces are permanent and carry no window at all. A
    horizon that caught them would silently stop the only evergreen content
    the channel has."""
    await _cleanup()
    try:
        evergreen = await _piece(None)
        with patch(
            "app.services.buffer_publisher.verify_organization", new=AsyncMock()
        ):
            with patch(
                "app.services.buffer_publisher._send",
                new=AsyncMock(return_value="post-1"),
            ) as send:
                with org_scope(ORG):
                    async with get_session_factory()() as db:
                        await publish_approved(db)

        assert send.called, "a permanent piece was held by a calendar it has no place on"
        assert await _rows(evergreen)
    finally:
        await _cleanup()

# ───────────────────── and the wait is not silent ──────────────────────────


@pytest.mark.asyncio
async def test_a_full_queue_rings_once_and_then_stops(database_url: str) -> None:
    """The half that makes PENDING safe.

    Leaving a platform pending is right — it recovers on its own — but a piece
    that waits in silence is the thing that went wrong in the first place:
    nothing said that 33, 34 and 36 had stopped. So the transition into the
    wait is announced.

    And exactly once. The publisher comes round every fifteen minutes, so a
    notice per attempt would be ninety-six a day per platform, which is noise
    nobody reads — the same outcome as no notice, reached more expensively.
    """
    await _cleanup()
    rung: list[tuple[int, str]] = []

    async def remember(piece_id: int, hook: str, platform: str) -> bool:
        rung.append((piece_id, platform))
        return True

    try:
        piece_id = await _piece(None)
        with patch(
            "app.services.buffer_publisher.verify_organization", new=AsyncMock()
        ):
            with patch(
                "app.services.buffer_publisher._send",
                new=AsyncMock(side_effect=BufferRefused(FULL)),
            ):
                with patch(
                    "app.services.buffer_publisher.notify_slots_full", new=remember
                ):
                    for _tick in range(3):
                        with org_scope(ORG):
                            async with get_session_factory()() as db:
                                await publish_approved(db)

        assert rung, "the piece stopped and nothing said so"
        platforms = [p for _id, p in rung]
        assert sorted(platforms) == sorted(set(platforms)), (
            f"rang more than once per platform across three ticks: {platforms}"
        )
        assert {pid for pid, _p in rung} == {piece_id}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_ordinary_refusal_does_not_ring_this_bell(database_url: str) -> None:
    """A caption Instagram will not accept is a different problem with a
    different answer, and it must not arrive dressed as a queue that is full."""
    await _cleanup()
    rung: list[int] = []

    async def remember(piece_id: int, hook: str, platform: str) -> bool:
        rung.append(piece_id)
        return True

    try:
        await _piece(None)
        with patch(
            "app.services.buffer_publisher.verify_organization", new=AsyncMock()
        ):
            with patch(
                "app.services.buffer_publisher._send",
                new=AsyncMock(
                    side_effect=BufferRefused("[InvalidInputError] posts require a type")
                ),
            ):
                with patch(
                    "app.services.buffer_publisher.notify_slots_full", new=remember
                ):
                    with org_scope(ORG):
                        async with get_session_factory()() as db:
                            await publish_approved(db)

        assert rung == [], "an ordinary refusal rang the full-queue bell"
    finally:
        await _cleanup()


# ───────────────── a spent quota is a budget, not a broken tenant ───────────


@pytest.mark.asyncio
async def test_a_quota_out_is_a_quiet_tick_not_an_org_failure(
    database_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """What production actually logged every fifteen minutes on 16-sep.

    `QuotaReached` from the reconcile step rose all the way to
    `run_for_every_org`, which writes "org 1 failed during a sweep" with a
    traceback at ERROR. Read at a glance that says this tenant's data is
    broken; it was a rail waiting for a clock. One warning, no traceback, and
    an empty tick is the honest shape.
    """
    await _cleanup()
    try:
        await _piece(None)
        caplog.set_level(logging.DEBUG, logger="app.services.buffer_publisher")
        with patch(
            "app.services.buffer_publisher.reconcile_scheduled",
            new=AsyncMock(side_effect=QuotaReached("Buffer quota reached on its 24h window")),
        ):
            with patch(
                "app.services.buffer_publisher._send", new=AsyncMock(return_value="p-1")
            ) as send:
                with org_scope(ORG):
                    async with get_session_factory()() as db:
                        assert await publish_approved(db) == 0

        assert not send.called, "the tick published with no quota to reconcile with"
        mine = [r for r in caplog.records if r.name == "app.services.buffer_publisher"]
        assert [r.levelno for r in mine if r.levelno >= logging.ERROR] == []
        warnings = [r for r in mine if r.levelno == logging.WARNING]
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert "quota" in warnings[0].getMessage().lower()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_identity_check_runs_out_of_quota_just_as_quietly(
    database_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The door the plan did not name.

    `verify_organization` is a Buffer call too, and it sits past the three
    steps that were guarded — so on a tick with nothing to reconcile, nothing
    to backfill and nothing to realign, it is the *first* request of the tick
    and the only one that can raise. Guarding the other three and not this one
    leaves exactly the traceback the fix was for.
    """
    await _cleanup()
    try:
        await _piece(None)
        caplog.set_level(logging.DEBUG, logger="app.services.buffer_publisher")
        with patch(
            "app.services.buffer_publisher.reconcile_scheduled", new=AsyncMock()
        ):
            with patch("app.services.buffer_publisher.backfill_links", new=AsyncMock()):
                with patch(
                    "app.services.buffer_publisher.realign_windows", new=AsyncMock()
                ):
                    with patch(
                        "app.services.buffer_publisher.verify_organization",
                        new=AsyncMock(side_effect=QuotaReached("Buffer quota reached")),
                    ):
                        with patch(
                            "app.services.buffer_publisher._send",
                            new=AsyncMock(return_value="p-1"),
                        ) as send:
                            with org_scope(ORG):
                                async with get_session_factory()() as db:
                                    assert await publish_approved(db) == 0

        assert not send.called, "a piece was posted without knowing whose rail this is"
        mine = [r for r in caplog.records if r.name == "app.services.buffer_publisher"]
        assert [r.levelno for r in mine if r.levelno >= logging.ERROR] == []
        warnings = [r for r in mine if r.levelno == logging.WARNING]
        # The message, not just the count: `publish_approved` has two other
        # early exits that return 0 with exactly one warning ("configured but
        # unusable", "not our rail"), so a count alone stays green on a tick
        # that never reached the identity check at all.
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert "quota" in warnings[0].getMessage().lower()
    finally:
        await _cleanup()


# ───────────── a refusal this rail cannot read is still a refusal ───────────


@pytest.mark.asyncio
async def test_a_429_that_says_nothing_still_arms_the_brake() -> None:
    """`Retry-After` may legitimately be an HTTP date, and a proxy in front of
    Buffer sends neither header. Zeroing the counter without a refill ahead
    arms the brake on one side only — and the pre-check needs both, so every
    tick would go back out to be refused again. That is the 16-sep behaviour
    the fix exists to end, reached by the other door."""
    calls: list[str] = []

    class _Resp:
        status_code = 429
        headers = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}

        def json(self) -> dict:
            return {"errors": []}

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kw: object) -> Any:
            calls.append(url)
            return _Resp()

    with patch("app.services.buffer_publisher.httpx.AsyncClient", return_value=_Client()):
        with pytest.raises(QuotaReached):
            await buffer_publisher._graphql("query {}", {})
        with pytest.raises(QuotaReached):
            await buffer_publisher._graphql("query {}", {})

    assert len(calls) == 1, "a refusal with no timing let every tick back onto the network"


@pytest.mark.asyncio
async def test_a_body_this_rail_cannot_read_is_still_a_quota_refusal() -> None:
    """The failure that would undo the whole phase. Reading the window out of
    the body happens inside the 429 handler, before the raise — so a body
    shaped unlike the one measured raised `AttributeError` instead of
    `QuotaReached`, sailed past every `except QuotaReached`, and produced the
    same "failed during a sweep" traceback the fix removes."""
    for body in (
        {"errors": [{"extensions": "nope"}]},
        {"errors": [{"extensions": [1]}]},
        {"errors": [{"extensions": None}]},
        {"errors": 5},
        {"errors": "boom"},
        {"data": None},
        [1, 2, 3],
    ):

        class _Resp:
            status_code = 429
            headers = {"Retry-After": "60"}

            def json(self, _b: Any = body) -> Any:
                return _b

        class _Client:
            async def __aenter__(self) -> "_Client":
                return self

            async def __aexit__(self, *a: object) -> None:
                return None

            async def post(self, url: str, **kw: object) -> Any:
                return _Resp()

        buffer_publisher._quota_remaining = None
        buffer_publisher._quota_refills_at = 0.0
        with patch(
            "app.services.buffer_publisher.httpx.AsyncClient", return_value=_Client()
        ):
            with pytest.raises(QuotaReached):
                await buffer_publisher._graphql("query {}", {})


@pytest.mark.asyncio
async def test_what_buffer_says_cannot_forge_a_log_line() -> None:
    """The window is server-supplied text on its way into a log record. A
    newline in it writes a second line that looks like ours."""

    class _Resp:
        status_code = 429
        headers = {"Retry-After": "60"}

        def json(self) -> dict:
            return {
                "errors": [
                    {
                        "extensions": {
                            "window": "24h\nERROR the database was dropped" + "x" * 500
                        }
                    }
                ]
            }

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kw: object) -> Any:
            return _Resp()

    with patch("app.services.buffer_publisher.httpx.AsyncClient", return_value=_Client()):
        with pytest.raises(QuotaReached) as caught:
            await buffer_publisher._graphql("query {}", {})

    message = str(caught.value)
    assert "\n" not in message, message
    assert len(message) < 200, len(message)


@pytest.mark.asyncio
async def test_a_refusal_with_no_timing_does_not_inherit_the_daily_hour() -> None:
    """A 429 that is not about the quota — a proxy in front of Buffer, say —
    arriving with a healthy `ratelimit` header. The header's `t` says when the
    daily window refills, which is not how long this refusal lasts; taking the
    longer of the two would stop the rail for **every** agency for an hour
    (the quota state is per API client, not per tenant) where before the
    change it cost a single tick."""
    resp = _refusal(None, ratelimit='"100-in-15min"; r=95; t=700, "250-in-1day"; r=30; t=40000')

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

        async def post(self, url: str, **kw: object) -> Any:
            return resp()

    with patch("app.services.buffer_publisher.httpx.AsyncClient", return_value=_Client()):
        with pytest.raises(QuotaReached):
            await buffer_publisher._graphql("query {}", {})

    held = buffer_publisher._quota_refills_at - buffer_publisher.monotonic()
    assert held <= buffer_publisher._QUOTA_BRAKE_FALLBACK_SECONDS, (
        f"a refusal with no stated wait inherited the daily window: {held}s"
    )
