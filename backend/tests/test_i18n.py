"""Language detection + bilingual prompt building."""
from __future__ import annotations

from app.services.i18n import (
    DEFAULT_LANGUAGE,
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
