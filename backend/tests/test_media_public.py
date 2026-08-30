"""The unauthenticated media route: the gate is the status, and it holds.

This route exists because Buffer downloads the video by URL when the post goes
out and rejects signed links, so the usual answer here — an HMAC link with a
TTL — cannot work. What replaces it is the piece's status, and these tests are
the reason that replacement is not just a smaller lock: unapproved footage is
unreachable, and every refusal looks the same so the address cannot be used to
enumerate an agency's unpublished work.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import ContentKind, ContentLanguage, ContentPiece, ContentStatus

ORG = 1
NAME = "b" * 32 + ".mp4"
BYTES = b"\x00\x00\x00\x18ftypmp42fake-video-bytes-for-the-test"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — public media tests need live Postgres")
    return url


@pytest.fixture
def media_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "CONTENT_MEDIA_DIR", str(tmp_path), raising=False)
    (tmp_path / NAME).write_bytes(BYTES)
    return tmp_path


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _piece(status: ContentStatus, media: str | None = NAME) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.RECORDED,
            language=ContentLanguage.EN,
            status=status,
            hook="A clip",
            media_path=media,
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [ContentStatus.APPROVED, ContentStatus.PUBLISHING, ContentStatus.PUBLISHED],
)
async def test_a_piece_on_its_way_out_is_fetchable(
    database_url: str, media_dir: Path, status: ContentStatus
) -> None:
    """PUBLISHING and PUBLISHED are here on purpose: Buffer fetches after the
    post was created, and a platform may re-fetch. Without them the video
    would vanish mid-publication."""
    try:
        piece_id = await _piece(status)
        async with _client() as client:
            resp = await client.get(f"/api/v1/public/content/{piece_id}/media")
        assert resp.status_code == 200
        assert resp.content == BYTES
        assert resp.headers["content-type"] == "video/mp4"
        # Nothing in between may keep a copy: an edit revokes the approval and
        # a cached body would outlive that decision.
        assert resp.headers["cache-control"] == "no-store"
    finally:
        await _cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [ContentStatus.DRAFT, ContentStatus.NEEDS_APPROVAL, ContentStatus.REJECTED,
     ContentStatus.FAILED],
)
async def test_unapproved_footage_is_not_reachable(
    database_url: str, media_dir: Path, status: ContentStatus
) -> None:
    """The gate. A client agency's unpublished footage is not public because
    somebody guessed a number."""
    try:
        piece_id = await _piece(status)
        async with _client() as client:
            resp = await client.get(f"/api/v1/public/content/{piece_id}/media")
        assert resp.status_code == 404
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_every_refusal_looks_identical(
    database_url: str, media_dir: Path
) -> None:
    """Telling "no such piece" apart from "not approved yet" hands a stranger
    a way to enumerate what an agency is working on."""
    try:
        draft = await _piece(ContentStatus.DRAFT)
        no_file = await _piece(ContentStatus.APPROVED, media="c" * 32 + ".mp4")
        async with _client() as client:
            answers = [
                await client.get(f"/api/v1/public/content/{draft}/media"),
                await client.get(f"/api/v1/public/content/{no_file}/media"),
                await client.get("/api/v1/public/content/99999999/media"),
            ]
        assert [a.status_code for a in answers] == [404, 404, 404]
        assert len({a.text for a in answers}) == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_path_that_stopped_looking_like_ours_is_refused(
    database_url: str, media_dir: Path, tmp_path: Path
) -> None:
    """The stored name is one we wrote, but it is about to be joined to a
    filesystem path."""
    secret = tmp_path.parent / "secret.txt"
    secret.write_bytes(b"not yours")
    try:
        piece_id = await _piece(ContentStatus.APPROVED, media="../secret.txt")
        async with _client() as client:
            resp = await client.get(f"/api/v1/public/content/{piece_id}/media")
        assert resp.status_code == 404
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_route_answers_range_requests(
    database_url: str, media_dir: Path
) -> None:
    """How the platforms fetch large media. Without it a fetch of a 20 MB
    video either fails or is served whole into one worker's memory."""
    try:
        piece_id = await _piece(ContentStatus.APPROVED)
        async with _client() as client:
            resp = await client.get(
                f"/api/v1/public/content/{piece_id}/media",
                headers={"Range": "bytes=0-9"},
            )
        assert resp.status_code == 206
        assert resp.content == BYTES[:10]
    finally:
        await _cleanup()
