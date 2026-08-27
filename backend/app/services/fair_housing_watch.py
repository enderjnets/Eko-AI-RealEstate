"""Tell the operator when a reply to a lead carried forbidden housing language.

`conversation.py` stamps `messages.fair_housing_flags` and sends anyway — that
is the deliberate design: a lead waiting on an answer does not get held behind a
review queue, and blocking would trade a compliance risk for a service outage.
The cost of that choice is that somebody has to be TOLD, out of band, or the
column is a log nobody reads. This module is that telling.

Two lessons from this repo are load-bearing here and neither is negotiable:

- **Alert on a CHANGE, never on a state.** Six correct alarms repeated every
  five minutes become background noise, and the outage they described went two
  days unnoticed. So: silence while the day stays flagged, one mail when a clean
  day turns flagged.
- **A state is only "reported" once the provider accepted it.** `alerted_state`
  advances on a 2xx and on nothing else, so a send that fails is retried by the
  next tick instead of being consumed. Same invariant as `llm_monitor`, same
  reason.

The body carries counts and categories per organization. It never carries the
message text: that is a client's conversation, and an operator alert is not the
place for it.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.db.base import get_bypass_session_factory
from app.models.message import Message, MessageDirection
from app.models.monitor_state import MonitorState
from app.services.ops_alert import (
    MAX_ALERTS_PER_DAY,
    send_operator_alert,
    undeliverable_reason,
)
from app.services.tenant_context import run_for_every_org

log = logging.getLogger(__name__)

WATCH_KEY = "fair_housing"

FLAGGED = "flagged"
CLEAN = "clean"


# A ROLLING 24-HOUR window, not the UTC calendar day, and the difference is two
# real defects rather than a preference:
#
#   1. A day-scoped reading flips to "clean" at 00:00 UTC whether or not the
#      alert it owed was ever delivered — so an undelivered warning was written
#      off at midnight, while the log still promised "will retry after the UTC
#      day rolls over". It could not.
#   2. Worse: a flagged reply landing in the up-to-300s gap between midnight and
#      the next tick was read as "still flagged" against yesterday's consumed
#      state, so it produced no alert — and since the reading could not return
#      to clean, neither did anything else for the rest of that day. In Denver
#      that window is 18:00-18:05, an active messaging hour.
#
# A sliding window has no boundary to fall through: the state stays flagged
# while there is anything to report, which is exactly when the retry should
# keep trying.
_WINDOW = timedelta(hours=24)


def _today_utc() -> str:
    """The budget's day. Budgets reset on a calendar boundary; readings do not."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


async def _load_or_create(session: Any) -> MonitorState:
    row = (
        await session.execute(select(MonitorState).where(MonitorState.key == WATCH_KEY))
    ).scalar_one_or_none()
    if row is None:
        row = MonitorState(key=WATCH_KEY)
        session.add(row)
        await session.flush()
    return row


def _budget_left(row: MonitorState) -> bool:
    """Is there room in today's alert budget?

    Shared shape with `llm_monitor._budget_left`, and shared quota with the
    mail that answers leads — which is why there is a cap at all.
    """
    if row.alerts_day != _today_utc():
        row.alerts_day = _today_utc()
        row.alerts_today = 0
    return row.alerts_today < MAX_ALERTS_PER_DAY


async def _flagged_today() -> dict[int, tuple[int, set[str]]]:
    """Flagged outbound messages written today, per organization.

    Selects the payload rather than a bare count because the alert has to name
    the categories — "three replies steered on neighbourhood" and "three replies
    named a religion" call for different conversations, and a number tells the
    operator neither.

    A background worker has no org bound and default-deny RLS would hand it zero
    rows in every tenant, silently. `run_for_every_org` walks them explicitly.
    """
    per_org: dict[int, tuple[int, set[str]]] = {}
    cutoff = datetime.now(UTC) - _WINDOW

    async def work(session: Any) -> None:
        rows = (
            await session.execute(
                select(Message.org_id, Message.fair_housing_flags).where(
                    # Length, not NOT NULL: a screened-clean reply is stored as
                    # `[]` so the audit trail can tell "checked, nothing found"
                    # from "never checked", and `[]` must not read as a hit.
                    func.jsonb_array_length(Message.fair_housing_flags) > 0,
                    Message.direction == MessageDirection.OUTBOUND,
                    Message.created_at >= cutoff,
                )
            )
        ).all()
        for org_id, flags in rows:
            count, cats = per_org.get(org_id, (0, set()))
            # Defensive about the payload's shape: this column is JSONB and a
            # future writer could put something else in it. A malformed row must
            # not take the watchdog down — that is the failure mode it exists to
            # prevent.
            if isinstance(flags, list):
                for item in flags:
                    if isinstance(item, dict) and item.get("category"):
                        cats.add(str(item["category"]))
            per_org[org_id] = (count + 1, cats)

    await run_for_every_org(work)
    return per_org


