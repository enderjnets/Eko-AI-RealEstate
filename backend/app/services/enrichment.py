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
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lead
from app.services.llm import LLMUnavailable, generate_reply

log = logging.getLogger(__name__)

_PARTNER_TYPES = {"referral_partner", "vendor", "prospect", "competitor", "other"}

_SYSTEM = """Sos un asistente de prospección para un agente inmobiliario en EEUU.
Te paso un negocio/contacto encontrado por el módulo de descubrimiento. Inferí SOLO
a partir del nombre, categoría, fuente y datos dados — NO inventes teléfonos, emails
ni hechos específicos que no estén.

Devolvé un JSON con exactamente estas claves:
- "business_type": string corto normalizado (ej "Mortgage broker", "Home inspector", "Real estate agent", "Title company", "Property manager").
- "partner_type": uno de: "referral_partner" (puede referir clientes), "vendor" (servicio que el realtor contrata), "prospect" (posible cliente comprador/vendedor), "competitor", "other".
- "summary": una frase (máx 140 chars) describiendo qué es y por qué le sirve a un realtor.
- "outreach_angle": una frase con el ángulo de primer contacto sugerido.
- "tags": array de 1-4 strings cortos en minúscula."""


class Enrichment(BaseModel):
    business_type: str | None = None
    partner_type: str = "other"
    summary: str | None = None
    outreach_angle: str | None = None
    tags: list[str] = []


def _coerce(raw: dict[str, Any]) -> Enrichment:
    pt = str(raw.get("partner_type") or "other").strip().lower()
    if pt not in _PARTNER_TYPES:
        pt = "other"
    raw["partner_type"] = pt
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    raw["tags"] = [str(t).strip().lower() for t in tags if str(t).strip()][:4]
    return Enrichment(**raw)


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
    except (LLMUnavailable, ValueError, json.JSONDecodeError, ValidationError) as exc:
        log.warning("Enrichment failed for lead %s: %s", lead.id, exc)
        enrichment = {"status": "failed", "error": str(exc)[:200], "partner_type": "other", "tags": []}

    enrichment["contact_missing"] = contact_missing
    enrichment["enriched_at"] = datetime.now(UTC).isoformat()
    meta["enrichment"] = enrichment
    lead.meta = meta
    await db.commit()
    await db.refresh(lead)
    return enrichment
