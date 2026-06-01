"""Tests for app.services.llm.generate_reply — fallback behavior under mock.

We patch AsyncAnthropic inside the llm module so no real HTTP calls happen.
Tests cover:
  1. Primary succeeds → fallback never invoked, returned provider == primary.
  2. Primary raises TimeoutException → fallback invoked → returned provider == fallback.
  3. Both providers fail → raises LLMUnavailable.
  4. Primary not configured (empty key) → falls straight to fallback.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import llm as llm_module
from app.services.llm import LLMUnavailable, generate_reply


def _fake_response(text: str, in_tok: int = 12, out_tok: int = 34) -> MagicMock:
    """Build a MagicMock that quacks like anthropic.types.Message."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    usage = MagicMock()
    usage.input_tokens = in_tok
    usage.output_tokens = out_tok
    resp.usage = usage
    return resp


def _client_with(create_side_effect: Any) -> MagicMock:
    """Build a MagicMock AsyncAnthropic whose messages.create has the given side_effect."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=create_side_effect)
    return client


@pytest.fixture(autouse=True)
def _force_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject dummy keys so the configured-check passes for both providers."""
    monkeypatch.setenv("KIMI_API_KEY", "dummy-kimi-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "dummy-minimax-key")
    # Clear the lru_cache on get_settings so the new env vars apply.
    from app.config import get_settings
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_primary_succeeds_no_fallback() -> None:
    primary_client = _client_with([_fake_response("Hola desde Kimi")])
    fallback_client = _client_with([_fake_response("Hola desde MiniMax")])

    def builder(cfg: Any, *, timeout: float) -> Any:
        return primary_client if cfg.name == "kimi" else fallback_client

    with patch.object(llm_module, "_build_client", side_effect=builder):
        result = await generate_reply(messages=[{"role": "user", "content": "hi"}])

    assert result.provider == "kimi"
    assert result.text == "Hola desde Kimi"
    primary_client.messages.create.assert_awaited_once()
    fallback_client.messages.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_primary_timeout_falls_back() -> None:
    primary_client = _client_with(httpx.TimeoutException("simulated timeout"))
    fallback_client = _client_with([_fake_response("Hola desde MiniMax")])

    def builder(cfg: Any, *, timeout: float) -> Any:
        return primary_client if cfg.name == "kimi" else fallback_client

    with patch.object(llm_module, "_build_client", side_effect=builder):
        result = await generate_reply(messages=[{"role": "user", "content": "hi"}])

    assert result.provider == "minimax"
    assert result.text == "Hola desde MiniMax"
    primary_client.messages.create.assert_awaited_once()
    fallback_client.messages.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_both_fail_raises_unavailable() -> None:
    primary_client = _client_with(httpx.TimeoutException("primary down"))
    fallback_client = _client_with(httpx.TimeoutException("fallback down"))

    def builder(cfg: Any, *, timeout: float) -> Any:
        return primary_client if cfg.name == "kimi" else fallback_client

    with patch.object(llm_module, "_build_client", side_effect=builder):
        with pytest.raises(LLMUnavailable):
            await generate_reply(messages=[{"role": "user", "content": "hi"}])

    primary_client.messages.create.assert_awaited_once()
    fallback_client.messages.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_falls_back_to_local_ollama_when_paid_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both paid providers fail + OLLAMA_ENABLED → local Gemma answers (provider=ollama)."""
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    paid_down = _client_with(httpx.TimeoutException("paid provider down"))

    from app.services.llm import LLMResult

    async def fake_ollama(cfg: Any, messages: Any, **kw: Any) -> LLMResult:
        return LLMResult(
            text="Hola, soy el agente — ¿en qué zona buscás?",
            provider="ollama", model=cfg.model, input_tokens=5, output_tokens=9,
        )

    with patch.object(llm_module, "_build_client", side_effect=lambda cfg, *, timeout: paid_down), \
         patch.object(llm_module, "_ollama_generate", side_effect=fake_ollama):
        result = await generate_reply(messages=[{"role": "user", "content": "hola"}])

    assert result.provider == "ollama"
    assert "agente" in result.text


@pytest.mark.asyncio
async def test_primary_unconfigured_skips_to_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wipe primary key only.
    monkeypatch.setenv("KIMI_API_KEY", "")
    from app.config import get_settings
    get_settings.cache_clear()

    primary_client = _client_with(RuntimeError("should not be called"))
    fallback_client = _client_with([_fake_response("Hola desde MiniMax")])

    def builder(cfg: Any, *, timeout: float) -> Any:
        return primary_client if cfg.name == "kimi" else fallback_client

    with patch.object(llm_module, "_build_client", side_effect=builder):
        result = await generate_reply(messages=[{"role": "user", "content": "hi"}])

    assert result.provider == "minimax"
    primary_client.messages.create.assert_not_awaited()
    fallback_client.messages.create.assert_awaited_once()
