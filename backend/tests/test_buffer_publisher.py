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
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
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
from app.services import buffer_publisher, content_studio
from app.services.buffer_publisher import (
    BufferRefused,
    QuotaReached,
    build_post_input,
    parse_create_post,
    publish_approved,
    publish_piece,
    verify_organization,
    with_platform_utm,
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
    monkeypatch.setattr(s, "CONTENT_ORG_ID", ORG, raising=False)
    # These tests predate the queue and cover the immediate path: the claim,
    # the refusals, the quota pause, the daily cap. They are pinned to it
    # explicitly rather than left to inherit whatever the default is, so that
    # "publishes now" and "goes in the queue" are each asserted somewhere on
    # purpose. The queue has its own tests below.
    monkeypatch.setattr(s, "CONTENT_SCHEDULE_ENABLED", False, raising=False)


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
        self.queries: list[str] = []
        self.reads: dict[str, Any] = {}
        #: Extra top-level keys to put beside "data" — `errors`, mostly.
        self.envelope: dict[str, Any] = {}
        #: Buffer nulls `data` for the whole batch when any field errors —
        #: measured against the live API, not assumed.
        self.null_data = False
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
        if "input" not in variables:
            # The reconciler's read: an aliased `post(input:{id})` batch, sent
            # as a literal query with no variables. Answers are keyed by the
            # post id parsed out of the query, never by alias position — a test
            # that assumed `p0` was always the first row would hide the exact
            # defect a missing ORDER BY causes.
            self.queries.append(query)
            # Ids arrive as GraphQL variables, one per alias — the query itself
            # carries only `$p0`. Answers are keyed by the post id, never by
            # alias position, so a test cannot accidentally depend on the order
            # rows came back from the database.
            answered = {
                alias: self.reads.get(post_id) for alias, post_id in variables.items()
            }
            return {
                "data": None if self.null_data else answered,
                **self.envelope,
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


def test_ai_is_declared_on_every_platform_and_tells_the_truth() -> None:
    """All three take the field; a clip Natalia filmed is not AI-generated, and
    declaring it as one would be a false statement on the agency's channel."""
    filmed = build_post_input(TT, PublicationPlatform.TIKTOK, "t", "u", False)
    assert filmed["metadata"]["tiktok"]["isAiGenerated"] is False
    for channel, platform, key in (
        (TT, PublicationPlatform.TIKTOK, "tiktok"),
        (YT, PublicationPlatform.YOUTUBE, "youtube"),
        (IG, PublicationPlatform.INSTAGRAM, "instagram"),
    ):
        built = build_post_input(channel, platform, "t", "u", True)
        assert built["metadata"][key]["isAiGenerated"] is True


def test_every_platform_gets_the_metadata_it_refuses_a_post_without() -> None:
    """Measured, not guessed. The first real publish attempt was rejected three
    times over: YouTube "require a title... require a category", Instagram
    "require a type (post, story, or reel)". The names below were then read out
    of Buffer's schema by introspection.
    """
    youtube = build_post_input(
        YT, PublicationPlatform.YOUTUBE, "body", "u", True, title="A headline"
    )
    assert youtube["metadata"]["youtube"]["title"] == "A headline"
    assert youtube["metadata"]["youtube"]["categoryId"]

    instagram = build_post_input(IG, PublicationPlatform.INSTAGRAM, "b", "u", True)
    # A portrait video posted to the feed would be shown in a square frame.
    assert instagram["metadata"]["instagram"]["type"] == "reel"
    assert instagram["metadata"]["instagram"]["shouldShareToFeed"] is True


def test_a_title_too_long_is_cut_here_rather_than_by_the_platform() -> None:
    """YouTube truncates past 100 characters, and it does it mid-word."""
    built = build_post_input(
        YT, PublicationPlatform.YOUTUBE, "b", "u", True, title="x" * 180
    )
    assert len(built["metadata"]["youtube"]["title"]) == 100


def test_with_no_hook_the_title_falls_back_to_the_first_line() -> None:
    """A platform that requires a title must never receive an empty one."""
    built = build_post_input(
        YT, PublicationPlatform.YOUTUBE, "First line\nsecond", "u", True, title=""
    )
    assert built["metadata"]["youtube"]["title"] == "First line"


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

    monkeypatch.setattr(content_studio, "other_orgs_exist", _two_agencies)
    # Nobody has said whose channels these are — which is the state a fresh
    # install is in, and the state this guard exists for.
    monkeypatch.setattr(get_settings(), "CONTENT_ORG_ID", 0, raising=False)
    try:
        await _approved_piece()
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await publish_approved(db) == 0
        assert recorder.sent == []

        # Named explicitly, it publishes again — for that org and no other.
        monkeypatch.setattr(get_settings(), "CONTENT_ORG_ID", ORG, raising=False)
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


def test_the_post_does_not_wait_in_buffers_own_approval_queue() -> None:
    """`needsApproval` is non-null in Buffer's schema and we were not sending
    it. If its default were ever `true`, the post would sit in Buffer waiting
    for someone there while `createPost` still returned an id — and this system
    would record PUBLISHED for something nobody published. The approval that
    matters already happened here."""
    built = build_post_input(TT, PublicationPlatform.TIKTOK, "t", "u", True)
    assert built["needsApproval"] is False


# ── The queue: one slot a day per channel ────────────────────────────────
#
# The owner's rule, in his words: "se publican 1 por bloque de mejor horario,
# nunca dos a la vez". Everything below holds that to account, and each test
# names the mutation that reddens it.

DENVER = "America/Denver"


@pytest.fixture
def queue_on(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "CONTENT_SCHEDULE_ENABLED", True, raising=False)
    monkeypatch.setattr(s, "CONTENT_SLOT_YOUTUBE", "20:30", raising=False)
    monkeypatch.setattr(s, "CONTENT_SLOT_INSTAGRAM", "18:30", raising=False)
    monkeypatch.setattr(s, "CONTENT_SLOT_TIKTOK", "08:30", raising=False)
    monkeypatch.setattr(s, "CONTENT_SCHEDULE_LEAD_MINUTES", 20, raising=False)


async def _set_timezone(name: str = DENVER) -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE agent_settings SET timezone=:t WHERE org_id=1"), {"t": name}
        )
        await db.commit()


async def _sched(piece_id: int) -> dict[str, tuple[Any, ...]]:
    """platform -> (status, scheduled_at, external_url, last_error)."""
    async with get_bypass_session_factory()() as db:
        found = (
            await db.execute(
                text(
                    "SELECT platform, status, scheduled_at, external_url, last_error "
                    "FROM content_publications WHERE piece_id=:p"
                ),
                {"p": piece_id},
            )
        ).all()
    return {r[0]: tuple(r[1:]) for r in found}


def _local_day(moment: datetime) -> str:
    return moment.astimezone(ZoneInfo(DENVER)).date().isoformat()


async def test_one_slot_a_day_per_channel(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two approved pieces never share a channel's day. THE owner's rule.

    Mutation: drop the "while the day is taken" loop in `next_free_slot` and
    both pieces land on the same evening.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(buffer_publisher, "_graphql", _Recorder())
    first = await _approved_piece()
    second = await _approved_piece()
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, first)
            await publish_piece(db, second)

    a, b = await _sched(first), await _sched(second)
    assert set(a) == {"youtube", "tiktok", "instagram"}, a
    for platform in a:
        assert a[platform][0] == "scheduled", a[platform]
        assert b[platform][0] == "scheduled", b[platform]
        assert _local_day(a[platform][1]) != _local_day(b[platform][1]), (
            f"{platform}: both pieces landed on the same local day — "
            f"{a[platform][1]} and {b[platform][1]}"
        )


async def test_a_post_already_out_today_spends_todays_slot(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `published_at` today spends the day, not only a `scheduled_at`.

    This is the state production was actually left in: on 3-sep all three
    channels published with shareNow, so the first piece to enter the queue has
    to go to TOMORROW. Looking only at `scheduled_at` would find the day empty
    and book that same evening — two posts on one channel in one day, the one
    thing the rule forbids.

    Mutation: drop the `published_at` half of `_day_is_taken` → red.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(buffer_publisher, "_graphql", _Recorder())
    zone = ZoneInfo(DENVER)
    today = datetime.now(UTC).astimezone(zone).date()

    old_piece = await _approved_piece()
    async with get_bypass_session_factory()() as db:
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=old_piece,
                platform=PublicationPlatform.YOUTUBE,
                status=PublicationStatus.PUBLISHED,
                external_id="already-out",
                # Noon local: unambiguously inside the local day and far from
                # any UTC boundary.
                published_at=datetime.combine(
                    today, time(12, 0), tzinfo=zone
                ).astimezone(UTC),
            )
        )
        await db.commit()

    fresh = await _approved_piece()
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, fresh)

    rows = await _sched(fresh)
    assert rows["youtube"][0] == "scheduled", rows
    assert _local_day(rows["youtube"][1]) != today.isoformat(), (
        f"YouTube already published today; the queue booked it again on "
        f"{rows['youtube'][1]}"
    )


