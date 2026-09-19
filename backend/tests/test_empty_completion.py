"""The completion that looked like a success and carried nothing.

Measured in production on 2026-09-19. Kimi was returning 403 (weekly quota), so
every call fell to MiniMax-M2.7 — a reasoning model. With the classifier capped
at 300 tokens it spent the whole budget inside a `thinking` block and returned no
text at all. `llm.py` keeps only blocks of `type == "text"`, so the classifier
received `""`, gave up, and filed lead 1268 with no intent, no budget, no zone
and no urgency — from an email that named all four. The line above it logged
`LLM ok`.

Three separate faults, and this file holds one test for each:

  * a completion with no text block is a PROVIDER failure and must fall back,
  * a text block holding `""` is a model with nothing to say and must NOT,
  * the classifier must ask for enough room to think and still speak.

Plus the Markdown the same reply carried to a real person: `**What could you
buy?**`, asterisks intact, because no channel we send on renders Markdown.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.conversation import strip_markdown
from app.services.llm import LLMUnavailable, generate_reply


def _text_response(text: str, out_tok: int = 34) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    resp.usage = MagicMock(input_tokens=12, output_tokens=out_tok)
    return resp


def _thinking_only_response() -> MagicMock:
    """What MiniMax-M2.7 actually returned, reproduced from the live call.

    One `thinking` block, no text, `stop_reason=max_tokens`. Verified against the
    real API on 2026-09-19: the same prompt to MiniMax-M3 comes back with a
    `text` block, which is why the model default moved.
    """
    block = MagicMock()
    block.type = "thinking"
    block.thinking = "The user says ... This is ambiguous. Possibly they mean"
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "max_tokens"
    resp.usage = MagicMock(input_tokens=43, output_tokens=300)
    return resp


def _client_with(side_effect: Any) -> MagicMock:
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=side_effect)
    return client


@pytest.fixture(autouse=True)
def _providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "dummy-kimi-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "dummy-minimax-key")
    monkeypatch.setenv("LLM_PRIMARY", "kimi")
    monkeypatch.setenv("LLM_FALLBACK", "minimax")
    # The local and free links are pinned off so these say what they say on a
    # machine that has real keys in its environment.
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("GROQ_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_completion_with_no_text_block_falls_back() -> None:
    """The fault this whole file exists for.

    Before the fix the primary's empty answer was returned as a success and the
    fallback was never reached — which is how a classifier goes dark with
    nothing anywhere turning red.
    """
    clients = [_client_with([_thinking_only_response()]), _client_with([_text_response("{}")])]
    with patch("app.services.llm._build_client", side_effect=clients):
        result = await generate_reply([{"role": "user", "content": "hi"}])

    assert result.provider == "minimax", "the empty primary has to hand over"
    assert result.text == "{}"


@pytest.mark.asyncio
async def test_the_failure_names_the_block_types_and_the_stop_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Those two facts together ARE the diagnosis.

    `stop_reason=max_tokens` with only a `thinking` block says "this model spent
    its budget before it spoke" in one line, which is the difference between
    finding this in minutes and finding it in a week.
    """
    clients = [_client_with([_thinking_only_response()]), _client_with([_text_response("ok")])]
    with patch(
        "app.services.llm._build_client", side_effect=clients
    ), caplog.at_level("ERROR"):
        await generate_reply([{"role": "user", "content": "hi"}])

    assert "thinking" in caplog.text
    assert "max_tokens" in caplog.text
    assert "no text block" in caplog.text


@pytest.mark.asyncio
async def test_an_empty_text_block_is_not_a_provider_failure() -> None:
    """A model with nothing to say is not a broken provider.

    The test is zero text BLOCKS, never an empty string: retrying this one on a
    second provider would spend a call to be told the same thing, and would hide
    a prompt that produces silence behind an infrastructure story.
    """
    clients = [_client_with([_text_response("")]), _client_with([_text_response("fallback")])]
    with patch("app.services.llm._build_client", side_effect=clients):
        result = await generate_reply([{"role": "user", "content": "hi"}])

    assert result.provider == "kimi", "the primary answered; it just said nothing"
    assert result.text == ""


@pytest.mark.asyncio
async def test_when_no_provider_can_speak_the_caller_is_told() -> None:
    clients = [_client_with([_thinking_only_response()]), _client_with([_thinking_only_response()])]
    with patch("app.services.llm._build_client", side_effect=clients):
        with pytest.raises(LLMUnavailable):
            await generate_reply([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_the_classifier_leaves_room_to_think_and_still_speak() -> None:
    """300 was the number that broke it, so the number is the assertion.

    The JSON asked for is about sixty tokens. The rest is headroom for a
    reasoning model, and pinning it here means shrinking it back turns this red
    instead of turning production silent.
    """
    from app.services.classifier import classify_intent

    sent: dict[str, Any] = {}

    async def _capture(*args: Any, **kwargs: Any) -> Any:
        sent.update(kwargs)
        return MagicMock(
            text='{"intent": "buy", "confidence": 0.9}',
            provider="minimax",
            model="MiniMax-M3",
        )

    with patch("app.services.classifier.generate_reply", new=_capture):
        await classify_intent([{"role": "user", "content": "I want to buy"}])

    assert sent["max_tokens"] == 800
    assert sent["temperature"] == 0.0


@pytest.mark.asyncio
async def test_a_classifier_that_extracts_nothing_is_an_error_not_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """It ran at WARNING in production and read like noise.

    When this fires the lead is filed cold with the whole substance of the
    conversation thrown away — the level has to match the damage, and the line
    has to name the model so the next person knows which one to stop using.
    """
    from app.services.classifier import classify_intent

    async def _empty(*args: Any, **kwargs: Any) -> Any:
        return MagicMock(text="", provider="minimax", model="MiniMax-M2.7")

    with patch("app.services.classifier.generate_reply", new=_empty), caplog.at_level("DEBUG"):
        result = await classify_intent([{"role": "user", "content": "hola"}])

    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errors, "a lead filed with nothing extracted is not a warning"
    assert "MiniMax-M2.7" in caplog.text, "name the model that produced nothing"
    assert result.confidence == 0.0


def test_the_markdown_that_reached_a_real_lead_is_stripped() -> None:
    """Verbatim from message 1368, which a person received.

    No channel we send on renders Markdown, and the persona already asks for
    plain prose. The model reaches for asterisks anyway, so they come off in
    code rather than by request.
    """
    sent = (
        "**What could you buy?** That really depends on current rates, and "
        "what's on the market in the $350K-$500K range.\n\n"
        "- **Send you current Wash Park-area listings** in your price range.\n"
        "### Next steps\n"
    )
    cleaned = strip_markdown(sent)

    assert "**" not in cleaned
    assert "What could you buy?" in cleaned
    assert "Send you current Wash Park-area listings" in cleaned
    assert cleaned.rstrip().endswith("Next steps")
    assert "#" not in cleaned


def test_whatsapp_bold_is_left_alone() -> None:
    """Single asterisks are formatting on WhatsApp, not Markdown leakage.

    Stripping them to tidy an email would delete real emphasis on the channel
    that carries most of the conversations.
    """
    assert strip_markdown("based on *your* full picture") == "based on *your* full picture"
