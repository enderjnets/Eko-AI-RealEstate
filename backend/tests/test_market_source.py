from datetime import UTC, datetime

import pytest

from app.services.market_source import MarketSourceError, parse_market_index

HTML = """
<div class="views-row">
  <a href="/news/market-trends/dmar-real-estate-market-trends-report-august-2026"
     class="teaser-list-title">
    <span>DMAR Real Estate Market Trends Report | August 2026</span>
  </a>
  <p><time datetime="2026-09-03T11:00:00Z">September 3, 2026</time></p>
  <p><p>August data shows inventory and prices were flat while closed sales fell.</p></p>
</div>
"""


def test_latest_dmar_report_keeps_verifiable_provenance() -> None:
    source = parse_market_index(HTML, now=datetime(2026, 9, 22, tzinfo=UTC))
    assert source.publisher == "Denver Metro Association of Realtors"
    assert source.published_on.isoformat() == "2026-09-03"
    assert source.url == (
        "https://www.dmarealtors.com/news/market-trends/"
        "dmar-real-estate-market-trends-report-august-2026"
    )
    assert "inventory and prices were flat" in source.summary


def test_stale_or_non_official_market_copy_is_not_used() -> None:
    with pytest.raises(MarketSourceError, match="45 days"):
        parse_market_index(HTML, now=datetime(2026, 11, 1, tzinfo=UTC))
    with pytest.raises(MarketSourceError, match="official DMAR"):
        parse_market_index(
            HTML.replace(
                'href="/news/market-trends/',
                'href="https://example.com/news/market-trends/',
            ),
            now=datetime(2026, 9, 22, tzinfo=UTC),
        )
