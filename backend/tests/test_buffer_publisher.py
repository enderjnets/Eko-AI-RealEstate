"""Publishing: the claim, the refusals, and the things that must never happen.

The invariants these hold, in the order they matter:

1. Nothing goes out that a person did not approve — `publish_piece` asks the
   gate first, and a piece edited back into NEEDS_APPROVAL is refused.
2. A crash cannot become a second public post: the publication row is claimed
   and committed before the outbound call.
3. A quota pause is not a content failure. Nothing is marked FAILED, and the
   platforms that were not reached are claimed on the next tick.
4. A 200 carrying a `MutationError` is a failure, because GraphQL puts
   application errors inside successful responses.
5. Channel ids that are not this organization's stop everything — the exact
   defect that published a video on the wrong brand's channel next door.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    AgentSettings,
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentPublication,
    ContentStatus,
    PublicationPlatform,
    PublicationStatus,
)
from app.services import buffer_publisher
from app.services.buffer_publisher import (
    BufferRefused,
    QuotaReached,
    build_post_input,
    parse_create_post,
    publish_approved,
    publish_piece,
    verify_organization,
)
from app.services.tenant_context import org_scope

ORG = 1

YT = "6a8f371eccaf649a67208cd0"
TT = "6a8f37efccaf649a6720a2a9"
IG = "6a8f36edccaf649a6720882a"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — publisher tests need live Postgres")
    return url


@pytest.fixture(autouse=True)
def _publishing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "CONTENT_PUBLISH_ENABLED", True, raising=False)
    monkeypatch.setattr(s, "CONTENT_PUBLISH_MAX_PER_DAY", 4, raising=False)
    monkeypatch.setattr(s, "BUFFER_SIMULATED", False, raising=False)
    monkeypatch.setattr(s, "BUFFER_ACCESS_TOKEN", "tok", raising=False)
    monkeypatch.setattr(s, "BUFFER_ORG_ID", "org-1", raising=False)
    monkeypatch.setattr(s, "BUFFER_CHANNEL_YOUTUBE", YT, raising=False)
    monkeypatch.setattr(s, "BUFFER_CHANNEL_TIKTOK", TT, raising=False)
    monkeypatch.setattr(s, "BUFFER_CHANNEL_INSTAGRAM", IG, raising=False)
    monkeypatch.setattr(
        s, "CONTENT_PUBLIC_BASE_URL", "https://panel.example.com", raising=False
    )
    # This installation really does carry a second organization — the "Demo"
    # row migration 015 creates, which is `trial` and therefore part of every
    # sweep. Naming whose channels these are is not test scaffolding: it is
    # what production has to set too, and the guard refuses without it.
    monkeypatch.setattr(s, "CONTENT_PUBLISH_ORG_ID", ORG, raising=False)


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_publications"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


async def _brokerage(value: str = "Engel & Völkers Aspen") -> None:
    async with get_bypass_session_factory()() as db:
        row = (await db.execute(text("SELECT id FROM agent_settings WHERE org_id=1"))).first()
        if row is None:
            db.add(AgentSettings(org_id=ORG, brokerage_line=value))
        else:
            await db.execute(
                text("UPDATE agent_settings SET brokerage_line=:v WHERE org_id=1"),
                {"v": value},
            )
        await db.commit()


async def _approved_piece(kind: ContentKind = ContentKind.GENERATED) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=kind,
            language=ContentLanguage.EN,
            status=ContentStatus.APPROVED,
            hook="What a Denver home is worth today.",
            script="Three numbers decide the price.",
            caption="Three numbers decide the price.",
            media_path="a" * 32 + ".mp4",
            approved_by="office",
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _rows(piece_id: int) -> dict[str, ContentPublication]:
    async with get_bypass_session_factory()() as db:
        found = (
            await db.execute(
                text(
                    "SELECT platform, status, external_id, last_error "
                    "FROM content_publications WHERE piece_id=:p"
                ),
                {"p": piece_id},
            )
        ).all()
    return {r[0]: r for r in found}


async def _status(piece_id: int) -> str:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text("SELECT status FROM content_pieces WHERE id=:p"), {"p": piece_id}
            )
        ).scalar_one()


class _Recorder:
    """Stands in for the wire. Records every input, answers per platform."""

    def __init__(self, answers: dict[str, Any] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.answers = answers or {}

    async def __call__(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if "channels(" in query:
            return {
                "data": {
                    "channels": [
                        {"id": YT, "service": "youtube", "isDisconnected": False},
                        {"id": TT, "service": "tiktok", "isDisconnected": False},
                        {"id": IG, "service": "instagram", "isDisconnected": False},
                    ]
                }
            }
        payload = variables["input"]
        self.sent.append(payload)
        answer = self.answers.get(payload["channelId"])
        if isinstance(answer, Exception):
            raise answer
        return answer or {
            "data": {
                "createPost": {
                    "__typename": "PostActionSuccess",
                    "post": {"id": f"post-{len(self.sent)}"},
                }
            }
        }


# ── The pure parts, no database ──────────────────────────────────────────


def test_a_mutation_error_inside_a_200_is_a_failure() -> None:
    """GraphQL answers 200 and puts the refusal in the body."""
    with pytest.raises(BufferRefused, match="LimitReached"):
        parse_create_post(
            {
                "data": {
                    "createPost": {
                        "__typename": "LimitReachedError",
                        "message": "daily limit",
                    }
                }
            }
        )


def test_success_without_a_post_id_is_not_success() -> None:
    """The id is what finds the post again; without it nothing can tell a
    retry from a duplicate."""
    with pytest.raises(BufferRefused, match="without a post id"):
        parse_create_post(
            {"data": {"createPost": {"__typename": "PostActionSuccess", "post": {}}}}
        )


def test_the_post_never_carries_a_thumbnail_url() -> None:
    """Buffer discards the entire post if the video asset has one."""
    built = build_post_input(TT, PublicationPlatform.TIKTOK, "hi", "https://x/v.mp4", True)
    assert "thumbnailUrl" not in built["assets"][0]["video"]
    assert built["assets"][0]["video"] == {"url": "https://x/v.mp4"}


def test_ai_disclosure_goes_only_to_tiktok_and_tells_the_truth() -> None:
    tiktok = build_post_input(TT, PublicationPlatform.TIKTOK, "t", "u", False)
    youtube = build_post_input(YT, PublicationPlatform.YOUTUBE, "t", "u", True)
    # A clip Natalia filmed is not AI-generated, and declaring it as one would
    # be a false statement on the platform's own field.
    assert tiktok["metadata"]["tiktok"]["isAiGenerated"] is False
    assert "metadata" not in youtube


def test_nothing_is_scheduled_for_later() -> None:
    """`shareNow`: a queued post is fetched later, and later is exactly when a
    piece may have been edited out of APPROVED."""
    built = build_post_input(YT, PublicationPlatform.YOUTUBE, "t", "u", True)
    assert built["mode"] == "shareNow"
    assert "dueAt" not in built


# ── The database-backed machine ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_approved_piece_reaches_every_platform_once(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _brokerage()
    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    try:
        piece_id = await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await publish_piece(db, piece_id)

        rows = await _rows(piece_id)
        assert set(rows) == {"youtube", "tiktok", "instagram"}
        assert all(r[1] == "published" for r in rows.values())
        assert len({r[2] for r in rows.values()}) == 3
        assert await _status(piece_id) == "published"
        assert len(recorder.sent) == 3
        # Every post points at the stable public address, not a signed link.
        for sent in recorder.sent:
            assert sent["assets"][0]["video"]["url"] == (
                f"https://panel.example.com/api/v1/public/content/{piece_id}/media"
            )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_piece_nobody_approved_never_reaches_the_wire(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the gate. A piece edited after approval is back in
    NEEDS_APPROVAL, and this is the moment that catches it."""
    from app.services.content_studio import NotPublishable

    await _brokerage()
    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    try:
        piece_id = await _approved_piece()
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE content_pieces SET status='needs_approval' WHERE id=:p"),
                {"p": piece_id},
            )
            await db.commit()

        with org_scope(ORG):
            async with get_session_factory()() as db:
                with pytest.raises(NotPublishable):
                    await publish_piece(db, piece_id)

        assert recorder.sent == []
        assert await _rows(piece_id) == {}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_without_a_brokerage_line_nothing_publishes(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Colorado requires the advertising to identify the brokerage, so an
    agency that cleared the field stops publishing rather than publishing
    unidentified."""
    from app.services.content_studio import NotPublishable

    await _brokerage("")
    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    try:
        piece_id = await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with pytest.raises(NotPublishable, match="brokerage"):
                    await publish_piece(db, piece_id)
        assert recorder.sent == []
    finally:
        await _brokerage()
        await _cleanup()


@pytest.mark.asyncio
async def test_a_quota_pause_is_resumed_on_the_next_tick(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 429 is Buffer's calendar, not a verdict on the video.

    The second tick is the whole test. An earlier version stopped after
    asserting the intermediate state — tiktok PENDING, piece PUBLISHING — and
    passed just as happily when the released platform was never picked up
    again: the `already` set was built from every row regardless of status, so
    a PENDING platform was skipped forever and the piece stayed in PUBLISHING
    with no reaper anywhere. A video half-published, permanently. An audit
    found it; this test is what would have.
    """
    await _brokerage()
    paused = _Recorder({TT: QuotaReached("429")})
    monkeypatch.setattr(buffer_publisher, "_graphql", paused)
    try:
        piece_id = await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with pytest.raises(QuotaReached):
                    await publish_piece(db, piece_id)

        rows = await _rows(piece_id)
        assert rows["youtube"][1] == "published"
        # Released, not failed: the next tick has to be able to pick it up.
        assert rows["tiktok"][1] == "pending"
        assert "instagram" not in rows
        assert await _status(piece_id) == "publishing"

        # Buffer recovers. Everything still owed goes out and the piece closes.
        healthy = _Recorder()
        monkeypatch.setattr(buffer_publisher, "_graphql", healthy)
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await publish_piece(db, piece_id)

        rows = await _rows(piece_id)
        assert {p: r[1] for p, r in rows.items()} == {
            "youtube": "published",
            "tiktok": "published",
            "instagram": "published",
        }
        assert await _status(piece_id) == "published"
        # And the platform that already went out was not posted a second time.
        assert {s["channelId"] for s in healthy.sent} == {TT, IG}
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_re_approved_piece_can_be_published_again(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A person's second approval has to mean something.

    After a total failure the declared way back is FAILED -> DRAFT ->
    NEEDS_APPROVAL -> APPROVED. If the previous attempt's rows still counted as
    "already attempted", every platform would be skipped and the piece would
    flip straight back to FAILED without a single call — a video somebody
    deliberately re-approved, permanently unpublishable.
    """
    await _brokerage()
    refusal = {
        "data": {"createPost": {"__typename": "UnexpectedError", "message": "nope"}}
    }
    monkeypatch.setattr(
        buffer_publisher, "_graphql", _Recorder({YT: refusal, TT: refusal, IG: refusal})
    )
    try:
        piece_id = await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await publish_piece(db, piece_id)
        assert await _status(piece_id) == "failed"

        # The operator walks it back through the queue.
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE content_pieces SET status='approved' WHERE id=:p"),
                {"p": piece_id},
            )
            await db.commit()

        healthy = _Recorder()
        monkeypatch.setattr(buffer_publisher, "_graphql", healthy)
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await publish_piece(db, piece_id)

        assert len(healthy.sent) == 3
        assert await _status(piece_id) == "published"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_second_agency_cannot_publish_to_the_first_ones_channels(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUFFER_CHANNEL_* is one set of ids for the whole installation.

    The publish sweep runs for EVERY organization, so without this guard the
    day a second agency uses the content rail their approved video is posted to
    the first agency's YouTube, TikTok and Instagram — which cannot be taken
    back. Refusing is the only safe answer until somebody says whose channels
    these are.
    """
    await _brokerage()
    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)

    async def _two_agencies(acting):
        return True

    monkeypatch.setattr(buffer_publisher, "_other_orgs_exist", _two_agencies)
    # Nobody has said whose channels these are — which is the state a fresh
    # install is in, and the state this guard exists for.
    monkeypatch.setattr(get_settings(), "CONTENT_PUBLISH_ORG_ID", 0, raising=False)
    try:
        await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await publish_approved(db) == 0
        assert recorder.sent == []

        # Named explicitly, it publishes again — for that org and no other.
        monkeypatch.setattr(
            get_settings(), "CONTENT_PUBLISH_ORG_ID", ORG, raising=False
        )
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await publish_approved(db) == 1
        with org_scope(ORG + 1):
            async with get_session_factory()() as db:
                assert await publish_approved(db) == 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_one_platform_failing_does_not_stop_the_others(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _brokerage()
    recorder = _Recorder(
        {
            IG: {
                "data": {
                    "createPost": {
                        "__typename": "InvalidInputError",
                        "message": "no facebook page linked",
                    }
                }
            }
        }
    )
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    try:
        piece_id = await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await publish_piece(db, piece_id)

        rows = await _rows(piece_id)
        assert rows["instagram"][1] == "failed"
        assert "no facebook page linked" in rows["instagram"][3]
        assert rows["youtube"][1] == "published"
        # One platform out is still a published piece: two videos are live.
        assert await _status(piece_id) == "published"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_every_platform_failing_fails_the_piece(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _brokerage()
    refusal = {
        "data": {"createPost": {"__typename": "UnexpectedError", "message": "nope"}}
    }
    recorder = _Recorder({YT: refusal, TT: refusal, IG: refusal})
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    try:
        piece_id = await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await publish_piece(db, piece_id)
        assert await _status(piece_id) == "failed"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_row_stuck_in_publishing_is_never_retried(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The crash case. A claim with no outcome means a human has to check the
    platform — retrying blind is how the same video is posted twice."""
    await _brokerage()
    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    try:
        piece_id = await _approved_piece()
        async with get_bypass_session_factory()() as db:
            db.add(
                ContentPublication(
                    org_id=ORG,
                    piece_id=piece_id,
                    platform=PublicationPlatform.YOUTUBE,
                    status=PublicationStatus.PUBLISHING,
                )
            )
            await db.execute(
                text("UPDATE content_pieces SET status='publishing' WHERE id=:p"),
                {"p": piece_id},
            )
            await db.commit()

        with org_scope(ORG):
            async with get_session_factory()() as db:
                await publish_piece(db, piece_id)

        sent_channels = {s["channelId"] for s in recorder.sent}
        assert YT not in sent_channels
        assert sent_channels == {TT, IG}
        rows = await _rows(piece_id)
        assert rows["youtube"][1] == "publishing"
        # And the piece cannot close while a person still owes an answer.
        assert await _status(piece_id) == "publishing"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_channels_that_are_not_this_organizations_stop_everything(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard against the failure next door: a plausible-looking id that
    belongs to somebody else's Buffer organization posts a real video on a
    real stranger's account."""

    async def _other_org(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        assert "channels(" in query, "nothing may be posted before the check"
        return {
            "data": {
                "channels": [
                    {"id": "someone-else", "service": "youtube", "isDisconnected": False}
                ]
            }
        }

    monkeypatch.setattr(buffer_publisher, "_graphql", _other_org)
    with pytest.raises(BufferRefused, match="not connected channels"):
        await verify_organization()


@pytest.mark.asyncio
async def test_a_disconnected_channel_is_not_a_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _disconnected(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return {
            "data": {
                "channels": [
                    {"id": YT, "service": "youtube", "isDisconnected": True},
                    {"id": TT, "service": "tiktok", "isDisconnected": False},
                    {"id": IG, "service": "instagram", "isDisconnected": False},
                ]
            }
        }

    monkeypatch.setattr(buffer_publisher, "_graphql", _disconnected)
    with pytest.raises(BufferRefused, match="youtube"):
        await verify_organization()


@pytest.mark.asyncio
async def test_the_tick_checks_the_organization_before_any_post(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _brokerage()
    calls: list[str] = []

    async def _record(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        calls.append("channels" if "channels(" in query else "post")
        if "channels(" in query:
            return {
                "data": {
                    "channels": [
                        {"id": YT, "service": "youtube", "isDisconnected": False},
                        {"id": TT, "service": "tiktok", "isDisconnected": False},
                        {"id": IG, "service": "instagram", "isDisconnected": False},
                    ]
                }
            }
        return {
            "data": {
                "createPost": {
                    "__typename": "PostActionSuccess",
                    "post": {"id": "p"},
                }
            }
        }

    monkeypatch.setattr(buffer_publisher, "_graphql", _record)
    try:
        await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                await publish_approved(db)
        assert calls[0] == "channels"
        # Once per tick, not once per post: it cannot change between two posts
        # of the same batch and it spends the same quota the posts need.
        assert calls.count("channels") == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_daily_cap_counts_pieces_not_posts(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One piece is three platforms; counting posts would let a single video
    spend three days of budget."""
    await _brokerage()
    monkeypatch.setattr(get_settings(), "CONTENT_PUBLISH_MAX_PER_DAY", 1, raising=False)
    monkeypatch.setattr(buffer_publisher, "_graphql", _Recorder())
    try:
        first = await _approved_piece()
        second = await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await publish_approved(db) == 1
                # Budget spent on ONE piece, even though it made three posts.
                assert await publish_approved(db) == 0
        assert await _status(first) == "published"
        assert await _status(second) == "approved"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_publishing_disabled_sends_nothing(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _brokerage()
    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    monkeypatch.setattr(get_settings(), "CONTENT_PUBLISH_ENABLED", False, raising=False)
    try:
        await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await publish_approved(db) == 0
        assert recorder.sent == []
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_no_public_base_url_is_undeliverable_rather_than_a_broken_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without it every post would carry a URL Buffer cannot fetch, and the
    failure would arrive hours later looking like a broken video."""
    monkeypatch.setattr(get_settings(), "CONTENT_PUBLIC_BASE_URL", "", raising=False)
    assert "CONTENT_PUBLIC_BASE_URL" in (buffer_publisher.undeliverable_reason() or "")


@pytest.mark.asyncio
async def test_simulation_needs_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dev install with a channel configured can exercise the whole machine
    without credentials — and without posting anything."""
    s = get_settings()
    monkeypatch.setattr(s, "BUFFER_SIMULATED", True, raising=False)
    monkeypatch.setattr(s, "BUFFER_ACCESS_TOKEN", "", raising=False)
    monkeypatch.setattr(s, "BUFFER_ORG_ID", "", raising=False)
    assert buffer_publisher.undeliverable_reason() is None
