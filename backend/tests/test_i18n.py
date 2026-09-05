"""Language detection + bilingual prompt building."""
from __future__ import annotations

import pytest

from app.services.i18n import (
    DEFAULT_LANGUAGE,
    detect_for,
    detect_language,
    language_instruction,
    pick_supported_language,
)


def test_detect_spanish_text() -> None:
    assert detect_language("Hola, busco piso en alquiler en Madrid") == "es"


def test_detect_english_text() -> None:
    assert detect_language("Hi, I'm looking for a 2-bedroom apartment in Brooklyn") == "en"


def test_short_text_falls_back_to_default() -> None:
    # Strings shorter than 3 chars are too ambiguous → fallback.
    assert detect_language("hi") == DEFAULT_LANGUAGE
    assert detect_language("") == DEFAULT_LANGUAGE


def test_explicit_fallback_overrides_default() -> None:
    assert detect_language("", fallback="en") == "en"


def test_pick_supported_returns_detected_when_in_whitelist() -> None:
    assert pick_supported_language("en", ["es", "en"]) == "en"


def test_pick_supported_returns_first_when_not_in_whitelist() -> None:
    # detected fr, only es supported → fallback to es (first item).
    assert pick_supported_language("fr", ["es"]) == "es"
    assert pick_supported_language("fr", ["es", "en"]) == "es"


def test_pick_supported_empty_whitelist_uses_fallback() -> None:
    assert pick_supported_language("en", [], fallback="es") == "es"


def test_language_instruction_spanish_persona() -> None:
    line = language_instruction("en", persona_locale="es")
    assert "IDIOMA" in line
    assert "inglés" in line  # "English" in Spanish wording
    assert "EXCLUSIVAMENTE" in line


def test_language_instruction_english_persona() -> None:
    line = language_instruction("es", persona_locale="en")
    assert "LANGUAGE" in line
    assert "Spanish" in line


def test_language_instruction_unknown_lang_falls_back_to_code() -> None:
    # zh isn't in _LANG_NAMES → uses the code uppercased.
    line = language_instruction("zh", persona_locale="es")
    assert "ZH" in line


def test_default_language_is_english() -> None:
    # System communications default to English when the language can't be detected.
    assert DEFAULT_LANGUAGE == "en"
    assert detect_language("") == "en"
    assert detect_language("ok") == "en"  # <3 chars → default


def test_english_first_order_mirrors_supported_else_english() -> None:
    # With the English-first default order: a supported language is mirrored,
    # an unsupported one falls back to English (the first/default).
    assert pick_supported_language("es", ["en", "es"]) == "es"
    assert pick_supported_language("en", ["en", "es"]) == "en"
    assert pick_supported_language("fr", ["en", "es"]) == "en"


def test_language_instruction_allows_explicit_request_override() -> None:
    # The steering line lets the client switch language on explicit request.
    assert "UNLESS" in language_instruction("en", persona_locale="en")
    assert "SALVO" in language_instruction("en", persona_locale="es")


# ── detect_for: langdetect is confidently wrong on the messages people send ──


_SPANISH_OPENERS = [
    "Hola, esta disponible?",
    "Hola, vi su anuncio",
    "hola",
    "Me interesa",
    "Sigue disponible?",
    "Buenos dias",
    "Cual es el precio?",
    "Cuanto es la renta?",
    "Hola! Me interesa el de 2 habitaciones",
    "Buenas tardes, me gustaria agendar una visita a la propiedad",
    "Hola, busco un apartamento de 2 habitaciones cerca de Cherry Creek, hasta 3000 al mes",
    "Puedo verlo este fin de semana?",
]

_ENGLISH_OPENERS = [
    "Hi, is it available?",
    "Hello, I saw your listing",
    "Is this still available?",
    "Hi! Interested in the 2 bed",
    "Can I see it this weekend?",
    "How much is rent?",
    "hi",
    "Hello",
    "Interested",
    "Whats the price?",
    "Good afternoon, I would like to schedule a tour of the property",
    "Hi, do you have any 2 bedroom apartments near Cherry Creek under 3000 a month?",
]


@pytest.mark.parametrize("text", _SPANISH_OPENERS)
def test_a_spanish_lead_is_answered_in_spanish(text: str) -> None:
    """The messages people actually open with, not paragraphs.

    `langdetect` does not hesitate on a short string — it returns a confident
    wrong answer rather than raising, so nothing downstream can tell. Measured
    before this fix, four of these twelve came back as another language
    entirely: "Hola, esta disponible?" → Italian, "Me interesa" → German,
    "hola" → Welsh, "Hola, vi su anuncio" → Italian. Each was then answered in
    English, because an unsupported result falls back to `supported[0]`.

    MUTATION GUARD — delete the marker pass in `detect_for` and four of these
    go red.
    """
    assert detect_for(text, ["en", "es"]) == "es"


@pytest.mark.parametrize("text", _ENGLISH_OPENERS)
def test_english_is_the_default_and_stays_the_default(text: str) -> None:
    """The other half of the promise, and the one most leads will exercise.

    A marker pass that leaks — one cognate too many on the list — would answer
    an English lead in Spanish, which is a worse failure than the one it fixes
    because it is the majority case. These twelve include the short strings
    where `langdetect` guesses wildly ("hi" → nothing usable), and every one of
    them must land on English.
    """
    assert detect_for(text, ["en", "es"]) == "en"


@pytest.mark.parametrize("text", _SPANISH_OPENERS)
def test_the_marker_pass_never_widens_what_the_agency_offers(text: str) -> None:
    """An English-only agency keeps replying in English, marker or no marker.

    `AgentSettings.languages` is a business decision — which languages that
    office can actually follow up in — and a detection fix must not overrule it.
    An agency that gets a Spanish reply it cannot continue has been handed a
    conversation it must drop.
    """
    assert detect_for(text, ["en"]) == "en"


def test_a_confident_supported_detection_is_never_second_guessed() -> None:
    """The correction only fires on an answer that was going to be discarded.

    Long, unambiguous English that happens to quote a Spanish word must stay
    English: `langdetect` says `en`, `en` is supported, and the marker pass is
    never consulted.
    """
    text = (
        "Good morning, my wife and I are relocating to Denver in November and we "
        "are looking for a three bedroom house with a yard. Our budget is around "
        "$750,000. The listing description mentioned a casa style patio, which is "
        "exactly what we want. Could we schedule a showing this weekend?"
    )
    assert detect_language(text) == "en"
    assert detect_for(text, ["en", "es"]) == "en"


@pytest.mark.parametrize("text", [
    "casa or condo?",
    "Any casa listings?",
    "patio?",
    "Is there a hacienda style one?",
    "Do you have anything in the plaza area?",
])
def test_a_cognate_is_not_a_spanish_marker(text: str) -> None:
    """Words English borrowed are not evidence of anything.

    These are the dangerous ones: short English messages where `langdetect`
    fails ("casa or condo?" → Portuguese, "Any casa listings?" → Tagalog,
    "patio?" → Italian), so the marker pass IS consulted and a cognate on the
    list would send an English-speaking lead a reply in Spanish. That is a worse
    failure than the one the markers fix, because English is the majority of
    this agency's leads.

    MUTATION GUARD — add `casa`, `patio`, `plaza`, `villa` or `hacienda` to
    `_SPANISH_MARKERS` and these go red.
    """
    assert detect_for(text, ["en", "es"]) == "en"
