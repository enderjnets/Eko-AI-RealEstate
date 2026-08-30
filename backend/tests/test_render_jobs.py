"""The render queue: who may touch it, and what a result has to be.

The invariants, most important first:

1. **An unset token closes the queue.** A missing secret that degrades to no
   authentication is how an internal queue silently becomes a public one — and
   the failure looks like everything working.
2. **The guard is actually attached.** FastAPI copies a router's dependency
   list when each route is registered, so a guard assigned after the routes are
   declared protects nothing while the code reads as though it does. That is
   not hypothetical: it is how the first version of this router shipped.
3. **A worker's word is not evidence.** The finished file is re-probed here,
   because a worker on another machine can be misconfigured or half-updated.
4. **The video lands in the approval queue, never past it.** The worst a broken
   worker can do is put a bad video in front of a person.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.main import app
from app.models import (
    AgentSettings,
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentStatus,
    RenderJob,
    RenderJobKind,
)
from app.services.tenant_context import org_scope

ORG = 1
TOKEN = "a-token-only-the-worker-has"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — render queue tests need live Postgres")
    return url


@pytest.fixture
def media_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """The media volume lives at /data/media in the container and nowhere on a
    developer's Mac."""
    monkeypatch.setattr(get_settings(), "CONTENT_MEDIA_DIR", str(tmp_path), raising=False)
    return tmp_path


@pytest.fixture
def worker_token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(get_settings(), "RENDER_WORKER_TOKEN", TOKEN, raising=False)
    return TOKEN


def _client(token: str | None = TOKEN) -> AsyncClient:
    headers = {"X-Worker-Token": token} if token else {}
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    )


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM render_jobs"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


async def _piece_with_job(
    status: ContentStatus = ContentStatus.DRAFT,
) -> tuple[int, int]:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.RECORDED,
            language=ContentLanguage.EN,
            status=status,
            hook="A clip",
            media_path="d" * 32 + ".mp4",
        )
        db.add(piece)
        await db.commit()
        job = RenderJob(org_id=ORG, piece_id=piece.id, kind=RenderJobKind.SUBTITLE_A)
        db.add(job)
        await db.commit()
        return piece.id, job.id


async def _brokerage(value: str = "Engel & Völkers Aspen") -> None:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(text("SELECT id FROM agent_settings WHERE org_id=1"))
        ).first()
        if row is None:
            db.add(AgentSettings(org_id=ORG, brokerage_line=value))
        else:
            await db.execute(
                text("UPDATE agent_settings SET brokerage_line=:v WHERE org_id=1"),
                {"v": value},
            )
        await db.commit()


