"""Tests for app.services.classifier.classify_intent — schema + error degradation.

The classifier delegates to llm.generate_reply, which we mock to return canned
strings; no real LLM calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models import LeadIntent
from app.services import classifier as classifier_module
from app.services.classifier import IntentEntities, IntentResult, classify_intent
from app.services.conversation import merge_budget
from app.services.llm import LLMResult, LLMUnavailable


def _llm_returning(text: str) -> AsyncMock:
    return AsyncMock(
        return_value=LLMResult(
            text=text, provider="kimi", model="kimi-for-coding", input_tokens=20, output_tokens=40
        )
    )


@pytest.mark.asyncio
async def test_clean_json_is_parsed() -> None:
    raw = """{
        "intent": "rent",
        "confidence": 0.92,
        "entities": {
            "zone": "Malasaña",
            "budget_min": null,
            "budget_max": 1200,
            "property_type": "apartment",
            "urgency": "weeks"
        }
    }"""
    with patch.object(classifier_module, "generate_reply", _llm_returning(raw)):
        result = await classify_intent([{"role": "user", "content": "alquiler en Malasaña 1200€"}])

    assert isinstance(result, IntentResult)
    assert result.intent == LeadIntent.RENT
    assert result.confidence == 0.92
    assert result.entities.zone == "Malasaña"
    assert result.entities.budget_max == 1200
    assert result.entities.budget_min is None
    assert result.entities.urgency == "weeks"


@pytest.mark.asyncio
async def test_confidence_clamps_to_unit_interval() -> None:
    raw = '{"intent": "buy", "confidence": 1.7, "entities": {}}'
    with patch.object(classifier_module, "generate_reply", _llm_returning(raw)):
        result = await classify_intent([{"role": "user", "content": "comprar"}])

    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_json_with_surrounding_prose_is_extracted() -> None:
    raw = (
        "Claro, aquí tienes el JSON:\n"
        '{"intent": "valuation", "confidence": 0.8, "entities": {"zone": "Salamanca"}}'
        "\nEspero te sirva."
    )
    with patch.object(classifier_module, "generate_reply", _llm_returning(raw)):
        result = await classify_intent([{"role": "user", "content": "tasar mi piso"}])

    assert result.intent == LeadIntent.VALUATION
    assert result.entities.zone == "Salamanca"


@pytest.mark.asyncio
async def test_invalid_json_degrades_to_other() -> None:
    raw = "This is not JSON at all — Kimi was confused"
    with patch.object(classifier_module, "generate_reply", _llm_returning(raw)):
        result = await classify_intent([{"role": "user", "content": "blah"}])

    assert result.intent == LeadIntent.OTHER
    assert result.confidence == 0.0
    assert result.raw_response == raw


@pytest.mark.asyncio
async def test_invalid_intent_value_degrades_to_other() -> None:
    raw = '{"intent": "nosense_value", "confidence": 0.9, "entities": {}}'
    with patch.object(classifier_module, "generate_reply", _llm_returning(raw)):
        result = await classify_intent([{"role": "user", "content": "blah"}])

    assert result.intent == LeadIntent.OTHER
    assert result.raw_response == raw


@pytest.mark.asyncio
async def test_llm_unavailable_degrades_to_other() -> None:
    failing = AsyncMock(side_effect=LLMUnavailable("all providers down"))
    with patch.object(classifier_module, "generate_reply", failing):
        result = await classify_intent([{"role": "user", "content": "hola"}])

    assert result.intent == LeadIntent.OTHER
    assert result.confidence == 0.0
    assert "LLMUnavailable" in (result.raw_response or "")


@pytest.mark.asyncio
async def test_budget_string_with_euro_sign_coerces() -> None:
    raw = '{"intent": "rent", "confidence": 0.7, "entities": {"budget_max": "1.500€"}}'
    with patch.object(classifier_module, "generate_reply", _llm_returning(raw)):
        result = await classify_intent([{"role": "user", "content": "alquiler 1500"}])

    assert result.entities.budget_max == 1500.0


class TestBudgetCoercion:
    """The classifier is the one writer whose input nobody checks: it comes
    from a language model reading free text. Everything it produces has to be
    either storable or discarded — never something that raises, because this
    runs inside the transaction that saves the customer's message."""

    def test_american_thousands_separators_are_not_a_decimal_point(self) -> None:
        # "450,000" used to come out as 450. Positive, in range, not inverted,
        # so every guard downstream waved it through — and the lead was then
        # matched against houses a thousand times cheaper than they asked for.
        # This is a Colorado brokerage; prices are written this way here.
        assert IntentEntities(budget_max="450,000").budget_max == 450_000
        assert IntentEntities(budget_max="1,200,000").budget_max == 1_200_000
        assert IntentEntities(budget_max="$450,000").budget_max == 450_000

    def test_european_formatting_still_works(self) -> None:
        # The original convention, kept: the first customers were Spanish-
        # speaking and the model may still answer this way.
        assert IntentEntities(budget_max="1.200.000").budget_max == 1_200_000
        assert IntentEntities(budget_max="1.200.000,50").budget_max == 1_200_000.5
        assert IntentEntities(budget_max="450,5").budget_max == 450.5

    def test_a_plain_decimal_is_left_alone(self) -> None:
        assert IntentEntities(budget_max="450.5").budget_max == 450.5
        assert IntentEntities(budget_max=900_000).budget_max == 900_000

    def test_a_value_the_database_would_refuse_is_dropped_not_raised(self) -> None:
        # The database refuses negatives and overflows NUMERIC(12,2) past ten
        # digits. Either would abort the inbound transaction — and because the
        # provider replays the same message, every retry would fail the same
        # way and the message would be lost for good. One missing field is a
        # far cheaper failure than a lost conversation.
        assert IntentEntities(budget_max=-50_000).budget_max is None
        assert IntentEntities(budget_min="-1").budget_min is None
        assert IntentEntities(budget_max=1e14).budget_max is None

    def test_nonsense_becomes_nothing(self) -> None:
        for junk in ("abc", "", None, "n/a", "null", "$"):
            assert IntentEntities(budget_max=junk).budget_max is None


