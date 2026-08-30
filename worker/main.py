"""The loop: ask for work, do it, hand it back.

Deliberately boring. Everything interesting is in the modules it calls, and
everything dangerous is somewhere else entirely — this program cannot approve a
video, cannot choose which piece to work on, and cannot publish. The finished
file lands in the approval queue where a licensed agent looks at it.

Three properties worth naming:

* **It polls; nothing calls it.** No port is opened on this machine.
* **The allowed hours are checked on every tick**, not declared to a timer.
  `OnCalendar` with `Persistent=true` fires a missed run late, and after a power
  cut that is a render starting inside another project's window on a machine
  three of them share.
* **One job at a time.** ffmpeg saturates the cores it is given; two renders in
  parallel is one render at half speed, twice.
"""

from __future__ import annotations

import logging
import shutil
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from worker import assemble, config, subtitles, verify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("worker")

ASSETS = Path(__file__).resolve().parent / "assets"
MARK = ASSETS / "dhs-mark.png"
MUSIC_DIR = ASSETS / "bgm"

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)

_running = True


def _stop(signum: int, _frame: object) -> None:
    global _running
    log.info("signal %s — finishing the current job and stopping", signum)
    _running = False


def font() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def within_hours(hours: frozenset[int], now: datetime | None = None) -> bool:
    """Is this an hour this machine agreed to work in?

    Empty means every hour, so running the worker by hand to debug it needs no
    knowledge of today's schedule.
    """
    if not hours:
        return True
    return (now or datetime.now()).hour in hours


def enough_disk(path: Path, min_free_gb: float) -> bool:
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        return False
    return free / (1024**3) >= min_free_gb


def pick_music() -> Path | None:
    """A bed track, or none.

    None is a perfectly good video. Missing assets never stop a render: an
    agency that has not chosen music yet gets a video without music, not an
    error nobody can act on.
    """
    if not MUSIC_DIR.is_dir():
        return None
    tracks = sorted(p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in {".mp3", ".m4a", ".wav"})
    if not tracks:
        return None
    # Rotate by the day rather than at random, so a run is reproducible and two
    # videos made the same day sound like a set.
    return tracks[datetime.now().toordinal() % len(tracks)]


class Panel:
    """The panel's queue, over HTTPS. The only thing this program talks to."""

    def __init__(self, cfg: config.Config) -> None:
        self.cfg = cfg
        self.http = httpx.Client(
            base_url=f"{cfg.api_base}/api/v1/internal/render-jobs",
            headers={"X-Worker-Token": cfg.token},
            timeout=httpx.Timeout(30.0, read=300.0),
        )

    def claim(self) -> dict | None:
        resp = self.http.post("/claim", params={"worker": self.cfg.name})
        resp.raise_for_status()
        return resp.json() or None

    def job_input(self, job_id: int) -> dict:
        resp = self.http.get(f"/{job_id}/input")
        resp.raise_for_status()
        return resp.json()

    def download_media(self, job_id: int, destination: Path) -> None:
        with self.http.stream("GET", f"/{job_id}/media") as resp:
            resp.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in resp.iter_bytes(chunk_size=1024 * 256):
                    handle.write(chunk)

    def deliver(self, job_id: int, video: Path) -> None:
        with video.open("rb") as handle:
            resp = self.http.put("/result", params={"job_id": job_id}, content=handle)
        resp.raise_for_status()

    def failed(self, job_id: int, error: str) -> None:
        try:
            self.http.post(f"/{job_id}/fail", json={"error": error[:2000]})
        except Exception:  # noqa: BLE001 — reporting a failure must not raise
            log.exception("could not report the failure of job %s", job_id)

    def heartbeat(self) -> None:
        try:
            self.http.post("/heartbeat", json={"worker": self.cfg.name})
        except Exception as exc:  # noqa: BLE001
            log.warning("heartbeat failed: %s", exc)


