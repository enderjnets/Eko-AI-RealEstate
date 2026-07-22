"""Pure tests for the RESO Web API (MLS Grid) adapter — no DB, no real token.

The HTTP layer is faked via httpx.MockTransport injected through `_reso_client`, so
these exercise pagination, incremental filters, status mapping, attribution, media
ordering and retry/backoff without touching the network.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import unquote

import httpx
import pytest

from app.models import PropertyStatus
from app.services import listings as L


def _resp(json_body: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=json_body)


def _install(monkeypatch, handler) -> None:
    """Point `_reso_client` at a MockTransport running `handler`, no real backoff."""

    def _client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(L, "_reso_client", _client)
    monkeypatch.setattr(L, "_RETRY_BASE_DELAY", 0.0)


async def _collect(**kwargs) -> list[L.ListingDTO]:
    out: list[L.ListingDTO] = []
    async for page in L._fetch_reso_pages("https://api.mlsgrid.test/v2", "tok", **kwargs):
        out.extend(page)
    return out


# ── status mapping ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "standard_status, mlg_can_view, expected",
    [
        ("Active", True, PropertyStatus.ACTIVE),
        ("Pending", True, PropertyStatus.PENDING),
        ("Active Under Contract", True, PropertyStatus.PENDING),
        ("Closed", True, PropertyStatus.SOLD),
        ("Withdrawn", True, PropertyStatus.OFF_MARKET),
        ("Canceled", True, PropertyStatus.OFF_MARKET),
        ("Active", False, PropertyStatus.OFF_MARKET),  # MlgCanView=false forces off-market
        ("SomethingWeird", True, PropertyStatus.OFF_MARKET),  # unknown → safe default
        (None, None, PropertyStatus.OFF_MARKET),
    ],
)
def test_map_status(standard_status, mlg_can_view, expected):
    assert L._map_status(standard_status, mlg_can_view) is expected


# ── OData literal helpers ──────────────────────────────────────────────────────


def test_odata_str_escapes_single_quotes():
    assert L._odata_str("O'Brien") == "'O''Brien'"
    assert L._odata_str("recolorado") == "'recolorado'"


def test_odata_dt_is_utc_z():
    dt = datetime(2026, 7, 20, 12, 34, 56, tzinfo=UTC)
    assert L._odata_dt(dt) == "2026-07-20T12:34:56Z"


# ── record mapping: photo order, decimal baths, attribution, cursor ────────────


def test_map_record_orders_photos_and_captures_attribution():
    rec = {
        "ListingKey": "R123",
        "ListPrice": 750000,
        "StandardStatus": "Active",
        "PropertySubType": "Single Family Residence",
        "City": "Aurora",
        "BedroomsTotal": 3,
        "BathroomsTotalDecimal": 2.5,  # half-baths matter for matching
        "LivingArea": 2100,
        "ModificationTimestamp": "2026-07-20T10:00:00Z",
        "ListOfficeName": "REcolorado Partner Realty",
        "ListAgentFullName": "Natalia K.",
        "Media": [
            {"MediaURL": "https://img/2.jpg", "Order": 2},
            {"MediaURL": "https://img/0.jpg", "Order": 0},
            {"MediaURL": "https://img/1.jpg", "Order": 1},
            {"Order": 3},  # no MediaURL → skipped
        ],
    }
    dto = L._map_reso_record(rec)
    assert dto is not None
    assert dto.external_id == "R123"
    assert dto.status is PropertyStatus.ACTIVE
    assert str(dto.bathrooms) == "2.5"
    assert dto.photos == ["https://img/0.jpg", "https://img/1.jpg", "https://img/2.jpg"]
    assert dto.raw["list_office_name"] == "REcolorado Partner Realty"
    assert dto.raw["list_agent_name"] == "Natalia K."
    assert dto.source_modified_at == datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC)


def test_map_record_without_key_is_none():
    assert L._map_reso_record({"ListPrice": 1}) is None


def test_map_record_bathrooms_integer_fallback():
    dto = L._map_reso_record(
        {"ListingKey": "K", "StandardStatus": "Active", "BathroomsTotalInteger": 3}
    )
    assert dto is not None and str(dto.bathrooms) == "3"


# ── outgoing request: OriginatingSystem + incremental cursor + $expand ──────────


async def test_outgoing_request_filters_and_expand(monkeypatch):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return _resp({"value": []})

    _install(monkeypatch, handler)
    cursor = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
    await _collect(modified_since=cursor, city="Aurora")

    dec = unquote(seen["url"])
    assert "OriginatingSystemName eq 'recolorado'" in dec
    assert "ModificationTimestamp ge 2026-07-01T00:00:00Z" in dec
    assert "City eq 'Aurora'" in dec
    assert "$expand=Media" in dec
    assert "ModificationTimestamp,ListingKey" in dec


async def test_outgoing_request_escapes_city_quote(monkeypatch):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return _resp({"value": []})

    _install(monkeypatch, handler)
    await _collect(city="O'Fallon")
    assert "City eq 'O''Fallon'" in unquote(seen["url"])


# ── pagination via @odata.nextLink ─────────────────────────────────────────────


async def test_pagination_follows_nextlink(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _resp(
                {
                    "value": [{"ListingKey": "A", "StandardStatus": "Active"}],
                    "@odata.nextLink": "https://api.mlsgrid.test/v2/Property?$skiptoken=2",
                }
            )
        return _resp({"value": [{"ListingKey": "B", "StandardStatus": "Active"}]})

    _install(monkeypatch, handler)
    out = await _collect()
    assert [d.external_id for d in out] == ["A", "B"]
    assert calls["n"] == 2


async def test_pagination_respects_max_pages(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return _resp(
            {
                "value": [{"ListingKey": "X", "StandardStatus": "Active"}],
                "@odata.nextLink": "https://api.mlsgrid.test/v2/Property?$skiptoken=loop",
            }
        )

    _install(monkeypatch, handler)
    pages = 0
    async for _page in L._fetch_reso_pages("https://api.mlsgrid.test/v2", "tok", max_pages=3):
        pages += 1
    assert pages == 3  # stopped at the cap despite an endless nextLink


# ── retry / error handling ─────────────────────────────────────────────────────


async def test_retry_then_success(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="temporarily unavailable")
        return _resp({"value": [{"ListingKey": "Z", "StandardStatus": "Active"}]})

    _install(monkeypatch, handler)
    out = await _collect()
    assert [d.external_id for d in out] == ["Z"]
    assert calls["n"] == 2  # retried once


async def test_http_client_error_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    _install(monkeypatch, handler)
    with pytest.raises(L.ListingsError):
        await _collect()


# ── misconfiguration guard (prevents the worker spinning on errors) ────────────


async def test_sync_listings_real_without_creds_raises(monkeypatch):
    monkeypatch.setattr(
        L,
        "get_settings",
        lambda: SimpleNamespace(
            LISTINGS_SIMULATED=False, RESO_BASE_URL="", RESO_ACCESS_TOKEN=""
        ),
    )
    with pytest.raises(L.ListingsError):
        await L.sync_listings(None)  # raises before touching the db