async def test_the_lead_time_pushes_a_slot_that_is_too_close(
    database_url: str, queue_on: None
) -> None:
    """A slot inside the lead window is missed, not raced.

    Buffer fetches the video when the post goes out; a fetch that starts after
    the hour has passed is a post that never happens.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    zone = ZoneInfo(DENVER)
    day = datetime(2026, 9, 10).date()

    with org_scope(ORG):
        async with get_session_factory()() as db:
            # 20:20 local against a 20:30 slot with 20 minutes of lead: the
            # edge, and the edge belongs to tomorrow.
            close = datetime.combine(day, time(20, 20), tzinfo=zone).astimezone(UTC)
            got = await buffer_publisher.next_free_slot(
                db, PublicationPlatform.YOUTUBE, zone, close
            )
            assert _local_day(got) == (day + timedelta(days=1)).isoformat(), got

            # 19:00 local is ninety minutes of warning: today.
            early = datetime.combine(day, time(19, 0), tzinfo=zone).astimezone(UTC)
            got = await buffer_publisher.next_free_slot(
                db, PublicationPlatform.YOUTUBE, zone, early
            )
            assert _local_day(got) == day.isoformat(), got
            assert got.astimezone(zone).time() == time(20, 30)


async def test_a_denver_evening_is_the_next_utc_day(
    database_url: str, queue_on: None
) -> None:
    """The case a UTC-day comparison gets wrong, and it is not exotic.

    20:30 in Denver is 02:30 UTC the following day. A `_day_is_taken` written
    against UTC dates would file a Thursday evening post under Friday and
    happily book Thursday evening a second time.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    zone = ZoneInfo(DENVER)
    day = datetime(2026, 9, 10).date()

    # The row that makes this test able to fail. Written against UTC dates,
    # `_day_is_taken` files this 20:30-local post under the NEXT UTC day, finds
    # `day` empty, and books that same evening a second time. Without a row in
    # the table the function under suspicion is never consulted at all and the
    # test passes on arithmetic that has nothing to do with the bug — measured:
    # it survived the mutation its own docstring describes.
    taken = await _approved_piece()
    async with get_bypass_session_factory()() as db:
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=taken,
                platform=PublicationPlatform.YOUTUBE,
                status=PublicationStatus.SCHEDULED,
                external_id="already-booked",
                scheduled_at=datetime.combine(
                    day, time(20, 30), tzinfo=zone
                ).astimezone(UTC),
            )
        )
        await db.commit()

    with org_scope(ORG):
        async with get_session_factory()() as db:
            noon = datetime.combine(day, time(12, 0), tzinfo=zone).astimezone(UTC)
            slot = await buffer_publisher.next_free_slot(
                db, PublicationPlatform.YOUTUBE, zone, noon
            )

    # That evening is spent, so the answer must be the NEXT local day — and a
    # UTC-day reading of the booked row would have said this evening was free.
    assert _local_day(slot) == (day + timedelta(days=1)).isoformat(), slot
    assert slot.date().isoformat() == (day + timedelta(days=2)).isoformat(), slot
    assert slot.astimezone(zone).time() == time(20, 30)


