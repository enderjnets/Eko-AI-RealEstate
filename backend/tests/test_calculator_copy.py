"""The calculator's public copy, in both languages, through the Fair Housing filter.

`/calculator` is arithmetic and prose, no listings and no neighborhoods, so
nothing on it should trip `find_violations` — and this test is how that stays
true when somebody edits a sentence. It also enforces the brand rule the
metadata tests enforce for titles: nothing a visitor reads names the platform.

The strings are read out of `frontend/lib/i18n.tsx` with a regex. A regex that
matches nothing would pass every per-string assertion, so the count is asserted
first: fewer than thirty strings per language means the extraction broke, not
that the page got shorter.

Each literal is decoded as JSON. That accepts what the file uses — backslash-u
escapes (``\\u00f3``) and literal accented characters — and refuses the
backslash-x and backslash-quote escapes TypeScript would accept. A `JSONDecodeError` here means a string was written
in a style the rest of the dictionary does not use; fix the string, not the
test.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.fair_housing import find_violations

I18N = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "i18n.tsx"
KEY = re.compile(r'^\s*"((?:calculator|lead\.calculator)\.[^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$')
MIN_STRINGS = 30


def _sections() -> dict[str, dict[str, str]]:
    text = I18N.read_text(encoding="utf-8")
    en_start = text.index("const EN: Record<string, string> = {")
    es_start = text.index("const ES: Record<string, string> = {")
    out: dict[str, dict[str, str]] = {}
    for lang, chunk in (("en", text[en_start:es_start]), ("es", text[es_start:])):
        found: dict[str, str] = {}
        for line in chunk.splitlines():
            m = KEY.match(line)
            if m:
                # The TS literal is JSON-compatible for what these strings use
                # (\uXXXX and \" escapes), so decode it the same way.
                found[m.group(1)] = json.loads('"' + m.group(2) + '"')
        out[lang] = found
    return out


@pytest.fixture(scope="module")
def sections() -> dict[str, dict[str, str]]:
    return _sections()


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_extraction_found_the_copy(sections: dict[str, dict[str, str]], lang: str) -> None:
    assert len(sections[lang]) >= MIN_STRINGS, sorted(sections[lang])


def test_both_languages_carry_the_same_keys(sections: dict[str, dict[str, str]]) -> None:
    assert set(sections["en"]) == set(sections["es"])


@pytest.mark.parametrize("lang", ["en", "es"])
def test_nothing_trips_fair_housing(sections: dict[str, dict[str, str]], lang: str) -> None:
    for key, text in sections[lang].items():
        assert find_violations(text, lang) == [], (key, text)


@pytest.mark.parametrize("lang", ["en", "es"])
def test_nothing_names_the_platform(sections: dict[str, dict[str, str]], lang: str) -> None:
    for key, text in sections[lang].items():
        assert not re.search(r"eko", text, re.IGNORECASE), (key, text)


@pytest.mark.parametrize("lang", ["en", "es"])
def test_no_lender_language(sections: dict[str, dict[str, str]], lang: str) -> None:
    # The brokerage does not lend. An APR or a promise to lend on this page is
    # credit advertising, which is a different set of rules and not ours.
    for key, text in sections[lang].items():
        assert not re.search(r"\bAPR\b|NMLS|commitment to lend|pre-?approved", text, re.IGNORECASE), (key, text)
