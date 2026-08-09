"""Tests for lead scoring — the pure `compute_lead_score` heuristic + tiers."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Lead, LeadIntent, LeadStatus
from app.services.scoring import (
    HOT_THRESHOLD,
    WARM_THRESHOLD,
    compute_lead_score,
    score_tier,
)

NOW = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)


def _lead(**kw) -> Lead:
    defaults = dict(
        phone="+1305000",
        status=LeadStatus.NEW,
        intent=None,
        budget_min=None,
        budget_max=None,
        zone=None,
        property_type=None,
        urgency=None,
        last_message_at=None,
        human_takeover=False,
    )
    defaults.update(kw)
    return Lead(**defaults)


def test_empty_lead_scores_low() -> None:
    score, b = compute_lead_score(lead=_lead(), inbound_count=0, has_active_visit=False, now=NOW)
    assert score == 0
    assert b["tier"] == "cold"


def test_fully_qualified_lead_is_hot() -> None:
    lead = _lead(
        status=LeadStatus.QUALIFIED,
        intent=LeadIntent.BUY,
        budget_min=Decimal("600000"),
        budget_max=Decimal("850000"),
        zone="Brickell",
        property_type="condo",
        urgency="high",
        last_message_at=NOW - timedelta(hours=2),
    )
    score, b = compute_lead_score(lead=lead, inbound_count=5, has_active_visit=True, now=NOW)
    assert score == 100  # all components max out
    assert b["tier"] == "hot"
    assert score >= HOT_THRESHOLD


def test_won_and_lost_are_zeroed() -> None:
    base_kw = dict(
        intent=LeadIntent.BUY, budget_min=Decimal("1"), budget_max=Decimal("2"),
        zone="X", property_type="condo", urgency="high", last_message_at=NOW,
    )
    for st in (LeadStatus.WON, LeadStatus.LOST):
        score, b = compute_lead_score(
            lead=_lead(status=st, **base_kw), inbound_count=5, has_active_visit=True, now=NOW
        )
        assert score == 0, st
        assert b["status_gate"] == 0.0


def test_paused_is_halved() -> None:
    kw = dict(
        status=LeadStatus.PAUSED, intent=LeadIntent.BUY,
        budget_min=Decimal("1"), budget_max=Decimal("2"),
        zone="X", property_type="condo", urgency="high", last_message_at=NOW,
    )
    paused_score, b = compute_lead_score(lead=_lead(**kw), inbound_count=5, has_active_visit=True, now=NOW)
    kw_active = dict(kw)
    kw_active["status"] = LeadStatus.QUALIFIED
    active_score, _ = compute_lead_score(lead=_lead(**kw_active), inbound_count=5, has_active_visit=True, now=NOW)
    assert paused_score == round(active_score * 0.5)
    assert b["status_gate"] == 0.5


def test_engagement_scales_with_inbound_count() -> None:
    lead = _lead(status=LeadStatus.NEW)
    s0, _ = compute_lead_score(lead=lead, inbound_count=0, has_active_visit=False, now=NOW)
    s1, _ = compute_lead_score(lead=lead, inbound_count=1, has_active_visit=False, now=NOW)
    s4, _ = compute_lead_score(lead=lead, inbound_count=4, has_active_visit=False, now=NOW)
    assert s0 < s1 < s4


def test_recency_decays() -> None:
    base = dict(status=LeadStatus.NEW, intent=LeadIntent.BUY)
    fresh, _ = compute_lead_score(
        lead=_lead(last_message_at=NOW - timedelta(hours=1), **base),
        inbound_count=1, has_active_visit=False, now=NOW,
    )
    stale, _ = compute_lead_score(
        lead=_lead(last_message_at=NOW - timedelta(days=30), **base),
        inbound_count=1, has_active_visit=False, now=NOW,
    )
    assert fresh > stale


def test_score_is_clamped_0_100() -> None:
    lead = _lead(
        status=LeadStatus.VISITING, intent=LeadIntent.BUY,
        budget_min=Decimal("1"), budget_max=Decimal("2"),
        zone="X", property_type="condo", urgency="urgent",
        last_message_at=NOW,
    )
    score, _ = compute_lead_score(lead=lead, inbound_count=99, has_active_visit=True, now=NOW)
    assert 0 <= score <= 100


def test_tier_thresholds() -> None:
    assert score_tier(HOT_THRESHOLD) == "hot"
    assert score_tier(WARM_THRESHOLD) == "warm"
    assert score_tier(WARM_THRESHOLD - 1) == "cold"
    assert score_tier(0) == "cold"
