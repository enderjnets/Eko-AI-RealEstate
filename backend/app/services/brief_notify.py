"""Telling the operator that a partner answered their brief.

The brief exists so that Natalia and Robbie stop having to write emails. If
reading their answers then required *us* to remember to open a page, the work
would simply have moved from one end of the conversation to the other. So the
save pushes: the answers arrive as mail, formatted for reading, and the panel
is where you go when you want the history rather than the news.

── Why this is not `ops_alert` ─────────────────────────────────────────────
`ops_alert` is for machinery that broke. It fires on a change of state and is
capped at three sends a UTC day, which is correct for an alarm and exactly
wrong for this: a partner answering is a business event, it is not a change of
health, and the day Natalia goes through the brief in four sittings the fourth
one would be swallowed by a circuit breaker meant to stop an alert loop.

── Why it is not `lead_notify` either ──────────────────────────────────────
That module addresses the agency about a person who contacted them, and its
whole shape — the booking mailbox, the panel link to a lead, the internal
thread record — is about a lead. A brief has no lead and never will.

── Why it may send without an opt-out check ────────────────────────────────
It is addressed to `OWNER_NOTICE_EMAIL`, the operator of the install, about
work they asked for. There is no marketing here and no recipient who could
have opted out: the person being written to is the one who built the page.
`tests/test_opt_out_is_absolute.py` names this function for that reason — see
the entry beside it, and add nothing here that sends anywhere else.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings
from app.db.base import get_bypass_session_factory
from app.models.partner_brief import PartnerBrief
from app.services.email import send_email

log = logging.getLogger(__name__)

#: How much of the answers to put in the mail before pointing at the page.
#: Long enough for a full nine-name pass with notes, short enough that a
#: pasted essay does not become a mail nobody scrolls.
MAX_BODY_CHARS = 8_000


def _render(value: Any, indent: int = 0, legend: dict[str, str] | None = None) -> list[str]:
    """Answers as indented lines, whatever shape that brief chose to collect.

    Shape-agnostic on purpose: the endpoint stores whatever the page sends
    (see `models/partner_brief`), so a renderer that expected a schema would
    start silently omitting the fields of the next brief we write. Unknown
    structure prints as itself rather than being dropped.
    """
    pad = "  " * indent
    names = legend or {}
    lines: list[str] = []
    if isinstance(value, dict):
        for key, inner in value.items():
            label = names.get(key, key)
            # A person's row is `{state, correct, naming}` — three keys that
            # read far better on one line than as a nested block, and `naming`
            # is UI state that means nothing to a reader.
            if isinstance(inner, dict) and ("state" in inner or "correct" in inner):
                verdict = _STATES.get(str(inner.get("state") or "send"), str(inner.get("state")))
                line = f"{pad}{label} — {verdict}"
                if inner.get("correct"):
                    line += f'  [calls them "{inner["correct"]}"]'
                lines.append(line)
            elif isinstance(inner, (dict, list)) and inner:
                lines.append(f"{pad}{label}:")
                lines.extend(_render(inner, indent + 1, names))
            else:
                lines.append(f"{pad}{label}: {_scalar(inner)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                lines.extend(_render(item, indent, names))
            else:
                lines.append(f"{pad}- {_scalar(item)}")
    else:
        lines.append(f"{pad}{_scalar(value)}")
    return lines


def _scalar(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


#: How a person's verdict reads in the mail. The page stores the machine's
#: word; nobody should have to know what "touch" meant.
_STATES = {
    "out": "LEAVE OUT",
    "touch": "already in touch — theirs to handle",
    "send": "send",
}


def _legend(payload: dict) -> dict[str, str]:
    """Every id in the answers, mapped to what a human calls it.

    The answers are keyed by id, because ids are what stays stable when a
    brief is edited. That is right for the row and useless in an email: the
    first notice this ever sent read `nine: p1: state: out`, which is not an
    answer, it is a lookup exercise. The brief's own payload already holds
    every name and label, so the mail reads it as a legend rather than making
    the reader be one.
    """
    out: dict[str, str] = {}
    for block in payload.get("blocks") or []:
        for person in block.get("people") or []:
            if person.get("id"):
                out[person["id"]] = person.get("name") or person["id"]
        for field in block.get("fields") or []:
            if field.get("id"):
                out[field["id"]] = field.get("label") or field["id"]
        if block.get("kind") == "people" and block.get("id"):
            out[block["id"]] = block.get("heading") or block["id"]
        if block.get("kind") == "letter" and block.get("id"):
            out[f"{block['id']}.state"] = block.get("heading") or block["id"]
    return out


def build_body(brief: PartnerBrief) -> str:
    """The mail's text. Pure, so the test can read it without sending."""
    lines = [
        f"{brief.recipient or 'Someone'} answered: {brief.title}",
        "",
    ]
    rendered = _render(brief.answers or {}, legend=_legend(brief.payload or {}))
    if rendered:
        lines.extend(rendered)
    else:
        # A save with nothing in it is a real event — they opened it, went
        # through it and had no changes — and saying so is more useful than an
        # empty mail that reads like a bug.
        lines.append("(they saved without changing anything)")

    body = "\n".join(lines)
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n\n… truncated. The full answers are on the brief."

    base = (get_settings().PANEL_URL or "").strip().rstrip("/")
    if base:
        body += f"\n\n—\nThe brief: {base}/brief/{brief.token}"
    return body


async def send_brief_answered_notice(brief_id: int) -> bool:
    """Mail the operator. Never raises — a save must not depend on the post.

    Read on the bypass session because the caller has already committed and
    this runs after the request's org binding has done its job; the lookup is
    by primary key and touches one row.
    """
    settings = get_settings()
    to = (settings.OWNER_NOTICE_EMAIL or "").strip()
    if not to:
        # Not an error. A fresh install has no operator address configured, and
        # the brief still works perfectly without one — the answers are in the
        # row. Logged at info so it is findable, not at warning so it does not
        # look like something is broken.
        log.info("Brief %d answered; no OWNER_NOTICE_EMAIL set, so nobody was mailed", brief_id)
        return False

    try:
        async with get_bypass_session_factory()() as meta:
            brief = await meta.get(PartnerBrief, brief_id)
            if brief is None:
                log.error("Brief %d answered but the row is gone", brief_id)
                return False
            subject = f"Brief answered — {brief.title}"
            body = build_body(brief)
    except Exception as exc:  # noqa: BLE001
        log.error("Brief %d: could not read the answers to send them: %s", brief_id, exc)
        return False

    try:
        result = await send_email(to=to, subject=subject, body_text=body)
        if (result or {}).get("id"):
            log.info("Brief %d: answers sent to the operator", brief_id)
            return True
        log.error("Brief %d: the provider accepted the notice and returned no id", brief_id)
        return False
    except Exception as exc:  # noqa: BLE001 — the answers are already durable
        log.error("Brief %d: the notice failed to send: %s", brief_id, exc)
        return False
