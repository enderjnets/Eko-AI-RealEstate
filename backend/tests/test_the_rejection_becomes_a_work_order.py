"""A rejection with a reason is a work order, not a note.

Four pieces were rejected on the live rail for the same missing call to action
over three days — 66, 70, 71 and 73 — and the fifth came out with it missing
too, because nothing ever read the string back. The phase before this one wrote
the reason down and diagnosed it. This one acts on it: the piece is corrected
and the video is made again, or a person is told why it will not be.

Two things are being guarded here at once, and they pull in opposite
directions. The rail must fix what it can without being asked. It must also
never spend a narration and six paid images on a guess, or loop.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import undefer

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentRejection,
    ContentStatus,
    RenderJob,
    RenderJobKind,
    RenderJobStatus,
)
from app.services.content_corrections import correct_rejected
from app.services.tenant_context import org_scope

ORG = 1

#: A narration that says the address out loud, as `with_sign_off` writes it.
WITH_SIGN_OFF = (
    "An appraisal and an online estimate answer different questions. "
    "Start at Denver Home Story dot com."
)
WITHOUT_SIGN_OFF = (
    "An appraisal and an online estimate answer different questions."
)


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — the sweep needs live Postgres")
    return url


@pytest.fixture(autouse=True)
def _the_rail_is_ours_and_it_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "CONTENT_ORG_ID", ORG, raising=False)
    monkeypatch.setattr(settings, "CONTENT_STUDIO_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings, "CONTENT_CTA_URL", "https://www.denverhomestory.com", raising=False
    )


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM render_jobs"))
        await db.execute(text("DELETE FROM content_rejections"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


def _scenes(narration: str, visual: str = "A quiet Denver street") -> dict:
    return {
        "narration": narration,
        "scenes": [
            {"visual_prompt": visual, "on_screen_text": "Denver"},
            {"visual_prompt": "A set of keys on a table", "on_screen_text": "Keys"},
        ],
    }


async def _rejected(
    reason: str,
    *,
    narration: str = WITH_SIGN_OFF,
    kind: ContentKind = ContentKind.GENERATED,
    scenes: dict | None = -1,  # type: ignore[assignment]
    media_path: str | None = "piece.mp4",
    calculator_check: dict | None = None,
    with_job: RenderJobStatus | None = RenderJobStatus.DONE,
    category: str | None = None,
    org_id: int = ORG,
    previous: tuple[str, ...] = (),
) -> tuple[int, int]:
    """A rejected piece and its open rejection row. Returns (piece_id, row_id)."""
    plan = _scenes(narration) if scenes == -1 else scenes
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=org_id,
            kind=kind,
            language=ContentLanguage.EN,
            status=ContentStatus.REJECTED,
            hook="What decides your home's value",
            script=WITHOUT_SIGN_OFF,
            caption="A caption with https://www.denverhomestory.com in it.",
            scenes=plan,
            media_path=media_path,
            calculator_check=calculator_check,
            rejected_reason=reason,
        )
        db.add(piece)
        await db.commit()
        # The history the caps count, written as the sweep would have written
        # it: resolved rows carrying an action.
        for action in previous:
            db.add(
                ContentRejection(
                    org_id=org_id,
                    piece_id=piece.id,
                    reason="an earlier one",
                    action=action,
                    resolved_at=piece.created_at,
                )
            )
        row = ContentRejection(
            org_id=org_id,
            piece_id=piece.id,
            reason=reason,
            category=category,
            snapshot={
                "hook": piece.hook,
                "script": piece.script,
                "caption": piece.caption,
                "scenes": piece.scenes,
                "media_path": piece.media_path,
            },
        )
        db.add(row)
        if with_job is not None:
            db.add(
                RenderJob(
                    org_id=org_id,
                    piece_id=piece.id,
                    kind=RenderJobKind.PRODUCE_B,
                    status=with_job,
                    attempts=3,
                    stage="uploading",
                    progress=90,
                    last_error="something from the old life",
                )
            )
        await db.commit()
        return piece.id, row.id


async def _sweep() -> int:
    with org_scope(ORG):
        async with get_session_factory()() as db:
            return await correct_rejected(db)


async def _row(row_id: int) -> ContentRejection:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                select(ContentRejection)
                .options(undefer(ContentRejection.snapshot))
                .where(ContentRejection.id == row_id)
            )
        ).scalar_one()


async def _piece(piece_id: int) -> ContentPiece:
    async with get_bypass_session_factory()() as db:
        return await db.get(ContentPiece, piece_id)


async def _jobs(piece_id: int) -> list[RenderJob]:
    async with get_bypass_session_factory()() as db:
        return list(
            (
                await db.execute(
                    select(RenderJob).where(RenderJob.piece_id == piece_id)
                )
            )
            .scalars()
            .all()
        )


class _Reply:
    def __init__(self, payload: dict) -> None:
        self.text = json.dumps(payload)


def _corrected(**over) -> dict:
    body = {
        "hook": "What an appraisal answers that an estimate cannot",
        "script": (
            "An appraisal is an opinion a lender will lend against, while an "
            "online estimate is only a starting point. Recent comparable sales, "
            "property condition, timing, and local demand can move the answer. "
            "Review those facts together before you choose a price or make an "
            "offer, because each tool serves a different decision in Denver. "
            "Write the figures down, compare them side by side, and ask a lender to confirm each one before you commit to anything."
        ),
        "caption": "The difference between the two, in one minute.",
        "scenes": [
            {"visual_prompt": "A quiet Denver street", "on_screen_text": "Denver"},
            {"visual_prompt": "A document with no legible text on a desk", "on_screen_text": "Appraisal"},
            {"visual_prompt": "A Denver home viewed from the sidewalk", "on_screen_text": "Condition"},
            {"visual_prompt": "A real estate advisor reviewing blank pages", "on_screen_text": "Comparable sales"},
            {"visual_prompt": "An unmarked calculator beside house keys", "on_screen_text": "Estimate"},
            {"visual_prompt": "The Denver skyline in clear daylight", "on_screen_text": "Local demand"},
            {"visual_prompt": "A buyer walking through an empty living room", "on_screen_text": "Your decision"},
        ],
    }
    body.update(over)
    return body


# ── The cheap answer, taken ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_video_made_before_the_fix_is_remade_and_costs_no_model(
    database_url: str,
) -> None:
    """The commonest case on the live rail, and the one that started all this.

    The narration already says the address; the video was made before the fix
    reached the narrator. There is nothing for a model to add, and asking one
    anyway would be a bill for a question already answered.
    """
    piece_id, row_id = await _rejected("CTA missing")
    asked = AsyncMock()
    try:
        with patch("app.services.content_writer.generate_reply", asked):
            assert await _sweep() == 1
        asked.assert_not_awaited()

        row = await _row(row_id)
        assert row.category == "no_cta"
        assert row.action == "rebuild"
        assert row.resolved_at is not None
        assert row.finding["narration_says_domain"] is True

        piece = await _piece(piece_id)
        assert piece.status is ContentStatus.DRAFT
        assert piece.media_path is None

        jobs = await _jobs(piece_id)
        assert len(jobs) == 1
        assert jobs[0].status is RenderJobStatus.QUEUED
        # The old job's last report belongs to the old job.
        assert (jobs[0].attempts, jobs[0].stage, jobs[0].progress) == (0, None, None)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_sweep_and_the_queue_together_make_one_job_not_two(
    database_url: str,
) -> None:
    """`enqueue_generated` looks for exactly the piece the sweep just made: a
    generated DRAFT with a plan and no video. If the two disagreed about whose
    job it is, a corrected piece would be rendered twice and billed twice."""
    from app.config import get_settings
    from app.services.content_render import enqueue_generated

    # Both of this sweep's own gates, opened on purpose. `RENDER_WORKER_ENABLED`
    # is False by default and the brokerage line is a legal requirement the
    # sweep refuses to build without — with either shut, `enqueue_generated`
    # returns 0 at its first line and this test would pass whatever the two
    # sweeps did to each other. Measured: it did exactly that.
    monkey = get_settings()
    was = monkey.RENDER_WORKER_ENABLED
    object.__setattr__(monkey, "RENDER_WORKER_ENABLED", True)
    async with get_bypass_session_factory()() as db:
        line = (
            await db.execute(
                text("SELECT brokerage_line FROM agent_settings WHERE org_id = 1")
            )
        ).scalar_one_or_none()
        await db.execute(
            text("UPDATE agent_settings SET brokerage_line = :v WHERE org_id = 1"),
            {"v": "Engel & Völkers"},
        )
        await db.commit()

    piece_id, _ = await _rejected("CTA missing")
    try:
        assert await _sweep() == 1
        with org_scope(ORG):
            async with get_session_factory()() as db:
                # The piece is exactly what this sweep looks for: a generated
                # DRAFT with a plan and no video. It must find the job already
                # there and leave it alone.
                await enqueue_generated(db)
        assert len(await _jobs(piece_id)) == 1
    finally:
        object.__setattr__(monkey, "RENDER_WORKER_ENABLED", was)
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE agent_settings SET brokerage_line = :v WHERE org_id = 1"),
                {"v": line},
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_a_piece_that_never_rendered_gets_a_job_made_for_it(
    database_url: str,
) -> None:
    """A draft rejected while it still carried findings has no render job at
    all. Resetting a job that is not there is how a correction reports success
    and produces nothing."""
    piece_id, row_id = await _rejected("CTA missing", with_job=None, media_path=None)
    try:
        assert await _sweep() == 1
        jobs = await _jobs(piece_id)
        assert len(jobs) == 1
        assert jobs[0].status is RenderJobStatus.QUEUED
        assert (await _row(row_id)).action == "rebuild"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_narration_that_lost_the_sign_off_gets_it_back(
    database_url: str,
) -> None:
    """Every piece written before 2-sep, and every piece whose script somebody
    edited by hand. Re-rendering one of these would produce the same silent
    video a second time."""
    piece_id, row_id = await _rejected(
        "There is not call to action at the end", narration=WITHOUT_SIGN_OFF
    )
    try:
        assert await _sweep() == 1
        assert (await _row(row_id)).action == "rematerialise"

        piece = await _piece(piece_id)
        narration = piece.scenes["narration"]
        assert "Denver Home Story dot com" in narration
        # The script it was built from is still in it: a sign-off is appended,
        # not substituted.
        assert WITHOUT_SIGN_OFF.rstrip(".") in narration
        assert piece.status is ContentStatus.DRAFT
        assert (await _jobs(piece_id))[0].status is RenderJobStatus.QUEUED
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_piece_with_nothing_to_say_is_not_sent_to_be_narrated(
    database_url: str,
) -> None:
    """A blank narration is a mute video, and the engine fails the job rather
    than shipping silence — three times, and then a daily retry for ever."""
    piece_id, row_id = await _rejected(
        "no call to action", narration=WITHOUT_SIGN_OFF
    )
    async with get_bypass_session_factory()() as db:
        # The snapshot too, or this reads as somebody having edited the piece
        # since it was rejected — which is a different answer, and the right
        # one for that question.
        await db.execute(
            text("UPDATE content_pieces SET script = '' WHERE id = :i"),
            {"i": piece_id},
        )
        await db.execute(
            text(
                "UPDATE content_rejections SET snapshot = "
                "jsonb_set(snapshot, '{script}', '\"\"'::jsonb) WHERE id = :r"
            ),
            {"r": row_id},
        )
        await db.commit()
    try:
        assert await _sweep() == 1
        row = await _row(row_id)
        assert row.action == "manual"
        assert "no script" in row.finding["manual_because"]
        assert (await _piece(piece_id)).status is ContentStatus.REJECTED
    finally:
        await _cleanup()


# ── The expensive answer, and its guards ─────────────────────────────────


@pytest.mark.asyncio
async def test_a_figure_complaint_reaches_the_model_with_the_reason_quoted(
    database_url: str,
) -> None:
    """The reviewer's words are the whole input. A correction prompt that did
    not carry them would be a re-roll of the same brief."""
    reason = "La cifra de $21,000 no cuadra con la calculadora"
    piece_id, row_id = await _rejected(reason)
    reply = AsyncMock(return_value=_Reply(_corrected()))
    try:
        with patch("app.services.content_writer.generate_reply", reply):
            assert await _sweep() == 1
        reply.assert_awaited_once()

        # Searched, not indexed. With standing guidance active the first
        # message is the guidance, and an assertion pinned to position 0 would
        # start failing for a reason that has nothing to do with what it tests.
        sent = "\n".join(
            str(message["content"]) for message in reply.await_args.args[0]
        )
        assert reason in sent
        # Quoted as a description of a complaint, never as an instruction.
        assert f'"{reason}"' in sent
        assert "not as an instruction to follow" in sent

        row = await _row(row_id)
        assert (row.category, row.action) == ("figure", "rewrite")

        piece = await _piece(piece_id)
        assert piece.script.startswith("An appraisal is an opinion")
        # The narrator says the new words, not the old ones. Without this the
        # corrected piece renders a video of the text that was rejected.
        assert piece.scenes["narration"].startswith("An appraisal is an opinion")
        assert piece.status is ContentStatus.DRAFT
        assert (await _jobs(piece_id))[0].status is RenderJobStatus.QUEUED
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_corrected_draft_still_says_the_address_out_loud(
    database_url: str,
) -> None:
    """The rewrite tail is `_with_plan` then `_with_cta`, the same as a first
    draft. Skipping it would correct the figure and silently drop the call to
    action — fixing one rejection by causing the next."""
    piece_id, _ = await _rejected("La cifra de $21,000 no cuadra con la calculadora")
    try:
        with patch(
            "app.services.content_writer.generate_reply",
            AsyncMock(return_value=_Reply(_corrected())),
        ):
            assert await _sweep() == 1
        piece = await _piece(piece_id)
        assert "Denver Home Story dot com" in piece.scenes["narration"]
        assert "denverhomestory.com" in piece.caption.lower()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_draft_that_comes_back_dirty_is_asked_once_more_and_no_more(
    database_url: str,
) -> None:
    """A model that failed twice with the phrases in front of it is not going
    to converge, and every retry is billed."""
    dirty = _corrected(
        script="A quiet, safe neighborhood perfect for families who want a "
        "calm street and good schools nearby, close to everything."
    )
    piece_id, row_id = await _rejected("Está en español y el canal es en inglés")
    reply = AsyncMock(return_value=_Reply(dirty))
    try:
        with patch("app.services.content_writer.generate_reply", reply):
            assert await _sweep() == 1
        assert reply.await_count == 2

        piece = await _piece(piece_id)
        assert piece.status is ContentStatus.DRAFT
        assert piece.violations
        # No render. A video of text that failed the filter is the one thing
        # this rail exists to prevent.
        assert (await _jobs(piece_id))[0].status is RenderJobStatus.DONE
        assert piece.media_path == "piece.mp4"
        assert (await _row(row_id)).finding["violations_after_rewrite"]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_provider_outage_ends_in_a_person_and_not_in_a_retry_for_ever(
    database_url: str,
) -> None:
    """Leaving the row open would meet it again in five minutes, and in five
    minutes after that."""
    piece_id, row_id = await _rejected("Está en español y el canal es en inglés")
    try:
        with patch(
            "app.services.content_writer.generate_reply",
            AsyncMock(side_effect=RuntimeError("both providers down")),
        ):
            assert await _sweep() == 1
        row = await _row(row_id)
        # A rewrite, not a manual: the call was made and the call was billed,
        # and only a `rewrite` is counted by the caps. Recording it as manual
        # would let a provider having a bad afternoon bill one call per
        # rejection with the day's counter still reading zero.
        assert row.action == "rewrite"
        assert row.finding["rewrite_failed"]
        assert row.resolved_at is not None
        assert (await _piece(piece_id)).status is ContentStatus.REJECTED
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_calculated_piece_whose_plan_will_not_come_back_is_left_alone(
    database_url: str,
) -> None:
    """The $21,000-against-$52,210 defect, re-entering through the door built
    to repair it. Rewritten without its `Plan`, a calculated piece gets the
    seller's sign-off, a link with no seed and a figure of the model's own
    choosing."""
    piece_id, row_id = await _rejected(
        "La cifra de $21,000 no cuadra con la calculadora",
        calculator_check={"scenarios": [{"inputs": {"rent": 1800}}]},
    )
    asked = AsyncMock()
    try:
        with patch("app.services.content_writer.generate_reply", asked):
            assert await _sweep() == 1
        asked.assert_not_awaited()
        assert (await _row(row_id)).action == "manual"
        assert (await _piece(piece_id)).status is ContentStatus.REJECTED
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_calculated_piece_whose_plan_does_come_back_is_rewritten_with_it(
    database_url: str,
) -> None:
    """The counterweight. A guard that refused every calculated piece would be
    indistinguishable from one that works, and this rail is half the queue."""
    from app.services.content_calculated import CALCULATED_SOURCE, SERIES

    piece_id, row_id = await _rejected(
        "La cifra de $21,000 no cuadra con la calculadora",
        calculator_check={
            "scenarios": [{"inputs": {"rent": 1800, "savings": 60000, "credit": "good"}}],
            "source": CALCULATED_SOURCE,
            "series": SERIES[0].key,
        },
    )
    try:
        with patch(
            "app.services.content_writer.generate_reply",
            AsyncMock(return_value=_Reply(_corrected())),
        ):
            assert await _sweep() == 1
        assert (await _row(row_id)).action == "rewrite"
        piece = await _piece(piece_id)
        # The shot list came from the plan, not from the model: the figure the
        # owner caught was ON SCREEN.
        assert piece.scenes["scenes"][0]["on_screen_text"] != "Denver"
        assert "?" in piece.caption  # the seeded link carries the inputs
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_shot_list_that_is_not_english_is_never_sent_to_the_image_model(
    database_url: str,
) -> None:
    """fal answers 200 with a picture of something else. The failure mode is
    the expensive kind: six pictures bought, a video rendered, and the wrong
    images going out under a licensed brokerage's name."""
    piece_id, row_id = await _rejected(
        "CTA missing",
        scenes=_scenes(
            WITH_SIGN_OFF,
            visual="Una casa de ladrillo en una calle tranquila de Denver con "
            "arboles altos y un cartel de se vende en el jardin delantero",
        ),
    )
    try:
        assert await _sweep() == 1
        row = await _row(row_id)
        assert row.action == "manual"
        assert "not in English" in row.finding["not_rendered_because"]

        piece = await _piece(piece_id)
        # The refusal left the piece exactly as it was. A caller that lost the
        # video here would have nothing to show and nothing to rebuild.
        assert piece.media_path == "piece.mp4"
        assert piece.status is ContentStatus.REJECTED
        assert (await _jobs(piece_id))[0].status is RenderJobStatus.DONE
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_filmed_clip_is_never_regenerated(database_url: str) -> None:
    """Its file is the only copy of what somebody filmed once."""
    piece_id, row_id = await _rejected("La voz se oye cortada", kind=ContentKind.RECORDED)
    try:
        assert await _sweep() == 1
        assert (await _row(row_id)).action == "manual"
        piece = await _piece(piece_id)
        assert piece.media_path == "piece.mp4"
        assert piece.status is ContentStatus.REJECTED
    finally:
        await _cleanup()


