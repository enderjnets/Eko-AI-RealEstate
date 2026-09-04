"""What happened to a lead, in order.

See `migrations/versions/20260904_1400_lead_events.py` for why the columns are
shaped this way — in particular why `actor` is text rather than a user id, and
why the statuses are text rather than the enum.

Rows are written by `app/services/lead_events.record` and by the `before_flush`
listener in `app/db/base.py`. Nothing updates them: a history that can be
edited is not a history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# The closed set of things that can happen. Closed rather than free text for the
# same reason the landing events are: an unrecognised name is a bug at the call
# site, and a typo that becomes a row is a gap in a report nobody will notice —
# the count is simply lower than the truth.
LEAD_EVENT_TYPES = frozenset(
    {
        "created",
        "status_changed",
        "call_inbound",
        "call_logged",
        "appointment_set",
        "appointment_cancelled",
        "appointment_outcome",
        "deal_closed",
    }
)


class LeadEvent(Base):
    __tablename__ = "lead_events"
    __table_args__ = (
        Index("ix_lead_events_org_at", "org_id", "at"),
        Index("ix_lead_events_lead_at", "lead_id", "at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The relationship, not just the id: a lead created in the same flush has no
    # id yet, and assigning `lead=lead` lets SQLAlchemy fill it in afterwards.
    lead: Mapped[Any] = relationship("Lead")

    type: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<LeadEvent {self.type} lead={self.lead_id} at={self.at}>"
