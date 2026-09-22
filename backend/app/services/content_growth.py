"""Briefs for the social-growth lines; facts stay narrow and local."""

from __future__ import annotations

from app.models import ContentSeries
from app.services.content_topics import BOTH, Topic
from app.services.market_source import MarketSource

_DECODED = (
    "Contrast a Front Range view with a downtown Denver view. Ask which one feels more like Denver, then reveal that the city is read in both directions: mountains orient the west side and the skyline marks the urban core. Keep it visual and invite no business action.",
    "Make a fast Denver choice between Red Rocks at first light and Union Station after dark. Treat it as a local taste question, not a ranking, travel itinerary or claim about access, hours or events.",
    "Make a visual choice between the City Park skyline view and a Sloan's Lake sunset view. Explain in one sentence why the same city can feel different from those two public places. State no hours, closures or event claims.",
    "Ask whether a Denver block is easier to recognize from the Front Range in the distance or from the street grid and skyline. Reveal that orientation is part of how locals read the city. Make no neighborhood-quality claim.",
    "Contrast a Denver morning after fresh snow with the same street under afternoon sun. The reveal is that fast visual change is part of the local experience; give no forecast, measurement or safety advice.",
    "Ask which Denver detail people notice first: the mountain horizon or the mix of older brick and newer infill. Reveal that both can appear in one short drive without judging either as better.",
)

_WEEKEND = (
    "Offer one Saturday choice: a Washington Park loop or a Cherry Creek Trail ride. Keep it as a visual A-or-B prompt and state no event, opening-hour, weather or closure information.",
    "Offer one Denver weekend contrast: City Park in the morning or Union Station after dark. Make it saveable, specific and free of schedules, prices, rankings or promises.",
    "Offer one Saturday photo choice: a Front Range view from Sloan's Lake or Denver architecture downtown. Do not claim current weather, access, parking or event information.",
    "Offer one simple Denver weekend choice: foothill scenery near Golden or an urban walk through RiNo. Treat both neutrally and avoid hours, route conditions, businesses or rankings.",
)


def growth_topic(series: ContentSeries, index: int) -> Topic:
    choices = _WEEKEND if series is ContentSeries.DENVER_WEEKEND else _DECODED
    brief = choices[index % len(choices)]
    return Topic(
        key=f"{series.value}_{index % len(choices)}",
        brief_en=brief,
        brief_es=brief,
        audience=BOTH,
    )


def market_topic(source: MarketSource) -> Topic:
    brief = (
        "Use this official DMAR report summary and nothing else as the factual "
        f"basis: TITLE: {source.title}. PUBLISHED: "
        f"{source.published_on.isoformat()}. SUMMARY: {source.summary}. Explain "
        "one useful distinction in plain English, without copying the source, "
        "adding figures, predicting the market or telling anyone to transact."
    )
    return Topic(
        key=f"denver_market_{source.published_on.isoformat()}",
        brief_en=brief,
        brief_es=brief,
        audience=BOTH,
    )
