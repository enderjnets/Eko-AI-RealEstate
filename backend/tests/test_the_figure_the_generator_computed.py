"""The number is computed first, and the model writes words around it.

`test_the_figure_the_calculator_never_saw.py` covers the door: a figure the
calculator cannot account for is refused at approval. This covers the road —
the rail added in v0.106.0 where `content_calculated` asks the calculator for
the figure BEFORE anything is written, hands it to the model in the brief, and
puts it on screen itself.

The distinction matters because the door alone made the only format this
channel has ever been watched for unshippable: after v0.104.0 a rent-vs-buy
piece could be approved only if somebody wrote its `calculator_check` by hand,
which is what happened to pieces 41, 43, 45 and 52-56 on 15-sep-2026 — by SQL,
one at a time, by me. A gate with no supply behind it does not stop bad
content; it stops content.

What is under test is the machinery, never the model. `generate_reply` is
patched in every test that reaches it, exactly as `test_content_writer.py`
does, and the assertions are about where a draft lands and what it carries.
"""

from __future__ import annotations

import json
import logging
import os
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import ContentKind, ContentLanguage, ContentPiece, ContentStatus
from app.services.calculator import build_snapshot
from app.services.content_calculated import (
    RENTS,
    SAVINGS,
    SERIES,
    plan_for,
    scene_fields,
    to_thousand,
)
from app.services.content_figures import claimed_text, unexplained_figures
from app.services.content_topics import (
    CALCULATED_SOURCE,
    TOPICS,
    calculated_index,
    next_topic,
    prose_index,
)
from app.services.content_writer import DraftPayload, _with_cta, generate_draft
from app.services.llm import LLMResult
from app.services.tenant_context import org_scope

ORG = 1

@pytest.fixture(autouse=True)
async def _a_brokerage_line_on_record():
    """`generate_draft` will not write a draft without one, so these need it.

    Seeded rather than assumed. Before this existed, thirteen tests across
    three files passed only because some other file, earlier in the alphabet,
    had left the column set — measured by emptying `brokerage_line` and running
    each file on its own. That is the same failure this suite's conftest
    already documents about an environment variable: green for whoever had it,
    red for everyone else.
    """
    from sqlalchemy import select as _select

    from app.models import AgentSettings as _AgentSettings

    async with get_bypass_session_factory()() as _db:
        row = (
            await _db.execute(_select(_AgentSettings).where(_AgentSettings.org_id == ORG))
        ).scalar_one_or_none()
        if row is None:
            _db.add(_AgentSettings(org_id=ORG, agency_name="Denver Home Story",
                                   brokerage_line="Engel & Völkers"))
        elif not (row.brokerage_line or "").strip():
            row.brokerage_line = "Engel & Völkers"
        await _db.commit()
    yield



@pytest.fixture(autouse=True)
def _this_is_our_rail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "CONTENT_ORG_ID", ORG, raising=False)
    monkeypatch.setattr(get_settings(), "CONTENT_STUDIO_ENABLED", True, raising=False)


@pytest.fixture(autouse=True)
def _a_conversion_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """The calculator rail only runs on conversion days, so pin one.

    Left to the real calendar, the series came from TODAY's weekday: green on
    Tuesday and Sunday, red on the other five days (23-sep-2026, a Wednesday,
    against untouched main). Worse, the tests that assert a draft does NOT
    reach the queue passed on those days for the wrong reason: the short
    growth contract refused it, not the invented figure.
    """
    from datetime import UTC, datetime

    from app.models import ContentSeries

    async def _conversion(*_args, **_kwargs):
        return datetime.now(UTC).date(), ContentSeries.CONVERSION, None

    monkeypatch.setattr(
        "app.services.content_writer._editorial_assignment", _conversion
    )


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


def _reply(payload: dict) -> LLMResult:
    return LLMResult(
        text=json.dumps(payload),
        provider="kimi",
        model="test",
        input_tokens=10,
        output_tokens=10,
    )


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


# --------------------------------------------------------------------------
# The figure itself
# --------------------------------------------------------------------------


