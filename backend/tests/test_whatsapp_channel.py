"""WhatsApp is a channel this install does not have, and says so.

The brokerage is in the United States: clients are reached by text, call and
email. That makes "WhatsApp, simulated, pending credentials" the wrong resting
state — it is a channel that is off, and the product should behave like it.

The reason this needs a guard rather than a comment: `WHATSAPP_SIMULATED` gates
two unrelated things. Outbound sending, and INBOUND HMAC verification. So the
obvious reading of the old instruction — "never ship SIMULATED=true to a
customer" — leads an operator to set it false, which with an empty app secret
does not go live. It makes every inbound webhook return 403 until Meta disables
the subscription, and it removes the one startup line that mentioned WhatsApp,
so the install ends up quieter and more broken than it was.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.main import app, whatsapp_is_half_configured


def _settings(**overrides: object) -> object:
    base = {
        "WHATSAPP_ENABLED": False,
        "WHATSAPP_SIMULATED": True,
        "WHATSAPP_APP_SECRET": "",
        "WHATSAPP_ACCESS_TOKEN": "",
        "WHATSAPP_PHONE_NUMBER_ID": "",
    }
    base.update(overrides)
    return type("S", (), base)


# ── The startup guard ────────────────────────────────────────────────────


def test_disabled_is_always_fine() -> None:
    assert whatsapp_is_half_configured(_settings()) is None
    assert whatsapp_is_half_configured(_settings(WHATSAPP_SIMULATED=False)) is None


def test_enabled_and_simulated_is_fine() -> None:
    # Dev, and the test suite itself. Nothing reaches Meta, nothing verifies.
    assert whatsapp_is_half_configured(_settings(WHATSAPP_ENABLED=True)) is None


def test_enabled_and_live_with_empty_secrets_refuses() -> None:
    """The trap. This combination used to start happily and kill inbound."""
    reason = whatsapp_is_half_configured(
        _settings(WHATSAPP_ENABLED=True, WHATSAPP_SIMULATED=False)
    )
    assert reason is not None
    # The message has to name what is missing and what to do, because the
    # symptom it prevents — Meta disabling the subscription days later — gives
    # the operator nothing to work from.
    assert "WHATSAPP_APP_SECRET" in reason
    assert "WHATSAPP_ACCESS_TOKEN" in reason
    assert "WHATSAPP_PHONE_NUMBER_ID" in reason
    assert "403" in reason


def test_one_missing_secret_is_still_refused() -> None:
    reason = whatsapp_is_half_configured(
        _settings(
            WHATSAPP_ENABLED=True,
            WHATSAPP_SIMULATED=False,
            WHATSAPP_ACCESS_TOKEN="tok",
            WHATSAPP_PHONE_NUMBER_ID="123",
        )
    )
    assert reason is not None and "WHATSAPP_APP_SECRET" in reason


def test_whitespace_is_not_a_secret() -> None:
    reason = whatsapp_is_half_configured(
        _settings(
            WHATSAPP_ENABLED=True,
            WHATSAPP_SIMULATED=False,
            WHATSAPP_APP_SECRET="   ",
            WHATSAPP_ACCESS_TOKEN="tok",
            WHATSAPP_PHONE_NUMBER_ID="123",
        )
    )
    assert reason is not None and "WHATSAPP_APP_SECRET" in reason


def test_fully_configured_starts() -> None:
    assert (
        whatsapp_is_half_configured(
            _settings(
                WHATSAPP_ENABLED=True,
                WHATSAPP_SIMULATED=False,
                WHATSAPP_APP_SECRET="sec",
                WHATSAPP_ACCESS_TOKEN="tok",
                WHATSAPP_PHONE_NUMBER_ID="123",
            )
        )
        is None
    )


# ── The channel is off by default ────────────────────────────────────────


def test_the_shipped_default_is_off() -> None:
    # Read from the class, not from the environment, so CI setting it true for
    # the rest of the suite cannot hide a change to what an install gets.
    assert Settings.model_fields["WHATSAPP_ENABLED"].default is False


@pytest.mark.asyncio
async def test_a_disabled_channel_does_not_accept_inbound() -> None:
    """A channel that is off must not keep creating leads.

    404 rather than 200: nobody should be pointing Meta at this endpoint, and
    answering 200 would tell them the delivery succeeded while the message went
    nowhere a person will read.
    """
    settings = get_settings()
    original = settings.WHATSAPP_ENABLED
    settings.WHATSAPP_ENABLED = False
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/webhooks/whatsapp",
                json={"entry": [{"changes": [{"value": {"messages": []}}]}]},
            )
        assert response.status_code == 404
        assert response.json()["detail"] == "whatsapp_not_enabled"
    finally:
        settings.WHATSAPP_ENABLED = original


@pytest.mark.asyncio
async def test_the_startup_actually_calls_the_guard() -> None:
    """A guard nothing invokes is a comment.

    Every test above exercises `whatsapp_is_half_configured` directly, and all
    of them would still pass if the call had never been added to `_startup`.
    Mutation found exactly that: deleting the two lines that raise left this
    file green.
    """
    import app.main as main_module

    # `main_module.settings`, not `get_settings()`. They are normally the same
    # object, but another test in the suite reloads the module, after which
    # `_startup` reads a different instance — so mutating the cached singleton
    # changed nothing and this test passed alone and failed in the suite.
    # Target what the code under test actually reads.
    _startup = main_module._startup
    settings = main_module.settings
    before = (
        settings.WHATSAPP_ENABLED,
        settings.WHATSAPP_SIMULATED,
        settings.WHATSAPP_APP_SECRET,
    )
    settings.WHATSAPP_ENABLED = True
    settings.WHATSAPP_SIMULATED = False
    settings.WHATSAPP_APP_SECRET = ""
    try:
        with pytest.raises(RuntimeError, match="WHATSAPP_APP_SECRET"):
            await _startup()
    finally:
        (
            settings.WHATSAPP_ENABLED,
            settings.WHATSAPP_SIMULATED,
            settings.WHATSAPP_APP_SECRET,
        ) = before


@pytest.mark.asyncio
async def test_no_warning_about_a_channel_this_install_does_not_use(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A warning that is always there is a warning nobody reads.

    This one fired on every restart of every production install, including the
    ones that will never send a WhatsApp message, and it pointed at the exact
    change that would break inbound. Scoped to installs where the channel is
    actually enabled.
    """
    import logging

    import app.main as main_module

    settings = main_module.settings
    before = (settings.WHATSAPP_ENABLED, settings.WHATSAPP_SIMULATED, settings.APP_ENV)
    settings.WHATSAPP_ENABLED = False
    settings.WHATSAPP_SIMULATED = True
    settings.APP_ENV = "production"
    try:
        with caplog.at_level(logging.WARNING, logger="app.main"):
            await main_module._startup()
        assert not [
            r for r in caplog.records if "WHATSAPP_SIMULATED" in r.getMessage()
        ], "warned about a channel that is switched off"

        # And it DOES warn when the channel is on, because then it is true.
        caplog.clear()
        settings.WHATSAPP_ENABLED = True
        with caplog.at_level(logging.WARNING, logger="app.main"):
            await main_module._startup()
        assert [r for r in caplog.records if "WHATSAPP_SIMULATED" in r.getMessage()]
    finally:
        (
            settings.WHATSAPP_ENABLED,
            settings.WHATSAPP_SIMULATED,
            settings.APP_ENV,
        ) = before


