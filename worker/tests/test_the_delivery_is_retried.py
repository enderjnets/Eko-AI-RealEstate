"""The upload is retried, because it is the step that throws money away.

Measured on 17-sep-2026 in the worker's own log on the render machine, not
supposed: 40 deliveries landed, 29 jobs failed for every reason, and **3** of
the failures broke at `panel.deliver` — `PUT /result`, the finished video going
up — all three with `[SSL: SSLV3_ALERT_BAD_RECORD_MAC]` raised from
`_receive_response_headers`. The body had already left the machine; it was the
answer that never arrived intact. Two of the three were fourteen minutes apart
on one afternoon (jobs 36 and 37, pieces 74 and 75); the third was on 7-sep.

By then the narration and the pictures are paid for, and `handle()` deletes
the workdir in its `finally` the moment `deliver` raises. So one corrupted TLS
record cost one paid render, and the retry the panel then granted paid the
narration again from scratch.

What is worth holding here:

* **The file is reread on every attempt.** httpx takes `Content-Length` from
  the file's SIZE, not from its position (`peek_filelike_length` on a drained
  handle still says the whole file — measured), so a handle the first attempt
  drained declares the whole video and sends nothing: a request that can never
  complete, and one that would be retried into three wasted attempts. The
  assert is on the BYTES each attempt sent, not on the count of attempts.
* **Transport errors and 5xx are retried; nothing under 500 is.** 400 is an
  empty body, 413 too large, 422 a video the panel refused and already marked
  failed, 409 a job nobody is waiting on. The same bytes again answer none of
  those.
* **After the attempts, the LAST exception comes out** — a transport error or
  an `HTTPStatusError`, whichever ended the run — so `handle()` keeps
  classifying it (`terminal=isinstance(exc, verify.Rejected)`) exactly as
  before: none of these is a `Rejected`. This change touches nothing above
  `deliver`.
* **A refusal after a failed attempt is said out loud.** The dropped response
  may have been a 200: the panel then holds the video and the job is done. Its
  refusal of the second upload comes BEFORE it reads the body, so from here it
  usually looks like a broken write, and occasionally like a 409; both cases
  get the same warning. A plain "failed" in the log for a video sitting in the
  approval queue sends somebody to render it again.
* **The backoff is real and it is between attempts**, not after the last one.
  A test that neutralises `sleep` and never asks what it was called with would
  pass an implementation with no backoff at all.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from worker import config, main

URL = "https://panel.test/api/v1/internal/render-jobs/result"
MAC = "[SSL: SSLV3_ALERT_BAD_RECORD_MAC] ssl/tls alert bad record mac (_ssl.c:2711)"


def _panel(monkeypatch: pytest.MonkeyPatch, put) -> main.Panel:
    cfg = config.Config(
        api_base="https://panel.test",
        token="t",
        name="rog-test",
        hours=frozenset(),
        workdir=Path("/tmp"),
        poll_seconds=60,
    )
    panel = main.Panel(cfg)
    monkeypatch.setattr(panel.http, "put", put)
    # The backoff is real in production and pointless in a test.
    monkeypatch.setattr(main.time, "sleep", lambda _s: None)
    return panel


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("PUT", URL))


class _Put:
    """A `put` that drains the body like the real one and answers from a script.

    Each entry is either an exception to raise AFTER reading the body — the
    measured failure is in reading the response, so the bytes had gone — or a
    status code to answer with.
    """

    def __init__(self, *script: int | Exception) -> None:
        self.script = list(script)
        self.received: list[bytes] = []

    def __call__(self, url: str, *, params: dict, content) -> httpx.Response:
        self.received.append(content.read())
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return _response(step)


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "short.mp4"
    path.write_bytes(b"\x00\x00\x00\x1cftypisom" + bytes(range(256)) * 40)
    return path


def test_a_dropped_response_is_retried_and_the_file_is_reread_each_time(
    monkeypatch: pytest.MonkeyPatch, video: Path
) -> None:
    """The discriminating assert: every attempt sent the WHOLE file.

    The obvious wrong implementation opens the file once above the loop; its
    second attempt sends whatever is left after the first read, which is
    nothing. That version passes a test that counts attempts and fails this
    one.
    """
    put = _Put(httpx.ReadError(MAC), httpx.ReadError(MAC), 200)
    panel = _panel(monkeypatch, put)

    panel.deliver(36, video)

    data = video.read_bytes()
    assert put.received == [data, data, data]


def test_after_the_last_attempt_the_error_comes_out_unwrapped(
    monkeypatch: pytest.MonkeyPatch, video: Path
) -> None:
    """`handle()` decides `terminal` from the exception type. It must still
    see a transport error — the last one — not a wrapper and not a silent
    return."""
    put = _Put(httpx.ReadError(MAC), httpx.ReadError(MAC), httpx.ReadError(MAC))
    panel = _panel(monkeypatch, put)

    with pytest.raises(httpx.ReadError):
        panel.deliver(36, video)
    assert len(put.received) == main.DELIVERY_ATTEMPTS


@pytest.mark.parametrize("status", [400, 409, 413, 422])
def test_a_refusal_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, video: Path, status: int
) -> None:
    """4xx means the panel READ the upload and said no. Sending the same bytes
    again cannot change its mind, and for 422 the job is already marked
    failed on the panel's side."""
    put = _Put(status, 200, 200)
    panel = _panel(monkeypatch, put)

    with pytest.raises(httpx.HTTPStatusError) as caught:
        panel.deliver(36, video)
    assert caught.value.response.status_code == status
    assert len(put.received) == 1