async def test_pieces_are_queued_in_the_order_they_were_approved(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"In order" means the order a person approved in.

    Ids are the order the machine happened to create rows in, and with one slot
    a day the difference between the two is days of waiting.

    Mutation: put `order_by(ContentPiece.id)` back → red.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(buffer_publisher, "_graphql", _Recorder())
    low_id = await _approved_piece()
    high_id = await _approved_piece()
    # The HIGHER id was approved FIRST, so it must get the earlier slot.
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE content_pieces SET approved_at=:t WHERE id=:i"),
            {"t": datetime(2026, 9, 1, 10, 0, tzinfo=UTC), "i": high_id},
        )
        await db.execute(
            text("UPDATE content_pieces SET approved_at=:t WHERE id=:i"),
            {"t": datetime(2026, 9, 2, 10, 0, tzinfo=UTC), "i": low_id},
        )
        await db.commit()

    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_approved(db)

    first, second = await _sched(high_id), await _sched(low_id)
    assert first["youtube"][1] < second["youtube"][1], (
        "the piece approved first did not get the earlier slot: "
        f"{first['youtube'][1]} vs {second['youtube'][1]}"
    )


async def test_the_post_carries_a_due_date_and_the_way_back_does_not(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What actually reaches Buffer, in both modes.

    The second half is the way back: `CONTENT_SCHEDULE_ENABLED=false` restores
    `shareNow` with no `dueAt`, so the queue can be turned off in the `.env`
    without a redeploy if it ever misbehaves.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    piece = await _approved_piece()
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, piece)

    rows = await _sched(piece)
    assert len(recorder.sent) == 3
    for post in recorder.sent:
        assert post["mode"] == "customScheduled", post["mode"]
        assert "dueAt" in post
    by_channel = {p["channelId"]: p["dueAt"] for p in recorder.sent}
    assert by_channel[YT] == rows["youtube"][1].isoformat()

    monkeypatch.setattr(
        get_settings(), "CONTENT_SCHEDULE_ENABLED", False, raising=False
    )
    plain_recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", plain_recorder)
    plain = await _approved_piece()
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, plain)

    assert len(plain_recorder.sent) == 3
    for post in plain_recorder.sent:
        assert post["mode"] == "shareNow", post["mode"]
        assert "dueAt" not in post
    assert all(r[0] == "published" for r in (await _sched(plain)).values())


