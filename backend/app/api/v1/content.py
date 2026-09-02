"""The approval queue, and the only doors in and out of it.

Every route here goes through `advance()`, so the state machine in
`content_studio.py` is the single authority on what a status change is. The
routes add exactly three things the service cannot know: who is asking (for
`approved_by`), what they typed (edits, rejection reasons), and the bytes of an
uploaded clip.

Two decisions worth their comments:

* **Editing revokes approval.** An edit while APPROVED moves the piece back to
  NEEDS_APPROVAL through the declared edge. The alternative — trusting the
  approval of text that no longer exists — is how something no person read gets
  published under a person's name.
* **Media is served by a route, not by static files.** The files are client
  agencies' unpublished footage; an unlisted URL is not access control. Since
  v0.65 there is a second, unauthenticated route in `api/v1/public.py`, and it
  does not contradict this: it exists because Buffer downloads the video by URL
  when the post goes out and rejects signed links, and it serves **only** a
  piece a person approved — the gate moved from the session to the status, it
  did not disappear. Unapproved footage answers 404 there exactly as it does to
  a stranger here. See `services/media_public.py`.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._validators import trimmed, trimmed_or_none
from app.api.v1.auth import current_email
from app.config import get_settings
from app.db.base import get_db
from app.models import (
    AgentSettings,
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentStatus,
)
from app.services.buffer_publisher import undeliverable_reason
from app.services.content_studio import (
    PUBLISHING_AVAILABLE,
    IllegalTransition,
    advance,
    text_violations,
)
from app.services.tenant_context import get_org_id

router = APIRouter()

_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    status: str
    external_id: str | None = None
    published_at: datetime | None = None
    last_error: str | None = None


class PieceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: ContentKind
    language: ContentLanguage
    status: ContentStatus
    hook: str | None = None
    script: str | None = None
    caption: str | None = None
    media_path: str | None = None
    # Why this clip is not rendered, in the render's own words. Written since
    # v0.52 and never returned by any route, so an agency whose clip was
    # waiting on a missing brokerage line saw it sit there with no reason.
    render_error: str | None = None
    violations: list | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    publications: list[PublicationOut] = []


def _trim_or_clear(value: object) -> object:
    """Trim, and treat whitespace-only as absent.

    These strings are burned into a video and read aloud by the caption, so a
    trailing space is not cosmetic. Shared by the two edit schemas below.
    """
    return trimmed_or_none(value)


class PieceEdit(BaseModel):
    hook: str | None = Field(default=None, max_length=300)
    script: str | None = None
    caption: str | None = None

    _trim = field_validator("hook", "script", "caption", mode="before")(
        classmethod(lambda cls, v: _trim_or_clear(v))
    )


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)

    # `mode="before"`, so `min_length=3` judges the trimmed value: "   " used to
    # pass as a three-character rejection reason and be stored as blank.
    @field_validator("reason", mode="before")
    @classmethod
    def _trim_reason(cls, value: object) -> object:
        return trimmed(value)


class DraftIn(BaseModel):
    kind: ContentKind = ContentKind.RECORDED
    language: ContentLanguage = ContentLanguage.EN
    hook: str | None = Field(default=None, max_length=300)
    script: str | None = None
    caption: str | None = None

    _trim = field_validator("hook", "script", "caption", mode="before")(
        classmethod(lambda cls, v: _trim_or_clear(v))
    )


def _refresh_violations(piece: ContentPiece) -> None:
    """The row always carries the filter's current opinion of its text.

    Stored, not recomputed by readers, so the console can show WHY a draft is
    stuck without running the filter per row per page load.
    """
    # Every field, through the one function that knows which fields there are.
    # Recomputing from hook/script/caption alone WIPED the findings against a
    # scene: a person who edited any text — or simply pressed Submit — laundered
    # a refused image prompt into the approval queue, and the render was then
    # paid for.
    piece.violations = (
        text_violations(
            hook=piece.hook,
            script=piece.script,
            caption=piece.caption,
            scenes=piece.scenes,
            language=piece.language,
        )
        or None
    )


class StudioStatus(BaseModel):
    """Why the queue looks the way it does.

    Booleans, counts, and one number — no URLs, no key names, no environment
    variable names. "Nothing here right now" is true and useless; the question
    a person actually has is why, and the answers live in three different
    places (two env flags and a settings row) that no single screen was showing.

    `upload_max_mb` is the amendment to "booleans and counts only", and it is
    made deliberately rather than quietly. The rule was written to keep this
    endpoint from leaking configuration to a browser: what is CONFIGURED is our
    business, and naming an env var tells an attacker what to look for. A size
    limit is neither. It is a number the person needs BEFORE choosing a file,
    and withholding it means the only way to learn it is to spend the upload
    and read the error — on a phone, over mobile data, with a clip that takes
    minutes to send. The value is also already discoverable by anyone who can
    reach the route: upload something too big and the 413 says it. Publishing
    it costs nothing and saves the upload.
    """

    studio_enabled: bool
    render_enabled: bool
    brokerage_line_set: bool
    publishing_available: bool
    # Whether THIS install can actually post: the switch is on and nothing is
    # missing. A boolean, not the reason — the reason names environment
    # variables and this response is read by anyone with a session. The reason
    # is logged at startup, where an operator can act on it.
    publishing_ready: bool
    # Megabytes. Named in the unit rather than bytes because it is shown to a
    # person, and the client compares it against `file.size` before opening the
    # request — see `UploadClip.tsx`.
    upload_max_mb: int
    counts: dict[str, int]


@router.get("/status", response_model=StudioStatus)
async def studio_status(db: AsyncSession = Depends(get_db)) -> StudioStatus:
    """Declared before the parametric routes on purpose — a rule this repo has
    already paid for: `/status` would otherwise be read as a piece id."""
    s = get_settings()
    # Scoped explicitly, like every other query that runs inside a request
    # (`settings.py:_get_or_create`, `visits.py`, `conversation.py`). RLS does
    # cover both tables, so this is belt and braces — but the belt has a known
    # hole: when `DATABASE_URL_APP` is unset the app connects as the owning
    # role and RLS does not apply, a state the startup check tolerates for a
    # single real organisation even though the demo org from migration 015 is
    # also present. In that state an unfiltered `.first()` with no ORDER BY
    # returns whichever row Postgres hands back, so this endpoint could have
    # told an admin their brokerage line was missing while it was set.
    org_id = get_org_id()
    if org_id is None:
        # Same refusal as `settings.py:_acting_org`. Not reachable today —
        # `require_auth` 401s a token with no org — but the alternative is an
        # endpoint that answers "no brokerage line, nothing queued" with total
        # confidence about an organisation it could not identify.
        raise RuntimeError(
            "no acting organization is bound; refusing to report the studio "
            "state of an unidentified one"
        )
    row = (
        await db.execute(
            select(AgentSettings).where(AgentSettings.org_id == org_id)
        )
    ).scalars().first()
    rows = (
        await db.execute(
            select(ContentPiece.status, func.count())
            .where(ContentPiece.org_id == org_id)
            .group_by(ContentPiece.status)
        )
    ).all()
    counts = {status.value: 0 for status in ContentStatus}
    for status, total in rows:
        # `status` is always the enum member: the pg_enum type returns members,
        # never strings. A `str(status)` fallback would have written the key
        # "ContentStatus.DRAFT" and left "draft" at zero — a wrong answer
        # wearing the costume of a defensive one.
        counts[status.value] = total
    return StudioStatus(
        studio_enabled=bool(s.CONTENT_STUDIO_ENABLED),
        render_enabled=bool(s.CONTENT_RENDER_ENABLED),
        # `.strip()` because both gates strip before deciding: a whitespace-only
        # value is "set" to a naive check and "unset" to everything that matters.
        brokerage_line_set=bool((row.brokerage_line or "").strip() if row else ""),
        publishing_available=PUBLISHING_AVAILABLE,
        publishing_ready=bool(
            s.CONTENT_PUBLISH_ENABLED and undeliverable_reason() is None
        ),
        upload_max_mb=s.CONTENT_UPLOAD_MAX_MB,
        counts=counts,
    )


@router.get("", response_model=list[PieceOut])
async def list_pieces(
    status: ContentStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[PieceOut]:
    stmt = (
        select(ContentPiece)
        .order_by(ContentPiece.created_at.desc(), ContentPiece.id.desc())
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(ContentPiece.status == status)
    rows = (await db.execute(stmt)).scalars().unique().all()
    return [PieceOut.model_validate(row) for row in rows]


@router.post("", response_model=PieceOut, status_code=201)
async def create_draft(
    payload: DraftIn, db: AsyncSession = Depends(get_db)
) -> PieceOut:
    """A person filing a piece by hand — Natalia's clip before its file, or a
    hook somebody wants to write themselves."""
    piece = ContentPiece(
        kind=payload.kind,
        language=payload.language,
        status=ContentStatus.DRAFT,
        hook=payload.hook,
        script=payload.script,
        caption=payload.caption,
        # Marks the collection loaded. A NEW row truly has none, and without
        # this the serialiser's first touch after commit is a lazy load from a
        # sync context — MissingGreenlet.
        publications=[],
    )
    _refresh_violations(piece)
    db.add(piece)
    await db.commit()
    # `updated_at` is a server-side onupdate, so the flush expired it; touching
    # it during serialisation would be a lazy refresh from a sync context.
    await db.refresh(piece)
    return PieceOut.model_validate(piece)


@router.patch("/{piece_id}", response_model=PieceOut)
async def edit_piece(
    piece_id: int, payload: PieceEdit, db: AsyncSession = Depends(get_db)
) -> PieceOut:
    piece = await db.get(ContentPiece, piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="No such piece")
    if piece.status in (ContentStatus.PUBLISHING, ContentStatus.PUBLISHED):
        raise HTTPException(
            status_code=409,
            detail="This piece is being published or already was; the text on "
            "the platform would not change",
        )

    changed = False
    for field in ("hook", "script", "caption"):
        # `model_fields_set`, not `is not None`. The two are different questions
        # and only this one has an answer: "was this field sent?" versus "did it
        # arrive empty?". Skipping None made clearing a caption impossible —
        # the trimming validator turns "" into None, the console sends all
        # three fields as strings on every save, so emptying the textarea
        # returned 200 and put the old text straight back. A 200 that discards
        # the edit is worse than a 400, because nobody goes looking.
        if field not in payload.model_fields_set:
            continue
        value = getattr(payload, field)
        if value != getattr(piece, field):
            setattr(piece, field, value)
            changed = True

    if changed:
        _refresh_violations(piece)
        # The person approved the OLD text. Through the declared edge, so an
        # illegal path here is a crash rather than a silent status write.
        if piece.status is ContentStatus.APPROVED:
            advance(piece, ContentStatus.NEEDS_APPROVAL)
            piece.approved_by = None
            piece.approved_at = None
    await db.commit()
    # `updated_at` is a server-side onupdate, so the flush expired it; touching
    # it during serialisation would be a lazy refresh from a sync context.
    await db.refresh(piece)
    return PieceOut.model_validate(piece)


@router.post("/{piece_id}/submit", response_model=PieceOut)
async def submit_for_approval(
    piece_id: int, db: AsyncSession = Depends(get_db)
) -> PieceOut:
    """DRAFT → NEEDS_APPROVAL, refused while the filter still objects.

    The refusal is the point: a draft with violations is edited by a person,
    not queued until somebody misses the red text and approves it anyway.
    """
    piece = await db.get(ContentPiece, piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="No such piece")

    _refresh_violations(piece)
    if piece.violations:
        await db.commit()  # keep the stored findings current even on refusal
        raise HTTPException(
            status_code=422,
            detail={
                "message": "This text cannot go in housing advertising; edit "
                "the flagged phrases first",
                "violations": piece.violations,
            },
        )
    try:
        advance(piece, ContentStatus.NEEDS_APPROVAL)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    # `updated_at` is a server-side onupdate, so the flush expired it; touching
    # it during serialisation would be a lazy refresh from a sync context.
    await db.refresh(piece)
    return PieceOut.model_validate(piece)


@router.post("/{piece_id}/approve", response_model=PieceOut)
async def approve_piece(
    piece_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> PieceOut:
    piece = await db.get(ContentPiece, piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="No such piece")
    if not (piece.media_path or "").strip():
        # You cannot approve a video you cannot watch, and this is not a
        # formality — it is the whole point of the gate. A generated piece
        # reaches NEEDS_APPROVAL as soon as its text is clean, while the render
        # is still running, so the console offered an Approve button next to a
        # script. Someone pressed it. The worker then finished and was refused
        # with a 409 by `_refuse_unless_awaited` — correctly, the piece was no
        # longer awaiting a render — three times, and the job died. The piece
        # is still sitting there today: approved, empty, and unpublishable
        # forever, because the publisher requires `media_path`. Nothing said a
        # word.
        raise HTTPException(
            status_code=409,
            detail=(
                "this piece has no video yet — it is still being made. "
                "Approving it now would leave it approved and empty: the render "
                "can no longer attach a file to an approved piece."
            ),
        )
    try:
        advance(piece, ContentStatus.APPROVED)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Identity, not a boolean — when a broker asks who approved a video, "the
    # office password" is an honest answer and "someone" is not.
    piece.approved_by = current_email(request) or "office"
    piece.approved_at = datetime.now(UTC)
    await db.commit()
    # `updated_at` is a server-side onupdate, so the flush expired it; touching
    # it during serialisation would be a lazy refresh from a sync context.
    await db.refresh(piece)
    return PieceOut.model_validate(piece)


@router.post("/{piece_id}/reject", response_model=PieceOut)
async def reject_piece(
    piece_id: int, payload: RejectIn, db: AsyncSession = Depends(get_db)
) -> PieceOut:
    piece = await db.get(ContentPiece, piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="No such piece")
    try:
        advance(piece, ContentStatus.REJECTED)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    piece.rejected_reason = payload.reason
    await db.commit()
    # `updated_at` is a server-side onupdate, so the flush expired it; touching
    # it during serialisation would be a lazy refresh from a sync context.
    await db.refresh(piece)
    return PieceOut.model_validate(piece)


@router.post("/{piece_id}/retry", response_model=PieceOut)
async def retry_piece(piece_id: int, db: AsyncSession = Depends(get_db)) -> PieceOut:
    """Put a piece that failed to publish back in front of a person.

    FAILED is where a piece lands when every platform refused it, and until now
    it was a dead end: the only way out of it was an UPDATE by hand on the
    production database. That is the wrong shape for the commonest cause, which
    is not the video — it is a bug or an outage on the way out. The first real
    publish of this installation failed on all three platforms for three
    reasons, all of them ours or Buffer's, and none of them anything a realtor
    could have seen in the piece.

    It goes back to NEEDS_APPROVAL rather than straight to APPROVED **on
    purpose**. Nothing about the artefact changed, so a person clicking approve
    again costs one click — and the invariant that a human approved the exact
    thing that went out is worth more than the click. The failed publication
    rows are left alone: they are the record of what happened, and the
    publisher resets them itself when the piece is approved afresh.
    """
    piece = await db.get(ContentPiece, piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="No such piece")
    try:
        advance(piece, ContentStatus.DRAFT)
        advance(piece, ContentStatus.NEEDS_APPROVAL)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    piece.approved_by = None
    piece.approved_at = None
    await db.commit()
    await db.refresh(piece)
    return PieceOut.model_validate(piece)


@router.post("/upload", response_model=PieceOut, status_code=201)
async def upload_clip(
    request: Request,
    filename: str = Query(min_length=1, max_length=200),
    language: ContentLanguage = Query(default=ContentLanguage.EN),
    db: AsyncSession = Depends(get_db),
) -> PieceOut:
    """A clip from the phone, streamed to the media volume.

    Raw body rather than multipart, on purpose: the body-size middleware
    exempts this path and the route enforces the cap itself while streaming,
    so a 4K clip never sits in memory — the same shape as discovery's upload.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in _SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"Expected a video file ({', '.join(sorted(_SUFFIXES))})",
        )

    media_root = Path(get_settings().CONTENT_MEDIA_DIR)
    await anyio.to_thread.run_sync(
        lambda: media_root.mkdir(parents=True, exist_ok=True)
    )
    # Our name, not the caller's. A filename is user input, and it only needed
    # to survive long enough to give us the suffix.
    stored = f"{uuid.uuid4().hex}{suffix}"
    destination = media_root / stored

    limit = get_settings().CONTENT_UPLOAD_MAX_MB * 1024 * 1024
    written = 0
    try:
        async with await anyio.open_file(destination, "wb") as handle:
            async for chunk in request.stream():
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Clip exceeds {get_settings().CONTENT_UPLOAD_MAX_MB} MB",
                    )
                await handle.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="Empty upload")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise

    piece = ContentPiece(
        kind=ContentKind.RECORDED,
        language=language,
        status=ContentStatus.DRAFT,
        media_path=stored,
        publications=[],
    )
    db.add(piece)
    await db.commit()
    # `updated_at` is a server-side onupdate, so the flush expired it; touching
    # it during serialisation would be a lazy refresh from a sync context.
    await db.refresh(piece)
    return PieceOut.model_validate(piece)


@router.get("/{piece_id}/media")
async def serve_media(piece_id: int, db: AsyncSession = Depends(get_db)):
    """The clip, through authentication and the tenant boundary.

    The lookup goes through the RLS-scoped session, so asking for another
    agency's piece 404s exactly like asking for one that never existed.
    """
    piece = await db.get(ContentPiece, piece_id)
    if piece is None or not piece.media_path:
        raise HTTPException(status_code=404, detail="No media")
    # The stored name is ours (a hex uuid), but the path it joins to is a
    # filesystem, so refuse anything that stopped looking like our names.
    if not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]{2,5}", piece.media_path):
        raise HTTPException(status_code=404, detail="No media")
    file_path = Path(get_settings().CONTENT_MEDIA_DIR) / piece.media_path
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Media file is missing")
    return FileResponse(file_path)
