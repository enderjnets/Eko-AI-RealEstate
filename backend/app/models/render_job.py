"""A unit of video work waiting for the machine that can do it.

See `migrations/versions/20260830_1200_render_jobs.py` for why the work leaves
this box at all. The short version: subtitles need a speech model and generated
video needs minutes of CPU and a media stack, and neither belongs next to the
process a lead is waiting on.

The row is the whole protocol. A worker claims one, does the work, and hands
back a file; if it dies, the claim goes stale and the job returns to the queue.
Nothing here knows what a worker is or where it runs.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pg_enum


class RenderJobKind(str, enum.Enum):
    # Lane A: an uploaded clip becomes a vertical, subtitled, signed video.
    SUBTITLE_A = "subtitle_a"
    # Lane B: a written script becomes a video — narration, visuals, assembly.
    PRODUCE_B = "produce_b"


class RenderJobStatus(str, enum.Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    DONE = "done"
    FAILED = "failed"


class RenderJob(Base):
    __tablename__ = "render_jobs"
    __table_args__ = (
        # A piece needs each kind of work at most once. The constraint, not the
        # code, is what makes "enqueue if missing" idempotent across restarts
        # and across two ticks that overlap.
        UniqueConstraint("piece_id", "kind", name="uq_render_job"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    piece_id: Mapped[int] = mapped_column(
        ForeignKey("content_pieces.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[RenderJobKind] = mapped_column(
        pg_enum(RenderJobKind, name="render_job_kind"), nullable=False
    )
    status: Mapped[RenderJobStatus] = mapped_column(
        pg_enum(RenderJobStatus, name="render_job_status"),
        nullable=False,
        default=RenderJobStatus.QUEUED,
        index=True,
    )

    # Who holds it and since when. Both NULL on an unclaimed job: a placeholder
    # would make "nobody has this" look like "somebody nameless has this".
    worker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # What the worker is doing right now, and roughly how far along. Written
    # by the worker as it goes; NULL on any row that never reported one.
    stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    progress: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