def _describe(per_org: dict[int, tuple[int, set[str]]]) -> tuple[str, str]:
    total = sum(count for count, _ in per_org.values())
    subject = f"[Eko Realtors] {total} reply(ies) flagged by the Fair Housing filter"
    lines = [
        f"{total} outbound reply(ies) written to leads in the last 24h carry "
        f"language the Fair Housing filter flagged.",
        "",
        "(\"Written\", not \"delivered\": this counts what the agent composed "
        "and handed to the channel. A few may have failed to send.)",
        "",
        "They WERE sent — this filter records, it does not block. Review them "
        "in the dashboard: the flagged messages carry an amber chip in the "
        "conversation view.",
        "",
    ]
    for org_id in sorted(per_org):
        count, cats = per_org[org_id]
        categories = ", ".join(sorted(cats)) or "unclassified"
        lines.append(f"  organization {org_id}: {count} message(s) — {categories}")
    lines += [
        "",
        "Note the filter's limit before drawing conclusions from a zero on any "
        "other day: it matches listed phrases, not paraphrase. Absence of a "
        "flag is not evidence of compliant language.",
    ]
    return subject, "\n".join(lines)


async def run_fair_housing_tick() -> str:
    """One pass: count today's flagged replies, and report the transition.

    Returns the reading so a caller can log or expose it. Signature mirrors
    `llm_monitor.run_monitor_tick` — no arguments, own sessions — so it can be
    driven from a worker loop or a test without an app running.
    """
    per_org = await _flagged_today()
    status = FLAGGED if per_org else CLEAN

    session_factory = get_bypass_session_factory()
    async with session_factory() as session:
        row = await _load_or_create(session)
        previous = row.alerted_state

        if row.state != status:
            log.info("Fair Housing daily state changed: %s -> %s", row.state, status)
        row.state = status

        # Going quiet is not news. A day that ends with nothing flagged consumes
        # the transition silently so that tomorrow's first flag is a change
        # again — without this, the watch would fire once and never again.
        if status == CLEAN:
            row.alerted_state = CLEAN
        elif status != previous:
            subject, body = _describe(per_org)
            undeliverable = undeliverable_reason()
            if undeliverable:
                # No number of attempts reaches anyone until a human edits the
                # configuration, so this is consumed rather than retried 288
                # times a day. Be honest about the cost, because it is higher
                # here than in `llm_monitor`: there, /api/v1/health carries the
                # live state so nothing is lost. There is no such compensating
                # readout for this watch yet (backlog), so with the alert
                # channel unconfigured a day of flagged replies survives only
                # in this log line and in `messages.fair_housing_flags`.
                log.error(
                    "Fair Housing: %d flagged reply(ies) today but the alert "
                    "channel cannot deliver (%s); not retrying.",
                    sum(c for c, _ in per_org.values()),
                    undeliverable,
                )
                row.alerted_state = status
            elif _budget_left(row):
                # The attempt is charged, not the delivery — same asymmetry as
                # `llm_monitor`: charging only successes means a failing send is
                # free, the budget never closes, and the retry becomes a loop
                # spending the quota that answers leads.
                row.alerts_today += 1
                row.last_alert_at = datetime.now(UTC)
                if await send_operator_alert(subject, body):
                    row.alerted_state = status
                else:
                    log.error(
                        "Fair Housing: alert did not go out; will retry "
                        "(attempt %d of %d today).",
                        row.alerts_today,
                        MAX_ALERTS_PER_DAY,
                    )
            else:
                log.error(
                    "Fair Housing: %d flagged reply(ies) today but the daily "
                    "alert budget (%d) is spent; will retry after the UTC day "
                    "rolls over.",
                    sum(c for c, _ in per_org.values()),
                    MAX_ALERTS_PER_DAY,
                )

        await session.commit()

    return status
