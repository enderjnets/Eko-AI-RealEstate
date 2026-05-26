"""Property — a real-estate listing ingested from an MLS / IDX feed.

Phase 7 (USA pivot): listings come from a RESO Web API feed (the USA standard),
an IDX provider, or are entered manually. The agent matches active listings to a
lead's criteria (zone, budget, beds) and the realtor can recommend them from the
dashboard. Populated by `app.services.listings.sync_listings` (SIMULATED in dev).
"""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pg_enum


class PropertySource(str, enum.Enum):
    RESO = "reso"      # RESO Web API (OData) — the modern USA MLS standard
    IDX = "idx"        # generic IDX feed
    MLS = "mls"        # other direct MLS export
    MANUAL = "manual"  # entered by the realtor


class PropertyStatus(str, enum.Enum):
    ACTIVE = "active"
    PENDING = "pending"        # under contract
    SOLD = "sold"
    OFF_MARKET = "off_market"


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[PropertySource] = mapped_column(
        pg_enum(PropertySource, name="property_source"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)

    status: Mapped[PropertyStatus] = mapped_column(
        pg_enum(PropertyStatus, name="property_status"),
        default=PropertyStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(280), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    property_type: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)

    # Location. `zone` is the neighborhood (Brickell, Coral Gables…) — the key the
    # lead's `zone` is matched against.
    address: Mapped[str | None] = mapped_column(String(280), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    zone: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)

    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True, index=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)  # USA half-baths (2.5)
    sqft: Mapped[int | None] = mapped_column(Integer, nullable=True)

    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photos: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_properties_source_external_id"),
    )

    def __repr__(self) -> str:
        return f"<Property id={self.id} {self.source.value}:{self.external_id} {self.status.value}>"
