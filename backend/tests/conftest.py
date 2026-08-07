"""Test fixtures shared across the suite.

Two autouse fixtures, both about state that leaks between tests.

The engine reset exists because pytest-asyncio gives each test its own event
loop while the engine singleton in `app.db.base` stays bound to the loop that
first touched it — the second test then sees:

  "got Future ... attached to a different loop"

The reset is cheap (engine + sessionmaker are recreated lazily on first
use of the next test), and keeps test isolation honest.

The tenant binding exists because every test that seeds rows directly needs an
acting organization: `org_id` is NOT NULL, and the RLS policies reject writes
that do not match the current org. In the running app the ASGI middleware binds
it per request; tests have no request, so they bind the default org here. Tests
that care about isolation override it — see `test_tenant_isolation.py`, which
deliberately switches orgs mid-test to prove rows do not cross.
"""
from __future__ import annotations

import pytest

from app.db.base import dispose_engine
from app.models.organization import DEFAULT_ORG_ID
from app.services.tenant_context import set_org_id


@pytest.fixture(autouse=True)
async def _reset_db_engine_between_tests() -> object:
    yield
    await dispose_engine()


@pytest.fixture(autouse=True)
def _bind_default_org() -> object:
    set_org_id(DEFAULT_ORG_ID)
    yield
    set_org_id(None)