async def test_a_scheduled_piece_stays_in_publishing(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SCHEDULED is not terminal, and that is what protects the post.

    While the piece is PUBLISHING its media URL keeps serving and its text
    cannot be edited — `_ALLOWED` has no edge from PUBLISHING back to
    NEEDS_APPROVAL. That, and not the posting mode, is what keeps the video
    Buffer will fetch and the video a person approved the same video.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(buffer_publisher, "_graphql", _Recorder())
    piece = await _approved_piece()
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, piece)
    assert await _status(piece) == "publishing"


async def test_a_scheduled_row_is_never_posted_twice(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect this file exists to prevent, in its newest shape.

    A scheduled piece stays PUBLISHING for days, so `publish_approved` picks it
    up on every tick in between — one every fifteen minutes. With SCHEDULED
    left out of the "already handled" list in `publish_piece`, each of those
    ticks posts the same video again. It was written that way first; this is
    what caught it.

    Mutation: remove `PublicationStatus.SCHEDULED` from that tuple → red.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    piece = await _approved_piece()
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, piece)
            assert len(recorder.sent) == 3, "one post per platform on the first pass"
            await publish_piece(db, piece)
            await publish_approved(db)

    assert len(recorder.sent) == 3, (
        f"the scheduled piece was posted again: {len(recorder.sent)} posts"
    )
    assert all(r[0] == "scheduled" for r in (await _sched(piece)).values())


