"""Turning what a machine understood into something the `leads` table accepts.

Two very different sources write these columns — a language model reading a
WhatsApp thread, and a voice agent's `structuredData` from a phone call — and
both are guesses about free-form human speech. Neither is trustworthy input.

What makes this worth a module of its own is where the cost lands. Both writers
run inside the transaction that stores what the customer actually said: the
message, or the call transcript. A value the database refuses does not merely
fail to save — it aborts that transaction, and because the provider redelivers
the same payload, every retry fails identically. The customer's words are gone,
and the lead with them.

So nothing here raises, and nothing here returns a value the table would refuse.
A field we could not make sense of is dropped. Losing one field is a bad day;
losing the conversation is a lost client.

The rules live here rather than beside each writer because that is the mistake
this code has already made several times: the guard gets added to the path
somebody was looking at, and the next path along keeps the bug.
"""

from __future__ import annotations

import logging
import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

log = logging.getLogger(__name__)

# NUMERIC(12,2): ten digits before the decimal point. `leads` also carries a
# CHECK refusing negatives, and another refusing an inverted pair.
BUDGET_CEILING = 9_999_999_999

# Column widths from `models/lead.py`. A longer string is truncated by nothing —
# Postgres raises, which is the failure this module exists to prevent.
FIELD_LIMITS = {
    "name": 160,
    "zone": 160,
    "property_type": 60,
    "urgency": 40,
}

# "450k", "1.2M", "2.5 million". A model told to return numbers returns these
# anyway. Dropping the suffix is the dangerous reading — 450k as 450 is wrong by
# a thousand, and wrong in a way that passes every later check.
_MULTIPLIERS = {
    "k": 1_000,
    "m": 1_000_000,
    "mm": 1_000_000,
    "mil": 1_000,          # "450 mil" — Spanish thousand
    "millon": 1_000_000,
    "millón": 1_000_000,
    "millones": 1_000_000,
    "million": 1_000_000,
    "millions": 1_000_000,
}

# The sign is part of the number. Leaving it out turned "-1" into 1 — a
# negative silently becoming a positive is worse than not reading it at all,
# because nothing downstream can tell it was ever wrong.
_NUMBER = re.compile(
    r"(?P<number>-?(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?))"
    r"\s*(?P<suffix>millones|millón|millions|million|millon|mm|mil|[km])?",
    re.IGNORECASE,
)


def _digits_only(number: str) -> float | None:
    """Read a grouped number in either convention, or give up.

    "1.200.000,50" is European and "1,200,000.50" is American, and the same
    string can be neither. Where it is genuinely ambiguous ("1.234" — a
    thousand two hundred, or one point two three four?) the grouped reading
    wins, because these are house prices.
    """
    if "." in number and "," in number:
        number = (
            number.replace(".", "").replace(",", ".")
            if number.rfind(",") > number.rfind(".")
            else number.replace(",", "")
        )
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+", number):
        number = number.replace(",", "")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", number):
        number = number.replace(".", "")
    elif "," in number:
        number = number.replace(",", ".")  # European decimal comma
    try:
        return float(number)
    except ValueError:
        return None


