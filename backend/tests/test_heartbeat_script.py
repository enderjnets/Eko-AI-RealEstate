"""Tests for `deploy/heartbeat.sh` — the watchdog that outlives its own machine.

This script runs from cron on a host that is not the ROG, so nothing in the
backend test suite exercises it in production. It was verified by hand once,
which is worth exactly as much as any other thing verified by hand once: the
next person to touch it gets no warning. These run the real script as a
subprocess against a stub mail endpoint, so the state machine is pinned.

The property that matters is the one an adversarial review found missing: **a
send that did not go out must not retire the outage**, or the next check reads
"unchanged" and nobody is ever told. Its twin matters just as much: the retry
must be capped, because a message the provider accepted whose response timed out
is indistinguishable from a rejection here, and an uncapped retry would mail
real duplicates out of the quota that answers leads.
"""
from __future__ import annotations

import http.server
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "heartbeat.sh"
# Nothing listens here, so a health check against it fails the way a dead host
# does — connection refused rather than a slow timeout.
DEAD_URL = "http://127.0.0.1:9/nope"


@pytest.fixture(scope="module")
def stub_mail():
    """A stand-in for the mail provider whose status code each test chooses."""
    state = {"status": 200, "received": [], "headers": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 — http.server's spelling
            length = int(self.headers.get("Content-Length", 0))
            state["received"].append(json.loads(self.rfile.read(length) or b"{}"))
            state["headers"].append(dict(self.headers))
            self.send_response(state["status"])
            self.end_headers()
            self.wfile.write(b'{"id":"stub"}')

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/emails"
    yield state
    server.shutdown()


@pytest.fixture
def run(tmp_path, stub_mail):
    """Run the script once. Returns (returncode, stderr) — it logs to stderr."""
    env_file = tmp_path / "env"
    env_file.write_text(
        "RESEND_API_KEY=re_stub\n"
        "OPS_ALERT_FROM=alertas@example.invalid\n"
        "OPS_ALERT_TO=operador@example.invalid\n"
    )
    state_dir = tmp_path / "state"

    def _run(*, healthy: bool, configured: bool = True) -> tuple[int, str]:
        proc = subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                "HOME": str(tmp_path),
                "HEALTH_URL": stub_mail["health_url"] if healthy else DEAD_URL,
                "RESEND_URL": stub_mail["url"],
                "HEARTBEAT_ENV": str(env_file) if configured else "/dev/null",
                "HEARTBEAT_STATE_DIR": str(state_dir),
            },
        )
        return proc.returncode, proc.stderr

    _run.state_dir = state_dir
    _run.read = lambda name: (
        (state_dir / name).read_text() if (state_dir / name).exists() else ""
    )
    return _run