def test_a_gateway_error_is_retried(monkeypatch: pytest.MonkeyPatch, video: Path) -> None:
    """A 502 from Cloudflare while the VPS restarts is the same accident as a
    dropped record: nothing was read, nothing was decided."""
    put = _Put(502, 200)
    panel = _panel(monkeypatch, put)

    panel.deliver(36, video)

    assert len(put.received) == 2


def test_every_attempt_is_logged_with_its_number(
    monkeypatch: pytest.MonkeyPatch, video: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The retry does not fix the transport, it measures it. A week of these
    lines is the evidence for whether the link has to be chased."""
    put = _Put(httpx.ReadError(MAC), 200)
    panel = _panel(monkeypatch, put)

    with caplog.at_level(logging.WARNING, logger="worker"):
        panel.deliver(36, video)

    lines = [r.getMessage() for r in caplog.records]
    assert any("job 36" in line and "attempt 1/3" in line and "BAD_RECORD_MAC" in line for line in lines)


def test_a_409_after_a_failed_attempt_is_said_out_loud(
    monkeypatch: pytest.MonkeyPatch, video: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The one case a retry can misreport: the dropped answer was a 200, the
    panel has the video, and the second PUT meets a job that is done."""
    put = _Put(httpx.ReadError(MAC), 409)
    panel = _panel(monkeypatch, put)

    with (
        caplog.at_level(logging.WARNING, logger="worker"),
        pytest.raises(httpx.HTTPStatusError) as caught,
    ):
        panel.deliver(36, video)

    assert caught.value.response.status_code == 409
    lines = [r.getMessage() for r in caplog.records]
    assert any("no longer awaits" in line and "check the piece" in line for line in lines)


def test_a_409_on_the_first_attempt_is_an_ordinary_refusal(
    monkeypatch: pytest.MonkeyPatch, video: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Without a failed attempt before it there is nothing that may have
    landed; the warning would send somebody to look for a video that does
    not exist."""
    put = _Put(409)
    panel = _panel(monkeypatch, put)

    with (
        caplog.at_level(logging.WARNING, logger="worker"),
        pytest.raises(httpx.HTTPStatusError),
    ):
        panel.deliver(36, video)

    assert not any("no longer awaits" in r.getMessage() for r in caplog.records)


def test_the_delivery_gets_as_many_chances_as_the_render() -> None:
    """The panel gives a job MAX_ATTEMPTS = 3. A delivery with fewer would be
    the weakest link on the only path that costs money."""
    assert main.DELIVERY_ATTEMPTS == 3


def test_a_mixed_run_ends_with_whichever_error_came_last(
    monkeypatch: pytest.MonkeyPatch, video: Path
) -> None:
    """Transport, then a 502, then transport: the third is what comes out.

    Not the first — the audit caught the docstring claiming "original" while
    the code reassigned `last` on every turn. The type still decides nothing
    in `handle()`, because neither is a `verify.Rejected`; what matters is
    that the log and the exception agree about how the run ENDED.
    """
    put = _Put(httpx.ReadError(MAC), 502, httpx.WriteError("broken pipe"))
    panel = _panel(monkeypatch, put)

    with pytest.raises(httpx.WriteError):
        panel.deliver(36, video)
    assert len(put.received) == 3


def test_three_gateway_errors_end_with_the_gateway_error(
    monkeypatch: pytest.MonkeyPatch, video: Path
) -> None:
    put = _Put(502, 503, 502)
    panel = _panel(monkeypatch, put)

    with pytest.raises(httpx.HTTPStatusError) as caught:
        panel.deliver(36, video)
    assert caught.value.response.status_code == 502
    assert len(put.received) == 3


def test_the_backoff_sits_between_attempts_and_not_after_the_last(
    monkeypatch: pytest.MonkeyPatch, video: Path
) -> None:
    """Two failures before the success: two waits. Three failures: still two
    — waiting after the last attempt would delay the failure report for
    nothing, and a job is marked failed only when `handle()` hears about it."""
    slept: list[float] = []
    put = _Put(httpx.ReadError(MAC), httpx.ReadError(MAC), 200)
    panel = _panel(monkeypatch, put)
    monkeypatch.setattr(main.time, "sleep", slept.append)

    panel.deliver(36, video)
    assert slept == [main.DELIVERY_BACKOFF_SECONDS, main.DELIVERY_BACKOFF_SECONDS]

    slept.clear()
    put = _Put(httpx.ReadError(MAC), httpx.ReadError(MAC), httpx.ReadError(MAC))
    panel = _panel(monkeypatch, put)
    monkeypatch.setattr(main.time, "sleep", slept.append)

    with pytest.raises(httpx.ReadError):
        panel.deliver(36, video)
    assert slept == [main.DELIVERY_BACKOFF_SECONDS, main.DELIVERY_BACKOFF_SECONDS]
    assert main.DELIVERY_BACKOFF_SECONDS > 0


def test_a_broken_write_after_a_failed_attempt_is_said_out_loud(
    monkeypatch: pytest.MonkeyPatch, video: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The realistic shape of "the panel already has it": the panel refuses a
    finished job BEFORE reading the body, so the second upload dies as a
    broken write, not as a 409. That is the case the warning exists for."""
    put = _Put(httpx.ReadError(MAC), httpx.WriteError("broken pipe"), 200)
    panel = _panel(monkeypatch, put)

    with caplog.at_level(logging.WARNING, logger="worker"):
        panel.deliver(36, video)

    lines = [r.getMessage() for r in caplog.records]
    assert any("may have landed" in line and "check the piece" in line for line in lines)


def test_a_single_transport_failure_does_not_claim_anything_landed(
    monkeypatch: pytest.MonkeyPatch, video: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Before any attempt has failed there is nothing that could have landed."""
    put = _Put(httpx.ReadError(MAC), 200)
    panel = _panel(monkeypatch, put)

    with caplog.at_level(logging.WARNING, logger="worker"):
        panel.deliver(36, video)

    assert not any("may have landed" in r.getMessage() for r in caplog.records)
