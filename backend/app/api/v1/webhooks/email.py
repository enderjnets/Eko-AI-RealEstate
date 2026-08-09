"""Email inbound webhook (Resend)."""
from __future__ import annotations

import json
import logging
from email.policy import default as _email_policy

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db
from app.models.channel_route import CHANNEL_EMAIL
from app.services.channel_identity import inbound_secret_or_503
from app.services.conversation import handle_inbound_message
from app.services.email import fetch_inbound_email, parse_inbound_email, verify_resend_signature
from app.services.tenant_context import set_org_id
from app.services.tenant_resolver import WebhookOrgUnresolved, webhook_org_or_refuse

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/email")
async def email_inbound(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Resend POSTs here when an inbound email arrives at our domain.

    Headers we care about:
      svix-id        — unique event id
      svix-timestamp — unix seconds
      svix-signature — `v1,<base64>` (possibly multiple, space-separated)

    Returns 200 unless body is malformed JSON — same idempotency contract as
    the WhatsApp webhook (UNIQUE on messages.external_id catches retries).
    """
    s = get_settings()
    raw = await request.body()
    svix_id = request.headers.get("svix-id")
    svix_timestamp = request.headers.get("svix-timestamp")
    svix_signature = request.headers.get("svix-signature")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Email webhook: invalid JSON: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    if not s.EMAIL_SIMULATED:
        # Chicken and egg: with per-agency Resend accounts the signing secret
        # depends on which mailbox was written to, and that lives inside the
        # payload the signature authenticates. Parsing first is safe because the
        # addresses are used only to *look up* a key: a forged recipient either
        # names no route, so the global secret applies, or names another
        # agency's, whose signature the forger cannot produce. The HMAC is still
        # computed over the original raw bytes, never a re-serialization.
        identity = await inbound_secret_or_503(CHANNEL_EMAIL, _mailboxes(payload))
        ok = verify_resend_signature(
            raw,
            svix_id=svix_id,
            svix_timestamp=svix_timestamp,
            svix_signature=svix_signature,
            secret=identity.inbound_secret or "",
        )
        if not ok:
            log.warning("Resend webhook signature verification failed")
            raise HTTPException(status_code=403, detail="Invalid signature")

    # Which agency's mailbox was written to. Resolved before any write, and
    # before the body fetch below: that call needs the agency's own Resend key,
    # and running it first meant it used the operator's — a 401 the `except`
    # swallowed, leaving the agent to answer an email whose body it never read.
    try:
        set_org_id(await webhook_org_or_refuse(CHANNEL_EMAIL, _mailboxes(payload)))
    except WebhookOrgUnresolved as exc:
        # 200, not 503. This refusal is *permanent*: the addresses map to no
        # agency, or to two, or to a suspended one. Asking Resend to redeliver
        # only produces the same answer forever, and a provider that keeps
        # seeing failures backs off or disables the endpoint — which would take
        # the channel down for every tenant, not just this one. Nothing is
        # written either way; the error log is the signal, and the operator
        # fixes it by mapping the address.
        log.error("refusing inbound email — %s", exc)
        return {"status": "unrouted"}

    # Real Resend `email.received` webhooks are METADATA-ONLY (no body/headers).
    # Fetch the full email (text + Message-ID + References) from the Received
    # Emails API so the agent sees real content AND replies thread correctly.
    # SIMULATED test payloads already carry the body, so they skip the fetch.
    data = payload.get("data") if isinstance(payload, dict) else None
    if (
        not s.EMAIL_SIMULATED
        and isinstance(data, dict)
        and payload.get("type") == "email.received"
        and not data.get("text")
    ):
        email_id = data.get("id") or data.get("email_id")
        if email_id:
            try:
                detail = await fetch_inbound_email(email_id)
            except Exception as exc:  # noqa: BLE001
                detail = None
                log.warning("Could not fetch full inbound email %s: %s", email_id, exc)
            if detail:
                payload = {"type": "email.received", "data": detail}
            else:
                # 503, not a 200 with an empty body. A real `email.received`
                # webhook is metadata only, so without the fetch the agent
                # answers a message it never read — confidently, and to a lead.
                # Returning success meant Resend never redelivered and nobody
                # found out; the reorder above fixed the cause of the failure
                # but left this outcome untouched.
                log.error("inbound email %s has no body to answer", email_id)
                return JSONResponse(
                    {"status": "body_unavailable", "external_id": email_id},
                    status_code=503,
                )

    parsed_messages = parse_inbound_email(payload)
    if not parsed_messages:
        return {"status": "ok", "processed": 0}

    results = []
    failed = False
    for parsed in parsed_messages:
        try:
            result = await handle_inbound_message(parsed, db)
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            failed = True
            log.exception("Error processing email %s: %s", parsed.external_id, exc)
            results.append({"status": "error", "external_id": parsed.external_id, "error": str(exc)})

    if failed:
        # 500 so Resend redelivers. Duplicates return normally from
        # handle_inbound_message, so reaching here means nothing was stored.
        return JSONResponse(
            {"status": "error", "processed": len(parsed_messages), "results": results},
            status_code=500,
        )
    return {"status": "ok", "processed": len(parsed_messages), "results": results}


def _mailboxes(payload: dict) -> list[str]:
    """Every address this message was addressed to, in no meaningful order.

    All of them, deliberately. This used to return the *first* entry of `to`,
    with a comment right above it admitting the agency's own address is not
    always first — so a lead writing to agency B while CC'ing agency A had their
    whole thread, lead row and transcript filed under A. Handing the full set to
    the resolver lets it match exactly one route and refuse when two agencies
    are both addressed, which is the same rule WhatsApp already follows.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    # The envelope first, and alone when it is there. `to` and `cc` are written
    # by the SENDER: anyone can mail an unrouted mailbox on the operator's own
    # domain with an agency's address in `To:`, and the message is then
    # genuinely signed by the operator's Resend account. The envelope recipient
    # is what the provider actually delivered to, so when the payload carries
    # one it is the only honest routing key.
    envelope = data.get("envelope")
    envelope_to = (
        envelope.get("to") if isinstance(envelope, dict) else None
    ) or data.get("envelope_to")
    sources = (
        (envelope_to,)
        if envelope_to
        else (data.get("to"), data.get("cc"), data.get("recipient"))
    )

    found: list[str] = []
    for candidate in sources:
        if isinstance(candidate, str) and candidate.strip():
            found.extend(_addresses_in(candidate))
        elif isinstance(candidate, list):
            for item in candidate:
                addr = item.get("email") if isinstance(item, dict) else item
                if isinstance(addr, str) and addr.strip():
                    found.extend(_addresses_in(addr))
    return found


def _addresses_in(value: str) -> list[str]:
    """Every address a header genuinely names, as tenant routing keys.

    Whatever comes back here decides which agency an inbound email belongs to
    AND which agency's secret verifies it, so anything a *sender* controls must
    not reach this list. Two shapes did:

    - **RFC 5322 group syntax.** `To: undisclosed:victim@agency.test;` is a
      named group, and `getaddresses` flattens its members into ordinary
      addresses. A message genuinely delivered to an unrouted mailbox on the
      operator's own domain therefore reported exactly one address — the
      victim's — so the "two agencies named, refuse" rule never fired and the
      lead, transcript and AI reply landed in their tenant. Named groups are
      dropped.
    - **A malformed header whose display name looks like an address.**
      `To: victim@agency.test <hello@operator.com>` resolves to the *display*
      text, because an unquoted `@` there is a defect the parser settles in the
      sender's favour. A header the parser reports defects on is not trusted to
      name a tenant.

    The one defect worth recovering from is Outlook's semicolon separator,
    which is common and unambiguous: retry by splitting at top-level semicolons
    and keep the result only if every piece then parses cleanly.
    """
    unfolded = " ".join(value.splitlines())
    found = _parse_clean(unfolded)
    if found is not None:
        return found

    pieces = _split_top_level(unfolded, ";")
    if len(pieces) < 2:
        return []
    recovered: list[str] = []
    for piece in pieces:
        part = _parse_clean(piece)
        if part is None:
            return []
        recovered.extend(part)
    return recovered


def _parse_clean(value: str) -> list[str] | None:
    """Addresses from a header that parses without defects, or None.

    None means "do not trust this", which is not the same as "names nobody".
    """
    cleaned = value.strip().rstrip(", \t")
    if not cleaned:
        return []
    try:
        header = _email_policy.header_factory("to", cleaned)
    except Exception:  # noqa: BLE001 — an unparseable header names nobody
        return None
    if header.defects:
        return None
    # Any named group and the whole header is untrusted, not just that group.
    # Dropping only its members stopped a sender ADDING an address and handed
    # them the power to REMOVE one: `undisclosed:hello@operator.test;,
    # leads@agencyb.test` deleted the honest recipient from the set, so the
    # "two agencies named, refuse" rule saw one owner and filed the lead,
    # transcript and reply into agency B. Group syntax never appears in mail a
    # lead actually sends, so refusing the header costs nothing real.
    if any(group.display_name is not None for group in header.groups):
        return None
    return [
        entry.addr_spec.strip()
        for group in header.groups
        for entry in group.addresses
        if entry.addr_spec and "@" in entry.addr_spec
    ]


def _split_top_level(value: str, separator: str) -> list[str]:
    """Split on `separator` outside quoted strings and angle brackets."""
    pieces: list[str] = []
    current: list[str] = []
    in_quotes = False
    in_angles = False
    escaped = False
    for char in value:
        if escaped:
            escaped = False
            current.append(char)
            continue
        if char == "\\" and in_quotes:
            # A backslash-escaped quote inside a quoted string is not a
            # terminator. Treating it as one desynchronised this from the RFC
            # parser, so a legitimate display name silently lost the message.
            escaped = True
            current.append(char)
            continue
        if char == '"':
            in_quotes = not in_quotes
        elif char == "<" and not in_quotes:
            in_angles = True
        elif char == ">" and not in_quotes:
            in_angles = False
        if char == separator and not in_quotes and not in_angles:
            pieces.append("".join(current))
            current = []
            continue
        current.append(char)
    pieces.append("".join(current))
    return [p for p in (piece.strip() for piece in pieces) if p]
