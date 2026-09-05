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
import re
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


# Spelling that is Spanish and cannot be anything else, for the case below.
#
# Nothing here is a word an English-writing lead would type: no cognates, no
# proper nouns, no "casa"/"patio"/"plaza" that live in English too. Inverted
# punctuation and Spanish-only diacritics are on the list because a keyboard
# that produces `¿` or `ñ` is not producing English.
_SPANISH_MARKERS = re.compile(
    r"[ñ¿¡]|[áéíóú]|"
    r"\b(hola|buenas|buenos\s+d[ií]as|buenas\s+(tardes|noches)|gracias|disponible|"
    r"cu[áa]nto|cu[áa]l|quisiera|quiero|me\s+interesa|por\s+favor|habitaci[óo]n|"
    r"habitaciones|alquiler|vivienda|piso|precio|est[áa]|mudarme|visita)\b",
    re.IGNORECASE,
)


def _marker_language(text: str) -> str | None:
    """`es` when the text carries Spanish-only spelling, else `None`."""
    return "es" if text and _SPANISH_MARKERS.search(text) else None


def detect_for(text: str, supported: Iterable[str], *, fallback: str = DEFAULT_LANGUAGE) -> str:
    """The language to answer a lead in: `langdetect`, corrected by markers.

    `langdetect` is unreliable on the short strings people actually open with,
    and it does not hesitate — it returns a confident wrong answer rather than
    raising, so nothing downstream can tell. Measured on twelve realistic first
    messages in Spanish, four came back as another language entirely:
    `"Hola, esta disponible?"` → Italian, `"Me interesa"` → German, `"hola"` →
    Welsh. Each of those was then answered in English, because an unsupported
    result falls back to `supported[0]`.

    So the marker pass runs **only when langdetect's answer is not one we
    support** — a confident, usable detection is never second-guessed, and the
    correction can only fire on an answer that was going to be discarded anyway.

    It never widens what the agency offers: a marker hit that is not in
    `supported` still falls through. An agency configured for English only keeps
    replying in English, which is a business decision, not a detection bug.
    """
    sup = list(supported) or [fallback]
    detected = detect_language(text, fallback=fallback)
    if detected in sup:
        return detected
    marker = _marker_language(text)
    if marker is not None and marker in sup:
        return marker
    return sup[0]


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