async def test_an_unusable_timezone_schedules_nothing(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A date in the wrong zone is worse than no date, because it looks right."""
    await _cleanup()
    await _brokerage()
    await _set_timezone("Mars/Olympus_Mons")
    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    piece = await _approved_piece()
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, piece)

    assert recorder.sent == []
    assert await _sched(piece) == {}
    assert await _status(piece) == "approved", (
        "the piece must stay approved so it goes out once the zone is fixed"
    )


# ── The reconciler: asking Buffer how it went ────────────────────────────


async def _scheduled_row(
    piece_id: int, platform: PublicationPlatform, external_id: str, *, due_minutes: int
) -> None:
    async with get_bypass_session_factory()() as db:
        db.add(
            ContentPublication(
                org_id=ORG,
                piece_id=piece_id,
                platform=platform,
                status=PublicationStatus.SCHEDULED,
                external_id=external_id,
                scheduled_at=datetime.now(UTC) + timedelta(minutes=due_minutes),
            )
        )
        await db.commit()


async def test_the_reconciler_reads_buffers_own_labels(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sent` publishes, `error` fails, an intermediate state waits.

    The labels are Buffer's, read out of its schema by introspection rather
    than guessed: draft | error | needs_approval | scheduled | sending | sent.
    A post on its way out genuinely sits in `sending` for a while, so treating
    "not sent" as failure would retire posts that are about to go live.

    Mutation: write PUBLISHED without looking at `status` → red.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(get_settings(), "BUFFER_SIMULATED", False, raising=False)

    piece = await _approved_piece()
    await _scheduled_row(piece, PublicationPlatform.YOUTUBE, "yt-1", due_minutes=-5)
    await _scheduled_row(piece, PublicationPlatform.TIKTOK, "tt-1", due_minutes=-5)
    await _scheduled_row(piece, PublicationPlatform.INSTAGRAM, "ig-1", due_minutes=-5)

    recorder = _Recorder()
    recorder.reads = {
        "yt-1": {
            "status": "sent",
            "sentAt": "2026-09-04T02:30:00Z",
            "externalLink": "https://youtube.com/shorts/abc",
            "error": None,
        },
        "tt-1": {"status": "error", "sentAt": None, "externalLink": None,
                 "error": {"message": "the channel rejected the video"}},
        "ig-1": {"status": "sending", "sentAt": None, "externalLink": None,
                 "error": None},
    }
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            resolved = await buffer_publisher.reconcile_scheduled(db)

    assert resolved == 2
    rows = await _sched(piece)
    assert rows["youtube"][0] == "published"
    assert rows["youtube"][2] == "https://youtube.com/shorts/abc"
    assert rows["tiktok"][0] == "failed"
    assert "rejected the video" in rows["tiktok"][3]
    # Still on its way out. Left alone, and the piece cannot close over it.
    assert rows["instagram"][0] == "scheduled"
    assert await _status(piece) == "approved"
    # One request for the batch, not one per row.
    assert len(recorder.queries) == 1
    assert recorder.queries[0].count("post(input:") == 3


async def test_a_post_deleted_in_buffer_lets_the_piece_close(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting the post in Buffer's interface is today's only way to cancel.

    Recording that honestly is what lets the piece finish instead of waiting
    forever for an hour that will never come.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(get_settings(), "BUFFER_SIMULATED", False, raising=False)

    piece = await _approved_piece()
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE content_pieces SET status='publishing' WHERE id=:i"),
            {"i": piece},
        )
        await db.commit()
    for platform, ext in (
        (PublicationPlatform.YOUTUBE, "yt-1"),
        (PublicationPlatform.TIKTOK, "tt-1"),
        (PublicationPlatform.INSTAGRAM, "ig-1"),
    ):
        await _scheduled_row(piece, platform, ext, due_minutes=-5)

    # Buffer's real shape for a deleted post, measured against the live API:
    # an `errors` entry with `code: NOT_FOUND` naming the alias in its `path`,
    # and `data` nulled for the WHOLE batch. Not a clean null for that alias —
    # the branch this used to assert was unreachable in production.
    recorder = _Recorder()
    recorder.reads = {}
    recorder.envelope = {
        "errors": [
            {
                "message": "Post not found for id: tt-1",
                "path": ["p1"],
                "extensions": {"code": "NOT_FOUND"},
            }
        ]
    }
    recorder.null_data = True
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            # Only the one Buffer answered about. The other two were not
            # answered at all — `data` came back null — and silence is not a
            # verdict; they are asked again on the next tick.
            assert await buffer_publisher.reconcile_scheduled(db) == 1

    rows = await _sched(piece)
    assert rows["tiktok"][0] == "failed"
    assert "no longer exists" in rows["tiktok"][3]
    assert rows["youtube"][0] == "scheduled"
    assert rows["instagram"][0] == "scheduled"
    assert await _status(piece) == "publishing"

    # Next tick: the deleted one is out of the batch, so the clean rows finally
    # get their answer and the piece closes. This is the half that a blanket
    # "errors means give up" would have blocked for ever.
    second = _Recorder()
    second.reads = {
        "yt-1": {"status": "sent", "sentAt": "2026-09-04T02:30:00Z",
                 "externalLink": "https://youtube.com/shorts/abc", "error": None},
        "ig-1": {"status": "sent", "sentAt": "2026-09-04T14:30:00Z",
                 "externalLink": "https://instagram.com/reel/xyz", "error": None},
    }
    monkeypatch.setattr(buffer_publisher, "_graphql", second)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            assert await buffer_publisher.reconcile_scheduled(db) == 2
    assert await _status(piece) == "published"


async def test_a_question_we_could_not_ask_is_not_an_answer(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Buffer being unreachable must not retire posts that are probably live."""
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(get_settings(), "BUFFER_SIMULATED", False, raising=False)

    piece = await _approved_piece()
    await _scheduled_row(piece, PublicationPlatform.YOUTUBE, "yt-1", due_minutes=-5)

    async def _boom(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(buffer_publisher, "_graphql", _boom)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            assert await buffer_publisher.reconcile_scheduled(db) == 0

    assert (await _sched(piece))["youtube"][0] == "scheduled"


async def test_a_slot_that_has_not_arrived_is_not_asked_about(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Buffer is not asked about a post whose hour is still in the future."""
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(get_settings(), "BUFFER_SIMULATED", False, raising=False)

    piece = await _approved_piece()
    await _scheduled_row(piece, PublicationPlatform.YOUTUBE, "yt-1", due_minutes=600)

    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            assert await buffer_publisher.reconcile_scheduled(db) == 0
    assert recorder.queries == []


async def test_graphql_errors_never_retire_a_live_post(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 carrying `errors` is a failed read, not a verdict. BLOCKING.

    GraphQL answers 200 and puts application errors in the body — the same
    thing `parse_create_post` already knows about writes. A rate-limited lookup
    comes back as `data: {p0: {...}, p1: null}` plus an `errors` array, where
    that null means "this field errored", NOT "this post is gone".

    Read as a verdict it retired a LIVE post as "no longer exists", which is
    bad on its own. What makes it blocking is the second half, asserted below:
    the piece then closes FAILED, and FAILED is the one status a person can
    Retry — and a re-approved piece has its FAILED rows released and sent
    again. A transient error on a read therefore ended in a SECOND public post
    of a video that had already gone out.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(get_settings(), "BUFFER_SIMULATED", False, raising=False)

    piece = await _approved_piece()
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE content_pieces SET status='publishing' WHERE id=:i"),
            {"i": piece},
        )
        await db.commit()
    for platform, ext in (
        (PublicationPlatform.YOUTUBE, "yt-live"),
        (PublicationPlatform.TIKTOK, "tt-live"),
        (PublicationPlatform.INSTAGRAM, "ig-live"),
    ):
        await _scheduled_row(piece, platform, ext, due_minutes=-5)

    recorder = _Recorder()
    # Every post is alive; Buffer just could not answer for one of them.
    recorder.reads = {
        "yt-live": {"status": "sent", "sentAt": "2026-09-04T02:30:00Z",
                    "externalLink": "https://youtube.com/shorts/a", "error": None},
        "tt-live": None,
        "ig-live": {"status": "sent", "sentAt": "2026-09-04T14:30:00Z",
                    "externalLink": "https://instagram.com/reel/b", "error": None},
    }
    recorder.envelope = {
        "errors": [
            {
                "message": "Rate limit exceeded for post lookup",
                "path": ["p1"],
                "extensions": {"code": "RATE_LIMITED"},
            }
        ]
    }
    recorder.null_data = True
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)

    with org_scope(ORG):
        async with get_session_factory()() as db:
            assert await buffer_publisher.reconcile_scheduled(db) == 0

    rows = await _sched(piece)
    assert all(r[0] == "scheduled" for r in rows.values()), (
        f"a failed read was treated as an answer and wrote verdicts: {rows}"
    )
    # And therefore the piece cannot reach FAILED, which is the status that
    # would have offered a person the Retry that publishes it all over again.
    assert await _status(piece) == "publishing"
    assert recorder.sent == []


async def test_an_id_with_a_quote_cannot_break_or_extend_the_query(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ids travel as variables, so no value can reach the query text.

    Two failures at once before this. A quote in one id invalidated the whole
    batch string, Buffer answered 400, and every OTHER row in that batch went
    unreconciled on every tick from then on — a permanent silent stall behind
    one bad value. And an id shaped like `") { id } evil: organization(...` had
    a second field appended to our own query.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(get_settings(), "BUFFER_SIMULATED", False, raising=False)

    hostile = '") { id } evil: organization(input: {id: "1"}) { name'
    piece = await _approved_piece()
    await _scheduled_row(piece, PublicationPlatform.YOUTUBE, hostile, due_minutes=-5)
    await _scheduled_row(piece, PublicationPlatform.TIKTOK, "tt-clean", due_minutes=-5)

    recorder = _Recorder()
    recorder.reads = {
        "tt-clean": {"status": "sent", "sentAt": "2026-09-04T14:30:00Z",
                     "externalLink": "https://tiktok.com/@x/video/1", "error": None},
    }
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await buffer_publisher.reconcile_scheduled(db)

    sent_query = recorder.queries[0]
    assert hostile not in sent_query, "the value reached the query text"
    assert "evil:" not in sent_query and "organization(" not in sent_query
    # And the clean row in the same batch is still answered, rather than being
    # dragged down by its neighbour.
    assert (await _sched(piece))["tiktok"][0] == "published"


async def test_a_state_we_do_not_recognise_is_said_out_loud(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Not inventing a verdict is right; doing it in silence is not.

    An unknown label leaves the row SCHEDULED and the piece PUBLISHING for
    ever, asked about on every tick, with nobody told. Nothing is written —
    guessing from a label we do not understand is how a live post gets retired
    — but it is logged as an error naming the rows.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(get_settings(), "BUFFER_SIMULATED", False, raising=False)

    piece = await _approved_piece()
    await _scheduled_row(piece, PublicationPlatform.YOUTUBE, "yt-1", due_minutes=-5)

    recorder = _Recorder()
    recorder.reads = {
        "yt-1": {"status": "quarantined_by_platform", "sentAt": None,
                 "externalLink": None, "error": None},
    }
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    with caplog.at_level("ERROR", logger="app.services.buffer_publisher"):
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert await buffer_publisher.reconcile_scheduled(db) == 0

    assert (await _sched(piece))["youtube"][0] == "scheduled"
    shouted = "\n".join(r.getMessage() for r in caplog.records)
    assert "quarantined_by_platform" in shouted, shouted


async def test_an_in_flight_post_with_an_error_object_is_not_retired(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sending` with a transient error attached is still on its way out."""
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(get_settings(), "BUFFER_SIMULATED", False, raising=False)

    piece = await _approved_piece()
    await _scheduled_row(piece, PublicationPlatform.YOUTUBE, "yt-1", due_minutes=-5)

    recorder = _Recorder()
    recorder.reads = {
        "yt-1": {"status": "sending", "sentAt": None, "externalLink": None,
                 "error": {"message": "temporary upstream hiccup"}},
    }
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            assert await buffer_publisher.reconcile_scheduled(db) == 0
    assert (await _sched(piece))["youtube"][0] == "scheduled"


# ── The same mechanics, in the mode production actually runs ─────────────
#
# The tests at the top of this file are pinned to the immediate path. That is
# right for what they assert, but it left the four mechanics below covered only
# in a mode `CONTENT_SCHEDULE_ENABLED` turns OFF. Re-approval especially: it is
# the step that turns a wrong FAILED into a second public post, and in queue
# mode nothing looked at it until now.


async def test_a_quota_pause_in_queue_mode_marks_nothing_failed(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A quota pause is not a content failure, whichever mode we are in."""
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    piece = await _approved_piece()

    recorder = _Recorder({TT: QuotaReached("Buffer quota reached")})
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            with pytest.raises(QuotaReached):
                await publish_piece(db, piece)

    rows = await _sched(piece)
    assert "failed" not in {r[0] for r in rows.values()}, rows
    # The paused platform is released for the next tick, not stranded.
    assert rows["tiktok"][0] == "pending"
    assert rows["tiktok"][1] is None

    # Next tick: it gets a slot, and not one already spent by its own siblings.
    monkeypatch.setattr(buffer_publisher, "_graphql", _Recorder())
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, piece)
    rows = await _sched(piece)
    assert all(r[0] == "scheduled" for r in rows.values()), rows


async def test_re_approval_in_queue_mode_retries_only_what_failed(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-approved piece re-sends its FAILED platforms and nothing else.

    This is step four of the blocking chain: a wrong FAILED plus this
    behaviour equals a second public post. The behaviour itself is correct and
    has to stay — a person who put a piece back through the queue meant it —
    so the defence is that FAILED must never be written from a failed read.
    That is asserted in `test_graphql_errors_never_retire_a_live_post`; this
    pins the other half, that a SCHEDULED sibling is not dragged along.
    """
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    piece = await _approved_piece()

    recorder = _Recorder({TT: BufferRefused("the channel refused it")})
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, piece)

    rows = await _sched(piece)
    assert rows["tiktok"][0] == "failed"
    assert rows["youtube"][0] == "scheduled"
    scheduled_before = rows["youtube"][1]

    # A person puts it back through the queue and approves it again.
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("UPDATE content_pieces SET status='approved' WHERE id=:i"),
            {"i": piece},
        )
        await db.commit()

    second = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", second)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, piece)

    assert len(second.sent) == 1, (
        f"only the failed platform should be re-sent, got {len(second.sent)}"
    )
    assert second.sent[0]["channelId"] == TT
    rows = await _sched(piece)
    assert rows["tiktok"][0] == "scheduled"
    # The one that was already queued keeps the exact slot Buffer holds it for.
    assert rows["youtube"][1] == scheduled_before


async def test_the_daily_cap_still_counts_pieces_in_queue_mode(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One video is three posts; the budget is spent in videos."""
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    monkeypatch.setattr(get_settings(), "CONTENT_PUBLISH_MAX_PER_DAY", 2, raising=False)
    for _ in range(3):
        await _approved_piece()

    monkeypatch.setattr(buffer_publisher, "_graphql", _Recorder())
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_approved(db)

    async with get_bypass_session_factory()() as db:
        touched = (
            await db.execute(
                text("SELECT count(DISTINCT piece_id) FROM content_publications")
            )
        ).scalar_one()
    assert touched == 2, f"the cap let {touched} pieces through with a limit of 2"


async def test_one_platform_failing_in_queue_mode_does_not_stop_the_others(
    database_url: str, queue_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal is about one channel, and the other two still get their date."""
    await _cleanup()
    await _brokerage()
    await _set_timezone()
    piece = await _approved_piece()

    recorder = _Recorder({IG: BufferRefused("instagram said no")})
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    with org_scope(ORG):
        async with get_session_factory()() as db:
            await publish_piece(db, piece)

    rows = await _sched(piece)
    assert rows["instagram"][0] == "failed"
    assert "instagram said no" in rows["instagram"][3]
    assert rows["youtube"][0] == "scheduled" and rows["youtube"][1] is not None
    assert rows["tiktok"][0] == "scheduled" and rows["tiktok"][1] is not None


# ── The link says which network it came from ─────────────────────────────
#
# Measured on the live site the day this was written: every real visitor so far
# arrived as `direct`, with no referrer at all. Instagram strips it, in-app
# browsers strip it, and a link in a Shorts description is not even clickable.
# A query string is the only part of a link that survives all of that, so the
# tagging has to happen in the caption — there is nothing to read afterwards.

CTA = "https://www.denverhomestory.com"


def test_each_platform_gets_its_own_source() -> None:
    text = f"Two numbers tell you everything. Start here: {CTA}"
    for platform, expected in (
        (PublicationPlatform.YOUTUBE, "utm_source=youtube"),
        (PublicationPlatform.TIKTOK, "utm_source=tiktok"),
        (PublicationPlatform.INSTAGRAM, "utm_source=instagram"),
    ):
        out = with_platform_utm(text, CTA, platform, 10, "video")
        assert expected in out, out
        assert "utm_medium=social" in out
        assert "utm_campaign=video" in out
        # Which video, not just which network: "this one brought eleven visits"
        # rather than "the videos brought eleven".
        assert "utm_content=piece-10" in out


def test_a_caption_without_the_link_is_left_exactly_as_it_was() -> None:
    text = "No call to action in this one."
    assert with_platform_utm(text, CTA, PublicationPlatform.TIKTOK, 4, "video") == text


def test_no_cta_configured_changes_nothing() -> None:
    """`CONTENT_CTA_URL` is empty until the domain is live, and an empty string
    is in every caption if you look for it with `in`."""
    text = f"Start here: {CTA}"
    assert with_platform_utm(text, "", PublicationPlatform.TIKTOK, 4, "video") == text


def test_a_url_that_already_carries_a_query_gets_an_ampersand() -> None:
    cta = "https://www.denverhomestory.com/?ref=bio"
    out = with_platform_utm(f"Here: {cta}", cta, PublicationPlatform.YOUTUBE, 7, "video")
    assert "?ref=bio&utm_source=youtube" in out
    assert "??" not in out


def test_a_longer_url_that_merely_starts_the_same_is_not_rewritten() -> None:
    """The trap in "replace the first occurrence": the blog link starts with the
    CTA, and rewriting it would insert a query in the middle of a path and break
    a link that worked."""
    text = f"Read more at {CTA}/blog and start at {CTA}"
    out = with_platform_utm(text, CTA, PublicationPlatform.TIKTOK, 3, "video")
    assert f"{CTA}/blog and" in out, "the blog link is untouched"
    assert out.rstrip().endswith("utm_content=piece-3")


def test_only_the_first_mention_is_tagged() -> None:
    text = f"{CTA} … and again {CTA}"
    out = with_platform_utm(text, CTA, PublicationPlatform.TIKTOK, 5, "video")
    assert out.count("utm_source=tiktok") == 1


def test_tagging_the_link_does_not_create_a_fair_housing_violation() -> None:
    """The gate is demonstrated, not assumed. This function only edits a URL,
    but the rail runs on the final text and nothing else in this repo is
    allowed to change a caption without proving the rail still passes."""
    from app.services.fair_housing import find_violations

    text = f"A quiet street near good schools is what most families ask for. {CTA}"
    before = find_violations(text, "en")
    after = find_violations(
        with_platform_utm(text, CTA, PublicationPlatform.YOUTUBE, 9, "video"), "en"
    )
    assert after == before


@pytest.mark.asyncio
async def test_the_three_posts_leave_with_three_different_sources(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end, on the text that actually goes over the wire.

    The unit tests above prove the function can tag a link. This proves the
    publisher calls it — which is the half that breaks silently: everything
    still posts, the videos still go out, and the only symptom is a funnel
    where every visit says `direct` for ever.
    """
    await _brokerage()
    recorder = _Recorder()
    monkeypatch.setattr(buffer_publisher, "_graphql", recorder)
    s = get_settings()
    monkeypatch.setattr(s, "CONTENT_CTA_URL", CTA, raising=False)
    monkeypatch.setattr(s, "CONTENT_UTM_CAMPAIGN", "video", raising=False)
    try:
        piece_id = await _approved_piece()
        # The caption has to carry the link for there to be anything to tag;
        # in production `_with_cta` appends it as the piece is written.
        async with get_bypass_session_factory()() as db:
            piece = await db.get(ContentPiece, piece_id)
            piece.caption = f"Three numbers decide the price. {CTA}"
            await db.commit()

        with org_scope(ORG):
            async with get_session_factory()() as db:
                await publish_piece(db, piece_id)

        texts = [sent["text"] for sent in recorder.sent]
        assert len(texts) == 3
        sources = sorted(
            t.split("utm_source=")[1].split("&")[0] for t in texts if "utm_source=" in t
        )
        assert sources == ["instagram", "tiktok", "youtube"]
        assert all(f"utm_content=piece-{piece_id}" in t for t in texts)
    finally:
        await _cleanup()
