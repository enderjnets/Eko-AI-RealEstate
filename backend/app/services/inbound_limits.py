"""Budgets for mail arriving from the open internet.

The email channel went live on 2026-09-19 and `hello@denverhomestory.com` is now
reachable by anyone. Every message that gets through costs two LLM calls (the
classifier and the reply) and one outbound send, and produces a lead row. Until
today nothing bounded that.

**Three tiers, charged in this order, each returning before the next is spent:**

  sender → domain → global

The order is the whole design, and it is borrowed from an incident this repo
already paid for. `api/v1/public.py` used to charge its platform-wide budget
FIRST, which turned it into a kill switch anyone could hold down: sixty tokenless
posts from sixty forged addresses were each refused and each still consumed a
slot, so lead capture went down for every agency on the install for ten minutes.
A request may only spend the shared budget once it has proven it is worth
processing.

**Why the sender tier is the weakest one, stated plainly.** An IP costs something
to rotate; a `From:` header costs nothing. Worse, `parse_inbound_email` reads no
SPF or DKIM verdict, so we cannot tell a real sender from a forged one — the
sender bucket stops a naive loop and nothing else. The domain tier is what makes
rotation cost something, and the global tier is the backstop. None of them are
authentication and this module does not pretend otherwise.

In-process and per-worker, like `public.py`'s. That is sound here and only here:
`CLAUDE.md` makes one backend replica a hard precondition for this install, and
it was verified as one container on 2026-09-19. A second replica silently halves
every number below.
"""
from __future__ import annotations

import logging
import time
from collections import deque

log = logging.getLogger(__name__)

# One sender, one quarter of an hour. A person writing in, then following up
# twice, then correcting themselves is four; five leaves room to be human.
SENDER_LIMIT = 5
SENDER_WINDOW = 900.0

# The tier that makes address rotation cost something. Twenty in a quarter of an
# hour from ONE domain is already far beyond a two-agent brokerage — and gmail.com
# is a domain, which is why this is not tighter.
DOMAIN_LIMIT = 20
DOMAIN_WINDOW = 900.0

# The backstop, charged last. Generous on purpose: the measured traffic on this
# channel is a handful of messages a month, so anything approaching this number
# is an attack and the point is to survive it, not to meter honest use.
GLOBAL_LIMIT = 200
GLOBAL_WINDOW = 3600.0

_sender_hits: dict[str, deque[float]] = {}
_domain_hits: dict[str, deque[float]] = {}
_global_hits: deque[float] = deque()


def _prune(hits: deque[float], now: float, window: float) -> None:
    while hits and now - hits[0] > window:
        hits.popleft()


def _charge(bucket: dict[str, deque[float]], key: str, limit: int, window: float, now: float) -> bool:
    """Charge `key` against its bucket. True when the budget is already spent."""
    hits = bucket.setdefault(key, deque())
    _prune(hits, now, window)
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


def _domain_of(address: str) -> str:
    _, _, domain = address.rpartition("@")
    return domain.casefold() or "(none)"


def over_budget(sender: str | None, *, now: float | None = None) -> str | None:
    """Charge this inbound message. Returns the tier that refused it, or None.

    A message with no readable sender is charged as one shared bucket rather
    than waved through: an empty `From:` is the cheapest possible forgery, and
    letting it skip the meter would make the meter optional.
    """
    stamp = time.monotonic() if now is None else now
    address = (sender or "").strip().casefold() or "(unknown)"

    if _charge(_sender_hits, address, SENDER_LIMIT, SENDER_WINDOW, stamp):
        return "sender"
    if _charge(_domain_hits, _domain_of(address), DOMAIN_LIMIT, DOMAIN_WINDOW, stamp):
        return "domain"

    # Last, and only now: the two cheap tiers have already turned away everything
    # they can, so what reaches here has earned a slot in the shared budget.
    _prune(_global_hits, stamp, GLOBAL_WINDOW)
    if len(_global_hits) >= GLOBAL_LIMIT:
        return "global"
    _global_hits.append(stamp)
    return None


def reset_inbound_limits() -> None:
    """Test seam. Nothing in the app calls this."""
    _sender_hits.clear()
    _domain_hits.clear()
    _global_hits.clear()
