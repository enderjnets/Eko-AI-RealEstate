"""Language detection + bilingual prompt scaffolding for the agent.

We detect the inbound message's language with `langdetect` (deterministic
seed for reproducibility), pick the closest supported language from
AgentSettings.languages, and pass that hint into the system prompt so the
LLM replies in the same language.

Supported languages today: en (English, the DEFAULT) and es (Spanish). The agent
replies in English by default; it mirrors the lead's language when they write in
(or explicitly ask for) another supported one. Adding pt/fr/de later is a one-line
change in `_LANG_NAMES`.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from langdetect import DetectorFactory, LangDetectException, detect

log = logging.getLogger(__name__)

# Deterministic detection — same input → same output, important for tests.
DetectorFactory.seed = 0

DEFAULT_LANGUAGE = "en"  # system communications default to English when undetected

_LANG_NAMES: dict[str, dict[str, str]] = {
    "es": {"es": "castellano", "en": "Spanish"},
    "en": {"es": "inglés", "en": "English"},
    "pt": {"es": "portugués", "en": "Portuguese"},
    "fr": {"es": "francés", "en": "French"},
    "de": {"es": "alemán", "en": "German"},
    "it": {"es": "italiano", "en": "Italian"},
}


def detect_language(text: str, *, fallback: str = DEFAULT_LANGUAGE) -> str:
    """Return a 2-letter language code (`es` / `en` / …). On any failure,
    falls back to the provided default. Very short strings (<3 chars) skip
    detection — they're too ambiguous and trigger langdetect exceptions."""
    if not text or len(text.strip()) < 3:
        return fallback
    try:
        return detect(text)
    except LangDetectException as exc:
        log.debug("langdetect failed (%s) — fallback %s", exc, fallback)
        return fallback


def pick_supported_language(detected: str, supported: Iterable[str], *, fallback: str = DEFAULT_LANGUAGE) -> str:
    """If `detected` is in the supported whitelist, return it; otherwise the first
    element of `supported`, or `fallback` if the whitelist is empty."""
    sup = list(supported) or [fallback]
    return detected if detected in sup else sup[0]


def language_instruction(lang_code: str, *, persona_locale: str = "es") -> str:
    """Build the language-steering line we append to the system prompt.

    `persona_locale` controls the language used to write the instruction itself
    (so the steering line is consistent with the rest of the persona text).
    """
    names = _LANG_NAMES.get(lang_code, {})
    if persona_locale == "en":
        name = names.get("en", lang_code.upper())
        return (
            f"\n\nLANGUAGE: Reply in {name} only — UNLESS the client explicitly asks for a "
            "different language, in which case reply in that one. Match the client's register "
            "(formal / informal)."
        )
    name = names.get("es", lang_code.upper())
    return (
        f"\n\nIDIOMA: responde EXCLUSIVAMENTE en {name}, SALVO que el cliente pida explícitamente "
        "otro idioma (en ese caso, responde en ese). Adapta el registro (formal / informal) al "
        "del cliente."
    )
