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

import app.main as main_module
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


async def _attach_video(piece_id: int) -> None:
    """What the render does before a person is asked to approve anything.

    Approval now requires a video, because a piece approved without one can
    never receive it: the worker is refused with a 409 and the piece is stuck
    approved and empty. These tests walk the same road production walks.
    """
    async with get_bypass_session_factory()() as db:
        from app.models import ContentPiece as _Piece

        piece = await db.get(_Piece, piece_id)
        piece.media_path = "0123456789abcdef0123456789abcdef.mp4"
        await db.commit()


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

            await _attach_video(piece["id"])
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
            await _attach_video(piece_id)
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


# --------------------------------------------------------------------------
# Why the queue is empty — the question "nothing here right now" does not answer
# --------------------------------------------------------------------------


async def _read_brokerage() -> str | None:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text("SELECT brokerage_line FROM agent_settings WHERE org_id = 1")
            )
        ).scalar_one_or_none()


async def _set_brokerage(line: str | None) -> None:
    """Scoped to org 1, and the caller restores what was there.

    The first version of this had no WHERE clause and ran on a bypass session,
    so RLS did not stop it: it rewrote `brokerage_line` for EVERY organisation
    and the `finally` left them all NULL. `agent_settings` is not test material
    the way `content_pieces` is — it is the configuration row carrying a legal
    obligation, and a suite that blanks it makes `render_pending` refuse every
    clip afterwards, which reads as a product bug rather than as a test.
    """
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE agent_settings SET brokerage_line = :v WHERE org_id = 1"),
            {"v": line},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_an_oversized_clip_is_cut_mid_stream_and_leaves_nothing_behind(
    database_url: str, tmp_path, monkeypatch
) -> None:
    """The app's own 413, which until now could not be reached.

    With the limit at 500 MB this branch was dead text: production measured
    99 MB through and 120 MB cut at the edge by Cloudflare with a 413 our app
    never saw. The tunnel gives out around 100 MB, so the limit the code
    enforced was guarding a door a different wall had already bricked up. At 95
    the app is the one that answers, which is the only way the message can name
    the real number.

    The limit is monkeypatched down rather than sending 95 MB: what is under
    test is the mid-stream cut, not the arithmetic of megabytes.

    Asserts the cleanup too. The refusal happens PART WAY through writing, so
    the obvious bug is a truncated file left on the volume — bytes nobody
    accounted for, under a name that looks like a real clip.
    """
    monkeypatch.setattr(get_settings(), "CONTENT_MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(get_settings(), "CONTENT_UPLOAD_MAX_MB", 1)
    # BOTH layers, or this test is a fiction. `_STREAM_PATHS` is built at import
    # from the setting, so monkeypatching the setting alone leaves the
    # middleware at 95 MB while the route sits at 1 — a configuration that
    # cannot exist, exercising a branch production never enters. The first
    # version of this test did exactly that and passed.
    monkeypatch.setitem(
        main_module._STREAM_PATHS, "/api/v1/content/upload", 1 * 1024 * 1024
    )
    payload = b"\x00\x00\x00\x18ftypmp42" + b"x" * (2 * 1024 * 1024)
    try:
        async with _client() as client:
            too_big = await client.post(
                "/api/v1/content/upload",
                params={"filename": "4k-from-the-phone.mp4", "language": "en"},
                content=payload,
            )
            assert too_big.status_code == 413, too_big.text
            # The number has to be in the ANSWER, or the person cannot act on
            # it: "too large" with no limit is a dead end on a phone. It comes
            # from `limit_mb`, not from `detail`: a browser always declares a
            # Content-Length, so the refusal a real user gets is the
            # middleware's `body_too_large`, never the route's prose.
            assert too_big.json()["limit_mb"] == 1, too_big.text

            leftovers = list(tmp_path.iterdir())
            assert leftovers == [], (
                f"a cut upload left a truncated clip on the volume: {leftovers}"
            )

            # And nothing reached the queue: a piece with a half-written file
            # would be rendered, reviewed and published from bytes that stop.
            listed = await client.get("/api/v1/content")
            assert listed.status_code == 200
            assert listed.json() == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_chunked_upload_that_declares_no_length_is_still_cut(
    database_url: str, tmp_path, monkeypatch
) -> None:
    """The case the ROUTE's own check exists for, and the only one it answers.

    A browser always declares a Content-Length, so `BodySizeLimit` in `main.py`
    refuses an oversized clip before the route sees a byte — which is why the
    route's prose about the cap is never what a person reads. But a chunked
    body declares nothing to check, the middleware waves streaming paths
    through untouched, and then the route counting bytes as they land is the
    only thing standing between us and a disk filled by an authenticated
    caller.

    So the two checks are not redundant, and this is the half that would go
    unnoticed if it broke: no client in the product exercises it, and the other
    test in this file cannot reach it.
    """
    monkeypatch.setattr(get_settings(), "CONTENT_MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(get_settings(), "CONTENT_UPLOAD_MAX_MB", 1)

    async def _chunks():
        yield b"\x00\x00\x00\x18ftypmp42"
        for _ in range(3):
            yield b"x" * (512 * 1024)

    try:
        async with _client() as client:
            r = await client.post(
                "/api/v1/content/upload",
                params={"filename": "chunked.mp4", "language": "en"},
                content=_chunks(),
            )
            assert r.status_code == 413, r.text
            # The route's own words this time, naming the cap.
            assert "1 MB" in r.json()["detail"], r.text
            assert list(tmp_path.iterdir()) == [], "a cut chunked upload left bytes"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_status_answers_with_the_whole_contract(database_url: str) -> None:
    """Every field the console reads, present in one response.

    This used to be named for route ordering and claimed `/status` had to be
    declared before the parametric routes. It does not: there is no
    `GET /{piece_id}` in this router, so moving the decorator to the bottom of
    the file leaves the test green. A test whose name promises something it
    cannot detect is worse than no test — it is a claim nobody will re-check.
    Ordering is still correct here, and still the repo's rule; it just is not
    what this asserts.
    """
    async with _client() as client:
        r = await client.get("/api/v1/content/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "studio_enabled",
        "render_enabled",
        "brokerage_line_set",
        "publishing_available",
        "publishing_ready",
        "upload_max_mb",
        "timezone",
        "counts",
    }
    # The value, not just the key. The browser refuses a file by comparing
    # `file.size` against this number, so a status endpoint that reports a
    # limit the server does not enforce would reject good clips or wave
    # through ones the upload will kill halfway.
    from app.config import get_settings

    assert body["upload_max_mb"] == get_settings().CONTENT_UPLOAD_MAX_MB
    # Same reasoning for the zone, and it matters more than it looks: the
    # console renders a scheduled post's date in it, and a date shown in the
    # reader's own zone is simply the wrong time — 20:30 in Denver reads as
    # 03:30 in Madrid, with nothing on screen to say so. It must never be
    # empty, because an empty string silently falls back to the browser's.
    assert body["timezone"]
    from zoneinfo import ZoneInfo

    ZoneInfo(body["timezone"])  # raises if it is not a zone anyone can use
    assert body["upload_max_mb"] > 0


@pytest.mark.asyncio
async def test_status_reports_the_brokerage_line_as_the_gates_read_it(
    database_url: str,
) -> None:
    """Whitespace is not a brokerage line — `content_render` and
    `content_studio` both strip before deciding, so a status that answered
    `true` for "   " would send a person looking for a different problem."""
    previous = await _read_brokerage()
    try:
        await _set_brokerage("Natalia & Robbie · Engel & Völkers")
        async with _client() as client:
            assert (await client.get("/api/v1/content/status")).json()[
                "brokerage_line_set"
            ] is True

        await _set_brokerage("   ")
        async with _client() as client:
            assert (await client.get("/api/v1/content/status")).json()[
                "brokerage_line_set"
            ] is False

        await _set_brokerage(None)
        async with _client() as client:
            assert (await client.get("/api/v1/content/status")).json()[
                "brokerage_line_set"
            ] is False
    finally:
        await _set_brokerage(previous)


@pytest.mark.asyncio
async def test_status_counts_every_state_including_the_empty_ones(
    database_url: str,
) -> None:
    """A missing key and a zero are different answers to "how many drafts".
    The console renders per state, so every state has to be present."""
    try:
        async with _client() as client:
            before = (await client.get("/api/v1/content/status")).json()["counts"]
            assert set(before) == {
                "draft",
                "needs_approval",
                "approved",
                "rejected",
                "publishing",
                "published",
                "failed",
            }, before

            created = await client.post("/api/v1/content", json=CLEAN)
            assert created.status_code == 201, created.text
            after = (await client.get("/api/v1/content/status")).json()["counts"]
        assert after["draft"] == before["draft"] + 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_publishing_is_reported_as_unavailable_while_it_is(
    database_url: str,
) -> None:
    """An empty `publications` list cannot distinguish "not published yet"
    from "nothing here can publish". Both answers still exist, and since v0.65
    they are different fields.

    This test used to assert `publishing_available is False` as a literal, on
    purpose, so that flipping the constant would fail it — the day that
    happened being the day the console's wording, the release notes and this
    test all needed revisiting together. That day was v0.65 and this is the
    revisit: the publisher exists, so the machinery question is answered True,
    and the question a reader of the console actually has moved to
    `publishing_ready` — is it switched on and configured HERE.

    Both are literals rather than comparisons against the code they describe:
    an assertion that reads the same constant the endpoint reads proves only
    that the two agree, which they cannot help doing.
    """
    async with _client() as client:
        body = (await client.get("/api/v1/content/status")).json()
    assert body["publishing_available"] is True
    # False in the test environment: no channels are configured, which is
    # exactly the state the console has to be able to explain.
    assert body["publishing_ready"] is False


@pytest.mark.asyncio
async def test_the_render_reason_reaches_the_console(database_url: str) -> None:
    """`render_error` was written from v0.52 and returned by nothing.

    An agency whose clip could not render — no brokerage line, ffmpeg refused,
    anything — saw it sit unrendered with no reason anywhere in the product.
    """
    try:
        async with _client() as client:
            piece_id = (await client.post("/api/v1/content", json=CLEAN)).json()["id"]
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE content_pieces SET render_error = :e WHERE id = :i"),
                {"e": "waiting: no brokerage line on record", "i": piece_id},
            )
            await db.commit()
        async with _client() as client:
            listed = (await client.get("/api/v1/content?status=draft")).json()
        mine = [p for p in listed if p["id"] == piece_id]
        assert mine, "the piece disappeared from its own status listing"
        assert mine[0]["render_error"] == "waiting: no brokerage line on record"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_clip_arrives_even_with_no_brokerage_line(
    database_url: str, tmp_path, monkeypatch
) -> None:
    """The brokerage gate stops rendering and publishing, not uploading.

    Refusing the upload would lose the footage — she filmed it, the studio is
    where it lives, and the missing line is a five-second fix she may not be
    the person to make. It lands in DRAFT and the console says why it has not
    rendered.
    """
    monkeypatch.setattr(get_settings(), "CONTENT_MEDIA_DIR", str(tmp_path))
    previous = await _read_brokerage()
    try:
        await _set_brokerage(None)
        async with _client() as client:
            r = await client.post(
                "/api/v1/content/upload?filename=phone.mov&language=en",
                content=b"not really a video, but bytes are bytes here",
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "draft"
        assert body["kind"] == "recorded"
        assert body["media_path"].endswith(".mov")
    finally:
        await _cleanup()
        await _set_brokerage(previous)


@pytest.mark.asyncio
async def test_a_file_that_is_not_a_video_is_named_as_such(database_url: str) -> None:
    """415, not a generic failure: "that is not a video" and "that is too big"
    have different fixes, and the console shows the server's own words."""
    async with _client() as client:
        r = await client.post(
            "/api/v1/content/upload?filename=notes.pdf&language=en",
            content=b"%PDF-1.4",
        )
    assert r.status_code == 415
    assert "video" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_caption_can_be_cleared(database_url: str) -> None:
    """Emptying a text field must actually empty it.

    The console sends hook, script and caption as strings on every save
    (`ContentQueue.tsx:287`), and the trimming validator turns "" into None. The
    handler skipped None — a reasonable rule on its own — so clearing a caption
    returned 200 with the old text still in the database. The realtor emptied
    the box, saw "saved", and watched the words come back.

    A 200 that discards the edit is worse than a 400: nobody goes looking.
    Worse here than elsewhere, because this is how flagged wording gets removed
    — and if the delete never lands, `_refresh_violations` never re-runs and the
    Fair Housing hit stays attached to a piece whose text looks clean.

    The distinction the handler needs is "was this field sent?", which is
    `model_fields_set`, not "is it None?".
    """
    try:
        async with _client() as client:
            created = await client.post(
                "/api/v1/content", json={**CLEAN, "caption": "Original caption."}
            )
            piece_id = created.json()["id"]
            assert created.json()["caption"] == "Original caption."

            cleared = await client.patch(
                f"/api/v1/content/{piece_id}", json={"caption": ""}
            )
            assert cleared.status_code == 200, cleared.text
            assert cleared.json()["caption"] is None, "the clear was silently dropped"

            # And it really is gone, not just absent from this response.
            fetched = await client.get("/api/v1/content?status=draft")
            mine = [p for p in fetched.json() if p["id"] == piece_id][0]
            assert mine["caption"] is None

            # Whitespace-only means the same thing.
            await client.patch(
                f"/api/v1/content/{piece_id}", json={"caption": "Back again."}
            )
            blanked = await client.patch(
                f"/api/v1/content/{piece_id}", json={"caption": "   "}
            )
            assert blanked.json()["caption"] is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_an_unsent_field_is_left_alone(database_url: str) -> None:
    """The control for the test above.

    Without it, "clear whatever is None" would pass — and a PATCH naming only
    the hook would wipe the script and caption it never mentioned.
    """
    try:
        async with _client() as client:
            created = await client.post(
                "/api/v1/content",
                json={**CLEAN, "script": "Keep me.", "caption": "Me too."},
            )
            piece_id = created.json()["id"]

            edited = await client.patch(
                f"/api/v1/content/{piece_id}", json={"hook": "Only the hook moves."}
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["hook"] == "Only the hook moves."
            assert edited.json()["script"] == "Keep me.", "an unsent field was cleared"
            assert edited.json()["caption"] == "Me too.", "an unsent field was cleared"
    finally:
        await _cleanup()



async def _seeded(
    status: ContentStatus,
    *,
    scenes: bool = False,
    media: bool = False,
    kind_recorded: bool = False,
) -> int:
    """A piece sitting in `status`, for the tests that start from one."""
    async with get_bypass_session_factory()() as db:
        from app.models import ContentKind, ContentLanguage, ContentPiece

        piece = ContentPiece(
            org_id=1,
            kind=ContentKind.RECORDED if kind_recorded else ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=status,
            hook=CLEAN["hook"],
            approved_by="someone@example.com",
            media_path="0123456789abcdef0123456789abcdef.mp4" if media else None,
            scenes=(
                {"narration": "A line.", "scenes": [{"visual_prompt": "a house"}]}
                if scenes
                else None
            ),
        )
        db.add(piece)
        await db.commit()
        return piece.id


@pytest.mark.asyncio
async def test_a_piece_that_failed_to_publish_can_be_tried_again(
    database_url: str,
) -> None:
    """FAILED was a dead end, and the commonest cause of it is not the video.

    The first real publish of this installation failed on all three platforms
    for three reasons — a 405 on our own media route, and two pieces of
    metadata Buffer requires — none of which a realtor could have seen in the
    piece. Without this the only way out was an UPDATE by hand on production.
    """
    try:
        piece_id = await _seeded(ContentStatus.FAILED)
        async with _client() as client:
            resp = await client.post(f"/api/v1/content/{piece_id}/retry")
        assert resp.status_code == 200
        # Back in front of a person, not straight out the door: nothing about
        # the artefact changed, so approving again costs one click and keeps
        # the invariant that a human approved what actually went out.
        assert resp.json()["status"] == "needs_approval"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_retry_is_refused_on_a_piece_that_did_publish(
    database_url: str,
) -> None:
    """PUBLISHED is a statement about the outside world, and nothing in here
    can un-post a video."""
    try:
        piece_id = await _seeded(ContentStatus.PUBLISHED)
        async with _client() as client:
            resp = await client.post(f"/api/v1/content/{piece_id}/retry")
        assert resp.status_code == 409
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_piece_with_no_video_cannot_be_approved(database_url: str) -> None:
    """The trap this closes was sprung in production on 2026-09-01.

    A generated piece reaches NEEDS_APPROVAL as soon as its text is clean,
    while the render is still running — so the console showed an Approve
    button beside a script with no video, and it was pressed. The worker
    finished, was refused with a 409 because the piece was no longer awaiting
    a render, retried twice more and died. The piece is approved, empty and
    unpublishable to this day, and nothing said a word.
    """
    try:
        piece_id = await _seeded(ContentStatus.NEEDS_APPROVAL)
        async with _client() as client:
            resp = await client.post(f"/api/v1/content/{piece_id}/approve")
        assert resp.status_code == 409
        assert "no video yet" in resp.json()["detail"]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_generated_piece_can_be_made_again(database_url: str) -> None:
    """Until this existed, a rendered piece was final: the only way to get a
    video that benefited from a change to the renderer was to wait for
    tomorrow's script — a strange thing to tell somebody who just changed the
    renderer because they did not like the video."""
    try:
        piece_id = await _seeded(ContentStatus.NEEDS_APPROVAL, scenes=True, media=True)
        async with _client() as client:
            resp = await client.post(f"/api/v1/content/{piece_id}/rebuild")
        assert resp.status_code == 200
        # No file, so the render sweep picks it up again — and the approval
        # gate refuses it meanwhile, which is the same invariant from v0.67.6.
        assert resp.json()["media_path"] is None
        assert resp.json()["status"] == "needs_approval"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_filmed_clip_is_never_rebuilt(database_url: str) -> None:
    """The safety rule, not a limitation. A recorded piece has no plan to
    rebuild from, and once the render has replaced `media_path` that field is
    the only copy of what the agent filmed. Clearing it would throw the footage
    away in order to make a new version of it."""
    try:
        piece_id = await _seeded(
            ContentStatus.NEEDS_APPROVAL, media=True, kind_recorded=True
        )
        async with _client() as client:
            resp = await client.post(f"/api/v1/content/{piece_id}/rebuild")
        assert resp.status_code == 409
        assert "only a generated piece" in resp.json()["detail"]
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_published_piece_is_never_rebuilt(database_url: str) -> None:
    """Nothing in here can un-post a video."""
    try:
        piece_id = await _seeded(ContentStatus.PUBLISHED, scenes=True, media=True)
        async with _client() as client:
            resp = await client.post(f"/api/v1/content/{piece_id}/rebuild")
        assert resp.status_code == 409
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_queue_reports_what_the_render_is_doing(database_url: str) -> None:
    """The console cannot say "queued" instead of "being made" unless the list
    actually carries the job's state. Written because the fix for a spinner
    that lied would be worth nothing if the field never reached the browser."""
    from app.models import MonitorState, RenderJob, RenderJobKind, RenderJobStatus

    try:
        piece_id = await _seeded(ContentStatus.NEEDS_APPROVAL, scenes=True)
        async with get_bypass_session_factory()() as db:
            db.add(
                RenderJob(
                    org_id=1,
                    piece_id=piece_id,
                    kind=RenderJobKind.PRODUCE_B,
                    status=RenderJobStatus.CLAIMED,
                    stage="pictures",
                    progress=45,
                )
            )
            db.add(
                MonitorState(
                    key="render_worker",
                    state="ok",
                    detail={"within_hours": False, "hours": [21, 23]},
                )
            )
            await db.commit()

        async with _client() as client:
            listed = await client.get("/api/v1/content")
        assert listed.status_code == 200
        mine = next(p for p in listed.json() if p["id"] == piece_id)
        assert mine["render_state"] == "claimed"
        assert mine["render_stage"] == "pictures"
        assert mine["render_progress"] == 45
        # And the case that started all this: the machine is outside its hours.
        assert mine["render_machine_working"] is False
    finally:
        async with get_bypass_session_factory()() as db:
            from sqlalchemy import delete

            await db.execute(delete(RenderJob))
            await db.execute(delete(MonitorState).where(MonitorState.key == "render_worker"))
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_a_queued_piece_cannot_be_edited_or_rejected(database_url: str) -> None:
    """PUBLISHING means somebody else is holding a copy of this text.

    With the queue, PUBLISHING stops being a state that lasts seconds: a
    scheduled post sits there for days while Buffer holds it, and the piece is
    kept there on purpose, because that is what protects it. Editing in that
    window would leave the database and the post disagreeing about what was
    published; rejecting would retire a piece that is about to appear in
    public.

    Both refusals already existed — `edit_piece` checks the status directly and
    `reject_piece` inherits it from the state machine, which has no edge from
    PUBLISHING to REJECTED. They are pinned here because days-long PUBLISHING
    is new, and an untested guard is a guard somebody simplifies away.
    """
    async with get_bypass_session_factory()() as db:
        from app.models import ContentKind, ContentLanguage, ContentPiece

        piece = ContentPiece(
            org_id=1,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHING,
            hook=CLEAN["hook"],
            caption="Three numbers decide the price.",
        )
        db.add(piece)
        await db.commit()
        piece_id = piece.id
    try:
        async with _client() as client:
            edited = await client.patch(
                f"/api/v1/content/{piece_id}", json={"caption": "different"}
            )
            assert edited.status_code == 409, edited.text

            rejected = await client.post(
                f"/api/v1/content/{piece_id}/reject",
                json={"reason": "changed my mind"},
            )
            assert rejected.status_code == 409, rejected.text

        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT status, caption FROM content_pieces WHERE id=:i"
                    ),
                    {"i": piece_id},
                )
            ).one()
        assert row[0] == "publishing"
        assert row[1] == "Three numbers decide the price."
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_listing_accepts_several_statuses(database_url: str) -> None:
    """One tab is not one status.

    "Approved" has to hold APPROVED *and* PUBLISHING — a piece handed to the
    queue is still waiting to go out, and it is precisely the one whose date a
    person opened the console to see. Before this, a piece left APPROVED and
    appeared in no tab at all, which is how pieces 6 and 7 became invisible
    the moment they published.
    """
    async with get_bypass_session_factory()() as db:
        from app.models import ContentKind, ContentLanguage, ContentPiece

        for status in (
            ContentStatus.APPROVED,
            ContentStatus.PUBLISHING,
            ContentStatus.REJECTED,
        ):
            db.add(
                ContentPiece(
                    org_id=1,
                    kind=ContentKind.GENERATED,
                    language=ContentLanguage.EN,
                    status=status,
                    hook=CLEAN["hook"],
                )
            )
        await db.commit()
    try:
        async with _client() as client:
            both = await client.get(
                "/api/v1/content?status=approved&status=publishing"
            )
            assert both.status_code == 200, both.text
            assert {p["status"] for p in both.json()} == {"approved", "publishing"}

            # The single-value contract still behaves exactly as it did.
            one = await client.get("/api/v1/content?status=rejected")
            assert {p["status"] for p in one.json()} == {"rejected"}

            # No filter still means everything.
            everything = await client.get("/api/v1/content")
            assert len(everything.json()) == 3
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_queued_piece_cannot_be_rebuilt(database_url: str) -> None:
    """Rebuilding clears `media_path`, and Buffer is waiting to fetch it.

    The public media route answers 404 without a file, so at the scheduled hour
    the post fails with a message about the URL — and the piece is then
    stranded in PUBLISHING for ever, because `publish_approved` only looks at
    rows that HAVE a file.

    The guard is new because the state is: before the queue, PUBLISHING lasted
    seconds and nobody could press the button during it. Now it lasts days and
    the console offers it the whole time.
    """
    async with get_bypass_session_factory()() as db:
        from app.models import ContentKind, ContentLanguage, ContentPiece

        piece = ContentPiece(
            org_id=1,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHING,
            hook=CLEAN["hook"],
            scenes=[{"visual_prompt": "a house", "on_screen_text": "hi"}],
            media_path="c" * 32 + ".mp4",
        )
        db.add(piece)
        await db.commit()
        piece_id = piece.id
    try:
        async with _client() as client:
            r = await client.post(f"/api/v1/content/{piece_id}/rebuild")
            assert r.status_code == 409, r.text

        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    text("SELECT status, media_path FROM content_pieces WHERE id=:i"),
                    {"i": piece_id},
                )
            ).one()
        assert row[0] == "publishing"
        assert row[1] is not None, "the video Buffer is waiting for was removed"
    finally:
        await _cleanup()


