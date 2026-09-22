from datetime import date

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


def test_new_dates_begin_after_the_existing_buffer_queue() -> None:
    today = date(2026, 9, 22)
    assert next_editorial_date(
        today,
        scheduled_dates=[date(2026, 9, 23), date(2026, 9, 28)],
        reserved_dates=[date(2026, 9, 29)],
    ) == date(2026, 9, 30)
    assert next_editorial_date(today, scheduled_dates=[], reserved_dates=[]) == today


def test_an_unslotted_existing_window_still_owns_its_future_date() -> None:
    today = date(2026, 9, 22)
    assert next_editorial_date(
        today,
        scheduled_dates=[date(2026, 10, 5)],
        # This represents an approved/publishing piece whose Buffer slot has
        # not been assigned yet. New lines must begin after it, not after the
        # last row that already has `scheduled_at`.
        reserved_dates=[date(2026, 10, 26)],
    ) == date(2026, 10, 27)


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
    assert (decoded.duration_min, decoded.duration_max) == (12, 18)
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
    assert finish.contract["duration_min"] == 12
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
