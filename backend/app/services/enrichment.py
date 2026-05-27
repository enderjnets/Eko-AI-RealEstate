"""Lead enrichment — turn a freshly imported discovery lead into something a
realtor can act on.

We have no extra paid data source, so enrichment is LLM reasoning over what the
discovery sources already gave us (name, category, source, website, address): a
normalized business type, how a realtor should view the contact (referral
partner / vendor / prospect), a one-line summary, a suggested outreach angle,
and a flag for missing contact info. Stored under `lead.meta["enrichment"]`.

Graceful by design (mirrors classifier.py): on LLM failure or invalid JSON we
record `status="failed"` and never raise — an enrichment pass must never lose a
lead it already imported.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lead, LeadIntent
from app.services.llm import LLMUnavailable, generate_reply
from app.services.scoring import score_tier

MAX_ENRICH_ATTEMPTS = 3

log = logging.getLogger(__name__)

_PARTNER_TYPES = {"referral_partner", "vendor", "prospect", "competitor", "other"}
_INTENTS = {"rent", "buy", "valuation", "other"}

# Score weight per partner_type — a referral partner / live prospect is worth more
# of the realtor's time than a vendor or competitor.
_PARTNER_WEIGHT = {"referral_partner": 35, "prospect": 32, "vendor": 18, "competitor": 6, "other": 12}

_SYSTEM = """Sos un asistente de prospección para un agente inmobiliario en EEUU.
Te paso un negocio/contacto encontrado por el módulo de descubrimiento. Inferí SOLO
a partir del nombre, categoría, fuente y datos dados — NO inventes teléfonos, emails
ni hechos específicos que no estén.

