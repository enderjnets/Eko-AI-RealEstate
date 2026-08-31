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

**Yellow, and the spoken word grows.** This is not decoration copied from a
trend: the caption is competing with a photograph behind it, and white on a
bright picture disappears at exactly the moment somebody is deciding whether to
keep watching. Yellow with a heavy black outline survives any background, and
growing the word being said is what tells a muted viewer where the voice is
without them having to read ahead. The shape is the one running on the owner's
other channel, read from `~/BitTrader/agents/karaoke_subs.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# English-only where we can, multilingual where we must. `small.en` is faster
# and more accurate on English, which is what this channel speaks — but the
# product is bilingual, and handing a Spanish clip to an English-only model
# produces either garbled English-shaped captions burned into a client-facing
# video, or none at all. Neither is an acceptable answer for half the market.
MODELS = {"en": "small.en"}
DEFAULT_MODEL = "small"


def model_for(language: str) -> str:
    return MODELS.get((language or "en").lower(), DEFAULT_MODEL)

# Bottom third, above the platform's own furniture. TikTok and Reels put a
# caption and a button stack over the lower ~18% of the frame, so text placed
# at the very bottom is text nobody reads.
_MARGIN_V = 420
# 60 rather than 64: the spoken word is drawn at _HIGHLIGHT per cent, so the
# widest line is wider than the type size suggests, and a line that overflows
# 1080 px is a line with a word missing off the edge. Measured on the render
# machine's own DejaVu against the longest line this channel has produced.
_FONT_SIZE = 60
_MARGIN_H = 50
# ASS colours are &HAABBGGRR — bytes reversed. This is #FFFF00.
_YELLOW = "&H0000FFFF"
_BLACK = "&H00000000"
_OUTLINE = 4
# The word being spoken, as a percentage. The outline grows with it: an outline
# left at its normal weight looks thin the moment the glyph is bigger.
_HIGHLIGHT = 126
_HIGHLIGHT_OUTLINE = 5
# How many characters fit on one line, MEASURED rather than guessed: on the
# render machine's DejaVu at this size, with one word enlarged, a caption runs
# 34 px per character, and 1080 px less the two margins leaves 980. Four words
# alone was not a limit — "certain features, certain neighborhoods." is four
# words and rendered 1080 px wide, which is to say with a word hanging off each
# edge of the frame. Word count decides where a line may break; this decides
# whether it must.
_MAX_CHARS = 26


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Line:
    """One caption: the words that appear together, each keeping its own clock.

    The clock per word is the whole point. A line that only knows when it
    starts and ends can be drawn, but not animated — and the animation is what
    a muted viewer follows.
    """

    words: list[Word]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    @property
    def text(self) -> str:
        return "".join(w.text for w in self.words).strip()


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
        model = WhisperModel(model_for(language), device="cpu", compute_type="int8")
        segments, _info = model.transcribe(
            str(audio_or_video), language=language, word_timestamps=True
        )
        words: list[Word] = []
        for segment in segments:
            for word in segment.words or []:
                # Whisper's tokens carry their OWN leading space — " Homes",
                # " $612", but ",000" and "." with none, because that is how
                # the text reads. Stripping them and rejoining with spaces put
                # a gap before every comma and full stop: a caption saying
                # "$612 ,000" on a video whose whole subject is a price. Kept
                # verbatim and joined with nothing instead.
                text = word.word or ""
                if text.strip():
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


def group(words: list[Word], per_line: int = 4, max_gap: float = 0.8) -> list[Line]:
    """Words into short phrases.

    One word at a time flickers; a full sentence is a wall. Four is what reads
    on a phone, and a pause longer than `max_gap` starts a new line whatever
    the count — a caption that runs across a silence is a caption out of sync
    with the speaker.
    """
    lines: list[Line] = []
    buffer: list[Word] = []

    def flush() -> None:
        if buffer:
            lines.append(Line(list(buffer)))
            buffer.clear()

    for word in words:
        # A token with no leading space CONTINUES the previous one — ",000"
        # after "$680", "-minute" after "15". Breaking there splits a price
        # across two captions on a video whose entire subject is that price,
        # so a continuation never starts a line however full the buffer is.
        continues = bool(buffer) and not word.text[:1].isspace()
        so_far = sum(len(w.text) for w in buffer)
        if buffer and not continues and (
            len(buffer) >= per_line
            or so_far + len(word.text) > _MAX_CHARS
            or word.start - buffer[-1].end > max_gap
        ):
            flush()
        buffer.append(word)
    flush()
    return lines


def _drawn(word: Word, *, active: bool) -> str:
    """One word as it appears inside a caption.

    Whisper's leading space is kept OUTSIDE the override block. Scaling it too
    is invisible on screen but widens the line, and the line width is the one
    dimension there is no room to waste at 1080 px.
    """
    raw = word.text
    body = raw.lstrip()
    lead = raw[: len(raw) - len(body)]
    drawn = _escape(body)
    if active:
        drawn = (
            f"{{\\fscx{_HIGHLIGHT}\\fscy{_HIGHLIGHT}\\bord{_HIGHLIGHT_OUTLINE}}}"
            f"{drawn}"
            f"{{\\fscx100\\fscy100\\bord{_OUTLINE}}}"
        )
    return _escape(lead) + drawn


def build_ass(lines: list[Line], width: int = 1080, height: int = 1920) -> str:
    """A complete ASS file for these lines.

    One event per WORD, not per line: each redraws the whole line with a
    different word enlarged. That is more rows than a static caption needs, and
    it is the only way to get the effect out of a subtitle file rather than out
    of a filter chain that would have to re-encode the text into the pixels.
    """
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,{_FONT_SIZE},{_YELLOW},{_BLACK},&H80000000,1,1,{_OUTLINE},2,2,{_MARGIN_H},{_MARGIN_H},{_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows: list[str] = []
    for line in lines:
        for index, word in enumerate(line.words):
            # Held until the NEXT word begins, not until this one ends: the gap
            # between two words is silence in the middle of a phrase, and a
            # caption that blinks out for it reads as a stutter.
            until = (
                line.words[index + 1].start
                if index + 1 < len(line.words)
                else line.end
            )
            if until <= word.start:
                continue
            drawn = "".join(
                _drawn(w, active=(position == index))
                for position, w in enumerate(line.words)
            )
            rows.append(
                f"Dialogue: 0,{_ass_time(word.start)},{_ass_time(until)},"
                f"Caption,,0,0,0,,{drawn.strip()}"
            )
    return header + "\n".join(rows) + ("\n" if rows else "")


def write_ass(lines: list[Line], destination: Path) -> Path | None:
    """Write the file, or None when there is nothing to say."""
    if not lines:
        return None
    destination.write_text(build_ass(lines), encoding="utf-8")
    return destination
