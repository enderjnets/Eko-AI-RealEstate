"""Test fixtures shared across the suite.

The only autouse fixture here resets the cached async DB engine after every
test. Without this, pytest-asyncio gives each test its own event loop while
the engine singleton in `app.db.base` stays bound to the loop that first
touched it — the second test then sees:

  "got Future ... attached to a different loop"

The reset is cheap (engine + sessionmaker are recreated lazily on first
use of the next test), and keeps test isolation honest.
"""
from __future__ import annotations

import pytest

from app.db.base import dispose_engine


@pytest.fixture(autouse=True)
async def _reset_db_engine_between_tests() -> object:
    yield
    await dispose_engine()
