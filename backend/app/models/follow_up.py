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
    # Scheduled from the call console for a lead who is interested but not
    # ready. One per logged call: the console's own list is what brings them
    # back round after that, rather than a drip nobody chose.
    CALL_FOLLOW_UP = "call_follow_up"


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
    # Set instead of visit_id when the follow-up was scheduled from a logged
    # call rather than from a booking. Exactly one of the two is populated.
    call_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("call_logs.id", ondelete="CASCADE"), nullable=True, index=True
    )

    kind: Mapped[FollowUpKind] = mapped_column(pg_enum(FollowUpKind, name="follow_up_kind"), nullable=False)
    status: Mapped[FollowUpStatus] = mapped_column(
        pg_enum(FollowUpStatus, name="follow_up_status"),
        default=FollowUpStatus.PENDING,
        nullable=False,
        index=True,
    )

    # When this message is FOR. Written once, at enqueue, and never again — the
    # staleness rule and the operator console both need it to keep meaning that.
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # When to look at this row again, if something deferred it: a consent hold,
    # or the cap that stops a lead receiving two post-visit messages at once.
    # NULL means nothing has ever deferred it. Splitting this out of
    # `scheduled_for` is what lets "nobody has looked at this in a month" be
    # told apart from "deliberately postponed yesterday".
    postponed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
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
        # The visit constraint cannot protect a call-anchored follow-up:
        # Postgres treats two NULLs as distinct, so a row with visit_id NULL
        # never collides. Logging the same call twice would otherwise queue the
        # nudge twice, and the lead would get it twice.
        UniqueConstraint("call_log_id", "kind", name="uq_followups_call_kind"),
    )

    def __repr__(self) -> str:
        return f"<FollowUp id={self.id} lead={self.lead_id} kind={self.kind.value} status={self.status.value}>"
