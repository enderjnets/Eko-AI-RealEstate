"""LLM client with inline primary→fallback (Kimi → MiniMax).

Both providers speak the Anthropic Messages protocol — we use the `anthropic`
Python SDK with a custom `base_url` per provider, so the same `messages.create`
shape works for both. The orchestrator (`app/services/conversation.py`) and the
classifier (`app/services/classifier.py`) both call `generate_reply()` from
here; there are NO direct `AsyncAnthropic` instantiations elsewhere.

Fallback policy: a single LLM request tries PRIMARY once with the configured
timeout. On `TimeoutException`, transient `APIConnectionError`, 429, or 5xx, it
falls through to FALLBACK. If FALLBACK also fails, we raise `LLMUnavailable`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
)

from app.config import get_settings

log = logging.getLogger(__name__)

ProviderName = Literal["kimi", "minimax"]


@dataclass(frozen=True)
class ProviderConfig:
    name: ProviderName
    base_url: str
    api_key: str
    model: str

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


class LLMUnavailable(RuntimeError):
    """All providers failed for this request."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: ProviderName
    model: str
    input_tokens: int
    output_tokens: int


def _provider_configs() -> dict[ProviderName, ProviderConfig]:
    s = get_settings()
    return {
        "kimi": ProviderConfig(
            name="kimi",
            base_url=s.KIMI_BASE_URL,
            api_key=s.KIMI_API_KEY,
            model=s.KIMI_MODEL,
        ),
        "minimax": ProviderConfig(
            name="minimax",
            base_url=s.MINIMAX_BASE_URL,
            api_key=s.MINIMAX_API_KEY,
            model=s.MINIMAX_MODEL,
        ),
    }


def _build_client(cfg: ProviderConfig, *, timeout: float) -> AsyncAnthropic:
    """One client per request — cheap (httpx connection pool inside)."""
    return AsyncAnthropic(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=timeout,
        max_retries=0,  # we orchestrate retries via the fallback loop, not the SDK
    )


def _is_transient(exc: Exception) -> bool:
    """Return True if this exception should trigger a fallback retry."""
    if isinstance(exc, (APITimeoutError, APIConnectionError, httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in (429, 500, 502, 503, 504)
    return False


async def generate_reply(
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.7,
    json_mode: bool = False,
) -> LLMResult:
    """Generate a single LLM reply with inline primary→fallback.

    Args:
        messages: list of {"role": "user"|"assistant", "content": str}
        system:   optional system prompt
        max_tokens: cap on output tokens (defaults to LLM_MAX_TOKENS_DEFAULT)
        temperature: 0.0–1.0 (0.0 for classification, 0.7 for replies)
        json_mode: appends a structured-output instruction to the system prompt
                   (Anthropic-compat backends don't always honor response_format,
                   so we steer with prompting + Pydantic validation downstream).

    Returns:
        LLMResult with the final text + the provider that produced it.

    Raises:
        LLMUnavailable: both primary and fallback failed.
    """
    s = get_settings()
    configs = _provider_configs()
    order: list[ProviderName] = [s.LLM_PRIMARY, s.LLM_FALLBACK]  # type: ignore[list-item]
    max_tok = max_tokens if max_tokens is not None else s.LLM_MAX_TOKENS_DEFAULT

    if json_mode and system is not None:
        system = (
            system
            + "\n\nDevuelve EXCLUSIVAMENTE un objeto JSON válido, sin markdown ni "
            "comentarios. La salida debe poder parsearse con json.loads()."
        )
    elif json_mode:
        system = (
            "Devuelve EXCLUSIVAMENTE un objeto JSON válido, sin markdown ni "
            "comentarios. La salida debe poder parsearse con json.loads()."
        )

    last_error: Exception | None = None

    for provider_name in order:
        cfg = configs.get(provider_name)
        if cfg is None or not cfg.is_configured:
            log.warning("LLM provider %s not configured (missing API key); skipping", provider_name)
            continue

        client = _build_client(cfg, timeout=s.LLM_TIMEOUT_SECONDS)
        try:
            resp = await client.messages.create(
                model=cfg.model,
                messages=messages,  # type: ignore[arg-type]
                system=system or "",
                max_tokens=max_tok,
                temperature=temperature,
            )
            # Anthropic SDK: content is a list of blocks; for text it's a single TextBlock.
            text_parts = [
                getattr(block, "text", "") for block in resp.content if getattr(block, "type", "") == "text"
            ]
            text = "".join(text_parts).strip()
            usage_in = getattr(getattr(resp, "usage", None), "input_tokens", 0) or 0
            usage_out = getattr(getattr(resp, "usage", None), "output_tokens", 0) or 0
            log.info(
                "LLM ok provider=%s model=%s in_tok=%d out_tok=%d",
                provider_name, cfg.model, usage_in, usage_out,
            )
            return LLMResult(
                text=text,
                provider=provider_name,
                model=cfg.model,
                input_tokens=usage_in,
                output_tokens=usage_out,
            )
        except Exception as exc:  # noqa: BLE001 — we classify below
            last_error = exc
            if _is_transient(exc):
                log.warning(
                    "LLM provider %s failed transiently (%s: %s); falling back",
                    provider_name, type(exc).__name__, exc,
                )
                continue
            # Non-transient (e.g. 4xx auth, validation) → still try fallback so the lead
            # doesn't go unanswered, but log louder.
            log.error(
                "LLM provider %s failed non-transient (%s: %s); falling back anyway",
                provider_name, type(exc).__name__, exc,
            )
            continue

    raise LLMUnavailable(
        f"All LLM providers failed. order={order}; last_error={type(last_error).__name__ if last_error else 'NoneConfigured'}: {last_error}"
    )
