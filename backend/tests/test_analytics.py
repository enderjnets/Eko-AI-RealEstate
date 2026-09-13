"""The analytics endpoint, asserted on values rather than on shape.

The version this replaces checked that the response had the right keys and
never that any number was right. That is worth stating because it is exactly
how the old `avg_first_response_seconds` shipped counting internal notes as
replies for months: the test was green the whole time.

Each test seeds what it needs and asserts the number it expects. Two of them
exist for defects that were live in production when this was written:

* **The day is the agency's day.** A lead that arrived at 23:30 in Denver was
  filed under the next day, because the grouping ran in UTC.
* **An internal note is not a reply.** A lead nobody ever answered showed a
  two-minute response time because an advisor typed "no answer" into the thread.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import (
    Conversation,
    ConversationStatus,
    LandingSession,
    Lead,
    LeadIntent,
    LeadStatus,
    Message,
    MessageDirection,
    MessageSender,
)

ORG = 1
MARKER = "+1997000"
TZ_OFFSET = timedelta(hours=6)  # Denver is UTC-6 in September (MDT)


async def _cleanup() -> None:
    """Everything, not just this file's rows.

    These tests assert totals, and a total is not a number you can scope to a
    marker: one lead left behind by another test makes "the 3rd has one lead"
    read as four. The suite recreates this database, so clearing it here costs
    nothing and every test below seeds exactly what it measures.
    """
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads"))
        await db.execute(text("DELETE FROM landing_sessions"))
        # Content too, since `content` began asserting how many rows come back
        # and which video each one names. The publisher's tests seed published
        # pieces and leave them, so without this the count here is whatever ran
        # earlier — which is a green that depends on file order. Publications
        # go with the piece: the foreign key cascades.
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


async def _fresh() -> None:
    await _cleanup()


async def _get(params: str = "") -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/api/v1/analytics{params}")
        assert resp.status_code == 200, resp.text
        return resp.json()


@pytest.mark.asyncio
async def test_the_envelope_carries_every_section() -> None:
    body = await _get()
    for section in (
        "range",
        "traffic",
        "funnel",
        "leads",
        "response",
        "calls",
        "appointments",
        "deals",
        "content",
        "by_agent",
    ):
        assert section in body, section
    assert body["range"]["timezone"], "a report without a timezone is a report about nothing"


@pytest.mark.asyncio
async def test_a_lead_that_arrived_at_half_eleven_at_night_counts_that_day() -> None:
    """The six-hour error that every individual number hides.

    23:30 on the 3rd in Denver is 05:30 UTC on the 4th. Grouped in UTC the lead
    lands on the 4th, so the two busiest hours of every evening are permanently
    filed under the following morning — and nothing looks wrong, because each
    daily count is still a plausible number.
    """
    await _fresh()
    local_evening = datetime(2026, 9, 3, 23, 30, tzinfo=UTC) + TZ_OFFSET  # 05:30Z on the 4th
    async with get_bypass_session_factory()() as db:
        db.add(
            Lead(
                org_id=ORG,
                phone=f"{MARKER}0001",
                intent=LeadIntent.BUY,
                status=LeadStatus.NEW,
                created_at=local_evening,
            )
        )
        await db.commit()
    try:
        body = await _get("?from=2026-09-03&to=2026-09-03")
        assert body["leads"]["total"] == 1, "the 3rd is the day it happened in Denver"

        body = await _get("?from=2026-09-04&to=2026-09-04")
        assert body["leads"]["total"] == 0, "and it must not also appear on the 4th"

        # The range and the grouping are two different things, and only this
        # second assertion sees the grouping: a window computed in Denver but
        # bucketed in UTC still returns the right total for a one-day range —
        # it just files the lead in the wrong column of the chart. Removing the
        # timezone from `Window.day` left the assertions above perfectly green.
        body = await _get("?from=2026-09-01&to=2026-09-07")
        per_day = {d["date"]: d["leads"] for d in body["leads"]["new_by_day"]}
        assert per_day["2026-09-03"] == 1, per_day
        assert per_day["2026-09-04"] == 0, per_day
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_internal_note_is_not_an_answer() -> None:
    """H8, and the reason the old average was meaningless.

    An advisor typing "called, no answer" into the thread is a note to
    themselves. Counted as a reply it produces a response time for a lead that
    was never answered — a number that is not merely wrong, it is the opposite
    of the truth.
    """
    await _fresh()
    started = datetime.now(UTC) - timedelta(hours=2)
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG, phone=f"{MARKER}0002", intent=LeadIntent.BUY, status=LeadStatus.NEW
        )
        db.add(lead)
        await db.flush()
        conv = Conversation(
            org_id=ORG,
            lead_id=lead.id,
            channel="sms",
            status=ConversationStatus.ACTIVE,
            started_at=started,
        )
        db.add(conv)
        await db.flush()
        db.add(
            Message(
                org_id=ORG,
                conversation_id=conv.id,
                direction=MessageDirection.OUTBOUND,
                sender=MessageSender.HUMAN,
                content="called, no answer",
                internal=True,
                created_at=started + timedelta(minutes=2),
            )
        )
        await db.commit()
    try:
        body = await _get()
        assert body["response"]["first_response_seconds"]["median"] is None
        assert body["response"]["unanswered"] == 1, "they are still waiting"
        assert body["response"]["by_kind"] == {}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_real_reply_is_measured_and_named() -> None:
    await _fresh()
    started = datetime.now(UTC) - timedelta(hours=1)
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG, phone=f"{MARKER}0003", intent=LeadIntent.BUY, status=LeadStatus.NEW
        )
        db.add(lead)
        await db.flush()
        conv = Conversation(
            org_id=ORG,
            lead_id=lead.id,
            channel="sms",
            status=ConversationStatus.ACTIVE,
            started_at=started,
        )
        db.add(conv)
        await db.flush()
        db.add_all(
            [
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="Hi, happy to help.",
                    llm_provider="kimi",
                    internal=False,
                    created_at=started + timedelta(seconds=90),
                ),
                # The canned reply that goes out when no model answers. Counted
                # as AI it would hide an outage behind a healthy response time.
                Message(
                    org_id=ORG,
                    conversation_id=conv.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=MessageSender.AGENT,
                    content="We'll be right with you.",
                    llm_provider="fallback",
                    internal=False,
                    created_at=started + timedelta(minutes=5),
                ),
            ]
        )
        await db.commit()
    try:
        body = await _get()
        assert body["response"]["first_response_seconds"]["median"] == 90.0
        assert body["response"]["by_kind"] == {"ai": 1, "fallback": 1}
        assert body["response"]["unanswered"] == 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_funnel_never_widens_as_it_goes_down() -> None:
    """A stage bigger than the one above it is the shape that makes a funnel
    obviously wrong in a chart and quietly wrong in a table."""
    body = await _get()
    counts = [step["count"] for step in body["funnel"]]
    stages = [step["stage"] for step in body["funnel"]]
    assert stages[-1] == "won"
    assert stages[:5] == ["sessions", "engaged", "reached_out", "tapped", "leads"]
    # `tapped` sale de la misma fila que `reached_out` y su condicion es parte
    # de la de aquel, asi que esta CONTENIDO en el: este peldano no puede
    # ensancharse nunca, con los datos que sea. Iguales cuando nadie se limito a navegar.
    assert counts[stages.index("tapped")] <= counts[stages.index("reached_out")]
    # Not a step on purpose: an appointment can be booked by the voice agent
    # without anybody logging a call, so this one sat wider than the step above
    # it. A seeded month showed it immediately; an empty database never would.
    assert "called_back" not in stages
    # Leads can exceed sessions — a phone call is a lead with no visit — so the
    # monotonic claim is only made from `leads` down, where it must hold.
    below = counts[stages.index("leads") :]
    assert below == sorted(below, reverse=True), below


@pytest.mark.asyncio
async def test_the_funnel_counts_people_not_taps_and_keeps_navigation_apart() -> None:
    """El defecto entero, con los datos que lo destaparon.

    Tres grupos DISJUNTOS, que es la forma que traia produccion el 12-sep-2026:
    quien solo pulsa el menu, quien solo toca el telefono, quien solo mete el
    cursor en el formulario. Nadie hace dos cosas.

    Antes esto daba `SUM(cta)+SUM(tel)+COUNT(form)` = 3+1+1 = **5** en un solo
    peldano llamado "tocaron llamar o empezaron el formulario", cuando son
    **3 personas** y solo **2** hicieron algo que se parezca a contactar. Las
    tres pulsaciones del menu eran una persona navegando.
    """
    await _fresh()
    now = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        # Uno que solo navego: TRES clics del menu, una sola persona. Es el que
        # inflaba el numero, y el que la etiqueta llamaba "tapped call".
        db.add(LandingSession(
            org_id=ORG, session_key="funnel-nav-" + "a" * 20,
            first_seen_at=now, last_seen_at=now, source="google", device="desktop",
            max_scroll_pct=100, sections_viewed=["about", "how"],
            cta_clicks=3, tel_clicks=0, event_count=9,
        ))
        # Uno que toco el telefono y NUNCA pulso el menu.
        db.add(LandingSession(
            org_id=ORG, session_key="funnel-tel-" + "b" * 20,
            first_seen_at=now, last_seen_at=now, source="direct", device="phone",
            max_scroll_pct=100, sections_viewed=["about", "how"],
            cta_clicks=0, tel_clicks=1, event_count=4,
        ))
        # Uno que metio el cursor en el formulario y nada mas.
        db.add(LandingSession(
            org_id=ORG, session_key="funnel-form-" + "c" * 19,
            first_seen_at=now, last_seen_at=now, source="facebook", device="phone",
            max_scroll_pct=100, sections_viewed=["about", "how"],
            cta_clicks=0, tel_clicks=0, form_started_at=now, event_count=5,
        ))
        await db.commit()
    try:
        body = await _get()
        steps = {s["stage"]: s["count"] for s in body["funnel"]}

        # PERSONAS. Sumando eventos esto habria dado 5.
        assert steps["reached_out"] == 3, steps
        # Y de esas tres, solo dos hicieron algo mas que navegar.
        assert steps["tapped"] == 2, steps
        # La contencion, con datos disjuntos que es cuando importa: un embudo
        # de dos peldanos independientes se habria ensanchado aqui.
        assert steps["tapped"] <= steps["reached_out"]

        # La tarjeta de trafico SIGUE contando toques, que es su pregunta.
        assert body["traffic"]["cta_clicks"] == 3
        assert body["traffic"]["people_clicked_cta"] == 1, "tres clics, una persona"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_send_that_produced_no_lead_is_visible() -> None:
    """El detector que existia en la base y no leia nadie.

    `form_submitted_at` puesto y `lead_id` nulo es el honeypot que contesta 202,
    el captcha rechazado, la conexion caida: el visitante ve "enviado" y no hay
    lead. El codigo que lo escribe lo describe asi desde que existe y ninguna
    consulta lo preguntaba.
    """
    await _fresh()
    now = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        db.add(LandingSession(
            org_id=ORG, session_key="funnel-lost-" + "d" * 19,
            first_seen_at=now, last_seen_at=now, source="direct", device="phone",
            max_scroll_pct=100, sections_viewed=["about", "consult"],
            form_started_at=now, form_submitted_at=now, lead_id=None,
            form_error_count=2, event_count=7,
        ))
        await db.commit()
    try:
        traffic = (await _get())["traffic"]
        assert traffic["submitted_without_lead"] == 1, traffic
        assert traffic["form_errors"] == 2
        assert traffic["people_with_errors"] == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_visit_is_counted_where_it_was_read() -> None:
    await _fresh()
    now = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        db.add(
            LandingSession(
                org_id=ORG,
                session_key="analytics-" + "a" * 22,
                first_seen_at=now,
                last_seen_at=now,
                source="tiktok",
                device="phone",
                max_scroll_pct=100,
                sections_viewed=["about", "how"],
                tel_clicks=1,
                event_count=6,
            )
        )
        await db.commit()
    try:
        body = await _get()
        traffic = body["traffic"]
        assert traffic["sessions"] >= 1
        assert traffic["engaged"] >= 1, "100% scrolled and two sections read"
        assert traffic["tel_clicks"] >= 1
        assert any(s["name"] == "tiktok" for s in traffic["by_source"])
        assert traffic["sections"]["about"] >= 1
        assert traffic["sections"]["consult"] == 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_guides_section_is_reported_not_only_stored() -> None:
    """`fold_events` stored `guides` from v0.91.0; this checks the panel sees it.

    The report used to iterate its own literal of four names, so a section the
    tracker recorded reached `sections_viewed` and no further — the "How far
    they read" card had no row for it and nothing said so.
    """
    await _fresh()
    now = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        db.add(
            LandingSession(
                org_id=ORG,
                session_key="analytics-" + "g" * 22,
                first_seen_at=now,
                last_seen_at=now,
                source="instagram",
                device="phone",
                max_scroll_pct=80,
                sections_viewed=["markets", "guides"],
                event_count=4,
            )
        )
        await db.commit()
    try:
        sections = (await _get())["traffic"]["sections"]
        assert sections["guides"] >= 1
        assert list(sections) == ["about", "how", "markets", "guides", "consult"]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_every_day_in_the_range_appears_even_when_nothing_happened() -> None:
    """A chart drawn from the rows alone closes up empty days, which turns a
    week with two dead days into a smooth line that never happened.

    Seven columns for seven days. The naive version produced eight, because the
    window's end is an instant in UTC and `.date()` on it lands on the next
    Denver morning."""
    body = await _get("?from=2026-09-01&to=2026-09-07")
    assert [d["date"] for d in body["traffic"]["by_day"]] == [
        f"2026-09-0{n}" for n in range(1, 8)
    ]


@pytest.mark.asyncio
async def test_an_inverted_or_absurd_range_is_refused() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/v1/analytics?from=2026-09-10&to=2026-09-01")).status_code == 422
        assert (await c.get("/api/v1/analytics?from=2020-01-01&to=2026-09-01")).status_code == 422
        # Half a range is a typo, not a default: answering it with 30 days would
        # silently ignore the date the person actually typed.
        assert (await c.get("/api/v1/analytics?from=2026-09-01")).status_code == 422


@pytest.mark.asyncio
async def test_the_amount_closed_is_admin_only() -> None:
    from app.api.v1.auth import current_role

    try:
        for role, visible in (("member", False), ("admin", True)):
            app.dependency_overrides[current_role] = lambda role=role: role
            body = await _get()
            assert (body["deals"]["total_value"] is not None) is visible, role
            # The count is not a secret; only the money is.
            assert "won" in body["deals"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_one_agency_never_reads_anothers_numbers() -> None:
    """H7: there was no isolation test for analytics at all.

    Every count must be **zero** under the other organization, not merely
    "no error". Aggregates are the easiest place to leak a tenant boundary,
    because a wrong number looks exactly like a right one and no row is ever
    displayed with somebody else's name on it.
    """
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )
    from app.services.tenant_context import org_scope

    await _fresh()
    now = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG, phone=f"{MARKER}0009", intent=LeadIntent.BUY, status=LeadStatus.NEW
        )
        db.add(lead)
        db.add(
            LandingSession(
                org_id=ORG,
                session_key="analytics-" + "b" * 22,
                first_seen_at=now,
                last_seen_at=now,
                source="tiktok",
                max_scroll_pct=100,
                event_count=3,
            )
        )
        # `content` grew a join to `content_pieces` to carry the title, which
        # puts a second tenant-owned table inside this boundary. A join reads
        # through the same session, so RLS covers it — but "should" is what an
        # isolation test exists to replace.
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook="isolation check",
        )
        db.add(piece)
        await db.flush()
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=piece.id,
                platform=PublicationPlatform.YOUTUBE,
                status=PublicationStatus.PUBLISHED,
                published_at=now - timedelta(hours=2),
            )
        )
        await db.commit()
        piece_id = piece.id
    try:
        from app.services import analytics as svc

        window = svc.Window(
            start=now - timedelta(days=1), end=now + timedelta(days=1), tz=svc.DEFAULT_TZ
        )
        from app.db.base import get_session_factory

        with org_scope(2):
            async with get_session_factory()() as db:
                assert (await svc.leads(db, window))["total"] == 0
                assert (await svc.traffic(db, window))["sessions"] == 0
                assert (await svc.funnel(db, window, await svc.traffic(db, window)))[0][
                    "count"
                ] == 0
                assert await svc.content(db, window) == []

        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert (await svc.leads(db, window))["total"] == 1
                assert (await svc.traffic(db, window))["sessions"] == 1
                assert len(await svc.content(db, window)) == 1
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM content_pieces WHERE id = :i"), {"i": piece_id}
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_a_range_does_not_reach_back_to_older_publications() -> None:
    """`content` had no range at all: it returned the twenty most recent posts
    whatever was asked, so a seven-day report showed August's videos and
    counted the visits around them."""
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )

    await _fresh()
    old = datetime.now(UTC) - timedelta(days=60)
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook="analytics range check",
        )
        db.add(piece)
        await db.flush()
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=piece.id,
                platform=PublicationPlatform.TIKTOK,
                status=PublicationStatus.PUBLISHED,
                published_at=old,
            )
        )
        await db.commit()
        piece_id = piece.id
    try:
        assert (await _get("?range=7d"))["content"] == []
        assert (await _get("?range=90d"))["content"], "and it is there when asked for"
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM content_pieces WHERE id = :i"), {"i": piece_id}
            )
            await db.commit()
        await _cleanup()


# There is deliberately no "the endpoint is tenant-bound" test here, and the
# reason is worth writing down rather than leaving as an absence.
#
# A first attempt wrapped the HTTP call in `org_scope(2)` and asserted zero. It
# failed, correctly: the context manager sets the org for *this* coroutine, and
# the request resolves its own tenant inside the app, so the assertion was
# measuring the wrong thing entirely. Making it real needs a signed session for
# a user belonging to the second organization — worth building, but it belongs
# with the auth fixtures and not here.
#
# What IS proven above is the part that carries the guarantee: every section
# reads through the RLS-bound session, and under `org_scope(2)` each one returns
# zero. The router adds one query of its own — `_agency_zone`, reading
# `AgentSettings` — and it uses the same session, so it is inside the same
# boundary as everything it precedes.


@pytest.mark.asyncio
async def test_each_row_names_its_video_and_its_own_publication() -> None:
    """A row said `#41 · YouTube` and nothing else.

    The owner reads this card to decide what to make more of, and a piece id is
    not something anybody recognises. The title is the piece's `hook`, which
    needs a join the query did not have; `publication_id` was already being read
    to fetch the view counts and simply never emitted, so the page had to
    address a publication by the pair it happened to know.
    """
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )

    await _fresh()
    now = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook="analytics range check",
        )
        db.add(piece)
        await db.flush()
        watched = ContentPublication(
            org_id=ORG,
            piece_id=piece.id,
            platform=PublicationPlatform.YOUTUBE,
            status=PublicationStatus.PUBLISHED,
            published_at=now - timedelta(days=1),
            external_url="https://youtube.com/shorts/abc",
        )
        unlinked = ContentPublication(
            org_id=ORG,
            piece_id=piece.id,
            platform=PublicationPlatform.TIKTOK,
            status=PublicationStatus.PUBLISHED,
            published_at=now - timedelta(days=2),
        )
        db.add_all([watched, unlinked])
        await db.commit()
        piece_id, watched_id, unlinked_id = piece.id, watched.id, unlinked.id
    try:
        rows = (await _get("?range=7d"))["content"]
        assert len(rows) == 2, rows
        assert {r["hook"] for r in rows} == {"analytics range check"}
        # Two publications, two ids. Emitting `piece_id` here would collapse
        # this to one value, which is the whole point of asking for the set.
        assert {r["publication_id"] for r in rows} == {watched_id, unlinked_id}
        by_platform = {r["platform"]: r for r in rows}
        assert by_platform["youtube"]["external_url"] == "https://youtube.com/shorts/abc"
        assert by_platform["tiktok"]["external_url"] is None
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM content_pieces WHERE id = :i"), {"i": piece_id}
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_the_limit_counts_videos_not_posts() -> None:
    """The card groups by video, so a limit counting posts cuts one in half.

    With three platforms per video, a limit of twenty publications ends the list
    somewhere inside the seventh video — showing YouTube and Instagram for it
    and silently dropping TikTok, which reads as "we never posted it there".
    """
    from app.db.base import get_session_factory
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )
    from app.services import analytics as svc
    from app.services.tenant_context import org_scope

    await _fresh()
    now = datetime.now(UTC)
    made: list[int] = []
    async with get_bypass_session_factory()() as db:
        for label, days in (("older video", 5), ("newer video", 1)):
            piece = ContentPiece(
                org_id=ORG,
                kind=ContentKind.GENERATED,
                language=ContentLanguage.EN,
                status=ContentStatus.PUBLISHED,
                hook=label,
            )
            db.add(piece)
            await db.flush()
            for platform in (PublicationPlatform.YOUTUBE, PublicationPlatform.TIKTOK):
                db.add(
                    ContentPublication(
                        org_id=ORG,
                        piece_id=piece.id,
                        platform=platform,
                        status=PublicationStatus.PUBLISHED,
                        published_at=now - timedelta(days=days),
                    )
                )
            made.append(piece.id)
        await db.commit()
    try:
        window = svc.Window(
            start=now - timedelta(days=10), end=now + timedelta(days=1), tz=svc.DEFAULT_TZ
        )
        with org_scope(ORG):
            async with get_session_factory()() as db:
                rows = await svc.content(db, window, limit=1)
        assert len(rows) == 2, "one video, and it keeps both of its platforms"
        assert {r["piece_id"] for r in rows} == {made[1]}
        assert {r["hook"] for r in rows} == {"newer video"}
    finally:
        async with get_bypass_session_factory()() as db:
            for piece_id in made:
                await db.execute(
                    text("DELETE FROM content_pieces WHERE id = :i"), {"i": piece_id}
                )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_a_video_written_without_a_hook_still_has_a_row() -> None:
    """`hook` is nullable and a clip filmed on a phone need not have one.

    The card falls back to the piece id for a title, which only works if the
    row arrives at all: an inner join or a non-null assumption here would make
    a published video disappear from the report instead of being unnamed.
    """
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )

    await _fresh()
    now = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.RECORDED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook=None,
        )
        db.add(piece)
        await db.flush()
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=piece.id,
                platform=PublicationPlatform.INSTAGRAM,
                status=PublicationStatus.PUBLISHED,
                published_at=now - timedelta(hours=3),
            )
        )
        await db.commit()
        piece_id = piece.id
    try:
        rows = (await _get("?range=7d"))["content"]
        assert len(rows) == 1, rows
        assert rows[0]["hook"] is None
        assert rows[0]["piece_id"] == piece_id
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM content_pieces WHERE id = :i"), {"i": piece_id}
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_a_visit_after_two_posts_of_one_video_is_counted_once() -> None:
    """One figure per video, over the union of its posts' windows.

    The platforms of one video go out half a day apart, so their 48-hour
    windows overlap for most of their length. Counted per post, a visit in the
    overlap sat on both rows — and the owner reading the card and adding the
    rows up got a number of people that never existed. A visit that followed
    only the FIRST post still belongs to the video (the union, not the
    intersection), and a visit between two posts days apart belongs to
    neither (the union, not the span).
    """
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )

    await _fresh()
    now = datetime.now(UTC)

    def piece(hook: str) -> ContentPiece:
        return ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook=hook,
        )

    def post(piece_id: int, platform: PublicationPlatform, hours_ago: int) -> ContentPublication:
        return ContentPublication(
            org_id=ORG,
            piece_id=piece_id,
            platform=platform,
            status=PublicationStatus.PUBLISHED,
            published_at=now - timedelta(hours=hours_ago),
        )

    def visit(key: str, hours_ago: int) -> LandingSession:
        at = now - timedelta(hours=hours_ago)
        return LandingSession(
            org_id=ORG,
            session_key=f"assoc-{key}".ljust(32, "x"),
            first_seen_at=at,
            last_seen_at=at,
            source="direct",
            device="phone",
            max_scroll_pct=10,
            sections_viewed=[],
            tel_clicks=0,
            event_count=1,
        )

    def lead(suffix: str, hours_ago: int) -> Lead:
        return Lead(
            org_id=ORG,
            phone=f"{MARKER}{suffix}",
            intent=LeadIntent.BUY,
            status=LeadStatus.NEW,
            created_at=now - timedelta(hours=hours_ago),
        )

    async with get_bypass_session_factory()() as db:
        video, other, gapped = piece("union of windows"), piece("one post"), piece("days apart")
        db.add_all([video, other, gapped])
        await db.flush()
        db.add_all(
            [
                post(video.id, PublicationPlatform.YOUTUBE, 30),
                post(video.id, PublicationPlatform.TIKTOK, 18),
                post(other.id, PublicationPlatform.INSTAGRAM, 100),
                post(gapped.id, PublicationPlatform.YOUTUBE, 150),
                post(gapped.id, PublicationPlatform.TIKTOK, 20),
                visit("first-only", 29),   # after the first post, before the second
                visit("overlap", 10),      # inside BOTH of the video's windows
                visit("before", 31),       # before either post: nobody had seen it
                visit("other", 60),        # the other video's window, and only its
                visit("gap", 40),          # between two posts days apart: neither's
                lead("0201", 10),
                lead("0202", 60),
            ]
        )
        await db.commit()
        ids = {"video": video.id, "other": other.id, "gapped": gapped.id}
    try:
        rows = (await _get("?range=7d"))["content"]

        def of(name: str, field: str) -> list[int]:
            return [r["association"][field] for r in rows if r["piece_id"] == ids[name]]

        # Two people followed this video: the one after the first post and the
        # one in the overlap. Per post it read 2 on one row and 1 on the other,
        # which adds up to a third person who does not exist.
        assert of("video", "sessions") == [2, 2]
        assert of("video", "leads") == [1, 1]
        assert of("other", "sessions") == [1]
        assert of("other", "leads") == [1]
        # The visit at -40h is not in either 48-hour window. A span from the
        # first post to the last would have claimed it, and four others.
        assert of("gapped", "sessions") == [1, 1], "the -20h post's window holds the -10h visit"
        assert of("gapped", "leads") == [1, 1]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_excluded_sessions_never_enter_traffic_funnel_or_content() -> None:
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )
    from app.services import analytics as svc

    await _fresh()
    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = datetime(2026, 9, 14, tzinfo=UTC)
    publication_at = datetime(2026, 9, 10, 9, tzinfo=UTC)
    unknown_at = datetime(2026, 9, 10, 10, tzinfo=UTC)
    automated_at = datetime(2026, 9, 11, 10, tzinfo=UTC)
    test_at = datetime(2026, 9, 12, 8, tzinfo=UTC)
    window = svc.Window(start=start, end=end, tz="UTC")

    async with get_bypass_session_factory()() as db:
        lead = Lead(
            org_id=ORG,
            phone=f"{MARKER}0301",
            intent=LeadIntent.BUY,
            status=LeadStatus.NEW,
            created_at=unknown_at,
        )
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook="measured traffic",
        )
        db.add_all([lead, piece])
        await db.flush()
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=piece.id,
                platform=PublicationPlatform.INSTAGRAM,
                status=PublicationStatus.PUBLISHED,
                published_at=publication_at,
            )
        )
        db.add_all(
            [
                LandingSession(
                    org_id=ORG,
                    session_key="measured-unknown",
                    first_seen_at=unknown_at,
                    last_seen_at=unknown_at,
                    landing_path="/start",
                    source="instagram",
                    device="phone",
                    in_app="instagram",
                    country="US",
                    region="CO",
                    city="Denver",
                    lang="en",
                    traffic_class="unknown",
                    max_scroll_pct=60,
                    sections_viewed=["about", "how"],
                    cta_clicks=2,
                    tel_clicks=1,
                    form_error_count=3,
                    form_started_at=unknown_at,
                    form_submitted_at=unknown_at,
                    lead_id=lead.id,
                    event_count=8,
                ),
                LandingSession(
                    org_id=ORG,
                    session_key="excluded-automated",
                    first_seen_at=automated_at,
                    last_seen_at=automated_at,
                    source="youtube",
                    device="desktop",
                    in_app="youtube",
                    country="CA",
                    region="ON",
                    city="Toronto",
                    lang="fr",
                    traffic_class="automated",
                    max_scroll_pct=100,
                    sections_viewed=["markets", "guides", "consult"],
                    cta_clicks=20,
                    tel_clicks=10,
                    form_error_count=9,
                    form_started_at=automated_at,
                    form_submitted_at=automated_at,
                    event_count=99,
                ),
                LandingSession(
                    org_id=ORG,
                    session_key="excluded-test",
                    first_seen_at=test_at,
                    last_seen_at=test_at,
                    source="eko_qa",
                    device="tablet",
                    in_app="tiktok",
                    country="MX",
                    region="CMX",
                    city="Mexico City",
                    lang="es",
                    traffic_class="test",
                    max_scroll_pct=90,
                    sections_viewed=["guides", "consult"],
                    cta_clicks=30,
                    tel_clicks=15,
                    form_error_count=7,
                    form_started_at=test_at,
                    form_submitted_at=test_at,
                    event_count=120,
                ),
            ]
        )
        await db.commit()

    try:
        async with get_bypass_session_factory()() as db:
            traffic = await svc.traffic(db, window)
            funnel = await svc.funnel(db, window, traffic)
            content = await svc.content(db, window)

        assert traffic["sessions"] == 1
        assert traffic["engaged"] == 1
        assert traffic["avg_scroll_pct"] == 60.0
        assert traffic["cta_clicks"] == 2
        assert traffic["tel_clicks"] == 1
        assert traffic["form_starts"] == 1
        assert traffic["form_submits"] == 1
        assert traffic["people_clicked_cta"] == 1
        assert traffic["people_tapped"] == 1
        assert traffic["people_reached_out"] == 1
        assert traffic["form_errors"] == 3
        assert traffic["people_with_errors"] == 1
        assert traffic["submitted_without_lead"] == 0
        assert traffic["excluded_sessions"] == {
            "total": 2,
            "automated": 1,
            "test": 1,
        }
        assert {row["name"] for row in traffic["by_source"]} == {"instagram"}
        assert {row["name"] for row in traffic["by_device"]} == {"phone"}
        assert {row["name"] for row in traffic["by_in_app"]} == {"instagram"}
        assert {row["name"] for row in traffic["by_country"]} == {"US"}
        assert {row["name"] for row in traffic["by_region"]} == {"CO"}
        assert {row["name"] for row in traffic["by_city"]} == {"Denver"}
        assert {row["name"] for row in traffic["by_lang"]} == {"en"}
        assert {row["date"]: row["sessions"] for row in traffic["by_day"]} == {
            "2026-09-09": 0,
            "2026-09-10": 1,
            "2026-09-11": 0,
            "2026-09-12": 0,
            "2026-09-13": 0,
        }
        assert traffic["sections"] == {
            "about": 1,
            "how": 1,
            "markets": 0,
            "guides": 0,
            "consult": 0,
        }
        funnel_counts = {row["stage"]: row["count"] for row in funnel}
        assert {name: funnel_counts[name] for name in (
            "sessions",
            "engaged",
            "reached_out",
            "tapped",
        )} == {
            "sessions": 1,
            "engaged": 1,
            "reached_out": 1,
            "tapped": 1,
        }
        assert len(content) == 1
        assert content[0]["association"]["sessions"] == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_start_engaged_requires_a_real_choice_or_existing_scroll_signal() -> None:
    from app.services import analytics as svc

    await _fresh()
    start = datetime(2026, 9, 10, tzinfo=UTC)
    end = datetime(2026, 9, 11, tzinfo=UTC)
    window = svc.Window(start=start, end=end, tz="UTC")

    def start_session(label: str, **signals) -> LandingSession:
        at = start + timedelta(hours=len(label))
        return LandingSession(
            org_id=ORG,
            session_key=f"start-{label}",
            first_seen_at=at,
            last_seen_at=at,
            landing_path="/start",
            source="direct",
            traffic_class="unknown",
            device="phone",
            max_scroll_pct=signals.get("max_scroll_pct", 0),
            sections_viewed=[],
            cta_clicks=signals.get("cta_clicks", 0),
            tel_clicks=signals.get("tel_clicks", 0),
            form_started_at=signals.get("form_started_at"),
            event_count=1,
        )

    async with get_bypass_session_factory()() as db:
        db.add_all(
            [
                start_session("untouched"),
                start_session("cta", cta_clicks=1),
                start_session("tel", tel_clicks=1),
                start_session("form", form_started_at=start + timedelta(hours=1)),
                start_session("scroll", max_scroll_pct=50),
            ]
        )
        await db.commit()

    try:
        async with get_bypass_session_factory()() as db:
            traffic = await svc.traffic(db, window)
        assert traffic["sessions"] == 5
        assert traffic["engaged"] == 4
        assert traffic["excluded_sessions"] == {
            "total": 0,
            "automated": 0,
            "test": 0,
        }
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_exact_attribution_counts_people_by_piece_and_platform() -> None:
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentMetric,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
        Visit,
        VisitStatus,
    )
    from app.services import analytics as svc

    await _fresh()
    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = datetime(2026, 9, 14, tzinfo=UTC)
    window = svc.Window(start=start, end=end, tz="UTC")

    async with get_bypass_session_factory()() as db:
        piece_a = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook="instagram piece",
        )
        piece_b = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.ES,
            status=ContentStatus.PUBLISHED,
            hook="tiktok piece",
        )
        db.add_all([piece_a, piece_b])
        await db.flush()
        publication_a = ContentPublication(
            org_id=ORG,
            piece_id=piece_a.id,
            platform=PublicationPlatform.INSTAGRAM,
            status=PublicationStatus.PUBLISHED,
            published_at=start + timedelta(hours=1),
        )
        publication_b = ContentPublication(
            org_id=ORG,
            piece_id=piece_b.id,
            platform=PublicationPlatform.TIKTOK,
            status=PublicationStatus.PUBLISHED,
            published_at=start + timedelta(hours=2),
        )
        db.add_all([publication_a, publication_b])
        await db.flush()

        lead_a = Lead(
            org_id=ORG,
            phone=f"{MARKER}0401",
            intent=LeadIntent.BUY,
            status=LeadStatus.NEW,
            created_at=start + timedelta(hours=8),
            meta={
                "attribution": {
                    "utm_content": f"piece-{piece_a.id}",
                    "utm_source": "instagram",
                }
            },
        )
        lead_a_second = Lead(
            org_id=ORG,
            phone=f"{MARKER}0402",
            intent=LeadIntent.VALUATION,
            status=LeadStatus.NEW,
            created_at=start + timedelta(hours=9),
            meta={
                "attribution": {
                    "utm_content": f"piece-{piece_a.id}",
                    "utm_source": "instagram",
                }
            },
        )
        lead_b = Lead(
            org_id=ORG,
            phone=f"{MARKER}0403",
            intent=LeadIntent.RENT,
            status=LeadStatus.NEW,
            created_at=start + timedelta(hours=10),
            meta={
                "attribution": {
                    "utm_content": f"piece-{piece_b.id}",
                    "utm_source": "tiktok",
                }
            },
        )
        wrong_source_lead = Lead(
            org_id=ORG,
            phone=f"{MARKER}0404",
            intent=LeadIntent.BUY,
            status=LeadStatus.NEW,
            created_at=start + timedelta(hours=11),
            meta={
                "attribution": {
                    "utm_content": f"piece-{piece_a.id}",
                    "utm_source": "tiktok",
                }
            },
        )
        malformed_lead = Lead(
            org_id=ORG,
            phone=f"{MARKER}0405",
            intent=LeadIntent.OTHER,
            status=LeadStatus.NEW,
            created_at=start + timedelta(hours=12),
            meta={"attribution": ["not", "a", "mapping"]},
        )
        malformed_values_lead = Lead(
            org_id=ORG,
            phone=f"{MARKER}0406",
            intent=LeadIntent.OTHER,
            status=LeadStatus.NEW,
            created_at=start + timedelta(hours=13),
            meta={
                "attribution": {
                    "utm_content": [f"piece-{piece_a.id}"],
                    "utm_source": {"platform": "instagram"},
                }
            },
        )
        db.add_all(
            [
                lead_a,
                lead_a_second,
                lead_b,
                wrong_source_lead,
                malformed_lead,
                malformed_values_lead,
            ]
        )
        await db.flush()

        def tagged_session(
            label: str,
            *,
            piece_id: int | None,
            source: str,
            hour: int,
            traffic_class: str = "unknown",
            lead_id: int | None = None,
            cta_clicks: int = 0,
            tel_clicks: int = 0,
            form_started: bool = False,
            form_submitted: bool = False,
            scroll: int = 0,
        ) -> LandingSession:
            at = start + timedelta(hours=hour)
            return LandingSession(
                org_id=ORG,
                session_key=f"exact-{label}",
                first_seen_at=at,
                last_seen_at=at,
                landing_path="/start",
                utm_content=f"piece-{piece_id}" if piece_id is not None else None,
                source=source,
                traffic_class=traffic_class,
                device="phone",
                max_scroll_pct=scroll,
                sections_viewed=[],
                cta_clicks=cta_clicks,
                tel_clicks=tel_clicks,
                form_started_at=at if form_started else None,
                form_submitted_at=at if form_submitted else None,
                lead_id=lead_id,
                event_count=1,
            )

        db.add_all(
            [
                tagged_session(
                    "a-cta", piece_id=piece_a.id, source="instagram", hour=4,
                    cta_clicks=7,
                ),
                tagged_session(
                    "a-tel", piece_id=piece_a.id, source="instagram", hour=5,
                    tel_clicks=3,
                ),
                tagged_session(
                    "a-form", piece_id=piece_a.id, source="instagram", hour=6,
                    form_started=True, form_submitted=True,
                ),
                tagged_session(
                    "a-scroll", piece_id=piece_a.id, source="instagram", hour=7,
                    scroll=50,
                ),
                tagged_session(
                    "a-view", piece_id=piece_a.id, source="instagram", hour=8,
                ),
                tagged_session(
                    "b-view", piece_id=piece_b.id, source="tiktok", hour=9,
                ),
                tagged_session(
                    "returning-a-on-b", piece_id=piece_b.id, source="tiktok", hour=10,
                    lead_id=lead_a.id, cta_clicks=2,
                ),
                tagged_session(
                    "wrong-source-a", piece_id=piece_a.id, source="tiktok", hour=11,
                    cta_clicks=1, tel_clicks=1, form_started=True, form_submitted=True,
                ),
                tagged_session(
                    "wrong-source-b", piece_id=piece_b.id, source="instagram", hour=12,
                    cta_clicks=1,
                ),
                tagged_session(
                    "wrong-case-a", piece_id=piece_a.id, source="Instagram", hour=13,
                    cta_clicks=1,
                ),
                tagged_session(
                    "untagged", piece_id=None, source="instagram", hour=14,
                    cta_clicks=1,
                ),
                tagged_session(
                    "automated", piece_id=piece_a.id, source="instagram", hour=15,
                    traffic_class="automated", cta_clicks=1,
                ),
                tagged_session(
                    "qa", piece_id=piece_b.id, source="tiktok", hour=16,
                    traffic_class="test", cta_clicks=1,
                ),
            ]
        )
        db.add_all(
            [
                Visit(
                    org_id=ORG,
                    lead_id=lead_a.id,
                    external_booking_id="exact-a-scheduled",
                    status=VisitStatus.SCHEDULED,
                    scheduled_at=start + timedelta(days=2),
                ),
                Visit(
                    org_id=ORG,
                    lead_id=lead_a.id,
                    external_booking_id="exact-a-completed",
                    status=VisitStatus.COMPLETED,
                    scheduled_at=start + timedelta(days=3),
                ),
                Visit(
                    org_id=ORG,
                    lead_id=lead_a.id,
                    external_booking_id="exact-a-cancelled",
                    status=VisitStatus.CANCELLED,
                    scheduled_at=start + timedelta(days=4),
                ),
                Visit(
                    org_id=ORG,
                    lead_id=lead_b.id,
                    external_booking_id="exact-b-completed",
                    status=VisitStatus.COMPLETED,
                    scheduled_at=start + timedelta(days=2),
                ),
            ]
        )
        db.add_all(
            [
                ContentMetric(
                    org_id=ORG,
                    publication_id=publication_a.id,
                    captured_on=(start + timedelta(days=1)).date(),
                    views=40,
                    likes=3,
                    comments=2,
                    source="manual",
                ),
                ContentMetric(
                    org_id=ORG,
                    publication_id=publication_a.id,
                    captured_on=(start + timedelta(days=2)).date(),
                    views=100,
                    likes=0,
                    comments=None,
                    source="manual",
                ),
            ]
        )
        await db.commit()
        ids = {"a": piece_a.id, "b": piece_b.id}

    try:
        async with get_bypass_session_factory()() as db:
            rows = await svc.content(db, window)
        by_piece = {row["piece_id"]: row for row in rows}
        row_a = by_piece[ids["a"]]
        row_b = by_piece[ids["b"]]
        attribution_fields = {
            "sessions",
            "engaged",
            "cta_clickers",
            "contact_intents",
            "form_starts",
            "form_submits",
            "leads",
            "appointments_set",
            "appointments_held",
        }

        assert set(row_a["attribution"]) == attribution_fields
        assert row_a["attribution"] == {
            "sessions": 5,
            "engaged": 4,
            "cta_clickers": 1,
            "contact_intents": 2,
            "form_starts": 1,
            "form_submits": 1,
            "leads": 2,
            "appointments_set": 3,
            "appointments_held": 1,
        }
        assert row_b["attribution"] == {
            "sessions": 2,
            "engaged": 1,
            "cta_clickers": 1,
            "contact_intents": 0,
            "form_starts": 0,
            "form_submits": 0,
            "leads": 1,
            "appointments_set": 1,
            "appointments_held": 1,
        }
        assert row_a["latest_metrics"] == {
            "views": 100,
            "likes": 0,
            "comments": None,
            "captured_on": "2026-09-11",
            "source": "manual",
        }
        assert row_b["latest_metrics"] is None
        assert row_a["views"] == {
            "count": 100,
            "captured_on": "2026-09-11",
            "source": "manual",
        }
        assert row_b["views"] is None
        assert row_a["leads_tagged"] == 3
        assert row_b["leads_tagged"] == 1
        assert row_a["association"]["window_hours"] == 48
        assert row_b["association"]["window_hours"] == 48
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_first_touch_lead_attribution_ignores_a_later_piece_session() -> None:
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )
    from app.services import analytics as svc

    await _fresh()
    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = datetime(2026, 9, 12, tzinfo=UTC)
    window = svc.Window(start=start, end=end, tz="UTC")
    async with get_bypass_session_factory()() as db:
        first = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook="first touch",
        )
        later = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook="later visit",
        )
        db.add_all([first, later])
        await db.flush()
        db.add_all(
            [
                ContentPublication(
                    org_id=ORG,
                    piece_id=first.id,
                    platform=PublicationPlatform.INSTAGRAM,
                    status=PublicationStatus.PUBLISHED,
                    published_at=start,
                ),
                ContentPublication(
                    org_id=ORG,
                    piece_id=later.id,
                    platform=PublicationPlatform.TIKTOK,
                    status=PublicationStatus.PUBLISHED,
                    published_at=start + timedelta(hours=1),
                ),
            ]
        )
        lead = Lead(
            org_id=ORG,
            phone=f"{MARKER}0410",
            intent=LeadIntent.BUY,
            status=LeadStatus.NEW,
            created_at=start + timedelta(hours=2),
            meta={
                "attribution": {
                    "utm_content": f"piece-{first.id}",
                    "utm_source": "instagram",
                }
            },
        )
        db.add(lead)
        await db.flush()
        db.add(
            LandingSession(
                org_id=ORG,
                session_key="first-touch-return",
                first_seen_at=start + timedelta(hours=3),
                last_seen_at=start + timedelta(hours=3),
                utm_content=f"piece-{later.id}",
                source="tiktok",
                traffic_class="unknown",
                device="phone",
                max_scroll_pct=0,
                sections_viewed=[],
                lead_id=lead.id,
                event_count=1,
            )
        )
        await db.commit()
        ids = {"first": first.id, "later": later.id}

    try:
        async with get_bypass_session_factory()() as db:
            rows = await svc.content(db, window)
        by_piece = {row["piece_id"]: row for row in rows}
        assert by_piece[ids["first"]]["attribution"]["leads"] == 1
        assert by_piece[ids["later"]]["attribution"]["sessions"] == 1
        assert by_piece[ids["later"]]["attribution"]["leads"] == 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_exact_attribution_query_count_is_constant_for_one_or_two_pieces() -> None:
    from sqlalchemy import event

    from app.db.base import get_bypass_engine
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )
    from app.services import analytics as svc

    await _fresh()
    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = datetime(2026, 9, 12, tzinfo=UTC)
    window = svc.Window(start=start, end=end, tz="UTC")

    async def add_piece(label: str, platform: PublicationPlatform, hour: int) -> None:
        async with get_bypass_session_factory()() as db:
            piece = ContentPiece(
                org_id=ORG,
                kind=ContentKind.GENERATED,
                language=ContentLanguage.EN,
                status=ContentStatus.PUBLISHED,
                hook=label,
            )
            db.add(piece)
            await db.flush()
            db.add(
                ContentPublication(
                    org_id=ORG,
                    piece_id=piece.id,
                    platform=platform,
                    status=PublicationStatus.PUBLISHED,
                    published_at=start + timedelta(hours=hour),
                )
            )
            await db.commit()

    await add_piece("one", PublicationPlatform.INSTAGRAM, 1)
    counter = {"selects": 0}

    def count_selects(_conn, _cursor, statement, _parameters, _context, _many) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            counter["selects"] += 1

    sync_engine = get_bypass_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", count_selects)
    try:
        async with get_bypass_session_factory()() as db:
            await svc.content(db, window)
        one_piece_queries = counter["selects"]

        await add_piece("two", PublicationPlatform.TIKTOK, 2)
        counter["selects"] = 0
        async with get_bypass_session_factory()() as db:
            await svc.content(db, window)
        two_piece_queries = counter["selects"]
    finally:
        event.remove(sync_engine, "before_cursor_execute", count_selects)
        await _cleanup()

    assert two_piece_queries == one_piece_queries


@pytest.mark.asyncio
async def test_exact_lead_attribution_normalizes_the_first_touch_source() -> None:
    from app.models import (
        ContentKind,
        ContentLanguage,
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
        Visit,
        VisitStatus,
    )
    from app.services import analytics as svc

    await _fresh()
    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = datetime(2026, 9, 12, tzinfo=UTC)
    window = svc.Window(start=start, end=end, tz="UTC")

    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook="aliased first touch",
        )
        db.add(piece)
        await db.flush()
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=piece.id,
                platform=PublicationPlatform.INSTAGRAM,
                status=PublicationStatus.PUBLISHED,
                published_at=start + timedelta(hours=1),
            )
        )
        lead = Lead(
            org_id=ORG,
            phone=f"{MARKER}0490",
            intent=LeadIntent.BUY,
            status=LeadStatus.NEW,
            created_at=start + timedelta(hours=2),
            meta={
                "attribution": {
                    "utm_content": f"piece-{piece.id}",
                    "utm_source": "IG",
                }
            },
        )
        db.add(lead)
        await db.flush()
        db.add(
            Visit(
                org_id=ORG,
                lead_id=lead.id,
                external_booking_id="exact-aliased-source",
                status=VisitStatus.COMPLETED,
                scheduled_at=start + timedelta(days=2),
            )
        )
        await db.commit()
        piece_id = piece.id

    try:
        async with get_bypass_session_factory()() as db:
            rows = await svc.content(db, window)
        row = next(item for item in rows if item["piece_id"] == piece_id)
        assert row["attribution"]["leads"] == 1
        assert row["attribution"]["appointments_set"] == 1
        assert row["attribution"]["appointments_held"] == 1
    finally:
        await _cleanup()
