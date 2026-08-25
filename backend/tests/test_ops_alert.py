"""Tests for the operator alert channel.

Two properties matter here and neither is "the email is pretty":

**It never raises.** It is called from a background worker whose real job is to
keep watching. A watchdog that dies because its transport was misconfigured
stops watching, and the outage it was built for then passes unseen.

**It never borrows a tenant's mailbox.** `send_email()` resolves the acting
organization's identity so agency B's lead is never answered from agency A's
address. A monitor has no acting organization, and an alert to the operator is
not a reply to anybody's lead.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import ops_alert
from app.services.ops_alert import send_operator_alert


@pytest.fixture(autouse=True)
def _config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "operador@example.com")
    monkeypatch.setenv("OPS_ALERT_FROM", "alertas@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "re_dummy")
    monkeypatch.setenv("EMAIL_SIMULATED", "false")
    from app.config import get_settings
    get_settings.cache_clear()


def _http(status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = "" if status < 400 else "quota exceeded"
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx), client


@pytest.mark.asyncio
async def test_sends_to_the_platform_operators_from_its_own_sender() -> None:
    factory, client = _http()
    with patch.object(ops_alert.httpx, "AsyncClient", factory):
        assert await send_operator_alert("asunto", "cuerpo") is True

    body = client.post.await_args.kwargs["json"]
    assert body["to"] == ["operador@example.com"]
    assert body["from"] == "alertas@example.com"


@pytest.mark.asyncio
async def test_unset_sender_is_reported_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A monitor that can reach nobody is exactly the kind of thing that looks
    fine for three months. It has to say so, and it has to keep running."""
    monkeypatch.setenv("OPS_ALERT_FROM", "")
    from app.config import get_settings
    get_settings.cache_clear()

    factory, client = _http()
    with caplog.at_level("ERROR"), patch.object(ops_alert.httpx, "AsyncClient", factory):
        assert await send_operator_alert("asunto", "cuerpo") is False

    client.post.assert_not_awaited()
    assert "OPS_ALERT_FROM" in caplog.text


@pytest.mark.asyncio
async def test_no_recipients_is_reported_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "")
    from app.config import get_settings
    get_settings.cache_clear()

    with caplog.at_level("ERROR"):
        assert await send_operator_alert("asunto", "cuerpo") is False
    assert "PLATFORM_ADMIN_EMAILS" in caplog.text


@pytest.mark.asyncio
async def test_a_provider_rejection_is_a_false_return_not_an_exception() -> None:
    """Quota exhausted is the expected rejection, and it must not kill the loop."""
    factory, _ = _http(status=429)
    with patch.object(ops_alert.httpx, "AsyncClient", factory):
        assert await send_operator_alert("asunto", "cuerpo") is False


@pytest.mark.asyncio
async def test_a_dead_transport_never_escapes() -> None:
    """MUTATION GUARD — drop the try/except around the POST and this goes red.
    The watcher must outlive its own transport."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=OSError("network unreachable"))
    ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(ops_alert.httpx, "AsyncClient", MagicMock(return_value=ctx)):
        assert await send_operator_alert("asunto", "cuerpo") is False


@pytest.mark.asyncio
async def test_simulated_mode_does_not_touch_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAIL_SIMULATED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    factory, client = _http()
    with patch.object(ops_alert.httpx, "AsyncClient", factory):
        assert await send_operator_alert("asunto", "cuerpo") is True
    client.post.assert_not_awaited()
