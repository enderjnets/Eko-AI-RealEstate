"""Colorado 6.10.A.4: every advertisement names the brokerage firm.

For three weeks the system behaved as though it did. There was a setting, a
gate that read the setting, an end card the renderer burned, and a prompt that
asked nicely — and the result, measured on 17-sep-2026, was that of the
twenty-four pieces then alive, four had it in no caption and three of those
named the brokerage nowhere at all. The fourth still carries it burned into
its video, from before the engine changed.

Each part was doing something real:

* the gate checked that the SETTING was filled in, which is not the same fact
  as the advertisement carrying it;
* the end card was burned by our own renderer, and since 10-sep the videos are
  built by an external engine that is never sent the line;
* the prompt asked the model to sign off, and the model did it on some pieces
  and not others, which is worse than never doing it because it looked handled.

The fix is small and the tests here are about the joins between those parts,
not about any one of them. A caption that names the firm; a gate that reads the
caption; and the three spellings this one firm is written in, all accepted.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    AgentSettings,
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentRejection,
    ContentStatus,
)
from app.services.content_studio import (
    NotIdentified,
    NotPublishable,
    caption_carries_brokerage,
    ensure_publishable,
)
from app.services.content_writer import DraftPayload, _with_cta
from app.services.tenant_context import org_scope

ORG = 1

#: What this installation has on record. The Commission's register spells the
#: same firm "Voelkers"; captions in production have carried both.
LINE = "Engel & Völkers"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — the publish gate needs live Postgres")
    return url


@pytest.fixture(autouse=True)
async def _the_line_on_record_is_put_back(request: pytest.FixtureRequest):
    """Two tests here empty the brokerage line, and it is shared state.

    Without this, whichever of them ran last left the settings row with no
    line, and every OTHER test file that publishes a piece failed at the gate.
    That is what happened on the first full run: twenty failures in files this
    change does not touch, all of them caused by this fixture not existing.
    """
    yield
    if "database_url" not in request.fixturenames:
        return
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
        ).scalar_one_or_none()
        if row is None:
            db.add(AgentSettings(org_id=ORG, agency_name="Denver Home Story",
                                 brokerage_line=LINE))
            await db.commit()
        elif (row.brokerage_line or "").strip() != LINE:
            row.brokerage_line = LINE
            await db.commit()


@pytest.fixture(autouse=True)
def _the_rail_is_ours_and_it_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "CONTENT_ORG_ID", ORG, raising=False)
    monkeypatch.setattr(settings, "CONTENT_STUDIO_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings, "CONTENT_CTA_URL", "https://www.denverhomestory.com", raising=False
    )


def _draft(caption: str = "A caption about pricing.", **over) -> DraftPayload:
    body = {
        "hook": "Pricing high can cost you",
        "script": "A high list price turns quiet days into public information.",
        "caption": caption,
        "scenes": [
            {"visual_prompt": "A quiet Denver street", "on_screen_text": "Denver"},
        ],
    }
    body.update(over)
    return DraftPayload(**body)


# --------------------------------------------------------------------------
# The predicate: one firm, three spellings, all of them an identification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "caption",
    [
        "Natalia & Robbie · Real estate advisors, Engel & Völkers Aspen",
        "Natalia & Robbie · Real estate advisors, Engel & Voelkers Aspen - Snowmass",
        "Natalia & Robbie · Real estate advisors, Engel & Volkers Denver",
        "engel  &\n  völkers",
        # Written out. The model composes the caption freely, and without this
        # the gate would refuse a caption that names the firm — and `_with_cta`
        # would add a SECOND identification underneath it.
        "Natalia & Robbie · Real estate advisors, Engel and Völkers Aspen",
    ],
)
def test_the_three_spellings_of_one_firm_all_count_as_naming_it(caption: str) -> None:
    """The register says "Voelkers", the setting says "Völkers", hands write both.

    Stripping the diaeresis alone does not do it: that turns "Völkers" into
    "Volkers" and leaves "Voelkers" alone, so the REGISTERED spelling — the one
    6.10.A.2 actually asks for — would have been refused by the gate meant to
    enforce it. Found by this test before it shipped.
    """
    assert caption_carries_brokerage(caption, LINE) is True


@pytest.mark.parametrize(
    "caption",
    [
        "A caption that names nobody.",
        "Engel only, without the rest of the firm.",
        "",
        None,
    ],
)
def test_a_caption_that_does_not_name_the_firm_is_not_an_identification(
    caption: str | None,
) -> None:
    assert caption_carries_brokerage(caption, LINE) is False


def test_no_line_on_record_is_never_an_identification() -> None:
    """Answering True here would say "identified" about a piece naming nobody.

    The caller refuses the empty setting a line earlier, so this is defence in
    depth rather than the live path — but a predicate whose empty case means
    "yes" is one refactor away from being the live path.
    """
    assert caption_carries_brokerage("Engel & Völkers Aspen", "") is False
    assert caption_carries_brokerage("anything", "   ") is False


# --------------------------------------------------------------------------
# The writer: the line is put in by code, not asked for in a prompt
# --------------------------------------------------------------------------


def test_the_caption_names_the_brokerage_even_when_the_model_forgot() -> None:
    out = _with_cta(_draft(), ContentLanguage.EN, 0, None, LINE)
    assert out is not None
    assert caption_carries_brokerage(out.caption, LINE)


def test_the_model_naming_it_already_is_not_named_twice() -> None:
    """Piece 68 wrote its own sign-off and it was a good one. Ours would double it."""
    theirs = (
        "Start here: somewhere.\n\n"
        "Denver Home Story · Natalia & Robbie · Real estate advisors, "
        "Engel & Völkers Aspen"
    )
    out = _with_cta(_draft(theirs), ContentLanguage.EN, 0, None, LINE)
    assert out is not None
    assert out.caption.lower().count("engel") == 1


def test_a_longer_registered_spelling_is_not_overruled_by_a_narrower_setting() -> None:
    """A person who writes the full registered name must not get ours appended.

    The setting is the shortest acceptable form, not the only one; appending
    "Engel & Völkers" under a caption that already says "Engel & Voelkers Aspen
    - Snowmass" would publish the firm's name twice, in two spellings.
    """
    theirs = "Advisors, Engel & Voelkers Aspen - Snowmass"
    out = _with_cta(_draft(theirs), ContentLanguage.EN, 0, None, LINE)
    assert out is not None
    assert out.caption.lower().count("engel") == 1


def test_with_no_line_on_record_nothing_is_invented() -> None:
    out = _with_cta(_draft(), ContentLanguage.EN, 0, None, "")
    assert out is not None
    assert "engel" not in out.caption.lower()


def test_the_identification_sits_above_the_hashtags_and_the_voice_notice() -> None:
    """Conspicuous is what the rule asks, and a caption gets cut off.

    Instagram and TikTok hide everything after the first couple of lines behind
    a "more" link. An identification pushed to the bottom, under the hashtags,
    is present in the text and absent from the advertisement as most people see
    it — so position is part of compliance, not styling.
    """
    out = _with_cta(_draft(), ContentLanguage.EN, 0, None, LINE)
    assert out is not None
    where_firm = out.caption.lower().index("engel")
    where_notice = out.caption.index("Narrated with a synthetic voice.")
    assert where_firm < where_notice
    # And below the link, where the model put it on the pieces that had it.
    assert where_firm > out.caption.index("denverhomestory.com")


def test_the_filter_sees_the_caption_that_will_be_published() -> None:
    """The same reason the call to action is appended here and not later.

    `_all_violations` runs on what `_with_cta` returns. A line appended after
    it would be text no Fair Housing filter ever read — the exact defect this
    project fixed in v0.56.0.
    """
    from app.services.content_writer import _all_violations

    out = _with_cta(_draft(), ContentLanguage.EN, 0, None, LINE)
    assert out is not None
    assert caption_carries_brokerage(out.caption, LINE)
    assert _all_violations(out, ContentLanguage.EN) == []


# --------------------------------------------------------------------------
# The gate: it reads the advertisement, not the settings row
# --------------------------------------------------------------------------


async def _a_piece(db, caption: str, status: ContentStatus) -> int:
    piece = ContentPiece(
        org_id=ORG,
        kind=ContentKind.GENERATED,
        status=status,
        language=ContentLanguage.EN,
        hook="Pricing high can cost you",
        script="A high list price turns quiet days into public information.",
        caption=caption,
        media_path="somewhere.mp4",
    )
    db.add(piece)
    await db.commit()
    return piece.id


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM render_jobs"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


async def _with_a_line_on_record(db) -> None:
    row = (
        await db.execute(select(AgentSettings).where(AgentSettings.org_id == ORG))
    ).scalar_one_or_none()
    if row is None:
        db.add(AgentSettings(org_id=ORG, agency_name="Denver Home Story",
                             brokerage_line=LINE))
    else:
        row.brokerage_line = LINE
    await db.commit()


@pytest.mark.anyio
async def test_a_piece_that_names_nobody_is_refused_even_with_a_line_on_record(
    database_url: str,
) -> None:
    """The defect, in one test.

    Before this, the gate asked "does this organisation have a brokerage line?"
    and the answer was yes for every piece that went out, including the ones
    that named nobody. The setting is filled in here too — that is the point.
    """
    await _cleanup()
    try:
        with org_scope(ORG):
            async with get_bypass_session_factory()() as db:
                await _with_a_line_on_record(db)
                piece_id = await _a_piece(
                    db, "A caption that names nobody.", ContentStatus.APPROVED
                )
                with pytest.raises(NotPublishable) as caught:
                    await ensure_publishable(db, piece_id)
                assert "brokerage" in str(caught.value)
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_a_piece_that_names_the_firm_publishes(database_url: str) -> None:
    await _cleanup()
    try:
        with org_scope(ORG):
            async with get_bypass_session_factory()() as db:
                await _with_a_line_on_record(db)
                piece_id = await _a_piece(
                    db,
                    "Start here.\n\nAdvisors, Engel & Voelkers Aspen - Snowmass",
                    ContentStatus.APPROVED,
                )
                piece = await ensure_publishable(db, piece_id)
                assert piece.id == piece_id
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_an_empty_setting_is_still_refused_first(database_url: str) -> None:
    """Both refusals matter and they say different things.

    An organisation with no line on record is a configuration problem a person
    fixes in Settings; a piece that does not carry the line is a problem with
    that piece. Collapsing them into one message sends somebody to the wrong
    screen.
    """
    await _cleanup()
    try:
        with org_scope(ORG):
            async with get_bypass_session_factory()() as db:
                row = (
                    await db.execute(
                        select(AgentSettings).where(AgentSettings.org_id == ORG)
                    )
                ).scalar_one_or_none()
                if row is None:
                    db.add(AgentSettings(org_id=ORG, agency_name="Denver Home Story",
                                         brokerage_line=""))
                else:
                    row.brokerage_line = ""
                await db.commit()
                piece_id = await _a_piece(
                    db, "Advisors, Engel & Völkers Aspen", ContentStatus.APPROVED
                )
                with pytest.raises(NotPublishable) as caught:
                    await ensure_publishable(db, piece_id)
                assert "no brokerage line on record" in str(caught.value)
    finally:
        await _cleanup()


# --------------------------------------------------------------------------
# End to end: a draft written today carries it
# --------------------------------------------------------------------------


class _Reply:
    def __init__(self, payload: dict) -> None:
        self.text = json.dumps(payload)


@pytest.mark.anyio
async def test_a_draft_written_today_names_the_brokerage(database_url: str) -> None:
    """`_with_cta` being right is worth nothing if the writer does not call it."""
    await _cleanup()
    try:
        async with get_bypass_session_factory()() as db:
            await _with_a_line_on_record(db)
        from app.services.content_writer import generate_draft

        body = {
            "hook": "Pricing high can cost you",
            "script": "A high list price turns quiet days into public information.",
            "caption": "The risk is not ambition; it is timing.",
            "scenes": [
                {"visual_prompt": "A quiet Denver street", "on_screen_text": "Denver"},
            ],
        }
        # The APP session, not a bypass one: `before_flush` stamps `org_id`
        # from the acting organisation and a bypass session has none, so the
        # insert goes in with a null and Postgres refuses it. The first run of
        # this test died exactly there.
        with patch(
            "app.services.content_writer.generate_reply",
            new=AsyncMock(return_value=_Reply(body)),
        ):
            with org_scope(ORG):
                async with get_session_factory()() as db:
                    piece = await generate_draft(db)
        assert piece is not None
        assert caption_carries_brokerage(piece.caption, LINE)
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_no_line_on_record_buys_no_model_call(database_url: str) -> None:
    """Writing a draft that cannot be published is spending money for nothing.

    The gate would refuse it at the far end anyway; refusing here means the
    reason is in the log before the bill, and the console does not fill with
    drafts that will never go out.
    """
    await _cleanup()
    try:
        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    select(AgentSettings).where(AgentSettings.org_id == ORG)
                )
            ).scalar_one_or_none()
            if row is None:
                db.add(AgentSettings(org_id=ORG, agency_name="Denver Home Story",
                                     brokerage_line=""))
            else:
                row.brokerage_line = ""
            await db.commit()
        from app.services.content_writer import generate_draft

        asked = AsyncMock()
        with patch("app.services.content_writer.generate_reply", new=asked):
            with org_scope(ORG):
                async with get_session_factory()() as db:
                    piece = await generate_draft(db)
        assert piece is None
        assert asked.await_count == 0
    finally:
        await _cleanup()

@pytest.mark.anyio
async def test_the_correction_path_hands_the_line_down_too(database_url: str) -> None:
    """A corrected draft that loses the line would be refused at the gate.

    And it would be refused after the model call was billed, which is the
    worst order to discover it in. The rewrite is a full re-write of the
    caption, so the line has to travel with it exactly as it does on a first
    draft — this asserts the wiring, because the two call sites are easy to
    change independently and only one of them is exercised every day.
    """
    from app.services import content_corrections

    async with get_bypass_session_factory()() as db:
        await _with_a_line_on_record(db)

    seen: dict[str, object] = {}

    async def _spy(*args, **kw):
        seen.update(kw)
        return None

    # Patched on the WRITER, not on the sweep: `_rewrite` imports it inside
    # the function, so the name is looked up in `content_writer` at call time
    # and a patch on the sweep's namespace finds nothing to replace.
    with patch("app.services.content_writer._ask_correction", new=_spy):
        with org_scope(ORG):
            async with get_session_factory()() as db:
                piece = ContentPiece(
                    org_id=ORG,
                    kind=ContentKind.GENERATED,
                    status=ContentStatus.REJECTED,
                    language=ContentLanguage.EN,
                    hook="Pricing high can cost you",
                    script="A high list price turns quiet days into public information.",
                    caption="A caption.",
                    scenes={
                        "narration": "A high list price turns quiet days "
                        "into public information.",
                        "scenes": [
                            {
                                "visual_prompt": "A quiet Denver street",
                                "on_screen_text": "Denver",
                            }
                        ],
                    },
                    rejected_reason="Editorial reserve — the opening repeats piece 10.",
                )
                db.add(piece)
                await db.commit()
                row = ContentRejection(
                    org_id=ORG,
                    piece_id=piece.id,
                    reason=piece.rejected_reason,
                    snapshot={
                        "hook": piece.hook,
                        "script": piece.script,
                        "caption": piece.caption,
                        "scenes": piece.scenes,
                        "media_path": None,
                    },
                )
                db.add(row)
                await db.commit()
                await content_corrections._rewrite(db, row, piece)

    assert seen.get("brokerage") == LINE
    await _cleanup()

@pytest.mark.anyio
async def test_the_second_ask_of_a_correction_keeps_the_line(database_url: str) -> None:
    """The retry inside `_ask_correction` dropped it, and silently.

    The parameter defaults to empty and `_with_cta` only acts when it is set,
    so a corrected draft that went round twice came back with no brokerage
    line, the model call was paid for, and the gate refused the result
    afterwards. Its twin `_ask` passes the line on its retry; this one did not.
    """
    import app.services.content_writer as cw

    # Driven through the REAL function: what is patched is what it calls, not
    # itself, so the retry branch actually executes. The first answer types a
    # web address, which is what sends `_ask_correction` round a second time;
    # the second is clean, so the tail runs — inside the RETRY, which is the
    # call that used to lose the line.
    answers = [
        _Reply({
            "hook": "Pricing high can cost you",
            "script": "A high list price turns quiet days into public information.",
            "caption": "Start at denverhomestory.com and see the number.",
            "scenes": [{"visual_prompt": "A street", "on_screen_text": "Denver"}],
        }),
        _Reply({
            "hook": "Pricing high can cost you",
            "script": "A high list price turns quiet days into public information.",
            "caption": "The risk is not ambition; it is timing.",
            "scenes": [{"visual_prompt": "A street", "on_screen_text": "Denver"}],
        }),
    ]

    async def _answer(*args, **kw):
        return answers.pop(0) if answers else answers[-1]

    seen: list[str] = []
    real = cw._with_cta

    def _watch(draft, language, cta_index=0, plan=None, brokerage=""):
        seen.append(brokerage)
        return real(draft, language, cta_index, plan, brokerage)

    with patch.object(cw, "generate_reply", new=_answer):
        with patch.object(cw, "_with_cta", new=_watch):
            out = await cw._ask_correction(
                DraftPayload(
                    hook="Pricing high can cost you",
                    script="A high list price turns quiet days into public "
                    "information.",
                    caption="A caption.",
                    scenes=[{"visual_prompt": "A street", "on_screen_text": "Denver"}],
                ),
                "The opening repeats piece 10.",
                ContentLanguage.EN,
                brokerage=LINE,
            )

    # The tail ran once, inside the retry, and the line was there.
    assert out is not None
    assert seen == [LINE]
    assert caption_carries_brokerage(out.caption, LINE)


@pytest.mark.anyio
async def test_a_piece_already_publishing_is_not_stranded(database_url: str) -> None:
    """Refusing there would be permanent, and would not unpublish anything.

    A piece in PUBLISHING is already out on at least one platform, cannot be
    edited (the endpoint answers 409) and cannot be closed until every platform
    reaches a terminal state. So the refusal is skipped when resuming, which is
    the only case that can exist: everything written from this release carries
    the line by construction.
    """
    await _cleanup()
    try:
        with org_scope(ORG):
            async with get_bypass_session_factory()() as db:
                await _with_a_line_on_record(db)
                piece_id = await _a_piece(
                    db, "A caption that names nobody.", ContentStatus.PUBLISHING
                )
                piece = await ensure_publishable(db, piece_id, resuming=True)
                assert piece.id == piece_id
                # And an APPROVED one is still refused **with the same
                # `resuming=True`** that `publish_piece` always passes. This is
                # the production call, and until this line existed no test
                # covered it: the gate was keyed on the flag instead of the
                # state, so it never ran where it mattered.
                other = await _a_piece(
                    db, "A caption that names nobody.", ContentStatus.APPROVED
                )
                with pytest.raises(NotIdentified):
                    await ensure_publishable(db, other, resuming=True)
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_a_held_piece_is_announced_and_not_only_logged(database_url: str) -> None:
    """A piece held in silence is held for ever — this codebase's own sentence.

    Driven through `publish_approved`, which is the point. An earlier version of
    this test was rewritten to read the source instead, because it kept failing
    — and it was failing for the right reason: the gate was written as
    `if not resuming`, `publish_piece` passes `resuming=True` on every call, so
    the check never ran, the piece sailed past, and no notice was sent. Turning
    the test into a source read buried the only evidence that the release did
    nothing.
    """
    from app.config import get_settings as _gs
    from app.services import buffer_publisher

    s = _gs()
    antes = (
        s.CONTENT_PUBLISH_ENABLED,
        s.BUFFER_CHANNEL_YOUTUBE,
        s.CONTENT_SCHEDULE_ENABLED,
        s.CONTENT_PUBLIC_BASE_URL,
    )
    s.CONTENT_PUBLISH_ENABLED = True
    s.BUFFER_CHANNEL_YOUTUBE = "test-channel"
    s.CONTENT_SCHEDULE_ENABLED = False
    # Without this the publisher says "configured but unusable" and returns
    # before looking at any piece.
    s.CONTENT_PUBLIC_BASE_URL = "https://www.denverhomestory.com"

    said: list[int] = []

    async def _spy(piece_id: int, hook: str) -> bool:
        said.append(piece_id)
        return True

    await _cleanup()
    try:
        with org_scope(ORG):
            async with get_bypass_session_factory()() as db:
                await _with_a_line_on_record(db)
                # The caption has the site link, so the twin refusal does not
                # fire first and swallow the result.
                piece_id = await _a_piece(
                    db,
                    "A caption that names nobody. https://www.denverhomestory.com",
                    ContentStatus.APPROVED,
                )
                piece = await db.get(ContentPiece, piece_id)
                assert piece is not None
                piece.approved_by = "office"
                piece.approved_at = datetime.now(UTC)
                await db.commit()

        with patch.object(buffer_publisher, "notify_held_without_brokerage", new=_spy):
            with org_scope(ORG):
                async with get_session_factory()() as db:
                    await buffer_publisher.publish_approved(db)
        assert said == [piece_id]
    finally:
        (
            s.CONTENT_PUBLISH_ENABLED,
            s.BUFFER_CHANNEL_YOUTUBE,
            s.CONTENT_SCHEDULE_ENABLED,
            s.CONTENT_PUBLIC_BASE_URL,
        ) = antes
        await _cleanup()


def test_the_two_refusals_are_different_kinds() -> None:
    """And the specific one is still a refusal, so nothing that catches the
    general kind stops working."""
    assert issubclass(NotIdentified, NotPublishable)
    assert NotIdentified is not NotPublishable
