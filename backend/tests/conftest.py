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

import os

# WhatsApp is off by default in the application, deliberately: a channel with no
# credentials must not answer. The webhook tests drive that channel, so they
# need it on — and this has to happen before anything imports the app, because
# `Settings()` reads the environment once and every later call gets that same
# answer. A fixture is too late; by the time one runs, the value is decided.
#
# It lives here rather than in the developer's shell because that is what it was
# doing until now: the suite passed for whoever had the variable exported and
# failed for everyone else. CI has never run, and it would have gone red on its
# first attempt over exactly the five tests this line fixes.
#
# `setdefault`, so an operator deliberately testing the disabled path still can.
os.environ.setdefault("WHATSAPP_ENABLED", "true")

# And Groq's key is wiped, unconditionally — not `setdefault`.
#
# The health probe now calls a THIRD PARTY with a credential. Several tests
# drive the real startup path (`test_whatsapp_channel.py`) without patching
# httpx, and on any machine that exports GROQ_API_KEY — the ROG does, and so
# does anyone who ran the deploy — that reaches `api.groq.com` carrying the
# owner's live key. Until this fase the same path only ever touched a local
# Ollama on the LAN.
#
# This repo has paid for that shape before: a fallback that read the key from
# the home directory made any test without a stub buy an image, and pass green
# while doing it. One source for the credential, and inside the suite it is
# empty. A test that genuinely needs Groq configured sets it itself, with
# monkeypatch, and stubs the transport.
os.environ["GROQ_API_KEY"] = ""

# Blanked UNCONDITIONALLY, not `setdefault`: the new-lead notice now has a
# second transport, and several tests drive the real capture endpoint. On a
# machine that exports a bot token — the owner's does — a green suite would be
# sending real Telegram messages to the operator channel. A credential the
# tests can reach is a credential the tests will spend.
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""


import pytest  # noqa: E402 — must follow the environment default above

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
