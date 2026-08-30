"""Lane B: a script becomes a video.

Narrate, find a picture per scene, time the scenes to the voice, assemble.

The order is not arbitrary. **The voice is made first and everything else is
cut to it**: a scene list with guessed durations produces captions that drift
and a last scene that ends mid-sentence. Whisper tells us where the words
actually fall, and the pictures are held for exactly that long.

Every picture prompt reaching this module has already been through the Fair
Housing filter and the person-descriptor denylist, in `content_writer`. Nothing
here re-decides that; it draws what it was given.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from worker import assemble, pictures, spoken, subtitles, tts

log = logging.getLogger(__name__)

OUT_W, OUT_H = 1080, 1920
# Denver Home Story's own colours, from the logo: a navy ground with a cream
# title. Used for the card a scene falls back to, so a missing photo still
# looks like this channel rather than like an error.
BRAND_BG = "0x0B1B33"
BRAND_FG = "0xF5E6C8"
MIN_SCENE_SECONDS = 1.5


@dataclass(frozen=True)
class Shot:
    image: Path | None
    text: str
    start: float
    end: float

    @property
    def seconds(self) -> float:
        return max(MIN_SCENE_SECONDS, self.end - self.start)


def plan_shots(
    scenes: list[dict], words: list[subtitles.Word], total: float
) -> list[tuple[float, float]]:
    """When each scene is on screen, timed to the voice.

    Split at word boundaries rather than by dividing the duration: an even
    split puts a cut in the middle of a sentence, and the eye notices that far
    more than an uneven scene length.
    """
    if not scenes:
        return []
    count = len(scenes)
    if not words:
        share = total / count
        return [(i * share, (i + 1) * share) for i in range(count)]

    per_scene = max(1, len(words) // count)
    spans: list[tuple[float, float]] = []
    for index in range(count):
        first = index * per_scene
        last = len(words) - 1 if index == count - 1 else min(
            len(words) - 1, (index + 1) * per_scene - 1
        )
        if first >= len(words):
            # More scenes than words. The leftovers share the tail rather than
            # collapsing to zero-length shots nobody sees.
            spans.append((total, total))
            continue
        spans.append((words[first].start, words[last].end))
    # The last scene runs to the end of the audio, so the end card is not cut
    # off by a word that finished early.
    if spans:
        spans[-1] = (spans[-1][0], total)
    return spans


def _card(text: str, destination: Path, font: str | None) -> None:
    """A branded frame with the line on it. What a scene falls back to."""
    font_clause = f":fontfile='{assemble.escape_path(font)}'" if font else ""
    safe = destination.with_suffix(".txt")
    safe.write_text(text, encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi",
            "-i", f"color=c={BRAND_BG}:size={OUT_W}x{OUT_H}:duration=1",
            "-vf",
            f"drawtext=textfile='{assemble.escape_path(str(safe))}'{font_clause}"
            f":fontcolor={BRAND_FG}:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2"
            f":line_spacing=18",
            "-frames:v", "1", str(destination),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    safe.unlink(missing_ok=True)


def build_scene_video(shots: list[Shot], workdir: Path, font: str | None) -> Path:
    """The picture track: each shot held for its span, with a slow push in.

    The movement is what keeps a still image from looking like a slideshow. It
    is a slow zoom rather than a pan because a pan on a portrait crop runs out
    of frame.
    """
    pieces: list[Path] = []
    for index, shot in enumerate(shots):
        clip = workdir / f"scene-{index}.mp4"
        image = shot.image
        if image is None:
            image = workdir / f"card-{index}.png"
            _card(shot.text, image, font)
        frames = max(1, int(shot.seconds * 30))
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-loop", "1", "-i", str(image),
                "-vf",
                f"scale={OUT_W * 2}:-2,"
                f"zoompan=z='min(zoom+0.0009,1.12)':d={frames}"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":s={OUT_W}x{OUT_H}:fps=30,"
                f"setsar=1",
                "-t", f"{shot.seconds:.2f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(clip),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
        pieces.append(clip)

    listing = workdir / "scenes.txt"
    listing.write_text(
        "".join(f"file '{p.name}'\n" for p in pieces), encoding="utf-8"
    )
    joined = workdir / "scenes.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", str(joined),
        ],
        check=True,
        capture_output=True,
        timeout=600,
        cwd=workdir,
    )
    return joined


def produce(
    spec: dict,
    workdir: Path,
    *,
    font: str | None,
    mark: Path | None,
    music: Path | None,
    domain: str = "denverhomestory.com",
) -> Path:
    """Script in, finished video out."""
    plan = spec.get("scenes") or {}
    scenes = plan.get("scenes") or []
    if not scenes:
        raise ValueError("this piece has no scene plan; nothing to build")

    # 1. The voice, first, because everything is cut to it.
    narration = spoken.for_the_voice(plan.get("narration") or spec.get("script") or "")
    voice = tts.narrate(narration, workdir / "voice.mp3")

    words = subtitles.transcribe(voice, language=spec.get("language", "en"))
    total = words[-1].end if words else 30.0

    # 2. A picture per scene. A prompt that nothing can draw becomes a branded
    # card, never a failed job.
    reported_no_balance = False
    shots: list[Shot] = []
    spans = plan_shots(scenes, words, total)
    for index, (scene, (start, end)) in enumerate(zip(scenes, spans, strict=True)):
        image: Path | None = workdir / f"pic-{index}.jpg"
        try:
            provider = pictures.fetch(scene["visual_prompt"], image)
        except pictures.NoBalance as exc:
            if not reported_no_balance:
                # Once. Kling is asked per scene, so an empty account would
                # otherwise produce six identical alarms per video.
                log.error("KLING OUT OF BALANCE: %s", exc)
                reported_no_balance = True
            provider = "none"
        if provider == "none":
            image = None
        else:
            log.info("scene %d: %s", index + 1, provider)
        shots.append(
            Shot(image=image, text=scene.get("on_screen_text", ""), start=start, end=end)
        )

    # 3. The picture track, then the words, then the identification.
    scene_video = build_scene_video(shots, workdir, font)
    with_voice = workdir / "voiced.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(scene_video), "-i", str(voice),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest", str(with_voice),
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )

    ass_path = subtitles.write_ass(subtitles.group(words), workdir / "captions.ass")
    brokerage_file = workdir / "brokerage.txt"
    brokerage_file.write_text(spec["brokerage_line"], encoding="utf-8")
    domain_file = workdir / "domain.txt"
    domain_file.write_text(domain, encoding="utf-8")

    destination = workdir / "out.mp4"
    assemble.run(
        assemble.build_command(
            with_voice,
            destination,
            duration=total,
            has_audio=True,
            brokerage_file=brokerage_file,
            domain_file=domain_file,
            font=font,
            mark=mark,
            subtitles=ass_path,
            music=music,
        )
    )
    return destination
