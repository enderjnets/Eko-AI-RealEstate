"""`ZoneInfo` raises three unrelated exception types, and this repo caught two.

Every timezone call site in the product used to hold its own copy of "how can
this fail", and the copy that reached the newest one was incomplete: it caught
`ZoneInfoNotFoundError` and `ValueError` and let `OSError` through. The result
was HTTP 500 on caller-supplied input that had previously been a clean 422.

These tests pin the surface itself, so the next call site cannot inherit a
narrower version of it.
"""
from __future__ import annotations

import pytest

from app.services.timezones import resolve_zone

# Each entry is a name and the exception `ZoneInfo` raises for it. The point of
# listing the exception is that they are NOT one family: KeyError, ValueError
# and OSError have no common ancestor short of Exception, which is why a
# hand-written `except` tuple kept missing one.
UNUSABLE = [
    ("Mars/Phobos", "ZoneInfoNotFoundError (a KeyError)"),
    ("America", "IsADirectoryError (an OSError) — a tzdata directory"),
    ("Etc", "IsADirectoryError — short enough to look like a real zone"),
    ("A" * 300, "OSError, [Errno 63] File name too long"),
    ("/etc/passwd", "ValueError — absolute path"),
    ("../../etc/passwd", "ValueError — traversal"),
    ("x\x00y", "ValueError — null byte"),
    ("", "ValueError — empty"),
]


@pytest.mark.parametrize(("name", "why"), UNUSABLE)
def test_an_unusable_name_comes_back_as_none_and_never_raises(
    name: str, why: str
) -> None:
    """One answer for every way the lookup can fail.

    `resolve_zone` is the only place allowed to know this list. Its callers
    decide what None means for them — a 400, a spoken apology, a refusal to
    write a time — but none of them has to enumerate exception types, which is
    the mistake this module exists to make unrepeatable.
    """
    assert resolve_zone(name) is None, f"{name[:20]!r} should be unusable: {why}"


def test_a_real_zone_still_resolves() -> None:
    """The instrument has to be able to say yes, or it proves nothing."""
    zone = resolve_zone("America/Denver")
    assert zone is not None
    assert str(zone) == "America/Denver"


def test_bytes_are_decoded_rather_than_refused() -> None:
    """Pydantic coerces bytes to str AFTER a `mode="before"` validator runs.

    A caller guarding on `isinstance(v, str)` alone therefore hands us raw
    bytes, and refusing them outright would reject a value the model is about
    to accept. Judged on the decoded text instead.
    """
    assert str(resolve_zone(b"America/Denver")) == "America/Denver"
    assert resolve_zone(b"Invented/Zone") is None
    assert resolve_zone(b"\xff\xfe") is None  # undecodable is not a zone either


def test_a_non_string_is_not_a_zone() -> None:
    """`mode="before"` sees whatever was sent, including the wrong type."""
    for value in (None, 42, [], {"tz": "America/Denver"}):
        assert resolve_zone(value) is None
