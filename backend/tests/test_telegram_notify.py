"""The doorbell for the approval queue.

What is worth holding here is narrow: the message says WHERE to look and never
what the video says, a failure cannot cost a render, and an unconfigured
channel does not touch the network at all.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.services import telegram_notify


@pytest.fixture(autouse=True)
def _clean_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _configured(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    monkeypatch.setenv("CONTENT_PUBLIC_BASE_URL", "https://panel.example.com")
    get_settings.cache_clear()


class _Response:
    def __init__(self, status_code: int = 200, text: str = "{}") -> None:
        self.status_code = status_code
        self.text = text


class _Client:
    """Records what would have gone to Telegram. Nothing leaves the process."""

    sent: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url, json=None, **kwargs):
        _Client.sent.append({"url": url, "json": json})
        return _Response()


@pytest.mark.asyncio
async def test_the_notice_says_where_to_look_and_not_what_it_says(
    monkeypatch,
) -> None:
    """The line the AST sweep's exemption is written on. A message carrying the
    hook invites approving from a phone without watching the video, and the
    gate exists precisely so that somebody watches."""
    _configured(monkeypatch)
    _Client.sent = []
    monkeypatch.setattr(telegram_notify.httpx, "AsyncClient", _Client)

    assert await telegram_notify.notify_video_ready(42, waiting=3) is True
    assert len(_Client.sent) == 1
    body = _Client.sent[0]["json"]
    assert body["chat_id"] == "555"
    assert "42" in body["text"]
    assert "https://panel.example.com/content" in body["text"]
    # The bot's identity is in the URL, never in the body.
    assert "123:abc" in _Client.sent[0]["url"]


@pytest.mark.asyncio
async def test_an_unconfigured_channel_does_not_touch_the_network(
    monkeypatch,
) -> None:
    """Asked before any call, so it is free — and asserting that nothing was
    SENT rather than that nothing raised is the difference between a guard and
    a hope."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    get_settings.cache_clear()
    _Client.sent = []
    monkeypatch.setattr(telegram_notify.httpx, "AsyncClient", _Client)

    assert await telegram_notify.notify_video_ready(1, waiting=1) is False
    assert _Client.sent == []


@pytest.mark.asyncio
async def test_a_refusal_is_not_read_as_delivery(monkeypatch) -> None:
    _configured(monkeypatch)

    class _Refuses(_Client):
        async def post(self, url, json=None, **kwargs):
            return _Response(status_code=403, text="forbidden")

    monkeypatch.setattr(telegram_notify.httpx, "AsyncClient", _Refuses)
    assert await telegram_notify.notify_video_ready(7, waiting=1) is False


@pytest.mark.asyncio
async def test_a_network_failure_is_reported_not_raised(monkeypatch) -> None:
    """It runs on the path that just delivered a finished render."""
    _configured(monkeypatch)

    class _Breaks(_Client):
        async def post(self, url, json=None, **kwargs):
            raise telegram_notify.httpx.ConnectError("no route")

    monkeypatch.setattr(telegram_notify.httpx, "AsyncClient", _Breaks)
    assert await telegram_notify.notify_video_ready(7, waiting=1) is False
