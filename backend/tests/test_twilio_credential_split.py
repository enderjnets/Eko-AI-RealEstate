"""One Twilio value used to do two jobs; now it does one.

`TWILIO_AUTH_TOKEN` authenticated everything we SENT and validated the signature
on everything we RECEIVED. That is a single point of compromise with an
unusually bad blast radius: a leak lets someone spend our Twilio balance AND
forge inbound webhooks, and rotating it breaks both halves at the same moment.
It is not hypothetical here — the token was found in plain text in a shell
history file on the ROG, which is why this split was written.

Twilio's own guidance: "Use API keys for all applications. If a key is
compromised or no longer used, revoke it to prevent unauthorized access without
affecting your other applications."

The half that CANNOT move is the signature: "Twilio hashes the signature with
the HMAC-SHA1 hashing algorithm using your account auth token as the secret
key." No API Key can produce or verify that, so `inbound_secret` stays the auth
token forever — and the test that matters most below is the one asserting that
it did not quietly follow `credential` across.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.models.channel_route import CHANNEL_SMS
from app.models.organization import DEFAULT_ORG_ID
from app.services.channel_identity import resolve_outbound_identity
from app.services.tenant_context import org_scope

KEY_SID = "SK00000000000000000000000000000001"
KEY_SECRET = "aBcDeFgHiJkLmNoPqRsTuVwXyZ012345"


def _settings(monkeypatch, **env: str):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(autouse=True)
def _restore_settings_cache():
    # The settings object is cached process-wide; leaving a patched one behind
    # would hand the next test a Twilio account it never configured.
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sending_uses_the_api_key_when_one_is_configured(monkeypatch) -> None:
    _settings(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest",
        TWILIO_AUTH_TOKEN="the-auth-token",
        TWILIO_API_KEY_SID=KEY_SID,
        TWILIO_API_KEY_SECRET=KEY_SECRET,
    )
    with org_scope(DEFAULT_ORG_ID):
        identity = await resolve_outbound_identity(CHANNEL_SMS)

    assert identity.credential == KEY_SECRET
    assert identity.credential_user == KEY_SID
    # The account still identifies the account in the request path.
    assert identity.provider_account == "ACtest"


@pytest.mark.asyncio
async def test_the_inbound_secret_stays_the_auth_token(monkeypatch) -> None:
    """The one that must never regress.

    If `inbound_secret` ever follows `credential` onto the API Key, every
    inbound SMS and voice webhook starts failing signature validation and
    returning 403 — the funnel goes deaf while the site stays up and every
    dashboard stays green. Nothing else in the suite would notice.
    """
    _settings(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest",
        TWILIO_AUTH_TOKEN="the-auth-token",
        TWILIO_API_KEY_SID=KEY_SID,
        TWILIO_API_KEY_SECRET=KEY_SECRET,
    )
    with org_scope(DEFAULT_ORG_ID):
        identity = await resolve_outbound_identity(CHANNEL_SMS)

    assert identity.inbound_secret == "the-auth-token"
    assert identity.inbound_secret != identity.credential


@pytest.mark.asyncio
async def test_without_an_api_key_nothing_changes(monkeypatch) -> None:
    """Every install that has not configured a key keeps working exactly as before."""
    _settings(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest",
        TWILIO_AUTH_TOKEN="the-auth-token",
        TWILIO_API_KEY_SID="",
        TWILIO_API_KEY_SECRET="",
    )
    with org_scope(DEFAULT_ORG_ID):
        identity = await resolve_outbound_identity(CHANNEL_SMS)

    assert identity.credential == "the-auth-token"
    assert identity.credential_user is None


@pytest.mark.parametrize(
    "sid,secret",
    [(KEY_SID, ""), ("", KEY_SECRET)],
    ids=["sid-without-secret", "secret-without-sid"],
)
@pytest.mark.asyncio
async def test_half_a_key_falls_back_instead_of_sending_a_broken_pair(
    monkeypatch, sid: str, secret: str
) -> None:
    """A half-finished rotation must not authenticate as half a key.

    Using the SID with the auth token as its password (or the secret with the
    Account SID as its username) is a 401 from Twilio on every send. Falling
    back keeps messages flowing; the operator finds the unfinished half when
    they revoke the key and nothing breaks.
    """
    _settings(
        monkeypatch,
        TWILIO_ACCOUNT_SID="ACtest",
        TWILIO_AUTH_TOKEN="the-auth-token",
        TWILIO_API_KEY_SID=sid,
        TWILIO_API_KEY_SECRET=secret,
    )
    with org_scope(DEFAULT_ORG_ID):
        identity = await resolve_outbound_identity(CHANNEL_SMS)

    assert identity.credential == "the-auth-token"
    assert identity.credential_user is None


@pytest.mark.asyncio
async def test_the_send_path_actually_puts_the_key_in_the_authorization(monkeypatch) -> None:
    """Reaching the wire, not just the dataclass.

    `resolve_outbound_identity` returning the right pair proves nothing if
    `send_sms` still builds `auth=(account_sid, ...)` — which is exactly what it
    did before this change, and what a careless revert would restore.
    """
    import httpx

    from app.services import sms as sms_service

    _settings(
        monkeypatch,
        SMS_SIMULATED="false",
        TWILIO_ACCOUNT_SID="ACtest",
        TWILIO_AUTH_TOKEN="the-auth-token",
        TWILIO_API_KEY_SID=KEY_SID,
        TWILIO_API_KEY_SECRET=KEY_SECRET,
        TWILIO_PHONE_NUMBER="+13055551234",
    )

    seen: dict[str, object] = {}

    async def fake_post(self, url, **kwargs):  # noqa: ANN001
        seen["url"] = url
        seen["auth"] = kwargs.get("auth")
        return httpx.Response(
            201, json={"sid": "SM1", "status": "queued"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with org_scope(DEFAULT_ORG_ID):
        await sms_service.send_sms(to="+13055559999", body="hola")

    assert seen["auth"] == (KEY_SID, KEY_SECRET)
    # The Account SID, not the key SID, still addresses the resource.
    assert "/Accounts/ACtest/Messages.json" in str(seen["url"])
