"""Editing a queued post must not strip the video off it.

`editPost` reads like a patch and behaves like a replacement. Sending
`{id, text}` — the obvious call, and the one written first — passes schema
validation and is then refused by the network with "Instagram posts require at
least one image or video., Instagram posts require a type (post, story, or
reel)". The assets and the metadata were not in the input, so they were dropped.

That was measured on 15-sep-2026 while correcting a brokerage line on
twenty-eight scheduled posts, on the FIRST one. Had the batch run first, every
one of the twenty-eight would have lost its video, silently, weeks before
anybody looked at the queue again.

So the test that matters here is not "does it send the new text" — it is **what
else travels with it**. `build_post_input` is the same function that created the
post, which is why the edit reuses it rather than assembling a second shape that
would drift the first time a platform gains a required field.

The rest holds the parser to the real union. `createPost` names `MutationError`;
this union does not contain it, and copying that fragment across fails
validation with "Fragment cannot be spread here" — a 200 response carrying an
error nobody parsed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models import ContentKind, ContentLanguage, ContentPiece, PublicationPlatform
from app.services.buffer_publisher import (
    _EDITABLE_KEYS,
    BufferRefused,
    edit_scheduled_text,
    parse_edit_post,
    read_scheduled_post,
)

DUE = datetime(2026, 10, 26, 17, 30, tzinfo=UTC)


def _piece() -> ContentPiece:
    return ContentPiece(
        id=39,
        org_id=1,
        kind=ContentKind.GENERATED,
        language=ContentLanguage.EN,
        hook="Twelve places, sorted by when to go.",
        caption="Twelve places, sorted by when to go. denverhomestory.com",
        media_path="a" * 32 + ".mp4",
    )


def _ok(text: str = "new words") -> dict:
    return {
        "data": {
            "editPost": {
                "__typename": "PostActionSuccess",
                "post": {"id": "p1", "text": text, "dueAt": DUE.isoformat(), "status": "scheduled"},
            }
        }
    }


# ---------------------------------------------------------------- the parser


def test_a_successful_edit_returns_the_post() -> None:
    assert parse_edit_post(_ok())["id"] == "p1"


def test_the_platforms_refusal_is_raised_with_its_words() -> None:
    """The exact failure this module exists to have seen once."""
    payload = {
        "data": {
            "editPost": {
                "__typename": "InvalidInputError",
                "message": "Instagram posts require at least one image or video.",
            }
        }
    }
    with pytest.raises(BufferRefused, match="require at least one image or video"):
        parse_edit_post(payload)


def test_a_graphql_error_is_not_read_as_success() -> None:
    """A 200 carrying `errors` is how the wrong fragment reported itself."""
    payload = {"errors": [{"message": "Fragment cannot be spread here"}]}
    with pytest.raises(BufferRefused, match="Fragment cannot be spread here"):
        parse_edit_post(payload)


def test_success_without_a_post_is_not_success() -> None:
    payload = {"data": {"editPost": {"__typename": "PostActionSuccess", "post": {}}}}
    with pytest.raises(BufferRefused, match="without a post"):
        parse_edit_post(payload)


def test_an_unknown_reply_shape_is_refused_rather_than_guessed() -> None:
    with pytest.raises(BufferRefused, match="no data.editPost"):
        parse_edit_post({"data": {}})


# ------------------------------------------------------- what actually travels


@pytest.mark.asyncio
async def test_the_edit_carries_the_video_and_the_type_not_only_the_text() -> None:
    """The whole point. `{id, text}` alone is what the platform refused."""
    sent: dict = {}

    async def fake(query: str, variables: dict) -> dict:
        sent.update(variables["input"])
        return _ok()

    with patch("app.services.buffer_publisher._graphql", new=AsyncMock(side_effect=fake)):
        with patch(
            "app.services.buffer_publisher.configured_channels",
            return_value={PublicationPlatform.INSTAGRAM: "chan-1"},
        ):
            await edit_scheduled_text(
                _piece(), PublicationPlatform.INSTAGRAM, "p1", "new words", DUE
            )

    assert sent["text"] == "new words"
    assert sent["id"] == "p1"
    # Not "some assets": the video, addressed the way the platform fetches it.
    assert sent["assets"], "the edit dropped the video, which is the bug this test exists for"
    assert sent["assets"][0]["video"]["url"].endswith("/content/39/media")
    # Instagram's other required field. It is not in `{id, text}` either.
    assert sent["metadata"], "the edit dropped the post type"


@pytest.mark.asyncio
async def test_the_due_date_is_sent_back_so_the_slot_is_not_lost() -> None:
    sent: dict = {}

    async def fake(query: str, variables: dict) -> dict:
        sent.update(variables["input"])
        return _ok()

    with patch("app.services.buffer_publisher._graphql", new=AsyncMock(side_effect=fake)):
        with patch(
            "app.services.buffer_publisher.configured_channels",
            return_value={PublicationPlatform.YOUTUBE: "chan-2"},
        ):
            await edit_scheduled_text(
                _piece(), PublicationPlatform.YOUTUBE, "p1", "new words", DUE
            )

    assert sent["dueAt"], "without the due date the post would leave its slot"


def test_the_channel_is_not_sent_because_a_post_cannot_change_channel() -> None:
    """An unknown key fails the whole edit, so the built input is filtered
    rather than forwarded wholesale."""
    assert "channelId" not in _EDITABLE_KEYS


@pytest.mark.asyncio
async def test_an_unconfigured_platform_is_refused_before_the_wire() -> None:
    with patch("app.services.buffer_publisher.configured_channels", return_value={}):
        with pytest.raises(BufferRefused, match="no channel configured"):
            await edit_scheduled_text(
                _piece(), PublicationPlatform.TIKTOK, "p1", "new words", DUE
            )


@pytest.mark.asyncio
async def test_reading_a_post_that_buffer_does_not_know_is_an_error() -> None:
    """Read before write: a missing post must not become a blank edit."""
    with patch(
        "app.services.buffer_publisher._graphql",
        new=AsyncMock(return_value={"data": {"post": None}}),
    ):
        with pytest.raises(BufferRefused, match="knows no post"):
            await read_scheduled_post("nope")
