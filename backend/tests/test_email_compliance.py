"""The three things that have to exist before automated email may be sent.

`models/lead.py` says the sender "stays human until those three exist" — an
unsubscribe, a physical address, and an opt-out that email is part of. This file
is how that sentence stops being prose.

No database here: the token is a pure function and the footer reads settings.
The route that spends the token, and the first-opt-out-wins rule it has to
honour, live in `test_unsubscribe_route.py` against live Postgres.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.email import send_email
from app.services.email_compliance import (
    MissingPostalAddress,
    build_footer,
    lead_id_from_token,
    unsubscribe_token,
    unsubscribe_url,
)

ADDRESS = "123 Test Ave Ste 1, Denver, CO 80200"


@pytest.fixture(autouse=True)
def _fresh_settings() -> None:
    """`get_settings` is cached, and these tests move the settings under it."""
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── the token ────────────────────────────────────────────────────────────


def test_a_token_names_its_lead_and_survives_the_round_trip() -> None:
    assert lead_id_from_token(unsubscribe_token(1267)) == 1267


def test_two_leads_never_share_a_token() -> None:
    assert unsubscribe_token(1) != unsubscribe_token(2)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "no-dot",
        "MTI2Nw.deadbeef",  # right shape, wrong signature
        "....",
        "MTI2Nw",  # payload with no signature at all
    ],
)
def test_a_token_we_did_not_sign_names_nobody(bad: str | None) -> None:
    # Every failure is the same answer. A route that distinguished them would
    # tell a stranger which lead ids exist.
    assert lead_id_from_token(bad) is None


def test_the_signature_covers_the_lead_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swapping the payload for another lead's must not verify."""
    mine = unsubscribe_token(1267)
    theirs = unsubscribe_token(999)
    forged = theirs.split(".")[0] + "." + mine.split(".")[1]
    assert lead_id_from_token(forged) is None


def test_a_token_does_not_expire() -> None:
    """Deliberate: a link that stops working is a person who cannot make us stop.

    Two mintings of the same id agree, so an old newsletter in somebody's
    archive keeps honouring them.
    """
    assert unsubscribe_token(42) == unsubscribe_token(42)


def test_the_url_is_public_and_carries_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTENT_CTA_URL", "https://www.denverhomestory.com/")
    from app.config import get_settings

    get_settings.cache_clear()
    url = unsubscribe_url(1267)
    assert url.startswith("https://www.denverhomestory.com/api/v1/public/unsubscribe/")
    assert lead_id_from_token(url.rsplit("/", 1)[1]) == 1267
    assert "//api" not in url  # the trailing slash on the base is not doubled


# ── the footer ───────────────────────────────────────────────────────────


def test_without_a_postal_address_the_footer_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The switch for the whole channel. It raises rather than degrading: a
    footer with a hole in it is a CAN-SPAM violation that cannot be un-sent."""
    monkeypatch.setenv("POSTAL_ADDRESS", "")
    from app.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(MissingPostalAddress):
        build_footer(lead_id=1267, brokerage_line="Engel & Voelkers")


def test_a_whitespace_address_is_not_an_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTAL_ADDRESS", "   ")
    from app.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(MissingPostalAddress):
        build_footer(lead_id=1267, brokerage_line=None)


def test_the_footer_carries_the_address_the_link_and_the_brokerage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTAL_ADDRESS", ADDRESS)
    monkeypatch.setenv("CONTENT_CTA_URL", "https://www.denverhomestory.com")
    from app.config import get_settings

    get_settings.cache_clear()
    footer = build_footer(lead_id=1267, brokerage_line="Engel & Voelkers · Each office…")
    assert ADDRESS in footer
    assert "/api/v1/public/unsubscribe/" in footer
    # Colorado 6.10.A.4: advertising names the brokerage firm.
    assert "Engel & Voelkers" in footer
    assert "Unsubscribe" in footer


def test_the_footer_speaks_the_visitor_s_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTAL_ADDRESS", ADDRESS)
    from app.config import get_settings

    get_settings.cache_clear()
    assert "cancela la suscripción" in build_footer(
        lead_id=1, brokerage_line=None, lang="es"
    )
    assert "Unsubscribe here" in build_footer(lead_id=1, brokerage_line=None, lang="en")


def test_a_missing_brokerage_line_does_not_invent_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """It is a fact about the agency — the registered name the Commission holds —
    and not a string this module is entitled to compose."""
    monkeypatch.setenv("POSTAL_ADDRESS", ADDRESS)
    from app.config import get_settings

    get_settings.cache_clear()
    footer = build_footer(lead_id=1, brokerage_line=None)
    assert ADDRESS in footer
    assert footer.count("\n") == 2  # the ask, the link, the address. Nothing else.


# ── the headers ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_email_sets_both_list_unsubscribe_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RFC 2369 for the link, RFC 8058 for the one-click POST.

    Gmail and Outlook show their own Unsubscribe button only when both are
    present, and that button is the one most people actually use — a footer
    alone leaves them hitting "spam" instead, which costs the sending domain.
    """
    monkeypatch.setenv("EMAIL_SIMULATED", "false")
    from app.config import get_settings

    get_settings.cache_clear()

    sent: dict[str, Any] = {}

    class _Identity:
        credential = "re_test"
        destination = "Denver Home Story <hello@example.com>"
        sender_override = None

    async def _identity(_channel: str) -> _Identity:
        return _Identity()

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"id": "resend.test"}

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, **_kw: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        async def post(self, _url: str, json: dict[str, Any], **_kw: Any) -> _Resp:
            sent.update(json)
            return _Resp()

    monkeypatch.setattr("app.services.email.resolve_outbound_identity", _identity)
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    await send_email(
        to="someone@example.com",
        subject="Your Denver numbers",
        body_text="…",
        unsubscribe_url="https://www.denverhomestory.com/api/v1/public/unsubscribe/abc.def",
    )

    headers = sent.get("headers") or {}
    assert headers["List-Unsubscribe"] == (
        "<https://www.denverhomestory.com/api/v1/public/unsubscribe/abc.def>"
    )
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


@pytest.mark.asyncio
async def test_a_message_without_the_url_carries_no_unsubscribe_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A realtor's own reply must not invite the reader to switch her off."""
    monkeypatch.setenv("EMAIL_SIMULATED", "false")
    from app.config import get_settings

    get_settings.cache_clear()

    sent: dict[str, Any] = {}

    class _Identity:
        credential = "re_test"
        destination = "Denver Home Story <hello@example.com>"
        sender_override = None

    async def _identity(_channel: str) -> _Identity:
        return _Identity()

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"id": "resend.test"}

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, **_kw: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        async def post(self, _url: str, json: dict[str, Any], **_kw: Any) -> _Resp:
            sent.update(json)
            return _Resp()

    monkeypatch.setattr("app.services.email.resolve_outbound_identity", _identity)
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    await send_email(to="someone@example.com", subject="Re: your question", body_text="…")

    assert "List-Unsubscribe" not in (sent.get("headers") or {})
