"""Deterministic Denver Home Story finishing after BitTrader returns an MP4."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from worker import verify

MIN_SECONDS = 20.0
MAX_SECONDS = 35.0
END_CARD_SECONDS = 3.0
OPENING_SECONDS = 2.8
MAX_NARRATION_WORDS = 75
MIN_SCENES = 7
MAX_SCENES = 9

# Legacy jobs carry no contract and retain the conversion bounds. New jobs get
# this block from the authenticated panel after their persisted series has
# already been chosen. The worker still bounds every value before using it.
_LEGACY_CONTRACT = {
    "series": "conversion",
    "duration_min": MIN_SECONDS,
    "duration_max": MAX_SECONDS,
    "word_max": MAX_NARRATION_WORDS,
    "scene_min": MIN_SCENES,
    "scene_max": MAX_SCENES,
}

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
_CHROMIUM_CANDIDATES = (
    "/snap/bin/chromium",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


@dataclass(frozen=True)
class FinishReport:
    duration: float
    used_calculator: bool


def default_font() -> str | None:
    return next((candidate for candidate in _FONT_CANDIDATES if Path(candidate).is_file()), None)


def _normalized_prompt(value: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split())


def authorized_calculator_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {
        "denverhomestory.com", "www.denverhomestory.com"
    }:
        return False
    if parsed.path.rstrip("/") != "/calculator":
        return False
    query = parse_qs(parsed.query)
    return bool(query.get("rent", [""])[0] and query.get("savings", [""])[0])


def opening_copy(value: object) -> str:
    """Two short lines that fit inside the 840 px opening safe area."""
    return "\n".join(
        textwrap.wrap(
            " ".join(str(value or "").split()),
            width=22,
            max_lines=2,
            placeholder="…",
        )
    )


def display_copy(value: object) -> str:
    """A readable DHS address, with the path on its own centered line."""
    display = " ".join(str(value or "").strip().split())
    display = re.sub(r"^https?://", "", display, flags=re.IGNORECASE).rstrip("/")
    if display.casefold().startswith("denverhomestory.com"):
        display = f"www.{display}"
    host, separator, path = display.partition("/")
    return f"{host}\n/{path}" if separator and path else host


def brokerage_copy(value: object) -> str:
    """Keep the legal identification centered instead of clipping its ends."""
    return "\n".join(
        textwrap.wrap(" ".join(str(value or "").split()), width=38, max_lines=2)
    )


def _contract(spec: dict) -> dict[str, int | float | str]:
    finish = spec.get("finish") if isinstance(spec.get("finish"), dict) else {}
    raw = finish.get("contract") if isinstance(finish.get("contract"), dict) else {}
    contract = {**_LEGACY_CONTRACT, **raw}
    try:
        duration_min = float(contract["duration_min"])
        duration_max = float(contract["duration_max"])
        word_max = int(contract["word_max"])
        scene_min = int(contract["scene_min"])
        scene_max = int(contract["scene_max"])
    except (TypeError, ValueError, KeyError) as exc:
        raise verify.Rejected("the finishing contract is malformed") from exc
    if not 5 <= duration_min < duration_max <= 90:
        raise verify.Rejected("the finishing duration contract is outside safe bounds")
    if not 1 <= scene_min <= scene_max <= 12:
        raise verify.Rejected("the finishing scene contract is outside safe bounds")
    if not 10 <= word_max <= 100:
        raise verify.Rejected("the finishing narration contract is outside safe bounds")
    return {
        "series": str(contract.get("series") or "conversion"),
        "duration_min": duration_min,
        "duration_max": duration_max,
        "word_max": word_max,
        "scene_min": scene_min,
        "scene_max": scene_max,
    }


def duration_bounds(spec: dict) -> tuple[float, float]:
    contract = _contract(spec)
    return float(contract["duration_min"]), float(contract["duration_max"])


def validate(spec: dict) -> None:
    """Refuse jobs whose stored plan cannot produce the approved format."""
    finish = spec.get("finish") if isinstance(spec.get("finish"), dict) else {}
    required = ("opening_text", "cta_label", "cta_display")
    missing = [name for name in required if not str(finish.get(name) or "").strip()]
    if missing:
        raise verify.Rejected("finishing text is missing: " + ", ".join(missing))
    if not str(spec.get("brokerage_line") or "").strip():
        raise verify.Rejected("the organisation has no brokerage line on record")

    contract = _contract(spec)
    plan = spec.get("scenes") if isinstance(spec.get("scenes"), dict) else {}
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    scene_min = int(contract["scene_min"])
    scene_max = int(contract["scene_max"])
    if not scene_min <= len(scenes) <= scene_max:
        raise verify.Rejected(
            f"the shot plan has {len(scenes)} scenes; it requires "
            f"{scene_min} to {scene_max}"
        )
    prompts = [
        _normalized_prompt(row.get("visual_prompt"))
        for row in scenes
        if isinstance(row, dict)
    ]
    if len(prompts) != len(scenes) or any(not prompt for prompt in prompts):
        raise verify.Rejected("every scene needs a visual prompt")
    if len(set(prompts)) != len(prompts):
        raise verify.Rejected("the shot plan repeats a visual prompt")

    narration = str(plan.get("narration") or spec.get("script") or "")
    word_count = len(narration.split())
    word_max = int(contract["word_max"])
    if word_count > word_max:
        raise verify.Rejected(
            f"the finished narration is {word_count} words; the limit is "
            f"{word_max} words"
        )
    if finish.get("cta_label") == "RUN YOUR NUMBERS" and not authorized_calculator_url(
        finish.get("calculator_url")
    ):
        raise verify.Rejected("a calculated piece needs a seeded calculator URL")


def escape_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def build_command(
    source: Path,
    destination: Path,
    *,
    duration: float,
    background: Path,
    opening_files: list[Path],
    cta_label_file: Path,
    cta_display_files: list[Path],
    brokerage_files: list[Path],
    font: str | None,
    mark: Path | None,
) -> list[str]:
    """Build ffmpeg argv; all audience-facing copy enters through text files."""
    font_clause = f":fontfile='{escape_path(font)}'" if font else ""
    end_at = max(0.0, duration - END_CARD_SECONDS)
    parts = [
        (
            "[1:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,setsar=1,format=rgba,"
            "drawbox=x=0:y=0:w=iw:h=ih:color=0x0B1F33@0.78:t=fill[card0]"
        ),
        (
            f"[card0]drawtext=textfile='{escape_path(str(cta_label_file))}'"
            f"{font_clause}:fontcolor=0xD4A953:fontsize=42:"
            "x=(w-text_w)/2:y=700[cardlabel]"
        ),
    ]
    last_card = "cardlabel"
    for index, path in enumerate(cta_display_files):
        output = f"carddisplay{index}"
        parts.append(
            f"[{last_card}]drawtext=textfile='{escape_path(str(path))}'"
            f"{font_clause}:fontcolor=white:fontsize=52:"
            f"x=(w-text_w)/2:y={790 + index * 68}[{output}]"
        )
        last_card = output
    for index, path in enumerate(brokerage_files):
        output = f"cardbrokerage{index}"
        parts.append(
            f"[{last_card}]drawtext=textfile='{escape_path(str(path))}'"
            f"{font_clause}:fontcolor=white:fontsize=27:"
            "borderw=2:bordercolor=black@0.8:x=(w-text_w)/2:"
            f"y={970 + index * 42}[{output}]"
        )
        last_card = output
    parts.append(
        "[0:v]drawbox=x=70:y=210:w=940:h=300:color=0x0B1F33@0.88:t=fill:"
        f"enable='between(t,0,{OPENING_SECONDS:.1f})'[open0]"
    )
    last_opening = "open0"
    for index, path in enumerate(opening_files):
        output = f"opening{index}"
        parts.append(
            f"[{last_opening}]drawtext=textfile='{escape_path(str(path))}'"
            f"{font_clause}:fontcolor=white:fontsize=56:"
            f"x=(w-text_w)/2:y={275 + index * 78}:"
            f"enable='between(t,0,{OPENING_SECONDS:.1f})'[{output}]"
        )
        last_opening = output
    parts.append(
        f"[{last_opening}][{last_card}]overlay=0:0:"
        f"enable='gte(t,{end_at:.2f})'[carded]"
    )
    graph = ";".join(parts)
    inputs = ["-i", str(source), "-loop", "1", "-i", str(background)]
    last = "carded"
    if mark is not None:
        inputs += ["-loop", "1", "-i", str(mark)]
        graph += (
            ";[2:v]scale=190:-1[mark];"
            f"[{last}][mark]overlay=W-w-44:44:eof_action=repeat[out]"
        )
        last = "out"
    return [
        "ffmpeg", "-y", "-v", "error", *inputs,
        "-filter_complex", graph, "-map", f"[{last}]", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "22",
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-t", f"{duration:.3f}",
        "-movflags", "+faststart", str(destination),
    ]


def capture_calculator(url: str, destination: Path) -> bool:
    """Capture only the DHS calculator. Any browser failure selects fallback."""
    if not authorized_calculator_url(url):
        return False
    browser = next(
        (candidate for candidate in _CHROMIUM_CANDIDATES if Path(candidate).is_file()),
        shutil.which("chromium") or shutil.which("chromium-browser"),
    )
    if not browser:
        return False
    try:
        result = subprocess.run(
            [
                str(browser), "--headless", "--disable-gpu", "--no-sandbox",
                "--hide-scrollbars", "--window-size=1080,1920",
                "--virtual-time-budget=8000", f"--screenshot={destination}", url,
            ],
            capture_output=True,
            timeout=45,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        # The calculator is an enhancement, not a reason to lose an otherwise
        # valid render. Chromium can hang behind Snap even when the executable
        # exists; remove any partial image and let the caller draw the branded
        # fallback card promised by the worker contract.
        destination.unlink(missing_ok=True)
        return False
    return result.returncode == 0 and destination.is_file() and destination.stat().st_size > 0


def _fallback_card(destination: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        raise verify.Rejected("cannot build the DHS fallback card: Pillow is not installed") from None
    Image.new("RGB", (1080, 1920), "#0B1F33").save(destination)


def _write_text(path: Path, value: object) -> None:
    text = str(value or "").strip()
    if not text:
        raise verify.Rejected(f"the final-card text file {path.name} would be empty")
    path.write_text(text, encoding="utf-8")


def line_files(workdir: Path, prefix: str, value: object) -> list[Path]:
    """One file per visible line; drawtext renders a real LF as a tofu box."""
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    if not lines:
        raise verify.Rejected(f"the final-card text {prefix} would be empty")
    paths = []
    for index, line in enumerate(lines):
        path = workdir / f"finish-{prefix}-{index}.txt"
        _write_text(path, line)
        paths.append(path)
    return paths


def apply(
    source: Path,
    destination: Path,
    *,
    spec: dict,
    mark: Path,
    font: str | None = None,
) -> FinishReport:
    """Finish into a new file, verify it, then atomically expose the result."""
    validate(spec)
    if not mark.is_file():
        raise verify.Rejected("the Denver Home Story brand mark is missing")
    duration_min, duration_max = duration_bounds(spec)
    source_probe = verify.check(
        source,
        expect_audio=True,
        min_seconds=duration_min,
        max_seconds=duration_max,
    )
    workdir = destination.parent
    verify.reject_readable_digits(
        source,
        workdir / "ocr",
        before_seconds=max(0.0, source_probe.duration - END_CARD_SECONDS),
    )

    finish_spec = spec["finish"]
    background = workdir / "finish-background.png"
    calculator_url = finish_spec.get("calculator_url")
    used_calculator = bool(
        calculator_url and capture_calculator(str(calculator_url), background)
    )
    if not used_calculator:
        _fallback_card(background)

    label = workdir / "finish-label.txt"
    opening = line_files(
        workdir, "opening", opening_copy(finish_spec["opening_text"])
    )
    _write_text(label, finish_spec["cta_label"])
    display = line_files(
        workdir, "display", display_copy(finish_spec["cta_display"])
    )
    brokerage = line_files(
        workdir, "brokerage", brokerage_copy(spec["brokerage_line"])
    )

    temporary = destination.with_name(destination.stem + ".part.mp4")
    command = build_command(
        source,
        temporary,
        duration=source_probe.duration,
        background=background,
        opening_files=opening,
        cta_label_file=label,
        cta_display_files=display,
        brokerage_files=brokerage,
        font=font or default_font(),
        mark=mark,
    )
    rendered = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=1800,
        check=False,
    )
    if rendered.returncode != 0:
        tail = rendered.stdout[-800:].decode(errors="replace").strip()
        raise RuntimeError(f"DHS finishing ffmpeg failed: {tail or 'no output'}")
    result = verify.check(
        temporary,
        expect_audio=True,
        min_seconds=duration_min,
        max_seconds=duration_max,
    )
    os.replace(temporary, destination)
    return FinishReport(duration=result.duration, used_calculator=used_calculator)
