"""Trim strings to their column width, on every write, at the model.

Postgres does not truncate an over-long `VARCHAR` — it refuses the statement.
That refusal is not a lost field: on the paths that matter here, the same
transaction is storing what the customer actually said (their WhatsApp message,
their email, the transcript of their phone call), so the whole thing rolls back
and the provider, replaying an identical payload, fails identically. The words
are gone.

Nine rounds of audit found this one field at a time — the budgets, then
`urgency`, then `zone`, then the display name on the constructor two lines below
the one that had just been guarded, then an email subject. Each fix was correct
and each one covered the field somebody happened to be looking at. Guarding
fields is the wrong move; this guards the column.

`@validates` fires on every ORM attribute set, whoever does it, so a writer
added next year is covered without knowing this exists. It is the same argument
as the CHECK constraints in migration 030: put the rule where nothing can go
around it.

Truncating is a real loss and it is logged, but it is the smaller one. The
alternative on these paths is losing the conversation.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Enum, String
from sqlalchemy.orm import validates

log = logging.getLogger(__name__)


def clip_string_columns(*columns: str) -> Any:
    """Build a `@validates` handler that trims the named columns.

    Usage, inside a model:

        _clip = clip_string_columns("name", "zone", "phone")

    The width comes from the column definition, so it cannot drift out of step
    with the schema the way a hand-written number would.
    """

    @validates(*columns)
    def _clip(self: Any, key: str, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        column = self.__table__.columns.get(key)
        if column is None:
            return value
        # Never an enum. `sa.Enum` subclasses `String` and carries a length
        # derived from the longest member, so it lands here looking like any
        # other bounded text — but truncating one turns a valid value into an
        # invalid one, which is the opposite of the trade this makes everywhere
        # else. Today every value is short enough that nothing happens; adding
        # one member spelled longer than the current longest would make this
        # quietly corrupt it, and the write would fail anyway with a value
        # nobody wrote.
        if isinstance(column.type, Enum):
            return value
        limit = getattr(column.type, "length", None)
        if limit is None or len(value) <= limit:
            return value
        log.warning(
            "%s.%s was %d characters, trimming to %d — the value is truncated, "
            "which is better than the write failing and taking the message with it",
            type(self).__name__,
            key,
            len(value),
            limit,
        )
        return value[:limit]

    return _clip


def bounded_string_columns(model: type) -> list[str]:
    """Every `String(n)` column on a model. Used by the test that pins this.

    A new bounded column added without being registered is a hole of exactly
    the kind this module exists to close, so the test walks the model rather
    than a list somebody has to remember to update.
    """
    return [
        column.key
        for column in model.__table__.columns
        if isinstance(column.type, String) and getattr(column.type, "length", None)
    ]
