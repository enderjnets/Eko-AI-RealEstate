"""The bot token must not reach the log — v0.67.11.

This is a fix for a leak of mine. `httpx` logs the full request URL at INFO, and
Telegram carries the bot token in the path, so the doorbell of v0.67.10 wrote the
live credential into `docker logs eko-realestate-backend` the first time it
succeeded (2026-09-03 07:04:34 UTC) and from there into a chat transcript.

The subtle part, and the reason test 1 is written the way it is: `httpx` does
**not** interpolate the URL into the format string. It calls

    logger.info('HTTP Request: %s %s "%s %d %s"', method, url, ...)

so the token lives in `record.args`, not in `record.msg`. A filter that
inspected `record.msg` would find no token, pass the record through untouched,
and keep leaking — while a test that emitted a pre-formatted string went green.
So the test emits with real args, exactly as the library does.
"""
from __future__ import annotations

import logging
import pathlib
import subprocess
import sys

from app.logging_redact import RedactSecrets, install

# A token-shaped string that is not a real credential: the digits and the body
# match Telegram's shape (<digits>:<35 chars>) so the pattern has something
# honest to bite, and nothing here has ever been valid.
_FAKE_TOKEN = "123456789:AAFxyzTESTtokenNOTrealAAAAAAAAAAAAA"
_TELEGRAM_URL = f"https://api.telegram.org/bot{_FAKE_TOKEN}/sendMessage"


def test_the_token_never_reaches_the_log(caplog) -> None:
    """The exact line httpx emits comes out redacted."""
    log = logging.getLogger("httpx")
    install()
    with caplog.at_level(logging.INFO, logger="httpx"):
        log.info(
            'HTTP Request: %s %s "%s %d %s"',
            "POST",
            _TELEGRAM_URL,
            "HTTP/1.1",
            200,
            "OK",
        )

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert _FAKE_TOKEN not in rendered
    assert "123456789:AAF" not in rendered
    assert "/bot<redacted>/sendMessage" in rendered
    # It redacts, it does not silence: the status line still has to be there,
    # because that is how we know the notice went out at all.
    assert "200" in rendered and "HTTP Request" in rendered


def test_a_logger_nobody_named_is_covered_too(caplog) -> None:
    """The root-handler half of `install()`, which had no test at all.

    The audit measured it: deleting the loop over the root handlers and keeping
    only the named loggers left the whole suite green, while `httpcore`,
    `urllib3` and our own modules went back to leaking. That half is not
    redundancy — it is the ONLY thing covering every logger we did not think to
    name, which is exactly the set that matters. So this asserts on the OUTPUT
    of a logger that is deliberately not in `_LOGGERS`.
    """
    install()
    log = logging.getLogger("httpcore.http11")
    assert not any(isinstance(f, RedactSecrets) for f in log.filters), (
        "this test is pointless unless the logger is unnamed; pick another"
    )
    with caplog.at_level(logging.INFO, logger="httpcore.http11"):
        logging.getLogger().handle(
            logging.LogRecord(
                name="httpcore.http11",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="send_request_headers.started request=<Request %s>",
                args=(_TELEGRAM_URL,),
                exc_info=None,
            )
        )

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert rendered, "the record never reached a handler; the test proves nothing"
    assert _FAKE_TOKEN not in rendered
    assert "/bot<redacted>/" in rendered


def test_a_credential_in_the_query_string_is_redacted(caplog) -> None:
    """Telegram was not the only one — this leak was live in production.

    `services/discovery.py:295` sends `SERPAPI_API_KEY` as an `api_key` query
    parameter, with the key set and `DISCOVERY_SIMULATED=false`, so httpx was
    writing it into the container log on every search. Matched by parameter
    NAME, because a secret has no shape.
    """
    log = logging.getLogger("httpx")
    install()
    url = "https://serpapi.com/search?engine=google&q=realtor&api_key=SERPAPI-secret-abc123"
    with caplog.at_level(logging.INFO, logger="httpx"):
        log.info('HTTP Request: %s %s "%s %d %s"', "GET", url, "HTTP/1.1", 200, "OK")

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "SERPAPI-secret-abc123" not in rendered
    assert "api_key=<redacted>" in rendered
    # The parameters around it are not secrets and must survive: the point of a
    # log line is still to say which request was made.
    assert "engine=google" in rendered and "q=realtor" in rendered


def test_a_line_without_a_token_is_untouched(caplog) -> None:
    """The filter must not mangle every other request we make."""
    log = logging.getLogger("httpx")
    install()
    url = "https://api.resend.com/emails"
    with caplog.at_level(logging.INFO, logger="httpx"):
        log.info('HTTP Request: %s %s "%s %d %s"', "POST", url, "HTTP/1.1", 200, "OK")

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert url in rendered
    assert "<redacted>" not in rendered


def test_importing_the_app_installs_the_filter() -> None:
    """A module nobody wires in is a module that protects nothing.

    In a **fresh interpreter**, and that is the whole point. Written as a plain
    `import app.main` in this process the test could not fail: the tests above
    call `install()` themselves, so the filter is already on the `httpx` logger
    by the time this one runs and the assertion passes whether or not `main.py`
    does anything. Commenting out the call in `main.py` left it green — measured,
    which is why it now runs somewhere that has no history.
    """
    probe = (
        "import logging, app.main;"
        "from app.logging_redact import RedactSecrets;"
        "print(any(isinstance(f, RedactSecrets)"
        ' for f in logging.getLogger("httpx").filters))'
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=str(pathlib.Path(__file__).resolve().parent.parent),
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1] == "True", done.stdout


def test_installing_twice_does_not_stack_filters() -> None:
    """`app.main` is imported more than once across a test session."""
    log = logging.getLogger("httpx")
    install()
    install()
    install()
    copies = [f for f in log.filters if isinstance(f, RedactSecrets)]
    assert len(copies) == 1


def test_a_broken_format_string_does_not_break_the_filter() -> None:
    """A record we cannot render must pass through, not raise.

    The filter runs inside `Logger.handle`, so an exception here would surface
    at whatever line did the logging — turning somebody else's bad format string
    into a crash in an unrelated code path.

    It is asserted against the filter directly and not through `caplog`, because
    a broken record blows up later anyway in pytest's own formatter: routing it
    through the fixture would test the standard library's error handling, not
    ours. The record passes through unredacted, which is the honest outcome —
    we could not read it, so we cannot claim it is clean.
    """
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="broken %s %s",
        args=("only-one",),
        exc_info=None,
    )
    assert RedactSecrets().filter(record) is True
