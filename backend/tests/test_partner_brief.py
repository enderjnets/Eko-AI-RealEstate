"""The brief is reachable by its token, by nobody else, and it keeps answers.

Every test drives the real ASGI stack rather than calling the handlers, and
that is load-bearing here for the same reason `test_public_capture.py` says it
is: `conftest` binds the default organization into every test by an autouse
fixture, and `TenantMiddleware` sets the organization to None for
`/api/v1/public`. Calling the handler directly would hand it the one thing
production never gives it — a tenant already bound — and the test would pass
against an endpoint incapable of resolving one.

The isolation test at the bottom is the one to keep if the file ever has to
shrink. A brief carries a past client's name and street address, and the
endpoint that serves it has no session to check: the token IS the credential.
What stops brief B leaking to whoever holds token A is that the handler binds
the row's own organization before it reads anything, and that is exactly what
that test drives.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.v1.public import (
    BRIEF_NOTIFY_QUIET,
    BRIEF_PER_IP_LIMIT,
    reset_rate_limits,
)
from app.config import get_settings
from app.db.base import get_bypass_session_factory
from app.main import app
from app.models.partner_brief import new_token

PAYLOAD = {
    "headline": "Nine names, and one listing that has gone quiet",
    "blocks": [
        {"kind": "prose", "id": "why", "heading": "What this is", "body": ["Because."]},
        {
            "kind": "people",
            "id": "nine",
            "people": [{"id": "p1", "name": "Sherpa Yangdi"}],
        },
    ],
}


@pytest.fixture(autouse=True)
def _clean_rate_limits() -> None:
    # Module-level counters would leak between tests and make the order of this
    # file part of its meaning.
    reset_rate_limits()
    yield
    reset_rate_limits()


async def _seed(org_id: int = 1, *, payload: dict | None = None) -> str:
    """One brief on `org_id`. Returns its token."""
    token = new_token()
    async with get_bypass_session_factory()() as db:
        # `org_id` written explicitly: a bypass session has no acting
        # organization, so nothing stamps it — the same rule the creation
        # script follows.
        await db.execute(
            text(
                "INSERT INTO partner_briefs (org_id, token, title, recipient, "
                "payload, answers) VALUES (:o, :t, :ti, :r, :p, '{}')"
            ),
            {
                "o": org_id,
                "t": token,
                "ti": "Nine names and a listing",
                "r": "Natalia and Robbie",
                "p": __import__("json").dumps(payload or PAYLOAD),
            },
        )
        await db.commit()
    return token


async def _other_org() -> int:
    async with get_bypass_session_factory()() as db:
        org_id = (
            await db.execute(
                text(
                    "INSERT INTO organizations (name, slug, status, plan) VALUES "
                    "('brief-other', 'brief-other', 'active', 'pilot') RETURNING id"
                )
            )
        ).scalar_one()
        await db.commit()
    return int(org_id)


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM partner_briefs"))
        await db.execute(text("DELETE FROM organizations WHERE slug = 'brief-other'"))
        await db.commit()


async def _get(token: str, **headers: str) -> tuple[int, dict]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get(f"/api/v1/public/brief/{token}", headers=headers or None)
    return res.status_code, (res.json() if res.content else {})


async def _post(
    token: str, answers: dict, *, notify: bool = True, **headers: str
) -> tuple[int, dict]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.post(
            f"/api/v1/public/brief/{token}",
            json={"answers": answers, "notify": notify},
            headers=headers or None,
        )
    return res.status_code, (res.json() if res.content else {})


async def test_the_page_gets_its_own_content() -> None:
    token = await _seed()
    try:
        status, body = await _get(token)
        assert status == 200
        assert body["payload"]["headline"].startswith("Nine names")
        assert body["answers"] == {}
        assert body["answered_at"] is None
        # The token is never echoed back. The page already has it; putting it
        # in a response body is one more place for it to end up in a log.
        assert "token" not in body
    finally:
        await _cleanup()


async def test_an_unknown_token_is_indistinguishable_from_a_malformed_one() -> None:
    """Both 404 `unknown_brief`, and that is the whole design.

    A different status or detail for "well-formed but not found" would turn
    this endpoint into an oracle: a caller could learn the shape of a real
    token by watching which guesses were merely wrong.
    """
    unknown = await _get(new_token())
    malformed = await _get("nope")
    assert unknown[0] == 404
    assert malformed[0] == 404
    assert unknown[1] == malformed[1] == {"detail": "unknown_brief"}


async def test_opening_it_is_recorded_once_and_never_refreshed() -> None:
    token = await _seed()
    try:
        await _get(token)
        async with get_bypass_session_factory()() as db:
            first = (
                await db.execute(
                    text("SELECT opened_at FROM partner_briefs WHERE token = :t"),
                    {"t": token},
                )
            ).scalar_one()
        assert first is not None

        await _get(token)
        async with get_bypass_session_factory()() as db:
            second = (
                await db.execute(
                    text("SELECT opened_at FROM partner_briefs WHERE token = :t"),
                    {"t": token},
                )
            ).scalar_one()
        # The question is "have they seen it", and that stops changing once it
        # is yes. A second load must not turn this into a last-seen stamp.
        assert second == first
    finally:
        await _cleanup()


async def test_answers_are_kept_and_come_back_on_the_next_load() -> None:
    token = await _seed()
    try:
        with patch(
            "app.api.v1.public.send_brief_answered_notice", new=AsyncMock(return_value=True)
        ):
            status, body = await _post(token, {"nine": {"p1": {"state": "out"}}})
        assert status == 200
        assert body["ok"] is True

        _, reread = await _get(token)
        assert reread["answers"] == {"nine": {"p1": {"state": "out"}}}
        assert reread["answered_at"] is not None
    finally:
        await _cleanup()


async def test_saving_replaces_rather_than_merges() -> None:
    """Un-ticking something has to be expressible.

    The page sends its whole state on every save, so a merge would make a
    cleared answer impossible to express — the key would simply be absent and
    the old value would survive as a decision nobody made.
    """
    token = await _seed()
    try:
        with patch(
            "app.api.v1.public.send_brief_answered_notice", new=AsyncMock(return_value=True)
        ):
            await _post(token, {"nine": {"p1": {"state": "out"}}, "note": "hello"})
            await _post(token, {"note": "hello"})
        _, body = await _get(token)
        assert body["answers"] == {"note": "hello"}
    finally:
        await _cleanup()


async def test_a_huge_answer_is_refused_before_it_is_stored() -> None:
    token = await _seed()
    try:
        with patch(
            "app.api.v1.public.send_brief_answered_notice", new=AsyncMock(return_value=True)
        ) as notice:
            status, body = await _post(token, {"note": "x" * 70_000})
        assert status == 413
        assert body == {"detail": "answers_too_large"}
        notice.assert_not_awaited()

        _, after = await _get(token)
        assert after["answers"] == {}
    finally:
        await _cleanup()


async def test_the_brief_budget_is_not_lead_captures() -> None:
    """Spending the brief budget must leave capture's alone.

    Sharing one counter would mean Natalia re-reading the page on a bad signal
    is what stops a seller's form from being written — backwards, and the same
    mistake the landing beacons already have their own budget to avoid.
    """
    from app.api.v1.public import _global_hits, _hits

    token = await _seed()
    try:
        for _ in range(BRIEF_PER_IP_LIMIT):
            status, _ = await _get(token, **{"CF-Connecting-IP": "203.0.113.9"})
            assert status == 200
        status, body = await _get(token, **{"CF-Connecting-IP": "203.0.113.9"})
        assert status == 429
        assert body == {"detail": "too_many_requests"}

        assert not _hits, "the brief spent the capture budget"
        assert not _global_hits, "the brief spent the global capture budget"
    finally:
        await _cleanup()


async def test_one_agency_brief_never_answers_with_another_agencys() -> None:
    """The handler binds the row's OWN organization before it reads anything.

    There is no session here to check, so this is the whole tenant boundary:
    holding token A must never reach brief B, and the org bound while serving A
    must be A's.
    """
    other = await _other_org()
    try:
        mine = await _seed(1, payload={"headline": "mine"})
        theirs = await _seed(other, payload={"headline": "theirs"})

        assert (await _get(mine))[1]["payload"]["headline"] == "mine"
        assert (await _get(theirs))[1]["payload"]["headline"] == "theirs"

        with patch(
            "app.api.v1.public.send_brief_answered_notice", new=AsyncMock(return_value=True)
        ):
            await _post(theirs, {"who": "theirs"})

        # The write landed on the other agency's row and touched nothing of
        # ours — which is only true if the org was rebound per request.
        assert (await _get(mine))[1]["answers"] == {}
        assert (await _get(theirs))[1]["answers"] == {"who": "theirs"}
    finally:
        await _cleanup()


async def test_the_operator_is_told_what_they_answered() -> None:
    from app.services import brief_notify

    token = await _seed()
    try:
        sent: dict = {}

        async def _fake_send(**kwargs):
            sent.update(kwargs)
            return {"id": "re_test"}

        # `OWNER_NOTICE_EMAIL` is blanked unconditionally by conftest, so a test
        # about the operator's copy sets it here, beside the assertion.
        with (
            patch.object(get_settings(), "OWNER_NOTICE_EMAIL", "ender@example.com"),
            patch.object(brief_notify, "send_email", _fake_send),
        ):
            status, _ = await _post(
                token, {"nine": {"p1": {"state": "out"}}, "note": "call him"}
            )
        assert status == 200
        assert sent["to"] == "ender@example.com"
        # The answers are IN the mail, not a link to go and read them. The
        # whole point of the page is that nobody has to open anything.
        assert "call him" in sent["body_text"]
        # By name and in words. This line used to assert the raw `out` was
        # present, which was true and was the defect: the reader was being
        # handed the machine's vocabulary.
        assert "Sherpa Yangdi — LEAVE OUT" in sent["body_text"]
    finally:
        await _cleanup()


async def test_no_operator_address_is_not_an_error() -> None:
    """A fresh install has none, and the brief still works perfectly."""
    from app.services.brief_notify import send_brief_answered_notice

    token = await _seed()
    try:
        async with get_bypass_session_factory()() as db:
            brief_id = (
                await db.execute(
                    text("SELECT id FROM partner_briefs WHERE token = :t"), {"t": token}
                )
            ).scalar_one()
        with patch.object(get_settings(), "OWNER_NOTICE_EMAIL", ""):
            assert await send_brief_answered_notice(int(brief_id)) is False
    finally:
        await _cleanup()


async def test_typing_does_not_mail_the_operator_once_per_keystroke() -> None:
    """The page autosaves a second after the last keystroke. Ninety seconds of
    typing produced EIGHT emails in production on 13-sep-2026 — not a bug in
    the sending, a design mistake: the notice was written for an event that
    turns out to happen every second and a half.

    A deliberate press always tells us. An autosave tells us only when the
    brief has been quiet, so somebody who fills it in and never finds the
    button is still not silent.
    """
    token = await _seed()
    try:
        with patch(
            "app.api.v1.public.send_brief_answered_notice", new=AsyncMock(return_value=True)
        ) as notice:
            # First autosave on an untouched brief: they have started, and
            # that is worth knowing even though nobody pressed anything.
            await _post(token, {"a": 1}, notify=False)
            assert notice.await_count == 1

            # The rest of the typing session is silent.
            for _ in range(6):
                await _post(token, {"a": 2}, notify=False)
            assert notice.await_count == 1, "an autosave burst mailed more than once"

            # And the button always speaks, however recent the last save.
            await _post(token, {"a": 3}, notify=True)
            assert notice.await_count == 2
    finally:
        await _cleanup()


async def test_a_brief_left_quiet_and_picked_up_again_does_tell_us() -> None:
    """The coalescing must not become silence.

    Somebody who answers half of it, puts the phone down and comes back after
    lunch has produced new information, and the whole point of the notice is
    that nobody has to remember to go and look.
    """
    token = await _seed()
    try:
        with patch(
            "app.api.v1.public.send_brief_answered_notice", new=AsyncMock(return_value=True)
        ) as notice:
            await _post(token, {"a": 1}, notify=False)
            assert notice.await_count == 1

            # Age the last save past the quiet window.
            stale = datetime.now(UTC) - BRIEF_NOTIFY_QUIET - timedelta(minutes=1)
            async with get_bypass_session_factory()() as db:
                await db.execute(
                    text("UPDATE partner_briefs SET answered_at = :t WHERE token = :k"),
                    {"t": stale, "k": token},
                )
                await db.commit()

            await _post(token, {"a": 2}, notify=False)
            assert notice.await_count == 2, "coming back after a break went unreported"
    finally:
        await _cleanup()


async def test_the_notice_reads_like_an_answer_not_a_lookup_exercise() -> None:
    """Names, not ids.

    The first notice this ever sent read `nine: p1: state: out`. Every fact was
    in it and none of it was usable: deciding whether to phone somebody meant
    opening the brief to find out who `p1` was. The payload already holds every
    name — the mail reads it as a legend rather than making the reader be one.
    """
    from app.models.partner_brief import PartnerBrief
    from app.services.brief_notify import build_body

    brief = PartnerBrief(
        title="Nine names and a listing",
        recipient="Natalia and Robbie",
        payload={
            "blocks": [
                {
                    "kind": "people",
                    "id": "nine",
                    "heading": "The nine who still own the home",
                    "people": [
                        {"id": "p1", "name": "Sherpa Yangdi"},
                        {"id": "p4", "name": "Auger Julie A"},
                    ],
                },
                {
                    "kind": "questions",
                    "fields": [{"id": "talking_natalia", "label": "Natalia"}],
                },
            ]
        },
        answers={
            "nine": {
                "p1": {"state": "out"},
                "p4": {"state": "touch", "correct": "Julie Auger", "naming": True},
            },
            "talking_natalia": "the Ramirez family",
        },
    )

    body = build_body(brief)

    # The people read by name and their verdict in words.
    assert "Sherpa Yangdi — LEAVE OUT" in body
    assert "Auger Julie A — already in touch" in body
    assert 'calls them "Julie Auger"' in body
    # The free text reads by its label.
    assert "Natalia: the Ramirez family" in body
    # And none of the machine's vocabulary survives.
    assert "p1" not in body
    assert "p4" not in body
    assert "naming" not in body


async def test_telegram_says_how_far_along_and_never_what_they_wrote() -> None:
    """Counts, not content.

    The owner asked for this so nobody has to keep asking "how's it going" —
    not for a feed. So the doorbell carries how much is done and the email
    carries what was said. A phone alert that quoted a past client's name would
    put it on a lock screen, which is a different thing entirely from a
    document you open on purpose.
    """
    from app.models.partner_brief import PartnerBrief
    from app.services.brief_activity import summarise

    brief = PartnerBrief(
        title="Nine names and a listing",
        recipient="Natalia and Robbie",
        payload={
            "blocks": [
                {
                    "kind": "people",
                    "id": "nine",
                    "heading": "The nine",
                    "people": [{"id": f"p{n}", "name": f"Person {n}"} for n in range(1, 10)],
                },
                {
                    "kind": "questions",
                    "fields": [
                        {"id": "talking_natalia", "label": "Natalia"},
                        {"id": "talking_robbie", "label": "Robbie"},
                    ],
                },
                {
                    "kind": "letter",
                    "id": "broker",
                    "fields": [{"id": "broker_note", "label": "Note"}],
                },
            ]
        },
        answers={
            "nine": {
                "p2": {"state": "out"},
                "p5": {"state": "touch"},
                "p4": {"correct": "Julie Auger"},
            },
            "talking_natalia": "the Ramirez family",
            "broker.state": "sent",
        },
    )

    text = summarise(brief)

    assert "The nine: 7 to write to, 1 left out, 1 already in touch" in text
    assert "1 name corrected" in text
    assert "the broker email: sent it" in text
    # Two free-text fields plus the broker note plus the broker choice = 4
    # asked; one field filled plus the choice made = 2 given.
    assert "2 of 4 questions answered" in text

    # And not one word of what they typed.
    assert "Ramirez" not in text
    assert "Julie Auger" not in text
    assert "Person" not in text


async def test_the_doorbell_does_not_ring_on_every_keystroke() -> None:
    from app.services.brief_activity import BRIEF_ACTIVITY_QUIET, should_ping_progress

    assert should_ping_progress(None) is True, "the first save is news"
    assert should_ping_progress(datetime.now(UTC)) is False, "a save seconds later is not"
    stale = datetime.now(UTC) - BRIEF_ACTIVITY_QUIET - timedelta(minutes=1)
    assert should_ping_progress(stale) is True, "picking it up again after a break is"
