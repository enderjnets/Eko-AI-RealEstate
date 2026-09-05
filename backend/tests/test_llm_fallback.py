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
    # Pin Ollama OFF by default so paid-provider tests are hermetic regardless of
    # the host env (the ROG sets OLLAMA_ENABLED=true). The local-fallback test
    # opts back in explicitly.
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    # Same reasoning for Groq: the third link is pinned OFF so the paid-provider
    # tests keep meaning what they say on a machine that has a real key in its
    # environment. The Groq tests opt back in explicitly.
    monkeypatch.setenv("GROQ_API_KEY", "")
    # Y su modelo y su URL: son configurables por entorno, y una máquina que los
    # cambie pondría en rojo dos tests que no dependen de su configuración.
    monkeypatch.setenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    # Clear the lru_cache on get_settings so the new env vars apply — and the
    # probe cache at the same instant, or a cached "ok" would hide a GROQ_MODEL
    # that this test just changed.
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr(llm_module, "_groq_probe_cache", None)


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


# ── Groq: the third link, and the first one that is not a laptop ──────────
#
# Every test here asserts on WHO answered, never merely that nothing raised.
# "no exception" is satisfied by a chain that skipped Groq entirely and was
# rescued by the link after it, which is the exact bug these exist to catch.


def _enable_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_dummy_not_a_real_key")
    from app.config import get_settings
    get_settings.cache_clear()


def _groq_result(text: str = "Hola, soy el agente de la agencia.") -> Any:
    from app.services.llm import LLMResult

    async def _generate(cfg: Any, messages: Any, **kw: Any) -> LLMResult:
        return LLMResult(
            text=text, provider="groq", model=cfg.model,
            input_tokens=11, output_tokens=22,
        )

    return _generate


@pytest.mark.asyncio
async def test_groq_answers_when_both_paid_providers_are_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MUTATION GUARD — drop `"groq"` from `order` and this must go red."""
    _enable_groq(monkeypatch)
    paid_down = _client_with(httpx.TimeoutException("paid provider down"))

    with patch.object(llm_module, "_build_client", side_effect=lambda cfg, *, timeout: paid_down), \
         patch.object(llm_module, "_openai_chat_generate", side_effect=_groq_result()):
        result = await generate_reply(messages=[{"role": "user", "content": "hola"}])

    assert result.provider == "groq"
    assert result.model == "openai/gpt-oss-120b"
    assert "agente" in result.text


@pytest.mark.asyncio
async def test_groq_is_tried_before_the_laptop(monkeypatch: pytest.MonkeyPatch) -> None:
    """With both last links available, the hosted one answers and the ROG is untouched.

    MUTATION GUARD — append `"groq"` AFTER `"ollama"` in `order` and this goes
    red. Ordering is the whole point of the change: the laptop is a bonus, not
    the net.
    """
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    paid_down = _client_with(httpx.TimeoutException("paid provider down"))
    ollama = AsyncMock(side_effect=RuntimeError("the ROG must not be reached"))

    with patch.object(llm_module, "_build_client", side_effect=lambda cfg, *, timeout: paid_down), \
         patch.object(llm_module, "_openai_chat_generate", side_effect=_groq_result()), \
         patch.object(llm_module, "_ollama_generate", ollama):
        result = await generate_reply(messages=[{"role": "user", "content": "hola"}])

    assert result.provider == "groq"
    ollama.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_429_from_groq_does_not_break_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Groq's free tier running out mid-reply falls through to the ROG, not to silence."""
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    from app.services.llm import LLMResult

    rate_limited = httpx.HTTPStatusError(
        "429 Too Many Requests",
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        response=httpx.Response(429, text="rate limit reached"),
    )

    async def fake_ollama(cfg: Any, messages: Any, **kw: Any) -> LLMResult:
        return LLMResult(
            text="Respuesta local", provider="ollama", model=cfg.model,
            input_tokens=3, output_tokens=4,
        )

    paid_down = _client_with(httpx.TimeoutException("paid provider down"))
    groq = AsyncMock(side_effect=rate_limited)

    with patch.object(llm_module, "_build_client", side_effect=lambda cfg, *, timeout: paid_down), \
         patch.object(llm_module, "_openai_chat_generate", groq), \
         patch.object(llm_module, "_ollama_generate", side_effect=fake_ollama):
        result = await generate_reply(messages=[{"role": "user", "content": "hola"}])

    groq.assert_awaited_once()
    assert result.provider == "ollama"


