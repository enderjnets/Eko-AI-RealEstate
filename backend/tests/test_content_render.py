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
    _escape_graph_path,
    _for_the_console,
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
        brokerage_file=Path("/tmp/x.brokerage.txt"),
        duration=30.0,
        has_audio=True,
    )
    graph = argv[argv.index("-filter_complex") + 1]
    assert "drawtext=" in graph
    assert "textfile=/tmp/x.brokerage.txt" in graph
    assert f"scale={OUT_W}:{OUT_H}" in graph


def test_audio_is_mapped_only_when_the_source_has_it() -> None:
    with_audio = build_render_command(
        Path("a.mp4"), Path("b.mp4"),
        brokerage_file=Path("/tmp/x.txt"), duration=10.0, has_audio=True,
    )
    silent = build_render_command(
        Path("a.mp4"), Path("b.mp4"),
        brokerage_file=Path("/tmp/x.txt"), duration=10.0, has_audio=False,
    )
    assert "0:a:0" in with_audio
    assert "0:a:0" not in silent, (
        "mapping audio from a silent source makes ffmpeg fail the whole render"
    )


def test_the_operator_text_never_enters_the_filter_language() -> None:
    """The brokerage line goes in a file, not in the graph, and that is the
    whole defence.

    The version this replaces escaped the text into `text='...'` and asserted
    on the SHAPE of the escaping — it asserted `\\'` was produced, which is
    exactly the encoding that broke: inside single quotes ffmpeg copies
    backslashes literally, so "O'Brien Realty" ended the quote and the graph
    was re-parsed as filter syntax. The test passed while the feature was
    broken because no test ever sent an apostrophe through real ffmpeg.
    """
    hostile = "O'Brien, [E&V]; 100%: \\ best"
    argv = build_render_command(
        Path("in.mp4"), Path("out.mp4"),
        brokerage_file=Path("/tmp/x.txt"), duration=30.0, has_audio=False,
    )
    graph = argv[argv.index("-filter_complex") + 1]
    assert hostile not in graph
    # Precisely `text=` as a drawtext option — `textfile=` and `text_w` both
    # contain those five characters and are not the thing being ruled out.
    assert ":text=" not in graph and "drawtext=text=" not in graph, (
        "the text= option is the one that could not be escaped safely"
    )
    assert "textfile=" in graph


def test_a_path_with_filter_syntax_in_it_is_escaped() -> None:
    """We generate the path, so it is safe — which is the assumption that
    produced the bug this module already paid for. Escape it anyway."""
    assert _escape_graph_path("/tmp/a:b") == "/tmp/a\\\\:b"
    assert _escape_graph_path("/tmp/a,b") == "/tmp/a\\,b"


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


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed on this machine")
@pytest.mark.parametrize(
    "brokerage",
    [
        "O'Brien Realty Group",              # the apostrophe that broke it
        "Smith & Jones, Realty, Inc.",       # commas: what a brokerage is called
        "A; B Realty",
        "[E&V] Denver",
        "Realty: 100% Denver \\ CO",
        "X',drawtext=textfile=/etc/passwd,drawtext=text='",
        "Natalia & Robbie · Engel & Völkers Aspen",
    ],
)
@pytest.mark.asyncio
async def test_a_hostile_brokerage_line_still_renders(tmp_path, brokerage: str) -> None:
    """Real ffmpeg, real characters. This is the test that was missing.

    Its predecessor asserted the escaper's output shape and passed while an
    apostrophe made ffmpeg exit non-zero — and a refused render stamps
    `rendered_at`, which nothing resets, so every queued clip died permanently.
    Brokerage names contain apostrophes and commas; refusing them is not an
    option, and asserting on a string instead of on ffmpeg is how that went
    unnoticed. Anything that reintroduces a filter micro-language for operator
    input turns this red.
    """
    source = tmp_path / "phone.mp4"
    _make_clip(source, seconds=4.0, with_audio=False)
    out = tmp_path / "rendered.mp4"

    result = await render_clip(source, out, brokerage_line=brokerage)

    assert (result.width, result.height) == (OUT_W, OUT_H)
    assert not list(tmp_path.glob("*.brokerage.txt")), (
        "the text file outlived the render"
    )


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed on this machine")
@pytest.mark.asyncio
async def test_the_brokerage_text_actually_reaches_the_pixels(tmp_path) -> None:
    """Two different lines must produce two different end cards.

    Without this, "it rendered" covers "it rendered nothing": a regression that
    silently passes an empty string still exits 0, still produces 1080x1920,
    and still satisfies every other check here — while shipping a video with no
    brokerage identification on it, which is the one thing Colorado requires.
    Found by mutating the module: the old `text='...'` form drew an empty
    string and every structural assertion stayed green.
    """
    source = tmp_path / "phone.mp4"
    _make_clip(source, seconds=4.0, with_audio=False)

    def end_card(video: Path, png: Path) -> bytes:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "3.5", "-i", str(video), "-frames:v", "1", str(png)],
            check=True, capture_output=True,
        )
        return png.read_bytes()

    first = tmp_path / "one.mp4"
    await render_clip(source, first, brokerage_line="O'Brien Realty Group")
    second = tmp_path / "two.mp4"
    await render_clip(source, second, brokerage_line="Smith & Jones, Realty, Inc.")

    assert end_card(first, tmp_path / "a.png") != end_card(second, tmp_path / "b.png"), (
        "both end cards are identical — the brokerage text is not being drawn"
    )


def test_the_console_never_sees_ffmpeg_s_own_words() -> None:
    """`render_error` is shown to every signed-in user since v0.55.

    ffmpeg's stderr tail names absolute container paths — the media volume and
    the temp file drawtext reads. Making the field visible is what turned that
    from a column nobody read into disclosure, so the transport's words stop at
    the log. Messages this module writes for a person pass through unchanged.
    """
    leaky = (
        "ffmpeg failed (1): [AVFilterGraph] Unable to open "
        "/data/media/tmp/9f3.brokerage.txt: No such file"
    )
    shown = _for_the_console(leaky)
    assert "/data/media" not in shown
    assert "brokerage.txt" not in shown
    assert "server log" in shown

    for ours in (
        "the uploaded file is missing from the volume",
        "waiting: no brokerage line on record",
        "render verification failed: output is 640x480",
    ):
        assert _for_the_console(ours) == ours
