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
def _config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PLATFORM_ADMIN_EMAILS", "operador@example.com")
    monkeypatch.setenv("OPS_ALERT_FROM", "alertas@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "re_dummy")
    monkeypatch.setenv("EMAIL_SIMULATED", "false")
    # Explicit, not ambient. Every assertion below about "the email half" is
    # only true while Telegram cannot deliver, and leaving that to whatever
    # happens to be in the developer's environment is how a suite ends up
    # posting to the owner's real chat.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    # `monkeypatch` restores the environment but nothing clears the LRU, so a
    # Settings built from a test's overrides would outlive it and be handed to
    # the next module.
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


@pytest.fixture
def _telegram_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:dummy")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99")
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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


@pytest.mark.asyncio
async def test_simulated_mode_does_not_reach_telegram_either(
    monkeypatch: pytest.MonkeyPatch, _telegram_configured
) -> None:
    """`EMAIL_SIMULATED` gates the mail half only, so a developer machine with a
    real bot token would post to the owner's actual chat on every alert while
    believing nothing left the building. The second transport has to honour the
    same switch or "simulated" is a lie about half the system."""
    monkeypatch.setenv("EMAIL_SIMULATED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    factory, client = _dual_http()
    with patch.object(ops_alert.httpx, "AsyncClient", factory):
        assert await send_operator_alert("asunto", "cuerpo") is True
    client.post.assert_not_awaited()


# ── "this attempt failed" vs "no attempt can succeed" ──────────────────────


@pytest.mark.asyncio
async def test_a_fully_configured_channel_reports_no_reason() -> None:
    assert ops_alert.undeliverable_reason() is None


@pytest.mark.parametrize(
    "unset,expected",
    [
        ("PLATFORM_ADMIN_EMAILS", "PLATFORM_ADMIN_EMAILS"),
        ("OPS_ALERT_FROM", "OPS_ALERT_FROM"),
        ("RESEND_API_KEY", "RESEND_API_KEY"),
    ],
)
def test_each_missing_setting_is_named_so_the_log_is_actionable(
    monkeypatch: pytest.MonkeyPatch, unset: str, expected: str
) -> None:
    """The caller writes this straight into a log line. "not configured" sends
    somebody hunting through three files; the name of the setting does not."""
    monkeypatch.setenv(unset, "")
    from app.config import get_settings
    get_settings.cache_clear()

    reason = ops_alert.undeliverable_reason()
    assert reason is not None and expected in reason


# ── two transports, because one is a single point of silence ───────────────
#
# Measured on 5-sep-2026: `monitor_state.llm_fallback` held `state=unreachable`
# with `alerted_state=ok` and all three daily attempts spent. The operator was
# never told the safety net had gone. Email was the only way out.


def _dual_http(email_status: int = 200, telegram_status: int = 200):
    """One fake client for BOTH transports, routed by URL.

    `ops_alert.httpx` and `telegram_notify.httpx` are the *same module object*,
    so patching `AsyncClient` on one patches it for the other and the second
    patch silently wins — which is how the first draft of these tests had email
    quietly using Telegram's double and asserting nothing. One client that
    answers differently per destination is the only honest way to drive both.
    """
    def answer(url, **_kwargs):
        resp = MagicMock()
        telegram = "telegram" in str(url)
        resp.status_code = telegram_status if telegram else email_status
        resp.text = "" if resp.status_code < 400 else "rechazado"
        return resp

    client = MagicMock()
    client.post = AsyncMock(side_effect=answer)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx), client


def _posts_to(client, needle: str) -> list:
    return [c for c in client.post.await_args_list if needle in str(c.args[0])]


