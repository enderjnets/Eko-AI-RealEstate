"""Writing a lead's history.

One function, and the reason it exists rather than `db.add(LeadEvent(...))` at
twenty call sites is `org_id`: the `before_flush` listener that stamps it only
runs on request sessions, and half the writers here are background workers on
bypass sessions where nothing stamps anything. Every event therefore carries an
explicit org, resolved here, once.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.models.lead_event import LEAD_EVENT_TYPES, LeadEvent
from app.services.tenant_context import get_org_id

log = logging.getLogger(__name__)


def record(
    db: Any,
    lead: Any,
    type: str,
    *,
    actor: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    meta: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> LeadEvent | None:
    """Add one history row for `lead`. Does not commit.

    Returns the row, or `None` when it could not be written — which happens for
    exactly two reasons, both logged: there is no lead (a calendar entry with
    nobody attached), or no organization could be resolved. Neither is worth
    raising for. **Analytics must never be able to take down the thing it is
    measuring**: losing the record of a call is bad, losing the call is worse.
    """
    if lead is None:
        log.warning("Lead event %r has no lead to attach to; not recorded", type)
        return None
    if type not in LEAD_EVENT_TYPES:
        # A raise, unlike the returns above: an unknown name is a typo at the
        # call site, it fails on the first run, and a silent skip would show up
        # months later as a report that is quietly missing a column.
        raise ValueError(f"Unknown lead event type: {type!r}")

    # The lead's own org first, the acting org second. A new Lead in a request
    # session still has `org_id = None` at this point — that is precisely what
    # `_stamp_org_id` exists to fill — and the order in which two `before_flush`
    # listeners run is not guaranteed. Reading the context var as the fallback
    # makes this independent of that order.
    org_id = getattr(lead, "org_id", None) or get_org_id()
    if org_id is None:
        log.warning("Lead event %r has no organization; not recorded", type)
        return None

    event = LeadEvent(
        org_id=org_id,
        lead=lead,
        type=type,
        at=at or datetime.now(UTC),
        actor=actor,
        from_status=from_status,
        to_status=to_status,
        meta=meta or None,
    )
    db.add(event)
    return event
