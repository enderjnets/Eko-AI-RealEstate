"""Organization — the tenant boundary.

One row per client agency. Robbie + Natalia are ONE organization with two users
who share leads, properties and social accounts; the boundary is the team, not
the person.

Two tables deliberately carry no `org_id` and are shared by every tenant:
`properties` and `sync_state`. There is a single REcolorado feed (we hold the
Software Vendor account) and therefore a single copy of the listings —
replicating them per tenant would multiply the database and blow MLS Grid's
4 GB/h bandwidth ceiling for nothing. Access is gated by whether the org holds
an active license, not by owning a private copy of the rows.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STATUS_ACTIVE = "active"
STATUS_TRIAL = "trial"
STATUS_SUSPENDED = "suspended"

PLAN_PILOT = "pilot"
PLAN_SUBSCRIPTION = "subscription"
PLAN_PER_LEAD = "per_lead"

# The org every pre-multi-tenant row is backfilled into, and the one Robbie and
# Natalia belong to. Pinned because migrations and the webhook fallback need a
# stable id before any self-service onboarding exists.
DEFAULT_ORG_ID = 1
# Public /register demo accounts land here so they see the seeded demo data
# instead of nothing — under default-deny RLS, a user with no org sees no rows.
DEMO_ORG_ID = 2


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE, nullable=False)
    plan: Mapped[str] = mapped_column(String(24), default=PLAN_PILOT, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug!r} status={self.status!r}>"
