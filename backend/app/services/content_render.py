"""Lane A: a phone clip becomes a publishable vertical video, or says why not.

Three stages, in a deliberate order:

1. **Probe.** ffprobe answers what the file actually is. The gate on the input
   is STRUCTURAL only — a video stream exists, the duration is workable, the
   file is not garbage. Nothing here measures how the video looks: the pipeline
   next door taught, at the cost of correct work rejected for the colour of its
   background, that aesthetic gates reject what they do not understand. A
   person approves every piece anyway; the machine checks what a machine can
   know.
2. **Render.** Normalise to 1080×1920 (scale to fit, pad with blurred edges —
   never crop: the agent framed the shot, not us), and burn the brokerage line
   into the last seconds of the video itself. Colorado requires advertising to
   identify the brokerage; burned pixels survive every platform's re-encoding,
   crops and mute buttons, which a caption does not.
3. **Verify.** ffprobe the OUTPUT and require what the render promised:
   1080×1920, an audio track when the source had one, sane duration. A render
   that silently produced something else is a render that failed.

The ffmpeg command is built by a pure function so tests can hold the command
itself — including the brokerage text inside it — without shelling out, and
one integration test actually runs it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AgentSettings, ContentKind, ContentPiece, ContentStatus

log = logging.getLogger(__name__)

# Structural bounds on the INPUT clip. Wide on purpose: a raw phone clip is
# trimmed by a person in review, not refused by a machine at the door.
_MIN_INPUT_SECONDS = 3.0
_MAX_INPUT_SECONDS = 600.0

# How long the burned identification stays on screen at the end.
_END_CARD_SECONDS = 3.0

_RENDER_TIMEOUT_SECONDS = 600

# The image installs fonts-dejavu-core, so the first candidate is the one
# production uses. On a dev Mac none may exist; drawtext then falls back to
# fontconfig's default, which is fine for tests and never for production.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def _font() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None

OUT_W, OUT_H = 1080, 1920


class RenderRefused(Exception):
    """The clip cannot be rendered, with the reason a person needs."""


@dataclass(frozen=True)
class Probe:
    duration: float
    width: int
    height: int
    has_audio: bool


async def _run(*argv: str, timeout_s: float) -> tuple[int, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        raise RenderRefused(
            f"renderer timed out after {int(timeout_s)}s — the clip may be "
            "corrupt or far longer than its header claims"
        ) from None
    return proc.returncode or 0, out


async def probe_media(path: Path) -> Probe:
    code, out = await _run(
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(path),
        timeout_s=60,
    )
    if code != 0:
        raise RenderRefused("the file is not a readable video")
    try:
        data = json.loads(out)
        streams = data["streams"]
        video = next(s for s in streams if s.get("codec_type") == "video")
        duration = float(data["format"]["duration"])
    except (KeyError, StopIteration, ValueError, json.JSONDecodeError):
        raise RenderRefused("the file has no video stream") from None
    return Probe(
        duration=duration,
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def check_input(probe: Probe) -> None:
    """The structural gate. Refusals name the number that failed."""
    if probe.duration < _MIN_INPUT_SECONDS:
        raise RenderRefused(
            f"clip is {probe.duration:.1f}s — under {_MIN_INPUT_SECONDS:.0f}s "
            "there is nothing to publish"
        )
    if probe.duration > _MAX_INPUT_SECONDS:
        raise RenderRefused(
            f"clip is {probe.duration:.0f}s — over {_MAX_INPUT_SECONDS:.0f}s; "
            "trim it to the moment worth keeping first"
        )
    if probe.width <= 0 or probe.height <= 0:
        raise RenderRefused("the video stream reports no dimensions")


def check_output(result: Probe, *, source: Probe | None = None) -> None:
    """What a finished video has to be, before anyone is offered it.

    A function rather than an inline block since v0.66, because there are now
    two producers: this module, and the worker on the render machine. A worker
    on another host is not a trusted source of 1080x1920 — it can be
    misconfigured or half-updated — and the point of the queue is that this
    side does not have to take its word for the result.

    `source` is the input's probe when there is one. Without it (a video
    generated from a script had no input) only the checks that stand on their
    own are applied.
    """
    problems = []
    if (result.width, result.height) != (OUT_W, OUT_H):
        problems.append(f"output is {result.width}x{result.height}")
    if result.duration <= 0:
        problems.append("the output has no duration")
    if source is not None:
        if source.has_audio and not result.has_audio:
            problems.append("the source had audio and the output does not")
        if abs(result.duration - source.duration) > 2.0:
            problems.append(
                f"duration drifted {source.duration:.1f}s -> {result.duration:.1f}s"
            )
    if problems:
        raise RenderRefused("render verification failed: " + "; ".join(problems))


# drawtext's `text=` is a micro-language wrapped in another micro-language: the
# filtergraph parser (which splits on , ; [ ] and handles quotes) runs first,
# then drawtext's own option parser (which splits on :). Escaping operator
# input for both was tried and abandoned. The record, measured against real
# ffmpeg rather than reasoned about:
#
#   * The original `text='...'` with `'` escaped as `\'` broke on the first
#     apostrophe — inside single quotes ffmpeg copies backslashes literally,
#     so "O'Brien Realty" ended the quote and the rest of the graph was
#     re-parsed as filter syntax.
#   * Unquoted with doubled backslashes fixed `'` `:` `%` `\` `"` `&` `$` —
#     and still died on `,` `;` `[` `]`. "Smith & Jones, Realty, Inc." is not
#     an exotic input; it is what a brokerage is called.
#
# Each round of escaping fixed the characters someone thought of and left the
# ones they did not, and the failure is not cosmetic: `render_pending` stamps
# `rendered_at` on a refusal and nothing resets it, so one bad character kills
# every queued clip permanently. `textfile=` removes the language entirely —
# ffmpeg reads the bytes verbatim — leaving only a path we generate ourselves.
_TEXTFILE_NAME = "brokerage.txt"


def _escape_graph_path(path: str) -> str:
    """Escape a path for use as a filter option value.

    Our own temp paths contain none of these, which is exactly why this is
    here: the assumption "the path is safe" is the shape of assumption that
    produced the bug above, and it costs three lines to not make it.
    """
    out = []
    for ch in path:
        if ch in ("\\", ":", "'"):
            out.append("\\\\" + ch)
        elif ch in (",", ";", "[", "]"):
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _font_clause() -> str:
    font = _font()
    return f"fontfile={font}:" if font else ""


def build_render_command(
    source: Path,
    destination: Path,
    *,
    brokerage_file: Path,
    duration: float,
    has_audio: bool,
) -> list[str]:
    """The whole render as data. Pure, so tests can assert on the command.

    `brokerage_file` holds the identification text, written by the caller. It
    is a file rather than a string for the reason recorded above
    `_escape_graph_path`.
    """
    start = max(0.0, duration - _END_CARD_SECONDS)
    textfile = _escape_graph_path(str(brokerage_file))
    # Scale to fit inside 1080×1920, then centre over a blurred, stretched copy
    # of itself — the standard vertical treatment that never crops the shot.
    filter_graph = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},gblur=sigma=20[bgb];"
        f"[fg]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,"
        f"drawtext={_font_clause()}textfile={textfile}:"
        f"fontcolor=white:fontsize=54:box=1:boxcolor=black@0.55:boxborderw=18:"
        f"x=(w-text_w)/2:y=h-260:enable='gte(t,{start:.3f})'"
        f"[vout]"
    )
    argv = [
        "ffmpeg",
        "-y",
        "-i", str(source),
        "-filter_complex", filter_graph,
        "-map", "[vout]",
    ]
    if has_audio:
        argv += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k"]
    argv += [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(destination),
    ]
    return argv


async def render_clip(
    source: Path, destination: Path, *, brokerage_line: str
) -> Probe:
    """Probe → gate → render → verify. Returns the OUTPUT's probe."""
    probe = await probe_media(source)
    check_input(probe)

    # Beside the output, so it inherits the same writable directory, and
    # removed in `finally` — ffmpeg reads it at filter init, not per frame.
    brokerage_file = destination.parent / f"{destination.stem}.{_TEXTFILE_NAME}"
    argv = build_render_command(
        source,
        destination,
        brokerage_file=brokerage_file,
        duration=probe.duration,
        has_audio=probe.has_audio,
    )
    try:
        await asyncio.to_thread(
            brokerage_file.write_text, brokerage_line, encoding="utf-8"
        )
        code, out = await _run(*argv, timeout_s=_RENDER_TIMEOUT_SECONDS)
    finally:
        await asyncio.to_thread(brokerage_file.unlink, missing_ok=True)
    if code != 0:
        await asyncio.to_thread(destination.unlink, missing_ok=True)
        tail = out[-400:].decode(errors="replace")
        raise RenderRefused(f"ffmpeg failed ({code}): {tail}")

    # The render's own promises, checked against the file that exists rather
    # than the command that ran. "It returned 0" is not verification.
    result = await probe_media(destination)
    try:
        check_output(result, source=probe)
    except RenderRefused:
        await asyncio.to_thread(destination.unlink, missing_ok=True)
        raise
    return result


