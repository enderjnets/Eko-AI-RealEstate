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
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as text_sql
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
    # Accepted by Buffer and held for a future time. Deliberately NOT terminal:
    # the piece stays in PUBLISHING until the post actually goes out, which is
    # what keeps its media URL served and its text un-editable while somebody
    # else is holding a copy of it.
    SCHEDULED = "scheduled"
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
    #
    # `none_as_null` is load-bearing and was missing here. Without it a Python
    # `None` is stored as the JSON value `null`, which is NOT SQL NULL: reading
    # the row back gives None either way, so nothing looks wrong until a query
    # asks `violations IS NULL` and matches zero rows — which is exactly how
    # the lane B sweep silently found no work to do. `message.py` already
    # carries this flag on `fair_housing_flags`; this model did not inherit the
    # lesson.
    violations: Mapped[list | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    # Lane B only: `{"narration": "...", "scenes": [{visual_prompt,
    # on_screen_text}, ...]}`. NULL for a clip somebody filmed, which needs no
    # plan. Every visual_prompt in here has been through the Fair Housing
    # filter and the person-descriptor denylist before the row was written.
    scenes: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    # What the dollar figures in this piece were computed from:
    # `{"scenarios": [{"inputs": {...}, "overrides": {...}}, ...],
    #   "literal": [12000]}`. NULL for the overwhelming majority, which state
    # no figure at all. Required before a piece that DOES state one can be
    # approved — see `content_figures.py` and the five videos that went out
    # promising $21,000 where the calculator answers $52,210.
    #
    # The inputs and not the answer, deliberately. A stored answer is true on
    # the day it is stored and silently stops being true when a default rate
    # moves, which is the case the written instruction of 14-sep-2026 calls
    # out by name.
    calculator_check: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )

    # Identity of the person who approved, not a boolean. "Somebody approved it"
    # is not an answer anyone can act on when a broker asks who did.
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cuando DEBERIA salir esta pieza. No lo usa el repartidor: `next_free_slot`
    # sigue buscando el siguiente dia libre y el orden de publicacion sigue
    # siendo el de `approved_at`. Esto existe para AVISAR de que una pieza
    # entro en su ventana sin que nadie la aprobara.
    #
    # Se guarda por pieza en vez de copiar las cuatro bandas de altitud de
    # `frontend/lib/fallGuide.ts` a Python: dos fuentes de la misma verdad se
    # separan en cuanto alguien toca una, y la que se quedaria atras seria
    # justo la que decide cuando avisar.
    publish_window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    publish_window_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Cuando se AVISO, no cuando se vio. Separado de la ventana por la misma
    # razon por la que `monitor_state` separa `state` de `alerted_state`: ver y
    # decir son dos hechos distintos. Se sella solo si un transporte acepto el
    # aviso; si el envio falla la pieza sigue sin sellar y el proximo tic
    # reintenta. Colapsarlos es como un envio fallido marca algo como
    # reportado y lo silencia para siempre.
    window_alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # NULL means "not rendered yet" and nothing else does. Set together with
    # `render_error` it means "tried, failed, not worth retrying until the
    # file changes" — the loop skips it and a person reads the reason.
    rendered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    render_error: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    # Eager for the same reason, and ordered newest first so the console can
    # read `rejections[0]` without sorting a list it did not ask for.
    rejections: Mapped[list[ContentRejection]] = relationship(
        back_populates="piece",
        cascade="all, delete-orphan",
        lazy="selectin",
        # `id` breaks the tie: `created_at` is Postgres `now()`, the start of
        # the transaction, so two rows written in one transaction are equal on
        # it and `rejections[0]` — which is what `correction` returns — would
        # not be deterministic.
        order_by="desc(ContentRejection.created_at), desc(ContentRejection.id)",
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
    # It went out, and it is no longer visible. `status` stays PUBLISHED, which
    # remains true and is about the past; this is about the present. The owner
    # set pieces 52-56 to private on 15-sep-2026 because their figures did not
    # reproduce, and for hours the count said twenty-three published where five
    # could not be opened by anyone.
    #
    # Per publication rather than per piece, because the same piece is private
    # on YouTube and still live on TikTok — a flag on the piece would be wrong
    # on two platforms out of three.
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdrawn_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When the platform will publish it. Written when Buffer accepts a
    # custom-scheduled post, and it is what the console counts down to.
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The post's real address on the platform, harvested from Buffer once it
    # has gone out. Text for the same reason `external_id` is.
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)

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


