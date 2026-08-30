"""Is this text in the language we asked for?

A deterministic check, not a model. The failure it exists for is specific and
was paid for next door: a pipeline whose prompts were written in one language
produced scripts in that language for a channel in another, and every gate
passed because the gates looked at the title, or the topic, or nothing at all.
A whole channel published in the wrong language for days.

Two rules, learned from that:

* **Look at the text that will be SPOKEN**, not the title and not the topic. A
  correct headline over a script in another language is the exact shape of the
  bug.
* **Mixture is a failure too.** A guard that only detects "wholly the wrong
  language" passes a script that switches halfway, which is what a model
  actually produces when its instructions and its context disagree.

Marker words rather than a language-detection library: no dependency, no model
download on a box that answers leads, and the markers are function words that
any sentence of prose contains several of. Short strings are unjudgeable and
are passed — this is a guard against a script, not a spell checker.
"""

from __future__ import annotations

import re
import unicodedata

# Function words. Deliberately not content words: "casa" and "house" both
# appear in real estate copy in either language, and a marker that fires on
# vocabulary rather than grammar measures the topic instead of the language.
MARKERS = {
    "en": {
        "the", "and", "of", "to", "in", "that", "is", "it", "for", "with",
        "you", "your", "this", "are", "what", "how", "on", "at", "from",
        "have", "has", "will", "not", "but", "they", "their", "when",
    },
    "es": {
        "el", "la", "los", "las", "de", "que", "y", "en", "un", "una",
        "por", "con", "para", "su", "lo", "se", "es", "al", "del", "como",
        "más", "mas", "pero", "cuando", "tu", "tus", "esta", "este",
    },
}

# Under this many words there is nothing to measure. A hook is four words and
# judging it would reject correct work.
MIN_WORDS = 25
# The other language may not carry more markers than the intended one, and a
# mixture is caught by requiring a clear majority rather than a bare win.
DOMINANCE = 1.5


def _words(text: str) -> list[str]:
    folded = "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9\s]+", " ", folded.lower()).split()


def wrong_language(text: str, expected: str) -> str | None:
    """The reason this text is not `expected`, or None.

    None also means "not enough text to judge", which is deliberate: a guard
    that guesses on four words rejects correct work, and the pieces this
    protects are always paragraphs.
    """
    if expected not in MARKERS:
        return None
    words = _words(text)
    if len(words) < MIN_WORDS:
        return None

    counts = {
        lang: sum(1 for word in words if word in markers)
        for lang, markers in MARKERS.items()
    }
    mine = counts[expected]
    other = max(count for lang, count in counts.items() if lang != expected)

    if mine == 0:
        return f"no {expected} function words in {len(words)} words"
    if other >= mine:
        return (
            f"reads as another language: {other} foreign markers against "
            f"{mine} {expected} ones"
        )
    if mine < other * DOMINANCE:
        # Not "wholly wrong" — mixed. This is the case a naive check passes,
        # and the one a model actually produces.
        return (
            f"mixes languages: {mine} {expected} markers against {other} "
            "foreign ones"
        )
    return None
