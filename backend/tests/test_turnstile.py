"""The captcha, which until now was never exercised past its first `if`.

One test existed and it posted with no token, so `_turnstile_ok` short-circuited
and never issued a request. Everything after that line — the URL, the payload,
reading `success`, and the fail-closed handler that is the whole security
argument — was unverified.

That mattered more than usual here, because the feature had already shipped
non-functional once: the secret never reached the container, so the endpoint
accepted every submission without checking, which from outside is
indistinguishable from a captcha that works.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.public import TURNSTILE_VERIFY_URL, _turnstile_ok, reset_rate_limits
from app.config import get_settings
from app.main import app


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Stands in for httpx.AsyncClient and records what was sent."""

    calls: list[tuple[str, dict]] = []

    def __init__(self, payload: dict | None = None, raises: Exception | None = None):
        # `payload or {...}` would turn an intentionally EMPTY reply into a
        # success, because {} is falsy — which made the malformed-reply test
        # fail against correct code.
        self._payload = {"success": True} if payload is None else payload
        self._raises = raises

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, data: dict) -> _FakeResponse:
        _FakeClient.calls.append((url, data))
        if self._raises:
            raise self._raises
        return _FakeResponse(self._payload)


def _client_factory(payload: dict | None = None, raises: Exception | None = None):
    def factory(*_args: object, **_kwargs: object) -> _FakeClient:
        return _FakeClient(payload, raises)

    return factory


@pytest.fixture(autouse=True)
def _clean() -> None:
    _FakeClient.calls = []
    reset_rate_limits()
    settings = get_settings()
    before = settings.TURNSTILE_SECRET
    yield
    settings.TURNSTILE_SECRET = before
    reset_rate_limits()


# ── The verification call itself ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_secret_means_no_call_and_no_captcha() -> None:
    get_settings().TURNSTILE_SECRET = ""
    assert await _turnstile_ok("anything", "203.0.113.1") is True
    assert _FakeClient.calls == [], "must not contact Cloudflare when unconfigured"


@pytest.mark.asyncio
async def test_a_valid_token_is_accepted_and_sent_correctly() -> None:
    get_settings().TURNSTILE_SECRET = "sec"
    with patch("app.api.v1.public.httpx.AsyncClient", _client_factory({"success": True})):
        assert await _turnstile_ok("tok", "203.0.113.1") is True
    url, data = _FakeClient.calls[0]
    assert url == TURNSTILE_VERIFY_URL
    assert data["secret"] == "sec"
    assert data["response"] == "tok"
    assert data["remoteip"] == "203.0.113.1"


@pytest.mark.asyncio
async def test_cloudflare_saying_no_is_a_no() -> None:
    get_settings().TURNSTILE_SECRET = "sec"
    with patch(
        "app.api.v1.public.httpx.AsyncClient",
        _client_factory({"success": False, "error-codes": ["invalid-input-response"]}),
    ):
        assert await _turnstile_ok("tok", "203.0.113.1") is False


@pytest.mark.asyncio
async def test_it_fails_closed_when_cloudflare_cannot_be_reached() -> None:
    """The entire security argument, and nothing tested it.

    A captcha that waves everyone through whenever Cloudflare has a bad minute
    is not a captcha. Mutating this handler to `return True` left the whole
    suite green before this test existed.
    """
    get_settings().TURNSTILE_SECRET = "sec"
    with patch(
        "app.api.v1.public.httpx.AsyncClient",
        _client_factory(raises=TimeoutError("connect timeout")),
    ):
        assert await _turnstile_ok("tok", "203.0.113.1") is False


@pytest.mark.asyncio
async def test_a_malformed_reply_is_a_no() -> None:
    get_settings().TURNSTILE_SECRET = "sec"
    with patch("app.api.v1.public.httpx.AsyncClient", _client_factory({})):
        assert await _turnstile_ok("tok", "203.0.113.1") is False


# ── remoteip ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remoteip_is_omitted_rather_than_wrong() -> None:
    """Better to send nothing than the proxy's own address.

    With no forwarding header the socket peer is the FRONTEND container on the
    Docker bridge, because the POST is proxied through Next's `/api/*` rewrite.
    Asserting that to Cloudflare as the visitor's IP is a classic source of
    spurious failures; the field is optional.
    """
    get_settings().TURNSTILE_SECRET = "sec"
    with patch("app.api.v1.public.httpx.AsyncClient", _client_factory({"success": True})):
        assert await _turnstile_ok("tok", None) is True
    _, data = _FakeClient.calls[0]
    assert "remoteip" not in data


@pytest.mark.asyncio
async def test_the_endpoint_forwards_the_visitor_ip_when_a_proxy_supplied_it() -> None:
    get_settings().TURNSTILE_SECRET = "sec"
    with patch("app.api.v1.public.httpx.AsyncClient", _client_factory({"success": True})):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/v1/public/leads",
                json={"email": "cf@turnstile.test", "turnstile_token": "tok"},
                headers={"cf-connecting-ip": "198.51.100.7"},
            )
    assert _FakeClient.calls, "the endpoint must actually verify"
    _, data = _FakeClient.calls[0]
    assert data["remoteip"] == "198.51.100.7"


@pytest.mark.asyncio
async def test_the_endpoint_sends_no_remoteip_without_a_proxy_header() -> None:
    get_settings().TURNSTILE_SECRET = "sec"
    with patch("app.api.v1.public.httpx.AsyncClient", _client_factory({"success": True})):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/v1/public/leads",
                json={"email": "noproxy@turnstile.test", "turnstile_token": "tok"},
            )
    _, data = _FakeClient.calls[0]
    assert "remoteip" not in data


# ── The runtime surface ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_reports_whether_the_captcha_is_actually_on() -> None:
    """A misconfiguration has to be visible without SSH.

    The failure mode is silent acceptance, so "is the captcha verifying" cannot
    be answered by looking at the form. It was answerable only from one line in
    the startup log, which a later rebuild that dropped the value would not
    reprint anywhere anyone looks.
    """
    settings = get_settings()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        settings.TURNSTILE_SECRET = ""
        assert (await client.get("/api/v1/health")).json()["captcha"] == "off"

        settings.TURNSTILE_SECRET = "sec"
        body = (await client.get("/api/v1/health")).json()
        assert body["captcha"] == "on"
        # And never the value — this endpoint is unauthenticated.
        assert "sec" not in str(body)
