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


# ── A prompt is not a paragraph ──────────────────────────────────────────
# `wrong_language` is built for prose and refuses to judge under MIN_WORDS,
# which is right: a hook is four words and guessing at it rejects correct work.
# An image prompt is not prose. Six of them joined usually clear the floor —
# piece 20's did, at 58 words — but a model that writes terse noun phrases
# ("Casa de ladrillo con jardín", "Llaves sobre una mesa") produces a whole
# shot list of twenty-four words that sails through with nothing measured.
# Measured, not assumed: that exact list returns None today.
#
# Lowering MIN_WORDS is not the fix. It is shared with the narration check, the
# more expensive guard of the two, and a terse ENGLISH list ("Brick house,
# keys, front door, desk") carries no function words either — it would be
# rejected for being short rather than for being wrong.
#
# So a second, narrower question, and it only ever ADDS a finding: is there
# positive evidence of the other language? Both conditions have to hold.

#: How many foreign function words count as evidence rather than as a loanword.
#: Colorado is full of Spanish place names — Cañon City, Del Norte, Buena Vista
#: — and "Del Norte" alone contributes a marker. Three is past coincidence.
FOREIGN_EVIDENCE = 3


def not_english_prompt(text: str) -> str | None:
    """Why this shot list cannot be sent to an image model, or None.

    The one place that answers that question, used by the writer (checking a
    draft the model just returned) and by the render queue (checking prompts
    stored months ago). Two copies of "what counts as English" is how the two
    gates drift apart, and the whole point of the second gate is that it
    catches what the first cannot see.
    """
    reason = wrong_language(text, "en")
    if reason is not None:
        return reason

    words = _words(text)
    english = sum(1 for word in words if word in MARKERS["en"])
    if english:
        # Any real English sentence carries function words. One is enough to
        # settle it, and it is what keeps Spanish toponyms in an English prompt
        # from tripping the count below.
        return None

    foreign = max(
        (
            (lang, sum(1 for word in words if word in markers))
            for lang, markers in MARKERS.items()
            if lang != "en"
        ),
        key=lambda pair: pair[1],
        default=("", 0),
    )
    if foreign[1] >= FOREIGN_EVIDENCE:
        return (
            f"too short to weigh, but {foreign[1]} {foreign[0]} function words "
            "and no English ones"
        )
    return None

