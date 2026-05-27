"""Tests for file import — text extraction + LLM lead extraction (mocked)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.file_import import extract_leads, extract_text
from app.services.llm import LLMResult


def test_extract_text_plaintext_and_csv() -> None:
    assert "Acme Realty" in extract_text("leads.txt", b"Acme Realty, +13035550000")
    csv = b"name,phone\nMile High Homes,+13035551212\n"
    out = extract_text("db.csv", csv)
    assert "Mile High Homes" in out and "+13035551212" in out


def test_extract_text_strips_html() -> None:
    out = extract_text("page.html", b"<html><body><p>Bob Realty</p></body></html>")
    assert "Bob Realty" in out and "<p>" not in out


def test_extract_text_empty() -> None:
    assert extract_text("x.txt", b"") == ""


def _reply(text: str) -> LLMResult:
    return LLMResult(text=text, provider="kimi", model="kimi-for-coding", input_tokens=10, output_tokens=10)


@pytest.mark.asyncio
async def test_extract_leads_parses_json_array() -> None:
    payload = (
        '[{"business_name":"Acme Realty","phone":"+13035550000","email":"info@acme2.com",'
        '"website":"https://acme.example","city":"Denver","category":"Brokerage"},'
        '{"business_name":"Bob Homes","phone":"+13035551111"}]'
    )
    with patch("app.services.file_import.generate_reply", AsyncMock(return_value=_reply(payload))):
        leads = await extract_leads("some contact list text")
    assert len(leads) == 2
    assert leads[0].business_name == "Acme Realty"
    assert leads[0].source == "import"
    assert leads[0].email == "info@acme2.com"
    assert leads[1].phone == "+13035551111"


@pytest.mark.asyncio
async def test_extract_leads_tolerates_prose_around_json() -> None:
    with patch("app.services.file_import.generate_reply",
               AsyncMock(return_value=_reply('Here you go:\n[{"business_name":"X Co"}]\nDone'))):
        leads = await extract_leads("text")
    assert len(leads) == 1 and leads[0].business_name == "X Co"


@pytest.mark.asyncio
async def test_extract_leads_bad_output_returns_empty() -> None:
    with patch("app.services.file_import.generate_reply", AsyncMock(return_value=_reply("no json here"))):
        assert await extract_leads("text") == []


@pytest.mark.asyncio
async def test_extract_leads_empty_text_skips_llm() -> None:
    # No LLM call for empty input.
    with patch("app.services.file_import.generate_reply", AsyncMock()) as m:
        assert await extract_leads("   ") == []
        m.assert_not_called()
