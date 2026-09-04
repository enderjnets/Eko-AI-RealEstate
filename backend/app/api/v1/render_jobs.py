"""The queue the render worker talks to. Not a dashboard route.

Authentication here is a shared token, not a session, because the caller is a
process on another machine and there is no person to sign in as. That token is
the entire boundary, so three things about it are deliberate:

* **An unset token means 503, never "open".** A missing secret that degrades to
  no authentication is how an internal queue becomes a public one, and the
  failure would be silent — everything would work.
* **`compare_digest`**, so the comparison does not leak the token's prefix to
  something timing it.
* **These routes are mounted without the session dependency**, which is exactly
  why they are in their own module and carry their own guard rather than
  hiding among the authenticated ones.

The worker has no organization, so this runs on the bypass engine and stamps
`org_id` from the job itself. That is the same pattern the background workers
use, and the same care applies: nothing here takes an org from the request.

What a worker can do is deliberately small: take one job, read its input, hand
back a result or a failure, say it is alive. It cannot approve anything, cannot
choose which piece to work on, and cannot publish. A compromised worker can
waste render time and return a bad video into the APPROVAL QUEUE, where a
person still has to look at it before it can go anywhere.
"""

from __future__ import annotations

import hmac
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_bypass_session_factory
from app.models import (
    AgentSettings,
    ContentPiece,
    ContentStatus,
    RenderJob,
    RenderJobKind,
    RenderJobStatus,
)
from app.services.content_render import RenderRefused, check_output, probe_media
from app.services.content_studio import advance
from app.services.fair_housing import PEOPLE_IN_PICTURES

log = logging.getLogger(__name__)


async def require_worker_token(request: Request) -> None:
    """The whole boundary. Unset means closed, never open."""
    expected = (get_settings().RENDER_WORKER_TOKEN or "").strip()
    if not expected:
        # 503, not 401: nothing is wrong with the caller's credentials, the
        # feature is not configured. Saying 401 would send an operator looking
        # for a bad token that does not exist.
        raise HTTPException(status_code=503, detail="render worker queue is not configured")
    presented = (request.headers.get("x-worker-token") or "").strip()
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="bad worker token")


# The dependency goes on the CONSTRUCTOR, not on `router.dependencies` after
# the routes are declared: FastAPI copies that list when each route is
# registered, so assigning it afterwards attaches the guard to nothing and
# every route ships unauthenticated while the code reads as if it were guarded.
router = APIRouter(dependencies=[Depends(require_worker_token)])

# A claim older than this is assumed dead. Generous: a generated video is
# minutes of work, and re-queueing a job somebody is still working on wastes
# the render that was nearly finished.
STALE_CLAIM = timedelta(hours=2)
# Three tries, then a person reads the reason. A job that killed three workers
# will kill the fourth.
MAX_ATTEMPTS = 3

_OUR_NAME = re.compile(r"[0-9a-f]{32}\.[a-z0-9]{2,5}")


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    piece_id: int
    kind: RenderJobKind
    attempts: int


class JobInput(BaseModel):
    """Everything the worker needs, and nothing it does not.

    No org id, no lead data, no settings: a render is a video and a line of
    text. The brokerage line is here because it is burned into the frame and
    the worker cannot invent it.
    """

    piece_id: int
    kind: RenderJobKind
    language: str
    brokerage_line: str
    # Lane A only: the clip is fetched separately as bytes.
    has_media: bool
    # Lane B only. `scenes` is `{"narration": ..., "scenes": [...]}` — every
    # visual_prompt in it already passed the Fair Housing filter and the
    # person-descriptor denylist when the draft was written. The worker draws
    # what it is given and re-decides nothing.
    hook: str | None = None
    script: str | None = None
    scenes: dict | None = None
    # The person-descriptor vocabulary, shipped rather than duplicated. The
    # worker searches a stock library, and a library answers a clean prompt
    # with whatever it has — "residential house keys" came back as "woman real
    # estate agent placing a sign". Housing advertising is regulated in
    # pictures, so the RESULT has to be screened too, and the only list that
    # may do the screening is the one the rest of the system already uses.
    people_words: list[str] = []


class FailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str = Field(max_length=2000)
    # Whether another attempt could possibly answer differently. Declared by
    # the worker, which knows WHICH exception it caught; this side would only
    # have a sentence to guess from, and a rule that reads the prefix of an
    # error message breaks the day somebody rewords it.
    #
    # It has a default because `extra="forbid"` rejects a field the model does
    # not declare: without one, a worker that has not been updated yet would
    # get a 422 and lose the ability to report failures at all.
    terminal: bool = False


