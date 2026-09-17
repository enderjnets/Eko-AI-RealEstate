"""The pieces whose number comes from the calculator instead of from a model.

Five videos went out on 12-14 September saying "Renting at $2,600 a month? —
Buying is ~$21,000 ahead in five years". The calculator the same caption links
to answers **$53,462** for that rent. The figures were not hallucinated — they
reproduce exactly at a flat 2% appreciation against the page's 3.75% — which is
the worse problem: right under assumptions nobody wrote down is indistinguish-
able from wrong, and the owner set all five to private.

`content_figures.unexplained_figures` closed the door at approval. It refuses a
figure the calculator cannot account for, which means that after v0.104.0 a
piece of this family can only be approved if somebody writes its
`calculator_check` by hand. That is a door, not a road: the gate's own comment
says it — *"nothing in content generation has ever called the calculator, so
the figures arrive as prose"* — and the family it blocks is the only one this
channel has ever been watched for. Measured 15-sep-2026: **72% of all channel
views** belong to it, 401 views against 3 for a piece published the same day.

This module is the road. **The calculator computes the number first and the
model writes words around it**, which is the same trick `_CTA` plays with the
URL in `content_writer`: a value an LLM would eventually corrupt is kept out of
its hands entirely and pasted in afterwards. The model never invents the
figure, never re-rounds it, and never puts it on screen — it is handed the
number in the brief, the screen text is written here, and what it produces is
checked with `unexplained_figures` before it can leave as anything but a DRAFT.

**Rounded here with the same expression the gate rounds with.** `rounds_to`
asks whether `round(computed / step) * step == published`; this states
`round(value / 1000) * 1000`. Written any other way — `math.floor(x + 0.5)`,
say, which is what the calculator uses internally — the two would disagree on
an exact half and a correct piece would be refused by its own check.

**This rail is deliberately outside `content_topics.TOPICS`.** That rotation is
weighted towards sellers on purpose and a test enforces it: this channel exists
to reach people thinking about listing. Every piece here speaks to a renter, so
folding six of them into that tuple would flip the balance the test guards. The
tension is real and it is a business decision, not a bug — the format that
works speaks to buyers and the channel is meant to find sellers — so it is left
visible here rather than resolved by quietly editing the guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import ContentLanguage
from app.services.calculator import build_snapshot
from app.services.content_topics import BUYER, CALCULATED_SOURCE, Topic

# The rents the autumn plan is written around (`docs/content/otono-2026.md`).
# Six, because the series is six videos and a seventh rent would be a number
# nobody chose — these are the bands a Denver renter recognises as their own.
RENTS: tuple[int, ...] = (1_800, 2_200, 2_600, 3_000, 3_500, 4_000)

# Held constant across the series so the videos are comparable to each other,
# and stated on screen for the same reason the assumptions are stated on the
# page: a ceiling computed from savings nobody mentioned is a number with a
# hidden input, which is the defect this whole module exists to close.
SAVINGS = 60_000
CREDIT = "good"

# Four shots, shared by every piece in the rail, from the autumn plan. Places
# and objects only: `content_writer._all_violations` puts these through the
# Fair Housing filter and through `not_english_prompt`, and a housing advert
# whose every frame shows one kind of household says something about who is
# welcome without a sentence anybody could edit.
VISUALS: tuple[str, ...] = (
    "Denver residential street with bungalows, morning light",
    "front door and porch of a brick home, no numbers visible",
    "kitchen window with light across a counter",
    "wide view of a Denver neighbourhood with the Front Range behind",
)


@dataclass(frozen=True)
class Series:
    """One shape of calculated piece, instantiated once per rent.

    `field` is the key of `build_snapshot(...)["result"]` the piece is about.
    Declared rather than inferred from the brief, for the same reason a topic
    declares its audience: what the video claims is a business decision, and a
    business decision that exists only inside prose cannot be tested.
    """

    key: str
    audience: str
    field: str
    brief_en: str
    brief_es: str
    #: Four lines of screen text, one per shot, with `{rent}`, `{figure}` and
    #: `{savings}` filled in here. Each has to stand on its own: the owner
    #: stopped the first cut of these because "$4,000 a month in rent — buys up
    #: to $527,000" never says *of what*, and somebody scrolling reads two
    #: loose numbers. Name the thing, the place, and the comparison.
    screen_en: tuple[str, str, str, str]
    screen_es: tuple[str, str, str, str]


SERIES: tuple[Series, ...] = (
    # First in the rotation on purpose. This is the series that went out wrong
    # and was pulled; the channel has never seen it at the assumptions the page
    # actually uses, and at 3.75% the answer is roughly two and a half times
    # the one those five videos promised.
    Series(
        key="five_year_net",
        audience=BUYER,
        field="net_5y",
        brief_en=(
            "Write this piece around ONE number that has already been "
            "computed for you, and around nothing else.\n\n"
            "Someone renting in Denver at {rent} a month, with {savings} "
            "saved and good credit, comes out about {figure} ahead after five "
            "years by buying a home instead of renting. That counts all of "
            "it: the rent they would have paid, what the home gains, the loan "
            "they pay down, and what it costs to sell at the end.\n\n"
            "That figure is COMPUTED, not invented — it is the answer the "
            "calculator in the caption gives for exactly these inputs, under "
            "the assumptions the page shows by default. State it exactly as "
            "written: {figure}. The ONLY other dollar amounts you may write "
            "are the rent ({rent}) and the savings ({savings}). No monthly "
            "payment, no home price, no closing costs, no other number with a "
            "dollar sign anywhere in the hook, the script or the caption.\n\n"
            "Say what moves it: the appreciation assumption changes this more "
            "than anything else, and on the page it is a slider the viewer "
            "can move, not a promise anybody is making."
        ),
        brief_es=(
            "Escribe esta pieza alrededor de UN número que ya está calculado, "
            "y de nada más.\n\n"
            "Alguien que alquila en Denver por {rent} al mes, con {savings} "
            "ahorrados y buen crédito, sale unos {figure} por delante a los "
            "cinco años si compra en vez de seguir alquilando. Eso cuenta "
            "todo: el alquiler que habría pagado, lo que se revaloriza la "
            "casa, el préstamo que va amortizando, y lo que cuesta vender al "
            "final.\n\n"
            "Esa cifra está CALCULADA, no inventada: es lo que responde la "
            "calculadora del caption para exactamente esos datos, con los "
            "supuestos que la página trae por defecto. Escríbela tal cual: "
            "{figure}. Las ÚNICAS otras cantidades en dólares que puedes "
            "escribir son el alquiler ({rent}) y el ahorro ({savings}). Ni "
            "cuota mensual, ni precio de la casa, ni gastos de cierre, ni "
            "ninguna otra cifra con signo de dólar en el hook, el guion o el "
            "caption.\n\n"
            "Di qué la mueve: el supuesto de revalorización cambia esto más "
            "que ninguna otra cosa, y en la página es un control que quien "
            "mira puede mover, no una promesa de nadie."
        ),
        screen_en=(
            "Renting in Denver at {rent} a month.",
            "Buying a home instead, over five years:",
            "about {figure} ahead of renting.",
            "Your rent, your savings. The page does the math.",
        ),
        screen_es=(
            "Alquilar en Denver por {rent} al mes.",
            "Comprar una casa, a cinco años:",
            "unos {figure} por delante de alquilar.",
            "Tu alquiler, tu ahorro. La página echa la cuenta.",
        ),
    ),
    # Series A of the autumn plan. This one was always right — 41, 43 and 45
    # reproduce to the dollar against the page — which is why it is second:
    # the rail leads with the correction, not with the piece that already
    # worked.
    Series(
        key="price_ceiling",
        audience=BUYER,
        field="price",
        brief_en=(
            "Write this piece around ONE number that has already been "
            "computed for you, and around nothing else.\n\n"
            "Someone paying {rent} a month in rent in Denver, with {savings} "
            "saved and good credit, could carry a home priced up to about "
            "{figure}. It is a ceiling that falls out of what they can pay "
            "every month — not a price, and not a promise that anything is "
            "for sale at it.\n\n"
            "That figure is COMPUTED, not invented — it is the answer the "
            "calculator in the caption gives for exactly these inputs, under "
            "the assumptions the page shows by default. State it exactly as "
            "written: {figure}, and keep the words 'up to'. The ONLY other "
            "dollar amounts you may write are the rent ({rent}) and the "
            "savings ({savings}). No monthly payment, no down payment, no "
            "other number with a dollar sign anywhere in the hook, the script "
            "or the caption.\n\n"
            "Say what sets it: the monthly payment is what decides the "
            "ceiling, far more than the size of the deposit."
        ),
        brief_es=(
            "Escribe esta pieza alrededor de UN número que ya está calculado, "
            "y de nada más.\n\n"
            "Quien paga {rent} al mes de alquiler en Denver, con {savings} "
            "ahorrados y buen crédito, podría sostener una casa de hasta unos "
            "{figure}. Es un techo que sale de lo que puede pagar cada mes — "
            "no es un precio, ni la promesa de que haya algo en venta por "
            "esa cantidad.\n\n"
            "Esa cifra está CALCULADA, no inventada: es lo que responde la "
            "calculadora del caption para exactamente esos datos, con los "
            "supuestos que la página trae por defecto. Escríbela tal cual: "
            "{figure}, y conserva el 'hasta'. Las ÚNICAS otras cantidades en "
            "dólares que puedes escribir son el alquiler ({rent}) y el ahorro "
            "({savings}). Ni cuota mensual, ni entrada, ni ninguna otra cifra "
            "con signo de dólar en el hook, el guion o el caption.\n\n"
            "Di qué lo fija: lo que decide el techo es la cuota mensual, "
            "mucho más que el tamaño de la entrada."
        ),
        screen_en=(
            "{rent} a month in rent in Denver.",
            "That same money, turned into a price:",
            "a home up to {figure}.",
            "With {savings} saved and good credit.",
        ),
        screen_es=(
            "{rent} al mes de alquiler en Denver.",
            "Ese mismo dinero, convertido en precio:",
            "una casa de hasta {figure}.",
            "Con {savings} ahorrados y buen crédito.",
        ),
    ),
)


@dataclass(frozen=True)
class Plan:
    """A calculated piece before a single word of it has been written.

    `check` is what goes into `ContentPiece.calculator_check`, and it records
    the INPUTS rather than the answer. A record that carried the answer would
    agree with itself for ever: the gate recomputes from these inputs, so a
    piece whose text drifts from its own arithmetic is caught by its own
    record instead of being blessed by it.
    """

    topic: Topic
    check: dict[str, Any]
    screen: tuple[str, str, str, str]
    figure: int
    rent: int


def to_thousand(value: float) -> int:
    """A figure as it is said out loud, to the nearest thousand.

    Written as the SAME expression `content_figures.rounds_to` uses to decide
    whether a published number is explained — `round(x / step) * step` with a
    step of a thousand. The calculator rounds half **up** internally
    (`_round`); Python's `round` is half-to-even. On an exact half the two
    disagree, and the disagreement would land as a piece refused by the very
    check that was written to let it through.
    """
    return round(value / 1000) * 1000


def _money(value: float) -> str:
    return f"${to_thousand(value):,}"


def plan_for(index: int, language: ContentLanguage) -> Plan:
    """The `index`-th calculated piece, with its figure already computed.

    The rotation is `rent`-major inside a series: six rents, then the next
    series. A series-major order would publish the same rent twice in a row
    under two different claims, which reads to a viewer as the channel
    contradicting itself.
    """
    per_series = len(RENTS)
    series = SERIES[(index // per_series) % len(SERIES)]
    rent = RENTS[index % per_series]

    inputs: dict[str, Any] = {"rent": rent, "savings": SAVINGS, "credit": CREDIT}
    snapshot = build_snapshot(inputs, None, lang=None)
    value = snapshot["result"].get(series.field)
    if not isinstance(value, int | float):
        # Below the page's price floor the calculator shows no figure at all,
        # and a piece claiming one would be inventing it. Refusing here is the
        # honest failure: the caller drops the generation rather than shipping
        # a number the page will not reproduce.
        raise ValueError(
            f"the calculator has no {series.field} for rent ${rent:,}; "
            "there is no figure for this piece to state"
        )

    filled = {
        "rent": f"${rent:,}",
        "savings": f"${SAVINGS:,}",
        "figure": _money(value),
    }
    english = language is ContentLanguage.EN
    screen = series.screen_en if english else series.screen_es

    return Plan(
        topic=Topic(
            key=f"{series.key}_{rent}",
            brief_en=series.brief_en.format(**filled),
            brief_es=series.brief_es.format(**filled),
            audience=series.audience,
        ),
        check={
            "scenarios": [{"inputs": dict(inputs)}],
            # Which rail made this, and it is load-bearing rather than
            # bookkeeping. `calculated_index` counts through it, and counting
            # every piece that merely HAS a check instead would have started
            # this rail at index 8 — because eight pieces were stamped by hand
            # on 15-sep-2026 — which is `price_ceiling` at $2,600: word for
            # word piece 42, scheduled for 18-sep on all three channels, with
            # 43, 44 and 45 behind it. The first four things this was built to
            # produce would have been copies of what was already in the queue.
            #
            # `unexplained_figures` reads `scenarios` and `literal` and ignores
            # everything else, so an extra key costs nothing at the gate.
            "source": CALCULATED_SOURCE,
            "series": series.key,
            "note": (
                "Computed at generation time by content_calculated from "
                "calculator.build_snapshot under the page's default "
                f"assumptions; the piece states {series.field} to the nearest "
                "thousand."
            ),
        },
        screen=tuple(line.format(**filled) for line in screen),  # type: ignore[arg-type]
        figure=to_thousand(value),
        rent=rent,
    )


def plan_from_check(
    check: dict[str, Any] | None, language: ContentLanguage
) -> Plan | None:
    """The `Plan` that produced this `calculator_check`, or None.

    `plan_for` takes an index and nothing else, so a stored piece could not be
    put back on its own rail: the index is not written down anywhere. It does
    not have to be. The rotation is a pure function of `(series, rent)` and
    both are in the check — the series key because `calculated_index` counts
    through it, the rent because the gate recomputes the figure from the
    inputs — so the index is recoverable by asking where those two sit in the
    tuples they came from.

    This is what makes a REWRITE safe on the calculated rail. Without it a
    correction would rebuild the draft with `plan=None`, and three things would
    quietly change at once: the sign-off would become the seller's rather than
    the renter's, the link would lose the seed that opens the page on the same
    number the video says, and the on-screen figure would go back to being
    whatever the model felt like writing. That is the $21,000-against-$52,210
    defect, re-entering through the door built to repair it.

    None means "do not rewrite this one" and the caller sends it to a person.
    Returned for a check from another rail, a rent or a series that no longer
    exists, and a figure the calculator will not state today.
    """
    if not isinstance(check, dict) or check.get("source") != CALCULATED_SOURCE:
        return None
    scenarios = check.get("scenarios")
    inputs = (
        scenarios[0].get("inputs")
        if isinstance(scenarios, list) and scenarios and isinstance(scenarios[0], dict)
        else None
    )
    rent = inputs.get("rent") if isinstance(inputs, dict) else None
    keys = [series.key for series in SERIES]
    if check.get("series") not in keys or rent not in RENTS:
        return None
    index = keys.index(str(check["series"])) * len(RENTS) + RENTS.index(int(rent))
    try:
        return plan_for(index, language)
    except ValueError:
        # The calculator has no figure for this rent any more. A piece cannot
        # be rewritten around a number that no longer exists.
        return None


def scene_fields(plan: Plan) -> list[tuple[str, str]]:
    """`(visual_prompt, on_screen_text)` for each of the four shots.

    The screen text comes from the plan and never from the model. The figure
    the owner caught was ON SCREEN, and `_SYSTEM` already keeps the URL out of
    the model's hands for the weaker reason that it might drop a character.
    """
    return [
        (VISUALS[i % len(VISUALS)], line) for i, line in enumerate(plan.screen)
    ]