@pytest.mark.asyncio
async def test_groq_without_a_key_is_skipped_in_silence() -> None:
    """No key, no link — and nothing is called with an empty Bearer token.

    The paid providers are knocked down on purpose. An earlier version let Kimi
    answer first, which made `assert_not_awaited` pass whether or not the key
    was checked: the chain never got as far as Groq either way. Now the chain
    has nowhere else to go, so reaching `LLMUnavailable` instead of calling Groq
    is the only way this can pass.

    MUTATION GUARD — drop `groq_cfg.is_configured` from the `order` guard and
    Groq is appended with an empty key; this goes red.
    """
    paid_down = _client_with(httpx.TimeoutException("paid provider down"))
    groq = AsyncMock(side_effect=RuntimeError("must not be called without a key"))

    with patch.object(llm_module, "_build_client", side_effect=lambda cfg, *, timeout: paid_down), \
         patch.object(llm_module, "_openai_chat_generate", groq):
        with pytest.raises(LLMUnavailable):
            await generate_reply(messages=[{"role": "user", "content": "hi"}])

    groq.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"choices": []},
    {"choices": [None]},
    {"choices": [{"message": None}]},
    {"choices": [{"message": {"content": None}}]},
    {"choices": [{"message": {"content": "   "}}]},
    # An error object served with a 200 status — `raise_for_status` sees nothing.
    {"error": {"message": "something went wrong", "type": "server_error"}},
    # A model that answers in content-parts: a list, not a string.
    {"choices": [{"message": {"content": [{"type": "text", "text": "hola"}]}}]},
])
async def test_an_empty_answer_from_groq_is_a_failure_not_an_answer(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, Any],
) -> None:
    """A 200 that carries no text must fall through, never be returned.

    This is the worst shape of all and it is silent: returned as an `LLMResult`,
    it STOPS the chain — the next link is never tried, `LLMUnavailable` is never
    raised — and `conversation.py` has no guard on empty text anywhere, so the
    lead is sent a blank message. The row is then stamped `provider="groq"`, so
    the analytics count it as a healthy AI reply and the monitor, which only
    looks for `"fallback"`, never says a word.

    MUTATION GUARD — delete `_refuse_empty` from `_openai_chat_generate` and
    every case here goes red.
    """
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    from app.services.llm import LLMResult

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=body)
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    async def fake_ollama(cfg: Any, messages: Any, **kw: Any) -> LLMResult:
        return LLMResult(
            text="Respuesta local", provider="ollama", model=cfg.model,
            input_tokens=3, output_tokens=4,
        )

    paid_down = _client_with(httpx.TimeoutException("paid provider down"))

    with patch.object(llm_module, "_build_client", side_effect=lambda cfg, *, timeout: paid_down), \
         patch.object(llm_module.httpx, "AsyncClient", MagicMock(return_value=ctx)), \
         patch.object(llm_module, "_ollama_generate", side_effect=fake_ollama):
        result = await generate_reply(messages=[{"role": "user", "content": "hola"}])

    # Groq WAS tried — the request went out — and its empty answer was refused.
    client.post.assert_awaited_once()
    assert result.provider == "ollama"
    assert result.text == "Respuesta local"