def test_per_org_credentials_are_not_refused() -> None:
    """Refusing a WORKING configuration is its own outage.

    Credentials can live per-organization in `channel_routes.credential_ref`
    rather than in the global `.env` — that is the multi-tenant shape the whole
    channel_identity module exists for. A guard that reads only the globals
    would crash-loop an install that is correctly configured, which is a worse
    failure than the one it was written to prevent.
    """
    assert (
        whatsapp_is_half_configured(
            _settings(WHATSAPP_ENABLED=True, WHATSAPP_SIMULATED=False),
            credentials_are_routed=True,
        )
        is None
    )
    # And with nothing routed, the same input is still refused.
    assert (
        whatsapp_is_half_configured(
            _settings(WHATSAPP_ENABLED=True, WHATSAPP_SIMULATED=False),
            credentials_are_routed=False,
        )
        is not None
    )


@pytest.mark.asyncio
async def test_the_route_probe_answers_false_when_nothing_is_routed() -> None:
    from app.main import _whatsapp_credentials_are_routed

    assert await _whatsapp_credentials_are_routed() is False


@pytest.mark.asyncio
async def test_an_sms_route_does_not_satisfy_the_whatsapp_check() -> None:
    """The escape hatch has to be channel-scoped, and nothing checked that.

    Dropping `channel = 'whatsapp'` from the probe left every test green, and
    the consequence is the exact outage the guard exists to prevent: an install
    that routes SMS per-org but has no WhatsApp credentials would be waved
    through into live mode, where every inbound WhatsApp returns 403.
    """
    from sqlalchemy import text as _text

    from app.db.base import get_bypass_session_factory
    from app.main import _whatsapp_credentials_are_routed

    async with get_bypass_session_factory()() as db:
        await db.execute(
            _text(
                "INSERT INTO channel_routes (org_id, channel, destination, "
                "credential_ref) VALUES (1, 'sms', '+19995557001', 'SOME_REF')"
            )
        )
        await db.commit()
    try:
        assert await _whatsapp_credentials_are_routed() is False
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                _text("DELETE FROM channel_routes WHERE destination = '+19995557001'")
            )
            await db.commit()