def do_subtitle_job(cfg: config.Config, panel: Panel, job: dict, spec: dict) -> Path:
    """Lane A: a filmed clip becomes a captioned, signed, vertical video."""
    workdir = cfg.workdir / f"job-{job['id']}"
    workdir.mkdir(parents=True, exist_ok=True)

    source = workdir / "source.mp4"
    panel.download_media(job["id"], source)
    probe = verify.probe(source)

    words = subtitles.transcribe(source, language=spec.get("language", "en"))
    ass_path = subtitles.write_ass(subtitles.group(words), workdir / "captions.ass")
    if ass_path is None:
        log.info("job %s: no speech found, rendering without captions", job["id"])

    brokerage_file = workdir / "brokerage.txt"
    brokerage_file.write_text(spec["brokerage_line"], encoding="utf-8")
    domain_file = workdir / "domain.txt"
    domain_file.write_text("denverhomestory.com", encoding="utf-8")

    destination = workdir / "out.mp4"
    assemble.run(
        assemble.build_command(
            source,
            destination,
            duration=probe.duration,
            has_audio=probe.has_audio,
            brokerage_file=brokerage_file,
            domain_file=domain_file,
            font=font(),
            mark=MARK if MARK.is_file() else None,
            subtitles=ass_path,
            music=pick_music(),
        )
    )

    verify.check(destination, expect_audio=probe.has_audio)
    if MARK.is_file():
        # Pixels, not the command that produced them. A render can run happily
        # and composite the wrong image, or none — which is exactly what
        # shipped next door with another brand's watermark on it.
        correlation = verify.brand_is_present(destination, MARK, workdir)
        log.info("job %s: brand mark present (correlation %.3f)", job["id"], correlation)
    return destination


def handle(cfg: config.Config, panel: Panel, job: dict) -> None:
    workdir = cfg.workdir / f"job-{job['id']}"
    try:
        spec = panel.job_input(job["id"])
        if not (spec.get("brokerage_line") or "").strip():
            # Nothing legal to burn. Reported rather than rendered: the video
            # would only have to be made again.
            panel.failed(job["id"], "the organisation has no brokerage line on record")
            return

        if job["kind"] == "subtitle_a":
            video = do_subtitle_job(cfg, panel, job, spec)
        else:
            panel.failed(job["id"], f"this worker cannot do {job['kind']} yet")
            return

        panel.deliver(job["id"], video)
        log.info("job %s delivered", job["id"])
    except Exception as exc:  # noqa: BLE001 — one bad job must not stop the worker
        log.exception("job %s failed", job["id"])
        panel.failed(job["id"], f"{type(exc).__name__}: {exc}")
    finally:
        # Always, including on success: these are hundreds of megabytes on a
        # machine three projects share.
        shutil.rmtree(workdir, ignore_errors=True)


def main() -> int:
    cfg = config.load()
    blocked = cfg.configured
    if blocked:
        log.error("the render worker cannot start: %s", blocked)
        return 1

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    cfg.workdir.mkdir(parents=True, exist_ok=True)
    panel = Panel(cfg)
    log.info(
        "render worker %s started (hours=%s, poll=%ds)",
        cfg.name,
        sorted(cfg.hours) or "any",
        cfg.poll_seconds,
    )

    while _running:
        try:
            # The heartbeat goes out on every tick, in or out of hours: it says
            # "this process is alive", and a worker that only reported inside
            # its window would look dead for twenty hours a day.
            panel.heartbeat()

            if not within_hours(cfg.hours):
                time.sleep(cfg.poll_seconds)
                continue
            if not enough_disk(cfg.workdir, cfg.min_free_gb):
                log.error(
                    "less than %.0f GB free — not starting a render", cfg.min_free_gb
                )
                time.sleep(cfg.poll_seconds)
                continue

            job = panel.claim()
            if job is None:
                time.sleep(cfg.poll_seconds)
                continue
            log.info("claimed job %s (%s) for piece %s", job["id"], job["kind"], job["piece_id"])
            handle(cfg, panel, job)
        except httpx.HTTPError as exc:
            # The panel being unreachable is weather, not a fault: keep polling.
            log.warning("panel unreachable: %s", exc)
            time.sleep(cfg.poll_seconds)
        except Exception:  # noqa: BLE001 — the loop outlives everything
            log.exception("unexpected failure in the worker loop")
            time.sleep(cfg.poll_seconds)

    log.info("render worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
