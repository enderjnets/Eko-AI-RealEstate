"""FollowUp — a scheduled nurture message for a lead (Phase 10).

Enqueued when a visit is booked (a 24h-before reminder) and for the post-visit
sequence (24h / 72h / 7d after the visit). A background worker
(`app.services.followups.process_due_followups`) sends the ones whose
`scheduled_for` has passed, skipping leads on `human_takeover` and visits that
were cancelled. UNIQUE(visit_id, kind) keeps enqueueing idempotent.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, pg_enum

if TYPE_CHECKING:
    from app.models.lead import Lead


class FollowUpKind(str, enum.Enum):
    REMINDER_24H = "reminder_24h"        # 24h before a scheduled visit
    POST_VISIT_24H = "post_visit_24h"    # "how was it?"
    POST_VISIT_72H = "post_visit_72h"    # nudge if no reply
    POST_VISIT_7D = "post_visit_7d"      # "new similar listings"


class FollowUpStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    SKIPPED = "skipped"      # human takeover / lead replied / visit cancelled
    CANCELLED = "cancelled"
    FAILED = "failed"


class FollowUp(Base):
    __tablename__ = "follow_ups"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    visit_id: Mapped[int | None] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), nullable=True, index=True
    )

    kind: Mapped[FollowUpKind] = mapped_column(pg_enum(FollowUpKind, name="follow_up_kind"), nullable=False)
    status: Mapped[FollowUpStatus] = mapped_column(
        pg_enum(FollowUpStatus, name="follow_up_status"),
        default=FollowUpStatus.PENDING,
        nullable=False,
        index=True,
    )

    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    lead: Mapped["Lead"] = relationship("Lead", lazy="joined")

    __table_args__ = (
        UniqueConstraint("visit_id", "kind", name="uq_followups_visit_kind"),
    )

    def __repr__(self) -> str:
        return f"<FollowUp id={self.id} lead={self.lead_id} kind={self.kind.value} status={self.status.value}>"
