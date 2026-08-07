"""Visit — one row per scheduled property visit between a Lead and the agency.

Created when the realtor books a slot from the dashboard (Phase 5), or when
the AI agent confirms a booking in a future phase. Bookings are mirrored to
Cal.com / Google Calendar via the provider stored in `calendar_provider` +
`external_booking_id`.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, pg_enum

if TYPE_CHECKING:
    from app.models.lead import Lead


class VisitStatus(str, enum.Enum):
    SCHEDULED = "scheduled"      # booked, hasn't happened yet
    CONFIRMED = "confirmed"      # lead explicitly confirmed (e.g., reminder reply)
    CANCELLED = "cancelled"      # cancelled by lead or realtor before the visit time
    COMPLETED = "completed"      # visit happened (set manually or by post-visit follow-up)
    NO_SHOW = "no_show"          # lead didn't show up


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable: a lead's property visit links to its lead; a MANUAL calendar event
    # (open house, team meeting, ...) created by the realtor has no lead.
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Title for manual events (NULL for lead visits, which derive their label from
    # the lead + scheduled time).
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Provider + external id (mirrored to Cal.com / Google Calendar). For
    # SIMULATED bookings the external_booking_id is `calcom-sim-<uuid>` so the
    # cancel/lookup flow still works.
    calendar_provider: Mapped[str] = mapped_column(String(20), default="calcom", nullable=False)
    external_booking_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    status: Mapped[VisitStatus] = mapped_column(
        pg_enum(VisitStatus, name="visit_status"),
        default=VisitStatus.SCHEDULED,
        nullable=False,
        index=True,
    )

    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)

    property_address: Mapped[str | None] = mapped_column(String(280), nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    lead: Mapped["Lead"] = relationship("Lead", back_populates="visits", lazy="joined")

    def __repr__(self) -> str:
        return f"<Visit id={self.id} lead={self.lead_id} when={self.scheduled_at} status={self.status.value}>"