@pytest.mark.asyncio
async def test_an_empty_answer_from_the_laptop_is_refused_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same guard on the last link, where an empty answer reaches the lead directly.

    Pre-existing and not introduced by Groq, but it is the same one-line fix and
    the same blank message: at the end of the chain there is nothing left to
    fall through to, so `LLMUnavailable` — and the caller's holding line — is
    the only correct outcome.
    """
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"message": {"content": ""}})
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    paid_down = _client_with(httpx.TimeoutException("paid provider down"))

    with patch.object(llm_module, "_build_client", side_effect=lambda cfg, *, timeout: paid_down), \
         patch.object(llm_module.httpx, "AsyncClient", MagicMock(return_value=ctx)):
        with pytest.raises(LLMUnavailable):
            await generate_reply(messages=[{"role": "user", "content": "hola"}])

    client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_every_link_down_still_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller — not this module — is what serves the holding line."""
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    paid_down = _client_with(httpx.TimeoutException("paid provider down"))
    groq = AsyncMock(side_effect=httpx.ConnectError("groq unreachable"))
    ollama = AsyncMock(side_effect=httpx.ConnectError("the ROG is asleep"))

    with patch.object(llm_module, "_build_client", side_effect=lambda cfg, *, timeout: paid_down), \
         patch.object(llm_module, "_openai_chat_generate", groq), \
         patch.object(llm_module, "_ollama_generate", ollama):
        with pytest.raises(LLMUnavailable):
            await generate_reply(messages=[{"role": "user", "content": "hola"}])

    groq.assert_awaited_once()
    ollama.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_request_groq_actually_receives(monkeypatch: pytest.MonkeyPatch) -> None:
    """The HTTP contract, asserted field by field — and driven through the chain.

    It goes through `generate_reply` and patches only the transport, on purpose.
    Every other test here replaces `_openai_chat_generate` with a stub that
    discards its keyword arguments, so the seam between the two — what
    `generate_reply` actually hands over — was asserted by nothing at all. Five
    separate mutations of that call site survived a full green suite, and the
    two expensive ones are silent: `system=None` deletes both the agent persona
    and the JSON instruction appended below for `json_mode`, so the classifier
    gets prose, fails Pydantic and degrades to `intent=OTHER` without a word;
    `messages=[]` asks the model to answer a lead who said nothing. Both ship a
    fluent reply stamped `provider="groq"`.

    MUTATION GUARDS — this goes red for any of: no `Authorization` header;
    reading `choices[0]["text"]`; passing `system=None`, `messages=[]`, a
    literal `max_tokens`, a literal `temperature`, or Ollama's timeout.
    """
    _enable_groq(monkeypatch)
    captured: dict[str, Any] = {}

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "choices": [{"message": {"role": "assistant", "content": "  Hola.  "}}],
        "usage": {"prompt_tokens": 41, "completion_tokens": 7},
    })

    async def fake_post(url: str, **kw: Any) -> Any:
        captured["url"] = url
        captured.update(kw)
        return resp

    client = MagicMock()
    client.post = AsyncMock(side_effect=fake_post)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    def client_factory(**kw: Any) -> Any:
        captured["client_kwargs"] = kw
        return ctx

    paid_down = _client_with(httpx.TimeoutException("paid provider down"))

    with patch.object(llm_module, "_build_client", side_effect=lambda cfg, *, timeout: paid_down), \
         patch.object(llm_module.httpx, "AsyncClient", MagicMock(side_effect=client_factory)):
        result = await generate_reply(
            messages=[{"role": "user", "content": "hola, busco piso en Denver"}],
            system="Eres un agente inmobiliario.",
            max_tokens=321,
            temperature=0.35,
            json_mode=True,
        )

    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer gsk_dummy_not_a_real_key"

    body = captured["json"]
    assert body["model"] == "openai/gpt-oss-120b"
    # The caller's numbers, not the module defaults (600 / 0.7) and not literals.
    assert body["max_tokens"] == 321
    assert body["temperature"] == 0.35

    # System first, then the conversation — the order the protocol expects.
    system_msg = body["messages"][0]
    assert system_msg["role"] == "system"
    assert "Eres un agente inmobiliario." in system_msg["content"]
    # And the JSON instruction `generate_reply` appends under json_mode really
    # reaches Groq. Without it the classifier silently degrades to intent=OTHER.
    assert "json.loads()" in system_msg["content"]
    # The lead's own words, carried through.
    assert body["messages"][1] == {
        "role": "user", "content": "hola, busco piso en Denver"
    }

    # Not sent even under json_mode: an unsupported response_format is a 400,
    # and the JSON instruction already rides in the system prompt.
    assert "response_format" not in body
    # None of these are supported by Groq; sending one is a 400.
    for unsupported in ("n", "logprobs", "logit_bias", "top_logprobs"):
        assert unsupported not in body

    # Groq's own timeout, not the laptop's 120 s: a hosted provider holding a
    # lead's reply for two minutes is the ROG's budget, not Groq's.
    assert captured["client_kwargs"]["timeout"] == 30.0

    assert result.provider == "groq"
    assert result.model == "openai/gpt-oss-120b"
    assert result.text == "Hola."
    assert result.input_tokens == 41
    assert result.output_tokens == 7


