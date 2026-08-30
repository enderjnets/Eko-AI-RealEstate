"""Is the render machine still there?

A queue with nobody working it looks exactly like a quiet queue, and that is
the whole problem: the console shows clips waiting, the logs show nothing, and
the first person to notice is the agency asking why their video never appeared.

The worker cannot report its own death, so what is watched is its heartbeat —
and only in the state where absence means something. A worker that is idle
because there is nothing to do is not a fault; a worker that is silent while
jobs are queued is. That distinction is the difference between a useful alert
and one people learn to ignore, which this project has already paid for once.

The alerting mechanics are the ones from v0.54.4 and they are not re-invented
here: state changes are reported, `alerted_state` only advances when the mail
was actually accepted, and the daily budget belongs to this row alone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.base import get_bypass_session_factory
from app.models import RenderJob, RenderJobStatus
from app.models.monitor_state import MonitorState
from app.services.ops_alert import MAX_ALERTS_PER_DAY, send_operator_alert

log = logging.getLogger(__name__)

KEY = "render_worker"

# How long a queue may go unworked before it is a fault. Generous: a generated
# video takes minutes, the worker only runs inside its allowed hours, and the
# gap between two of those windows is hours by design.
SILENCE = timedelta(hours=3)


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


async def record_heartbeat(worker: str) -> None:
    """The worker says it is alive. Stored, not judged."""
    async with get_bypass_session_factory()() as db:
        row = await _row(db)
        row.last_heartbeat_at = datetime.now(UTC)
        await db.commit()
    log.debug("Render worker %s checked in", worker)


async def run_render_watch_tick() -> None:
    """One look. Never raises — a watcher that dies stops watching.

    No arguments, and it makes its own session: it is called from the monitor
    loop, which has no organization, and `render_jobs` is read on the bypass
    engine for the same reason the other sweeps do it.
    """
    try:
        now = datetime.now(UTC)
        async with get_bypass_session_factory()() as db:
            waiting = (
                await db.execute(
                    select(func.count())
                    .select_from(RenderJob)
                    .where(
                        RenderJob.status.in_(
                            (RenderJobStatus.QUEUED, RenderJobStatus.CLAIMED)
                        )
                    )
                )
            ).scalar_one()

            row = await _row(db)
            last_seen = row.last_heartbeat_at

            # Silence with nothing to do is not a fault. This is the whole
            # difference between an alert worth reading and one that fires
            # every night the queue happens to be empty.
            if waiting == 0:
                status = "ok"
            elif last_seen is None or (now - last_seen) > SILENCE:
                status = "stalled"
            else:
                status = "ok"

            row.state = status
            previous = row.alerted_state

            if previous is None:
                # First reading. A fresh deploy does not greet anyone.
                row.alerted_state = status
                await db.commit()
                return

            if status == previous:
                await db.commit()
                return

            if row.alerts_day != _today():
                row.alerts_day = _today()
                row.alerts_today = 0
            if row.alerts_today >= MAX_ALERTS_PER_DAY:
                log.error(
                    "Render worker went %s and the daily alert budget is spent",
                    status,
                )
                await db.commit()
                return

            if status == "stalled":
                subject = "Render worker silent while clips are waiting"
                body = (
                    f"{waiting} render job(s) are queued or claimed and the "
                    f"worker has not checked in for more than "
                    f"{int(SILENCE.total_seconds() // 3600)} hours.\n\n"
                    "The videos are not lost — they are waiting. On the render "
                    "machine: systemctl --user status eko-render-worker"
                )
            else:
                subject = "Render worker is back"
                body = "The render worker is checking in again and the queue is moving."

            sent = await send_operator_alert(subject, body)
            if sent:
                # Only a delivered alert consumes the change. An undelivered
                # one is retried next tick, which is the invariant v0.54.4 was
                # written for: a fault nobody heard about is not reported.
                row.alerted_state = status
                row.alerts_today += 1
                row.last_alert_at = now
            else:
                log.error("Render worker alert (%s) could not be delivered", status)
            await db.commit()
    except Exception:  # noqa: BLE001 — the watcher must survive everything
        log.exception("Render watch tick failed")
