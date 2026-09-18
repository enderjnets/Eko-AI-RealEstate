"""The rotation talks about Denver, and never promises to send anybody anything.

Written on 17-sep-2026 with the first end-to-end reading of the three networks
on the table. Two facts drove it:

* The single piece that travelled furthest — 20 % of every view and 68 % of
  every like TikTok has ever given us, 35 % of Instagram's views, and the only
  one that produced a conversation — was about autumn in Colorado, and it came
  from outside `TOPICS`. Twelve topics, not one of them local.
* Six of the nine comments on it said "Fall", because the caption said
  *"Comment FALL and I'll send you the free guide"*. Nobody sends anything.
  Answering those six is manual work that only gets done when a person
  remembers, and the ninth sat unanswered for three hours. The guide is a page;
  a topic that points at the page costs nothing and never leaves somebody
  waiting.

So: local topics exist, they reach the person who sells, and no brief in the
rotation offers to deliver something by hand.
"""

from __future__ import annotations

import pytest

from app.services.content_topics import BOTH, BUYER, SELLER, TOPICS

#: The three added in 0.120.0. Named here rather than detected by a keyword so
#: that renaming one is a decision somebody makes on purpose, not a silent drop.
LOCALES = ("the_season_right_now", "altitude_and_your_house", "colorado_weather_and_the_roof")


def _por_clave() -> dict[str, object]:
    return {t.key: t for t in TOPICS}


def test_the_rotation_still_carries_the_local_topics() -> None:
    """Without these the channel goes back to twelve process explainers.

    The reach they exist to buy is measured, not assumed: see the module
    docstring for the numbers it was written from.
    """
    faltan = [clave for clave in LOCALES if clave not in _por_clave()]
    assert not faltan, f"temas locales que ya no están en la rotación: {faltan}"


@pytest.mark.parametrize("clave", LOCALES)
def test_a_local_topic_must_reach_whoever_sells(clave: str) -> None:
    """A local topic labelled BUYER would be tourism with a real-estate logo.

    This channel exists to reach somebody thinking about selling a home with
    this agency. The searches that already bring us people on TikTok are
    "Aspen fall peak" and "Aspen current fall conditions" — real traffic, wrong
    person. Declaring these BOTH is the promise that each one is also useful to
    somebody who already owns a house here; the brief has to keep it.
    """
    topic = _por_clave()[clave]
    assert topic.audience in (BOTH, SELLER), (
        f"{clave} está declarado {topic.audience!r}: un tema local que solo "
        "sirve a quien compra no le habla a quien vende"
    )


def test_two_of_the_three_locals_are_about_the_house_not_the_view() -> None:
    """One piece of pure reach is a bet; three would be a different channel.

    Not a style rule — a ratio. `the_season_right_now` is the one that buys
    attention; the other two have to earn their slot by being useful to an
    owner, or the rotation drifts into a Denver account that happens to mention
    real estate.
    """
    por_clave = _por_clave()
    sobre_la_casa = [
        clave
        for clave in LOCALES
        if any(
            palabra in por_clave[clave].brief_en.lower()
            for palabra in ("house", "roof", "home")
        )
    ]
    assert len(sobre_la_casa) >= 2, (
        "solo "
        f"{len(sobre_la_casa)} de los {len(LOCALES)} temas locales habla de la "
        "casa; el resto es paisaje"
    )


@pytest.mark.parametrize("topic", TOPICS, ids=lambda t: t.key)
def test_no_brief_offers_to_send_anybody_anything(topic: object) -> None:
    """"I'll send you the guide" is a promise a background worker cannot keep.

    It already happened: six people commented "Fall" on one video waiting for a
    guide that a person then had to hand over one by one, and the ninth waited
    three hours because nobody was watching. The page exists and is public.
    A brief may point at it; it may not offer a delivery.
    """
    prohibidas = (
        "send you",
        "i'll send",
        "send it to you",
        "dm me",
        "te lo mando",
        "te lo envío",
        "te la mando",
        "te la envío",
        "escríbeme",
    )
    for texto, lengua in ((topic.brief_en, "brief_en"), (topic.brief_es, "brief_es")):
        bajo = texto.lower()
        ofrece = [frase for frase in prohibidas if frase in bajo]
        assert not ofrece, (
            f"{topic.key}.{lengua} ofrece entregar algo a mano ({ofrece}); "
            "apunta a la página, que no hace esperar a nadie"
        )


def test_the_locals_did_not_break_the_audience_balance() -> None:
    """The balance rule lives in `test_content_audience_and_cta`; this says why.

    Three topics were added to twelve. Two thirds of the rotation still has to
    reach a seller — with fifteen that is ten — and it does because all three
    are BOTH. Asserted here as well so that a future fourth local topic added
    as BUYER fails with a message that explains the trade, instead of with
    arithmetic in another file.
    """
    alcanzan = sum(1 for t in TOPICS if t.audience in (SELLER, BOTH))
    assert alcanzan * 3 >= len(TOPICS) * 2, (
        f"solo {alcanzan} de {len(TOPICS)} temas llegan a quien vende: añadir "
        "un tema local declarado BUYER inclina la rotación al público que no "
        "contrata a esta agencia"
    )
    assert sum(1 for t in TOPICS if t.audience == BUYER) == 3, (
        "el número de temas BUYER cambió sin que nadie tocara este test"
    )
