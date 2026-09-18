"""TikTok and Instagram counts through Buffer, dated when Buffer read them.

Until now those two numbers arrived exactly one way: a person opened the app,
read the count off their phone and typed it into the console. That is what
`set_publication_metrics` says about itself — *"for those two this route is the
only way the number ever arrives"* — and it was true of the NATIVE APIs, which
hand counts to a first-party app that has passed platform review. Buffer is
such an app, and we already hold its token.

**Measured on two real posts on 18-sep-2026, not read off the schema.** The
enum lists sixteen metric types and says nothing about which ones a channel
fills in. What actually came back:

* TikTok  — views 94, reach 92, comments 0, reactions 0, shares 0,
  totalTimeWatched 7.27, averageTimeWatched 4.49
* Instagram — views 7, reach 5, comments 0, reactions 0, shares 0, saves 0,
  follows 0

Three facts drove the whole design, and each has a test below:

1. **There is no `likes`.** Both channels answer `reactions`. A column mapped
   onto the same-sounding name would have stayed NULL for ever while every
   layer reported success.
2. **`metrics` is a LIST of `{type, value}` and it varies by channel** — TikTok
   sent the watch-time pair and no `saves`; Instagram the reverse. Read as an
   object of fixed shape it would work on one network and not the other.
3. **`metricsUpdatedAt` was YESTERDAY on both** (20:03 and 21:24 UTC on the
   17th). Buffer refreshes about once a day. Filing that under today would put
   a correct number in the wrong frame, and the scorecard would claim a reading
   nobody took today.

The third one also answers a question the typed numbers cannot. The same
publication was typed as 94 on three consecutive days. That is either a post
that did not move or a person copying yesterday's figure, and nothing in the
data tells them apart. `metricsUpdatedAt` does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.buffer_publisher import parse_post_metrics

#: The TikTok answer, word for word in the shape Buffer sends it.
TIKTOK = {
    "status": "sent",
    "metricsUpdatedAt": "2026-09-17T21:24:02Z",
    "metrics": [
        {"type": "views", "value": 94},
        {"type": "reach", "value": 92},
        {"type": "comments", "value": 0},
        {"type": "reactions", "value": 0},
        {"type": "shares", "value": 0},
        {"type": "engagementRate", "value": 0},
        {"type": "totalTimeWatched", "value": 7.27},
        {"type": "averageTimeWatched", "value": 4.49},
    ],
}

#: The Instagram answer. A DIFFERENT set of types, which is the point.
INSTAGRAM = {
    "status": "sent",
    "metricsUpdatedAt": "2026-09-17T20:03:27Z",
    "metrics": [
        {"type": "views", "value": 7},
        {"type": "reach", "value": 5},
        {"type": "comments", "value": 0},
        {"type": "reactions", "value": 0},
        {"type": "shares", "value": 0},
        {"type": "saves", "value": 0},
        {"type": "follows", "value": 0},
    ],
}


def test_the_tiktok_answer_becomes_our_three_columns() -> None:
    values, _ = parse_post_metrics(TIKTOK)
    assert values == {"views": 94, "likes": 0, "comments": 0}


def test_the_instagram_answer_works_with_a_different_metric_list() -> None:
    """Same parser, and the two channels do not send the same types.

    Mutation that this catches: reading `metrics` as an object with fixed keys
    instead of a list of pairs passes on whichever network was written first
    and returns nothing on the other.
    """
    values, _ = parse_post_metrics(INSTAGRAM)
    assert values == {"views": 7, "likes": 0, "comments": 0}


def test_likes_comes_from_reactions_because_there_is_no_likes() -> None:
    """The trap, asserted on its own so its message says what went wrong.

    Neither channel returned a `likes` metric. If our column were mapped to the
    name that matches it, it would be NULL for ever and nothing would fail.
    """
    values, _ = parse_post_metrics(
        {"metrics": [{"type": "reactions", "value": 12}], "metricsUpdatedAt": None}
    )
    assert values["likes"] == 12


def test_a_channel_that_does_send_likes_is_not_ignored() -> None:
    """The other direction. Accepting only `reactions` would drop the number
    the day a channel sends the obvious name instead."""
    values, _ = parse_post_metrics({"metrics": [{"type": "likes", "value": 5}]})
    assert values["likes"] == 5


def test_reactions_wins_when_a_channel_sends_both() -> None:
    """Resolved by declared preference, never by the order Buffer happens to
    list them in — an order it does not promise."""
    values, _ = parse_post_metrics(
        {
            "metrics": [
                {"type": "likes", "value": 99},
                {"type": "reactions", "value": 3},
            ]
        }
    )
    assert values["likes"] == 3


def test_the_watch_time_metrics_are_not_mistaken_for_counts() -> None:
    """`averageTimeWatched` is 4.49 seconds. Nothing stores it, and above all
    it must not land in a column that means "how many people"."""
    values, _ = parse_post_metrics(TIKTOK)
    assert set(values) == {"views", "likes", "comments"}


def test_when_buffer_read_it_is_kept_and_it_is_not_now() -> None:
    """The whole reason the reading can be dated honestly."""
    _, read_at = parse_post_metrics(TIKTOK)
    assert read_at == datetime(2026, 9, 17, 21, 24, 2, tzinfo=UTC)


def test_a_reading_with_no_timestamp_says_so_rather_than_guessing() -> None:
    """`None` here is what makes the caller skip the row instead of stamping it
    with our clock, which would undo the point of the whole change."""
    post = dict(TIKTOK)
    del post["metricsUpdatedAt"]
    _, read_at = parse_post_metrics(post)
    assert read_at is None


def test_the_read_time_lands_on_the_right_day_in_the_office_zone() -> None:
    """21:24 UTC is still the 17th in Denver; 02:00 UTC would be too.

    This is the arithmetic the caller does, asserted here because getting it
    wrong files an evening reading on the following day — the same mistake
    `agency_today` exists to prevent for the manual path.
    """
    denver = ZoneInfo("America/Denver")
    _, read_at = parse_post_metrics(TIKTOK)
    assert read_at.astimezone(denver).date().isoformat() == "2026-09-17"

    _, late = parse_post_metrics({"metricsUpdatedAt": "2026-09-18T02:00:00Z"})
    assert late.astimezone(denver).date().isoformat() == "2026-09-17"


@pytest.mark.parametrize(
    "broken",
    [
        {"metrics": "not a list"},
        {"metrics": [None, {"type": "views", "value": 94}]},
        {"metrics": [{"type": "views", "value": "ninety-four"}, {"type": "comments", "value": 2}]},
        {"metrics": [{"type": "", "value": 1}, {"type": "views", "value": 94}]},
    ],
)
def test_one_malformed_entry_never_costs_the_rest(broken: dict) -> None:
    """A vendor boundary, so every field is hostile.

    The pass writes every other post in the same batch; a single bad entry that
    raised would take all of them with it.
    """
    values, _ = parse_post_metrics(broken)
    assert isinstance(values, dict)
    assert "ninety-four" not in str(values)


def test_a_count_that_arrives_with_a_decimal_point_is_still_a_count() -> None:
    """JSON has one number type and Buffer uses the float side of it —
    `averageTimeWatched` came back as 4.49.

    Honest about what this proves: `int(94.0)` works on its own, so deleting
    the `float()` call does NOT make this test red. It is here to pin the
    behaviour a count with a decimal point must have, not to defend a line.
    """
    values, _ = parse_post_metrics({"metrics": [{"type": "views", "value": 94.0}]})
    assert values == {"views": 94}


def test_a_true_is_not_a_count() -> None:
    """`True` is an `int` in Python, so `int(True)` is 1 and a boolean would be
    stored as one view by a parser that only checked the type."""
    values, _ = parse_post_metrics({"metrics": [{"type": "views", "value": True}]})
    assert "views" not in values


def test_nothing_at_all_is_not_an_error() -> None:
    """A post published minutes ago has no metrics yet. That is a fact about
    the post, not a failure to read it."""
    assert parse_post_metrics({}) == ({}, None)
    assert parse_post_metrics(None) == ({}, None)
