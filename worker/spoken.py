"""Turning a written script into something a voice can read.

The whole module exists because of one published short. It said "$10,340" and
the narrator read it "one zero three four zero" — nine of its thirty-one
seconds spent spelling out a number. A script is written for the eye; a
narrator needs the words.

This matters more here than it did there. Denver Home Story talks about prices
in almost every video: "$450,000", "3.5%", "1,200 square feet", "2nd". Every
one of those is a trap.

`num2words` does the counting. What is here is the surrounding rules — currency
before the number, percent after it, ordinals, ranges — which no library knows
because they are about how English says money rather than how it says numbers.
"""

from __future__ import annotations

import re

try:  # pragma: no cover - exercised by the absence test
    from num2words import num2words
except ImportError:  # pragma: no cover
    num2words = None


def _spell(number: float) -> str:
    if num2words is None:
        return str(number)
    if number == int(number):
        return num2words(int(number))
    whole, _, fraction = f"{number}".partition(".")
    digits = " ".join(num2words(int(d)) for d in fraction)
    return f"{num2words(int(whole))} point {digits}"


def _money(match: re.Match[str]) -> str:
    raw = match.group(1).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return match.group(0)
    suffix = (match.group(2) or "").lower()
    if suffix.startswith("k"):
        value *= 1_000
    elif suffix.startswith("m"):
        value *= 1_000_000
    # "dollars" AFTER the number, because that is how it is said: the symbol
    # comes first in writing and last in speech.
    unit = "dollar" if value == 1 else "dollars"
    return f"{_spell(value)} {unit}"


def _percent(match: re.Match[str]) -> str:
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return match.group(0)
    return f"{_spell(value)} percent"


_ORDINALS = {
    "1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth",
    "5th": "fifth", "6th": "sixth", "7th": "seventh", "8th": "eighth",
    "9th": "ninth", "10th": "tenth", "11th": "eleventh", "12th": "twelfth",
    "20th": "twentieth", "21st": "twenty first", "30th": "thirtieth",
}


def _plain_number(match: re.Match[str]) -> str:
    raw = match.group(0).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return match.group(0)
    # Four digits with no separator is far more often a year than a quantity,
    # and "two thousand and twenty six" for 2026 is worse than leaving it.
    if "," not in match.group(0) and value.is_integer() and 1900 <= value <= 2100:
        return match.group(0)
    return _spell(value)


def for_the_voice(text: str) -> str:
    """The script, rewritten so a narrator reads it as a person would.

    Order matters: money and percentages first, because they contain the
    numbers the general rule would otherwise take apart. `$450,000` handled
    last would already be "four hundred fifty thousand $".
    """
    if not text:
        return text
    # The `\s*` lives INSIDE the optional group: outside it, a number with no
    # suffix ate the space after itself and "$450,000 and" came out as
    # "four hundred and fifty thousand dollarsand".
    out = re.sub(r"\$\s*([\d,]+(?:\.\d+)?)(?:\s*([kKmM])\b)?", _money, text)
    out = re.sub(r"([\d,]+(?:\.\d+)?)\s*%", _percent, out)
    for written, spoken in _ORDINALS.items():
        out = re.sub(rf"\b{written}\b", spoken, out, flags=re.IGNORECASE)
    out = re.sub(r"\b\d[\d,]*(?:\.\d+)?\b", _plain_number, out)
    # A URL is for the eye. It is burned into the end card and it belongs in
    # the caption; read aloud it is "denverhomestory dot com" at best and a
    # spelled-out string at worst.
    out = re.sub(r"\b(?:https?://)?[\w.-]+\.(?:com|net|org)\b", "", out)
    return re.sub(r"\s{2,}", " ", out).strip()
