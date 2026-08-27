"""One answer to "is this a usable IANA timezone?", for the whole product.

This module exists because the answer was previously held in four separate
places, and the copy that reached the newest one was wrong.

`ZoneInfo` does not raise one exception type. It raises **three** unrelated
ones, and every call site in this repo caught two of them:

    ZoneInfo("Mars/Phobos")   ZoneInfoNotFoundError   (a KeyError)
    ZoneInfo("/etc/passwd")   ValueError
    ZoneInfo("America")       IsADirectoryError       (an OSError)
    ZoneInfo("A" * 300)       OSError, [Errno 63] File name too long

The first two were caught. The third was not, so a caller-supplied timezone of
300 characters left `except (ZoneInfoNotFoundError, ValueError)` untouched and
came back as HTTP 500. On the endpoint that had no validator at all, the same
string was a clean 422 from `max_length` — so adding the validator made that
input strictly worse. A guard that turns a 422 into a 500 is not a guard.

`OSError` is caught deliberately and not narrowed to `IsADirectoryError`: the
name is attacker-supplied and reaches the filesystem, and "the zone is not
usable" is the honest answer for every way that lookup can fail. The trade is
that a genuinely broken tzdata install reads as "unknown zone" instead of
crashing; `resolve_zone` is the one place that would have to change if that
ever needs telling apart, which is the whole point of it being one place.

Case sensitivity is the host's, not Python's — `ZoneInfo` reads tzdata off the
filesystem. `america/denver` resolves on a case-insensitive macOS volume and
raises in the Linux container that runs production, so **local is the more
permissive of the two** and a test can go green here on a string production
will refuse. Nothing here depends on that difference; it is written down so the
next person to meet it does not spend an afternoon on it.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The complete surface, measured rather than remembered. Anything `ZoneInfo`
# can throw for a name means the same thing to every caller: not usable.
_ZONE_ERRORS = (ZoneInfoNotFoundError, ValueError, OSError)


def resolve_zone(name: object) -> ZoneInfo | None:
    """The zone for `name`, or None when it is not one we can use.

    Never raises. Callers decide what an unusable zone means for them — a 400
    to whoever sent it, a spoken apology mid-call, a refusal to write a time —
    but none of them has to know how the lookup can fail.

    `bytes` is accepted because Pydantic coerces `bytes` to `str` **after** a
    `mode="before"` validator runs, so a caller guarding on `isinstance(v, str)`
    alone hands us the raw bytes. Rejecting them outright would refuse a value
    the model is about to accept, so they are decoded the same way Pydantic
    will decode them and judged on the result.
    """
    if isinstance(name, bytes):
        try:
            name = name.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(name, str):
        return None
    try:
        return ZoneInfo(name)
    except _ZONE_ERRORS:
        return None
