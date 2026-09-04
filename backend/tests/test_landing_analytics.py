"""The classification rules, tested without a browser or a database.

Everything in `services/landing_analytics.py` that decides something is a pure
function over strings, which is the reason it lives there rather than inside
the handler: these are the rules that turn a report into "TikTok brought forty
visits" or into "we do not know where anybody came from", and being able to
state them as a table of inputs and answers is what keeps them honest.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.landing_analytics import (
    browser_of,
    clip,
    device_of,
    fold_events,
    geo_of,
    in_app_of,
    new_events,
    os_of,
    referrer_host_of,
    source_of,
)

NOW = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)

# Real strings, not invented ones: an in-app browser is exactly where the
# classification has to work and exactly where a hand-written UA would be wrong.
UA_IPHONE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
UA_INSTAGRAM = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 Instagram 331.0.0.35.90 (iPhone14,3; iOS 17_5)"
)
UA_TIKTOK = (
    "Mozilla/5.0 (Linux; Android 13; SM-S908B Build/TP1A) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/119.0.0.0 Mobile Safari/537.36 "
    "trill_310204 JsSdk/1.0 NetType/WIFI Channel/googleplay BytedanceWebview/d8a21c6"
)
UA_MAC_CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
UA_ANDROID_TABLET = (
    "Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/119.0.0.0 Safari/537.36"
)


class TestReferrerHost:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.youtube.com/shorts/abc123", "youtube.com"),
            ("https://l.instagram.com/?u=https%3A%2F%2Fx.com", "l.instagram.com"),
            ("https://www.google.com/search?q=denver", "google.com"),
            ("HTTPS://WWW.TIKTOK.COM/@denverhomestory", "tiktok.com"),
            ("", None),
            (None, None),
            ("not a url", None),
        ],
    )
    def test_reads_the_host(self, url: str | None, expected: str | None) -> None:
        assert referrer_host_of(url) == expected

    def test_android_app_referrers_name_the_site_they_mean(self) -> None:
        """Android's in-app browsers hand over a package name instead of a URL.

        Left unmapped these parse to nothing and the visit is filed as
        `direct` — which is the single most misleading answer available, since
        it reads as "they typed the domain" when they in fact came from a video.
        """
        assert referrer_host_of("android-app://com.google.android.youtube") == "youtube.com"
        assert referrer_host_of("android-app://com.instagram.android") == "instagram.com"
        assert referrer_host_of("android-app://com.example.unknown") is None


class TestSource:
    def test_a_utm_wins_over_the_referrer(self) -> None:
        # We put the UTM on the link ourselves; the referrer is whatever the
        # platform felt like sending.
        assert source_of("tiktok", "youtube.com") == "tiktok"

    @pytest.mark.parametrize(
        "host,expected",
        [
            ("youtube.com", "youtube"),
            ("m.youtube.com", "youtube"),
            ("youtu.be", "youtube"),
            ("tiktok.com", "tiktok"),
            ("l.instagram.com", "instagram"),
            ("google.co.uk", "google"),
            ("duckduckgo.com", "search"),
            ("someblog.example", "other"),
        ],
    )
    def test_falls_back_to_the_referrer(self, host: str, expected: str) -> None:
        assert source_of(None, host) == expected

    def test_nothing_at_all_is_direct(self) -> None:
        assert source_of(None, None) == "direct"
        assert source_of("", "") == "direct"

    def test_an_unknown_campaign_is_other_not_dropped(self) -> None:
        # The row keeps `utm_source` verbatim, so a campaign we did not plan
        # for is still countable — it just does not pretend to be a channel.
        assert source_of("some-newsletter", None) == "other"


class TestUserAgent:
    @pytest.mark.parametrize(
        "ua,device,browser,os_name",
        [
            (UA_IPHONE_SAFARI, "phone", "Safari", "iOS"),
            (UA_MAC_CHROME, "desktop", "Chrome", "macOS"),
            (UA_ANDROID_TABLET, "tablet", "Chrome", "Android"),
            (UA_TIKTOK, "phone", "Chrome", "Android"),
            ("", "unknown", None, None),
            (None, "unknown", None, None),
        ],
    )
    def test_families(self, ua, device, browser, os_name) -> None:
        assert device_of(ua) == device
        assert browser_of(ua) == browser
        assert os_of(ua) == os_name

    def test_in_app_browsers_are_named(self) -> None:
        assert in_app_of(UA_INSTAGRAM) == "instagram"
        assert in_app_of(UA_TIKTOK) == "tiktok"
        assert in_app_of(UA_IPHONE_SAFARI) is None


class TestGeo:
    def test_reads_the_cloudflare_headers(self) -> None:
        country, region, city = geo_of(
            {"cf-ipcountry": "US", "cf-region-code": "CO", "cf-ipcity": "Denver"}
        )
        assert (country, region, city) == ("US", "CO", "Denver")

    def test_absent_headers_are_none_not_empty_strings(self) -> None:
        assert geo_of({}) == (None, None, None)

    def test_cloudflares_own_placeholders_are_not_countries(self) -> None:
        """`XX` means "we do not know" and `T1` means "a Tor exit". Stored
        as-is they appear in every breakdown as if they were places."""
        assert geo_of({"cf-ipcountry": "XX"})[0] is None
        assert geo_of({"cf-ipcountry": "T1"})[0] is None


class TestClip:
    def test_trims_bounds_and_drops_empties(self) -> None:
        assert clip("  hello  ") == "hello"
        assert clip("   ") is None
        assert clip(None) is None
        assert clip(12345) is None
        assert len(clip("x" * 500)) == 200


class TestFoldEvents:
    """The batch reduced to a delta. Nothing here reads the row's current
    values — that is the point: the delta is applied by SQL expressions, so two
    beacons for the same visit cannot each compute a total from the same
    starting point and overwrite one another."""

    def test_counts_and_flags(self) -> None:
        d = fold_events(
            [
                ("page_view", {}),
                ("cta_click", {}),
                ("cta_click", {}),
                ("tel_click", {"where": "hero"}),
                ("form_start", {}),
                ("form_submit", {}),
            ]
        )
        assert (d.events, d.cta_clicks, d.tel_clicks) == (6, 2, 1)
        assert d.form_started and d.form_submitted
        assert d.max_scroll_pct is None

    def test_scroll_is_the_batch_maximum(self) -> None:
        d = fold_events([("scroll", {"pct": 25}), ("scroll", {"pct": 75}), ("scroll", {"pct": 50})])
        assert d.max_scroll_pct == 75

    def test_a_nonsense_scroll_value_is_ignored(self) -> None:
        d = fold_events([("scroll", {"pct": 4000}), ("scroll", {"pct": "half"}),
                         ("scroll", {"pct": True})])
        assert d.max_scroll_pct is None

    def test_sections_are_deduplicated_and_unknown_ones_dropped(self) -> None:
        d = fold_events(
            [
                ("section_view", {"section": "markets"}),
                ("section_view", {"section": "markets"}),
                ("section_view", {"section": "../etc/passwd"}),
                ("section_view", {"section": "about"}),
            ]
        )
        assert d.sections == ["markets", "about"]

    def test_an_empty_batch_folds_to_nothing(self) -> None:
        d = fold_events([])
        assert (d.events, d.cta_clicks, d.tel_clicks, d.sections) == (0, 0, 0, [])
        assert not d.form_started and not d.form_submitted


class TestMergeValues:
    """What reaches the UPDATE. Asserted on the SQL, because the whole reason
    this returns expressions instead of numbers is that a Python number here
    would be a lost update under two concurrent beacons."""

    def _sql(self, values: dict, key: str) -> str:
        from sqlalchemy import update

        from app.models.landing import LandingSession

        stmt = update(LandingSession).values(**values)
        return str(stmt.compile(compile_kwargs={"literal_binds": False}))

    def test_counters_are_expressions_over_the_current_value(self) -> None:
        from app.services.landing_analytics import merge_values

        values = merge_values(fold_events([("cta_click", {}), ("tel_click", {})]), NOW)
        sql = self._sql(values, "cta_clicks")
        for column in ("cta_clicks", "tel_clicks", "event_count"):
            assert f"{column}=(landing_sessions.{column} + " in sql, sql

    def test_the_scroll_maximum_is_taken_by_the_database(self) -> None:
        from app.services.landing_analytics import merge_values

        sql = self._sql(merge_values(fold_events([("scroll", {"pct": 40})]), NOW), "x")
        assert "greatest(landing_sessions.max_scroll_pct" in sql.lower()

    def test_first_timestamps_are_kept_by_coalesce(self) -> None:
        from app.services.landing_analytics import merge_values

        sql = self._sql(
            merge_values(fold_events([("form_start", {}), ("form_submit", {})]), NOW), "x"
        ).lower()
        assert "coalesce(landing_sessions.form_started_at" in sql
        assert "coalesce(landing_sessions.form_submitted_at" in sql

    def test_untouched_fields_are_absent_rather_than_rewritten(self) -> None:
        from app.services.landing_analytics import merge_values

        values = merge_values(fold_events([("page_view", {})]), NOW)
        assert set(values) == {"last_seen_at", "event_count"}


class TestRawRows:
    def test_the_org_comes_from_the_session_not_the_request(self) -> None:
        rows = new_events(1, 7, [("page_view", {"a": 1})], NOW)
        assert [(e.org_id, e.session_id, e.type, e.at) for e in rows] == [
            (1, 7, "page_view", NOW)
        ]
        assert rows[0].meta == {"a": 1}

    def test_empty_metadata_is_stored_as_null(self) -> None:
        assert new_events(1, 7, [("page_view", {})], NOW)[0].meta is None
