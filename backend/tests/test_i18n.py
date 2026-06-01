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
