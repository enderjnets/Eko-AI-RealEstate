"""The approval queue over HTTP: the routes hold the line the service draws.

The service tests prove the gate; these prove the doors. What matters here is
what an operator can actually do from the console: file a draft, be refused
while the filter objects, approve, and — the load-bearing one — lose the
approval by editing, because the person approved the old text.
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory
from app.main import app
from app.models import ContentStatus


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — content API tests need live Postgres")
    return url


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


CLEAN = {
    "kind": "generated",
    "language": "en",
    "hook": "Three things to check before an offer in Denver.",
    "script": "Inspection, comps, and your loan estimate.",
}


@pytest.mark.asyncio
async def test_a_clean_draft_walks_to_approved(database_url: str) -> None:
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=CLEAN)
            assert created.status_code == 201, created.text
            piece = created.json()
            assert piece["status"] == "draft"
            assert piece["violations"] is None

            submitted = await client.post(
                f"/api/v1/content/{piece['id']}/submit"
            )
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["status"] == "needs_approval"

            approved = await client.post(
                f"/api/v1/content/{piece['id']}/approve"
            )
            assert approved.status_code == 200, approved.text
            body = approved.json()
            assert body["status"] == "approved"
            # Auth is off in this environment, so the honest answer is the
            # office identity — never an empty field.
            assert body["approved_by"] == "office"
            assert body["approved_at"] is not None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_draft_with_violations_is_refused_at_the_door(
    database_url: str,
) -> None:
    """422 with the phrases named, and the piece stays a draft."""
    try:
        async with _client() as client:
            created = await client.post(
                "/api/v1/content",
                json={**CLEAN, "hook": "Perfect for families, safe neighborhood."},
            )
            piece = created.json()
            assert piece["violations"], "the stored findings are the operator's map"

            submitted = await client.post(
                f"/api/v1/content/{piece['id']}/submit"
            )
            assert submitted.status_code == 422
            detail = submitted.json()["detail"]
            phrases = {v["phrase"] for v in detail["violations"]}
            assert "perfect for families" in phrases
            assert "safe neighborhood" in phrases

            listed = await client.get(
                "/api/v1/content", params={"status": "draft"}
            )
            assert [p["id"] for p in listed.json()] == [piece["id"]]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_editing_an_approved_piece_revokes_the_approval(
    database_url: str,
) -> None:
    """The person approved the OLD text."""
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=CLEAN)
            piece_id = created.json()["id"]
            await client.post(f"/api/v1/content/{piece_id}/submit")
            await client.post(f"/api/v1/content/{piece_id}/approve")

            edited = await client.patch(
                f"/api/v1/content/{piece_id}",
                json={"hook": "Two things to check before an offer."},
            )
            assert edited.status_code == 200, edited.text
            body = edited.json()
            assert body["status"] == "needs_approval", (
                "an edit left the approval standing on text nobody read"
            )
            assert body["approved_by"] is None
            assert body["approved_at"] is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_edit_that_changes_nothing_keeps_the_approval(
    database_url: str,
) -> None:
    """Saving without changes is not an edit, and revoking on it teaches
    people not to open the editor."""
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=CLEAN)
            piece_id = created.json()["id"]
            await client.post(f"/api/v1/content/{piece_id}/submit")
            await client.post(f"/api/v1/content/{piece_id}/approve")

            same = await client.patch(
                f"/api/v1/content/{piece_id}", json={"hook": CLEAN["hook"]}
            )
            assert same.json()["status"] == "approved"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_rejection_requires_a_reason(database_url: str) -> None:
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=CLEAN)
            piece_id = created.json()["id"]
            await client.post(f"/api/v1/content/{piece_id}/submit")

            bare = await client.post(f"/api/v1/content/{piece_id}/reject", json={})
            assert bare.status_code == 422

            reasoned = await client.post(
                f"/api/v1/content/{piece_id}/reject",
                json={"reason": "Wrong tone for the audience."},
            )
            assert reasoned.status_code == 200
            assert reasoned.json()["status"] == "rejected"
            assert reasoned.json()["rejected_reason"]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_published_piece_cannot_be_edited(database_url: str) -> None:
    """The text on the platform would not change, so pretending here would
    make the database disagree with the world."""
    async with get_bypass_session_factory()() as db:
        from app.models import ContentKind, ContentLanguage, ContentPiece

        piece = ContentPiece(
            org_id=1,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
            hook=CLEAN["hook"],
        )
        db.add(piece)
        await db.commit()
        piece_id = piece.id
    try:
        async with _client() as client:
            edited = await client.patch(
                f"/api/v1/content/{piece_id}", json={"hook": "New words."}
            )
            assert edited.status_code == 409
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_upload_stores_the_clip_and_serves_it_back(
    database_url: str, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "CONTENT_MEDIA_DIR", str(tmp_path))
    payload = b"\x00\x00\x00\x18ftypmp42" + b"fake video bytes" * 100
    try:
        async with _client() as client:
            uploaded = await client.post(
                "/api/v1/content/upload",
                params={"filename": "clip from phone.mp4", "language": "es"},
                content=payload,
            )
            assert uploaded.status_code == 201, uploaded.text
            piece = uploaded.json()
            assert piece["status"] == "draft"
            assert piece["kind"] == "recorded"
            assert piece["language"] == "es"

            served = await client.get(f"/api/v1/content/{piece['id']}/media")
            assert served.status_code == 200
            assert served.content == payload

            # The name on disk is ours, not the phone's.
            stored = piece["media_path"]
            assert stored.endswith(".mp4") and "clip" not in stored
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_upload_refuses_what_is_not_a_video(
    database_url: str, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "CONTENT_MEDIA_DIR", str(tmp_path))
    try:
        async with _client() as client:
            refused = await client.post(
                "/api/v1/content/upload",
                params={"filename": "notes.pdf"},
                content=b"%PDF-1.4",
            )
            assert refused.status_code == 415

            empty = await client.post(
                "/api/v1/content/upload",
                params={"filename": "clip.mp4"},
                content=b"",
            )
            assert empty.status_code == 400
            leftovers = list(tmp_path.iterdir())
            assert leftovers == [], (
                f"a refused upload left bytes on the volume: {leftovers}"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_media_of_a_missing_piece_is_a_404(database_url: str) -> None:
    async with _client() as client:
        assert (await client.get("/api/v1/content/999999/media")).status_code == 404
