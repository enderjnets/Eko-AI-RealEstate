"""What the generated pieces talk about, and the order they talk about it in.

Deliberately not property listings. Showing a property in a video needs the MLS
feed and image rights sorted out first, and neither is; until then the safe
material is the process and the market — the questions every Denver buyer and
seller actually asks, which cost nothing to be right about.

The rotation is driven by how many generated pieces the organisation already
has, not by the date: it cannot skip a topic when a day's generation fails, two
orgs are not in lockstep, and a test can predict topic N without freezing time.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentKind, ContentPiece

SELLER = "seller"
BUYER = "buyer"
BOTH = "both"


@dataclass(frozen=True)
class Topic:
    key: str
    # What the piece should get across, handed to the writer as the brief.
    brief_en: str
    brief_es: str
    # Who the piece is FOR. Declared rather than inferred from the brief,
    # because the balance of this rotation is a business decision and a
    # business decision that only exists inside prose cannot be tested.
    #
    # It is tested: this channel exists to reach people thinking about SELLING
    # a home with this agency, and the rotation used to be 6 buyer topics to 1
    # seller. Generating correct content for the wrong audience spends LLM
    # quota to grow the wrong list.
    audience: str


TOPICS: tuple[Topic, ...] = (
    Topic(
        key="what_x_buys_today",
        brief_en=(
            "What a typical budget actually buys in Denver right now: frame it "
            "as expectations versus reality, neighborhood-agnostic, no prices "
            "invented — speak in ranges and 'depends on'."
        ),
        brief_es=(
            "Qué compra de verdad un presupuesto típico en Denver ahora mismo: "
            "expectativas contra realidad, sin atarlo a un barrio, sin inventar "
            "precios — hablar en rangos y en 'depende'."
        ),
        audience=BUYER,
    ),
    Topic(
        key="inspection",
        brief_en=(
            "What a home inspection is for and what it typically catches — "
            "from BOTH chairs: what a buyer is deciding when they consider "
            "waiving it, and what a seller can expect it to surface about "
            "their own house before it does."
        ),
        brief_es=(
            "Para qué sirve la inspección y qué suele encontrar — desde las "
            "DOS sillas: qué decide quien compra cuando se plantea renunciar "
            "a ella, y qué puede esperar quien vende que saque a la luz sobre "
            "su propia casa antes de que lo haga."
        ),
        audience=BOTH,
    ),
    Topic(
        key="offer_to_close",
        brief_en=(
            "The road from accepted offer to closing: the steps, roughly how "
            "long each takes, and where deals usually wobble — told so that "
            "the person SELLING recognises their own side of it, not only the "
            "buyer waiting for keys."
        ),
        brief_es=(
            "El camino de la oferta aceptada al cierre: los pasos, cuánto "
            "suele tardar cada uno, y dónde se suelen torcer las operaciones "
            "— contado de modo que quien VENDE reconozca su lado, no solo el "
            "comprador que espera las llaves."
        ),
        audience=BOTH,
    ),
    Topic(
        key="earnest_money",
        brief_en=(
            "Earnest money explained: what it is, when it is at risk, and the "
            "contingencies that protect it."
        ),
        brief_es=(
            "El depósito de seriedad (earnest money): qué es, cuándo está en "
            "riesgo, y qué contingencias lo protegen."
        ),
        audience=BUYER,
    ),
    Topic(
        key="preapproval",
        brief_en=(
            "Pre-qualified versus pre-approved, why sellers care, and what a "
            "loan estimate actually tells you."
        ),
        brief_es=(
            "Precalificado contra preaprobado, por qué le importa al "
            "vendedor, y qué dice de verdad un loan estimate."
        ),
        audience=BUYER,
    ),
    Topic(
        key="first_week_selling",
        brief_en=(
            "The first week of selling a home: what to fix, what to leave, "
            "and why the first weekend's showings matter most."
        ),
        brief_es=(
            "La primera semana de vender una casa: qué arreglar, qué dejar "
            "como está, y por qué las visitas del primer fin de semana son "
            "las que más pesan."
        ),
        audience=SELLER,
    ),
    Topic(
        key="market_pulse",
        brief_en=(
            "How to read the Denver market without a crystal ball: days on "
            "market and inventory, and what they mean for someone deciding "
            "whether to LIST this month as much as for someone buying. No "
            "predictions, no invented numbers."
        ),
        brief_es=(
            "Cómo leer el mercado de Denver sin bola de cristal: días en "
            "mercado e inventario, y qué significan tanto para quien decide "
            "si SACAR SU CASA al mercado este mes como para quien compra. Sin "
            "predicciones y sin inventar números."
        ),
        audience=BOTH,
    ),
    # ── Los cinco del vendedor. Son las preguntas que se hace alguien que
    # todavía NO ha decidido vender, que es exactamente a quien queremos
    # llegar: quien ya decidió, ya está hablando con un agente.
    Topic(
        key="what_is_my_home_worth",
        brief_en=(
            "What actually decides what a Denver home is worth today — recent "
            "comparable sales, condition, and how the first two weeks on "
            "market price a house whether the seller likes it or not. Explain "
            "why an online estimate and an appraisal are different animals. "
            "No valuation of any specific home and no invented figures."
        ),
        brief_es=(
            "Qué decide de verdad lo que vale una casa en Denver hoy: ventas "
            "comparables recientes, estado, y cómo las dos primeras semanas "
            "en el mercado le ponen precio a una casa le guste o no al que "
            "vende. Explicar por qué una estimación de internet y una "
            "tasación son cosas distintas. Sin valorar ninguna casa concreta "
            "y sin inventar cifras."
        ),
        audience=SELLER,
    ),
    Topic(
        key="fix_before_listing",
        brief_en=(
            "What is worth fixing before listing and what is not. The honest "
            "version: most renovations do not return what they cost, and the "
            "cheap work — paint, light, clutter, the front door — usually "
            "moves the needle more than the expensive work. Speak in "
            "categories, never in guaranteed returns."
        ),
        brief_es=(
            "Qué merece la pena arreglar antes de sacar la casa al mercado y "
            "qué no. La versión honesta: la mayoría de las reformas no "
            "devuelven lo que cuestan, y lo barato — pintura, luz, quitar "
            "trastos, la puerta de entrada — suele mover más la aguja que lo "
            "caro. Hablar por categorías, jamás de retornos garantizados."
        ),
        audience=SELLER,
    ),
    Topic(
        key="true_cost_of_selling",
        brief_en=(
            "What selling a home actually costs, line by line: commissions, "
            "title and closing costs, concessions, the repairs that come out "
            "of inspection, and the mortgage payments made while it sits. The "
            "point is that the number in the seller's head is the sale price "
            "and the number that matters is what lands in their account. "
            "Ranges and 'it depends', never invented percentages."
        ),
        brief_es=(
            "Lo que cuesta de verdad vender una casa, línea por línea: "
            "comisiones, título y gastos de cierre, concesiones, los arreglos "
            "que salen de la inspección, y las cuotas de hipoteca mientras "
            "está en venta. La idea: el número que tiene en la cabeza quien "
            "vende es el precio de venta, y el número que importa es lo que "
            "le llega a la cuenta. Rangos y 'depende', nunca porcentajes "
            "inventados."
        ),
        audience=SELLER,
    ),
    Topic(
        key="pricing_mistakes",
        brief_en=(
            "Why pricing high 'to leave room for negotiation' usually ends in "
            "less money, not more: the first two weeks carry the traffic, a "
            "price cut reads as a problem to buyers, and days on market is "
            "public. Describe the mechanism, do not promise an outcome."
        ),
        brief_es=(
            "Por qué poner un precio alto 'para dejar margen de negociación' "
            "suele acabar en menos dinero y no en más: las dos primeras "
            "semanas se llevan las visitas, una bajada de precio se lee como "
            "un problema, y los días en mercado son públicos. Describir el "
            "mecanismo, no prometer un resultado."
        ),
        audience=SELLER,
    ),
    Topic(
        key="sell_and_buy_at_once",
        brief_en=(
            "Selling and buying at the same time in Denver: the orders it can "
            "happen in, what each one risks, and the plain question nobody "
            "wants to ask out loud — where do you sleep if the timing slips. "
            "No financial advice and no product recommendations."
        ),
        brief_es=(
            "Vender y comprar a la vez en Denver: en qué órdenes se puede "
            "hacer, qué arriesga cada uno, y la pregunta incómoda que nadie "
            "quiere hacer en voz alta — dónde duermes si los plazos se "
            "descuadran. Sin consejo financiero y sin recomendar productos."
        ),
        audience=SELLER,
    ),
)


async def rotation_index(db: AsyncSession) -> int:
    """How many generated pieces this organisation already has.

    The number every rotation in this product turns on — the topic, and since
    v0.67.9 the spoken sign-off. Extracted so the second one reuses the count
    rather than issuing the same query again under a different name.
    """
    return (
        await db.execute(
            select(func.count())
            .select_from(ContentPiece)
            .where(ContentPiece.kind == ContentKind.GENERATED)
        )
    ).scalar_one()


async def next_topic(db: AsyncSession) -> Topic:
    """The topic after the last one this organisation generated."""
    return TOPICS[await rotation_index(db) % len(TOPICS)]
