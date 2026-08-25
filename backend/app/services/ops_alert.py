"""Telling a human that the machinery broke.

Separate from `services/email.py` on purpose, and the separation is not
cosmetic. `send_email()` resolves the outbound identity **of the acting
organization** so agency B's lead is never answered from agency A's address — a
bug this repo has already paid for. A monitor runs in a background worker with
no request and therefore no org, so it has no identity to resolve; and an alert
addressed to the operator is not a reply to anybody's lead. Routing it through
the tenant sender would be borrowing an agency's mailbox to send ourselves mail.

Two rules govern everything here, and both come from failures that already
happened:

1. **Fire on a change, never on a state.** Six correct alarms repeated on a
   schedule become background noise, and the operator learns to scroll past
   them — at which point the alarm is worse than nothing, because it looks like
   coverage. The caller owns the comparison; this module only sends.
2. **Spend a hard-capped budget.** This shares the email provider's quota with
   the replies that go to real customers. A level-triggered alert every five
   minutes is 288 messages a day: it would exhaust the quota and take down the
   product it is watching. The cap below is the circuit breaker for that.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

# Ceiling per UTC day across all subjects. Sized for "an incident produces one
# alert and one recovery": three leaves room for a second incident in the same
# day and still cannot dent a mail quota. Anything beyond this is a loop, and a
# loop must be capped rather than delivered.
MAX_ALERTS_PER_DAY = 3

_RESEND_URL = "https://api.resend.com/emails"


class OpsAlertNotSent(RuntimeError):
    """The alert could not be sent. Never raised at the caller — logged."""


async def send_operator_alert(subject: str, body: str) -> bool:
    """Email the platform operators. Returns True only if it actually went out.

    Never raises: this is called from a background worker whose real job is to
    keep watching. A watchdog that dies because it could not send mail stops
    being a watchdog, and the state it measured is still on /api/v1/health.
    """
    s = get_settings()
    recipients = s.platform_admin_emails_list

    if not recipients:
        log.error(
            "Operator alert not sent (PLATFORM_ADMIN_EMAILS is empty) — subject=%r", subject
        )
        return False
    if not (s.OPS_ALERT_FROM or "").strip():
        # Said out loud rather than swallowed: a monitor that cannot reach
        # anyone is exactly the kind of thing that looks fine for three months.
        log.error(
            "Operator alert not sent (OPS_ALERT_FROM unset) — subject=%r. Set it to a "
            "sender on a domain verified with the email provider. Body was: %s",
            subject, body,
        )
        return False
    if not (s.RESEND_API_KEY or "").strip():
        log.error("Operator alert not sent (RESEND_API_KEY unset) — subject=%r", subject)
        return False

    if s.EMAIL_SIMULATED:
        log.info("Operator alert SIMULATED to=%s subject=%r body=%s", recipients, subject, body)
        return True

    payload: dict[str, Any] = {
        "from": s.OPS_ALERT_FROM,
        "to": recipients,
        "subject": subject,
        "text": body,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                _RESEND_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {s.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code >= 400:
            log.error(
                "Operator alert REJECTED by provider: status=%d body=%s — subject=%r",
                resp.status_code, resp.text[:300], subject,
            )
            return False
    except Exception as exc:  # noqa: BLE001 — the watcher must survive its transport
        log.error("Operator alert failed to send (%s: %s) — subject=%r", type(exc).__name__, exc, subject)
        return False

    log.info("Operator alert sent to=%s subject=%r", recipients, subject)
    return True