def test_the_brief_states_what_the_calculator_computes_not_a_constant() -> None:
    """Recomputed here, deliberately.

    Pinning the six answers as literals would pass for ever after somebody
    changed `DEFAULTS["appreciation"]` and left twelve videos promising the old
    number — which is, exactly, the failure this rail was built to end. The
    assertion is that the two agree, not that either equals 42,000.
    """
    for index in range(len(SERIES) * len(RENTS)):
        plan = plan_for(index, ContentLanguage.EN)
        series = SERIES[(index // len(RENTS)) % len(SERIES)]
        fresh = build_snapshot(
            {"rent": plan.rent, "savings": SAVINGS, "credit": "good"}, None, lang=None
        )
        assert plan.figure == to_thousand(fresh["result"][series.field]), (
            f"piece {index} states ${plan.figure:,} where the calculator now "
            f"answers {fresh['result'][series.field]} for rent ${plan.rent:,}"
        )
        assert f"${plan.figure:,}" in plan.topic.brief_en
        assert f"${plan.figure:,}" in plan.topic.brief_es


def test_every_planned_piece_survives_its_own_check() -> None:
    """The whole rail, against the gate that will judge it.

    A piece whose own screen text its own record cannot explain would be
    generated, rendered, and refused at the moment a person tried to approve
    it — the cost paid in full, three steps before anybody found out.
    """
    for index in range(len(SERIES) * len(RENTS)):
        plan = plan_for(index, ContentLanguage.EN)
        screen = "\n".join(line for _, line in scene_fields(plan))
        assert unexplained_figures(screen, plan.check) == [], (
            f"piece {index} puts a figure on screen its own record cannot "
            "account for"
        )


def test_the_rounding_is_the_gate_s_own_arithmetic() -> None:
    """`to_thousand` and `rounds_to` must agree on every value, not almost.

    Python's `round` is half-to-even and the calculator's `_round` is half-up.
    Written with the wrong one, a figure landing on an exact half would be
    stated one way and checked the other, and a correct piece would be refused
    by the very record written to let it through.
    """
    for value in (49_500, 50_500, 42_499, 42_500, 313_263, 1_500, 2_500):
        stated = to_thousand(value)
        assert round(value / 1000) * 1000 == stated, (
            f"{value} is stated as {stated} but the gate rounds it elsewhere"
        )


# --------------------------------------------------------------------------
# The hole the on-screen text was hiding in
# --------------------------------------------------------------------------


def test_a_figure_only_on_screen_is_still_a_claim() -> None:
    """The five pulled videos said their number ON SCREEN.

    `docs/content/otono-2026.md` requires the screen to stand alone precisely
    because nobody reads the caption before deciding whether to keep watching.
    A gate reading hook and caption only would have passed all five had the
    caption been silent — which is a caption edit away, not a hypothetical.
    """
    scenes = {
        "narration": "whatever the narrator says",
        "scenes": [
            {"visual_prompt": "a Denver street", "on_screen_text": "about $21,000 ahead."}
        ],
    }
    check = {"scenarios": [{"inputs": {"rent": 2600, "savings": 60000, "credit": "good"}}]}

    silent_caption = claimed_text("Five years of renting.", "Save this.", scenes)
    assert unexplained_figures(silent_caption, check) == [21_000], (
        "a figure nobody can account for passed because it was only on screen"
    )

    # And the other half of the invariant: the text the gate reads is not
    # merely longer, it is the RIGHT text — a piece with nothing on screen is
    # unaffected.
    assert unexplained_figures(claimed_text("A hook.", "A caption.", None), check) == []


def test_a_figure_only_in_the_script_is_still_a_claim() -> None:
    """The narrator says it out loud, which is not "nobody can see it".

    The first draft of `claimed_text` left the script out, reasoning that
    `worker/spoken.py` converts "$450,000" into words before anybody hears it.
    That is backwards: the conversion is what makes a viewer *hear* the claim.
    A figure in the script is a figure in the video.
    """
    check = {"scenarios": [{"inputs": {"rent": 2600, "savings": 60000, "credit": "good"}}]}
    spoken_only = claimed_text(
        "A hook with no number.",
        "A caption with no number.",
        None,
        "And after five years you come out about $21,000 ahead.",
    )
    assert unexplained_figures(spoken_only, check) == [21_000]

    # The narration, when a piece carries one that differs from the script, is
    # the text actually spoken — and it is read for the same reason.
    narrated = claimed_text(
        "A hook.",
        "A caption.",
        {"narration": "roughly $21,000 ahead", "scenes": []},
    )
    assert unexplained_figures(narrated, check) == [21_000]


# --------------------------------------------------------------------------
# The writer
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_calculated_draft_queues_itself_with_its_record(
    database_url: str,
) -> None:
    """The point of the whole exercise: no hand-written SQL in the path."""
    try:
        plan = plan_for(0, ContentLanguage.EN)
        payload = {
            "hook": (
                f"Renting in Denver at ${plan.rent:,} a month? Five years of "
                f"buying comes out about ${plan.figure:,} ahead."
            ),
            "script": (
                "Start with the rent you would pay, then compare it with the "
                "equity a purchase may build. Include appreciation, the loan "
                "balance paid down, and the cost to sell at the end. The "
                "calculator keeps every assumption visible, so you can move "
                "each one and see how the estimate changes."
            ),
            "caption": "Every assumption behind it is a slider on the page.",
        }
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    "app.services.content_writer.generate_reply",
                    AsyncMock(return_value=_reply(payload)),
                ):
                    piece = await generate_draft(db)

        assert piece is not None
        assert piece.status is ContentStatus.NEEDS_APPROVAL, (
            f"a correct calculated piece did not reach the queue: {piece.violations}"
        )
        assert piece.kind is ContentKind.GENERATED
        assert piece.calculator_check is not None, (
            "the piece reached the queue with no record, so approval will 409 "
            "on it exactly as it did before this rail existed"
        )
        assert piece.calculator_check["scenarios"][0]["inputs"]["rent"] == plan.rent
        # The gate at approval, run here against what was actually stored.
        assert (
            unexplained_figures(
                claimed_text(piece.hook, piece.caption, piece.scenes),
                piece.calculator_check,
            )
            == []
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_screen_text_is_never_the_model_s(database_url: str) -> None:
    """`_CTA` keeps the URL out of the model's hands because it would drop a
    character. A figure is the same kind of value and the stakes are higher:
    the wrong one is a promise the page refuses to repeat."""
    try:
        plan = plan_for(0, ContentLanguage.EN)
        payload = {
            "hook": f"About ${plan.figure:,} ahead in five years.",
            "script": "A script.",
            "caption": "A caption.",
            "scenes": [
                {"visual_prompt": "a house", "on_screen_text": "Buying is $9,999 ahead"},
                {"visual_prompt": "a door", "on_screen_text": "trust me"},
            ],
        }
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    "app.services.content_writer.generate_reply",
                    AsyncMock(return_value=_reply(payload)),
                ):
                    piece = await generate_draft(db)

        assert piece is not None
        on_screen = [s["on_screen_text"] for s in piece.scenes["scenes"]]
        assert "Buying is $9,999 ahead" not in on_screen, (
            "the model's own screen text survived, so the figure a viewer "
            "reads is one nothing checked"
        )
        assert list(plan.screen) == on_screen
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_invented_figure_never_reaches_the_queue(database_url: str) -> None:
    """One rewrite, then it stays a DRAFT wearing the reason.

    The same shape as the Fair Housing path, and for the same reason: a model
    that failed twice with the number in front of it is not going to converge,
    and a piece a person has to look at is strictly better than a 409 in their
    face at the moment they try to approve it.
    """
    try:
        payload = {
            "hook": "Buying puts you $99,000 ahead in five years.",
            "script": "A script with no figures.",
            "caption": "A caption.",
        }
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    "app.services.content_writer.generate_reply",
                    AsyncMock(return_value=_reply(payload)),
                ) as llm:
                    piece = await generate_draft(db)

        assert piece is not None
        assert llm.await_count == 2, "the one rewrite did not happen"
        assert piece.status is ContentStatus.DRAFT, (
            "a piece stating a figure nobody computed walked itself into the "
            "approval queue"
        )
        assert piece.violations is not None
        assert any(v.get("category") == "figure" for v in piece.violations), (
            f"the reason is not recorded where a person will read it: "
            f"{piece.violations}"
        )
        assert any("$99,000" in v.get("phrase", "") for v in piece.violations)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_prose_piece_that_invents_a_figure_is_caught_too(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_SYSTEM` has always said "never invent numbers". Nothing read the answer.

    On the prose rail there is no record at all, so ANY dollar figure is
    unexplained — which is the correct reading: a piece about inspections has
    no business naming a price, and before v0.106.0 the first thing to notice
    was a person clicking approve.
    """
    monkeypatch.setattr(get_settings(), "CONTENT_CALCULATED_EVERY", 0, raising=False)
    try:
        payload = {
            "hook": "A typical Denver inspection runs about $650.",
            "script": "A script.",
            "caption": "A caption.",
        }
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    "app.services.content_writer.generate_reply",
                    AsyncMock(return_value=_reply(payload)),
                ):
                    piece = await generate_draft(db)

        assert piece is not None
        assert piece.calculator_check is None, "a prose piece carries no record"
        assert piece.status is ContentStatus.DRAFT
        assert any(v.get("category") == "figure" for v in (piece.violations or []))
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_rail_can_be_turned_off_entirely(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero means prose, exactly as before this existed."""
    monkeypatch.setattr(get_settings(), "CONTENT_CALCULATED_EVERY", 0, raising=False)
    try:
        payload = {
            "hook": "Three things to check before you offer.",
            "script": (
                "Start with the inspection, recent comparable sales, and the "
                "loan estimate. Then compare the repair exposure with the "
                "monthly payment you can actually carry. A clear offer "
                "connects those facts before emotion or urgency changes the "
                "decision, and leaves room to verify every assumption with "
                "your own advisors."
            ),
            "caption": "Save this.",
            "scenes": [
                {
                    "visual_prompt": (
                        f"wide exterior angle {i} of a Denver home in natural "
                        "light, with no readable text or signs"
                    ),
                    "on_screen_text": f"Offer check {i}",
                }
                for i in range(1, 8)
            ],
        }
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    "app.services.content_writer.generate_reply",
                    AsyncMock(return_value=_reply(payload)),
                ):
                    piece = await generate_draft(db)
        assert piece is not None
        assert piece.calculator_check is None
        assert piece.status is ContentStatus.NEEDS_APPROVAL
    finally:
        await _cleanup()


# --------------------------------------------------------------------------
# The rotation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_prose_rotation_does_not_skip_topics(database_url: str) -> None:
    """The trap in interleaving two rails through one counter.

    `next_topic` is `TOPICS[n % 12]`. Counted over EVERY generated piece, with
    one calculated piece between every two prose ones, `n` moves in twos and
    the rotation visits six of the twelve topics for ever — the other six
    never get made, and nothing anywhere says so.
    """
    try:
        async with get_bypass_session_factory()() as db:
            for n in range(6):
                db.add(
                    ContentPiece(
                        org_id=ORG,
                        kind=ContentKind.GENERATED,
                        language=ContentLanguage.EN,
                        status=ContentStatus.DRAFT,
                        hook=f"piece {n}",
                        # Alternating rails, as production will hold them.
                        calculator_check=(
                            {"scenarios": [{"inputs": {"rent": 2200}}]}
                            if n % 2 == 0
                            else None
                        ),
                    )
                )
            await db.commit()

        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await prose_index(db) == 3, (
                    "the prose count is reading the other rail's pieces"
                )
                assert await next_topic(db) is TOPICS[3]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_hand_stamped_record_does_not_advance_this_rail(
    database_url: str,
) -> None:
    """The bug this nearly shipped with.

    Eight pieces were stamped with a `calculator_check` by hand on 15-sep-2026
    to get finished, correct work past the v0.104.0 gate. Counting "has a
    check" would have started the rail at index 8 — `price_ceiling` at $2,600,
    which is piece 42 word for word, scheduled for 18-sep on all three
    channels, with 43, 44 and 45 immediately behind it. The first four pieces
    this rail was built to produce would have been copies of what was already
    in the queue, and nothing would have said so.
    """
    try:
        async with get_bypass_session_factory()() as db:
            for n in range(8):
                db.add(
                    ContentPiece(
                        org_id=ORG,
                        kind=ContentKind.GENERATED,
                        language=ContentLanguage.EN,
                        status=ContentStatus.DRAFT,
                        hook=f"stamped by hand {n}",
                        # Exactly the shape written by SQL that day: inputs and
                        # a note, and no idea which rail it came from.
                        calculator_check={
                            "scenarios": [
                                {"inputs": {"rent": 2200, "savings": 60000,
                                            "credit": "good"}}
                            ],
                            "note": "Recovered 15-sep-2026 by hand.",
                        },
                    )
                )
            await db.commit()

        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await calculated_index(db) == 0, (
                    "the rail counted eight pieces it did not make, so its "
                    "first output would repeat what is already in the queue"
                )

        # And the stamp this rail does write is counted.
        plan = plan_for(0, ContentLanguage.EN)
        assert plan.check["source"] == CALCULATED_SOURCE
        async with get_bypass_session_factory()() as db:
            db.add(
                ContentPiece(
                    org_id=ORG,
                    kind=ContentKind.GENERATED,
                    language=ContentLanguage.EN,
                    status=ContentStatus.DRAFT,
                    hook="made by the rail",
                    calculator_check=plan.check,
                )
            )
            await db.commit()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await calculated_index(db) == 1
    finally:
        await _cleanup()


# --------------------------------------------------------------------------
# The link the calculated piece promises
# --------------------------------------------------------------------------


def _draft(caption: str = "Every assumption behind it is a slider on the page.") -> DraftPayload:
    return DraftPayload(hook="A hook.", script="A script.", caption=caption)


def test_a_calculated_caption_lands_on_its_own_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The video says a number; the link has to open on that number.

    `denverhomestory.com/calculator` with nothing after it opens an empty form
    on the site's own defaults, and the defaults are not what the video was
    computed from — which is how five videos came to promise $21,000 where the
    page says $52,210. The two inputs travel in the URL because they are the
    same two `plan` computed the figure from, not a copy of them.
    """
    monkeypatch.setattr(
        get_settings(), "CONTENT_CTA_URL", "https://www.denverhomestory.com",
        raising=False,
    )
    plan = plan_for(2, ContentLanguage.EN)
    assert plan.rent == 2600, "this test is written around the $2,600 band"

    out = _with_cta(_draft(), ContentLanguage.EN, 0, plan)

    assert out is not None
    assert "calculator?rent=2600&savings=60000" in out.caption, out.caption
    # And it speaks to the person who is renting, not to a seller.
    assert "Run your own number" in out.caption
    assert "Thinking about selling" not in out.caption


def test_the_spanish_calculated_caption_carries_the_same_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two languages, one link. A translated sentence with an untranslated —
    or absent — seed is the same broken promise in another language."""
    monkeypatch.setattr(
        get_settings(), "CONTENT_CTA_URL", "https://www.denverhomestory.com",
        raising=False,
    )
    plan = plan_for(2, ContentLanguage.ES)
    out = _with_cta(_draft("Cada supuesto es un control en la página."),
                    ContentLanguage.ES, 0, plan)
    assert out is not None
    assert "calculator?rent=2600&savings=60000" in out.caption, out.caption
    assert "Haz tu propio número" in out.caption


def test_a_prose_caption_keeps_the_selling_cta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half. A piece about inspections has no figure to seed, and
    sending its viewer to a pre-filled calculator would be answering a question
    nobody asked. No plan, no seed, and the selling sentence stays."""
    monkeypatch.setattr(
        get_settings(), "CONTENT_CTA_URL", "https://www.denverhomestory.com",
        raising=False,
    )
    out = _with_cta(_draft("A caption."), ContentLanguage.EN, 0, None)

    assert out is not None
    assert "calculator" not in out.caption, out.caption
    assert "Thinking about selling in Denver? Start here:" in out.caption


def test_no_url_configured_still_means_no_link_at_all(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`CONTENT_CTA_URL` empty is the install that has no landing page yet, and
    the rail is **inert** by design. A seeded path appended to an empty base
    would publish `/calculator?rent=…` as an absolute nothing.

    Inert is the word that matters, so the silence is asserted too: with no URL
    configured, `caption_carries_link` answers "yes" to everything, and a guard
    that leaned on it alone would reach this same empty caption by deciding the
    model had written a link. Same output, different reason — and the reason is
    what a later change would break."""
    monkeypatch.setattr(get_settings(), "CONTENT_CTA_URL", "", raising=False)
    caplog.set_level(logging.WARNING, logger="app.services.content_writer")
    plan = plan_for(2, ContentLanguage.EN)
    out = _with_cta(_draft("A caption."), ContentLanguage.EN, 0, plan)
    assert out is not None
    assert "calculator" not in out.caption
    assert "Run your own number" not in out.caption
    assert [r.getMessage() for r in caplog.records] == []


@pytest.mark.asyncio
async def test_a_calculated_draft_reaches_the_queue_carrying_its_link(
    database_url: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end, because `_with_cta` being right is worth nothing if the
    generator does not hand it the plan. And the caption it checks is the one
    `find_violations` reads, since the CTA is appended before the gate runs."""
    monkeypatch.setattr(
        get_settings(), "CONTENT_CTA_URL", "https://www.denverhomestory.com",
        raising=False,
    )
    try:
        plan = plan_for(0, ContentLanguage.EN)
        payload = {
            "hook": (
                f"Renting in Denver at ${plan.rent:,} a month? Five years of "
                f"buying comes out about ${plan.figure:,} ahead."
            ),
            "script": (
                "Start with the rent you would pay, then compare it with the "
                "equity a purchase may build. Include appreciation, the loan "
                "balance paid down, and the cost to sell at the end. The "
                "calculator keeps every assumption visible, so you can move "
                "each one and see how the estimate changes."
            ),
            "caption": "Every assumption behind it is a slider on the page.",
        }
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with patch(
                    "app.services.content_writer.generate_reply",
                    AsyncMock(return_value=_reply(payload)),
                ):
                    piece = await generate_draft(db)

        assert piece is not None
        assert f"calculator?rent={plan.rent}&savings={SAVINGS}" in piece.caption, (
            piece.caption
        )
        assert piece.status is ContentStatus.NEEDS_APPROVAL, piece.violations
    finally:
        await _cleanup()


def test_a_model_that_wrote_its_own_link_does_not_get_a_second_one(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The regression the seed introduced, held down.

    The old test was `url not in caption`, and a seeded link is never a
    substring of the bare one the model might write. So a caption that already
    carried `…/calculator` got a second link appended — and the publisher tags
    and follows up on the FIRST one it finds, which is the model's. The viewer
    would land on an empty form and the visit would arrive with no
    `utm_content`: the defect this rail exists to close, plus an unattributable
    click. Asked of `caption_carries_link`, the same function the publisher's
    own gate uses, so the two cannot drift.
    """
    monkeypatch.setattr(
        get_settings(), "CONTENT_CTA_URL", "https://www.denverhomestory.com",
        raising=False,
    )
    plan = plan_for(2, ContentLanguage.EN)
    caplog.set_level(logging.WARNING, logger="app.services.content_writer")

    out = _with_cta(
        _draft("Run the numbers yourself at denverhomestory.com/calculator."),
        ContentLanguage.EN,
        0,
        plan,
    )

    assert out is not None
    assert out.caption.lower().count("denverhomestory") == 1, out.caption
    assert "rent=2600" not in out.caption
    assert any("wrote its own site link" in r.getMessage() for r in caplog.records), (
        "the model broke the prompt's rule and nothing said so"
    )


def test_a_configured_url_with_a_trailing_slash_does_not_double_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seed is concatenated onto the configured URL, so one trailing slash
    in the environment publishes `…com//calculator?…`. One character of
    configuration away from a 404 on every calculated piece."""
    monkeypatch.setattr(
        get_settings(), "CONTENT_CTA_URL", "https://www.denverhomestory.com/",
        raising=False,
    )
    plan = plan_for(2, ContentLanguage.EN)
    out = _with_cta(_draft(), ContentLanguage.EN, 0, plan)
    assert out is not None
    assert "//calculator" not in out.caption, out.caption
    assert "com/calculator?rent=2600&savings=60000" in out.caption
