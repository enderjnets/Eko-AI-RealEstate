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


def _seconds(media: Path) -> float:
    """How long a media file actually is. Zero when it cannot be read.

    `verify.probe` is not usable here: it demands a video stream, and the first
    thing measured is the narration mp3.
    """
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(media),
        ],
        capture_output=True,
        timeout=120,
    )
    try:
        return float(out.stdout.decode().strip())
    except ValueError:
        return 0.0

OUT_W, OUT_H = 1080, 1920
# Denver Home Story's own colours, from the logo: a navy ground with a cream
# title. Used for the card a scene falls back to, so a missing photo still
# looks like this channel rather than like an error.
BRAND_BG = "0x0B1B33"
BRAND_FG = "0xF5E6C8"
# A held frame after the last word, so the video ends instead of stopping. It
# is also what gives the brokerage line time to be read.
TAIL_SECONDS = 1.2


@dataclass(frozen=True)
class Shot:
    image: Path | None
    text: str
    start: float
    end: float

    @property
    def seconds(self) -> float:
        """Exactly its span — no floor.

        A floor here is not a safety net, it is a desynchroniser: the shots are
        concatenated in order, so padding one to a minimum pushes every later
        shot away from the words it belongs to, and makes the picture track a
        different length from the voice.
        """
        return self.end - self.start


