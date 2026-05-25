"""Property — placeholder for Phase 4 (Idealista / Fotocasa scrapers).

Schema defined now so the migration baseline is complete; population logic
arrives with the scrapers in Phase 4.
"""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pg_enum


class PropertySource(str, enum.Enum):
    IDEALISTA = "idealista"
    FOTOCASA = "fotocasa"
    MANUAL = "manual"


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[PropertySource] = mapped_column(
        pg_enum(PropertySource, name="property_source"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(280), nullable=False)
    zone: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    rooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    m2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_properties_source_external_id"),
    )

    def __repr__(self) -> str:
        return f"<Property id={self.id} {self.source.value}:{self.external_id}>"
