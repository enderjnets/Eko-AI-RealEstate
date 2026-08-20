"""The content rail: a piece of short-form video, and where it went.

Two tables because they answer two different questions. `content_pieces` is the
thing that was made and whether a person has agreed to it; `content_publications`
is one attempt to put that thing on one platform. Folding the second into the
first would mean a piece that reached YouTube and failed on TikTok has no honest
status to be in.

The approval gate is the reason this exists at all. Everything here is real
estate advertising by licensed agents, where a phrase an engagement-optimising
model produces by default — "perfect for families", "safe neighborhood", "good
schools" — is a Fair Housing violation, and the exposure lands on the broker's
licence rather than on us. So `APPROVED` is a state only a person can set, and
nothing may be published from any other state.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, pg_enum
from app.db.text_limits import clip_string_columns

if TYPE_CHECKING:
    pass


class ContentKind(str, enum.Enum):
    GENERATED = "generated"  # written and rendered by us
    RECORDED = "recorded"    # a clip the agent filmed on their phone


class ContentLanguage(str, enum.Enum):
    EN = "en"
    ES = "es"


class ContentStatus(str, enum.Enum):
    """The only path to PUBLISHED runs through a person.

    DRAFT is where a piece waits when the Fair Housing filter found something:
    it carries its `violations` and needs a human edit. It never reaches
    NEEDS_APPROVAL on its own.
    """

    DRAFT = "draft"
    NEEDS_APPROVAL = "needs_approval"
    APPROVED = "approved"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"


class PublicationPlatform(str, enum.Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


class PublicationStatus(str, enum.Enum):
    PENDING = "pending"
    # Claimed before the outbound call, so a crash cannot be mistaken for
    # "never attempted" and retried into a double post.
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class ContentPiece(Base):
    __tablename__ = "content_pieces"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind: Mapped[ContentKind] = mapped_column(
        pg_enum(ContentKind, name="content_kind"), nullable=False
    )
    language: Mapped[ContentLanguage] = mapped_column(
        pg_enum(ContentLanguage, name="content_language"), nullable=False
    )
    status: Mapped[ContentStatus] = mapped_column(
        pg_enum(ContentStatus, name="content_status"),
        nullable=False,
        default=ContentStatus.DRAFT,
        index=True,
    )

    hook: Mapped[str | None] = mapped_column(String(300), nullable=True)
    script: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Path inside the media volume, never a URL: the file is served through an
    # authenticated route so an unlisted link cannot leak a client's footage.
    media_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # What the Fair Housing filter found, kept on the row so the person editing
    # sees the reason rather than a bare refusal.
    violations: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Identity of the person who approved, not a boolean. "Somebody approved it"
    # is not an answer anyone can act on when a broker asks who did.
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Eager ("selectin"), not lazy: the API serialises pieces with their
    # publications, and a lazy relationship read from an async session raises
    # MissingGreenlet the first time anything touches it after a commit.
    publications: Mapped[list[ContentPublication]] = relationship(
        back_populates="piece", cascade="all, delete-orphan", lazy="selectin"
    )

    # The hook is written by a language model, which does not count characters
    # and will happily return 400 of them for a 300-character column. Losing a
    # draft to a database error is worse than losing its last few words, and a
    # person reviews every one of these before it goes anywhere.
    _clip = clip_string_columns("hook", "media_path", "approved_by")


class ContentPublication(Base):
    __tablename__ = "content_publications"
    __table_args__ = (
        # Idempotency lives here rather than in the publisher. A retry, a second
        # worker and a double click all arrive as the same insert, and the
        # database is the only participant that sees all three.
        UniqueConstraint("piece_id", "platform", name="uq_content_publication"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    piece_id: Mapped[int] = mapped_column(
        ForeignKey("content_pieces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    platform: Mapped[PublicationPlatform] = mapped_column(
        pg_enum(PublicationPlatform, name="publication_platform"), nullable=False
    )
    status: Mapped[PublicationStatus] = mapped_column(
        pg_enum(PublicationStatus, name="publication_status"),
        nullable=False,
        default=PublicationStatus.PENDING,
        index=True,
    )

    # Text, not a bounded column. This is the handle that finds the post again
    # on the platform, so clipping it produces a wrong id rather than a short
    # one — and letting an over-long value raise would take down the very
    # transaction that records "this went out", which is how the same video
    # gets posted twice. The platform decides this length, so we do not cap it.
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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

    piece: Mapped[ContentPiece] = relationship(back_populates="publications")
