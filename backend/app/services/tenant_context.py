"""Which organization the current task is acting for.

A ContextVar rather than a parameter threaded through every call: the value has
to reach `db/base.py`'s transaction hook, which sits far below the request
handlers and has no access to the request.

`None` is not "all orgs" — it is "no org". The RLS policies are default-deny, so
an unset value yields zero rows rather than everything. That asymmetry is the
whole point: a forgotten `SET` fails closed.

Two callers legitimately need to reach data outside any single org — the login
lookup (which resolves a user's org *before* an org is known) and the background
workers (which sweep every org). They do it through the bypass engine in
`db/base.py`, never by clearing this variable.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

_current_org_id: ContextVar[int | None] = ContextVar("current_org_id", default=None)


def get_org_id() -> int | None:
    return _current_org_id.get()


def set_org_id(org_id: int | None) -> None:
    _current_org_id.set(org_id)


@contextlib.contextmanager
def org_scope(org_id: int | None) -> Iterator[None]:
    """Run a block as `org_id`, restoring the previous value afterwards.

    Used by the workers, which walk many orgs inside one task and must not leak
    the last one they touched into whatever runs next on the same thread.
    """
    token = _current_org_id.set(org_id)
    try:
        yield
    finally:
        _current_org_id.reset(token)
