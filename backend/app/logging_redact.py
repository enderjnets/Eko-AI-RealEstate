"""Keep secrets that travel inside a URL out of the log.

`httpx` logs the full request URL at INFO for every call it makes, and
Telegram's API carries the bot token in the *path* (`/bot<token>/sendMessage`).
So the doorbell of v0.67.10 wrote the live token into
`docker logs eko-realestate-backend` on its very first successful send. Measured,
not feared: the line was there at 2026-09-03 07:04:34 UTC.

This is the only sender in the product that puts a credential in a URL — Resend,
Buffer, Cal.com and VAPI all authenticate with headers — but the filter is
written as a list of patterns rather than one hard-coded regex, because the next
one will arrive the same way: quietly, through somebody else's logger.

Telegram was not the only one, and the first draft of this file said it was —
the audit measured `services/discovery.py:295` putting `SERPAPI_API_KEY` in a
**query string**, with `DISCOVERY_SIMULATED=false` and the key set in
production. So the second pattern is not defensive programming for a hypothesis:
it closes a leak that was live. The lesson is written here rather than learned
twice — a credential reaches a URL either in the path or in the query, and both
shapes are covered.

**It redacts, it does not silence.** `HTTP Request: POST ... "HTTP/1.1 200 OK"`
is how we know the notice went out at all; dropping the record to protect the
token would trade one blindness for another.

**What it cannot see, said out loud:** a traceback. `getMessage()` renders
`msg % args` and nothing else; `record.exc_info` is turned into text by the
*Formatter*, which runs after every filter. `httpx.HTTPStatusError` puts the
full URL in its message, so a `raise_for_status()` added to any caller that
sends a credential in the URL — `telegram_notify` is wrapped by a
`log.exception` at `api/v1/render_jobs.py:456` — would leak again with this
filter installed and nothing going red. Do not add one without solving that
first.
"""

from __future__ import annotations

import logging
import re

# Telegram: https://api.telegram.org/bot<digits>:<secret>/sendMessage
_TELEGRAM_BOT_TOKEN = re.compile(r"/bot\d+:[A-Za-z0-9_-]+")

# A credential passed as a query parameter — SerpApi's `api_key` today, and
# Meta's `hub.verify_token` on the way in. Matched by PARAMETER NAME rather than
# by the shape of the value, because a secret has no shape: `api_key=1` is as
# secret as forty hex characters. The name list is the narrow part, so an
# ordinary `?q=` or `?engine=` is never touched.
_SECRET_QUERY_PARAM = re.compile(
    r"([?&](?:api_key|apikey|access_token|auth_token|hub\.verify_token"
    r"|client_secret|secret|password|passwd|signature)=)[^&\s\"']+",
    re.IGNORECASE,
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_TELEGRAM_BOT_TOKEN, "/bot<redacted>"),
    (_SECRET_QUERY_PARAM, r"\1<redacted>"),
)


def redact(text: str) -> str:
    """Return `text` with every known secret shape replaced."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactSecrets(logging.Filter):
    """Rewrite a record in place when its rendered message carries a secret.

    The rendering matters: `httpx` does not interpolate the URL into the format
    string, it passes it in `record.args`. A filter that only looked at
    `record.msg` would find `'HTTP Request: %s %s "%s %d %s"'`, see nothing to
    redact, pass the record through, and leave the token in the log — while a
    test written against a pre-formatted string went green. So we go through
    `getMessage()`, and on a hit we replace `msg` with the rendered text and drop
    `args`, because the placeholders are gone once it is rendered.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:  # a broken format string is not ours to fix here
            return True
        clean = redact(rendered)
        if clean != rendered:
            record.msg = clean
            record.args = ()
        return True


#: Loggers that get the filter by name. `httpx` writes our outbound URLs.
#: uvicorn's two are here because `uvicorn.config.LOGGING_CONFIG` gives them
#: their own handlers with `propagate: false` — they never reach a root handler,
#: so the root sweep below cannot see them, and `uvicorn.access` logs the full
#: request line of every INBOUND request, query string included.
_LOGGERS = ("httpx", "uvicorn", "uvicorn.access", "uvicorn.error")


def install(*, logger_names: tuple[str, ...] = _LOGGERS) -> None:
    """Install the filter on the named loggers and on every root handler.

    Both, and the redundancy is deliberate: a filter attached to a *logger* is
    only consulted for records emitted through that logger, never for records
    that propagated up from its children, whereas a filter on the root
    *handler* sees everything that is actually written. The named loggers cover
    the case where a handler is added later; the root handlers cover the child
    loggers we have not thought of.

    Idempotent — importing `app.main` twice in a test session must not stack
    two copies of the filter on the same logger.
    """
    for name in logger_names:
        _add_once(logging.getLogger(name))
    for handler in logging.getLogger().handlers:
        _add_once(handler)


def _add_once(target: logging.Logger | logging.Handler) -> None:
    if any(isinstance(f, RedactSecrets) for f in target.filters):
        return
    target.addFilter(RedactSecrets())
