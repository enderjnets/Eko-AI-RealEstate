"""Whitespace on the way in, across every schema that persists free text.

`agency_name` held "Ashly " and every greeting read "assistant at Ashly ." —
the space was invisible in the Settings box and impossible to spot in the
rendered sentence without counting characters. It was fixed for
`brokerage_line` in v0.55.0 and not generalised, so it came straight back on
the field next door.

The ordering matters as much as the trimming, and is the reason these are
`mode="before"` validators rather than a `.strip()` in the handler: as an
`after` step, `min_length` judges the RAW string, so " " passes a
`min_length=1` check and is written verbatim. `leads.CallIn._email_shape`
carries the same note; this is the third time the repo has paid for it.
"""
from __future__ import annotations

import pytest

from app.api.v1.content import DraftIn, PieceEdit, RejectIn
from app.api.v1.public import PublicLeadIn
from app.api.v1.settings import SettingsPatch


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("hook", "  A hook  ", "A hook"),
        ("hook", "   ", None),
        ("script", "  Line one.\n", "Line one."),
        ("caption", "\t#denver  ", "#denver"),
        ("caption", "", None),
    ],
)
def test_a_content_edit_is_trimmed(field: str, raw: str, expected: str | None) -> None:
    """Hook, script and caption are burned into a video and read by the caption.

    A trailing space is not cosmetic here: it reaches the rendered frame.
    """
    assert getattr(PieceEdit(**{field: raw}), field) == expected
    assert getattr(DraftIn(**{field: raw}), field) == expected


def test_a_rejection_reason_of_spaces_is_refused() -> None:
    """`min_length=3` used to see the raw string, so "   " was a valid reason.

    It was then stored as the record of WHY a piece was rejected — blank, on a
    field whose only purpose is to tell the next person what was wrong.
    """
    assert RejectIn(reason="  too salesy  ").reason == "too salesy"
    with pytest.raises(ValueError, match="reason"):
        RejectIn(reason="     ")


def test_the_public_form_is_normalised_downstream_not_in_the_schema() -> None:
    """The public form needs no trimming validator, and finding that out matters.

    One was written and then removed: `services/capture.py` already normalises
    everything that gets stored — `clean_text` trims AND collapses runs of
    whitespace for name and message, `normalize_email` and `normalize_phone`
    handle the other two. Measured on identical POSTs, the stored row was
    byte-identical with and without the validator. Code that changes nothing
    still reads as coverage, which is why it went.

    This test holds the fact the removal depends on, so that if `capture.py`
    ever stops normalising, something says so here.
    """
    from app.services.capture import clean_text, normalize_email, normalize_phone

    assert clean_text("  Ana\n  Pérez  ", 200) == "Ana Pérez"
    assert clean_text("   ", 200) is None
    assert normalize_email("  ANA@Example.test ") == "ana@example.test"
    assert normalize_phone("  (303) 555-1234  ") == "+13035551234"


def test_the_honeypot_must_never_be_trimmed() -> None:
    """Trimming `website` would WEAKEN the trap, not tidy it.

    The route tests it as `if body.website`, ahead of the captcha and of tenant
    resolution, and a whitespace-only string is truthy — so a bot filling the
    hidden field with spaces is caught today. Normalising it to None would wave
    that bot straight through.

    This test exists for the next person who decides to trim every string on
    the model: they find out here rather than in the lead table.
    """
    assert PublicLeadIn(website="   ").website == "   "
    assert bool(PublicLeadIn(website="   ").website) is True


def test_the_consent_record_is_collapsed_not_verbatim() -> None:
    """Said plainly because the opposite was assumed and written down as fact.

    `consent_text` goes through `clean_text` like everything else
    (`capture.py:510`), so newlines are collapsed and it is NOT stored exactly
    as the person saw it. An earlier comment here claimed it was kept verbatim
    "because a legal record is not normalised" — a comforting sentence that the
    code contradicts, on the one field whose whole job is defending a claim.
    """
    from app.services.capture import clean_text

    raw = "  I agree\n  to be   contacted.  "
    assert clean_text(raw, 500) == "I agree to be contacted."


@pytest.mark.parametrize(
    "field", ["agency_name", "agent_persona", "greeting_template", "timezone"]
)
def test_a_not_null_settings_field_refuses_blank(field: str) -> None:
    """Trimmed first, THEN length-checked — so blank is refused, not stored.

    Refused rather than nulled: these columns are NOT NULL, and a validator
    returning None for them would hand the handler a value it writes straight
    into the database, turning a 422 into a 500.
    """
    assert getattr(SettingsPatch(**{field: "  x  "}), field) == "x"
    with pytest.raises(ValueError, match=field):
        SettingsPatch(**{field: "   "})


@pytest.mark.parametrize(
    "field", ["brokerage_line", "agency_phone", "booking_contact_email"]
)
def test_a_nullable_settings_field_clears_on_blank(field: str) -> None:
    """Blank means "clear it" — the only way to unset these without an endpoint."""
    assert getattr(SettingsPatch(**{field: "  x  "}), field) == "x"
    assert getattr(SettingsPatch(**{field: "   "}), field) is None


def test_bytes_are_trimmed_without_manufacturing_characters() -> None:
    """Both halves at once, which is what the first two attempts could not do.

    Pydantic coerces bytes to str AFTER a `mode="before"` validator runs, so
    `isinstance(value, str)` alone lets `b"  x  "` through untrimmed — the exact
    value the validator exists to refuse.

    Attempt one closed that with `decode("utf-8", "replace")` and made things
    worse: `b"\xff\xff\xff"` stopped being a clean 422 and became
    "\ufffd\ufffd\ufffd", three characters that SATISFY the very `min_length=3`
    on `RejectIn.reason` that its validator exists to enforce honestly. A
    rejection reason of three unreadable glyphs is worse than a refused request,
    so it was reverted and this test held the hole open on purpose, documented.

    Attempt two — a STRICT decode, handing undecodable bytes back untouched for
    Pydantic to refuse the way it already would — has neither cost. An audit is
    what made the difference: leaving it documented meant the same paragraph got
    written into a second module without the code underneath, which is worse
    than the gap it described.

    Neither case is reachable over JSON, which has no byte string.
    """
    # Invalid UTF-8 is still refused, and refused as bytes — no glyphs invented
    # to satisfy a length rule.
    with pytest.raises(ValueError):
        RejectIn(reason=b"\xff\xff\xff")

    # And valid UTF-8 is now trimmed like the string it is about to become.
    assert SettingsPatch(agency_name=b"  x  ").agency_name == "x"

    # The trim happens before `min_length`, so padding cannot buy length: three
    # spaces around one character is a 1-character reason, and refused.
    with pytest.raises(ValueError):
        RejectIn(reason=b"  x  ")
