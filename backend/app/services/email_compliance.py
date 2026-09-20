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
from dataclasses import dataclass
from html import escape

from app.config import get_settings

log = logging.getLogger(__name__)

__all__ = [
    "FOOTER_OPENERS",
    "MissingPostalAddress",
    "build_footer",
    "build_footer_html",
    "lead_id_from_token",
    "unsubscribe_token",
    "unsubscribe_url",
]

# Domain separation. Prefixing the message with a constant nobody else uses
# means a signature produced here cannot verify anywhere else even if the
# underlying secret is ever shared.
_DOMAIN = b"eko-email-unsubscribe::v1"

#: The sentence that opens the footer, per language. Exported because the
#: footer ends up inside `Message.content`, and `conversation.history_content`
#: has to recognise it there: a model that reads its own compliance footer back
#: as part of a past turn copies it into the next one, and the real footer is
#: then appended on top. Measured on 2026-09-19 — three copies in one reply, by
#: the third turn of a thread. `_footer_parts` builds from this tuple so the
#: two cannot drift apart.
FOOTER_OPENERS: tuple[str, str] = (
    "Don't want these emails? Unsubscribe here:",
    "Si no quieres volver a recibir correos nuestros, cancela la suscripción aquí:",
)

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


@dataclass(frozen=True)
class _FooterParts:
    """The facts a compliant footer is made of, before anyone renders them.

    Text and HTML are two renderings of ONE set of facts, not two templates. A
    footer whose HTML half quietly lost the postal address while the text half
    kept it would pass every test that reads `body_text` and still be the
    violation, so neither renderer is allowed its own source of truth.
    """

    #: The full sentence the plain-text footer uses, link on the next line.
    stop: str
    #: The same invitation with the link taken out of it, for HTML, where the
    #: URL hides behind `word` instead of being printed.
    ask: str
    #: What the link says in HTML. CAN-SPAM wants the opt-out "clear and
    #: conspicuous"; the word Unsubscribe as a link is the standard form of it.
    word: str
    url: str
    #: Empty when the agency has not set one.
    brokerage: str
    address: str


def _footer_parts(
    *, lead_id: int, brokerage_line: str | None, lang: str | None
) -> _FooterParts:
    """Raises `MissingPostalAddress` — see `build_footer`."""
    address = (get_settings().POSTAL_ADDRESS or "").strip()
    if not address:
        raise MissingPostalAddress(
            "POSTAL_ADDRESS is empty. CAN-SPAM requires a valid physical postal "
            "address in every commercial message, so no compliant footer can be "
            "built and nothing may be sent. Set POSTAL_ADDRESS to the agency's "
            "mailing address to turn the automated email channel on."
        )
    spanish = lang == "es"
    return _FooterParts(
        stop=FOOTER_OPENERS[1] if spanish else FOOTER_OPENERS[0],
        ask=(
            "¿No quieres volver a recibir correos nuestros?"
            if spanish
            else "Don't want these emails?"
        ),
        word="Cancelar suscripción" if spanish else "Unsubscribe",
        url=unsubscribe_url(lead_id),
        brokerage=(brokerage_line or "").strip(),
        address=address,
    )


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
    p = _footer_parts(lead_id=lead_id, brokerage_line=brokerage_line, lang=lang)
    parts = [p.stop, p.url]
    if p.brokerage:
        parts.append(p.brokerage)
    parts.append(p.address)
    return "\n".join(parts)


def build_footer_html(
    *, lead_id: int, brokerage_line: str | None, lang: str | None = None
) -> str:
    """The same footer for the HTML half. Raises `MissingPostalAddress` too.

    Only the URL hides — behind one word. The brokerage line and the postal
    address stay VISIBLE text, because they are what the law asks to be on the
    page; a mailing address behind a link is an address nobody reads.

    Styles are inline and the stack is a system serif: Gmail strips `<style>`
    blocks and `@font-face`, so a brand font here would look like a brand font
    only in the one client nobody uses.
    """
    p = _footer_parts(lead_id=lead_id, brokerage_line=brokerage_line, lang=lang)
    rows = [
        f'{escape(p.ask)} <a href="{escape(p.url, quote=True)}" '
        f'style="color:#6b6b6b;">{escape(p.word)}</a>.'
    ]
    if p.brokerage:
        rows.append(escape(p.brokerage))
    rows.append(escape(p.address))
    inner = "<br>".join(rows)
    return (
        '<div style="margin-top:28px;padding-top:14px;'
        'border-top:1px solid #e0e0e0;font-size:12px;color:#6b6b6b;">'
        f"{inner}</div>"
    )
