"""Is Buffer still taking our token?

From 26-sep to 3-oct 2026 Buffer answered every call with 401 "Access token is
not valid" and nobody knew for five days. The posts already queued inside
Buffer kept going out on their own, so the accounts looked alive until the
queue ran dry; meanwhile eight approved pieces sat here unsent. The only trace
was a WARNING line every fifteen minutes in a log nobody reads.

What is watched is Buffer's own answer, recorded by `_graphql` on every call:
a 401 starts a streak, anything Buffer accepts ends it. One 401 is not yet an
alert — the streak has to outlive one pass of the publish worker — and a quiet
rail with nothing to send leaves the streak as it was, because silence is not
evidence either way.

The alerting mechanics are render_watch's: a change of state is reported,
`alerted_state` only advances when the alert was accepted, and the daily budget
belongs to this row alone. One addition: while the token is still refused, the
alert is repeated once a day, because a single message about a fault that
lasts five days is a message somebody missed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.base import get_bypass_session_factory
from app.models.monitor_state import MonitorState
from app.services.ops_alert import MAX_ALERTS_PER_DAY, send_operator_alert

log = logging.getLogger(__name__)

KEY = "buffer_auth"

# One pass of the publish worker is 15 minutes: a refusal still there after
# that was seen by at least two passes.
REFUSED_FOR = timedelta(minutes=15)

REMIND_EVERY = timedelta(hours=24)

_refused_since: datetime | None = None


def record_answer(status_code: int, now: datetime | None = None) -> None:
    """What Buffer said to one call. Called by `_graphql`; never raises."""
    global _refused_since
    if status_code == 401:
        if _refused_since is None:
            _refused_since = now or datetime.now(UTC)
    elif status_code < 400:
        _refused_since = None


def refused_since() -> datetime | None:
    return _refused_since


def status(now: datetime) -> str:
    if _refused_since is not None and now - _refused_since >= REFUSED_FOR:
        return "refused"
    return "ok"


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


async def _row(db) -> MonitorState:
    row = (
        await db.execute(select(MonitorState).where(MonitorState.key == KEY))
    ).scalar_one_or_none()
    if row is None:
        row = MonitorState(key=KEY, state="ok", alerted_state="ok")
        db.add(row)
        await db.commit()
    return row


def _message(state: str, since: datetime | None) -> tuple[str, str]:
    if state == "refused":
        when = since.strftime("%Y-%m-%d %H:%M UTC") if since else "recently"
        return (
            "Buffer is refusing the access token - nothing new is being published",
            f"Since {when}, Buffer answers 401 \"Access token is not valid\".\n\n"
            "Posts already queued inside Buffer still go out on their own. "
            "Approved pieces are NOT being sent, and nothing is marked as "
            "published.\n\n"
            "Fix: in Buffer (Denver Home Story account) create a new API key, "
            "then on the Mac run, in one line:\n"
            "read -rs \"T?Token nuevo de Buffer: \" && echo && printf '%s' \"$T\" "
            "| ssh ender-vps 'bash ~/bin/dhs-buffer-token.sh'; unset T",
        )
    return (
        "Buffer accepts the token again",
        "Buffer is answering again. Approved pieces will be sent on the next "
        "pass of the publish worker.",
    )


async def run_buffer_watch_tick(now: datetime | None = None) -> None:
    """One look. Never raises — a watcher that dies stops watching."""
    try:
        now = now or datetime.now(UTC)
        state = status(now)
        async with get_bypass_session_factory()() as db:
            row = await _row(db)
            row.state = state
            previous = row.alerted_state

            if previous is None:
                row.alerted_state = state
                await db.commit()
                return

            reminder = (
                state == "refused"
                and previous == "refused"
                and row.last_alert_at is not None
                and now - row.last_alert_at >= REMIND_EVERY
            )
            if state == previous and not reminder:
                await db.commit()
                return

            if row.alerts_day != _today():
                row.alerts_day = _today()
                row.alerts_today = 0
            if row.alerts_today >= MAX_ALERTS_PER_DAY:
                log.error("Buffer went %s and the daily alert budget is spent", state)
                await db.commit()
                return

            subject, body = _message(state, _refused_since)
            if await send_operator_alert(subject, body):
                row.alerted_state = state
                row.alerts_today += 1
                row.last_alert_at = now
            else:
                log.error("Buffer alert (%s) could not be delivered", state)
            await db.commit()
    except Exception:  # noqa: BLE001 — the watcher must survive everything
        log.exception("Buffer watch tick failed")
