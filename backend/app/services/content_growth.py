"""Briefs for the social-growth lines; facts stay narrow and local."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentKind, ContentPiece, ContentSeries
from app.services.content_topics import BOTH, Topic
from app.services.market_source import MarketSource

# Twelve verified Denver facts, approved by Ender on 25-sep-2026 after he
# rejected the old six "A or B?" taste questions (88, 95: the same mountains-or-
# brick idea twice). Each brief carries its own facts, read on the source named
# in it, and what must not be said. The model may not add a number, date or
# claim of its own: a wrong fact about a place locals know is the one thing
# this line cannot afford. The research, with every source, is kept in
# docs/content/denver-decoded-topics.md.
_NO_NEW_FACTS = (
    " Use only the facts in this brief. Add no other number, date, name or claim."
)
_DECODED = (
    "The mile-high mark at the Colorado State Capitol has moved. The 15th step of "
    "the west steps is engraved ONE MILE ABOVE SEA LEVEL (cut into the stone in "
    "1947 after earlier bronze markers kept being stolen). In 1969 engineering "
    "students set a marker on the 18th step. A 2003 survey found that one too high "
    "and a plaque went on the 13th step. A new national survey in 2026 moved it "
    "again. Do not say which step is correct now. Show the Capitol's west steps and "
    "gold dome." + _NO_NEW_FACTS,
    "Denver is named after a governor who had already quit. On 22 November 1858 "
    "the town company named the town after Kansas Territorial Governor James W. "
    "Denver, hoping to win his favour, but he had resigned about a month earlier. "
    "He visited only twice, in 1875 and 1883, and felt poorly received both times. "
    "Show Larimer Street downtown." + _NO_NEW_FACTS,
    "Larimer Square is Denver's first historic district. Its oldest surviving "
    "building is the Kettle Building of 1873. In 1926 business owners tried to "
    "rename the street Main Street. Dana Crawford saved the block, and in 1971 it "
    "became Denver's first historic district. Show the 1400 block of Larimer "
    "Street with its Victorian brick storefronts." + _NO_NEW_FACTS,
    "The City of Denver keeps conservation bison herds at Genesee Park, seen from "
    "Interstate 70 in the foothills, and at Daniels Park. By 1908, 18 bison at the "
    "Denver Zoo in City Park were all that remained in Colorado; the herd moved to "
    "Genesee in 1914. Since 2021 Denver has given surplus bison to tribal nations. "
    "Do not give a head count or say where the bison came from. Show bison in a "
    "foothill pasture with pine forest." + _NO_NEW_FACTS,
    "The rocks at Red Rocks are older than today's Rockies. The Fountain Formation "
    "is about 300 million years old, sediment from the Ancestral Rockies, which "
    "wore away before the present Rockies rose about 65 million years ago. The "
    "amphitheatre belongs to the City and County of Denver; it was built by the "
    "Civilian Conservation Corps and opened in 1941. Do not say which side each "
    "big rock stands on. Show tilted red sandstone monoliths around the seating "
    "bowl." + _NO_NEW_FACTS,
    "The paving on 16th Street downtown copies a diamondback rattlesnake. The "
    "street opened in 1982, designed by I. M. Pei's firm; the granite pattern was "
    "inspired by Navajo rugs and rattlesnake skin. A rebuild finished in October "
    "2025 kept the pattern with new pavers. Do not call them the original stones. "
    "Show the gray and red granite pattern from above." + _NO_NEW_FACTS,
    "Downtown Denver's streets run on a diagonal because gold miners needed the "
    "water. The first streets were laid out along Cherry Creek and the South "
    "Platte River so claims could reach water. Later the rest of the city was laid "
    "on a north-south grid, and the odd intersections where the two grids meet "
    "are what is left of the boomtown. Give no angle in degrees. Show the seam "
    "between the two grids from above." + _NO_NEW_FACTS,
    "One row of seats at Coors Field is purple: in the upper deck, it marks one "
    "mile above sea level among green seats. The air pressure is about 15 percent "
    "lower than at sea-level ballparks, so since 2002 the baseballs are stored in "
    "a humidor, a small room kept at a steady temperature. Give no humidity "
    "figure and do not say it fixed scoring. Show green seats with one purple row "
    "high up." + _NO_NEW_FACTS,
    "Denver Union Station has hidden history. Passengers once boarded trains "
    "through an underground area built in 1912, and some unused passages remain. "
    "During World War Two the station handled 24,000 people a day. From 1906 to "
    "1933 the Mizpah Arch, lit by 2,200 bulbs, stood over 17th Street. Give no "
    "tower height. Show the granite Beaux-Arts station with its rooftop Travel by "
    "Train sign." + _NO_NEW_FACTS,
    "Denver's first newspaper office stood on stilts in the bed of Cherry Creek. "
    "On the night of 19 May 1864 the creek flooded and carried away the Rocky "
    "Mountain News building and Old City Hall, with the city's earliest land "
    "records. At least eight people died. Give no other death toll. Show Cherry "
    "Creek running beside Larimer Street today." + _NO_NEW_FACTS,
    "The Denver Mint on West Colfax is modeled on the Palazzo Medici Riccardi, a "
    "Renaissance palace in Florence. Created by Congress in 1862, for more than 40 "
    "years it only tested gold and silver, and it struck its first coins in 1906. "
    "In 1934 a third of the nation's gold bullion was moved there from San "
    "Francisco. Show the granite facade with its red tile roof." + _NO_NEW_FACTS,
    "Denver's 300 days of sunshine only add up if one hour of sun makes a sunny "
    "day. The state climatologist says there is no official definition. A 1990s "
    "study reached about 300 by counting any day with at least one hour of sun. By "
    "National Weather Service definitions Denver has about 115 clear, 130 partly "
    "cloudy and 120 cloudy days a year. Show the Denver skyline under a partly "
    "cloudy sky." + _NO_NEW_FACTS,
)

_WEEKEND = (
    "Offer one Saturday choice: a Washington Park loop or a Cherry Creek Trail ride. Keep it as a visual A-or-B prompt and state no event, opening-hour, weather or closure information.",
    "Offer one Denver weekend contrast: City Park in the morning or Union Station after dark. Make it saveable, specific and free of schedules, prices, rankings or promises.",
    "Offer one Saturday photo choice: a Front Range view from Sloan's Lake or Denver architecture downtown. Do not claim current weather, access, parking or event information.",
    "Offer one simple Denver weekend choice: foothill scenery near Golden or an urban walk through RiNo. Treat both neutrally and avoid hours, route conditions, businesses or rankings.",
)


#: When the twelve topics above went in. Decoded pieces written before it used
#: the old six and do not move this list along.
DECODED_TOPICS_SINCE = datetime(2026, 9, 26, 5, 0, tzinfo=UTC)


async def decoded_index(db: AsyncSession) -> int:
    """Which of the twelve comes next: one per Decoded written since the list.

    Not `rotation_index`, which counts every generated piece: conversions would
    move this list along too, and two Decoded in a row could land on the same
    topic. A withdrawn or rejected piece still counts, so a topic Ender turned
    down is not offered again before the other eleven.
    """
    return (
        await db.execute(
            select(func.count())
            .select_from(ContentPiece)
            .where(
                ContentPiece.kind == ContentKind.GENERATED,
                ContentPiece.series == ContentSeries.DENVER_DECODED,
                ContentPiece.created_at >= DECODED_TOPICS_SINCE,
            )
        )
    ).scalar_one()


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
