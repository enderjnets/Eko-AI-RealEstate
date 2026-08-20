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


@dataclass(frozen=True)
class Topic:
    key: str
    # What the piece should get across, handed to the writer as the brief.
    brief_en: str
    brief_es: str


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
    ),
    Topic(
        key="inspection",
        brief_en=(
            "What a home inspection is for, what it typically catches, and why "
            "waiving it to win a bid is a decision to make with open eyes."
        ),
        brief_es=(
            "Para qué sirve la inspección de la casa, qué suele encontrar, y "
            "por qué renunciar a ella para ganar una oferta es una decisión "
            "que se toma con los ojos abiertos."
        ),
    ),
    Topic(
        key="offer_to_close",
        brief_en=(
            "The road from accepted offer to keys in hand: the steps, roughly "
            "how long each takes, and where deals usually wobble."
        ),
        brief_es=(
            "El camino de la oferta aceptada a las llaves en la mano: los "
            "pasos, cuánto suele tardar cada uno, y dónde se suelen torcer "
            "las operaciones."
        ),
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
    ),
    Topic(
        key="market_pulse",
        brief_en=(
            "How to read the Denver market without a crystal ball: days on "
            "market, inventory, and what they mean for a buyer this month. "
            "No predictions, no invented numbers."
        ),
        brief_es=(
            "Cómo leer el mercado de Denver sin bola de cristal: días en "
            "mercado, inventario, y qué significan para quien compra este "
            "mes. Sin predicciones y sin inventar números."
        ),
    ),
)


async def next_topic(db: AsyncSession) -> Topic:
    """The topic after the last one this organisation generated."""
    generated_so_far = (
        await db.execute(
            select(func.count())
            .select_from(ContentPiece)
            .where(ContentPiece.kind == ContentKind.GENERATED)
        )
    ).scalar_one()
    return TOPICS[generated_so_far % len(TOPICS)]
