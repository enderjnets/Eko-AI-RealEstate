"""Intent classifier — turns a WhatsApp message history into structured fields.

Returns an `IntentResult` Pydantic model. If the LLM returns invalid JSON or
fields outside the schema, we degrade gracefully to `intent=OTHER` and log the
raw response so it can be inspected later — a lead is never lost over a parse
failure.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.models import LeadIntent
from app.services.llm import LLMUnavailable, generate_reply

log = logging.getLogger(__name__)


class IntentEntities(BaseModel):
    zone: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    property_type: str | None = None  # apartment | house | commercial | land | other
    urgency: str | None = None        # immediate | weeks | months | exploring

    @field_validator("budget_min", "budget_max", mode="before")
    @classmethod
    def _coerce_numeric(cls, v: Any) -> Any:
        """Whatever the model returns, produce a usable number or nothing.

        Never raise. This runs on the inbound path: a `ValidationError` here
        aborts the transaction that stores the customer's message, and since the
        same message replays identically the provider's retries fail the same
        way — the message is gone. Degrading to "no budget extracted" costs one
        field; raising costs the conversation.
        """
        if v is None or v == "" or (isinstance(v, str) and v.lower() in ("null", "none", "n/a")):
            return None
        if isinstance(v, str):
            # Drop currency marks, spaces and stray words, keep the number.
            s = re.sub(r"[^\d.,\-]", "", v)
            if not s:
                return None
            # Both separators present: the rightmost is the decimal point.
            # "1.200.000,50" is European, "1,200,000.50" is American.
            if "." in s and "," in s:
                s = (
                    s.replace(".", "").replace(",", ".")
                    if s.rfind(",") > s.rfind(".")
                    else s.replace(",", "")
                )
            # One separator, grouped in threes: it is a thousands separator, in
            # either convention. "450,000" meant 450000 and used to come out as
            # 450 — off by a thousand, positive, in range, and so past every
            # check downstream. This install writes prices the American way.
            elif re.fullmatch(r"-?\d{1,3}(,\d{3})+", s):
                s = s.replace(",", "")
            elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
                s = s.replace(".", "")
            elif "," in s:
                s = s.replace(",", ".")  # European decimal comma
            try:
                v = float(s)
            except ValueError:
                return None
        try:
            number = float(v)
        except (TypeError, ValueError):
            return None
        # The database refuses negatives outright and overflows NUMERIC(12,2)
        # past ten digits. Either would abort the inbound transaction, so a
        # value that cannot be stored is discarded here instead — the same way
        # `confidence` is clamped rather than rejected.
        if number < 0 or number > 9_999_999_999:
            log.warning("classifier returned an unusable budget (%s), ignoring it", v)
            return None
        return number


class IntentResult(BaseModel):
    intent: LeadIntent = LeadIntent.OTHER
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    entities: IntentEntities = Field(default_factory=IntentEntities)
    raw_response: str | None = None  # for debugging when validation failed

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))


_SYSTEM_PROMPT = """Eres un clasificador de leads inmobiliarios. Recibes una conversación corta de WhatsApp en castellano entre un cliente potencial y un asistente. Devuelves un JSON con la intención del cliente y los datos que hayas podido extraer.

Esquema EXACTO:
{
  "intent": "rent" | "buy" | "valuation" | "other",
  "confidence": 0.0-1.0,
  "entities": {
    "zone": string | null,
    "budget_min": number | null,
    "budget_max": number | null,
    "property_type": "apartment" | "house" | "commercial" | "land" | "other" | null,
    "urgency": "immediate" | "weeks" | "months" | "exploring" | null
  }
}

Reglas:
- "rent" = busca alquilar. "buy" = busca comprar. "valuation" = quiere tasar/valorar una propiedad propia. "other" = saludo genérico, pregunta administrativa, queja, etc.
- "confidence" refleja qué tan seguro estás de la intención (1.0 = inequívoco).
- Si el cliente NO menciona un dato, devuelve null para ese campo. NUNCA inventes.
- Los importes en euros van como número plano (1200 no "1.200€").
- urgency=immediate si dice "ya"/"esta semana"/"urgente"; weeks si "este mes"; months si "en unos meses"; exploring si solo curiosea.

Devuelve EXCLUSIVAMENTE el JSON. Sin texto antes o después. Sin markdown."""


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Find the first {...} block in the response and json.loads it."""
    if not text:
        return None
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


async def classify_intent(
    message_history: list[dict[str, str]],
    *,
    language_hint: str | None = None,
) -> IntentResult:
    """Run the classifier against the given conversation history.

    Args:
        message_history: list of {"role": "user"|"assistant", "content": str} —
            the same shape the orchestrator passes to the LLM for reply generation.
        language_hint: optional 2-letter language code (es/en/…) of the inbound
            message. Helps the LLM disambiguate (e.g., "rent" in English vs
            "renta" in Spanish that could mean income).

    Returns:
        IntentResult. On any error (LLMUnavailable, invalid JSON, schema mismatch),
        returns IntentResult(intent=OTHER, confidence=0.0, raw_response=<diagnostic>)
        so the caller can persist *something* and move on.
    """
    system_prompt = _SYSTEM_PROMPT
    if language_hint:
        system_prompt += f"\n\nNOTA: el mensaje del usuario está en idioma `{language_hint}`. Esto NO cambia el formato del JSON ni los valores válidos del campo intent — sigue devolviendo rent/buy/valuation/other en inglés."

    try:
        result = await generate_reply(
            messages=message_history,
            system=system_prompt,
            max_tokens=300,
            temperature=0.0,
            json_mode=True,
        )
    except LLMUnavailable as exc:
        log.error("classifier: all LLMs unavailable: %s", exc)
        return IntentResult(raw_response=f"LLMUnavailable: {exc}")

    parsed = _extract_json(result.text)
    if parsed is None:
        log.warning("classifier: could not parse JSON from response: %r", result.text[:200])
        return IntentResult(raw_response=result.text)

    try:
        return IntentResult.model_validate(parsed)
    except ValidationError as exc:
        log.warning("classifier: pydantic validation failed: %s; raw=%r", exc, result.text[:200])
        return IntentResult(raw_response=result.text)
