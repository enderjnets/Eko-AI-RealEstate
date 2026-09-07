"""Telling the owner about mail that was refused before it could become a lead.

The MX of a brand domain sits on the ROOT, so the product receives everything
addressed to it. Exactly one mailbox is mapped — `hello@` — and
`webhook_org_or_refuse` now closes the rest of that domain rather than letting
the single-tenant fallback file a typo, a scrape or an `admin@` probe as a lead.

Refusing is only half the decision. The other half is what the owner asked for
in the same breath: *out of the Inbox, but I still see it*. So every refusal
becomes one line in the log and one nudge on the owner's own phone.

Three constraints shape everything below, and each of them comes from a
property of this exact call site rather than from taste:

* **It cannot use `ops_alert`.** That module's budget is three alerts a UTC day
  *across every subject*, and it is what the LLM safety-net monitor and the
  Fair Housing watch spend to reach a human. Anyone who knows the domain can
  send mail to it; borrowing that budget would let a stranger silence the
  alarms that watch the product. Own budget, own counter.
* **It cannot use `send_email`.** This fires from the webhook *before*
  `set_org_id` has run — that is the whole point, there is no org — and
  `send_email` resolves the acting agency's identity to pick a sender. There is
  nothing to resolve. Telegram needs no identity and is already the owner's own
  chat.
* **It must not repeat itself.** One sender who retries, or one loop somewhere
  else, would otherwise be an unbounded stream of notifications. Deduplicated
  per sender per UTC day, and capped besides.

The state is in the process, and that is the right size for it: this deployment
runs a single uvicorn worker with no `--workers` (see CLAUDE.md, which makes
that a hard precondition for the tenant cache too), and a restart forgetting
that it already mentioned `bounce@x.test` costs one extra message. What a
restart does NOT lose is the `log.error` line, which is written every single
time and is the durable record.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

log = logging.getLogger(__name__)

# A day's worth of nudges about mail nobody has to act on. Higher than
# `ops_alert`'s three because these are informational and cheap, low enough that
# a stranger with the domain cannot turn the owner's phone into an alarm.
MAX_NOTICES_PER_DAY = 12

# Trimmed hard. A subject line is written by whoever sent the mail, so it is
# untrusted text being forwarded to a person: it goes in for recognition, not
# for reading, and it never carries the body — which at this point in the
# webhook has deliberately not even been fetched.
MAX_SUBJECT = 120

# The dedup set is attacker-fed — one entry per distinct sender seen today — so
# it is capped. Past the cap it simply stops growing: the budget below is spent
# long before, so the only thing lost is the ability to recognise a repeat, and
# nobody is being notified at that point anyway.
MAX_SENDERS_REMEMBERED = 2000

_day: str | None = None
_seen: set[str] = set()
_sent = 0
_refused = 0


def reset_state() -> None:
    """Forget today's dedup and budget. For tests, and for nothing else."""
    global _day, _seen, _sent, _refused
    _day = None
    _seen = set()
    _sent = 0
    _refused = 0


def _roll_the_day(today: str) -> None:
    global _day, _seen, _sent, _refused
    if _day != today:
        _day = today
        _seen = set()
        _sent = 0
        _refused = 0


def _verdict(sender: str) -> tuple[bool, bool]:
    """`(speak, is_the_last_one)` for this refusal, booking it either way.

    The second flag is what stops the budget from being a way to SILENCE the
    owner. Dedup is per sender and the ceiling is a dozen, so twelve messages
    from twelve throwaway addresses would otherwise buy a whole day in which
    every genuine refusal reaches the log and nothing reaches his phone. The
    message that spends the last of the budget says so, and says how many were
    refused — one more notification, and then quiet.
    """
    global _sent, _refused
    _roll_the_day(datetime.now(UTC).strftime("%Y-%m-%d"))
    _refused += 1
    key = (sender or "").strip().lower() or "(no sender)"
    if key in _seen:
        return False, False
    # Booked BEFORE the send, and booked even when the send then fails. The
    # counter is a rate limit, not a delivery receipt: a transport that is
    # failing must not become a way to keep asking it.
    if len(_seen) < MAX_SENDERS_REMEMBERED:
        _seen.add(key)
    if _sent >= MAX_NOTICES_PER_DAY:
        return False, False
    _sent += 1
    return True, _sent == MAX_NOTICES_PER_DAY


async def tell_the_owner_about_unrouted(
    *,
    sender: str | None,
    mailboxes: list[str] | None,
    subject: str | None,
    reason: str,
) -> bool:
    """One nudge about one refused message. Never raises, never blocks a 200.

    Returns True only when Telegram accepted it, which is information for the
    caller's tests and for nobody else: the webhook ignores it on purpose, since
    a notification that failed must not cost the provider its 200.
    """
    to = ", ".join(sorted({(m or "").strip().lower() for m in (mailboxes or []) if m}))
    frm = (sender or "").strip() or "(unknown)"
    # Always, before any budget: this is the record that survives a restart.
    # Every field that came from the message is %r-escaped, not just the
    # subject. `_sender` falls back to the RAW `from` string when it parses no
    # address, and a JSON string may contain a newline: interpolated with %s it
    # writes a second, fabricated log line — in the one file an operator reads
    # to find out what was refused.
    log.error(
        "inbound email refused — from=%r to=%r subject=%r reason=%s",
        frm, to or "(none)", (subject or "")[:MAX_SUBJECT], reason,
    )

    speak, last = _verdict(frm)
    if not speak:
        return False

    from app.services.telegram_notify import send_operator_telegram, undeliverable_reason

    blocked = undeliverable_reason()
    if blocked:
        log.info("unrouted-mail notice not sent (%s)", blocked)
        return False
    try:
        return bool(
            await send_operator_telegram(
                "Mail to Denver Home Story that did NOT become a lead",
                f"From: {frm}\n"
                f"To: {to or '(none)'}\n"
                f"Subject: {(subject or '(none)')[:MAX_SUBJECT]}\n\n"
                f"{reason}\n\n"
                "Nothing was written and nobody was answered. If this address "
                "should receive, map it in channel_routes."
                + (
                    f"\n\nThat is the last of today's {MAX_NOTICES_PER_DAY} "
                    f"notices ({_refused} refused so far today). Anything else "
                    "refused before midnight UTC will only be in the log."
                    if last
                    else ""
                ),
            )
        )
    except Exception as exc:  # noqa: BLE001 — a nudge may never cost the webhook
        log.error("unrouted-mail notice failed to send: %s", exc)
        return False
