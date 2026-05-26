"""phase7 properties USA — rework properties table for MLS/IDX (RESO) listings

The Phase 1 `properties` table was an EU placeholder (idealista/fotocasa, rooms,
m2) and is never populated before Phase 7, so we drop + recreate it with the
USA-oriented schema (RESO source, status, beds/baths/sqft, address, photos…).

Enum types are created explicitly with `checkfirst` and referenced with
`create_type=False` — robust across SQLAlchemy versions when dropping +
recreating a type of the same name in one migration.

Revision ID: 004_phase7_properties
Revises: 003_phase5_visits
Create Date: 2026-05-25 23:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_phase7_properties"
down_revision: Union[str, None] = "003_phase5_visits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE_VALUES = ("reso", "idx", "mls", "manual")
_STATUS_VALUES = ("active", "pending", "sold", "off_market")


def upgrade() -> None:
    bind = op.get_bind()

    # Placeholder table is empty before Phase 7 — safe to drop + recreate.
    op.drop_table("properties")
    op.execute("DROP TYPE IF EXISTS property_source")
    op.execute("DROP TYPE IF EXISTS property_status")

    property_source = postgresql.ENUM(*_SOURCE_VALUES, name="property_source")
    property_status = postgresql.ENUM(*_STATUS_VALUES, name="property_status")
    property_source.create(bind, checkfirst=True)
    property_status.create(bind, checkfirst=True)

    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", postgresql.ENUM(*_SOURCE_VALUES, name="property_source", create_type=False), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=False),
        sa.Column("status", postgresql.ENUM(*_STATUS_VALUES, name="property_status", create_type=False), nullable=False),
        sa.Column("title", sa.String(length=280), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("property_type", sa.String(length=60), nullable=True),
        sa.Column("address", sa.String(length=280), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=True),
        sa.Column("zip_code", sa.String(length=10), nullable=True),
        sa.Column("zone", sa.String(length=160), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("bedrooms", sa.Integer(), nullable=True),
        sa.Column("bathrooms", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("sqft", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("photos", sa.JSON(), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("listed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_properties_source_external_id"),
    )
    op.create_index("ix_properties_source", "properties", ["source"], unique=False)
    op.create_index("ix_properties_status", "properties", ["status"], unique=False)
    op.create_index("ix_properties_property_type", "properties", ["property_type"], unique=False)
    op.create_index("ix_properties_city", "properties", ["city"], unique=False)
    op.create_index("ix_properties_zone", "properties", ["zone"], unique=False)
    op.create_index("ix_properties_price", "properties", ["price"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_properties_price", table_name="properties")
    op.drop_index("ix_properties_zone", table_name="properties")
    op.drop_index("ix_properties_city", table_name="properties")
    op.drop_index("ix_properties_property_type", table_name="properties")
    op.drop_index("ix_properties_status", table_name="properties")
    op.drop_index("ix_properties_source", table_name="properties")
    op.drop_table("properties")
    op.execute("DROP TYPE IF EXISTS property_status")
    op.execute("DROP TYPE IF EXISTS property_source")

    # Recreate the original EU placeholder so downgrade is reversible.
    eu_source = postgresql.ENUM("idealista", "fotocasa", "manual", name="property_source")
    eu_source.create(bind, checkfirst=True)
    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", postgresql.ENUM("idealista", "fotocasa", "manual", name="property_source", create_type=False), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=280), nullable=False),
        sa.Column("zone", sa.String(length=160), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("rooms", sa.Integer(), nullable=True),
        sa.Column("m2", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_properties_source_external_id"),
    )
    op.create_index("ix_properties_source", "properties", ["source"], unique=False)
    op.create_index("ix_properties_zone", "properties", ["zone"], unique=False)