# ── check_fallback_provider: is the safety net actually there? ─────────────
#
# These exist because the production install ran with OLLAMA_ENABLED=true for
# twelve weeks while BOTH the server was unreachable from the container and the
# configured model was not downloaded. A probe that only checked the port would
# have caught the first fault and reported the second one as healthy, so the
# model case below is the one that matters most.


def _probe_client(payload: Any = None, *, raises: Exception | None = None) -> MagicMock:
    """Stand in for httpx.AsyncClient so GET /api/tags returns what we say."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload if payload is not None else {})
    client = MagicMock()
    client.get = AsyncMock(side_effect=raises) if raises else AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


def _enable_ollama(monkeypatch: pytest.MonkeyPatch, model: str) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_MODEL", model)
    from app.config import get_settings
    get_settings.cache_clear()


def _tags(*names: str) -> dict[str, Any]:
    return {"models": [{"name": n} for n in names]}


# ── The probe describes the NET, not one machine ──────────────────────────
#
# One transport double for both providers, routing by URL. Two separate
# `patch.object` calls on `httpx.AsyncClient` would write the same attribute and
# the second would silently win — the exact trap that made an ops_alert test
# assert on a client that was never used.


def _net_client(
    *,
    groq: Any = None,
    groq_status: int = 200,
    groq_raises: Exception | None = None,
    ollama: Any = None,
    ollama_raises: Exception | None = None,
) -> MagicMock:
    """Stand in for httpx.AsyncClient, answering per host."""
    calls: list[str] = []
    requests: list[dict[str, Any]] = []

    async def get(url: str, **kw: Any) -> Any:
        calls.append(url)
        # Headers too, not just the host. Routing by `"groq.com" in url` catches
        # a probe sent to the wrong PROVIDER, and nothing below it: a missing
        # Authorization header, or a path that is not `/models`, both left the
        # suite green while production would get a permanent 401 or 404.
        requests.append({"url": url, **kw})
        if "groq.com" in url:
            if groq_raises is not None:
                raise groq_raises
            resp = MagicMock()
            resp.status_code = groq_status
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value=groq if groq is not None else {})
            return resp
        if ollama_raises is not None:
            raise ollama_raises
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=ollama if ollama is not None else {})
        return resp

    client = MagicMock()
    client.get = AsyncMock(side_effect=get)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    factory.calls = calls
    factory.requests = requests
    return factory


def _models(*ids: str) -> dict[str, Any]:
    """Groq's GET /models shape."""
    return {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]}


