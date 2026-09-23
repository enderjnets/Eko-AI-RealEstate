from datetime import date, timedelta

import pytest

from app.api.v1.render_jobs import _finish_input
from app.models import ContentKind, ContentLanguage, ContentPiece, ContentSeries, ContentStatus
from app.services.content_series import (
    contract_for,
    next_editorial_date,
    series_for_date,
)
from app.services.content_writer import (
    DraftPayload,
    Scene,
    _all_violations,
    _with_cta,
    carries_social_cta,
)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 9, 21), ContentSeries.DENVER_DECODED),
        (date(2026, 9, 22), ContentSeries.CONVERSION),
        (date(2026, 9, 23), ContentSeries.DENVER_DECODED),
        (date(2026, 9, 24), ContentSeries.DENVER_MARKET_NO_HYPE),
        (date(2026, 9, 25), ContentSeries.DENVER_DECODED),
        (date(2026, 9, 26), ContentSeries.DENVER_WEEKEND),
        (date(2026, 9, 27), ContentSeries.CONVERSION),
    ],
)
def test_active_week_uses_the_approved_mix(day: date, expected: ContentSeries) -> None:
    assert series_for_date(day, ask_enabled=False) is expected


def test_ask_alternates_on_thursday_only_when_enabled() -> None:
    thursdays = [date(2026, 9, 24), date(2026, 10, 1)]
    assert {series_for_date(day, ask_enabled=True) for day in thursdays} == {
        ContentSeries.ASK_DENVER_HOME_STORY,
        ContentSeries.DENVER_MARKET_NO_HYPE,
    }
    assert series_for_date(date(2026, 9, 21), ask_enabled=True) is ContentSeries.DENVER_DECODED


def test_new_dates_fill_the_gaps_in_the_existing_queue() -> None:
    # 23-sep-2026: the rule used to be "the day after the LAST occupied one".
    # One autumn piece kept on 26-oct put every new line after it, a month of
    # nothing, while the days in between sat empty.
    today = date(2026, 9, 23)
    scheduled = [date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 26)]
    reserved = [date(2026, 10, 3)]
    assert next_editorial_date(
        today, scheduled_dates=scheduled, reserved_dates=reserved
    ) == date(2026, 9, 25)
    assert next_editorial_date(
        today,
        scheduled_dates=[*scheduled, date(2026, 9, 25)],
        reserved_dates=reserved,
    ) == date(2026, 9, 27)
    assert next_editorial_date(today, scheduled_dates=[], reserved_dates=[]) == today


def test_a_late_kept_piece_does_not_push_the_new_lines_after_it() -> None:
    today = date(2026, 9, 22)
    assert next_editorial_date(
        today,
        scheduled_dates=[date(2026, 10, 5)],
        # An approved piece whose Buffer slot is not assigned yet still owns
        # ITS day, and only that day.
        reserved_dates=[date(2026, 10, 26)],
    ) == today


def test_an_occupied_day_is_never_reserved_twice() -> None:
    today = date(2026, 9, 22)
    taken = [today + timedelta(days=offset) for offset in range(10)]
    assert next_editorial_date(
        today, scheduled_dates=taken[:5], reserved_dates=taken[5:]
    ) == today + timedelta(days=10)


def test_the_past_does_not_count_as_occupied() -> None:
    today = date(2026, 9, 22)
    assert next_editorial_date(
        today,
        scheduled_dates=[date(2026, 9, 20)],
        reserved_dates=[date(2026, 9, 21)],
    ) == today


def test_growth_and_conversion_keep_separate_production_contracts() -> None:
    conversion = contract_for(ContentSeries.CONVERSION)
    decoded = contract_for(ContentSeries.DENVER_DECODED)
    weekend = contract_for(ContentSeries.DENVER_WEEKEND)

    assert (conversion.word_min, conversion.word_max) == (45, 65)
    assert (conversion.scene_min, conversion.scene_max) == (7, 9)
    assert (conversion.duration_min, conversion.duration_max) == (20, 35)
    assert conversion.requires_site_link is True

    assert (decoded.word_min, decoded.word_max) == (25, 35)
    assert (decoded.scene_min, decoded.scene_max) == (5, 6)
    # 8, not 12: measured on 23-sep-2026 across 36 renders, the voice speaks
    # 2.4-4.2 words a second (about 3.5 since the engine changed), so 32-42
    # narrated words last 8-14 s. The first Decoded came out at 11 s and was
    # refused against a floor of 12 that most of this range could not meet.
    assert (decoded.duration_min, decoded.duration_max) == (8, 18)
    assert (weekend.duration_min, weekend.duration_max) == (8, 18)
    market = contract_for(ContentSeries.DENVER_MARKET_NO_HYPE)
    assert (market.duration_min, market.duration_max) == (8, 18)
    assert decoded.requires_site_link is False
    assert weekend.social_ctas == ("save", "share")


