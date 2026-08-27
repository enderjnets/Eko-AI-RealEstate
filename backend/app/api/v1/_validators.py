"""Trimming that runs at the API boundary, in one place instead of four.

Three schema modules — `settings.py`, `content.py`, `visits.py` — each grew
their own `mode="before"` trimming validator, and each wrote the same
`isinstance(value, str)` guard. Two of them also wrote a docstring explaining
precisely why that guard is not enough, and left it that way. This module is
the third attempt, and it is shared so there is no fourth.

**Why `mode="before"` matters.** A `Field(min_length=…)` constraint judges the
value the validator returns. Run the trim *after* it and `" "` satisfies
`min_length=1`, which is how `agency_name` came to hold `"Ashly "` and every
greeting read "assistant at Ashly .". Run it before and the constraint sees the
trimmed value, which is the one that will be stored.

**Why `bytes`.** Pydantic coerces `bytes` to `str` AFTER a `mode="before"`
validator runs, so a str-only guard hands the model raw bytes and they are
persisted untrimmed — the exact value the validator exists to refuse.

The obvious fix is wrong, and was tried: `decode("utf-8", "replace")` turned
`b"\\xff\\xff\\xff"` from a clean 422 into `"\\ufffd\\ufffd\\ufffd"`, three
characters that SATISFY the `min_length=3` on a rejection reason. A reason made
of three unreadable glyphs is worse than a refused request. So the decode here
is strict, and undecodable bytes are handed back untouched for Pydantic to
refuse the way it already would. Valid UTF-8 gets trimmed; invalid stays a 422.

None of this is reachable over JSON, which has no byte string. It is closed
because "documented, not fixed" is how the same hole got written down twice.
"""
from __future__ import annotations


def trimmed(value: object) -> object:
    """Strip a caller string, whether it arrives as `str` or as `bytes`.

    Anything else is returned untouched, for the field's own type rules to
    judge — a `mode="before"` validator sees whatever was actually sent.
    """
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return value
    return value.strip() if isinstance(value, str) else value


def trimmed_or_none(value: object) -> object:
    """For NULLABLE columns: trim, and treat whitespace-only as "clear it".

    Split from `trimmed` by the column's nullability, and the split is
    load-bearing: a single "trim, empty becomes None" rule turns
    `agency_name=" "` into None, which a blind `setattr` writes into a NOT NULL
    column — a 500 where a 422 belongs. On a nullable column the opposite is
    true: storing `""` means `IS NULL` and `= ''` both have to be checked to
    ask one question.
    """
    result = trimmed(value)
    if not isinstance(result, str):
        return result
    return result or None
