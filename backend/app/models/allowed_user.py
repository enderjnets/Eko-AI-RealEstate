"""AllowedUser — the database-backed access list for Google Sign In.

Each row is an email allowed to log in via Google, with a role (`admin` |
`member`). Admins manage this list from the Settings → Team panel. Bootstrap
admins pinned in `GOOGLE_ADMIN_EMAILS` are seeded here on startup and treated as
immutable by the API (can't be demoted or removed) so the office can't lock
itself out.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"


class AllowedUser(Base):
    __tablename__ = "allowed_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_MEMBER, nullable=False)
    added_by: Mapped[str | None] = mapped_column(String(254), nullable=True)

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
        return f"<AllowedUser {self.email!r} role={self.role!r}>"