@pytest.mark.asyncio
async def test_the_net_is_ok_when_groq_answers_and_the_laptop_is_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case that lies today: a healthy net reported as down.

    Before Groq, `unreachable` here was true — the laptop WAS the net. Now it is
    a working safety net waking the owner at 7am to fix a machine whose absence
    changes nothing, which is the fastest way to teach someone to ignore the
    alarm.

    MUTATION GUARD — make the probe ignore Groq and return `_probe_ollama()`
    alone; this goes red.
    """
    _enable_groq(monkeypatch)
    _enable_ollama(monkeypatch, "gemma3:4b")
    factory = _net_client(
        groq=_models("openai/gpt-oss-120b", "llama-3.1-8b-instant"),
        ollama_raises=httpx.ConnectError("[Errno 111] Connection refused"),
    )
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "ok"


@pytest.mark.asyncio
async def test_groq_answering_without_our_model_is_model_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Free tiers withdraw models without notice — that is how Kling broke.

    MUTATION GUARD — stop checking that GROQ_MODEL is in `data[].id` (return
    "ok" as soon as the listing responds) and this goes red.
    """
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    factory = _net_client(groq=_models("llama-3.1-8b-instant", "whisper-large-v3"))
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "model-missing"


@pytest.mark.asyncio
async def test_a_rate_limited_groq_is_present_not_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 means the service answered. Being limited is not being gone.

    MUTATION GUARD — treat 429 as `unreachable` and this goes red. It would page
    the owner for a busy minute on a link that is working.
    """
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    factory = _net_client(groq_status=429, groq={"error": {"code": "rate_limit_exceeded"}})
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "ok"


@pytest.mark.asyncio
async def test_a_dead_key_says_so_and_names_the_variable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A 401 is the owner's to fix, and the log has to say WHICH thing to fix."""
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    factory = _net_client(groq_status=401, groq={"error": {"code": "invalid_api_key"}})
    with caplog.at_level("ERROR"), patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "unreachable"

    assert "GROQ_API_KEY" in caplog.text


