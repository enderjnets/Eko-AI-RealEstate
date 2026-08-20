"""Lane A: the render's promises, held both as data and against real files.

The command builder is pure, so its tests read the command itself — including
the brokerage text burned into the filter graph. The integration tests run
actual ffmpeg on clips generated on the spot, because "the command looked
right" and "the file that came out is 1080×1920 with its audio intact" are
different claims and only the second one is the product.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    AgentSettings,
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentStatus,
)
from app.services.content_render import (
    OUT_H,
    OUT_W,
    Probe,
    RenderRefused,
    _escape_drawtext,
    build_render_command,
    check_input,
    probe_media,
    render_clip,
    render_pending,
)
from app.services.tenant_context import org_scope

FFMPEG = shutil.which("ffmpeg")

BROKERAGE = "Natalia & Robbie · Engel & Völkers"


# --------------------------------------------------------------------------
# The command as data
# --------------------------------------------------------------------------


def test_the_brokerage_line_is_in_the_command() -> None:
    """The burn is the point of the render. A command without the text is a
    resize, and a resize satisfies every structural check."""
    argv = build_render_command(
        Path("in.mp4"),
        Path("out.mp4"),
        brokerage_line=BROKERAGE,
        duration=30.0,
        has_audio=True,
    )
    graph = argv[argv.index("-filter_complex") + 1]
    assert "drawtext=" in graph
    assert "Natalia & Robbie" in graph
    assert f"scale={OUT_W}:{OUT_H}" in graph


def test_audio_is_mapped_only_when_the_source_has_it() -> None:
    with_audio = build_render_command(
        Path("a.mp4"), Path("b.mp4"),
        brokerage_line=BROKERAGE, duration=10.0, has_audio=True,
    )
    silent = build_render_command(
        Path("a.mp4"), Path("b.mp4"),
        brokerage_line=BROKERAGE, duration=10.0, has_audio=False,
    )
    assert "0:a:0" in with_audio
    assert "0:a:0" not in silent, (
        "mapping audio from a silent source makes ffmpeg fail the whole render"
    )


def test_drawtext_syntax_in_the_line_is_defused() -> None:
    """The brokerage line is operator input; drawtext treats : ' % \\ as
    syntax. 'Natalia: 100%' must render as text, not parse as filter."""
    escaped = _escape_drawtext("Natalia: 100% 'the' \\ best")
    assert "\\:" in escaped and "\\%" in escaped and "\\'" in escaped
    assert "\\\\" in escaped
    assert "\n" not in _escape_drawtext("two\nlines")


def test_the_structural_gate_names_the_number_that_failed() -> None:
    with pytest.raises(RenderRefused, match="nothing to publish"):
        check_input(Probe(duration=1.0, width=1920, height=1080, has_audio=True))
    with pytest.raises(RenderRefused, match="trim it"):
        check_input(Probe(duration=4000.0, width=1920, height=1080, has_audio=True))
    with pytest.raises(RenderRefused, match="dimensions"):
        check_input(Probe(duration=30.0, width=0, height=0, has_audio=True))
    check_input(Probe(duration=30.0, width=1920, height=1080, has_audio=False))


# --------------------------------------------------------------------------
# Real files through real ffmpeg
# --------------------------------------------------------------------------


def _make_clip(path: Path, *, seconds: float = 4.0, with_audio: bool = True) -> None:
    inputs = ["-f", "lavfi", "-i", f"testsrc2=size=640x480:rate=24:duration={seconds}"]
    if with_audio:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    subprocess.run(
        ["ffmpeg", "-y", *inputs, "-c:v", "libx264", "-pix_fmt", "yuv420p",
         *(['-c:a', 'aac'] if with_audio else []), "-shortest", str(path)],
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed on this machine")
@pytest.mark.asyncio
async def test_a_real_clip_comes_out_vertical_with_its_audio(tmp_path) -> None:
    source = tmp_path / "phone.mp4"
    _make_clip(source, seconds=4.0, with_audio=True)
    out = tmp_path / "rendered.mp4"

    result = await render_clip(source, out, brokerage_line=BROKERAGE)

    assert (result.width, result.height) == (OUT_W, OUT_H)
    assert result.has_audio, "the source's audio was lost in the render"
    assert abs(result.duration - 4.0) < 1.5
    assert out.stat().st_size > 10_000


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed on this machine")
@pytest.mark.asyncio
async def test_a_silent_clip_renders_without_inventing_audio(tmp_path) -> None:
    source = tmp_path / "silent.mp4"
    _make_clip(source, seconds=4.0, with_audio=False)
    out = tmp_path / "rendered.mp4"

    result = await render_clip(source, out, brokerage_line=BROKERAGE)
    assert (result.width, result.height) == (OUT_W, OUT_H)
    assert not result.has_audio


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed on this machine")
@pytest.mark.asyncio
async def test_garbage_is_refused_with_a_reason_not_a_crash(tmp_path) -> None:
    fake = tmp_path / "not_video.mp4"
    fake.write_bytes(b"this is a text file wearing an mp4 suffix" * 100)
    with pytest.raises(RenderRefused, match="not a readable video|no video stream"):
        await probe_media(fake)


# --------------------------------------------------------------------------
# The worker against the database
# --------------------------------------------------------------------------


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — render worker tests need live Postgres")
    return url


async def _brokerage(line: str | None) -> None:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(select(AgentSettings).where(AgentSettings.org_id == 1))
        ).scalar_one_or_none()
        if row is None:
            row = AgentSettings(org_id=1)
            db.add(row)
        row.brokerage_line = line
        await db.commit()


async def _seed_piece(media_name: str) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=1,
            kind=ContentKind.RECORDED,
            language=ContentLanguage.EN,
            status=ContentStatus.DRAFT,
            media_path=media_name,
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _piece(piece_id: int) -> ContentPiece:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(select(ContentPiece).where(ContentPiece.id == piece_id))
        ).scalar_one()


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_pieces WHERE org_id = 1"))
        await db.commit()


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed on this machine")
@pytest.mark.asyncio
async def test_the_worker_renders_marks_and_swaps(
    database_url: str, tmp_path, monkeypatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "CONTENT_MEDIA_DIR", str(tmp_path))
    await _brokerage(BROKERAGE)
    source_name = "raw_clip.mp4"
    _make_clip(tmp_path / source_name, seconds=4.0)
    piece_id = await _seed_piece(source_name)
    try:
        with org_scope(1):
            async with get_session_factory()() as db:
                done = await render_pending(db)
        assert done == 1

        row = await _piece(piece_id)
        assert row.rendered_at is not None
        assert row.render_error is None
        assert row.media_path != source_name, "the piece still points at the raw clip"
        rendered = tmp_path / row.media_path
        assert rendered.is_file()
        assert not (tmp_path / source_name).exists(), (
            "the raw original was left on the volume for ever"
        )

        probe = await probe_media(rendered)
        assert (probe.width, probe.height) == (OUT_W, OUT_H)

        # A second pass finds nothing to do — rendered_at is the memory.
        with org_scope(1):
            async with get_session_factory()() as db:
                assert await render_pending(db) == 0
    finally:
        await _cleanup()


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed on this machine")
@pytest.mark.asyncio
async def test_a_bad_clip_fails_visibly_and_does_not_block_the_good_one(
    database_url: str, tmp_path, monkeypatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "CONTENT_MEDIA_DIR", str(tmp_path))
    await _brokerage(BROKERAGE)
    (tmp_path / "garbage.mp4").write_bytes(b"not a video" * 1000)
    _make_clip(tmp_path / "good.mp4", seconds=4.0)
    bad_id = await _seed_piece("garbage.mp4")
    good_id = await _seed_piece("good.mp4")
    try:
        with org_scope(1):
            async with get_session_factory()() as db:
                done = await render_pending(db)
        assert done == 1, "the bad clip stopped the good one"

        bad = await _piece(bad_id)
        assert bad.rendered_at is not None
        assert bad.render_error, "the failure has to be visible on the row"
        good = await _piece(good_id)
        assert good.render_error is None
        assert good.rendered_at is not None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_without_a_brokerage_line_clips_wait_and_say_why(
    database_url: str, tmp_path, monkeypatch
) -> None:
    """Rendering without the identification would only have to be done again,
    and a silent queue is how work disappears. The clip waits, the reason sits
    on the row, and rendered_at stays NULL so the next pass retries."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "CONTENT_MEDIA_DIR", str(tmp_path))
    await _brokerage(None)
    (tmp_path / "waiting.mp4").write_bytes(b"placeholder")
    piece_id = await _seed_piece("waiting.mp4")
    try:
        with org_scope(1):
            async with get_session_factory()() as db:
                assert await render_pending(db) == 0
        row = await _piece(piece_id)
        assert row.rendered_at is None, "marked tried without being tried"
        assert row.render_error and "brokerage" in row.render_error
    finally:
        await _cleanup()
        await _brokerage(BROKERAGE)