def _for_the_console(reason: str) -> str:
    """What a realtor reads. A worker's stderr carries its own paths."""
    return reason if len(reason) < 300 else reason[:297] + "…"


@router.post("/claim", response_model=JobOut | None)
async def claim_job(worker: str = Query(max_length=64)) -> JobOut | None:
    """Hand out one job, or nothing.

    `FOR UPDATE SKIP LOCKED` rather than a read-then-write: two workers asking
    at the same instant must not both be told about the same job, and locking
    is the only way that holds without a transaction retry loop.
    """
    now = datetime.now(UTC)
    async with get_bypass_session_factory()() as db:
        # Reclaim the dead first, so a crashed worker's job is worked on before
        # newer ones rather than after all of them.
        stale = (
            (
                await db.execute(
                    select(RenderJob)
                    .where(
                        RenderJob.status == RenderJobStatus.CLAIMED,
                        RenderJob.claimed_at < now - STALE_CLAIM,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for job in stale:
            job.attempts += 1
            if job.attempts >= MAX_ATTEMPTS:
                job.status = RenderJobStatus.FAILED
                job.last_error = (
                    f"no worker finished this job in {MAX_ATTEMPTS} attempts"
                )
                await _write_failure_to_piece(db, job, job.last_error)
            else:
                job.status = RenderJobStatus.QUEUED
                job.worker = None
                job.claimed_at = None
        if stale:
            await db.commit()

        job = (
            (
                await db.execute(
                    select(RenderJob)
                    .where(RenderJob.status == RenderJobStatus.QUEUED)
                    .order_by(RenderJob.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .first()
        )
        if job is None:
            return None

        job.status = RenderJobStatus.CLAIMED
        job.worker = worker
        job.claimed_at = now
        await db.commit()
        return JobOut.model_validate(job)


async def _load(db: AsyncSession, job_id: int) -> RenderJob:
    job = (
        await db.execute(select(RenderJob).where(RenderJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return job


async def _write_failure_to_piece(db: AsyncSession, job: RenderJob, reason: str) -> None:
    """Put the reason where a person will see it, on the piece."""
    piece = (
        await db.execute(select(ContentPiece).where(ContentPiece.id == job.piece_id))
    ).scalar_one_or_none()
    if piece is not None:
        piece.render_error = _for_the_console(reason)


@router.get("/{job_id}/input", response_model=JobInput)
async def job_input(job_id: int) -> JobInput:
    async with get_bypass_session_factory()() as db:
        job = await _load(db, job_id)
        piece = (
            await db.execute(
                select(ContentPiece).where(ContentPiece.id == job.piece_id)
            )
        ).scalar_one_or_none()
        if piece is None:
            raise HTTPException(status_code=404, detail="no such piece")
        settings_row = (
            await db.execute(
                select(AgentSettings).where(AgentSettings.org_id == job.org_id)
            )
        ).scalar_one_or_none()
        brokerage = (settings_row.brokerage_line or "").strip() if settings_row else ""
        return JobInput(
            piece_id=piece.id,
            kind=job.kind,
            language=piece.language.value,
            brokerage_line=brokerage,
            has_media=bool(piece.media_path),
            hook=piece.hook,
            script=piece.script,
            scenes=piece.scenes,
            people_words=list(PEOPLE_IN_PICTURES),
        )


@router.get("/{job_id}/media")
async def job_media(job_id: int):
    """The source clip, for lane A."""
    async with get_bypass_session_factory()() as db:
        job = await _load(db, job_id)
        piece = (
            await db.execute(
                select(ContentPiece).where(ContentPiece.id == job.piece_id)
            )
        ).scalar_one_or_none()
        if piece is None or not piece.media_path:
            raise HTTPException(status_code=404, detail="no media")
        if not _OUR_NAME.fullmatch(piece.media_path):
            raise HTTPException(status_code=404, detail="no media")
        path = Path(get_settings().CONTENT_MEDIA_DIR) / piece.media_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no media")
    return FileResponse(path, media_type="video/mp4")


async def _refuse_unless_awaited(
    db: AsyncSession, job_id: int
) -> tuple[RenderJob, ContentPiece]:
    """The job is claimed and its piece is still waiting for a video. Or 409.

    One function because the same three questions are asked twice — once
    before the upload to save it, once inside the committing transaction where
    the answer is authoritative — and two copies of a rule are two rules.
    """
    job = await _load(db, job_id)
    if job.status is not RenderJobStatus.CLAIMED:
        raise HTTPException(
            status_code=409,
            detail=f"job {job_id} is {job.status.value}; it is not waiting for a result",
        )
    piece = (
        await db.execute(select(ContentPiece).where(ContentPiece.id == job.piece_id))
    ).scalar_one_or_none()
    if piece is None:
        raise HTTPException(status_code=404, detail="no such piece")
    if piece.status not in (ContentStatus.DRAFT, ContentStatus.NEEDS_APPROVAL):
        raise HTTPException(
            status_code=409,
            detail=(
                f"piece {piece.id} is {piece.status.value}; a video a person has "
                "already acted on is not replaced by a late render"
            ),
        )
    return job, piece


@router.put("/result")
async def job_result(request: Request, job_id: int = Query()) -> dict[str, str]:
    """The finished video, streamed in.

    `job_id` is a query parameter and not part of the path because the
    streaming exemption in `main.py` matches the path EXACTLY — a parametric
    path would never match it, and the body would be buffered whole in memory
    before this function saw a byte.

    The file is verified here, against the same checks `content_render` applies
    to its own output. A worker on another machine is not a trusted source of
    1080x1920: it may have been misconfigured, or half-updated, and the point
    of the queue is that this side does not have to trust it.
    """
    # Asked BEFORE a byte is read. A job that already finished, or a piece a
    # person has approved, is not owed a result — and finding that out after
    # streaming 20 MB to disk means writing a file only to delete it, and
    # answering "your video is the wrong shape" to a worker whose real problem
    # is that it is two hours late. The state is re-checked after the upload
    # too: this is the cheap answer, not the authoritative one.
    async with get_bypass_session_factory()() as db:
        job, _piece = await _refuse_unless_awaited(db, job_id)
        job_kind = job.kind

    media_root = Path(get_settings().CONTENT_MEDIA_DIR)
    # In a thread: this is a blocking filesystem call on the event loop that
    # every other request shares. In production the volume is already there and
    # it costs nothing; on a fresh install it is the difference between the
    # first result landing and a 500.
    await anyio.to_thread.run_sync(partial(media_root.mkdir, parents=True, exist_ok=True))
    destination = media_root / f"{uuid.uuid4().hex}.mp4"

    written = 0
    limit = get_settings().CONTENT_UPLOAD_MAX_MB * 1024 * 1024
    try:
        with destination.open("wb") as handle:
            async for chunk in request.stream():
                written += len(chunk)
                if written > limit:
                    raise HTTPException(status_code=413, detail="body_too_large")
                handle.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="empty body")

        probe = await probe_media(destination)
        # Lane B exists to produce a narrated video; the worker itself fails
        # rather than ship silence. Requiring it HERE too is the point of the
        # queue: a half-updated worker is exactly the thing this side does not
        # take at its word, and a mute short reaching the approval queue is a
        # different video from the one that was planned.
        check_output(probe, expect_audio=job_kind is RenderJobKind.PRODUCE_B)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except RenderRefused as exc:
        destination.unlink(missing_ok=True)
        async with get_bypass_session_factory()() as db:
            job = await _load(db, job_id)
            job.status = RenderJobStatus.FAILED
            job.last_error = str(exc)[:2000]
            await _write_failure_to_piece(db, job, str(exc))
            await db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    # Everything from here to the commit either lands the file or removes it.
    # The earlier version unlinked in the branches somebody thought of, so a
    # 404 from a deleted job — or any commit failure — left a video on the
    # media volume that nothing ever sweeps.
    delivered = False
    async with get_bypass_session_factory()() as db:
        try:
            job, piece = await _refuse_unless_awaited(db, job_id)
        except HTTPException:
            destination.unlink(missing_ok=True)
            raise

        previous = piece.media_path
        piece.media_path = destination.name
        piece.rendered_at = datetime.now(UTC)
        piece.render_error = None
        # Straight into the approval queue. The worker produced a video; a
        # person still decides whether it goes anywhere.
        #
        # Unless the text has findings against it. `submit_for_approval`
        # refuses in that state and the status enum says a DRAFT "never reaches
        # NEEDS_APPROVAL on its own"; advancing here would be a second door
        # into the queue that skips the filter the first one exists to enforce.
        # The file is still attached — the render was not wasted — the piece
        # simply stays where the violations put it.
        if piece.status is ContentStatus.DRAFT and not piece.violations:
            advance(piece, ContentStatus.NEEDS_APPROVAL)
        job.status = RenderJobStatus.DONE
        job.last_error = None
        await db.commit()
        delivered = True
        # AFTER the commit, never before: a notice is a consequence of a fact,
        # and announcing one before it is durable is how somebody is told about
        # a video that is not there.
        #
        # The condition is the RESULTING state, not the transition. A clean
        # generated piece is ALREADY in NEEDS_APPROVAL when the render lands —
        # that is the whole shape of the piece-5 incident — so a bell wired to
        # "the advance happened" would stay silent on the commonest path of
        # all: the doorbell that never rings, which is the fault this exists to
        # fix.
        if (
            piece.status is ContentStatus.NEEDS_APPROVAL
            and piece.media_path
        ):
            await _ring_the_bell(db, piece.id)

    if not delivered:  # pragma: no cover — belt to the suspenders above
        destination.unlink(missing_ok=True)

    # The source clip, only once the new one is committed. Deleting first would
    # trade a wasted file for a lost original if the commit failed.
    if previous and previous != destination.name and _OUR_NAME.fullmatch(previous):
        (media_root / previous).unlink(missing_ok=True)
    return {"status": "done"}



async def _ring_the_bell(db: AsyncSession, piece_id: int) -> None:
    """Tell the owner a video is waiting. Never raises.

    Wrapped whole: this runs on the path that just delivered a finished render,
    and losing that video to a failed message would be a spectacular way to pay
    for a convenience.

    No "already notified" column. Delivery happens once per render —
    `_refuse_unless_awaited` forbids the second — and after a rebuild it happens
    again, which is exactly when the owner wants telling again. A flag here
    would be state to keep in step with a fact that is already unique.
    """
    from app.services.telegram_notify import notify_video_ready

    try:
        waiting = (
            await db.execute(
                select(func.count())
                .select_from(ContentPiece)
                .where(
                    ContentPiece.status == ContentStatus.NEEDS_APPROVAL,
                    ContentPiece.media_path.is_not(None),
                )
            )
        ).scalar_one()
        await notify_video_ready(piece_id, waiting)
    except Exception:  # noqa: BLE001 — a doorbell cannot break the delivery
        log.exception("Could not send the approval notice for piece %s", piece_id)


@router.post("/{job_id}/fail")
async def job_failed(job_id: int, payload: FailIn) -> dict[str, str]:
    """The worker could not do it, and says why.

    Counted as an attempt rather than failed outright: a transient failure —
    an image provider timing out, a disk full for a minute — should be retried,
    and only a job that beat every attempt is a job for a person.

    Unless the worker says the answer cannot change. A render that failed its
    own output verification will fail it identically on the next two attempts:
    piece 10 spent three MiniMax narrations in seventy-one seconds to be told
    the same thing three times. The attempt is still counted — it happened —
    but the remaining ones are not spent on a foregone conclusion.
    """
    async with get_bypass_session_factory()() as db:
        job = await _load(db, job_id)
        if job.status is not RenderJobStatus.CLAIMED:
            # Same reason as `/result`: a job nobody is holding cannot fail,
            # and accepting it here re-queued a DONE job for a second render.
            raise HTTPException(
                status_code=409,
                detail=f"job {job_id} is {job.status.value}; nobody is working it",
            )
        job.attempts += 1
        job.last_error = payload.error[:2000]
        if payload.terminal or job.attempts >= MAX_ATTEMPTS:
            job.status = RenderJobStatus.FAILED
            await _write_failure_to_piece(db, job, payload.error)
        else:
            job.status = RenderJobStatus.QUEUED
            job.worker = None
            job.claimed_at = None
        await db.commit()
        return {"status": job.status.value}


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker: str = Field(max_length=64)
    # Whether THIS tick fell inside the machine's agreed hours, and which hours
    # those are. Optional so an older worker keeps working. Without it the
    # console cannot tell "nothing is being made" from "nothing will be made
    # for another hour", and it showed a spinner for both.
    within_hours: bool | None = None
    hours: list[int] | None = None


class ProgressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(max_length=40)
    percent: int = Field(ge=0, le=100)


@router.post("/heartbeat")
async def heartbeat(payload: HeartbeatIn) -> dict[str, str]:
    """"I am alive." Recorded so the watcher can tell a quiet queue from a
    dead worker — a process cannot report its own death."""
    from app.services.render_watch import record_heartbeat

    await record_heartbeat(
        payload.worker,
        detail=(
            None
            if payload.within_hours is None
            else {"within_hours": payload.within_hours, "hours": payload.hours or []}
        ),
    )
    return {"status": "ok"}


@router.post("/{job_id}/progress")
async def job_progress(job_id: int, payload: ProgressIn) -> dict[str, str]:
    """How far along this job is, in its own words.

    Advisory only: it never changes the job's status, so a lost or late report
    cannot strand a render. The console reads it to say what is happening
    instead of spinning.
    """
    from app.db.base import get_bypass_session_factory

    async with get_bypass_session_factory()() as db:
        job = (
            await db.execute(select(RenderJob).where(RenderJob.id == job_id))
        ).scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")
        job.stage = payload.stage
        job.progress = payload.percent
        await db.commit()
    return {"status": "ok"}