@pytest.mark.asyncio
async def test_the_laptop_alone_still_holds_the_net_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Either link is enough — including the one that is only a bonus."""
    _enable_groq(monkeypatch)
    _enable_ollama(monkeypatch, "gemma3:4b")
    factory = _net_client(
        groq_raises=httpx.ConnectError("groq unreachable"),
        ollama=_tags("gemma3:4b"),
    )
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "ok"

    # Both were asked. Without this the test passed with Groq deleted from the
    # function entirely: its name promises "either link is enough" and it only
    # ever demonstrated one of them.
    assert [u for u in factory.calls if "groq.com" in u], "no se sondeo Groq"
    assert [u for u in factory.calls if "groq.com" not in u], "no se sondeo el ROG"


@pytest.mark.asyncio
async def test_with_nothing_configured_it_behaves_exactly_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key and no laptop is `off` — a choice, not a fault — and costs no request."""
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    factory = _net_client(groq=_models("openai/gpt-oss-120b"))
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "off"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_the_probe_does_not_spend_what_it_is_watching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The monitor ticks every 5 minutes; Groq is asked at most once an hour.

    A watchman that consumes the resource it watches is the v0.54.3 lesson
    upside down. `monotonic` is patched on THIS module's own reference, never on
    the `time` module: asyncio reads `time.monotonic()` for its own scheduling,
    and patching it globally either hangs the loop or passes for the wrong
    reason.

    MUTATION GUARD — delete the cache READ (always fall through to the GET) and
    the first assertion goes red.
    """
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    clock = {"t": 1000.0}
    monkeypatch.setattr(llm_module, "_now", lambda: clock["t"])

    factory = _net_client(groq=_models("openai/gpt-oss-120b"))
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "ok"
        assert await llm_module.check_fallback_provider() == "ok"
        groq_calls = [u for u in factory.calls if "groq.com" in u]
        assert len(groq_calls) == 1, f"asked Groq {len(groq_calls)} times in an hour"

        # Past the TTL it asks again — a cache that never expires is a probe
        # that stopped probing.
        clock["t"] += llm_module._GROQ_PROBE_TTL_SECONDS + 1
        assert await llm_module.check_fallback_provider() == "ok"
        groq_calls = [u for u in factory.calls if "groq.com" in u]
        assert len(groq_calls) == 2


@pytest.mark.asyncio
async def test_removing_the_key_is_not_hidden_by_a_cached_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The no-key path must not write the cache.

    Caching `off` would report "no link" for an hour after a key was added, and
    between tests it would leak one case's answer into the next.
    """
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    factory = _net_client(groq=_models("openai/gpt-oss-120b"))
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "off"
        assert llm_module._groq_probe_cache is None

        _enable_groq(monkeypatch)
        assert await llm_module.check_fallback_provider() == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"models": "texto"},
    {"models": ["texto"]},
    {"models": [None]},
    {"models": {"gemma3:4b": True}},
    ["una", "lista", "en", "la", "raiz"],
    "una cadena",
    None,
])
async def test_the_probe_never_raises_whatever_comes_back(
    monkeypatch: pytest.MonkeyPatch, body: Any,
) -> None:
    """Never raising is the contract, not a nicety — and Groq being fine is no shield.

    `main.py` calls this during startup and the monitor every 5 minutes, and
    neither has anywhere to put an exception. An `AttributeError` out of here
    leaves `app.state.llm_fallback` frozen at its last value — so `/api/v1/health`
    serves a stale reading for ever — and stops `row.state` from moving, so the
    debounce never confirms and **no alert is ever sent** while the log fills
    with a line every five minutes. The alarm failing because of the fault it
    exists to report.

    Groq is healthy in every case below, which is the part that matters: the
    composition awaited the laptop's probe regardless, so the link that was just
    demoted to a bonus could still take down a report about a net that is
    demonstrably fine.

    MUTATION GUARD — move the Ollama parsing back outside its `try`, or drop the
    `isinstance` guards, and these go red.
    """
    _enable_groq(monkeypatch)
    _enable_ollama(monkeypatch, "gemma3:4b")

    # Groq answers, but WITHOUT our model, so the composition is forced to go on
    # and probe the laptop — a short-circuit on `ok` would otherwise mean this
    # test never exercised the parsing it is here to pin.
    factory = _net_client(groq=_models("otro-modelo"), ollama=body)
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        status = await llm_module.check_fallback_provider()

    assert status in ("ok", "unreachable", "model-missing", "off")


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"models": "texto"},
    {"models": ["texto"]},
    {"models": [None]},
    {"models": {"gemma3:4b": True}},
    ["una", "lista", "en", "la", "raiz"],
    "una cadena",
    None,
])
async def test_something_answered_is_not_the_same_as_nothing_answered(
    monkeypatch: pytest.MonkeyPatch, body: Any,
) -> None:
    """A 200 nobody can parse means "answered, model not found" — not "down".

    Groq is off here on purpose, so the laptop's own word is the one that comes
    out; with Groq configured the composition returns Groq's and this would
    prove nothing.

    The two words send the owner to different places: `unreachable` says the
    port is dead (`systemctl status`), `model-missing` says something is
    listening and the model is not on it. Getting a 200 and reporting the port
    dead is the same class of lie the whole fase exists to remove, one level
    down — and it is the difference the `isinstance` guards make, since without
    them the `try` swallows an `AttributeError` and calls it `unreachable`.

    MUTATION GUARD — drop either `isinstance` guard in `_probe_ollama` and this
    goes red.
    """
    monkeypatch.setenv("GROQ_API_KEY", "")
    _enable_ollama(monkeypatch, "gemma3:4b")

    factory = _net_client(ollama=body)
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "model-missing"