# --------------------------------------------------------------------------
# View counts typed by a person (v0.78)
# --------------------------------------------------------------------------


async def _publish(piece_id: int, platform: str, *, sent: bool) -> None:
    """A publication row in the state the console would show it in."""
    from datetime import UTC, datetime

    from app.models import (
        ContentPublication,
        PublicationPlatform,
        PublicationStatus,
    )

    async with get_bypass_session_factory()() as db:
        db.add(
            ContentPublication(
                org_id=1,
                piece_id=piece_id,
                platform=PublicationPlatform(platform),
                status=(
                    PublicationStatus.PUBLISHED if sent else PublicationStatus.PENDING
                ),
                published_at=datetime.now(UTC) if sent else None,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_a_typed_view_count_comes_back_on_the_piece(database_url: str) -> None:
    """The only way a TikTok or Instagram number ever arrives.

    Neither platform hands view counts to anything short of a first-party app
    with platform review, so this route is not a convenience — it is the whole
    mechanism for two of the three networks.
    """
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=CLEAN)
            piece_id = created.json()["id"]
            await _publish(piece_id, "tiktok", sent=True)

            saved = await client.put(
                f"/api/v1/content/{piece_id}/publications/tiktok/metrics",
                json={"views": 1240, "likes": 31},
            )
            assert saved.status_code == 200, saved.text
            publication = saved.json()["publications"][0]
            assert publication["latest_metrics"]["views"] == 1240
            assert publication["latest_metrics"]["likes"] == 31
            assert publication["latest_metrics"]["comments"] is None
            # The provenance travels with the number, so a hand-read count is
            # never displayed with the confidence of an API reading.
            assert publication["latest_metrics"]["source"] == "manual"

            # And the listing shows it too, which is where the console reads.
            listed = await client.get("/api/v1/content")
            row = next(p for p in listed.json() if p["id"] == piece_id)
            assert row["publications"][0]["latest_metrics"]["views"] == 1240
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_typing_it_twice_corrects_rather_than_appends(
    database_url: str,
) -> None:
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=CLEAN)
            piece_id = created.json()["id"]
            await _publish(piece_id, "instagram", sent=True)
            url = f"/api/v1/content/{piece_id}/publications/instagram/metrics"
            await client.put(url, json={"views": 10})
            second = await client.put(url, json={"views": 900})
            assert (
                second.json()["publications"][0]["latest_metrics"]["views"] == 900
            )
        async with get_bypass_session_factory()() as db:
            from sqlalchemy import func, select

            from app.models import ContentMetric

            total = await db.scalar(select(func.count()).select_from(ContentMetric))
            assert total == 1, "one reading per day, corrected in place"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_queued_post_cannot_have_views(database_url: str) -> None:
    """It has been seen by nobody. A number here would be about a video that
    does not exist yet."""
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=CLEAN)
            piece_id = created.json()["id"]
            await _publish(piece_id, "youtube", sent=False)
            refused = await client.put(
                f"/api/v1/content/{piece_id}/publications/youtube/metrics",
                json={"views": 5},
            )
            assert refused.status_code == 409
            assert refused.json()["detail"] == "not_published_yet"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_platform_that_was_never_posted_to_is_404(database_url: str) -> None:
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=CLEAN)
            piece_id = created.json()["id"]
            await _publish(piece_id, "tiktok", sent=True)
            missing = await client.put(
                f"/api/v1/content/{piece_id}/publications/youtube/metrics",
                json={"views": 5},
            )
            assert missing.status_code == 404
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_negative_view_count_is_refused(database_url: str) -> None:
    try:
        async with _client() as client:
            created = await client.post("/api/v1/content", json=CLEAN)
            piece_id = created.json()["id"]
            await _publish(piece_id, "tiktok", sent=True)
            bad = await client.put(
                f"/api/v1/content/{piece_id}/publications/tiktok/metrics",
                json={"views": -1},
            )
            assert bad.status_code == 422
    finally:
        await _cleanup()