Devolvé un JSON con exactamente estas claves:
- "business_type": string corto normalizado (ej "Mortgage broker", "Home inspector", "Real estate agent", "Title company", "Property manager").
- "partner_type": uno de: "referral_partner" (puede referir clientes), "vendor" (servicio que el realtor contrata), "prospect" (posible cliente comprador/vendedor), "competitor", "other".
- "intent": el mejor encaje de necesidad inmobiliaria si este contacto pudiera ser un CLIENTE: "buy", "rent", "valuation"; si es un partner/proveedor/competidor que NO es cliente, usá "other".
- "relevance": entero 0-10 — qué tan valioso es este contacto para el pipeline de un realtor (10 = altísimo, p.ej. un broker hipotecario que refiere; 0 = irrelevante).
- "summary": una frase (máx 140 chars) describiendo qué es y por qué le sirve a un realtor.
- "outreach_angle": una frase con el ángulo de primer contacto sugerido.
- "tags": array de 1-4 strings cortos en minúscula."""


class Enrichment(BaseModel):
    business_type: str | None = None
    partner_type: str = "other"
    intent: str = "other"
    relevance: int = 5
    summary: str | None = None
    outreach_angle: str | None = None
    tags: list[str] = []


def _coerce(raw: dict[str, Any]) -> Enrichment:
    pt = str(raw.get("partner_type") or "other").strip().lower()
    if pt not in _PARTNER_TYPES:
        pt = "other"
    raw["partner_type"] = pt
    it = str(raw.get("intent") or "other").strip().lower()
    raw["intent"] = it if it in _INTENTS else "other"
    try:
        raw["relevance"] = max(0, min(10, int(raw.get("relevance", 5))))
    except (TypeError, ValueError):
        raw["relevance"] = 5
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    raw["tags"] = [str(t).strip().lower() for t in tags if str(t).strip()][:4]
    return Enrichment(**raw)


def discovery_score(partner_type: str, relevance: int, *, has_contact: bool, has_website: bool) -> tuple[int, dict]:
    """A 0-100 priority score for a prospected (no-conversation) lead, built from
    enrichment signals so it ranks alongside conversation-scored leads."""
    comps = {
        "partner_type": _PARTNER_WEIGHT.get(partner_type, 12),
        "relevance": max(0, min(10, relevance)) * 2,  # 0-20
        "contact": 25 if has_contact else 0,
        "website": 10 if has_website else 0,
    }
    base = sum(comps.values())
    score = max(0, min(100, base))
    return score, {
        "components": comps,
        "base": base,
        "status_gate": 1.0,
        "status": "new",
        "tier": score_tier(score),
        "source": "discovery_enrichment",
    }


def _context(lead: Lead) -> str:
    m = lead.meta or {}
    parts = [f"Nombre: {lead.name or '(sin nombre)'}"]
    if m.get("category"):
        parts.append(f"Categoría: {m['category']}")
    if m.get("source"):
        parts.append(f"Fuente: {m['source']}")
    if m.get("website"):
        parts.append(f"Web: {m['website']}")
    if m.get("address"):
        parts.append(f"Dirección: {m['address']}")
    if lead.zone:
        parts.append(f"Ciudad: {lead.zone}")
    return "\n".join(parts)


async def enrich_lead(lead: Lead, db: AsyncSession) -> dict[str, Any]:
    """Enrich one lead in place (writes lead.meta['enrichment'] + commits)."""
    meta = dict(lead.meta or {})
    contact_missing = bool(meta.get("synthetic_identifier")) or not (meta.get("phone") or meta.get("email"))
    attempts = ((meta.get("enrichment") or {}).get("attempts") or 0) + 1

    enrichment: dict[str, Any]
    try:
        result = await generate_reply(
            [{"role": "user", "content": _context(lead)}],
            system=_SYSTEM,
            json_mode=True,
            temperature=0.2,
            max_tokens=400,
        )
        match = re.search(r"\{.*\}", result.text, re.DOTALL)
        if not match:
            raise ValueError("no JSON object in LLM output")
        parsed = _coerce(json.loads(match.group(0)))
        enrichment = parsed.model_dump()
        enrichment["status"] = "ok"
        # Classify + score so the lead shows an intent badge + a 🔥/🟡 tier like
        # conversation leads (it has no chat history to run the normal classifier on).
        lead.intent = LeadIntent(parsed.intent) if parsed.intent in {i.value for i in LeadIntent} else LeadIntent.OTHER
        score, breakdown = discovery_score(
            parsed.partner_type, parsed.relevance,
            has_contact=not contact_missing, has_website=bool(meta.get("website")),
        )
        lead.score = score
        lead.score_breakdown = breakdown
        enrichment["score"] = score
        enrichment["tier"] = breakdown["tier"]
    except (LLMUnavailable, ValueError, json.JSONDecodeError, ValidationError) as exc:
        log.warning("Enrichment failed for lead %s: %s", lead.id, exc)
        enrichment = {"status": "failed", "error": str(exc)[:200], "partner_type": "other", "tags": []}

    enrichment["contact_missing"] = contact_missing
    enrichment["attempts"] = attempts
    enrichment["enriched_at"] = datetime.now(UTC).isoformat()
    meta["enrichment"] = enrichment
    lead.meta = meta
    await db.commit()
    await db.refresh(lead)
    return enrichment


async def enrich_pending_leads(db: AsyncSession, *, limit: int = 10) -> dict[str, int]:
    """Backfill / safety-net: enrich discovery leads that aren't classified yet.

    A classified discovery lead has score > 0 (discovery_score floors at ~12); an
    unclassified one sits at 0 — whether it predates classification, was skipped by
    dedupe on re-import, or the frontend enrichment loop never reached it. This runs
    server-side (periodic worker + manual trigger), so enrichment never depends on
    the browser staying open. Failed leads are retried up to MAX_ENRICH_ATTEMPTS.
    """
    rows = (
        await db.execute(
            select(Lead)
            .where(Lead.score == 0)
            .where(Lead.meta["discovery"].astext == "true")
            .order_by(Lead.id.desc())
            .limit(limit * 4)
        )
    ).scalars().all()

    enriched = failed = 0
    for lead in rows:
        enr = (lead.meta or {}).get("enrichment") or {}
        if enr.get("status") != "ok" and (enr.get("attempts") or 0) >= MAX_ENRICH_ATTEMPTS:
            continue  # give up on a persistently failing lead
        out = await enrich_lead(lead, db)
        if out.get("status") == "ok":
            enriched += 1
        else:
            failed += 1
        if enriched >= limit:
            break
    return {"enriched": enriched, "failed": failed, "scanned": len(rows)}