@pytest.mark.asyncio
async def test_a_blip_is_not_cached_for_an_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure spends no quota, so it must not buy an hour of silence.

    The hour-long cache exists to protect the free tier's allowance. A refused
    or unreachable call costs nothing, so caching it for the same hour is all
    downside: a one-second network hiccup froze `unreachable`, the monitor's
    two-reading debounce mailed "the safety net is down" about it, and the
    recovery notice arrived fifty-five minutes after the net was back.

    MUTATION GUARD — give failures the same TTL as successes and this goes red.
    """
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    clock = {"t": 5000.0}
    monkeypatch.setattr(llm_module, "_now", lambda: clock["t"])

    blip = _net_client(groq_raises=httpx.ConnectError("un parpadeo"))
    with patch.object(llm_module.httpx, "AsyncClient", blip):
        assert await llm_module.check_fallback_provider() == "unreachable"

    healthy = _net_client(groq=_models("openai/gpt-oss-120b"))
    with patch.object(llm_module.httpx, "AsyncClient", healthy):
        # Still inside the failure TTL: the cached answer stands.
        clock["t"] += llm_module._GROQ_PROBE_FAIL_TTL_SECONDS - 1
        assert await llm_module.check_fallback_provider() == "unreachable"
        assert healthy.calls == []

        # Just past it — and well short of the hour a success would have bought.
        clock["t"] += 2
        assert await llm_module.check_fallback_provider() == "ok"

    assert llm_module._GROQ_PROBE_FAIL_TTL_SECONDS < llm_module._GROQ_PROBE_TTL_SECONDS


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [500, 502, 503, 504, 404, 418])
async def test_a_bad_status_from_groq_is_not_a_healthy_net(
    monkeypatch: pytest.MonkeyPatch, code: int,
) -> None:
    """Any status that is not 200/429 means Groq cannot serve a lead right now.

    A connection error was covered; a bad status code was not, and it is the
    likelier failure: Groq answering 503 with the laptop asleep would have made
    `/api/v1/health` say `ok`, the monitor stay quiet, and leads collect the
    holding line with nothing making a sound. That is precisely the outage this
    branch exists to make visible, hiding inside the thing built to reveal it.

    MUTATION GUARD — return `ok` from the catch-all status branch and this goes
    red.
    """
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    factory = _net_client(groq_status=code, groq={"error": {"code": "server_error"}})
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "unreachable"


@pytest.mark.asyncio
async def test_the_request_the_probe_actually_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    """The probe's own wire contract: right path, right credential.

    Routing the double by host proves the probe went to the right provider and
    nothing under that. A probe sent to `/no-such-endpoint`, or one that forgets
    the `Authorization` header, is a permanent 404 or 401 in production — the
    net reported down for ever while it is perfectly fine — and both left every
    test green.

    MUTATION GUARD — change the path or drop the header and this goes red.
    """
    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    factory = _net_client(groq=_models("openai/gpt-oss-120b"))
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "ok"

    assert len(factory.requests) == 1
    sent = factory.requests[0]
    assert sent["url"] == "https://api.groq.com/openai/v1/models"
    assert sent["headers"]["Authorization"] == "Bearer gsk_dummy_not_a_real_key"


@pytest.mark.asyncio
async def test_a_configured_groq_is_the_fault_worth_reporting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With both links broken, the word describes the one the owner can fix.

    A dead `GROQ_API_KEY` is fixable from a phone in another country; the laptop
    needs somebody in the house. Report the laptop's fault instead and the alarm
    says `model-missing` — "run ollama pull" — for a problem that is a revoked
    key, which is the wrong machine and the exact thing the alert text was
    rewritten to stop doing.

    MUTATION GUARD — swap the priority so the laptop's word wins and this goes
    red.
    """
    _enable_groq(monkeypatch)
    _enable_ollama(monkeypatch, "gemma3:4b")

    factory = _net_client(
        groq_status=401,
        groq={"error": {"code": "invalid_api_key"}},
        ollama=_tags("qwen2.5:14b"),   # responde, pero no tiene NUESTRO modelo
    )
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "unreachable"