def _short_draft() -> DraftPayload:
    return DraftPayload(
        hook="Denver: which side would you choose?",
        script=(
            "West for mountain light, east for skyline color. The surprise is "
            "timing: sunset changes both views from one Denver block to another. "
            "Which Denver side wins for you?"
        ),
        caption="Pick a side.",
        scenes=[
            Scene(
                visual_prompt=f"Denver skyline angle {i} with no readable text",
                on_screen_text=f"Denver choice {i}",
            )
            for i in range(5)
        ],
    )


def test_growth_contract_accepts_a_short_that_conversion_rejects() -> None:
    draft = _short_draft()
    growth = _all_violations(
        draft, ContentLanguage.EN, series=ContentSeries.DENVER_DECODED
    )
    conversion = _all_violations(
        draft, ContentLanguage.EN, series=ContentSeries.CONVERSION
    )
    assert not [v for v in growth if v["category"] in {"length", "scenes"}]
    assert {v["category"] for v in conversion} >= {"length", "scenes"}


def test_growth_gets_one_social_cta_and_no_site_cta(monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(
        get_settings(), "CONTENT_CTA_URL", "https://www.denverhomestory.com"
    )
    draft = _with_cta(
        _short_draft(),
        ContentLanguage.EN,
        cta_index=0,
        brokerage="Engel & Völkers",
        series=ContentSeries.DENVER_DECODED,
    )
    assert draft is not None
    assert "denverhomestory.com" not in draft.caption.casefold()
    assert "dot com" not in (draft.narration or "").casefold()
    assert "Follow for more Denver, decoded." in draft.caption
    assert (draft.narration or "").endswith("Follow for more Denver, decoded.")
    assert carries_social_cta(draft.caption, ContentSeries.DENVER_DECODED)
    assert not carries_social_cta(
        "Visit denverhomestory.com", ContentSeries.DENVER_DECODED
    )


def test_growth_render_card_is_social_and_uses_the_short_bounds() -> None:
    piece = ContentPiece(
        kind=ContentKind.GENERATED,
        language=ContentLanguage.EN,
        status=ContentStatus.NEEDS_APPROVAL,
        series=ContentSeries.DENVER_DECODED,
        hook="Which Denver view?",
        script="A short Denver contrast.",
    )
    finish = _finish_input(
        piece,
        {
            "narration": "A short Denver contrast. Follow for more Denver, decoded.",
            "scenes": [{"on_screen_text": "Which Denver view?"}],
        },
    )
    assert finish.cta_display == "@denverhomestory"
    assert "denverhomestory.com" not in finish.cta_display
    assert finish.contract["duration_min"] == 8
    assert finish.contract["duration_max"] == 18


def test_market_render_card_carries_the_verified_source_date() -> None:
    piece = ContentPiece(
        kind=ContentKind.GENERATED,
        language=ContentLanguage.EN,
        status=ContentStatus.NEEDS_APPROVAL,
        series=ContentSeries.DENVER_MARKET_NO_HYPE,
        hook="Three signals, not one headline.",
        script="The latest report points in more than one direction.",
        source={"publisher": "Denver Metro Association of Realtors", "published_on": "2026-09-03"},
    )
    finish = _finish_input(
        piece,
        {
            "narration": "The latest report points in more than one direction. Follow for the next Denver market check.",
            "scenes": [{"on_screen_text": "Three signals"}],
        },
    )
    assert finish.cta_display == "Source: DMAR · 2026-09-03"
    assert finish.cta_label == "FOLLOW THE NEXT MARKET CHECK"