def plan_shots(
    scenes: list[dict], words: list[subtitles.Word], total: float
) -> list[tuple[float, float]]:
    """When each scene is on screen, timed to the voice.

    Split at word boundaries rather than by dividing the duration: an even
    split puts a cut in the middle of a sentence, and the eye notices that far
    more than an uneven scene length.

    **The spans tile the whole audio — no gaps.** An earlier version ended each
    scene on the last word of its group and started the next on the first word
    of the next group, which drops every PAUSE between them. The picture track
    then came out shorter than the voice by the sum of those pauses, `-shortest`
    cut the difference off the end, and the video stopped four words before the
    script did — mid-sentence, on a piece a person had already been shown.
    A scene boundary is therefore the moment the next scene's first word
    STARTS, which is still a real word boundary and loses no time.
    """
    if not scenes:
        return []
    count = len(scenes)
    if not words:
        share = total / count
        return [(i * share, (i + 1) * share) for i in range(count)]

    # More scenes than words is a real case — a six-scene plan over a very
    # short narration — and it has to produce spans somebody can see. The
    # earlier version handed the leftovers `(total, total)`: zero-length shots
    # that `Shot.seconds` padded to a floor and `-shortest` then cut off
    # entirely, so their images had already been fetched and PAID FOR and never
    # appeared on screen. Falling back to an even split keeps every scene in
    # the video; the word-boundary cut is an improvement on the even split, not
    # a replacement for having one.
    if len(words) < count:
        share = total / count
        return [(i * share, (i + 1) * share) for i in range(count)]

    per_scene = max(1, len(words) // count)
    spans: list[tuple[float, float]] = []
    cursor = 0.0
    for index in range(count):
        if index == count - 1:
            # The last scene runs to the end of the audio, so the end card is
            # not cut off by a word that finished early.
            end = total
        else:
            end = words[min(len(words) - 1, (index + 1) * per_scene)].start
        spans.append((cursor, end))
        cursor = end

    # A degenerate transcript — two group boundaries on the same timestamp —
    # would give a zero-length scene, and ffmpeg cannot render `-t 0`. An even
    # split is a worse cut and a real video; refusing here would be neither.
    if any(end <= start for start, end in spans):
        share = total / count
        return [(i * share, (i + 1) * share) for i in range(count)]
    return spans


# The headline over each photograph, MEASURED — and measured twice, because the
# first measurement was wrong in a way worth recording. It used drawtext's
# DEFAULT font and gave 27.3 px per character; the worker actually passes
# `DejaVuSans-Bold`, which is wider. Rendered, the real headline "Mid-Range:
# Single-Family Homes" came out 1029 px inside a 1080 px frame — 25 px of
# margin — and at 34 characters it hit 1080 px exactly, which is to say clipped.
# Right machine, wrong font: the lesson from the captions, learned again.
#
# With the font it really uses: 29.5 px per character at this size, so 30
# characters is 885 px inside 960 px of usable width. Two lines of 30 is 60,
# which is exactly the cap `content_writer` puts on `on_screen_text` — every
# headline the writer can produce fits, and none is cut.
HEADLINE_SIZE = 48
HEADLINE_CHARS = 30
HEADLINE_LINES = 2
# Below the brand mark, which sits top-right down to about y=150.
HEADLINE_Y = 230
# Line height: the type size plus the leading the design uses elsewhere.
HEADLINE_STEP = HEADLINE_SIZE + 14


def wrap_headline(text: str, width: int = HEADLINE_CHARS) -> list[str]:
    """The scene's headline, broken into lines that fit the frame.

    drawtext does not wrap: it draws one long line and lets it run off both
    edges, which is what the captions did until it was measured. Words are kept
    whole; a single word longer than the line is left alone rather than cut,
    because a hyphen invented by a renderer reads as a typo.

    A LIST, and each line is drawn by its own filter. Putting a newline in one
    drawtext looked right and was not: this ffmpeg breaks the line AND draws the
    newline as a missing-glyph box at the end of it — visible in the frame,
    invisible in every measurement, because the box falls inside the bounding
    box the width check reads. Two filters have no newline to mishandle.
    """
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:HEADLINE_LINES]


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
        # The headline, but only over a PHOTOGRAPH. A fallback card already has
        # this same text as its whole content, and drawing it again would print
        # it twice on top of itself.
        headline_lines: list[str] = []
        if shot.image is not None:
            headline_lines = wrap_headline(shot.text)
        headline_clause = ""
        font_clause = f":fontfile='{assemble.escape_path(font)}'" if font else ""
        for row, line in enumerate(headline_lines):
            line_file = workdir / f"headline-{index}-{row}.txt"
            line_file.write_text(line, encoding="utf-8")
            # An outline rather than a box: a filled bar across the top of every
            # photograph is heavier than the thing it is labelling. Same reason
            # the captions carry an outline.
            headline_clause += (
                f",drawtext=textfile='{assemble.escape_path(str(line_file))}'"
                f"{font_clause}:fontcolor=white:fontsize={HEADLINE_SIZE}"
                f":borderw=5:bordercolor=black@0.9"
                f":x=(w-text_w)/2:y={HEADLINE_Y + row * HEADLINE_STEP}"
            )
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-loop", "1", "-i", str(image),
                "-vf",
                f"scale={OUT_W * 2}:-2,"
                f"zoompan=z='min(zoom+0.0009,1.12)':d={frames}"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":s={OUT_W}x{OUT_H}:fps=30,"
                f"setsar=1{headline_clause}",
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
    # Every later length is derived from this one. The last WORD rather than the
    # file, because MiniMax leaves a little silence at the end and the tail is
    # measured from where the voice stops, not where the file does — but never
    # shorter than the file, or the mix would cut audio that is still playing.
    spoken_until = words[-1].end if words else _seconds(voice)
    total = max(spoken_until + TAIL_SECONDS, _seconds(voice))

    # 2. A picture per scene. A prompt that nothing can draw becomes a branded
    # card, never a failed job.
    reported_no_balance = False
    shots: list[Shot] = []
    spans = plan_shots(scenes, words, total)
    for index, (scene, (start, end)) in enumerate(zip(scenes, spans, strict=True)):
        image: Path | None = workdir / f"pic-{index}.jpg"
        try:
            provider = pictures.fetch(
                scene["visual_prompt"], image, spec.get("people_words")
            )
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

    # A card standing in for ONE scene is a fallback. A card standing in for
    # EVERY scene is not a video: it is half a minute of a flat colour with a
    # word on it, and the only thing left to do with it is reject it — which is
    # exactly what happened to the first generated piece, after a person sat
    # through it to find out. Fail here instead, with the reason where the
    # console shows it, so nobody has to watch to learn that no image provider
    # is configured.
    if all(shot.image is None for shot in shots):
        raise ValueError(
            "no image provider produced a single picture: the video would be "
            "text on a plain background. Set PEXELS_API_KEY (free) or the "
            "Kling keys on the render machine."
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
            # `apad` + an explicit length instead of `-shortest`. `-shortest`
            # answers "how long is this video?" with whichever track came out
            # shorter — so any arithmetic slip upstream leaves the tail of the
            # NARRATION on the floor, exit code 0, nothing in the log. Silence
            # is padded on; speech never is.
            "-af", "apad",
            "-t", f"{total:.2f}",
            str(with_voice),
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )

    # And then it is measured, because the paragraph above is an intention. The
    # video a person watches has to contain the last word of the script; a
    # render that quietly drops it is worse than one that fails here, where the
    # reason lands in the console.
    made = _seconds(with_voice)
    if made + 0.15 < spoken_until:
        raise RuntimeError(
            f"the picture track is {made:.2f}s but the narration runs to "
            f"{spoken_until:.2f}s: the video would end mid-sentence"
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
            # The MEASURED length, not the planned one. The end card is drawn
            # over the last three seconds counted from here, so feeding it an
            # intention rather than a fact is how the brokerage identification
            # ends up on screen for a fraction of a second — or not at all.
            duration=made,
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
