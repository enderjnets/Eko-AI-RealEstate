"""AgentCalendar — the link between one person, one kind of appointment, and
the Cal.com objects that own their schedule.

Read the absence first, because it is the design: **this table stores no
hours.** Recurring weekly windows, timezones, DST, buffers, minimum notice and
conflicts against a real calendar all live in Cal.com, which already implements
them. Storing windows here too would make a fourth answer to "when can this be
booked", and the product already has three that disagree:

  * `agent_settings.business_hours` — per ORG, and its only reader
    (`conversation.py::_office_hours_note`) pastes it into the LLM prompt as
    prose. It filters nothing. It is a different question and it stays.
  * `calendar_cal.SIMULATED_HOURS_OF_DAY` — a fixed tuple, used only while
    CALENDAR_SIMULATED is on.
  * The Cal.com schedule itself.

So what is ours here is the *mapping and the identity*; what is Cal.com's is
time. If this file ever grows a `start_time` column, that reasoning was lost.

Keyed on the login email rather than an account id: sessions carry the email
(`services/auth.py::token_email`) and `allowed_users.email` is what grants
access, so a row cannot belong to somebody who cannot sign in. There is
deliberately no foreign key to `allowed_users` — revoking a person's access must
not delete the schedule that their already-booked visits were made against.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pg_enum


class AppointmentActivity(str, enum.Enum):
    """What kind of appointment this is — each has its own windows and length.

    Shared with `Visit.purpose`, so a booking records which kind it was. The
    seller-facing one matters most to this business and is the reason the
    product could not simply keep one type: `VALUATION` is the appointment
    where an agent visits a homeowner to price their house, and until now it
    was booked as if it were a buyer's showing.
    """

    SHOWING = "showing"          # buyer visits a property
    VALUATION = "valuation"      # agent visits a seller to price their home
    CALL = "call"                # phone/video consultation, no travel
    OPEN_HOUSE = "open_house"    # agent blocks a slot at a property


# Sensible starting lengths per activity, used when provisioning a calendar the
# first time. The agent can change them afterwards; these only decide what the
# first Cal.com event type looks like, so nobody starts from a blank form.
DEFAULT_DURATION_MINUTES: dict[AppointmentActivity, int] = {
    AppointmentActivity.SHOWING: 45,
    AppointmentActivity.VALUATION: 60,
    AppointmentActivity.CALL: 20,
    AppointmentActivity.OPEN_HOUSE: 180,
}


class AgentCalendar(Base):
    __tablename__ = "agent_calendars"
    __table_args__ = (
        # One row per person per kind of appointment. This is what makes
        # provisioning idempotent: a second `ensure_calendars` for the same pair
        # collides here instead of creating a second Cal.com schedule.
        UniqueConstraint("org_id", "email", "activity", name="uq_agent_calendar"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # No `index=True`: the UNIQUE constraint below is a btree on
    # (org_id, email, activity) and its prefixes already serve every lookup
    # this table gets. Declaring one here created drift — the model asked
    # for an index the migration never built.
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    activity: Mapped[AppointmentActivity] = mapped_column(
        pg_enum(AppointmentActivity, name="appointment_activity"), nullable=False
    )

    # Opaque handles from Cal.com — text, because nothing here does arithmetic
    # on them. Nullable so a row can exist before provisioning succeeds; the
    # service treats "no event type id" as "not bookable yet", never as an
    # error to hide.
    calcom_schedule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    calcom_event_type_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    duration_minutes: Mapped[int] = mapped_column(Integer, default=45, nullable=False)

    # Turned off rather than deleted, so the Cal.com ids survive and turning it
    # back on is not a re-provision.
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AgentCalendar {self.email!r} {self.activity} et={self.calcom_event_type_id}>"
