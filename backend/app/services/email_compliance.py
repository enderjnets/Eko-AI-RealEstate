"""What an automated commercial email must carry before it may be sent.

Three things have kept this product's email channel switched off, and they are
named in three separate places in the codebase rather than in one:
`models/lead.py` ("the sender stays human until those three exist"),
`followups.py` ("a compliance decision, not a configuration one") and
`optout.py` ("Email unsubscribes are a link and a List-Unsubscribe header, not
a one-word reply"). This module is those three things.

**The unsubscribe is a link, not a keyword.** That is why `optout.py` is not
extended here: it parses what someone typed, and nobody types STOP at an email
footer. The link carries a signed token so the route can identify a lead
without accepting a bare id from a stranger — an unauthenticated endpoint that
took `?lead=1267` would let anyone walk the table and silence an agency's book.

**The key is derived, not shared.** `services/auth.py` signs session tokens and
says of its secret that it "has exactly one audience". Reusing it would give it
two, and a token minted for one purpose that verifies for the other is how an
unsubscribe link becomes a login. Same secret material, separate key, separate
domain string.

**The footer refuses rather than degrades.** A commercial message without a
physical postal address is a CAN-SPAM violation, so `build_footer` raises when
`POSTAL_ADDRESS` is empty instead of quietly sending a footer with a hole in
it. The caller is expected to let that stop the send. A channel that is off
because a setting is missing announces itself the first time someone tries to
use it; a channel that sends non-compliant mail does not.

Not in scope here: whether a given lead may be written to. That is
`capture.may_send_automated`, which reads `opted_out_at` first for every
channel — including this one.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging

from app.config import get_settings

log = logging.getLogger(__name__)

__all__ = [
    "MissingPostalAddress",
    "build_footer",
    "lead_id_from_token",
    "unsubscribe_token",
    "unsubscribe_url",
]

# Domain separation. Prefixing the message with a constant nobody else uses
# means a signature produced here cannot verify anywhere else even if the
# underlying secret is ever shared.
_DOMAIN = b"eko-email-unsubscribe::v1"

# What lands in `leads.opted_out_keyword` when the link is what stopped us. The
# column takes 40 characters; the other writers put the word the person typed,
# and this is the honest equivalent for a click.
OPT_OUT_KEYWORD = "unsubscribe-link"


class MissingPostalAddress(RuntimeError):
    """`POSTAL_ADDRESS` is empty, so no compliant footer can be built."""


def _key() -> bytes:
    s = get_settings()
    # AUTH_SECRET is the only secret this install is guaranteed to have, but it
    # is never used raw here — see the module docstring.
    material = (s.AUTH_SECRET or "eko-unsubscribe::insecure-dev-only").encode("utf-8")
    return hashlib.sha256(_DOMAIN + b"::" + material).digest()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def unsubscribe_token(lead_id: int) -> str:
    """A tamper-evident `<lead_id>.<signature>` for one lead.

    Deliberately WITHOUT an expiry. An unsubscribe link that stops working is a
    person who cannot make us stop, which is the outcome the law is about; a
    six-month-old newsletter in somebody's archive has to keep honouring them.
    """
    body = str(int(lead_id)).encode("ascii")
    sig = hmac.new(_key(), body, hashlib.sha256).digest()
    return f"{_b64e(body)}.{_b64e(sig)}"


def lead_id_from_token(token: str | None) -> int | None:
    """The lead the token names, or None when it names nobody.

    Every failure — malformed, wrong signature, not a number — returns None and
    says nothing about which it was. The route turns all of them into the same
    answer, so this cannot be used to probe which lead ids exist.
    """
    if not token or "." not in token:
        return None
    body_b64, sig_b64 = token.rsplit(".", 1)
    try:
        body = _b64d(body_b64)
        expected = hmac.new(_key(), body, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(sig_b64), expected):
            return None
        return int(body.decode("ascii"))
    except (ValueError, TypeError, UnicodeDecodeError, base64.binascii.Error):
        return None


def unsubscribe_url(lead_id: int) -> str:
    """The public link that appears in the footer and in `List-Unsubscribe`."""
    base = (get_settings().CONTENT_CTA_URL or "").rstrip("/")
    return f"{base}/api/v1/public/unsubscribe/{unsubscribe_token(lead_id)}"


def build_footer(*, lead_id: int, brokerage_line: str | None, lang: str | None = None) -> str:
    """The block every automated commercial email to a lead has to end with.

    Raises `MissingPostalAddress` when the address is not configured. Callers
    must let that stop the send rather than catching it and mailing anyway: the
    footer IS the compliance, and an email that reached someone without one
    cannot be un-sent.

    `brokerage_line` is printed as stored, not composed here. Colorado's Rule
    6.10.A.4 requires advertising to name the brokerage firm, and 6.10.A.2
    requires the name the Commission holds — which is a fact about the agency,
    not a string this module is entitled to invent or correct.
    """
    address = (get_settings().POSTAL_ADDRESS or "").strip()
    if not address:
        raise MissingPostalAddress(
            "POSTAL_ADDRESS is empty. CAN-SPAM requires a valid physical postal "
            "address in every commercial message, so no compliant footer can be "
            "built and nothing may be sent. Set POSTAL_ADDRESS to the agency's "
            "mailing address to turn the automated email channel on."
        )
    spanish = lang == "es"
    stop = (
        "Si no quieres volver a recibir correos nuestros, cancela la suscripción aquí:"
        if spanish
        else "Don't want these emails? Unsubscribe here:"
    )
    parts = [stop, unsubscribe_url(lead_id)]
    line = (brokerage_line or "").strip()
    if line:
        parts.append(line)
    parts.append(address)
    return "\n".join(parts)
