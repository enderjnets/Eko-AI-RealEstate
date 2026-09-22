"""Read the newest public DMAR report without turning search copy into facts."""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from urllib.parse import urljoin, urlsplit

import httpx

INDEX_URL = "https://www.dmarealtors.com/market-trends-reports"
MAX_AGE_DAYS = 45


class MarketSourceError(ValueError):
    pass


@dataclass(frozen=True)
class MarketSource:
    publisher: str
    title: str
    published_on: date
    url: str
    summary: str

    def as_json(self) -> dict[str, str]:
        values = asdict(self)
        values["published_on"] = self.published_on.isoformat()
        return values


_REPORT = re.compile(
    r'<a\s+href="(?P<href>[^"]+)"[^>]*class="teaser-list-title"[^>]*>\s*'
    r'<span[^>]*>(?P<title>DMAR Real Estate Market Trends Report\s*\|[^<]+)</span>'
    r'.{0,1200}?<time\s+datetime="(?P<when>[^"]+)"[^>]*>.*?</time>'
    r'.{0,500}?<p>\s*<p>(?P<summary>.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)
_TAGS = re.compile(r"<[^>]+>")


def _clean(value: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", value)).split())


def parse_market_index(raw: str, *, now: datetime | None = None) -> MarketSource:
    match = _REPORT.search(raw or "")
    if match is None:
        raise MarketSourceError("no official DMAR market report was found")
    url = urljoin(INDEX_URL, html.unescape(match.group("href")))
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "www.dmarealtors.com":
        raise MarketSourceError("the market report is not on the official DMAR host")
    if not parsed.path.startswith("/news/market-trends/dmar-real-estate-market-trends-report-"):
        raise MarketSourceError("the link is not an official DMAR market report")
    try:
        published = datetime.fromisoformat(
            match.group("when").replace("Z", "+00:00")
        ).date()
    except ValueError as exc:
        raise MarketSourceError("the official DMAR report has no readable date") from exc
    today = (now or datetime.now(UTC)).astimezone(UTC).date()
    age = (today - published).days
    if age < -1 or age > MAX_AGE_DAYS:
        raise MarketSourceError(f"the latest official DMAR report is outside {MAX_AGE_DAYS} days")
    summary = _clean(match.group("summary"))
    if not summary:
        raise MarketSourceError("the official DMAR report has no usable summary")
    return MarketSource(
        publisher="Denver Metro Association of Realtors",
        title=_clean(match.group("title")),
        published_on=published,
        url=url,
        summary=summary,
    )


async def latest_market_source() -> MarketSource:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(INDEX_URL, headers={"User-Agent": "EkoAIRealtors/1.0"})
        response.raise_for_status()
    return parse_market_index(response.text)

