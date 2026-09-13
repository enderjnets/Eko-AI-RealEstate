"""Telling us how a brief is going, so nobody has to ask.

The owner's words for why this exists, and they are the design brief: *"no es
espiar, es para no estar preguntando cómo van"*. That sentence draws the line
this module has to hold.

**It reports state, never a stream.** Three things get sent: somebody opened
it, the state of play at a checkpoint, and somebody finished. What is
deliberately NOT sent is a live feed — no keystrokes, no "they are looking at
person 4", no notice every time a field changes. That restraint is not only
manners: a drip of twelve messages does not tell you how they are doing, it
tells you to stop reading Telegram.

**The same lesson the email already paid for.** The notice used to fire on
every save, and the page autosaves a second after the last keystroke: ninety
seconds of typing produced eight emails. Progress here is coalesced on the same
principle — see `BRIEF_ACTIVITY_QUIET`.

**Nothing anybody typed appears here.** The counts say *how much*, never
*what*. The answers themselves go by email, which is a place you read on
purpose, rather than a phone alert that quotes a client's name on a lock
screen. Telegram is the doorbell; the email is the letter.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.partner_brief import PartnerBrief
from app.services.telegram_notify import send_operator_telegram

log = logging.getLogger(__name__)

#: How long the brief must have been quiet before another progress ping is
#: worth sending. Long enough that one sitting produces one or two, short
#: enough that "they picked it up again after dinner" still reaches us.
BRIEF_ACTIVITY_QUIET = timedelta(minutes=20)


def summarise(brief: PartnerBrief) -> str:
    """How far along they are, in counts. Never in their words.

    Reads the payload as the list of what was asked and the answers as what
    came back, so a brief with different questions next month summarises
    itself without this function being edited.
    """
    payload: dict[str, Any] = brief.payload or {}
    answers: dict[str, Any] = brief.answers or {}
    lines: list[str] = []

    asked = 0
    given = 0
    for block in payload.get("blocks") or []:
        # The nine, or whatever list this brief carries.
        if block.get("kind") == "people" and block.get("id"):
            rows = answers.get(block["id"]) or {}
            people = block.get("people") or []
            out = sum(1 for r in rows.values() if isinstance(r, dict) and r.get("state") == "out")
            touch = sum(
                1 for r in rows.values() if isinstance(r, dict) and r.get("state") == "touch"
            )
            fixed = sum(
                1 for r in rows.values() if isinstance(r, dict) and (r.get("correct") or "").strip()
            )
            send = len(people) - out - touch
            piece = f"· {block.get('heading') or 'the list'}: {send} to write to"
            if out:
                piece += f", {out} left out"
            if touch:
                piece += f", {touch} already in touch"
            if fixed:
                piece += f", {fixed} name{'s' if fixed > 1 else ''} corrected"
            lines.append(piece)

        # Robbie's side of it: a choice, not a list.
        if block.get("kind") == "letter" and block.get("id"):
            chosen = answers.get(f"{block['id']}.state")
            asked += 1
            if chosen:
                given += 1
                said = "sent it" if chosen == "sent" else "wants to change something"
                lines.append(f"· the broker email: {said}")

        # Everything typed, counted and never quoted.
        for field in block.get("fields") or []:
            asked += 1
            if str(answers.get(field.get("id"), "") or "").strip():
                given += 1

    head = f"{given} of {asked} questions answered" if asked else "nothing asked"
    return "\n".join([head, *lines])


async def _say(subject: str, body: str, brief_id: int) -> bool:
    """Send, and never let a failed doorbell cost anything upstream."""
    try:
        return bool(await send_operator_telegram(subject, body))
    except Exception as exc:  # noqa: BLE001 — a notice may never break a save
        log.error("Brief %d: telegram notice failed: %s", brief_id, exc)
        return False


async def notify_opened(brief: PartnerBrief) -> bool:
    """They opened it. Sent once ever, because that is when it is news."""
    return await _say(
        "Brief opened",
        f"{brief.recipient or 'Somebody'} opened “{brief.title}”.",
        brief.id,
    )


async def notify_progress(brief: PartnerBrief) -> bool:
    """Where they have got to. Only ever at a checkpoint — see the module docs."""
    return await _say(
        "Brief in progress",
        f"{brief.recipient or 'Somebody'} is working through “{brief.title}”.\n\n"
        f"{summarise(brief)}\n\n"
        "They have not pressed “Send answers” yet.",
        brief.id,
    )


async def notify_finished(brief: PartnerBrief) -> bool:
    """They pressed the button. The one message worth interrupting somebody for."""
    return await _say(
        "Brief finished",
        f"{brief.recipient or 'Somebody'} finished “{brief.title}”.\n\n"
        f"{summarise(brief)}\n\n"
        "The answers themselves are in your email.",
        brief.id,
    )


def should_ping_progress(previous: datetime | None) -> bool:
    """Whether this save is far enough from the last to be worth a ping.

    The caller owns the comparison and this module only sends — the same
    division `ops_alert` documents, and for the same reason: a level-triggered
    notice on a page that autosaves every second and a half is a flood.
    """
    if previous is None:
        return True
    return datetime.now(UTC) - previous >= BRIEF_ACTIVITY_QUIET
