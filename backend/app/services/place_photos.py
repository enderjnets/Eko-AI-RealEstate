"""Real photographs of the places a Denver Decoded piece names.

Why this exists: on 30-sep-2026 Ender rejected piece 103, a Red Rocks video in
which Red Rocks never appeared — "the places that are named must be in the
videos". Every shot had been drawn by a model from a sentence, and when the
drawing failed the engine filled the gap with stock footage searched by the
hook. Nothing anywhere checked that the picture was the place.

So the places with a brief now carry photographs that a person checked: each
file below was found on Wikimedia Commons, compared against the place, cleared
for commercial use and approved one by one by Ender on 30-sep-2026 ("Apruebo:
R3, R9, R7, R5, C8, C15, C9, C3, L2, L10, L7, L4" — the ids below are those
codes). Only public domain, CC0 and CC BY: CC BY-SA was left out, because its
share-alike clause could reach the whole video.

What is NOT in this repository: the image files. The repository is public and
the licences ask for attribution, not for a mirror. The render worker fetches
each original from Commons and refuses any file whose SHA-1 is not the one
recorded here, so a file replaced on Commons after the approval never reaches a
video.

Everything that depends on which photos a piece shows — the shots the worker
draws, the disclosure and the credits in the caption — asks `assign` the same
question, so the caption cannot credit a photo the video does not show.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentLanguage, ContentPiece
from app.services.content_growth import growth_topic_for

APPROVED_ON = date(2026, 9, 30)
APPROVED_BY = "Ender"

#: The licences a photo here may carry. Anything else is refused at import.
_PUBLIC = ("Public domain", "CC0")
_ATTRIBUTION = ("CC BY 2.0", "CC BY 3.0", "CC BY 4.0")


@dataclass(frozen=True)
class PlacePhoto:
    id: str
    #: `Topic.key` of the brief whose place it shows.
    topic: str
    place: str
    file: str
    url: str
    page: str
    sha1: str
    width: int
    height: int
    #: Empty when Commons names nobody (the 1941 aerial, the HABS survey).
    author: str
    license: str
    shows: str

    def __post_init__(self) -> None:
        if self.license not in _PUBLIC + _ATTRIBUTION:
            raise ValueError(f"{self.id}: licence {self.license!r} is not one we use")
        if len(self.sha1) != 40:
            raise ValueError(f"{self.id}: a SHA-1 is 40 hex characters")
        if not self.url.startswith("https://upload.wikimedia.org/"):
            raise ValueError(f"{self.id}: not a Commons original")


_RED_ROCKS = "denver_decoded_4"
_CAPITOL = "denver_decoded_0"
_LARIMER = "denver_decoded_2"
_GOVERNOR = "denver_decoded_1"
_C = "https://upload.wikimedia.org/wikipedia/commons/"
_P = "https://commons.wikimedia.org/wiki/"

# In the order Ender approved them, which is the order they are used in: the
# first opens the video and the second closes it.
PHOTOS: tuple[PlacePhoto, ...] = (
    PlacePhoto(
        id="R3", topic=_RED_ROCKS, place="Red Rocks",
        file="File:Red Rocks Amphitheater above Denver, Colorado LCCN2011630896.tif",
        url=_C + "f/ff/Red_Rocks_Amphitheater_above_Denver%2C_Colorado_LCCN2011630896.tif",
        page=_P + "File:Red_Rocks_Amphitheater_above_Denver,_Colorado_LCCN2011630896.tif",
        sha1="fdb968e8e6513829adbecf79ccd7ce89291d88ec", width=3400, height=4310,
        author="Carol M. Highsmith", license="Public domain",
        shows="Red Rocks Amphitheater above Denver (Commons title)",
    ),
    PlacePhoto(
        id="R9", topic=_RED_ROCKS, place="Red Rocks",
        file="File:The famous Red Rock Amphitheatre (6452947535).jpg",
        url=_C + "a/a9/The_famous_Red_Rock_Amphitheatre_%286452947535%29.jpg",
        page=_P + "File:The_famous_Red_Rock_Amphitheatre_(6452947535).jpg",
        sha1="8abec8ce26c0febbbf1760767f1249fd20de0c77", width=2592, height=3872,
        author="Maarten Heerlien", license="CC BY 2.0",
        shows="The famous Red Rock Amphitheatre (Commons description)",
    ),
    PlacePhoto(
        id="R7", topic=_RED_ROCKS, place="Red Rocks",
        file="File:Seating area in Red Rock amphitheatre (6452951521).jpg",
        url=_C + "3/3e/Seating_area_in_Red_Rock_amphitheatre_%286452951521%29.jpg",
        page=_P + "File:Seating_area_in_Red_Rock_amphitheatre_(6452951521).jpg",
        sha1="a8867c339bb03b286d3e6ca462b3c3d8411181e9", width=2592, height=3872,
        author="Maarten Heerlien", license="CC BY 2.0",
        shows="Seating area, hewn into the rocks (Commons title and description)",
    ),
    PlacePhoto(
        id="R5", topic=_RED_ROCKS, place="Red Rocks",
        file="File:Red Rocks Amphitheatre 1941.jpg",
        url=_C + "d/da/Red_Rocks_Amphitheatre_1941.jpg",
        page=_P + "File:Red_Rocks_Amphitheatre_1941.jpg",
        sha1="2fd9bdaaf9923b5a3ec57307ad503de2db3c8e9b", width=3599, height=2679,
        author="", license="Public domain",
        shows="Red Rocks Amphitheatre photographed from the air, 1941 (Commons description)",
    ),
    PlacePhoto(
        id="C8", topic=_CAPITOL, place="the Colorado State Capitol",
        file="File:Colorado State Capitol - 54046260779.jpg",
        url=_C + "4/4a/Colorado_State_Capitol_-_54046260779.jpg",
        page=_P + "File:Colorado_State_Capitol_-_54046260779.jpg",
        sha1="11225c3cacec03f36689297c21113e2b85ae1a6c", width=1709, height=2560,
        author="xiquinhosilva", license="CC BY 2.0",
        shows="The Colorado State Capitol, 200 East Colfax Avenue (Commons description)",
    ),
    PlacePhoto(
        id="C15", topic=_CAPITOL, place="the Colorado State Capitol",
        file="File:Tree Framed.jpg",
        url=_C + "2/2e/Tree_Framed.jpg",
        page=_P + "File:Tree_Framed.jpg",
        sha1="5b2425446de79213e4a2b11f510e85a0a5775f37", width=5304, height=7952,
        author="jjmusgrove", license="CC BY 2.0",
        shows="Colorado Capitol Building, framed by trees (Commons description and title)",
    ),
    PlacePhoto(
        id="C9", topic=_CAPITOL, place="the Colorado State Capitol",
        file="File:Colorado State Capitol - 54046380855.jpg",
        url=_C + "e/ef/Colorado_State_Capitol_-_54046380855.jpg",
        page=_P + "File:Colorado_State_Capitol_-_54046380855.jpg",
        sha1="ae22792066cb506286a6d7d7cc18d4d151b725cd", width=2560, height=1709,
        author="xiquinhosilva", license="CC BY 2.0",
        shows="The Colorado State Capitol, 200 East Colfax Avenue (Commons description)",
    ),
    PlacePhoto(
        id="C3", topic=_CAPITOL, place="the Colorado State Capitol",
        file="File:Colorado State Capitol - 54045065567.jpg",
        url=_C + "d/de/Colorado_State_Capitol_-_54045065567.jpg",
        page=_P + "File:Colorado_State_Capitol_-_54045065567.jpg",
        sha1="a34c9b41c724bd9ed59625f8a99a756113e500a3", width=1679, height=2560,
        author="xiquinhosilva", license="CC BY 2.0",
        shows="The Colorado State Capitol, 200 East Colfax Avenue (Commons description)",
    ),
    PlacePhoto(
        id="L2", topic=_LARIMER, place="Larimer Square",
        file="File:Denver, CO (55347641208).jpg",
        url=_C + "6/64/Denver%2C_CO_%2855347641208%29.jpg",
        page=_P + "File:Denver,_CO_(55347641208).jpg",
        sha1="3e7964f11387cbbe6a7cc999ba2011f19a8c7827", width=6960, height=4640,
        author="thirdsphoto", license="CC BY 4.0",
        shows="Larimer Square in Denver (Commons description)",
    ),
    PlacePhoto(
        id="L10", topic=_LARIMER, place="Larimer Square",
        file="File:Larimer St Plaza.jpg",
        url=_C + "1/1e/Larimer_St_Plaza.jpg",
        page=_P + "File:Larimer_St_Plaza.jpg",
        sha1="a8a810b8fcba6d97975a37b36b698f3911374ad6", width=4032, height=2268,
        author="RuralResurrection", license="CC BY 4.0",
        shows="Larimer Street Plaza in Denver (Commons description)",
    ),
    PlacePhoto(
        id="L7", topic=_LARIMER, place="Larimer Square",
        file="File:Larimer Square (55347886055).jpg",
        url=_C + "f/f7/Larimer_Square_%2855347886055%29.jpg",
        page=_P + "File:Larimer_Square_(55347886055).jpg",
        sha1="2c63cdf6f73ccf9d43894dec08c66284f946517e", width=6426, height=4284,
        author="thirdsphoto", license="CC BY 4.0",
        shows="Larimer Square in Denver (Commons description)",
    ),
    PlacePhoto(
        id="L4", topic=_LARIMER, place="Larimer Square",
        file="File:LARIMER SQUARE (1400 BLOCK OF LARIMER STREET) - Skyline Urban Renewal Area, Larimer Square, 1400 Block, Larimer Street, Denver, Denver County, CO HABS COLO,16-DENV,18-1.tif",
        url=_C + "3/38/LARIMER_SQUARE_%281400_BLOCK_OF_LARIMER_STREET%29_-_Skyline_Urban_Renewal_Area%2C_Larimer_Square%2C_1400_Block%2C_Larimer_Street%2C_Denver%2C_Denver_County%2C_CO_HABS_COLO%2C16-DENV%2C18-1.tif",
        page=_P + "File:LARIMER_SQUARE_(1400_BLOCK_OF_LARIMER_STREET)_-_Skyline_Urban_Renewal_Area,_Larimer_Square,_1400_Block,_Larimer_Street,_Denver,_Denver_County,_CO_HABS_COLO,16-DENV,18-1.tif",
        sha1="d0c36d818140e0e2f1a2d6fcb65ad819a84fbf9f", width=5000, height=3979,
        author="", license="Public domain",
        shows="Larimer Square, 1400 block of Larimer Street, HABS survey (Commons title)",
    ),
)


#: Topics with no place of their own whose brief asks for another topic's
#: place. The governor story's brief says "Show Larimer Street downtown";
#: on 30-sep-2026 piece 98 opened on a drawn "Larimer Street, Denver" with a
#: spire out of New York, and Ender chose L2 for that shot.
_BORROWED: dict[str, tuple[str, ...]] = {_GOVERNOR: ("L2",)}


def photos_for_topic(topic_key: str | None) -> tuple[PlacePhoto, ...]:
    if not topic_key:
        return ()
    borrowed = _BORROWED.get(topic_key, ())
    return tuple(
        photo for photo in PHOTOS if photo.topic == topic_key or photo.id in borrowed
    )


#: Topics whose every shot is a photo. The drawing model does not know the
#: Colorado State Capitol: on 30-sep-2026 piece 97 showed a grey dome and a
#: dome with a blank white disc, though its prompt said "no building dome in
#: frame". Ender: "fotos reales ahí también".
_EVERY_SHOT = frozenset({_CAPITOL})


def assign(scene_count: int, photos: Sequence[PlacePhoto]) -> dict[int, PlacePhoto]:
    """Which shot shows which photo: the first and the last, then spread.

    The opening shot is the one the viewer decides on and the closing one is
    what they remember, so the place is in both. The rest of the photos are
    spaced evenly between them and the shots in the gaps stay drawn — except
    in a topic of `_EVERY_SHOT`, where the gaps are filled too.
    """
    if scene_count <= 0 or not photos:
        return {}
    used = list(photos[: min(len(photos), scene_count)])
    if len(used) == 1:
        return {0: used[0]}
    order = [used[0], *used[2:], used[1]]
    step = (scene_count - 1) / (len(order) - 1)
    shown = {round(i * step): photo for i, photo in enumerate(order)}
    if photos[0].topic in _EVERY_SHOT:
        _fill_gaps(scene_count, order, shown)
    return shown


def _fill_gaps(scene_count: int, order: list[PlacePhoto], shown: dict[int, PlacePhoto]) -> None:
    """Each empty shot gets the least shown photo that neither neighbour shows."""
    for scene in range(scene_count):
        if scene in shown:
            continue
        near = {shown.get(scene - 1), shown.get(scene + 1)}
        free = [photo for photo in order if photo not in near] or order
        times = [sum(p is photo for p in shown.values()) for photo in free]
        shown[scene] = free[times.index(min(times))]


_DISCLOSURE_MIXED = {
    ContentLanguage.EN: (
        "Narrated with a synthetic voice. The photos of {place} are real; "
        "the other images are AI-generated."
    ),
    ContentLanguage.ES: (
        "Narrado con una voz sintética. Las fotos {place} son reales; "
        "las demás imágenes están generadas con IA."
    ),
}
_DISCLOSURE_ALL_PHOTOS = {
    ContentLanguage.EN: "Narrated with a synthetic voice. The photos are real.",
    ContentLanguage.ES: "Narrado con una voz sintética. Las fotos son reales.",
}
_CREDITS = {
    ContentLanguage.EN: "Photos: {names}, via Wikimedia Commons (cropped).",
    ContentLanguage.ES: "Fotos: {names}, vía Wikimedia Commons (recortadas).",
}
_PLACE_ES = {"the Colorado State Capitol": "del Capitolio de Colorado"}
_PUBLIC_DOMAIN = {ContentLanguage.EN: "public domain", ContentLanguage.ES: "dominio público"}


def disclosure(
    language: ContentLanguage, scene_count: int, shown: dict[int, PlacePhoto]
) -> str | None:
    """The disclosure for a video that shows these photos, or None for none."""
    if not shown:
        return None
    if len(shown) >= scene_count:
        return _DISCLOSURE_ALL_PHOTOS[language]
    place = next(iter(shown.values())).place
    if language is ContentLanguage.ES:
        place = _PLACE_ES.get(place, f"de {place}")
    return _DISCLOSURE_MIXED[language].format(place=place)


def credit_line(language: ContentLanguage, shown: dict[int, PlacePhoto]) -> str | None:
    """"Photos: author (licence), …" for every photo that names an author.

    CC BY requires the credit; a public-domain photo does not, but its author
    is named when Commons names one. An unnamed public-domain photo adds
    nothing. Each author once per licence, in the order they appear.
    """
    names: list[str] = []
    for _scene, photo in sorted(shown.items()):
        if not photo.author:
            continue
        licence = (
            _PUBLIC_DOMAIN[language] if photo.license in _PUBLIC else photo.license
        )
        name = f"{photo.author} ({licence})"
        if name not in names:
            names.append(name)
    if not names:
        return None
    return _CREDITS[language].format(names=", ".join(names))


async def photos_for_piece(db: AsyncSession, piece: ContentPiece) -> tuple[PlacePhoto, ...]:
    topic = await growth_topic_for(db, piece)
    return photos_for_topic(topic.key if topic is not None else None)


def scene_count(piece: ContentPiece) -> int:
    plan = piece.scenes if isinstance(piece.scenes, dict) else {}
    scenes = plan.get("scenes")
    return len(scenes) if isinstance(scenes, list) else 0


async def shown_in(db: AsyncSession, piece: ContentPiece) -> dict[int, PlacePhoto]:
    """Which shot of this piece shows which photo — the render's answer.

    Nothing unless the caption already says so and credits them. A CC BY photo
    shown without its credit breaks the licence, and a caption that says
    "Images are AI-generated" over a real photo is false: both happen to any
    piece written before the photos existed (97, 100, 103) if it is simply
    rendered again. Such a piece gets its photos when it is rewritten, which
    writes the lines, or when a person adds them.
    """
    language = piece.language
    count = scene_count(piece)
    shown = assign(count, await photos_for_piece(db, piece))
    if not shown:
        return {}
    caption = piece.caption or ""
    said = disclosure(language, count, shown)
    credits = credit_line(language, shown)
    if said not in caption or (credits is not None and credits not in caption):
        return {}
    return shown
