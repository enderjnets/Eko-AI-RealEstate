"""Words on screen, timed to the voice.

A short with no captions is half a video: most of the feed is watched muted,
and a talking head with no text is a talking head nobody hears. This is why the
render moved off the API box at all — transcription needs a speech model, and a
speech model has no business next to the process a lead is waiting on.

**CPU, not GPU, and that is not a compromise being apologised for.** The GPU on
the render machine is shared with another project's model server, which holds
most of the card; `small.en` in int8 transcribes a sixty-second clip in well
under a minute on cores that are otherwise idle in this window.

ASS rather than burned-in text: one subtitle filter, styled once, and the words
stay legible after a platform re-encodes the video.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MODEL = "small.en"

# Bottom third, above the platform's own furniture. TikTok and Reels put a
# caption and a button stack over the lower ~18% of the frame, so text placed
# at the very bottom is text nobody reads.
_MARGIN_V = 420
_FONT_SIZE = 64


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


def transcribe(audio_or_video: Path, language: str = "en") -> list[Word]:
    """Word-level timings, or an empty list.

    An empty list is a legitimate answer — a clip with no speech, music only —
    and the caller draws no subtitles rather than inventing any. It is also
    what a failed model load returns, logged: a video without captions is
    worse than one with, and far better than no video.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.error("faster-whisper is not installed; this clip gets no subtitles")
        return []

    try:
        model = WhisperModel(MODEL, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(
            str(audio_or_video), language=language, word_timestamps=True
        )
        words: list[Word] = []
        for segment in segments:
            for word in segment.words or []:
                text = (word.word or "").strip()
                if text:
                    words.append(Word(float(word.start), float(word.end), text))
        return words
    except Exception:  # noqa: BLE001 — a caption failure must not lose the video
        log.exception("transcription failed; continuing without subtitles")
        return []


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def _escape(text: str) -> str:
    # ASS treats `{` as the start of an override block and `\` as an escape.
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def group(words: list[Word], per_line: int = 4, max_gap: float = 0.8) -> list[Word]:
    """Words into short phrases.

    One word at a time flickers; a full sentence is a wall. Four is what reads
    on a phone, and a pause longer than `max_gap` starts a new line whatever
    the count — a caption that runs across a silence is a caption out of sync
    with the speaker.
    """
    lines: list[Word] = []
    buffer: list[Word] = []

    def flush() -> None:
        if buffer:
            lines.append(
                Word(buffer[0].start, buffer[-1].end, " ".join(w.text for w in buffer))
            )
            buffer.clear()

    for word in words:
        if buffer and (
            len(buffer) >= per_line or word.start - buffer[-1].end > max_gap
        ):
            flush()
        buffer.append(word)
    flush()
    return lines


def build_ass(lines: list[Word], width: int = 1080, height: int = 1920) -> str:
    """A complete ASS file for these lines."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,{_FONT_SIZE},&H00FFFFFF,&H00000000,&H80000000,1,1,4,2,2,80,80,{_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = [
        f"Dialogue: 0,{_ass_time(line.start)},{_ass_time(line.end)},Caption,,0,0,0,,"
        f"{_escape(line.text)}"
        for line in lines
    ]
    return header + "\n".join(rows) + ("\n" if rows else "")


def write_ass(lines: list[Word], destination: Path) -> Path | None:
    """Write the file, or None when there is nothing to say."""
    if not lines:
        return None
    destination.write_text(build_ass(lines), encoding="utf-8")
    return destination
