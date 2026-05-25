"""Tests for app.services.classifier.classify_intent — schema + error degradation.

The classifier delegates to llm.generate_reply, which we mock to return canned
strings; no real LLM calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models import LeadIntent
from app.services import classifier as classifier_module
from app.services.classifier import IntentResult, classify_intent
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