# ── The ceilings ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_third_rejection_of_one_piece_stops_and_rings(
    database_url: str,
) -> None:
    """Two automatic corrections per piece, decided by the owner. A third is
    not a correction, it is a loop — and a loop that pays per lap."""
    piece_id, row_id = await _rejected(
        "CTA missing", previous=("rebuild", "rewrite")
    )
    alert = AsyncMock(return_value=True)
    try:
        with patch("app.services.ops_alert.send_operator_alert", alert):
            assert await _sweep() == 1
        alert.assert_awaited_once()
        assert str(piece_id) in alert.await_args.args[0]

        row = await _row(row_id)
        assert row.action == "given_up"
        assert "which is the limit" in row.finding["gave_up_because"]

        piece = await _piece(piece_id)
        assert piece.status is ContentStatus.REJECTED
        assert piece.media_path == "piece.mp4"
        assert (await _jobs(piece_id))[0].status is RenderJobStatus.DONE
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_actions_that_spend_nothing_do_not_use_up_the_piece(
    database_url: str,
) -> None:
    """A piece nothing could be done about twice would otherwise be out of
    goes before anything had been tried."""
    piece_id, row_id = await _rejected(
        "CTA missing", previous=("manual", "superseded")
    )
    try:
        assert await _sweep() == 1
        assert (await _row(row_id)).action == "rebuild"
        assert (await _piece(piece_id)).status is ContentStatus.DRAFT
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_day_has_a_ceiling_of_its_own(database_url: str) -> None:
    """Three per agency per day. Without it one bad afternoon of rejections is
    one bad afternoon of renders."""
    from datetime import UTC, datetime

    spent = await _rejected("CTA missing", previous=())
    async with get_bypass_session_factory()() as db:
        now = datetime.now(UTC)
        for action in ("rebuild", "rematerialise", "rewrite"):
            db.add(
                ContentRejection(
                    org_id=ORG,
                    piece_id=spent[0],
                    reason="earlier today, on another piece",
                    action=action,
                    resolved_at=now,
                )
            )
        await db.commit()
    piece_id, row_id = await _rejected("CTA missing")
    try:
        with patch("app.services.ops_alert.send_operator_alert", AsyncMock()):
            await _sweep()
        row = await _row(row_id)
        assert row.action == "given_up"
        assert "today" in row.finding["gave_up_because"]
        assert (await _piece(piece_id)).status is ContentStatus.REJECTED
    finally:
        await _cleanup()


