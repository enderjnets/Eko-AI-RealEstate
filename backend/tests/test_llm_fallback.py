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
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")
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
    assert result.model == "llama-3.3-70b-versatile"
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
    assert body["model"] == "llama-3.3-70b-versatile"
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
    assert result.model == "llama-3.3-70b-versatile"
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
