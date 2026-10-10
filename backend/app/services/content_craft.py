"""Hook formulas, the caption's first sentence, and phrases that read as machine-written.

Adapted from instagram-agent-skill by Jake Schincariol (MIT licence, commit
d03c56b, 13-sep-2026; notice in docs/third_party/instagram-agent-skill.md).
Ender chose these three pieces on 10-oct-2026 after an audit of the pack.

What changed on the way in, and why:

- The pack's 26 formulas are written for a creator on camera: "$18,000 is what
  one missing clause cost me", "I spent ten years inside...". Our narrator is a
  synthetic voice speaking for two licensed agents. It has no costs, no years
  and no clients of its own, and `_SYSTEM` forbids inventing numbers. So only
  the formulas that need none of those came across, reworded, and one of ours
  joined them: the legend-then-truth opening the Decoded series already uses.
- "The Callout" ({specific group}, this is for you) stayed out: picking an
  audience by who they are is the Fair Housing line this product exists to
  keep. Formulas built on a statistic or a deadline stayed out too; a model
  asked for a percentage produces one.
- The phrase list is a curated subset. Words with an honest meaning in real
  estate ("leverage", "unlock", "landscape", "journey") are not on it, and
  neither is anything our own deterministic lines say ("Follow for more
  Denver, decoded.", "Save this for your Denver weekend.").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import ContentLanguage, ContentSeries

_CONVERSION = ContentSeries.CONVERSION
_DECODED = ContentSeries.DENVER_DECODED
_WEEKEND = ContentSeries.DENVER_WEEKEND
_MARKET = ContentSeries.DENVER_MARKET_NO_HYPE
_WRITTEN = frozenset({_CONVERSION, _DECODED, _WEEKEND, _MARKET})


@dataclass(frozen=True)
class HookFormula:
    key: str
    name: str
    template: str
    example: str
    series: frozenset[ContentSeries]


HOOK_FORMULAS: tuple[HookFormula, ...] = (
    HookFormula(
        "legend-then-truth", "Legend, then truth",
        "{Place or thing} has a legend about {it}. Here's what's actually true.",
        "Denver's airport has a \"cursed\" horse. Here's what's actually true.",
        frozenset({_DECODED}),
    ),
    HookFormula(
        "nobody-tells-you", "Nobody tells you",
        "Nobody tells you {a true, slightly uncomfortable fact about the thing}.",
        "Nobody tells you the appraisal can come in under the offer.",
        _WRITTEN,
    ),
    HookFormula(
        "stop-then-instead", "Stop, then instead",
        "Stop {the common move}. {The better move} instead.",
        "Stop pricing from an online estimate. Start from the last three sales on the street instead.",
        frozenset({_CONVERSION}),
    ),
    HookFormula(
        "backwards", "Backwards, and not your fault",
        "Most people get {the thing} backwards, and it is not their fault. {The fix}.",
        "Most people read days on market backwards, and it is not their fault.",
        frozenset({_CONVERSION, _MARKET}),
    ),
    HookFormula(
        "if-this", "If this, watch",
        "If you {are in a specific situation}, this is the part to watch.",
        "If the offer depends on selling the current house first, this is the part to watch.",
        frozenset({_CONVERSION, _WEEKEND}),
    ),
    HookFormula(
        "numbered-favourite", "Numbered, with a favourite",
        "{Count of items in this video} {things} about {topic}. The last one is the one people skip.",
        "Three things an inspection report will not say out loud. The last one is the one people skip.",
        _WRITTEN,
    ),
    HookFormula(
        "the-objection", "The objection",
        "\"{An objection people really say}.\" Fair. Here is what it misses.",
        "\"Spring is the only time to list.\" Fair. Here is what it misses.",
        frozenset({_CONVERSION, _MARKET}),
    ),
    HookFormula(
        "this-or-that", "This or that",
        "{A} or {B}? {What actually separates them}.",
        "Red Rocks or the Mission Ballroom? They were built for different reasons.",
        frozenset({_CONVERSION, _DECODED, _WEEKEND}),
    ),
    HookFormula(
        "you-do-not-need", "You do not need",
        "You do not need {the thing people assume they need} - only when the brief says so.",
        "You do not need a perfect house to list it.",
        frozenset({_CONVERSION}),
    ),
    HookFormula(
        "mid-sentence", "Mid-sentence start",
        "...and that is when {the turn in the story}.",
        "...and that is when the lake flooded the road to Golden.",
        frozenset({_DECODED, _WEEKEND}),
    ),
    HookFormula(
        "saying-flipped", "A saying, flipped",
        "{A well-known saying}, except {where it breaks}.",
        "Location, location, location, except the listing photos rarely show it.",
        _WRITTEN,
    ),
    HookFormula(
        "not-what-it-looks-like", "Not what it looks like",
        "This is {a place or thing}, and it is not what it looks like.",
        "This is a Denver park, and it used to be a cemetery.",
        frozenset({_DECODED, _WEEKEND}),
    ),
    HookFormula(
        "the-superlative", "The superlative",
        "The {biggest / oldest / only} {thing} in Denver is {the answer} - true by the brief, never about a neighbourhood or who lives there.",
        "Denver's biggest lake has two legends, and one of them is an elephant.",
        frozenset({_DECODED}),
    ),
)

_HOOK_MESSAGE = {
    ContentLanguage.EN: (
        "Hook formula for this draft: {name}. Shape: {template} "
        "Example of the shape only, not its facts: {example} "
        "Use it only if the brief supports it truthfully. Never invent a number, a "
        "date, a quote or a personal experience to fill it; if it does not fit, "
        "write the plainest true hook instead."
    ),
    ContentLanguage.ES: (
        "Fórmula de gancho para este borrador: {name}. Forma: {template} "
        "Ejemplo solo de la forma, no de sus datos: {example} "
        "Úsala solo si el brief la sostiene con verdad. Nunca te inventes un número, "
        "una fecha, una cita ni una experiencia personal para rellenarla; si no "
        "encaja, escribe el gancho verdadero más sencillo."
    ),
}


def hook_formula_for(series: ContentSeries, index: int) -> HookFormula | None:
    """The formula this draft is asked to try. None for recorded answers."""
    fits = [f for f in HOOK_FORMULAS if series in f.series]
    return fits[index % len(fits)] if fits else None


def hook_message(formula: HookFormula, language: ContentLanguage) -> dict[str, str]:
    template = _HOOK_MESSAGE.get(language, _HOOK_MESSAGE[ContentLanguage.EN])
    return {
        "role": "user",
        "content": template.format(
            name=formula.name, template=formula.template, example=formula.example
        ),
    }


#: Instagram shows roughly this many characters of a caption in the feed before
#: "more". Whatever the caption is for has to be said before it.
CAPTION_PREVIEW_CHARS = 125

_FIRST_SENTENCE = re.compile(r"^.*?[.!?](?=\s|$)")


def caption_opening(caption: str | None) -> str:
    """The first sentence of the first line: what the feed shows."""
    first_line = str(caption or "").strip().split("\n", 1)[0].strip()
    found = _FIRST_SENTENCE.match(first_line)
    return (found.group(0) if found else first_line).strip()


def caption_opening_finding(caption: str | None) -> dict[str, str] | None:
    opening = caption_opening(caption)
    if len(opening) <= CAPTION_PREVIEW_CHARS:
        return None
    return {
        "phrase": (
            f"the caption opens with a {len(opening)}-character sentence; Instagram "
            f"shows about {CAPTION_PREVIEW_CHARS} before \"more\", so put the point "
            "in a short first sentence"
        ),
        "category": "caption",
        "where": "caption",
    }


#: Phrases that read as machine-written in a voiceover or a caption. Matched as
#: whole words, case-insensitive.
MACHINE_PHRASES: tuple[str, ...] = (
    # verbs
    "delve into", "delve", "dive deep into", "embark on", "unleash", "supercharge",
    "revolutionize", "skyrocket", "level up", "elevate your",
    # nouns
    "game-changer", "game changer", "tapestry", "testament to", "treasure trove",
    "plethora", "synergy", "paradigm", "hidden gem", "secret sauce", "ultimate guide",
    "deep dive", "north star", "no-brainer",
    # adjectives
    "game-changing", "groundbreaking", "unparalleled", "cutting-edge", "transformative",
    "seamless", "seamlessly", "breathtaking", "captivating", "must-have", "bespoke",
    "holistic", "multifaceted", "myriad",
    # connectives
    "moreover", "furthermore", "it is worth noting that", "in essence", "in conclusion",
    # openers
    "in today's fast-paced world", "in today's digital age", "ever-evolving landscape",
    "ever-changing world", "let's face it", "imagine a world where", "it's no secret that",
    "we've all been there", "without further ado", "buckle up", "the harsh truth is",
    "stop scrolling", "don't scroll past this", "in this video", "in today's video",
    "watch till the end", "you won't believe", "nobody is talking about this",
    "no one is talking about this", "this changed everything", "this is your sign to",
    # closers
    "let that sink in", "the choice is yours", "food for thought", "the future is here",
    "at the end of the day", "move the needle", "read that again", "trust me on this one",
    "don't sleep on this", "run don't walk", "tag someone who needs this", "double tap if",
    "drop a comment below", "let me know in the comments",
)

_STRUCTURES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("it's not just X, it's Y",
     re.compile(r"(?i)\bit'?s not (?:just|only) [^.!?\n]{2,60}[,.;] it'?s\b")),
    ("not only X but also Y", re.compile(r"(?i)\bnot only\b[^.!?\n]{2,80}\bbut also\b")),
    ("it isn't about X, it's about Y",
     re.compile(r"(?i)\b(?:this|it) (?:is|isn'?t)(?: not)? about [^.!?\n]{2,60}[.!;,] it'?s about\b")),
    ("as an AI", re.compile(r"(?i)\bas an ai\b|\bas a language model\b")),
)


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    body = r"\s+".join(re.escape(part) for part in phrase.split())
    body = body.replace("'", "['’]")
    return re.compile(rf"(?i)(?<![\w'’-]){body}(?![\w'’-])")


_PATTERNS = tuple((phrase, _phrase_pattern(phrase)) for phrase in MACHINE_PHRASES)


def machine_phrase_findings(
    *, hook: str | None, script: str | None, caption: str | None
) -> list[dict[str, str]]:
    """One finding per machine-written phrase per field, naming both."""
    found: list[dict[str, str]] = []
    for where, text in (("hook", hook), ("script", script), ("caption", caption)):
        body = str(text or "")
        if not body:
            continue
        named: list[str] = []
        for phrase, pattern in _PATTERNS:
            if pattern.search(body) and not any(phrase in longer for longer in named):
                named.append(phrase)
        for name, pattern in _STRUCTURES:
            if pattern.search(body):
                named.append(name)
        for phrase in named:
            found.append({
                "phrase": f"“{phrase}” reads as machine-written; say it the plain way",
                "category": "ai-phrase",
                "where": where,
            })
    return found
