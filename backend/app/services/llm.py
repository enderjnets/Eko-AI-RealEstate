"""LLM client with an inline chain: Kimi → MiniMax → Groq → Ollama.

**Two protocols, not one.** Kimi and MiniMax speak the Anthropic Messages
protocol, so they share the `anthropic` SDK with a custom `base_url` and the
same `messages.create` shape. Groq speaks the OpenAI chat protocol and Ollama
its own `/api/chat`; both are plain `httpx` POSTs handled in their own branch.
Assuming one protocol for everything is how a fourth provider gets wired to a
client that cannot talk to it.

The orchestrator (`app/services/conversation.py`) and the classifier
(`app/services/classifier.py`) both call `generate_reply()` from here; there are
NO direct `AsyncAnthropic` instantiations elsewhere.

Fallback policy: a single request tries each configured link in order with the
configured timeout, moving on for any failure — timeout, transient connection
error, 429, 5xx, or a 4xx that means we got the request wrong. If every link
fails we raise `LLMUnavailable` and the caller serves the canned holding line.

**Groq goes ahead of Ollama on purpose, and Ollama is no longer load-bearing.**
The local model runs on a laptop at home; on 2026-09-05 that laptop froze and
spent seven hours off the network, which under the old three-link chain meant
the safety net was a machine somebody has to walk over to. Groq's free tier is
always up, so it is the net; the laptop is a free extra link when it happens to
be awake. (Making `/api/v1/health` agree — it still probes only the laptop and
so still reports a healthy net as down — is the next phase, not this one.)
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

# "fallback" is not a provider you can call — it is what the canned reply is
# stamped with when every real one is unreachable, so the dashboard and the
# analytics can tell a held line apart from something a model wrote.
ProviderName = Literal["kimi", "minimax", "groq", "ollama", "fallback"]

# What `check_fallback_provider()` can say about the last-resort provider.
# "off" is a choice, not a fault; the other two are faults with different fixes.
FallbackStatus = Literal["ok", "unreachable", "model-missing", "off"]

# The probe is not a generation, so it does not get the generation timeout
# (OLLAMA_TIMEOUT_SECONDS, 120s by default). A readiness check that can hold the
# startup for two minutes is a readiness check someone will delete.
_PROBE_TIMEOUT_SECONDS = 5.0


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
        # Groq's free tier, OpenAI protocol. `is_configured` is `bool(api_key)`,
        # the same gate as the paid providers: no key, no link.
        "groq": ProviderConfig(
            name="groq",
            base_url=s.GROQ_BASE_URL,
            api_key=s.GROQ_API_KEY,
            model=s.GROQ_MODEL,
        ),
        # Local Gemma via Ollama. api_key is just a configured-flag here; the real
        # gate is OLLAMA_ENABLED (no key needed for a local server).
        "ollama": ProviderConfig(
            name="ollama",
            base_url=s.OLLAMA_BASE_URL,
            api_key="local" if s.OLLAMA_ENABLED else "",
            model=s.OLLAMA_MODEL,
        ),
    }


def _refuse_empty(text: str, cfg: ProviderConfig) -> None:
    """An empty completion is a failure, and it has to be raised, not returned.

    A 200 with `choices: []`, a `message` of `null`, or an error object served
    with a 200 status all parse cleanly into `text=""`. Returned as a result,
    that stops the chain dead: the next link is never tried, `LLMUnavailable` is
    never raised, and the lead is sent a blank message — which `conversation.py`
    does not guard against anywhere. Worse, the row is stamped with this
    provider, so the analytics count it as a healthy AI reply and the monitor,
    which only looks for `"fallback"`, stays quiet.

    Raising instead puts it exactly where it belongs: the branch's own
    `except`, which logs it and moves on to the next provider.
    """
    if not text:
        raise RuntimeError(f"empty completion from {cfg.name} (model={cfg.model})")


async def _ollama_generate(
    cfg: ProviderConfig,
    messages: list[dict[str, Any]],
    *,
    system: str | None,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    timeout_s: float,
) -> LLMResult:
    """Call a local Ollama model via its native /api/chat (not the Anthropic
    protocol). Used as a zero-cost final fallback when paid providers are down."""
    msgs: list[dict[str, Any]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": msgs,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if json_mode:
        payload["format"] = "json"
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(f"{cfg.base_url.rstrip('/')}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
    text = ((data.get("message") or {}).get("content") or "").strip()
    _refuse_empty(text, cfg)
    return LLMResult(
        text=text,
        provider="ollama",
        model=cfg.model,
        input_tokens=int(data.get("prompt_eval_count") or 0),
        output_tokens=int(data.get("eval_count") or 0),
    )


async def _openai_chat_generate(
    cfg: ProviderConfig,
    messages: list[dict[str, Any]],
    *,
    system: str | None,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    timeout_s: float,
) -> LLMResult:
    """Call any OpenAI-chat-compatible endpoint (today: Groq).

    Named for the protocol and not for Groq on purpose: the next provider that
    speaks this shape needs a config entry and a branch, not another function.

    `json_mode` deliberately does NOT become a `response_format` field.
    `generate_reply` already appends the "return only valid JSON" instruction to
    the system prompt for every provider, and `response_format` sent to a model
    that does not support it is an avoidable 400 — the difference between a link
    that degrades and a link that is dead.
    """
    msgs: list[dict[str, Any]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            f"{cfg.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    choices = data.get("choices") or []
    message = (choices[0] or {}).get("message") if choices else None
    content = (message or {}).get("content")
    # `isinstance` and not `or ""`: a model that answers in content-parts sends a
    # list here, and `.strip()` on it is an AttributeError from inside the branch
    # rather than a link that degrades.
    text = content.strip() if isinstance(content, str) else ""
    _refuse_empty(text, cfg)
    usage = data.get("usage") or {}
    return LLMResult(
        text=text,
        provider=cfg.name,
        model=cfg.model,
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
    )


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
    # The safety net, in the order it is reached. Groq before Ollama: it is a
    # hosted service that is always up, while the local model lives on a laptop
    # that sleeps and occasionally freezes. Paid providers still go first, for
    # quality.
    groq_cfg = configs.get("groq")
    if groq_cfg is not None and groq_cfg.is_configured and "groq" not in order:
        order.append("groq")
    if s.OLLAMA_ENABLED and "ollama" not in order:
        order.append("ollama")
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

        if provider_name == "groq":
            try:
                result = await _openai_chat_generate(
                    cfg, messages, system=system, max_tokens=max_tok,
                    temperature=temperature, json_mode=json_mode,
                    timeout_s=s.LLM_TIMEOUT_SECONDS,
                )
                log.info(
                    "LLM ok provider=groq model=%s in_tok=%d out_tok=%d",
                    cfg.model, result.input_tokens, result.output_tokens,
                )
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                # The status and body, not just the exception class. "Groq was
                # rate limited" and "we sent Groq a malformed body" are the same
                # line otherwise, and only one of them is our bug.
                # Wrapped: this runs inside an `except` with no outer `try`, so
                # an exception here would escape `generate_reply` and skip both
                # the next link and the caller's canned line.
                detail = ""
                try:
                    response = getattr(exc, "response", None)
                    if response is not None:
                        detail = f" status={response.status_code} body={response.text[:200]!r}"
                except Exception:  # noqa: BLE001
                    detail = ""
                log.warning("LLM provider groq failed (%s: %s)%s; falling back anyway",
                            type(exc).__name__, exc, detail)
                continue

        if provider_name == "ollama":
            try:
                result = await _ollama_generate(
                    cfg, messages, system=system, max_tokens=max_tok,
                    temperature=temperature, json_mode=json_mode,
                    timeout_s=s.OLLAMA_TIMEOUT_SECONDS,
                )
                log.info(
                    "LLM ok provider=ollama model=%s in_tok=%d out_tok=%d",
                    cfg.model, result.input_tokens, result.output_tokens,
                )
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                log.warning("LLM provider ollama failed (%s: %s); falling back anyway",
                            type(exc).__name__, exc)
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


def _model_is_available(configured: str, available: set[str]) -> bool:
    """Is `configured` one of the tags this Ollama actually holds?

    Ollama resolves a bare name to its `:latest` tag, so a config that says
    `qwen3.5` and a server that lists `qwen3.5:latest` are talking about the
    same model. Calling that missing would be a false alarm, and a probe that
    cries wolf gets switched off.
    """
    if configured in available:
        return True
    return ":" not in configured and f"{configured}:latest" in available


async def check_fallback_provider() -> FallbackStatus:
    """Can the last-resort provider actually answer right now?

    Two things have to be true, and checking only the first is precisely how
    this stayed broken for twelve weeks: the server has to respond, AND the
    configured model has to exist on it. A reachable Ollama pointed at a model
    it does not have is exactly as useless as no Ollama at all — and it looks
    healthier, which is worse.

    `OLLAMA_ENABLED=true` is a statement of intent. This is the statement of
    fact. Never raises: a probe that can break the caller is a liability.
    """
    s = get_settings()
    if not s.OLLAMA_ENABLED:
        return "off"

    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{s.OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 — every failure to reach it means the same thing
        log.debug("Ollama probe failed against %s: %s", s.OLLAMA_BASE_URL, exc)
        return "unreachable"

    available = {
        str((m or {}).get("name") or "") for m in (data.get("models") or [])
    }
    return "ok" if _model_is_available(s.OLLAMA_MODEL, available) else "model-missing"