def _for_the_console(reason: str) -> str:
    """What a realtor is told, as opposed to what the log records.

    ffmpeg's stderr tail carries absolute container paths — the media volume,
    the temp file the drawtext filter reads — and `render_error` is shown in
    the console to any signed-in user, including a `viewer`. The messages this
    module writes itself are already written for a person and pass through; a
    transport's own words do not. The log keeps everything.
    """
    if reason.startswith("ffmpeg failed"):
        return "the video tool could not process this clip; see server log"
    return reason


async def render_pending(db: AsyncSession) -> int:
    """Render every recorded clip that has not been tried yet. Returns count.

    Runs per organisation under RLS via `run_for_every_org`, like every other
    worker here. One at a time — ffmpeg saturates the cores it gets, and two
    renders in parallel on this box is one render at half speed twice.
    """
    settings_row = (
        await db.execute(select(AgentSettings))
    ).scalars().first()
    brokerage = (
        (settings_row.brokerage_line or "").strip() if settings_row else ""
    )

    rows = (
        (
            await db.execute(
                select(ContentPiece).where(
                    ContentPiece.kind == ContentKind.RECORDED,
                    ContentPiece.media_path.is_not(None),
                    ContentPiece.rendered_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    if not brokerage:
        # Without the identification there is nothing legal to burn, so
        # rendering now would only have to be done again. The clips wait, the
        # reason is visible on each row, and nothing is marked tried.
        for piece in rows:
            if piece.render_error != _NO_BROKERAGE_NOTE:
                piece.render_error = _NO_BROKERAGE_NOTE
        await db.commit()
        return 0

    if get_settings().RENDER_WORKER_ENABLED:
        # The work goes to the machine with the media stack. This path adds
        # subtitles, which is why it exists: transcription needs a speech model
        # that has no business living in the API container.
        #
        # The local path below is NOT deleted and is not dead code — it is the
        # fallback for an install with no worker, and the thing to switch back
        # to when the render machine is down.
        return await _enqueue_pending(db, rows)

    media_root = Path(get_settings().CONTENT_MEDIA_DIR)
    done = 0
    for piece in rows:
        source = media_root / piece.media_path
        destination = media_root / f"{uuid.uuid4().hex}.mp4"
        try:
            if not source.is_file():
                raise RenderRefused("the uploaded file is missing from the volume")
            await render_clip(
                source, destination, brokerage_line=brokerage
            )
        except RenderRefused as exc:
            piece.rendered_at = datetime.now(UTC)
            piece.render_error = _for_the_console(str(exc))
            # The full reason, ffmpeg's own words included, goes here and only
            # here. The column is read by the console (v0.55) and therefore by
            # every signed-in member and viewer.
            log.warning("Render refused for piece %d: %s", piece.id, exc)
        except Exception:  # noqa: BLE001 — one bad clip must not stop the rest
            destination.unlink(missing_ok=True)
            log.exception("Render crashed for piece %d", piece.id)
            piece.rendered_at = datetime.now(UTC)
            piece.render_error = "renderer crashed; see server log"
        else:
            old = source
            piece.media_path = destination.name
            piece.rendered_at = datetime.now(UTC)
            piece.render_error = None
            done += 1
            # The original is deleted only after the new path is committed;
            # a crash between the two leaves an orphan file, never a piece
            # pointing at nothing.
            await db.commit()
            old.unlink(missing_ok=True)
            continue
        await db.commit()
    return done


_NO_BROKERAGE_NOTE = (
    "waiting: no brokerage line on record — set it in Settings and the clip "
    "renders on the next pass"
)


async def enqueue_generated(db: AsyncSession) -> int:
    """Queue lane B for every generated piece that has a plan and no video.

    The order here is the product decision, not an implementation detail: the
    video is built BEFORE a person approves, so what they approve is the video
    and not a description of one. Approving text and publishing whatever came
    out of it would put the human gate in front of the wrong artefact.

    A generated piece that is clean already sits in NEEDS_APPROVAL; the render
    attaches its file and leaves the status alone. One that carries violations
    stays a DRAFT and is skipped — there is no point spending a narration and
    six images on text a person still has to rewrite.
    """
    from app.models import RenderJobKind

    if not get_settings().RENDER_WORKER_ENABLED:
        return 0

    rows = (
        (
            await db.execute(
                select(ContentPiece).where(
                    ContentPiece.kind == ContentKind.GENERATED,
                    ContentPiece.scenes.is_not(None),
                    ContentPiece.media_path.is_(None),
                    ContentPiece.violations.is_(None),
                    ContentPiece.status.in_(
                        (ContentStatus.DRAFT, ContentStatus.NEEDS_APPROVAL)
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    return await _enqueue(db, rows, RenderJobKind.PRODUCE_B) if rows else 0


async def _enqueue_pending(db: AsyncSession, pieces: list[ContentPiece]) -> int:
    """Hand these clips to the render worker instead of rendering them here.

    Idempotent by constraint, not by care: `uq_render_job` on
    `(piece_id, kind)` means a second tick over the same clip collides rather
    than queueing it twice, so a restart between the query and the commit
    cannot double the work.

    `rendered_at` is deliberately NOT stamped. It means "this clip has been
    dealt with", and a queued job has not been — stamping it here would hide
    the clip from this sweep forever if the worker never came back.
    """
    from app.models import RenderJobKind

    return await _enqueue(db, pieces, RenderJobKind.SUBTITLE_A)


# How long a job that gave up waits before anybody tries again. A worker with
# a full disk burns three attempts in the minutes it takes to poll three times,
# and without this the clip could NEVER be rendered again — not after the disk
# was cleared, not ever — because nothing re-queues a FAILED row and the only
# recovery was to upload the same clip a second time, which nothing told the
# operator. A day, so a permanent fault retries once a day instead of forever.
FAILED_JOB_COOLDOWN = timedelta(hours=24)


async def _enqueue(db: AsyncSession, pieces: list, kind) -> int:
    """One job per piece, at most once at a time.

    Idempotent by CONSTRAINT and not by care: `uq_render_job` on
    `(piece_id, kind)` means a second tick collides instead of queueing twice,
    so a restart between the query and the commit cannot double the work — or
    the money, for a lane that pays per image.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models import RenderJob, RenderJobStatus

    queued = 0
    for piece in pieces:
        existing = (
            await db.execute(
                select(RenderJob).where(
                    RenderJob.piece_id == piece.id, RenderJob.kind == kind
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            stale_failure = (
                existing.status is RenderJobStatus.FAILED
                and existing.updated_at is not None
                and datetime.now(UTC) - existing.updated_at > FAILED_JOB_COOLDOWN
            )
            if stale_failure:
                existing.status = RenderJobStatus.QUEUED
                existing.attempts = 0
                existing.worker = None
                existing.claimed_at = None
                await db.commit()
                queued += 1
            continue
        db.add(RenderJob(piece_id=piece.id, kind=kind))
        try:
            await db.commit()
        except IntegrityError:
            # Another tick got there first. Not an error, and not a reason to
            # abandon the rest of the batch.
            await db.rollback()
            continue
        queued += 1
    if queued:
        log.info("Queued %d %s job(s) for the render worker", queued, kind.value)
    return queued
