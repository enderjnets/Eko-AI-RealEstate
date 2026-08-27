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
    payload = b"\x00\x00\x00\x18ftypmp42" + b"x" * (2 * 1024 * 1024)
    try:
        async with _client() as client:
            too_big = await client.post(
                "/api/v1/content/upload",
                params={"filename": "4k-from-the-phone.mp4", "language": "en"},
                content=payload,
            )
            assert too_big.status_code == 413, too_big.text
            # The message has to carry the number, or the person cannot act on
            # it: "too large" without a limit is a dead end on a phone.
            assert "1" in too_big.json()["detail"]

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
        "upload_max_mb",
        "counts",
    }
    # The value, not just the key. The browser refuses a file by comparing
    # `file.size` against this number, so a status endpoint that reports a
    # limit the server does not enforce would reject good clips or wave
    # through ones the upload will kill halfway.
    from app.config import get_settings

    assert body["upload_max_mb"] == get_settings().CONTENT_UPLOAD_MAX_MB
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
    from "no publisher exists". Today the second is the true answer.

    Asserted as a literal `False`, not against `PUBLISHING_AVAILABLE`: the
    first version compared the endpoint's output to the very constant the
    endpoint reads, so flipping that constant to True left the test green. It
    proved the two agreed, which they cannot help doing. This fails on the day
    someone flips it — which is the day the console's wording, the release
    notes and this test all need revisiting together, and the failure is how
    that gets noticed.
    """
    async with _client() as client:
        body = (await client.get("/api/v1/content/status")).json()
    assert body["publishing_available"] is False


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