class TestBudgetMerge:
    """What the classifier extracts has to be reconciled with what the lead
    already holds. Both directions of getting this wrong are silent: a range
    the wrong way round matches nothing, and a stale value that refuses to be
    corrected keeps showing people what they said they did not want."""

    @staticmethod
    def _merge(stored, extracted):
        """The real function, not a copy of it — a reimplementation here would
        stay green while the code it describes drifted away underneath."""
        return merge_budget(stored, extracted)

    def test_a_complete_range_overrides_a_stale_guess(self) -> None:
        # The customer says "between 100 and 300". An earlier message had left
        # a minimum of 500k. Skipping both — which is what the previous fix did
        # — left them permanently at 500k, matched against houses they had just
        # ruled out, however many times they repeated themselves.
        assert self._merge((500_000, None), (100_000, 300_000)) == (100_000, 300_000)

    def test_a_backwards_range_is_ignored_entirely(self) -> None:
        assert self._merge((None, None), (900_000, 100_000)) == (None, None)
        assert self._merge((100_000, 300_000), (900_000, 100_000)) == (100_000, 300_000)

    def test_a_single_value_only_fills_a_gap(self) -> None:
        assert self._merge((None, 300_000), (100_000, None)) == (100_000, 300_000)
        assert self._merge((100_000, None), (None, 300_000)) == (100_000, 300_000)
        # Already known: an established budget is not overwritten by a guess.
        assert self._merge((100_000, 300_000), (None, 900_000)) == (100_000, 300_000)

    def test_a_single_value_that_would_invert_the_pair_is_refused(self) -> None:
        # This one matters twice over: the pair would match nothing, and the
        # database refuses it outright — which would abort the transaction
        # holding the customer's message.
        assert self._merge((None, 300_000), (900_000, None)) == (None, 300_000)
        assert self._merge((900_000, None), (None, 300_000)) == (900_000, None)
