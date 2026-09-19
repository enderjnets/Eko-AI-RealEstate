"""The unsubscribe link, end to end through the real ASGI app.

The token itself and the footer are pure functions and live in
`test_email_compliance.py`. What needs live Postgres is the part that writes:
that a GET does NOT opt anybody out, that the POST does, and that a second click
cannot move the date the agency was first on notice.

Drives the actual endpoint rather than the function behind it, for the same
reason `test_new_lead_notice.py` does: the route is the thing that will be in an
email, and a helper handed a pre-bound tenant proves nothing about it.
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.base import get_bypass_session_factory
from app.main import app
from app.models.lead import Lead
from app.services.email_compliance import unsubscribe_token

ORG = 1
MARK = "%@unsub.test"


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


async def _seed(email: str) -> int:
    """Through the model, not raw SQL.

    An INSERT that lists columns by hand is a second, silent copy of the schema:
    the first draft of this helper left out `human_takeover` and every test in
    the file failed on a NOT NULL it had never heard of. The mapper knows the
    defaults. `org_id` is passed explicitly because a bypass session is not
    stamped by `before_flush`.
    """
    async with get_bypass_session_factory()() as db:
        lead = Lead(org_id=ORG, phone=f"+1999{os.urandom(3).hex()}", email=email)
        db.add(lead)
        await db.commit()
        return int(lead.id)


async def _opt_out_row(lead_id: int) -> dict:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(
                text(
                    "SELECT opted_out_at, opted_out_channel, opted_out_keyword "
                    "FROM leads WHERE id = :i"
                ),
                {"i": lead_id},
            )
        ).mappings().first()
        return dict(row) if row else {}


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM leads WHERE email LIKE :p"), {"p": MARK})
        await db.commit()


async def _call(method: str, token: str) -> int:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.request(method, f"/api/v1/public/unsubscribe/{token}")
    return r.status_code


@pytest.mark.asyncio
async def test_a_get_asks_and_does_not_act(database_url: str) -> None:
    """Every link-scanning security appliance opens a URL before its recipient
    does. A GET that unsubscribed on sight would silently remove people who
    never clicked anything — which is why RFC 8058 puts the action on POST."""
    lead_id = await _seed("prefetch@unsub.test")
    try:
        assert await _call("GET", unsubscribe_token(lead_id)) == 200
        assert (await _opt_out_row(lead_id))["opted_out_at"] is None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_post_honours_it_and_records_how(database_url: str) -> None:
    lead_id = await _seed("stop@unsub.test")
    try:
        assert await _call("POST", unsubscribe_token(lead_id)) == 200
        row = await _opt_out_row(lead_id)
        assert row["opted_out_at"] is not None
        assert row["opted_out_channel"] == "email"
        assert row["opted_out_keyword"] == "unsubscribe-link"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_first_opt_out_keeps_the_date(database_url: str) -> None:
    """The same rule the STOP path in `conversation.py` states: the day the
    agency was first on notice is the difference between one violation and
    thirty, and a second click must not reset it."""
    lead_id = await _seed("twice@unsub.test")
    try:
        token = unsubscribe_token(lead_id)
        assert await _call("POST", token) == 200
        first = (await _opt_out_row(lead_id))["opted_out_at"]
        assert await _call("POST", token) == 200
        assert (await _opt_out_row(lead_id))["opted_out_at"] == first
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_forged_token_changes_nothing_and_still_answers_200(
    database_url: str,
) -> None:
    """Same page for a signature we did not write, so a stranger cannot learn
    which lead ids exist — and a mail client doing one-click needs the 2xx or it
    tells the reader the unsubscribe failed."""
    lead_id = await _seed("forged@unsub.test")
    try:
        good = unsubscribe_token(lead_id)
        forged = good.split(".")[0] + ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        assert await _call("POST", forged) == 200
        assert (await _opt_out_row(lead_id))["opted_out_at"] is None
        assert await _call("POST", "not-even-a-token") == 200
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_token_for_a_lead_that_is_gone_is_not_an_error(database_url: str) -> None:
    lead_id = await _seed("deleted@unsub.test")
    await _cleanup()
    assert await _call("POST", unsubscribe_token(lead_id)) == 200
