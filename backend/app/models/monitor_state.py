"""MonitorState — what the watchdog saw last time, so it can tell what changed.

One row per watched thing, keyed by `key` (today: ``"llm_fallback"``). It exists
for one reason: **an alert must fire on a CHANGE of state, never on the state
itself.** Six correct alarms repeated on a schedule stop being alarms and become
background noise — that lesson was paid for elsewhere and is not worth paying
twice. Comparing against a previous value is the whole design, and a previous
value has to survive a restart or a crash-looping process emails on every boot.

Deliberately **shared and not tenant-owned**: no ``org_id`` and no RLS policy,
like ``properties`` and ``sync_state``. The health of the LLM chain is a
property of the installation, not of any one agency, and giving it an org would
mean every tenant carrying a copy of a fact none of them own. The migration
therefore has to GRANT the app role DML explicitly — since migration 019 new
tables get nothing by default, precisely so that this decision is visible next
to the table that made it.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MonitorState(Base):
    """Last observed state of one watched thing. Keyed by `key`."""

    __tablename__ = "monitor_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # What is being watched, e.g. "llm_fallback". Unique: one row per subject.
    key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    # The last value we alerted about — the thing a new reading is compared to.
    state: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Rate limiting, kept here rather than in memory for the same reason as
    # `state`: a process that restarts must not get a fresh budget to spend.
    last_alert_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    alerts_today: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # UTC date the counter above belongs to, as YYYY-MM-DD. A date, not a
    # rolling window: it lines up with how the email provider resets its quota.
    alerts_day: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # High-water mark for the ground-truth sweep: the newest canned reply we
    # have already reported. Without it the same collapsed conversation would
    # be re-reported on every tick for as long as it stays in the window.
    last_seen_fallback_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
