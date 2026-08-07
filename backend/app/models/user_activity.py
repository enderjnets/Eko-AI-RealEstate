"""UserActivity — per-user engagement aggregate, keyed by email.

One row per known user (the email carried by their session token — Google/Apple
or a self-registered account; the shared office password has no email and is not
tracked). Updated by a lightweight middleware on each authenticated request +
on each login. Aggregate only (no per-event log) so the table stays small.
Admins view these stats in Settings to understand who's using the system.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserActivity(Base):
    __tablename__ = "user_activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # account|google|apple

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_active_day: Mapped[date | None] = mapped_column(Date, nullable=True)

    # {"leads": 42, "inbox": 5, "calendar": 3, ...} — hits per top-level section.
    sections: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    last_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    device: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<UserActivity {self.email!r} reqs={self.request_count} logins={self.login_count}>"
