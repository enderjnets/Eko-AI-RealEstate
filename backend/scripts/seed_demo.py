#!/usr/bin/env python3
"""Seed realistic demo data so the public demo URL looks alive.

Populates a fictional USA real-estate office ("Sunset Realty Group", Miami)
with a handful of bilingual leads, their WhatsApp/email conversations, and a
couple of scheduled/completed visits. Used to make `inmo-demo.ekoaiautomation.com`
(Phase 6) compelling for sales without exposing any real customer data.

Every seeded lead carries `meta={"demo": true}`, so `--reset` can find and
delete exactly the demo rows (cascading to their conversations / messages /
visits) without touching anything a live demo visitor might have created.

Usage:
  docker compose exec backend python scripts/seed_demo.py            # idempotent: reseeds
  docker compose exec backend python scripts/seed_demo.py --reset    # wipe demo rows only
  docker compose exec backend python scripts/seed_demo.py --keep-settings  # don't touch branding
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# Allow `python scripts/seed_demo.py` from the backend root: Python puts the
# script's own dir on sys.path, not the package root, so add it explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.db.base import dispose_engine, get_session_factory  # noqa: E402
from app.models import (  # noqa: E402
    AgentSettings,
    Conversation,
    ConversationStatus,
    Lead,
    LeadIntent,
    LeadStatus,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
    Visit,
    VisitStatus,
)

NOW = datetime.now(UTC)

DEMO_BRANDING = {
    "agency_name": "Sunset Realty Group",
    "agency_phone": "+1-305-555-0142",
    "agent_persona": (
        "You are the virtual assistant for Sunset Realty Group, a boutique real-estate "
        "office in Miami, FL. You answer leads 24/7 in a warm, professional tone. Your job "
        "is to capture leads, classify their intent (rent / buy / valuation), gather their "
        "target neighborhood and budget, and book showings when appropriate. Never invent "
        "details about a listing; if you don't know, say so and offer to connect a human agent. "
        "Reply in the language the lead writes in (English or Spanish)."
    ),
    "greeting_template": (
        "Hi! I'm the assistant at {agency_name}. How can I help you today? Tell me what "
        "you're looking for (rent, buy, or a home valuation) and which area of Miami."
    ),
    "languages": ["en", "es"],
}


def _mins(base: datetime, m: int) -> datetime:
    return base + timedelta(minutes=m)


# (name, identifier, channel, intent, status, zone, budget_min, budget_max,
#  property_type, urgency, human_takeover, hours_ago, turns[(sender, text, subject?)])
DEMO_LEADS: list[dict] = [
    {
        "name": "Jessica Romero",
        "phone": "+13055550111",
        "channel": "whatsapp",
        "intent": LeadIntent.BUY,
        "status": LeadStatus.VISITING,
        "zone": "Brickell",
        "budget_min": Decimal("650000"),
        "budget_max": Decimal("850000"),
        "property_type": "condo",
        "urgency": "high",
        "hours_ago": 3,
        "turns": [
            (MessageSender.LEAD, "Hi, I'm looking for a 2-bed condo in Brickell, budget up to 850k. Anything available?"),
            (MessageSender.AGENT, "Great to hear from you! Brickell is a fantastic choice. To match you with the right units — are you looking for a high-floor view, and do you need parking included?"),
            (MessageSender.LEAD, "High floor with a bay view ideally, and yes 2 parking spots."),
            (MessageSender.AGENT, "Perfect. I have a couple of high-floor 2-bed units with bay views and 2 spaces. Would you like to schedule a showing this week?"),
            (MessageSender.LEAD, "Yes! Thursday afternoon works."),
        ],
    },
    {
        "name": "Marcus Lee",
        "phone": "marcus.lee@gmail.com",
        "channel": "email",
        "intent": LeadIntent.BUY,
        "status": LeadStatus.QUALIFIED,
        "zone": "Coral Gables",
        "budget_min": Decimal("1000000"),
        "budget_max": Decimal("1300000"),
        "property_type": "single_family",
        "urgency": "medium",
        "hours_ago": 26,
        "turns": [
            (MessageSender.LEAD, "Hello, my wife and I are relocating to Miami and interested in single-family homes in Coral Gables in the $1–1.3M range, 4 bedrooms. Could you send some options?", "Relocating to Coral Gables — home search"),
            (MessageSender.AGENT, "Welcome to Miami! Coral Gables has wonderful family neighborhoods. I'd love to put together a shortlist. A few quick questions: do you need a pool, and what's your ideal move-in timeline?", "Re: Relocating to Coral Gables — home search"),
            (MessageSender.LEAD, "A pool would be a plus. We'd like to move by August.", "Re: Relocating to Coral Gables — home search"),
        ],
    },
    {
        "name": "Carla Méndez",
        "phone": "+13055550133",
        "channel": "whatsapp",
        "intent": LeadIntent.RENT,
        "status": LeadStatus.NEW,
        "zone": "Doral",
        "budget_min": Decimal("2400"),
        "budget_max": Decimal("2900"),
        "property_type": "apartment",
        "urgency": "high",
        "hours_ago": 1,
        "turns": [
            (MessageSender.LEAD, "Hola, busco apartamento en alquiler en Doral, 2 habitaciones, hasta $2,900 al mes. ¿Tienen algo disponible?"),
            (MessageSender.AGENT, "¡Hola Carla! Claro que sí. En Doral tenemos varias opciones de 2 habitaciones en ese rango. ¿Para cuándo necesitarías mudarte y prefieres con gimnasio/piscina en el edificio?"),
            (MessageSender.LEAD, "Para el mes que viene, y sí me encantaría con gimnasio."),
        ],
    },
    {
        "name": "David Thompson",
        "phone": "+13055550155",
        "channel": "whatsapp",
        "intent": LeadIntent.VALUATION,
        "status": LeadStatus.QUALIFIED,
        "zone": "Wynwood",
        "budget_min": None,
        "budget_max": None,
        "property_type": "loft",
        "urgency": "low",
        "hours_ago": 50,
        "turns": [
            (MessageSender.LEAD, "Hey, I own a loft in Wynwood and I'm thinking about selling. Can you tell me what it might be worth?"),
            (MessageSender.AGENT, "Absolutely, happy to help with a valuation. Wynwood has appreciated a lot. Could you share the square footage, number of bedrooms, and the building or street? I'll prepare a comparative market analysis."),
            (MessageSender.LEAD, "It's 1,150 sqft, 1 bed 1.5 bath, on NW 2nd Ave."),
            (MessageSender.AGENT, "Thanks David! Based on recent Wynwood comps, units like yours have been trading around $620–$680k. I'll have one of our agents prepare a precise CMA and reach out. Sound good?"),
        ],
    },
    {
        "name": "Priya Patel",
        "phone": "priya.invests@outlook.com",
        "channel": "email",
        "intent": LeadIntent.BUY,
        "status": LeadStatus.QUALIFIED,
        "zone": "Edgewater",
        "budget_min": Decimal("2000000"),
        "budget_max": Decimal("3500000"),
        "property_type": "multi_unit",
        "urgency": "medium",
        "human_takeover": True,
        "hours_ago": 8,
        "turns": [
            (MessageSender.LEAD, "I'm an investor looking for small multi-unit buildings in Edgewater / Edgewater-adjacent, $2M–$3.5M, ideally value-add. Do you handle income properties?", "Investor — multi-unit in Edgewater"),
            (MessageSender.AGENT, "We do work with investors on income properties. To tailor the search: are you targeting a specific cap rate, and is this a 1031 exchange with a deadline?", "Re: Investor — multi-unit in Edgewater"),
            (MessageSender.HUMAN, "Hi Priya, this is Elena, the owner of Sunset Realty — I'll personally handle your search given the deal size. Let's set up a call this week.", "Re: Investor — multi-unit in Edgewater"),
        ],
    },
    {
        "name": "Sofía Gutiérrez",
        "phone": "+13055550177",
        "channel": "whatsapp",
        "intent": LeadIntent.RENT,
        "status": LeadStatus.POST_VISIT,
        "zone": "Little Havana",
        "budget_min": Decimal("1800"),
        "budget_max": Decimal("2200"),
        "property_type": "apartment",
        "urgency": "medium",
        "hours_ago": 96,
        "turns": [
            (MessageSender.LEAD, "Hola, vi un apartamento de ustedes en Little Havana. ¿Puedo visitarlo?"),
            (MessageSender.AGENT, "¡Hola Sofía! Por supuesto. Tengo disponibilidad esta semana. ¿Te viene bien el viernes a las 11:00?"),
            (MessageSender.LEAD, "Sí, perfecto. Nos vemos el viernes."),
            (MessageSender.AGENT, "¡Genial! Confirmado para el viernes a las 11:00. Te enviaré la dirección exacta. ¡Hasta pronto!"),
        ],
    },
]

# (lead phone, status, days_from_now, duration, address, notes)
DEMO_VISITS: list[tuple[str, VisitStatus, int, int, str, str]] = [
    ("+13055550111", VisitStatus.SCHEDULED, 2, 45, "1300 Brickell Bay Dr #4502, Miami, FL 33131", "High-floor 2-bed, bay view. Bring parking garage access."),
    ("+13055550177", VisitStatus.COMPLETED, -2, 30, "1450 SW 8th St #3, Miami, FL 33135", "Lead liked the unit; follow up on application."),
]


async def _wipe_demo(session, *, keep_settings: bool) -> int:
    rows = (await session.execute(select(Lead))).scalars().all()
    demo = [l for l in rows if isinstance(l.meta, dict) and l.meta.get("demo")]
    for lead in demo:
        await session.delete(lead)  # cascades to conversations/messages/visits
    if not keep_settings:
        cfg = (await session.execute(select(AgentSettings))).scalar_one_or_none()
        if cfg is not None:
            await session.delete(cfg)
    await session.commit()
    return len(demo)


async def _seed(session, *, keep_settings: bool) -> None:
    if not keep_settings:
        cfg = (await session.execute(select(AgentSettings))).scalar_one_or_none()
        if cfg is None:
            cfg = AgentSettings()
            session.add(cfg)
        for k, v in DEMO_BRANDING.items():
            setattr(cfg, k, v)
        await session.flush()

    phone_to_lead: dict[str, Lead] = {}

    for spec in DEMO_LEADS:
        started = NOW - timedelta(hours=spec["hours_ago"])
        lead = Lead(
            phone=spec["phone"],
            name=spec["name"],
            status=spec["status"],
            intent=spec["intent"],
            zone=spec.get("zone"),
            budget_min=spec.get("budget_min"),
            budget_max=spec.get("budget_max"),
            property_type=spec.get("property_type"),
            urgency=spec.get("urgency"),
            human_takeover=spec.get("human_takeover", False),
            meta={"demo": True},
        )
        session.add(lead)
        await session.flush()
        phone_to_lead[spec["phone"]] = lead

        conv = Conversation(
            lead_id=lead.id,
            channel=spec["channel"],
            status=ConversationStatus.ACTIVE,
            started_at=started,
            last_at=started,
        )
        session.add(conv)
        await session.flush()

        last_ts = started
        for i, turn in enumerate(spec["turns"]):
            sender = turn[0]
            text = turn[1]
            subject = turn[2] if len(turn) > 2 else None
            inbound = sender == MessageSender.LEAD
            ts = _mins(started, i * 4)
            last_ts = ts
            session.add(
                Message(
                    conversation_id=conv.id,
                    direction=MessageDirection.INBOUND if inbound else MessageDirection.OUTBOUND,
                    sender=sender,
                    content=text,
                    external_id=f"demo-{spec['channel']}-{lead.id}-{i}",
                    delivery_status=MessageStatus.DELIVERED if inbound else MessageStatus.SENT,
                    subject=subject if spec["channel"] == "email" else None,
                    llm_provider=None if inbound or sender == MessageSender.HUMAN else "kimi",
                    llm_model=None if inbound or sender == MessageSender.HUMAN else "kimi-for-coding",
                    created_at=ts,
                )
            )

        conv.last_at = last_ts
        lead.last_message_at = last_ts

    await session.flush()

    for phone, status, days, duration, address, notes in DEMO_VISITS:
        lead = phone_to_lead.get(phone)
        if lead is None:
            continue
        when = NOW + timedelta(days=days)
        when = when.replace(hour=15, minute=0, second=0, microsecond=0)
        session.add(
            Visit(
                lead_id=lead.id,
                calendar_provider="calcom",
                external_booking_id=f"calcom-sim-demo-{lead.id}",
                status=status,
                scheduled_at=when,
                duration_minutes=duration,
                timezone="America/New_York",
                property_address=address,
                notes=notes,
            )
        )

    await session.commit()


async def main() -> int:
    p = argparse.ArgumentParser(description="Seed / reset the public-demo dataset.")
    p.add_argument("--reset", action="store_true", help="delete demo rows and exit (no reseed)")
    p.add_argument("--keep-settings", action="store_true", help="don't touch AgentSettings branding")
    args = p.parse_args()

    # Bind the demo org: without it, default-deny RLS made every seeded row
    # fail the WITH CHECK and the script exited 1 on agent_settings.
    from app.models.organization import DEMO_ORG_ID
    from app.services.tenant_context import set_org_id

    set_org_id(DEMO_ORG_ID)
    Session = get_session_factory()
    try:
        async with Session() as session:
            # Always wipe demo rows first so seeding is idempotent (re-runnable).
            wiped = await _wipe_demo(session, keep_settings=args.keep_settings)
            if wiped:
                print(f"🧹 removed {wiped} existing demo lead(s) + their conversations/visits")
            if args.reset:
                print("✅ reset complete (no reseed — --reset was passed)")
                return 0

        async with Session() as session:
            await _seed(session, keep_settings=args.keep_settings)

        async with Session() as session:
            total = len((await session.execute(select(Lead))).scalars().all())
            visits = len((await session.execute(select(Visit))).scalars().all())
        print(f"🌱 seeded {len(DEMO_LEADS)} demo leads + {len(DEMO_VISITS)} visits")
        print(f"   branding: {'kept existing' if args.keep_settings else DEMO_BRANDING['agency_name']}")
        print(f"   DB now has {total} leads, {visits} visits total")
        print("   open the dashboard /leads to see them.")
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