# ── The boundary ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_token_no_queue(database_url: str, worker_token: str) -> None:
    async with _client(token=None) as client:
        resp = await client.post("/api/v1/internal/render-jobs/claim?worker=x")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_a_wrong_token_is_refused(database_url: str, worker_token: str) -> None:
    async with _client(token=TOKEN + "x") as client:
        resp = await client.post("/api/v1/internal/render-jobs/claim?worker=x")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_an_unset_token_closes_the_queue_rather_than_opening_it(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure this is built to prevent: a secret nobody set, degrading to
    no authentication, on a route that hands out an agency's footage."""
    monkeypatch.setattr(get_settings(), "RENDER_WORKER_TOKEN", "", raising=False)
    async with _client(token=None) as client:
        resp = await client.post("/api/v1/internal/render-jobs/claim?worker=x")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_every_route_carries_the_guard(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not one route — every one of them.

    FastAPI copies `router.dependencies` when each route is REGISTERED, so a
    guard attached after the decorators run protects nothing at all while the
    module reads as if it were guarded. The first version of this router did
    exactly that. Asserting on one route would not have caught it either: they
    would all have been equally unguarded.
    """
    monkeypatch.setattr(get_settings(), "RENDER_WORKER_TOKEN", TOKEN, raising=False)
    paths = [
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/internal/render-jobs")
    ]
    assert len(paths) >= 5, f"the queue's routes moved: {paths}"

    async with _client(token=None) as client:
        for path in paths:
            probe = path.replace("{job_id}", "1")
            for method in ("get", "post", "put"):
                resp = await getattr(client, method)(probe)
                # 405 means the route exists with another verb; anything that
                # is NOT 401/405 means an unauthenticated caller got through.
                assert resp.status_code in (401, 405), (
                    f"{method.upper()} {probe} answered {resp.status_code} "
                    "without a worker token"
                )


# ── The queue ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_job_is_handed_out_once(database_url: str, worker_token: str) -> None:
    try:
        await _piece_with_job()
        async with _client() as client:
            first = await client.post("/api/v1/internal/render-jobs/claim?worker=a")
            second = await client.post("/api/v1/internal/render-jobs/claim?worker=b")
        assert first.status_code == 200 and first.json() is not None
        # Nothing left to hand out — the second worker is told so rather than
        # being given the same job.
        assert second.json() is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_input_carries_the_brokerage_line_and_no_tenant_data(
    database_url: str, worker_token: str
) -> None:
    """A render is a video and a line of text. The worker gets exactly that."""
    await _brokerage()
    try:
        _piece_id, job_id = await _piece_with_job()
        async with _client() as client:
            resp = await client.get(f"/api/v1/internal/render-jobs/{job_id}/input")
        body = resp.json()
        assert body["brokerage_line"] == "Engel & Völkers Aspen"
        assert body["has_media"] is True
        assert "org_id" not in body
        assert "email" not in body
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_dead_claim_goes_back_to_the_queue(
    database_url: str, worker_token: str
) -> None:
    """A worker that died mid-job must not take the piece with it."""
    try:
        _piece_id, job_id = await _piece_with_job()
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text(
                    "UPDATE render_jobs SET status='claimed', worker='ghost', "
                    "claimed_at=:t WHERE id=:i"
                ),
                {"t": datetime.now(UTC) - timedelta(hours=5), "i": job_id},
            )
            await db.commit()

        async with _client() as client:
            resp = await client.post("/api/v1/internal/render-jobs/claim?worker=alive")
        assert resp.json()["id"] == job_id
        assert resp.json()["attempts"] == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_job_that_beat_three_workers_stops_and_says_why(
    database_url: str, worker_token: str
) -> None:
    """Retrying forever is how a queue full of poison never empties, and the
    reason has to reach the console rather than the log."""
    try:
        piece_id, job_id = await _piece_with_job()
        async with _client() as client:
            for _ in range(3):
                await client.post(
                    f"/api/v1/internal/render-jobs/{job_id}/fail",
                    json={"error": "ffmpeg said no"},
                )
        async with get_bypass_session_factory()() as db:
            status, attempts = (
                await db.execute(
                    text("SELECT status, attempts FROM render_jobs WHERE id=:i"),
                    {"i": job_id},
                )
            ).one()
            render_error = (
                await db.execute(
                    text("SELECT render_error FROM content_pieces WHERE id=:i"),
                    {"i": piece_id},
                )
            ).scalar_one()
        assert (status, attempts) == ("failed", 3)
        assert "ffmpeg said no" in render_error
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_not_buried(
    database_url: str, worker_token: str
) -> None:
    try:
        _piece_id, job_id = await _piece_with_job()
        async with _client() as client:
            resp = await client.post(
                f"/api/v1/internal/render-jobs/{job_id}/fail",
                json={"error": "image provider timed out"},
            )
        assert resp.json()["status"] == "queued"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_result_that_is_not_a_video_is_refused(
    database_url: str, worker_token: str, media_dir
) -> None:
    """The worker's word is not evidence. This side re-probes the file."""
    try:
        piece_id, job_id = await _piece_with_job()
        async with _client() as client:
            resp = await client.put(
                f"/api/v1/internal/render-jobs/result?job_id={job_id}",
                content=b"this is not an mp4",
            )
        assert resp.status_code == 422
        async with get_bypass_session_factory()() as db:
            status = (
                await db.execute(
                    text("SELECT status FROM content_pieces WHERE id=:i"),
                    {"i": piece_id},
                )
            ).scalar_one()
        # Still a draft: a rejected render must not advance anything.
        assert status == "draft"
    finally:
        await _cleanup()


HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
async def test_a_perfectly_valid_video_of_the_wrong_shape_is_refused(
    database_url: str, worker_token: str, media_dir
) -> None:
    """The test that actually holds the verification.

    Sending garbage does not: ffprobe rejects it before any of our checks run,
    so a version of this route with the verification DELETED still answered
    422 and the suite stayed green. A mutation proved it. What a
    misconfigured or half-updated worker actually produces is a real, readable
    video of the wrong size — 1920x1080 instead of 1080x1920 — and that is
    what has to be refused here, because the panel does not take the worker's
    word for the result.
    """
    landscape = media_dir / "landscape.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=25:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(landscape),
        ],
        check=True,
        capture_output=True,
    )
    try:
        piece_id, job_id = await _piece_with_job()
        async with _client() as client:
            resp = await client.put(
                f"/api/v1/internal/render-jobs/result?job_id={job_id}",
                content=landscape.read_bytes(),
            )
        assert resp.status_code == 422
        assert "1920x1080" in resp.text
        async with get_bypass_session_factory()() as db:
            status, job_status = (
                await db.execute(
                    text(
                        "SELECT p.status, j.status FROM content_pieces p "
                        "JOIN render_jobs j ON j.piece_id = p.id WHERE p.id = :i"
                    ),
                    {"i": piece_id},
                )
            ).one()
        # The piece did not advance, and the job carries the reason.
        assert status == "draft"
        assert job_status == "failed"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_empty_result_is_refused(
    database_url: str, worker_token: str, media_dir
) -> None:
    try:
        _piece_id, job_id = await _piece_with_job()
        async with _client() as client:
            resp = await client.put(
                f"/api/v1/internal/render-jobs/result?job_id={job_id}", content=b""
            )
        assert resp.status_code == 400
    finally:
        await _cleanup()


