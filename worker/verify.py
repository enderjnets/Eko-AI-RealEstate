"""What a finished video has to be before it is handed back.

The panel checks this too, and that is not redundancy — it is the boundary.
This side catches a bad render before spending an upload on it; that side
refuses to take a worker's word for the result. Neither can be removed.

`brand_is_present` is the one check that cannot be done by reading numbers off
ffprobe: it renders a frame and compares it against the mark that was supposed
to be burned into it. The reason it exists is a video that shipped with the
wrong brand's watermark next door and passed every gate, because the gates
measured contrast and not identity.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

OUT_W, OUT_H = 1080, 1920
# Named rather than a default buried in a signature: the tests assert against
# the same number the worker enforces, and a threshold a test spells out for
# itself is a threshold that can drift away from the one in production.
BRAND_THRESHOLD = 0.80


class Rejected(Exception):
    """The output is not what it had to be, with the reason."""


@dataclass(frozen=True)
class Probe:
    duration: float
    width: int
    height: int
    has_audio: bool


def probe(path: Path) -> Probe:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ],
        capture_output=True,
        timeout=120,
    )
    if out.returncode != 0:
        raise Rejected("the file is not a readable video")
    try:
        data = json.loads(out.stdout)
        streams = data["streams"]
        video = next(s for s in streams if s.get("codec_type") == "video")
        duration = float(data["format"]["duration"])
    except (KeyError, StopIteration, ValueError, json.JSONDecodeError):
        raise Rejected("the file has no video stream") from None
    return Probe(
        duration=duration,
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def check(path: Path, *, expect_audio: bool, max_seconds: float | None = None) -> Probe:
    result = probe(path)
    problems = []
    if (result.width, result.height) != (OUT_W, OUT_H):
        problems.append(f"output is {result.width}x{result.height}")
    if result.duration <= 0:
        problems.append("the output has no duration")
    if expect_audio and not result.has_audio:
        problems.append("the output has no audio track")
    if max_seconds is not None and result.duration > max_seconds:
        problems.append(f"output is {result.duration:.0f}s, over {max_seconds:.0f}s")
    if problems:
        raise Rejected("; ".join(problems))
    return result


def _grab_frame(video: Path, at_seconds: float, destination: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{at_seconds:.2f}", "-i", str(video),
            "-frames:v", "1", str(destination),
        ],
        capture_output=True,
        timeout=120,
        check=True,
    )


def brand_is_present(
    video: Path,
    mark: Path,
    workdir: Path,
    *,
    threshold: float = BRAND_THRESHOLD,
    mark_width: int = 190,
    margin: int = 44,
) -> float:
    """Is our mark actually in the frame? Correlation, or Rejected.

    Looking at pixels rather than at the command that produced them, because
    the failure this guards against is precisely a render that ran happily and
    composited the wrong image, or none at all. Next door a video shipped with
    another brand's watermark and passed every gate, because the gates measured
    contrast rather than identity.

    The crop is the EXACT rectangle `assemble.build_command` composites into —
    same width, same margin, height derived from the mark's own aspect ratio.

    **Only the pixels the mark's alpha says were drawn are compared**, and that
    is the whole correction. `overlay` draws the mark where its alpha allows and
    leaves the photograph everywhere else; this file's own mark is 47.9%
    fully transparent with black underneath it. Reading the reference through
    `convert("L")` throws the alpha away, so half of what was being correlated
    was black pixels that ffmpeg never puts on screen — against the PICTURE. A
    dark photograph agreed with them and scored 0.892; a pale one disagreed and
    scored 0.014, and a correct video was refused three times in seventy-one
    seconds while the console showed a spinner.

    Measured on the six renders this installation has delivered: the old
    reading ranged 0.170 to 0.892 with the mark identically present in all six;
    masked, the same six give 0.981 to 0.994. The same crop taken from the
    OPPOSITE corner — real picture, no mark — reaches 0.647, which is why the
    threshold is 0.80 and not the old 0.15: with the mask, 0.15 would accept a
    frame with no mark in it at all. The number sits between the two measured
    populations, not where it looks comfortable.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a soft dependency
        # Said out loud rather than skipped. A check that quietly returns
        # "fine" when it could not run is worse than no check at all.
        raise Rejected(
            "cannot verify the watermark: Pillow is not installed on this worker"
        ) from None

    frame_path = workdir / "brandcheck.png"
    _grab_frame(video, 1.0, frame_path)
    try:
        frame = Image.open(frame_path).convert("L")
        reference = Image.open(mark)

        scale = mark_width / reference.width
        mark_h = max(1, round(reference.height * scale))
        drawn = reference.resize((mark_width, mark_h))
        w, _h = frame.size
        left = w - margin - mark_width
        box = frame.crop((left, margin, left + mark_width, margin + mark_h))

        # A mark with no alpha channel is opaque everywhere. Not a special
        # case to tolerate: it is what a client uploading a JPEG logo would
        # give us, and `getchannel("A")` on it raises.
        if "A" in drawn.getbands():
            alpha = list(drawn.getchannel("A").getdata())
        else:
            alpha = [255] * (mark_width * mark_h)
        # 128 rather than 0: ffmpeg and Pillow resample the mark's edges
        # differently, so the half-covered pixels of an outline are the one
        # place the two disagree. Comparing only the solidly drawn interior
        # costs nothing — there are thousands of those pixels.
        wanted = [i for i, value in enumerate(alpha) if value > 128]
        if not wanted:
            raise Rejected(
                "the brand mark image is fully transparent; there is nothing "
                "in it to draw"
            )

        reference_pixels = list(drawn.convert("L").getdata())
        frame_pixels = list(box.getdata())
        a = [frame_pixels[i] for i in wanted]
        b = [reference_pixels[i] for i in wanted]

        mean_a = sum(a) / len(a)
        mean_b = sum(b) / len(b)
        var_a = sum((x - mean_a) ** 2 for x in a) ** 0.5
        var_b = sum((y - mean_b) ** 2 for y in b) ** 0.5
        if var_b == 0:
            # A mark with no variation cannot be correlated with anything.
            # Named rather than reported as a low score, because the fix is to
            # the asset and not to the render.
            raise Rejected(
                "the brand mark image is a flat colour; there is nothing in it "
                "to recognise"
            )
        if var_a == 0:
            raise Rejected("that corner of the frame is blank — no mark was drawn")
        cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True))
        correlation = cov / (var_a * var_b)
    finally:
        frame_path.unlink(missing_ok=True)

    if correlation < threshold:
        raise Rejected(
            f"the brand mark is not in the frame (correlation {correlation:.3f} "
            f"< {threshold})"
        )
    return correlation
