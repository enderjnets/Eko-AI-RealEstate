"""A correction is written from the same verified brief as the first draft.

On 28-sep-2026 Ender's rejections of Decoded 97 and 98 were corrected by the
sweep, and both corrections changed a fact they had no business touching. The
first draft had been written from a brief that said "use only these facts";
the correction was written from the rejected draft and the reviewer's reason,
with no brief at all:

* 98's brief says James W. Denver "visited only twice, in 1875 and 1883". The
  correction said he "returned to Colorado a handful of times".
* 97's brief says the 15th step "is engraved ONE MILE ABOVE SEA LEVEL". The
  correction said "a small stone circle marks the spot".

Nothing stored which topic a growth piece was written from, so the sweep could
not have found the brief if it had looked. Now the writer records it, and for
the Decoded pieces written before it did, the topic is worked out the same way
the writer chose it: one per Decoded since the list of twelve went in.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentRejection,
    ContentSeries,
    ContentStatus,
)
from app.services.content_growth import (
    DECODED_TOPICS_SINCE,
    brief_for,
    growth_source,
    growth_topic,
)
from app.services.tenant_context import org_scope

ORG = 1


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — this reads pieces from Postgres")
    return url


@pytest.fixture(autouse=True)
def _this_is_our_rail(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "CONTENT_ORG_ID", ORG, raising=False)


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


def _decoded(created_at: datetime, source: dict | None = None) -> ContentPiece:
    return ContentPiece(
        org_id=ORG,
        kind=ContentKind.GENERATED,
        language=ContentLanguage.EN,
        status=ContentStatus.REJECTED,
        series=ContentSeries.DENVER_DECODED,
        created_at=created_at,
        source=source,
        hook="A Denver fact",
        script="A Denver fact, told in a few sentences.",
        caption="A caption.",
        scenes={
            "narration": "A Denver fact, told in a few sentences.",
            "scenes": [
                {"visual_prompt": "Denver skyline at dusk", "on_screen_text": "Denver"}
            ],
        },
    )


CAPITOL = growth_topic(ContentSeries.DENVER_DECODED, 0).brief_en
GOVERNOR = growth_topic(ContentSeries.DENVER_DECODED, 1).brief_en
LARIMER = growth_topic(ContentSeries.DENVER_DECODED, 2).brief_en


def test_the_three_briefs_are_the_ones_97_98_and_100_were_written_from() -> None:
    assert "ONE MILE ABOVE SEA LEVEL" in CAPITOL
    assert "1875 and 1883" in GOVERNOR
    assert "Kettle Building" in LARIMER


@pytest.mark.asyncio
async def test_pieces_written_before_the_topic_was_stored_get_it_back(
    database_url: str,
) -> None:
    """The shape of 97, 98 and 100: three Decoded after the list went in, and
    two older ones before it that must not move the count."""
    after = DECODED_TOPICS_SINCE + timedelta(hours=1)
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                older = _decoded(DECODED_TOPICS_SINCE - timedelta(days=1))
                db.add(older)
                await db.commit()
                pieces = []
                for hours in (0, 1, 2):
                    piece = _decoded(after + timedelta(hours=hours))
                    db.add(piece)
                    await db.commit()
                    pieces.append(piece)

                assert await brief_for(db, pieces[0]) == CAPITOL
                assert await brief_for(db, pieces[1]) == GOVERNOR
                assert await brief_for(db, pieces[2]) == LARIMER
                # Written from the old six taste questions: there is no brief
                # to hold it to, and inventing one would be worse.
                assert await brief_for(db, older) is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_stored_topic_wins_over_the_count(database_url: str) -> None:
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                piece = _decoded(
                    datetime.now(UTC),
                    source=growth_source(ContentSeries.DENVER_DECODED, 13),
                )
                db.add(piece)
                await db.commit()
                assert await brief_for(db, piece) == growth_topic(
                    ContentSeries.DENVER_DECODED, 1
                ).brief_en
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_market_piece_is_held_to_its_dmar_report(database_url: str) -> None:
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                piece = _decoded(datetime.now(UTC))
                piece.series = ContentSeries.DENVER_MARKET_NO_HYPE
                piece.source = {
                    "publisher": "DMAR",
                    "title": "DMAR Real Estate Market Trends Report | September 2026",
                    "published_on": date(2026, 9, 3).isoformat(),
                    "url": "https://www.dmarealtors.com/example",
                    "summary": "Inventory rose while closings held steady.",
                }
                db.add(piece)
                await db.commit()
                brief = await brief_for(db, piece)
                assert brief is not None
                assert "Inventory rose while closings held steady." in brief
                assert "2026-09-03" in brief
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_sweep_hands_the_brief_to_the_correction(database_url: str) -> None:
    """Piece 98 exactly: a Decoded, second after the list, no stored topic."""
    from app.services import content_corrections

    seen: dict[str, object] = {}

    async def _spy(*args, **kw):
        seen.update(kw)
        return None

    try:
        with patch("app.services.content_writer._ask_correction", new=_spy):
            with org_scope(ORG):
                async with get_session_factory()() as db:
                    first = _decoded(DECODED_TOPICS_SINCE + timedelta(hours=1))
                    db.add(first)
                    await db.commit()
                    piece = _decoded(DECODED_TOPICS_SINCE + timedelta(hours=2))
                    piece.rejected_reason = "El guion pide calendario y billete."
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
        assert seen.get("brief") == GOVERNOR
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_brief_reaches_the_model_and_outranks_the_draft() -> None:
    """Asserted on the messages, because that is the only thing the model reads."""
    from app.services import content_writer as cw
    from app.services.llm import LLMResult

    sent: list[list[dict]] = []

    async def _fake(messages, **_kw):
        sent.append(messages)
        return LLMResult(text="not json", provider="kimi", model="test",
                         input_tokens=1, output_tokens=1)

    previous = cw.DraftPayload(
        hook="Did you know Denver was named after a governor who had already quit?",
        script="He returned to Colorado a handful of times.",
        caption="A caption.",
        scenes=[{"visual_prompt": "Larimer Street, Denver", "on_screen_text": "Denver"}],
    )
    with patch("app.services.content_writer.generate_reply", new=_fake):
        await cw._ask_correction(
            previous,
            "El guion pide calendario y billete.",
            ContentLanguage.EN,
            series=ContentSeries.DENVER_DECODED,
            brief=GOVERNOR,
        )
    assert sent, "the model was never asked"
    joined = "\n".join(str(m.get("content")) for m in sent[0])
    assert GOVERNOR in joined
    brief_at = joined.index(GOVERNOR)
    draft_at = joined.index("He returned to Colorado a handful of times.")
    assert brief_at < draft_at


@pytest.mark.asyncio
async def test_no_brief_leaves_the_correction_as_it_was() -> None:
    from app.services import content_writer as cw
    from app.services.llm import LLMResult

    sent: list[list[dict]] = []

    async def _fake(messages, **_kw):
        sent.append(messages)
        return LLMResult(text="not json", provider="kimi", model="test",
                         input_tokens=1, output_tokens=1)

    previous = cw.DraftPayload(hook="h", script="s", caption="c", scenes=[])
    with patch("app.services.content_writer.generate_reply", new=_fake):
        await cw._ask_correction(previous, "reason", ContentLanguage.EN)
    joined = "\n".join(str(m.get("content")) for m in sent[0])
    assert "verified brief" not in joined