@pytest.mark.asyncio
async def test_the_hour_is_the_point_not_the_ordering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The TTL's actual value, because the argument for it is a number.

    Asserting only that the failure TTL is shorter than the success one lets
    both shrink together: with 1.0 and 0.5 the ordering still holds, the suite
    still passes, and the probe goes from 24 calls a day to 86,400 against an
    allowance of 1,000. The whole justification written above the constant is
    "2.4% of the quota", so that is what has to be pinned.

    MUTATION GUARD — shrink either constant and this goes red.
    """
    assert llm_module._GROQ_PROBE_TTL_SECONDS >= 3600.0
    assert 30.0 <= llm_module._GROQ_PROBE_FAIL_TTL_SECONDS <= 300.0

    _enable_groq(monkeypatch)
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    clock = {"t": 9000.0}
    monkeypatch.setattr(llm_module, "_now", lambda: clock["t"])

    # `model-missing` takes the long TTL too: the model being withdrawn is a
    # 200 like any other, and asking again every minute would spend the quota
    # the cache exists to protect.
    factory = _net_client(groq=_models("otro-modelo"))
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "model-missing"
        clock["t"] += 3599.0
        assert await llm_module.check_fallback_provider() == "model-missing"
        assert len(factory.calls) == 1, "volvio a preguntar dentro de la hora"


@pytest.mark.asyncio
async def test_a_healthy_groq_does_not_wake_the_laptop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Groq answers, the ROG is never asked — and that is not just speed.

    With the laptop asleep its probe costs the full `_PROBE_TIMEOUT_SECONDS` on
    startup and on every 5-minute tick, and it puts a link that no longer
    matters back in the path of a report about a net that is demonstrably fine:
    a malformed answer from it used to take down the whole reading.

    MUTATION GUARD — remove the short-circuit and this goes red.
    """
    _enable_groq(monkeypatch)
    _enable_ollama(monkeypatch, "gemma3:4b")

    factory = _net_client(
        groq=_models("openai/gpt-oss-120b"),
        ollama_raises=AssertionError("no se debe preguntar al ROG"),
    )
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "ok"

    assert [u for u in factory.calls if "groq.com" not in u] == []


@pytest.mark.asyncio
async def test_probe_ok_when_server_answers_and_has_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_ollama(monkeypatch, "gemma3:4b")
    with patch.object(llm_module.httpx, "AsyncClient", _probe_client(_tags("gemma3:4b"))):
        assert await llm_module.check_fallback_provider() == "ok"


@pytest.mark.asyncio
async def test_probe_reports_model_missing_when_server_answers_without_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact fault that survived twelve weeks: reachable, and still useless.

    MUTATION GUARD — delete the model check in `check_fallback_provider` (return
    "ok" as soon as /api/tags responds) and this test must go red. If it stays
    green the probe is decoration.
    """
    _enable_ollama(monkeypatch, "gemma3:4b")
    with patch.object(
        llm_module.httpx, "AsyncClient", _probe_client(_tags("qwen2.5:14b", "moondream:latest"))
    ):
        assert await llm_module.check_fallback_provider() == "model-missing"


@pytest.mark.asyncio
async def test_probe_unreachable_when_connection_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the container actually got: ECONNREFUSED against the bridge gateway."""
    _enable_ollama(monkeypatch, "gemma3:4b")
    refused = httpx.ConnectError("[Errno 111] Connection refused")
    with patch.object(llm_module.httpx, "AsyncClient", _probe_client(raises=refused)):
        assert await llm_module.check_fallback_provider() == "unreachable"


@pytest.mark.asyncio
async def test_probe_says_off_when_disabled_and_never_touches_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not configured is a choice, not a fault — and must not cost a request."""
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    factory = _probe_client(_tags("gemma3:4b"))
    with patch.object(llm_module.httpx, "AsyncClient", factory):
        assert await llm_module.check_fallback_provider() == "off"
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_probe_treats_a_bare_name_as_its_latest_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama resolves `qwen3.5` to `qwen3.5:latest`; calling that missing is a
    false alarm, and a probe that cries wolf gets switched off."""
    _enable_ollama(monkeypatch, "qwen3.5")
    with patch.object(llm_module.httpx, "AsyncClient", _probe_client(_tags("qwen3.5:latest"))):
        assert await llm_module.check_fallback_provider() == "ok"
