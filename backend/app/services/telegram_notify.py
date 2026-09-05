"""A doorbell for the approval queue.

The machine produces on its own and the human gate had no bell: four pieces
piled up waiting (3, 5, 6, 7) while everything depended on somebody remembering
to open the console. This sends one message when a video becomes approvable.

**It reuses the owner's existing bot rather than a new one — his decision, and
the trade is recorded here rather than lost.** That bot is administered by
another project. If its token is rotated, these notices go silent and the
symptom will be "the message never arrived", which is the worst kind of fault
because nothing looks broken. When that day comes, look here first.

Nothing about that bot is touched: this sends to Telegram's own API with the
bot's identity, so the other project's code, its unit and its behaviour are
exactly as they were — one more message appears in the chat, that is all.

**The body carries a link, never the script.** The sweep in
`test_content_gate_is_absolute.py` exempts the operator emailer on the written
grounds that its body is "a status word and a remedy, never a content piece",
and this holds to the same line. It is not squeamishness: a message containing
the hook invites approving from a phone without watching the video, and the
gate exists precisely so that somebody watches.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15.0


def _api_url(token: str) -> str:
    return f"https://api.telegram.org/bot{token}/sendMessage"


def undeliverable_reason() -> str | None:
    """Why no notice could ever arrive, or None if the channel is usable.

    Asked before any network call, so it is free. "This attempt failed" and "no
    attempt can succeed" deserve opposite answers: the first is worth another
    tick, the second produces identical log lines forever until a person edits
    `.env`.
    """
    s = get_settings()
    if not (s.TELEGRAM_BOT_TOKEN or "").strip():
        return "TELEGRAM_BOT_TOKEN is unset"
    if not (s.TELEGRAM_CHAT_ID or "").strip():
        return "TELEGRAM_CHAT_ID is unset"
    return None


def console_url() -> str:
    base = (get_settings().CONTENT_PUBLIC_BASE_URL or "").strip().rstrip("/")
    return f"{base}/content" if base else "/content"


# Telegram refuses anything longer than this, and a refused alert is a silent
# alert. The operator body carries a remedy in its first lines, so clipping the
# tail costs nothing that matters.
_MAX_CHARS = 3900


async def _post_to_telegram(text: str, *, what: str) -> bool:
    """The one function here that touches the wire. True only if it went out.

    Single on purpose: a second wire-touching path in this module would have to
    declare itself in `test_content_gate_is_absolute.py` too, which is the point
    of that sweep. Never raises — both callers are on paths (a finished render,
    a watchdog tick) where losing the work to a failed notification would be a
    spectacular way to pay for a convenience.
    """
    blocked = undeliverable_reason()
    if blocked is not None:
        log.info("Telegram notice not sent (%s) — %s", blocked, what)
        return False

    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                _api_url(s.TELEGRAM_BOT_TOKEN.strip()),
                json={
                    "chat_id": s.TELEGRAM_CHAT_ID.strip(),
                    "text": text[:_MAX_CHARS],
                    "disable_web_page_preview": True,
                },
            )
    except Exception as exc:  # noqa: BLE001 — the caller must outlive its transport
        log.warning("Telegram notice failed (%s): %s", what, exc)
        return False

    if resp.status_code >= 400:
        # Telegram answers 200 with `ok: false` for some refusals and a 4xx for
        # others; both are failures and neither should be read as delivery.
        log.warning(
            "Telegram refused the notice (%s) (%s): %.200s",
            what, resp.status_code, resp.text,
        )
        return False
    return True


async def notify_video_ready(piece_id: int, waiting: int) -> bool:
    """Say a video is ready to approve. True only if it actually went out."""
    text = (
        f"🎬 A video is ready to approve (piece {piece_id}).\n"
        f"{waiting} waiting in the queue.\n"
        f"{console_url()}"
    )
    return await _post_to_telegram(text, what=f"piece {piece_id} is ready")


async def send_operator_telegram(subject: str, body: str) -> bool:
    """An operator alert on the owner's own phone. True only if it went out.

    The second transport for `ops_alert.send_operator_alert`, and the reason it
    exists is measured rather than theoretical: on 5-sep-2026 the watchdog spent
    all three of its daily attempts on a flapping provider and `alerted_state`
    never advanced, so the outage that followed was never reported at all. One
    transport meant one point of silence.

    Same line as `notify_video_ready` on content: this carries a status word and
    a remedy, never a piece's hook, script or caption.
    """
    return await _post_to_telegram(f"⚠️ {subject}\n\n{body}", what="operator alert")