@pytest.mark.asyncio
async def test_telegram_delivers_when_email_is_rejected(
    _telegram_configured, caplog: pytest.LogCaptureFixture
) -> None:
    """MUTATION GUARD — make `send_operator_alert` try only email and this goes
    red. It is the whole point of the phase: a fault in one channel must not
    produce silence."""
    factory, client = _dual_http(email_status=429, telegram_status=200)
    with caplog.at_level("WARNING"), patch.object(ops_alert.httpx, "AsyncClient", factory):
        assert await send_operator_alert("asunto", "cuerpo") is True

    to_telegram = _posts_to(client, "telegram")
    assert len(to_telegram) == 1
    assert "one channel only" in caplog.text, \
        "degradar a un solo canal es justo el estado del que veniamos"
    sent = to_telegram[0].kwargs["json"]
    assert sent["chat_id"] == "99"
    assert "asunto" in sent["text"] and "cuerpo" in sent["text"]


@pytest.mark.asyncio
async def test_both_channels_are_tried_on_every_alert(_telegram_configured) -> None:
    """Not one as a standby for the other. A channel only tried when the first
    *reports* failure is no help when the first fails by reporting a success it
    did not achieve."""
    factory, client = _dual_http()
    with patch.object(ops_alert.httpx, "AsyncClient", factory):
        assert await send_operator_alert("asunto", "cuerpo") is True

    assert len(_posts_to(client, "resend")) == 1
    assert len(_posts_to(client, "telegram")) == 1


@pytest.mark.asyncio
async def test_both_failing_is_a_false_return_and_a_loud_log(
    _telegram_configured, caplog: pytest.LogCaptureFixture
) -> None:
    factory, client = _dual_http(email_status=500, telegram_status=400)
    with caplog.at_level("ERROR"), patch.object(ops_alert.httpx, "AsyncClient", factory):
        assert await send_operator_alert("asunto", "cuerpo") is False

    assert len(_posts_to(client, "resend")) == 1, "lo intento por correo"
    assert len(_posts_to(client, "telegram")) == 1, "y por Telegram"
    assert "reached NOBODY" in caplog.text


@pytest.mark.asyncio
async def test_telegram_alone_is_enough_to_be_deliverable(
    monkeypatch: pytest.MonkeyPatch, _telegram_configured
) -> None:
    """An install with no mail sender is not a reason to give up on the alert
    while the owner's phone still works."""
    monkeypatch.setenv("OPS_ALERT_FROM", "")
    from app.config import get_settings
    get_settings.cache_clear()

    assert ops_alert.undeliverable_reason() is None


def test_when_nothing_can_deliver_the_reason_names_both_halves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator fixing this needs to know what is missing on each side,
    not one name at a time."""
    monkeypatch.setenv("OPS_ALERT_FROM", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    from app.config import get_settings
    get_settings.cache_clear()

    reason = ops_alert.undeliverable_reason()
    assert reason is not None
    assert "OPS_ALERT_FROM" in reason and "TELEGRAM_BOT_TOKEN" in reason


@pytest.mark.asyncio
async def test_a_transport_that_raises_does_not_stop_the_other(
    _telegram_configured, caplog: pytest.LogCaptureFixture
) -> None:
    """MUTATION GUARD — drop the `_guarded` wrapper and this goes red.

    Both halves are written never to raise, but "written never to raise" is the
    same class of claim as `OLLAMA_ENABLED=true`: an assertion about the world
    that nothing checks. If the mail half ever escapes, the cost is doubled and
    absurd — Telegram is never tried, which is exactly the single point of
    silence this phase existed to remove, and the exception climbs into the
    watchdog tick and aborts it before it commits.
    """
    async def explode(subject: str, body: str) -> bool:
        raise OSError("resolver down")

    tg, client = _dual_http()
    with caplog.at_level("ERROR"), \
         patch.object(ops_alert, "_send_email", explode), \
         patch.object(ops_alert.httpx, "AsyncClient", tg):
        assert await send_operator_alert("asunto", "cuerpo") is True

    assert len(_posts_to(client, "telegram")) == 1, "el segundo transporte SI se intento"
    assert "transport email raised" in caplog.text
