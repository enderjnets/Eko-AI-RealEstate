"""SyncState — replication cursor + run metadata for external data feeds.

One row per feed source (e.g. ``"reso"``). The listings sync worker reads the last
processed ``ModificationTimestamp`` to fetch only the delta (MLS Grid replication),
and writes it back **only after the batch commits** — so a crash re-fetches from the
last durable point instead of silently skipping records. Filtering the feed with
``ge`` (≥) on the cursor + the idempotent upsert absorbs any boundary records that
share the cursor's exact timestamp.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncState(Base):
    """Per-feed replication state. Keyed by `source`."""

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Feed key, e.g. "reso". Unique so there is exactly one cursor per feed.
    source: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    # Last ModificationTimestamp actually PERSISTED (advanced only post-commit).
    cursor_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Observability for the background worker / a future health-check.
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_created: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    last_updated: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SyncState source={self.source} cursor={self.cursor_modified_at}>"
