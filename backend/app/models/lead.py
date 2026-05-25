"""Lead — one row per real-estate prospect that contacted us on WhatsApp."""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, pg_enum

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class LeadStatus(str, enum.Enum):
    NEW = "new"
    QUALIFIED = "qualified"
    VISITING = "visiting"
    POST_VISIT = "post_visit"
    WON = "won"
    LOST = "lost"
    PAUSED = "paused"


class LeadIntent(str, enum.Enum):
    RENT = "rent"
    BUY = "buy"
    VALUATION = "valuation"
    OTHER = "other"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[LeadStatus] = mapped_column(
        pg_enum(LeadStatus, name="lead_status"),
        default=LeadStatus.NEW,
        nullable=False,
        index=True,
    )
    intent: Mapped[LeadIntent | None] = mapped_column(
        pg_enum(LeadIntent, name="lead_intent"),
        nullable=True,
    )

    budget_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    budget_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    zone: Mapped[str | None] = mapped_column(String(160), nullable=True)
    property_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(40), nullable=True)

    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    human_takeover: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="lead",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_leads_status_last_message_at", "status", "last_message_at"),
    )

    def __repr__(self) -> str:
        return f"<Lead id={self.id} phone={self.phone} status={self.status.value}>"
