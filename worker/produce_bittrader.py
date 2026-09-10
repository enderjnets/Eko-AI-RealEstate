"""Lane B on the BitTrader engine: the approved script goes to the other project's
producer on this same machine, with a Denver Home Story profile, and the finished
video comes back here for the usual delivery.

Owner's decision D6b (9-sep-2026): one manufacturer for the three channels. The
writing, the Fair Housing filter, the approval and the publishing stay in this
system; only the *making* moves. `produce.py` (fal.ai + Pexels) stays as the
fallback: with `RENDER_ENGINE` unset or `eko`, nothing here runs.

How it hands over: a JSON spec in the job's workdir, one subprocess
(`render_externo.py` in the BitTrader agents dir, under the BitTrader virtualenv,
with `BITTRADER_CHANNEL` in the child's environment), one JSON result back. The
engine refuses to run against a channel that publishes on its own, so a wrong
channel variable cannot put a Denver video in a crypto channel's upload queue.

What is NOT re-checked here: the brand mark. `verify.brand_is_present` crops the
exact rectangle `assemble` composites into, and the BitTrader engine burns the
DHS mark elsewhere on the frame; its own watermark rule (REGLA #2, correlation
against the same PNG) is reported in the result and is the check we trust. A
result without a confirmed mark is a `Rejected`, terminal, like any other.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from worker import config, verify

log = logging.getLogger("worker.bittrader")

# A BitTrader short measured 21 minutes on this machine; the panel reclaims a
# stale claim after two hours. One hour leaves room for a slow Kling day and
# still returns the job to the queue with time to spare.
TIMEOUT_S = 60 * 60


class EngineFailed(Exception):
    """The BitTrader engine did not hand back a usable video. Not terminal: a
    retry may hit a better hour for the image suppliers."""


def _say(report, stage: str, percent: int) -> None:
    if report is not None:
        try:
            report(stage, percent)
        except Exception:  # noqa: BLE001 — advisory, never fatal
            pass


def command(cfg: config.Config, entrada: Path, salida: Path) -> list[str]:
    return [
        str(cfg.bittrader_python),
        "render_externo.py",
        "--entrada",
        str(entrada),
        "--salida",
        str(salida),
    ]


def produce(spec: dict, workdir: Path, *, cfg: config.Config, report=None) -> Path:
    """Script in, finished video out — built by BitTrader, delivered by us."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    entrada = workdir / "spec.json"
    salida = workdir / "resultado.json"
    registro = workdir / "bittrader.log"
    entrada.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    env = dict(os.environ)
    env["BITTRADER_CHANNEL"] = cfg.bittrader_channel
    _say(report, "bittrader", 5)
    log.info("handing the script to the BitTrader engine (channel %s)", cfg.bittrader_channel)
    with registro.open("wb") as out:
        proc = subprocess.run(
            command(cfg, entrada, salida),
            cwd=str(cfg.bittrader_agents),
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            timeout=TIMEOUT_S,
            check=False,
        )
    if not salida.is_file():
        raise EngineFailed(
            f"the BitTrader engine exited {proc.returncode} without a result file; see {registro}"
        )
    try:
        res = json.loads(salida.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise EngineFailed(f"the BitTrader engine wrote an unreadable result: {exc}") from exc
    if not res.get("ok"):
        raise EngineFailed(f"the BitTrader engine said no: {res.get('error') or 'no detail'}")
    mp4 = Path(str(res.get("output_file") or ""))
    if not mp4.is_file():
        raise EngineFailed(f"the BitTrader engine named a video that is not there: {mp4}")
    marca = res.get("marca_agua") or {}
    if not marca.get("ok"):
        raise verify.Rejected(
            "brand mark not confirmed by the engine "
            f"(corr {marca.get('corr')}, {marca.get('motivo') or 'no detail'})"
        )
    destination = workdir / "video.mp4"
    shutil.copy2(mp4, destination)
    log.info(
        "BitTrader engine delivered %s (%.1fs, mark corr %.3f)",
        mp4.name, float(res.get("duration") or 0), float(marca.get("corr") or 0),
    )
    _say(report, "bittrader", 95)
    return destination
