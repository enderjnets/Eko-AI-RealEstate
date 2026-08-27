"""This channel exists to reach people thinking about SELLING a home.

Two things are under test, and neither is a style preference:

1. **The balance of the rotation.** It used to be 6 buyer topics against 1
   seller. Generating correct content for the wrong audience is not a harmless
   miss: it spends LLM quota and publishing slots building the wrong audience,
   and the videos exist to bring sellers to the landing page.

2. **The call to action reaches the Fair Housing filter.** The CTA is appended
   before `find_violations` runs, so what gets published is what the gate read.
   Appending it afterwards would publish text the filter never saw — the exact
   shape of the defect fixed in v0.56.0, where the filter existed and did not
   cover the live lane.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.config import get_settings
from app.models import ContentLanguage
from app.services.content_topics import BOTH, BUYER, SELLER, TOPICS
from app.services.content_writer import DraftPayload, _ask, _with_cta
from app.services.llm import LLMResult

_URL = "www.denverhomestory.com"


# ── 1. La rotación ───────────────────────────────────────────────────────────


def test_every_topic_says_who_it_is_for() -> None:
    """A topic added without a real audience would silently dilute the balance
    the next test measures, so the label itself is checked first."""
    allowed = {SELLER, BUYER, BOTH}
    unlabelled = [t.key for t in TOPICS if t.audience not in allowed]
    assert not unlabelled, f"topics with no usable audience: {unlabelled}"


def test_the_rotation_speaks_to_sellers_more_than_to_buyers() -> None:
    """`next_topic` is `TOPICS[n % len(TOPICS)]`, so one full cycle IS this
    tuple: the proportion here is the proportion that gets published."""
    seller = sum(1 for t in TOPICS if t.audience == SELLER)
    buyer = sum(1 for t in TOPICS if t.audience == BUYER)
    both = sum(1 for t in TOPICS if t.audience == BOTH)

    assert seller > buyer, (
        f"the rotation publishes {buyer} buyer topics against {seller} seller "
        "ones; this channel is meant to bring in people who want to sell"
    )
    assert (seller + both) * 3 >= len(TOPICS) * 2, (
        f"only {seller + both} of {len(TOPICS)} topics reach a seller at all"
    )


def test_every_topic_is_written_in_both_languages() -> None:
    """The repo norm: no key ships in one language only."""
    missing = [t.key for t in TOPICS if not t.brief_en.strip() or not t.brief_es.strip()]
    assert not missing, f"topics missing a brief in one language: {missing}"


def test_topic_keys_are_unique() -> None:
    keys = [t.key for t in TOPICS]
    assert len(keys) == len(set(keys)), "two topics share a key; one shadows the other"


# ── 2. La llamada a la acción ────────────────────────────────────────────────


def _draft(caption: str = "Save this before you list.") -> DraftPayload:
    return DraftPayload(hook="A hook.", script="A script.", caption=caption)


def test_no_url_configured_means_no_call_to_action(monkeypatch) -> None:
    """A link to a domain that does not resolve yet is worse than no link."""
    monkeypatch.setattr(get_settings(), "CONTENT_CTA_URL", "")
    out = _with_cta(_draft(), ContentLanguage.EN)
    assert out is not None
    assert "denverhomestory" not in out.caption


def test_the_call_to_action_carries_the_url_verbatim(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "CONTENT_CTA_URL", _URL)
    out = _with_cta(_draft(), ContentLanguage.EN)
    assert out is not None
    assert out.caption.endswith(_URL), out.caption
    assert "Save this before you list." in out.caption, "the caption was replaced, not extended"


def test_the_spanish_draft_gets_the_spanish_call_to_action(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "CONTENT_CTA_URL", _URL)
    out = _with_cta(_draft("Guarda esto antes de listar."), ContentLanguage.ES)
    assert out is not None
    assert "vender en Denver" in out.caption
    assert out.caption.endswith(_URL)


def test_applying_it_twice_does_not_stack_two_links(monkeypatch) -> None:
    """The rewrite path calls the same machinery a second time."""
    monkeypatch.setattr(get_settings(), "CONTENT_CTA_URL", _URL)
    once = _with_cta(_draft(), ContentLanguage.EN)
    twice = _with_cta(once, ContentLanguage.EN)
    assert twice is not None
    assert twice.caption.count(_URL) == 1


@pytest.mark.asyncio
async def test_the_filter_sees_the_caption_that_will_be_published(monkeypatch) -> None:
    """The one that matters.

    `_ask` is what the generator calls, and its result is what
    `find_violations` is handed. If the CTA were appended after that check, the
    draft coming out of `_ask` would NOT carry it — so asserting it here is
    asserting that the published caption passed the gate.
    """
    monkeypatch.setattr(get_settings(), "CONTENT_CTA_URL", _URL)
    reply = LLMResult(
        text=json.dumps(
            {"hook": "A hook.", "script": "A script.", "caption": "Save this."}
        ),
        provider="kimi",
        model="test",
        input_tokens=1,
        output_tokens=1,
    )
    with patch(
        "app.services.content_writer.generate_reply", AsyncMock(return_value=reply)
    ):
        draft = await _ask(TOPICS[0], ContentLanguage.EN)
    assert draft is not None
    assert _URL in draft.caption, (
        "the draft handed to the Fair Housing check does not carry the CTA, so "
        "the published caption would contain text the filter never read"
    )
