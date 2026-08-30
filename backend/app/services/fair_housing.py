"""Phrases that cannot appear in housing advertising, in English and Spanish.

The Fair Housing Act forbids advertising that states a preference or limitation
based on race, colour, religion, sex, familial status, national origin or
disability. It does not require intent. "Perfect for young families" is a
familial-status preference; "safe neighborhood" and "good schools" are the
recognised euphemisms for race, and they are the exact phrases a model
optimising for engagement writes without being asked.

Deterministic on purpose. The check that decides whether a licensed agent's
advertising is legal cannot be another prompt: it has to give the same answer
every time, be readable by the broker, and be testable phrase by phrase.

Both languages are always checked, whatever the piece is tagged as. A Spanish
phrase in an English piece is the same violation, and mislabelling the language
is not a defence.

This list is a floor, not a ceiling. It catches the phrasings a generator
actually produces; it cannot catch everything a person could write, which is why
a human approves every piece regardless of what this returns.
"""

from __future__ import annotations

import re
import unicodedata

# Category → the phrases that give it away. Phrases, never bare words: "family
# room" is a room and "familia" is half the language, and a filter that fires on
# those gets switched off within a week, which is worse than not having one.
FORBIDDEN: dict[str, tuple[str, ...]] = {
    # Familial status — who lives there, children, marital status.
    "familial_status": (
        "perfect for families",
        "perfect for a family",
        "ideal for families",
        "great for families",
        "family friendly neighborhood",
        "family friendly neighbourhood",
        "no kids",
        "no children",
        "adults only",
        "adult community",
        "mature couple",
        "single professionals only",
        "empty nesters",
        "kid free",
        "child free",
        "ideal para familias",
        "perfecto para familias",
        "perfecta para familias",
        "ideal para una familia",
        "sin ninos",
        "no se admiten ninos",
        "solo adultos",
        "solo para adultos",
        "pareja madura",
        "matrimonio sin hijos",
    ),
    # Steering — the coded language that sorts people by race and class.
    "steering": (
        "safe neighborhood",
        "safe neighbourhood",
        "safe area",
        "good schools",
        "great schools",
        "best schools",
        "desirable neighborhood",
        "desirable neighbourhood",
        "exclusive neighborhood",
        "exclusive neighbourhood",
        "up and coming neighborhood",
        "right kind of people",
        "our kind of people",
        "changing neighborhood",
        "barrio seguro",
        "zona segura",
        "buenas escuelas",
        "mejores escuelas",
        "buenos colegios",
        "barrio exclusivo",
        "zona exclusiva",
        "gente como usted",
        "el tipo de gente",
    ),
    "race_or_colour": (
        "white neighborhood",
        "white neighbourhood",
        "hispanic neighborhood",
        "black neighborhood",
        "asian neighborhood",
        "integrated neighborhood",
        "barrio blanco",
        "barrio hispano",
        "barrio negro",
    ),
    "religion": (
        "christian community",
        "christian family",
        "near the church",
        "walking distance to the church",
        "jewish community",
        "muslim community",
        "comunidad cristiana",
        "familia cristiana",
        "cerca de la iglesia",
        "comunidad judia",
        "comunidad musulmana",
    ),
    "national_origin": (
        "english speakers only",
        "must speak english",
        "no foreigners",
        "american family",
        "solo hispanos",
        "solo latinos",
        "no extranjeros",
        "solo se habla espanol",
    ),
    "disability": (
        "able bodied",
        "no wheelchairs",
        "not suitable for disabled",
        "no disabilities",
        "must be able to climb",
        "sin discapacidad",
        "no apto para discapacitados",
        "debe poder subir escaleras",
    ),
    "sex": (
        "male tenants only",
        "female tenants only",
        "bachelor pad",
        "solo hombres",
        "solo mujeres",
        "solo caballeros",
        "solo senoritas",
    ),
}


def _normalise(text: str) -> str:
    """Fold the text so a phrase match is not defeated by typography.

    Accents removed, case folded, punctuation turned into spaces and runs of
    whitespace collapsed. Without this, "ideal para famílias" and
    "perfect-for-families" walk straight past a list that has both.
    """
    stripped = "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def find_violations(text: str, language: object = None) -> list[dict[str, str]]:
    """Every forbidden phrase present, with the category it belongs to.

    `language` is accepted and ignored on purpose: both lists always run. It
    stays in the signature because callers have a language to hand and leaving
    it out invites somebody to add per-language filtering later, which is the
    bug this docstring exists to prevent.
    """
    if not text:
        return []

    haystack = f" {_normalise(text)} "
    found: list[dict[str, str]] = []
    for category, phrases in FORBIDDEN.items():
        for phrase in phrases:
            if f" {_normalise(phrase)} " in haystack:
                found.append({"phrase": phrase, "category": category})
    return found


# ── What a picture may not be of ─────────────────────────────────────────
# Housing advertising is regulated in images as much as in words. A video whose
# every frame shows one kind of household says something about who is welcome,
# and it says it without a single sentence anybody could edit in review.
#
# So the prompts that go to an image model are checked too — and against a
# WIDER list than the text, because the failure mode is different. In a script,
# "family" appears in sentences that are perfectly fine ("family room", "the
# family that owns it"). In an image prompt it is an instruction: draw one.
# A prompt is a short, purpose-built string that we ask for and can regenerate
# for free, so a false positive here costs one retry and a false negative costs
# a Fair Housing exposure on the broker's licence.
#
# This is a floor, not a ceiling. It catches the words a model reaches for by
# default; it cannot catch a paraphrase, and the human approval gate is still
# what stands behind it.
PEOPLE_IN_PICTURES = (
    "family", "families", "familia", "familias",
    "couple", "couples", "pareja", "parejas",
    "kid", "kids", "child", "children", "niño", "niños", "niña", "niñas",
    "baby", "babies", "toddler", "bebé", "bebe",
    "mom", "mother", "dad", "father", "parents", "madre", "padre", "padres",
    "professional", "professionals", "profesional", "profesionales",
    "retiree", "retirees", "senior", "seniors", "elderly", "jubilado",
    "jubilados", "anciano", "ancianos",
    "young man", "young woman", "young people", "joven", "jóvenes",
    "student", "students", "estudiante", "estudiantes",
    "man", "woman", "men", "women", "hombre", "mujer", "hombres", "mujeres",
    "person", "people", "persona", "personas", "gente",
    "portrait", "portraits", "retrato", "faces", "face", "cara", "rostro",
    "smiling", "sonriente", "sonriendo",
    "neighbors", "neighbours", "vecinos",
    "church", "churchgoers", "iglesia", "temple", "synagogue", "mosque",
    "school", "schools", "escuela", "escuelas", "colegio",
)


def picture_violations(prompt: str) -> list[dict[str, str]]:
    """Words that must not steer what an image model draws.

    Whole words, unlike `find_violations`, which matches phrases: "manor" must
    not trip on "man", and a substring check here would reject most of the
    English language. Runs IN ADDITION to `find_violations`, never instead of
    it — the phrase list still applies to a prompt.
    """
    if not prompt:
        return []
    words = set(_normalise(prompt).split())
    found = [
        {"phrase": term, "category": "people_in_pictures"}
        for term in PEOPLE_IN_PICTURES
        if _normalise(term) in words
        or (" " in term and f" {_normalise(term)} " in f" {_normalise(prompt)} ")
    ]
    return found
