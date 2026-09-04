"""What a visitor did on the landing page, before there was a lead.

See `migrations/versions/20260904_1000_landing_sessions.py` for why these exist
and what is deliberately not stored (no cookie, no IP, no raw user agent).

`LandingSession` is the rolled-up row a report reads; `LandingEvent` is the raw
stream behind it, deleted after a retention window. Reports must never sum the
events: the session carries the same facts already merged, and an event stream
that is purged on a schedule would make last quarter's numbers change.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# The only event names the API accepts. A closed set rather than free text: an
# unknown name is a client bug or somebody poking the endpoint, and either way
# it should be refused at the door instead of becoming a row nobody can group.
LANDING_EVENT_TYPES = frozenset(
    {
        "page_view",
        "section_view",
        "scroll",
        "cta_click",
        "tel_click",
        "form_start",
        "form_submit",
        "form_error",
    }
)

# Sections of the page an IntersectionObserver can report. Also a closed set,
# for the same reason and because the analytics reads them by name.
LANDING_SECTIONS = ("about", "how", "markets", "consult")


class LandingSession(Base):
    __tablename__ = "landing_sessions"
    __table_args__ = (
        # Per organization, not global: the key is a random value the browser
        # invented, with no authority behind it. Scoped, two agencies cannot
        # collide into one row by chance.
        UniqueConstraint("org_id", "session_key", name="uq_landing_session"),
        Index("ix_landing_sessions_org_first_seen", "org_id", "first_seen_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_key: Mapped[str] = mapped_column(Text, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    landing_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    lang: Mapped[str | None] = mapped_column(Text, nullable=True)

    utm_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_term: Mapped[str | None] = mapped_column(Text, nullable=True)
    referrer_host: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="direct")

    device: Mapped[str | None] = mapped_column(Text, nullable=True)
    browser: Mapped[str | None] = mapped_column(Text, nullable=True)
    os: Mapped[str | None] = mapped_column(Text, nullable=True)
    in_app: Mapped[str | None] = mapped_column(Text, nullable=True)

    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)

    screen_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_scroll_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    sections_viewed: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cta_clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tel_clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    form_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    form_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lead_id: Mapped[int | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )

    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

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
        return f"<LandingSession id={self.id} source={self.source} lead={self.lead_id}>"


class LandingEvent(Base):
    __tablename__ = "landing_events"
    __table_args__ = (Index("ix_landing_events_org_at", "org_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("landing_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<LandingEvent id={self.id} type={self.type} session={self.session_id}>"
