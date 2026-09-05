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
3. **Two transports, because one is a single point of silence.** Measured on
   5-sep-2026: `monitor_state.llm_fallback` held `state=unreachable` with
   `alerted_state=ok` and all three daily attempts spent — the operator was
   never told the safety net had gone. An alert counts as delivered when
   **either** email or Telegram accepts it, and both are attempted every time
   rather than one as a fallback for the other: the whole point is that a fault
   in one cannot produce silence.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services import telegram_notify

log = logging.getLogger(__name__)

# Ceiling per UTC day across all subjects. Sized for "an incident produces one
# alert and one recovery": three leaves room for a second incident in the same
# day and still cannot dent a mail quota. Anything beyond this is a loop, and a
# loop must be capped rather than delivered.
MAX_ALERTS_PER_DAY = 3

_RESEND_URL = "https://api.resend.com/emails"


class OpsAlertNotSent(RuntimeError):
    """The alert could not be sent. Never raised at the caller — logged."""


def _email_undeliverable_reason() -> str | None:
    """Why email could never deliver, or None if that channel is usable."""
    s = get_settings()
    if not s.platform_admin_emails_list:
        return "PLATFORM_ADMIN_EMAILS is empty"
    if not (s.OPS_ALERT_FROM or "").strip():
        return "OPS_ALERT_FROM is unset"
    if not (s.RESEND_API_KEY or "").strip():
        return "RESEND_API_KEY is unset"
    return None


def undeliverable_reason() -> str | None:
    """Why no alert could ever be delivered, or None if ANY channel is usable.

    Callers that retry need this, because "this attempt failed" and "no attempt
    can succeed" deserve opposite responses. A provider that rejected one
    message may accept the next; a missing sender address will reject every
    message until a human edits `.env`, and retrying that on a timer produces
    identical log lines forever while a customer-impact mark sits frozen behind
    it. Checked before any network call, so asking is free.

    With two transports the question is about the pair, not either one: while
    Telegram can still deliver, a mail account nobody configured is not a
    reason to give up on the alert. The reason names **both** halves when it
    does give up, because the operator fixing this needs to know what is
    missing on each side rather than one name at a time.
    """
    email = _email_undeliverable_reason()
    telegram = telegram_notify.undeliverable_reason()
    if email is None or telegram is None:
        return None
    return f"email: {email}; telegram: {telegram}"


async def send_operator_alert(subject: str, body: str) -> bool:
    """Tell the platform operators, by every channel there is.

    Returns True if **either** transport accepted it. Both are attempted on
    every alert rather than one standing in for the other: the failure this
    exists to prevent is silence, and a channel that is only tried when the
    first one *reports* failure is no help when the first one fails by
    reporting success it did not achieve.

    Never raises: this is called from a background worker whose real job is to
    keep watching. A watchdog that dies because it could not send mail stops
    being a watchdog, and the state it measured is still on /api/v1/health.
    """
    # One switch for one message. `EMAIL_SIMULATED` used to gate only the mail
    # half, so a developer machine holding a real bot token posted to the
    # owner's actual chat on every alert while the log said "SIMULATED". An
    # operator alert is a single notification that happens to travel two ways;
    # simulating half of it is a lie about the other half.
    if get_settings().EMAIL_SIMULATED:
        log.info("Operator alert SIMULATED subject=%r body=%s", subject, body)
        return True

    # Each half in its own guard. Both are written never to raise, but the one
    # thing this function must not do is let a fault in the first transport
    # stop the second from being tried — that is precisely the single point of
    # silence the second transport was added to remove. It would also abort the
    # caller's tick before it commits, which is how a watchdog stops watching.
    by_email = await _guarded(_send_email(subject, body), "email", subject)
    by_telegram = await _guarded(
        telegram_notify.send_operator_telegram(subject, body), "telegram", subject
    )

    if not (by_email or by_telegram):
        log.error(
            "Operator alert reached NOBODY (email and Telegram both failed) — "
            "subject=%r. Body was: %s",
            subject, body,
        )
    elif not (by_email and by_telegram):
        # Worth a line: one channel carrying every alert is the state this
        # module was rebuilt to get out of, and it degrades silently.
        log.warning(
            "Operator alert went out on one channel only (email=%s telegram=%s) "
            "— subject=%r",
            by_email, by_telegram, subject,
        )
    return by_email or by_telegram


async def _guarded(coro, channel: str, subject: str) -> bool:
    """Await one transport, turning any escape into a False."""
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 — the watcher outlives its transports
        log.error(
            "Operator alert transport %s raised (%s: %s) — subject=%r",
            channel, type(exc).__name__, exc, subject,
        )
        return False


async def _send_email(subject: str, body: str) -> bool:
    """The mail half. True only if the provider accepted it.

    Same grounds as the module docstring: the body is a status word and a
    remedy addressed to PLATFORM_ADMIN_EMAILS, never a content piece and never
    an audience.
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