# The two ways a view count can get here. `youtube_api` was read from the
# platform; `manual` was typed by a person because TikTok and Instagram do not
# publish view counts to anything short of a first-party app with platform
# review. Keeping the provenance on the row is what stops a hand-typed estimate
# from being read later with the confidence of a measurement.
METRIC_SOURCES = ("youtube_api", "manual")


class ContentMetric(Base):
    """One day's reading of one publication's public counters.

    A row per day rather than a column on the publication, because the question
    worth asking is not "how many views now" but "is it still being watched" —
    and that needs history. `UNIQUE (publication_id, captured_on)` makes the day
    the unit, so a tick running every six hours refines its own snapshot instead
    of inventing four.

    Every counter is nullable on purpose: YouTube omits `likeCount` when a
    channel hides likes and `commentCount` when comments are off. `None` means
    "the platform did not say"; `0` would mean "nobody did it".
    """

    __tablename__ = "content_metrics"
    __table_args__ = (
        UniqueConstraint(
            "publication_id", "captured_on", name="uq_content_metrics_pub_day"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("content_publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # A date in the agency's zone, not a timestamp: it labels a bucket, and the
    # counter it holds is cumulative since publication, so the exact instant of
    # the reading carries nothing worth the confusion.
    captured_on: Mapped[date] = mapped_column(Date, nullable=False)

    views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comments: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# What a rejection can be about. Closed on purpose: an open vocabulary is one
# more thing for a model to invent, and every value here has to map to a
# decision the sweep knows how to take.
REJECTION_CATEGORIES = (
    "no_cta",       # the video does not ask for anything
    "figure",       # a number the calculator will not stand behind
    "language",     # written in the wrong language
    "fair_housing", # words that cannot appear in housing advertising
    "visual",       # the pictures
    "audio",        # the voice or the music
    "other",        # a reason in the reviewer's own words
)

# What the sweep did about it. `manual` and `given_up` are endings, not
# failures: a filmed clip cannot be regenerated, and a piece that has already
# had its two goes should stop costing renders.
REJECTION_ACTIONS = (
    "rebuild",         # the text is fine, the video was made before the fix
    "rematerialise",   # the narration lost its sign-off; rebuild it, then render
    "rewrite",         # ask the model to correct its own draft
    "manual",          # nothing automatic can help
    "given_up",        # the caps in G4 are spent
    "superseded",      # somebody moved the piece before the sweep got to it
)


class ContentRejection(Base):
    """One rejection, its diagnosis, and what was done about it.

    The row it points at is REUSED by the correction — a new piece would shift
    `next_topic` and the sign-off rotation, both of which count rows — so the
    text that was rejected is overwritten upstairs and `snapshot` is the only
    place it survives.

    `category`, `finding` and `action` are filled by the sweep rather than by
    the endpoint: classifying can cost an LLM call, and a person pressing
    Reject should not wait on a provider to find out whether it worked.
    """

    __tablename__ = "content_rejections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    piece_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("content_pieces.id", ondelete="CASCADE"), nullable=False
    )
    #: The reviewer's own words. Data, never an instruction: it is quoted into
    #: the prompt and everything that comes back is filtered again.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: What the machine could check about that reason, or `{}` when nothing
    #: mechanical can answer it.
    #: `none_as_null` on BOTH, and the reason is written down three hundred
    #: lines above this one: without it a Python `None` is stored as the JSON
    #: value `null`, which is not SQL NULL, and `WHERE finding IS NULL` returns
    #: nothing — which is exactly how the lane B sweep once found no work to do,
    #: silently. The sweep in the next phase queries on this column.
    finding: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Deferred: this is the whole rejected draft, and the relationship that
    #: loads it is eager — so without this every read of a piece, including the
    #: public route Buffer downloads the video through, would drag one copy of
    #: the text per rejection for nobody.
    snapshot: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True, deferred=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    piece: Mapped[ContentPiece] = relationship(back_populates="rejections")

    _clip = clip_string_columns("category", "action")


class ContentLesson(Base):
    """Something the reviewer said once that the writer should not need told
    twice.

    Standing guidance, not history — which is why it is not a column on the
    rejection. It outlives the piece that produced it, it is capped, and a
    person can revoke it; a rejection is an event and cannot be any of those.

    Only reasons with no mechanical gate become lessons. Where there is a gate
    — a figure the calculator refuses, a sign-off that is missing — the gate IS
    the lesson, and duplicating it in the prompt would be a rule the model can
    talk itself out of.
    """

    __tablename__ = "content_lessons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    source_piece_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("content_pieces.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, server_default=text_sql("true"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    _clip = clip_string_columns("category", "text")