# ── Enqueueing ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_with_a_worker_the_clip_is_queued_instead_of_rendered_here(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.content_render import render_pending

    await _brokerage()
    monkeypatch.setattr(get_settings(), "RENDER_WORKER_ENABLED", True, raising=False)

    async def _never(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("the local renderer ran while a worker was configured")

    monkeypatch.setattr("app.services.content_render.render_clip", _never)
    try:
        async with get_bypass_session_factory()() as db:
            piece = ContentPiece(
                org_id=ORG,
                kind=ContentKind.RECORDED,
                language=ContentLanguage.EN,
                status=ContentStatus.DRAFT,
                hook="A clip",
                media_path="e" * 32 + ".mp4",
            )
            db.add(piece)
            await db.commit()
            piece_id = piece.id

        with org_scope(ORG):
            async with get_session_factory()() as db:
                queued = await render_pending(db)
                # Twice: the constraint, not the code, is what makes this
                # idempotent, and a restart between the query and the commit
                # must not double the work.
                again = await render_pending(db)
        assert (queued, again) == (1, 0)

        async with get_bypass_session_factory()() as db:
            rows = (
                await db.execute(
                    text("SELECT count(*) FROM render_jobs WHERE piece_id=:p"),
                    {"p": piece_id},
                )
            ).scalar_one()
            rendered_at = (
                await db.execute(
                    text("SELECT rendered_at FROM content_pieces WHERE id=:p"),
                    {"p": piece_id},
                )
            ).scalar_one()
        assert rows == 1
        # NOT stamped: "dealt with" is not true of a job nobody has done, and
        # stamping it would hide the clip from this sweep forever if the worker
        # never came back.
        assert rendered_at is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_render_jobs_are_tenant_isolated(database_url: str) -> None:
    """RLS, like every tenant table here. A worker reads on the bypass engine;
    everything inside a request does not."""
    try:
        _piece_id, job_id = await _piece_with_job()
        with org_scope(999):
            async with get_session_factory()() as db:
                found = (
                    await db.execute(
                        text("SELECT count(*) FROM render_jobs WHERE id=:i"),
                        {"i": job_id},
                    )
                ).scalar_one()
        assert found == 0
    finally:
        await _cleanup()
