"""Tests for the listings service — SIMULATED fetch + matching shape.

Pure (no DB): exercises fetch_listings in SIMULATED mode and the DTO invariants.
DB-backed sync + matching are covered in test_properties_api.py.
"""
from __future__ import annotations

import pytest

from app.services.listings import fetch_listings


@pytest.mark.asyncio
async def test_fetch_simulated_returns_listings() -> None:
    listings = await fetch_listings()
    assert len(listings) >= 5
    for dto in listings:
        assert dto.external_id
        assert dto.title
        assert dto.listing_type in ("sale", "rent")


@pytest.mark.asyncio
async def test_fetch_has_both_sale_and_rent() -> None:
    types = {dto.listing_type for dto in await fetch_listings()}
    assert "sale" in types
    assert "rent" in types


@pytest.mark.asyncio
async def test_fetch_city_filter_miami() -> None:
    listings = await fetch_listings(city="Miami")
    assert listings
    assert all((dto.city or "").lower() == "miami" for dto in listings)


@pytest.mark.asyncio
async def test_fetch_city_filter_unknown_is_empty() -> None:
    assert await fetch_listings(city="Nowhereville") == []


@pytest.mark.asyncio
async def test_fetch_limit() -> None:
    assert len(await fetch_listings(limit=2)) == 2