@pytest.fixture(autouse=True)
def _health_stub(stub_mail, tmp_path):
    """A second stub standing in for /api/v1/health, so "healthy" is real."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(stub_mail.get("health_status", 200))
            self.end_headers()
            self.wfile.write(stub_mail.get("health_body", b'{"status":"ok","llm_fallback":"ok"}'))

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stub_mail["health_url"] = f"http://127.0.0.1:{server.server_address[1]}/api/v1/health"
    stub_mail["received"].clear()
    stub_mail["headers"].clear()
    stub_mail["status"] = 200
    stub_mail.pop("health_status", None)
    stub_mail.pop("health_body", None)
    yield
    server.shutdown()


pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or not SCRIPT.exists(),
    reason="needs bash and deploy/heartbeat.sh",
)


def test_a_healthy_first_run_records_a_baseline_without_alerting(run) -> None:
    """A fresh install must not greet its owner with an outage that never was."""
    rc, err = run(healthy=True)
    assert rc == 0
    assert "nothing to report" in err
    assert run.read("state") == "up"


def test_one_bad_check_waits_because_every_deploy_restarts_the_backend(run) -> None:
    run(healthy=True)
    rc, err = run(healthy=False)
    assert rc == 0
    assert "waiting for confirmation" in err
    assert run.read("state") == "up", "un solo fallo no es una caida"


def test_a_delivered_alert_records_the_outage_and_does_not_repeat(
    run, stub_mail
) -> None:
    run(healthy=True)
    run(healthy=False)
    _, err = run(healthy=False)
    assert "alert sent" in err
    assert run.read("state") == "down"

    _, err = run(healthy=False)
    assert "alert sent" not in err, "ya comunicado: no se repite"
    assert run.read("count").endswith(":1")


def test_a_rejected_alert_does_not_retire_the_outage(run, stub_mail) -> None:
    """MUTATION GUARD — the finding this phase exists to fix.

    Make the tail write `$STATE_FILE` unconditionally again and this goes red:
    the state would read `down`, the next check would see "unchanged", and the
    outage would never be mentioned to anyone.
    """
    run(healthy=True)
    run(healthy=False)
    stub_mail["status"] = 500
    _, err = run(healthy=False)

    assert "REJECTED" in err
    assert "state NOT recorded" in err
    assert run.read("state") == "up", "un aviso que no salio no comunica nada"

    _, err = run(healthy=False)
    assert "REJECTED" in err, "y por eso se reintenta"


def test_the_retry_is_capped_so_a_broken_transport_cannot_mail_all_day(
    run, stub_mail
) -> None:
    """MUTATION GUARD — charge the ATTEMPT, not the delivery.

    Move the counter write back below the curl (inside the 2xx branch) and this
    goes red. A failed send would then cost nothing, the budget would never
    close, and every check would try again — with a timed-out-but-delivered
    message reading as a failure, those are real duplicates.
    """
    run(healthy=True)
    run(healthy=False)
    stub_mail["status"] = 500
    for _ in range(6):
        run(healthy=False)

    assert run.read("count").endswith(":3"), "el techo corta en MAX_ALERTS_PER_DAY"
    assert run.read("state") == "up", "y la deuda sigue pendiente"


def test_an_unconfigured_channel_is_recorded_rather_than_retried(run) -> None:
    """No sender means no attempt can reach anyone. Holding the outage open for
    that would write the same line to the log on a timer, forever."""
    run(healthy=True, configured=False)
    run(healthy=False, configured=False)
    _, err = run(healthy=False, configured=False)

    assert "NOT CONFIGURED" in err
    assert run.read("state") == "down", "consumido: no hay nada que reintentar"
    assert run.read("count") == "", "y no gasta un presupuesto que nadie usara"


def test_recovery_is_reported_too(run, stub_mail) -> None:
    run(healthy=True)
    run(healthy=False)
    run(healthy=False)
    stub_mail["received"].clear()
    _, err = run(healthy=True)

    assert "alert sent" in err
    assert run.read("state") == "up"
    assert "vuelve a ver" in stub_mail["received"][-1]["subject"]


def test_the_alert_carries_no_credentials(run, stub_mail) -> None:
    """The body quotes a server response we did not write. It must not quote the
    key that sent it."""
    run(healthy=True)
    run(healthy=False)
    run(healthy=False)

    sent = json.dumps(stub_mail["received"])
    assert "re_stub" not in sent, "la clave no puede viajar en el cuerpo"

    # La cabecera SI debe llevarla — el punto es que llegue entera por stdin y
    # solo ahi. Antes esta mitad no podia fallar: el stub no guardaba cabeceras.
    auth = stub_mail["headers"][-1].get("Authorization", "")
    assert auth == "Bearer re_stub", f"la cabecera debe llegar intacta, no {auth!r}"


def test_a_reachable_service_with_a_broken_safety_net_is_still_an_outage(
    run, stub_mail
) -> None:
    """Half the reason this watchdog exists.

    The backend answering 200 proves the box is alive; it says nothing about
    whether the LLM safety net can catch a fall. A watchdog that only checks
    liveness would report all-clear through exactly the failure that started
    this whole line of work.
    """
    run(healthy=True)
    stub_mail["health_body"] = b'{"status":"ok","llm_fallback":"model-missing"}'
    run(healthy=True)
    _, err = run(healthy=True)

    assert "alert sent" in err
    assert run.read("state") == "down"
    body = stub_mail["received"][-1]["text"]
    assert "llm_fallback=model-missing" in body, "el aviso debe nombrar el estado real"


def test_the_key_never_reaches_the_process_command_line(run, stub_mail) -> None:
    """MUTATION GUARD — put `-H "Authorization: Bearer $RESEND_API_KEY"` back on
    the curl invocation and this goes red.

    On Linux /proc/<pid>/cmdline is world-readable, so a secret on an argv is
    readable by any local account that polls the process tree — and `chmod 600`
    on the env file buys nothing once the key is copied onto a command line
    several times a day. The body follows the same rule: it is not secret, but
    it names internal hosts and containers.
    """
    src = SCRIPT.read_text()
    curl_block = src[src.index("curl -sS -o /dev/null"):]
    curl_block = curl_block[: curl_block.index(")\"")]

    # Sin el `$`: `${RESEND_API_KEY}` con llaves es la forma mas comun y
    # esquivaba la version anterior de esta asercion.
    assert "RESEND_API_KEY" not in curl_block, "la clave no puede ir en argv"
    assert "--config -" in curl_block, "va por stdin"
    assert '-d "@' in curl_block, "y el cuerpo por fichero, no en argv"


def test_a_permanent_build_failure_is_capped_like_any_other(run, tmp_path) -> None:
    """Cron's PATH is sparse. Without python3 the payload cannot be built at all
    — a permanent failure, and one that would otherwise retry forever with no
    counter to stop it and 2>/dev/null hiding every line of it."""
    run(healthy=True)
    run(healthy=False)

    env_file = tmp_path / "env"
    state_dir = tmp_path / "state"

    # A PATH with the tools the script needs EXCEPT python3, which is what
    # cron's own sparse PATH looks like on a host where python lives in /usr/local.
    crippled = tmp_path / "bin"
    crippled.mkdir()
    for tool in ("curl", "date", "mktemp", "cat", "rm", "chmod", "mkdir", "printf", "grep", "sed", "tr"):
        found = shutil.which(tool)
        if found:
            (crippled / tool).symlink_to(found)

    for _ in range(5):
        subprocess.run(
            [shutil.which("bash") or "/bin/bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "PATH": str(crippled),
                "HOME": str(tmp_path),
                "HEALTH_URL": DEAD_URL,
                # Fijado aunque este test nunca deberia llegar al envio: si
                # alguien mueve la construccion del payload por debajo de curl,
                # sin esto el test llamaria al proveedor REAL desde CI.
                "RESEND_URL": "http://127.0.0.1:9/never",
                "HEARTBEAT_ENV": str(env_file),
                "HEARTBEAT_STATE_DIR": str(state_dir),
            },
        )

    count = (state_dir / "count").read_text() if (state_dir / "count").exists() else ""
    assert count.endswith(":3"), f"el techo debe cortar tambien aqui, no {count!r}"


def test_a_rejected_recovery_does_not_retire_it_either(run, stub_mail) -> None:
    """MUTATION GUARD — the other half of the fix, which had no guard at all.

    An audit made `alert_rc` capture the wrong command's exit status in the
    recovery branch and the whole suite stayed green, while a rejected
    "it's back" mail still wrote `up`: the operator would go on believing in an
    outage that had already ended, with no retry. The bug this phase removes,
    pointing the other way.
    """
    run(healthy=True)
    run(healthy=False)
    run(healthy=False)
    assert run.read("state") == "down"

    stub_mail["status"] = 500
    _, err = run(healthy=True)
    assert "REJECTED" in err
    assert "state NOT recorded (down -> up)" in err
    assert run.read("state") == "down", "una recuperacion no comunicada no es una recuperacion"

    stub_mail["status"] = 200
    _, err = run(healthy=True)
    assert "alert sent" in err
    assert run.read("state") == "up"
