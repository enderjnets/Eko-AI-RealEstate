"""The sentence a visitor agrees to, and the record it becomes.

Nothing guarded these strings. `test_calculator_copy.py` reads the
`calculator.*` keys and stops there, so the consent wording could have been
edited in English and left stale in Spanish — on a page whose own footer says
"Se habla español" — and every test would still have passed.

That matters more here than anywhere else in the dictionary, because this
string is not copy. It is stored verbatim on the lead with a timestamp, an IP
and a user agent, and it is the thing that would be produced if the consent
were ever questioned. `ConsultForm.tsx` says it plainly: a second, subtly
different wording "is how a TCPA record ends up describing a sentence the
visitor never read."

── What the wording has to carry ───────────────────────────────────────────
47 CFR 64.1200(f)(9) defines prior express written consent and (f)(9)(i)
requires two clear and conspicuous disclosures: that the signer authorises
telemarketing calls placed with an automatic dialler or an artificial or
prerecorded voice, and that they are NOT required to agree as a condition of
purchasing anything. The definition also wants the seller named and the number
identified. The carriers add two more through CTIA's messaging guidelines —
message frequency, and rates — before they will register the campaign at all.

Those elements are asserted per language below. The assertions are on meaning,
not on the exact sentence: rewording is allowed, dropping an element is not.

── Two lines, one record ───────────────────────────────────────────────────
The visible label is short so it can be read. The disclosure sits under it in
small print, on screen rather than behind a link, and `consent_text` stores
BOTH joined. The last test reads the two form components and fails if either
renders the detail without storing it, or stores a record the page never
showed — the exact inversion this file exists to prevent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.fair_housing import find_violations

ROOT = Path(__file__).resolve().parents[2]
I18N = ROOT / "frontend" / "lib" / "i18n.tsx"
FORMS = (
    ROOT / "frontend" / "components" / "landing" / "ConsultForm.tsx",
    ROOT / "frontend" / "app" / "contact" / "page.tsx",
)

KEY = re.compile(r'^\s*"(contact\.consent[^"]*)":\s*"((?:[^"\\]|\\.)*)",?\s*$')

#: key → what it is for. Both languages must carry all three.
REQUIRED_KEYS = {
    "contact.consent",        # the short line beside the checkbox
    "contact.consentDetail",  # the disclosure, in small print under it
    "contact.consentHint",    # "optional, we answer either way"
}

#: element → the alternatives that satisfy it, per language. One match is
#: enough; the wording may change, the element may not disappear.
ELEMENTS: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "names the seller": ("denver home story",),
        "identifies the number": ("number you provide", "number you give"),
        "automated or artificial voice": ("automated", "ai-generated", "prerecorded"),
        "not a condition of purchase": ("not required", "not a condition"),
        "message frequency": ("frequency varies", "frequency may vary", "msg frequency"),
        "rates": ("rates may apply",),
        "how to stop": ("stop",),
    },
    "es": {
        "names the seller": ("denver home story",),
        "identifies the number": ("número que facilites", "número que facilitas"),
        "automated or artificial voice": ("automáticos", "generada por ia", "pregrabada"),
        "not a condition of purchase": ("no es necesario", "no es condición"),
        "message frequency": ("frecuencia de los mensajes", "frecuencia varía"),
        "rates": ("tarifas",),
        "how to stop": ("stop",),
    },
}


def _strings() -> dict[str, dict[str, str]]:
    text = I18N.read_text(encoding="utf-8")
    en_start = text.index("const EN: Record<string, string> = {")
    es_start = text.index("const ES: Record<string, string> = {")
    out: dict[str, dict[str, str]] = {}
    for lang, chunk in (("en", text[en_start:es_start]), ("es", text[es_start:])):
        found: dict[str, str] = {}
        for line in chunk.splitlines():
            m = KEY.match(line)
            if m:
                found[m.group(1)] = json.loads('"' + m.group(2) + '"')
        out[lang] = found
    return out


@pytest.fixture(scope="module")
def strings() -> dict[str, dict[str, str]]:
    return _strings()


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_extraction_found_the_consent_copy(
    strings: dict[str, dict[str, str]], lang: str
) -> None:
    """A regex that matches nothing passes every assertion below it."""
    assert REQUIRED_KEYS <= set(strings[lang]), sorted(strings[lang])


def test_neither_language_is_left_behind(strings: dict[str, dict[str, str]]) -> None:
    """The record a Spanish speaker agrees to is not the English one."""
    assert set(strings["en"]) == set(strings["es"])
    for key in REQUIRED_KEYS:
        assert strings["en"][key].strip(), key
        assert strings["es"][key].strip(), key


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_stored_record_carries_every_required_element(
    strings: dict[str, dict[str, str]], lang: str
) -> None:
    """What `consent_text` will hold, checked element by element.

    The record is the label plus the detail, because that is what the page
    shows and what the form sends.
    """
    record = (
        strings[lang]["contact.consent"] + " " + strings[lang]["contact.consentDetail"]
    ).casefold()
    missing = [
        element
        for element, options in ELEMENTS[lang].items()
        if not any(option.casefold() in record for option in options)
    ]
    assert not missing, f"{lang}: the consent record no longer says: {missing}"


@pytest.mark.parametrize("lang", ["en", "es"])
def test_the_consent_copy_is_clean(
    strings: dict[str, dict[str, str]], lang: str
) -> None:
    """It is advertising copy too, and it is read by everyone who fills the form."""
    for key in REQUIRED_KEYS:
        assert find_violations(strings[lang][key], lang) == [], key
        assert not re.search(r"\beko\b", strings[lang][key], re.I), key


@pytest.mark.parametrize("form", FORMS, ids=lambda p: p.name)
def test_every_form_stores_the_sentence_it_showed(form: Path) -> None:
    """Rendered and recorded, or neither — checked on both forms.

    The failure this catches does not look like a bug in review: somebody
    shortens the visible label for the page's sake and leaves `consent_text`
    pointing at it, and the record silently stops carrying the disclosure while
    the page still shows it. Nothing else in the suite would notice.
    """
    source = form.read_text(encoding="utf-8")
    # The lookbehind is load-bearing and was added after a mutation survived:
    # `consentRecord = `${consentWording} ${consentDetail}`` CONTAINS the
    # literal `{consentDetail}`, so a plain substring check passed on a file
    # that had stopped rendering the disclosure entirely. Only an interpolation
    # NOT preceded by `$` is JSX.
    assert re.search(r"(?<!\$)\{consentDetail\}", source), (
        f"{form.name} does not render the disclosure"
    )
    assert re.search(r"consentRecord\s*=\s*`\$\{consentWording\}\s*\$\{consentDetail\}`", source), (
        f"{form.name} does not build the record from both lines"
    )
    assert "consent_text: consent ? consentRecord : undefined" in source, (
        f"{form.name} stores something other than what it rendered"
    )