# ── Getting out of somebody's way ────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_piece_somebody_fixed_by_hand_is_not_rewritten_on_top(
    database_url: str,
) -> None:
    """Editing a rejected piece leaves it REJECTED — nothing in `edit_piece`
    advances it — so the status alone cannot answer this. A person who read
    the reason and fixed the script deserves better than a model rewriting
    their work."""
    piece_id, row_id = await _rejected("La cifra de $21,000 no cuadra")
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE content_pieces SET script = :s WHERE id = :i"),
            {"s": "The figure a person put here by hand.", "i": piece_id},
        )
        await db.commit()
    asked = AsyncMock()
    try:
        with patch("app.services.content_writer.generate_reply", asked):
            assert await _sweep() == 1
        asked.assert_not_awaited()
        row = await _row(row_id)
        assert row.action == "superseded"
        assert row.resolved_at is not None
        piece = await _piece(piece_id)
        assert piece.script == "The figure a person put here by hand."
        assert piece.media_path == "piece.mp4"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_piece_somebody_already_retried_is_left_where_they_put_it(
    database_url: str,
) -> None:
    piece_id, row_id = await _rejected("CTA missing")
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE content_pieces SET status = 'draft' WHERE id = :i"),
            {"i": piece_id},
        )
        await db.commit()
    try:
        assert await _sweep() == 1
        assert (await _row(row_id)).action == "superseded"
        assert (await _jobs(piece_id))[0].status is RenderJobStatus.DONE
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_another_agency_is_not_this_rail(database_url: str) -> None:
    """`run_for_every_org` visits every tenant by design. A correction on the
    demo organization spends a render on content nobody will ever look at."""
    piece_id, row_id = await _rejected("CTA missing", org_id=2)
    try:
        with org_scope(2):
            async with get_session_factory()() as db:
                assert await correct_rejected(db) == 0
        assert (await _row(row_id)).action is None
        assert (await _piece(piece_id)).status is ContentStatus.REJECTED
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_studio_that_is_switched_off_corrects_nothing(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    piece_id, row_id = await _rejected("CTA missing")
    monkeypatch.setattr(get_settings(), "CONTENT_STUDIO_ENABLED", False, raising=False)
    try:
        assert await _sweep() == 0
        assert (await _row(row_id)).action is None
        assert (await _piece(piece_id)).media_path == "piece.mp4"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_one_bad_row_does_not_stop_the_ones_behind_it(
    database_url: str,
) -> None:
    """The sweep meets rows oldest first. Without a guard per row, one piece
    that raises would stop every correction behind it, for ever — the same row
    first, every five minutes."""
    first, first_row = await _rejected("CTA missing")
    second, second_row = await _rejected("CTA missing")

    async def _boom(db, row, piece, action):  # noqa: ANN001
        # SQL FIRST, and that is the whole point of this test. The real `_act`
        # always issues some — `requeue_render` selects the job, a rematerialise
        # reads the rotation — so the session has an open transaction when it
        # fails. A fake that raised before touching the database left nothing
        # for `rollback()` to expire, the handler read `row.id` from memory,
        # and the green hid a sweep that died inside its own error handler.
        await db.execute(text("SELECT 1"))
        if piece.id == first:
            raise RuntimeError("this one is broken")
        return True

    try:
        with patch("app.services.content_corrections._act", _boom):
            assert await _sweep() == 1
        # The one that raised is still open, so the next tick meets it again.
        assert (await _row(first_row)).resolved_at is None
        # The one behind it was reached, diagnosed and closed.
        closed = await _row(second_row)
        assert closed.action == "rebuild"
        assert closed.resolved_at is not None
        assert second != first
    finally:
        await _cleanup()


# ── What the audit found ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_the_filter_refuses_is_never_rendered(database_url: str) -> None:
    """Findings against the TEXT outrank whatever the reviewer was describing.

    Without this a piece rejected for its pictures, whose words the Fair
    Housing filter had already refused, would buy a narration and six images —
    and the delivery endpoint would then refuse to advance it, so the money is
    gone and the video parks in DRAFT where nobody can approve it.
    """
    piece_id, row_id = await _rejected("Una de las imágenes salió en negro")
    async with get_bypass_session_factory()() as db:
        piece = await db.get(ContentPiece, piece_id)
        piece.violations = [{"phrase": "perfect for families", "category": "fair_housing"}]
        await db.commit()
    try:
        with patch(
            "app.services.content_writer.generate_reply",
            AsyncMock(return_value=_Reply(_corrected())),
        ):
            assert await _sweep() == 1
        # A rewrite, not the rebuild the word "imágenes" would otherwise buy.
        assert (await _row(row_id)).action == "rewrite"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_video_goes_but_no_render_is_bought_for_refused_words(
    database_url: str,
) -> None:
    """`enqueue_generated` excludes a piece with violations, and `claim_job`
    hands out a queued job without ever reading the piece — so the helper is
    the only place left to say it. The stale video still goes: a video
    contradicting its own text is what every caller came here to remove."""
    from app.services.content_render import requeue_render

    piece_id, _ = await _rejected("CTA missing", with_job=None)
    async with get_bypass_session_factory()() as db:
        piece = await db.get(ContentPiece, piece_id)
        piece.violations = [{"phrase": "safe neighborhood", "category": "fair_housing"}]
        await db.commit()
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                piece = await db.get(ContentPiece, piece_id)
                assert await requeue_render(db, piece) is False
                await db.commit()
        assert (await _piece(piece_id)).media_path is None
        assert await _jobs(piece_id) == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_one_agency_day_does_not_spend_another_agency_s_ceiling(
    database_url: str,
) -> None:
    """The day's ceiling belongs to an agency, not to the installation. Three
    corrections on the demo organisation must not stop this rail working —
    and the counting query has no org filter of its own, so this measures the
    row-level policy rather than a predicate in Python."""
    from datetime import UTC, datetime

    theirs, _ = await _rejected("CTA missing", org_id=2)
    async with get_bypass_session_factory()() as db:
        now = datetime.now(UTC)
        for action in ("rebuild", "rematerialise", "rewrite"):
            db.add(
                ContentRejection(
                    org_id=2,
                    piece_id=theirs,
                    reason="another agency's afternoon",
                    action=action,
                    resolved_at=now,
                )
            )
        await db.commit()
    piece_id, row_id = await _rejected("CTA missing")
    try:
        assert await _sweep() == 1
        assert (await _row(row_id)).action == "rebuild"
        assert (await _piece(piece_id)).status is ContentStatus.DRAFT
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_reason_naming_the_site_does_not_put_the_model_s_url_in_the_caption(
    database_url: str,
) -> None:
    """One of the owner's real rejections carries the domain inside it:
    "There is not call to action at the end , like visit: DenverHomeStory.com
    for". Handed to a model, that produces a caption with a URL the model
    typed — and `_with_cta` then sees a link already there and does NOT append
    the deterministic one. What ships is an address with no scheme, no UTM and,
    on the calculated rail, no seed, so the page opens on an empty form instead
    of on the figure the video just said.
    """
    reason = (
        "There is not call to action at the end , like visit: "
        "DenverHomeStory.com for a free valuation, call 303-555-0199"
    )
    piece_id, row_id = await _rejected(reason, previous=("rebuild",))
    reply = AsyncMock(
        side_effect=[
            _Reply(
                _corrected(
                    caption="See what your home could fetch at "
                    "DenverHomeStory.com or call 303-555-0199 today.",
                )
            ),
            _Reply(_corrected()),
        ]
    )
    try:
        with patch("app.services.content_writer.generate_reply", reply):
            assert await _sweep() == 1
        # Asked again, with the addresses named — not silently cut out of the
        # sentence, which would leave the narrator saying "Start at or call."
        assert reply.await_count == 2
        second = "\n".join(
            str(message["content"]) for message in reply.await_args.args[0]
        )
        assert "DenverHomeStory.com" in second
        assert "303-555-0199" in second
        assert "Never write a web address" in second

        assert (await _row(row_id)).action == "rewrite"
        piece = await _piece(piece_id)
        assert "303-555-0199" not in piece.caption
        # The deterministic link is there, exactly once, appended by `_with_cta`
        # as on any other draft.
        assert piece.caption.lower().count("denverhomestory.com") == 1
        assert "https://www.denverhomestory.com" in piece.caption
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_model_that_keeps_typing_the_address_is_not_published(
    database_url: str,
) -> None:
    """Twice, with the addresses named, and then a person looks. Accepting the
    third version would mean shipping a hand-typed URL in place of ours, and
    asking a fourth time is a bill with no ceiling."""
    piece_id, row_id = await _rejected("CTA missing", previous=("rebuild",))
    stubborn = _Reply(_corrected(caption="Start at www.denverhomestory.com today."))

    async def _always_stubborn(*_args, **_kwargs):
        # A function, not a list of two. A list makes the assertion depend on
        # the call count being exactly what this test predicted, and an
        # exhausted list raises inside the writer's own `except`, which turns a
        # wrong prediction into a different green.
        return stubborn

    reply = AsyncMock(side_effect=_always_stubborn)
    try:
        with patch("app.services.content_writer.generate_reply", reply):
            assert await _sweep() == 1
        # Twice: the draft, and one more with the addresses named. Never three.
        assert reply.await_count == 2
        row = await _row(row_id)
        assert row.action == "rewrite"
        assert "rewrite_failed" in row.finding, row.finding
        # A draft that was dropped replaced nothing.
        assert (await _piece(piece_id)).script == WITHOUT_SIGN_OFF
    finally:
        await _cleanup()


# ── Wired in ─────────────────────────────────────────────────────────────


def _loop_body(name: str) -> ast.AsyncFunctionDef:
    source = Path("app/main.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not in app/main.py any more")


def test_the_sweep_is_actually_called_by_the_loop() -> None:
    """The bell with no rope. This repo has paid for it twice: a detector
    nobody read, and a classifier nobody called."""
    called = set()
    for node in ast.walk(_loop_body("_content_studio_loop")):
        if not isinstance(node, ast.Call):
            continue
        for argument in node.args:
            if isinstance(argument, ast.Name):
                called.add(argument.id)
    assert "correct_rejected" in called
    assert "generate_draft" in called


def _call_order(name: str) -> list[str]:
    """The names passed to a call, in the order the calls are written.

    Over the AST and not over the text, because the function imports both of
    these by name at its top: a text search finds the import first and would
    report the order as correct whatever the calls do. Measured — that is
    exactly what it did.
    """
    order: list[str] = []
    for node in ast.walk(_loop_body(name)):
        if not isinstance(node, ast.Call):
            continue
        for argument in node.args:
            if isinstance(argument, ast.Name):
                order.append((argument.lineno, argument.id))
    return [name for _, name in sorted(order)]


def test_the_corrections_run_before_the_new_drafts() -> None:
    """A rejection is work somebody is waiting on; a new draft is not. And if
    the day's cap is reached by the writer first, the correction still runs."""
    order = _call_order("_content_studio_loop")
    assert "correct_rejected" in order and "generate_draft" in order
    assert order.index("correct_rejected") < order.index("generate_draft")


def test_neither_tick_can_take_the_other_down() -> None:
    """The neighbouring loop learned this the expensive way: one classifier
    failing took its two siblings with it and the rule was dead in production
    while its tests were green."""
    source = ast.unparse(_loop_body("_content_studio_loop"))
    # Each call sits in a Try of its own, so there are at least as many
    # handlers as there are calls.
    node = _loop_body("_content_studio_loop")
    tries = [n for n in ast.walk(node) if isinstance(n, ast.Try)]
    guarded = {
        call.args[0].id
        for try_ in tries
        for call in ast.walk(try_)
        if isinstance(call, ast.Call) and call.args
        and isinstance(call.args[0], ast.Name)
    }
    assert {"correct_rejected", "generate_draft"} <= guarded
    assert len(tries) >= 3, source
