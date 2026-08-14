"""CallLog — what an advisor learned on a call, and what it set in motion.

One row per call the office logs from the console. The *state* it reveals — the
lead's intent, budget, zone, urgency, preferred channel — is written onto the
`Lead` itself, because that is where `match_properties_for_lead` and
`compute_lead_score` already read from. Keeping a parallel copy here would need
somebody to reconcile the two, and nobody would.

So this table is history, not state: who called, when, how it went, and any
note. It is also the anchor for the follow-up a call schedules, which is why
`follow_ups.call_log_id` points back at it.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, pg_enum

if TYPE_CHECKING:
    from app.models.lead import Lead


class CallOutcome(str, enum.Enum):
    """How the call ended. Each value is a trigger, not a filing category —
    `services/calls.py` turns exactly one of these into exactly one action."""

    WANTS_LISTINGS = "wants_listings"      # send options, then decide on a showing
    BOOKED_VISIT = "booked_visit"          # a showing was agreed on the call
    FOLLOW_UP = "follow_up"                # interested, not now — nurture
    NO_ANSWER = "no_answer"                # nobody picked up; try again
    HAS_AGENT = "has_agent"                # NAR Article 16: stand down
    DO_NOT_CONTACT = "do_not_contact"      # asked us to stop
    WRONG_NUMBER = "wrong_number"          # this number is not the lead


class CallLog(Base):
    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Who logged it. Free text rather than a foreign key: the office signs in
    # with Google or with the shared password, so there is not always a row to
    # point at, and losing the attribution would be worse than storing a string.
    logged_by: Mapped[str | None] = mapped_column(String(254), nullable=True)

    outcome: Mapped[CallOutcome] = mapped_column(
        pg_enum(CallOutcome, name="call_outcome"), nullable=False, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lead: Mapped["Lead"] = relationship("Lead", lazy="joined")

    def __repr__(self) -> str:
        return f"<CallLog id={self.id} lead={self.lead_id} outcome={self.outcome.value}>"