def parse_budget(value: Any) -> float | None:
    """Read a budget out of whatever the model returned. Never raise.

    Returns None for anything it cannot read confidently — including a string
    holding more than one number. "between 300k and 500k" is a range, and
    welding its two numbers into a third is worse than admitting we did not
    understand it.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        try:
            number = float(value)
        except (TypeError, ValueError, InvalidOperation, OverflowError):
            return None
        return number if math.isfinite(number) else None

    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text or text in ("null", "none", "n/a", "na", "-"):
        return None
    # Currency and spacing vary; "450 000" is one number written with a space.
    text = text.replace("$", "").replace("€", "").replace("£", "")
    text = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", text)

    # "450kk" and "450 mil millones" are not readings this code can defend:
    # the first is a typo and the second stacks two multipliers. Both used to
    # come out a thousand or a million low, which is the worst kind of wrong —
    # plausible, in range, and invisible to everything downstream.
    if re.search(r"(?:k|m|mm|mil|mill\w*)\s*(?:k|m|mm|mil|mill\w*)", text, re.IGNORECASE):
        return None

    matches = _NUMBER.findall(text)
    if len(matches) != 1:
        # Zero: no number at all. More than one: a range or a sentence, and
        # picking one of them would be inventing an answer.
        return None
    raw, suffix = matches[0]
    number = _digits_only(raw)
    if number is None:
        return None
    if suffix:
        number *= _MULTIPLIERS.get(suffix.lower(), 1)
    return number if math.isfinite(number) else None


def storable_budget(value: Any) -> float | None:
    """`parse_budget`, then refuse anything the table would.

    NaN deserves its own mention: it survives every comparison-based check
    (`nan < 0` is False, and so is `nan > ceiling`), Postgres stores it happily
    in a NUMERIC, and a lead holding it matches no listing ever again while
    `/matches` reports that as "nothing available". It also makes any later
    comparison raise, which is how it took the message down.
    """
    number = parse_budget(value)
    if number is None:
        return None
    if not math.isfinite(number) or number < 0 or number > BUDGET_CEILING:
        log.warning("dropping a budget the database would refuse: %r", value)
        return None
    return number


def storable_text(value: Any, field: str) -> str | None:
    """Trim to the column width instead of letting Postgres refuse the write.

    `urgency` is 40 characters and a voice agent answers "as soon as possible,
    ideally within the next thirty days" — 52. Truncating loses the tail of one
    field; refusing loses the call.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    limit = FIELD_LIMITS.get(field)
    if limit is not None and len(text) > limit:
        log.info("%s was %d characters, trimming to %d", field, len(text), limit)
        text = text[:limit].rstrip()
    return text


def merge_budget(
    stored: tuple[Decimal | float | None, Decimal | float | None],
    extracted: tuple[float | None, float | None],
) -> tuple[Decimal | float | None, Decimal | float | None]:
    """Reconcile what was just understood with what the lead already holds.

    Both ways of getting this wrong are silent:

    - A range the wrong way round matches no listing at all, and `/matches`
      reports that as "nothing available" rather than "this record is broken".
      The table refuses the pair outright, and that refusal costs the message.
    - A stale value that refuses to be corrected is as bad in the other
      direction: the lead says "between 100 and 300", an earlier guess left a
      minimum of 500, and we keep showing them what they just ruled out however
      many times they repeat themselves.

    So a complete range in one message is the customer stating their budget, and
    it wins. A single value only fills a gap, and only if it does not turn the
    pair around.
    """
    low, high = _finite(stored[0]), _finite(stored[1])
    e_min, e_max = _finite(extracted[0]), _finite(extracted[1])

    if e_min is not None and e_max is not None:
        if e_min <= e_max:
            return (e_min, e_max)
        log.warning("a backwards range was extracted (%s-%s), ignoring it", e_min, e_max)
        return (low, high)

    if e_min is not None and low is None and (high is None or e_min <= high):
        low = e_min
    if e_max is not None and high is None and (low is None or e_max >= low):
        high = e_max
    return (low, high)


def _finite(value: Decimal | float | None) -> Decimal | float | None:
    """NaN compares False against everything and then poisons the arithmetic.

    A `Decimal('NaN')` already in the row makes `Decimal >= float` raise
    `InvalidOperation`, inside the transaction holding the customer's message.
    Treat it as absent, which is what it means.
    """
    if value is None:
        return None
    try:
        if isinstance(value, Decimal):
            return None if not value.is_finite() else value
        return None if not math.isfinite(float(value)) else value
    except (TypeError, ValueError, InvalidOperation, OverflowError):
        # OverflowError included deliberately: float(10**400) raises, and the
        # whole contract of this function is that it does not.
        return None
