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


async def notify_video_ready(piece_id: int, waiting: int) -> bool:
    """Say a video is ready to approve. True only if it actually went out.

    Never raises. It is called on the path that delivers a finished render, and
    losing a video because a notification failed would be a spectacular way to
    pay for a convenience.
    """
    blocked = undeliverable_reason()
    if blocked is not None:
        log.info("Telegram notice not sent (%s) — piece %s is ready", blocked, piece_id)
        return False

    s = get_settings()
    text = (
        f"🎬 A video is ready to approve (piece {piece_id}).\n"
        f"{waiting} waiting in the queue.\n"
        f"{console_url()}"
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                _api_url(s.TELEGRAM_BOT_TOKEN.strip()),
                json={
                    "chat_id": s.TELEGRAM_CHAT_ID.strip(),
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
    except httpx.HTTPError as exc:
        log.warning("Telegram notice failed for piece %s: %s", piece_id, exc)
        return False

    if resp.status_code >= 400:
        # Telegram answers 200 with `ok: false` for some refusals and a 4xx for
        # others; both are failures and neither should be read as delivery.
        log.warning(
            "Telegram refused the notice for piece %s (%s): %.200s",
            piece_id, resp.status_code, resp.text,
        )
        return False
    return True
