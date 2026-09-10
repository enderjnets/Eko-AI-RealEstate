"""v0.99.0 — lane B on the BitTrader engine (owner's decision D6b, 9-sep-2026).

What must hold: with `RENDER_ENGINE` unset the worker is byte-for-byte the worker of
yesterday; `bittrader` is accepted only when the engine is actually installed; the
hand-over runs the engine's CLI in ITS directory, under ITS interpreter, with the
channel in the CHILD's environment; and every way the engine can fail turns into the
right exception — a missing mark is `Rejected` (terminal), anything else retries.

Nothing here runs the real engine: `subprocess.run` is replaced by a fake that writes
the result file the engine would write.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from worker import config, main, produce_bittrader, verify


def _cfg(tmp_path: Path, engine: str = "bittrader", **more) -> config.Config:
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    agents = tmp_path / "agents"
    agents.mkdir(exist_ok=True)
    (agents / "render_externo.py").write_text("# stub\n", encoding="utf-8")
    base = dict(
        api_base="https://panel.example", token="t" * 20, name="rog-test",
        hours=frozenset(), workdir=tmp_path / "work", poll_seconds=1,
        engine=engine, bittrader_python=python, bittrader_agents=agents,
        bittrader_channel="denver_home_story",
    )
    base.update(more)
    return config.Config(**base)


# ── configuration ─────────────────────────────────────────────────────────────

def test_the_engine_is_eko_unless_somebody_says_otherwise(monkeypatch) -> None:
    for var in ("RENDER_ENGINE", "RENDER_BITTRADER_PYTHON", "RENDER_BITTRADER_AGENTS",
                "RENDER_BITTRADER_CHANNEL"):
        monkeypatch.delenv(var, raising=False)
    cfg = config.load()
    assert cfg.engine == "eko"
    assert cfg.bittrader_channel == "denver_home_story"
    assert cfg.bittrader_python.name == "python"


def test_the_engine_variable_is_read_and_normalised(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RENDER_ENGINE", " BitTrader ")
    monkeypatch.setenv("RENDER_BITTRADER_PYTHON", str(tmp_path / "py"))
    monkeypatch.setenv("RENDER_BITTRADER_AGENTS", str(tmp_path / "ag"))
    monkeypatch.setenv("RENDER_BITTRADER_CHANNEL", "denver_home_story")
    cfg = config.load()
    assert cfg.engine == "bittrader"
    assert cfg.bittrader_python == tmp_path / "py"
    assert cfg.bittrader_agents == tmp_path / "ag"


def test_a_typo_in_the_engine_name_refuses_to_start(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, engine="bitrader")
    assert cfg.configured is not None
    assert "bitrader" in cfg.configured


def test_bittrader_without_the_engine_installed_refuses_to_start(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert cfg.configured is None
    (cfg.bittrader_agents / "render_externo.py").unlink()
    assert "render_externo.py" in (cfg.configured or "")
    cfg.bittrader_python.unlink()
    assert "not there" in (cfg.configured or "")


def test_eko_stays_configured_whatever_bittrader_looks_like(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, engine="eko", bittrader_python=tmp_path / "missing",
               bittrader_agents=tmp_path / "missing")
    assert cfg.configured is None


# ── the hand-over ─────────────────────────────────────────────────────────────

SPEC = {"piece_id": 7, "kind": "produce_b", "language": "en",
        "brokerage_line": "Brokered by Example Realty", "hook": "h", "script": "s",
        "scenes": {"narration": "s", "scenes": [{"visual_prompt": "a house", "on_screen_text": "x"}]},
        "people_words": ["family"]}


class _Engine:
    """A fake `subprocess.run` that behaves like render_externo.py would."""

    def __init__(self, tmp_path: Path, result: dict | None, returncode: int = 0):
        self.tmp_path, self.result, self.returncode = tmp_path, result, returncode
        self.calls: list[dict] = []

    def __call__(self, cmd, **kw):
        self.calls.append({"cmd": cmd, **kw})
        salida = Path(cmd[cmd.index("--salida") + 1])
        if self.result is not None:
            res = dict(self.result)
            if res.get("output_file") == "<mp4>":
                mp4 = self.tmp_path / "engine_out.mp4"
                mp4.write_bytes(b"\x00" * 1024)
                res["output_file"] = str(mp4)
            salida.write_text(json.dumps(res), encoding="utf-8")
        kw["stdout"].write(b"engine log line\n")
        return subprocess.CompletedProcess(cmd, self.returncode)


GOOD = {"ok": True, "script_id": "short_abc", "output_file": "<mp4>", "duration": 33.4,
        "marca_agua": {"ok": True, "corr": 0.91, "motivo": "marca presente"}, "canal": "denver_home_story"}


def test_the_engine_runs_in_its_own_house_with_the_channel_in_the_childs_env(
    monkeypatch, tmp_path: Path
) -> None:
    cfg = _cfg(tmp_path)
    engine = _Engine(tmp_path, GOOD)
    monkeypatch.setattr(produce_bittrader.subprocess, "run", engine)
    monkeypatch.delenv("BITTRADER_CHANNEL", raising=False)
    stages: list[tuple[str, int]] = []
    workdir = tmp_path / "work" / "job-1"
    video = produce_bittrader.produce(SPEC, workdir, cfg=cfg, report=lambda s, p: stages.append((s, p)))

    assert video == workdir / "video.mp4" and video.stat().st_size == 1024
    call = engine.calls[0]
    assert call["cmd"][0] == str(cfg.bittrader_python)
    assert call["cmd"][1] == "render_externo.py"
    assert call["cwd"] == str(cfg.bittrader_agents)
    assert call["env"]["BITTRADER_CHANNEL"] == "denver_home_story"
    assert call["timeout"] == produce_bittrader.TIMEOUT_S
    assert json.loads((workdir / "spec.json").read_text(encoding="utf-8")) == SPEC
    assert (workdir / "bittrader.log").read_bytes().startswith(b"engine log line")
    assert stages[0][0] == "bittrader" and stages[-1][1] == 95


def test_no_result_file_is_a_retryable_failure_that_names_the_log(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(produce_bittrader.subprocess, "run", _Engine(tmp_path, None, returncode=2))
    with pytest.raises(produce_bittrader.EngineFailed) as exc:
        produce_bittrader.produce(SPEC, tmp_path / "w", cfg=cfg)
    assert "exited 2" in str(exc.value) and "bittrader.log" in str(exc.value)


def test_the_engines_own_no_is_passed_on_verbatim(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(produce_bittrader.subprocess, "run",
                        _Engine(tmp_path, {"ok": False, "error": "LONG_TOO_SHORT"}, returncode=1))
    with pytest.raises(produce_bittrader.EngineFailed) as exc:
        produce_bittrader.produce(SPEC, tmp_path / "w", cfg=cfg)
    assert "LONG_TOO_SHORT" in str(exc.value)


def test_a_video_that_is_not_there_is_a_failure_not_a_delivery(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    res = dict(GOOD, output_file=str(tmp_path / "gone.mp4"))
    monkeypatch.setattr(produce_bittrader.subprocess, "run", _Engine(tmp_path, res))
    with pytest.raises(produce_bittrader.EngineFailed):
        produce_bittrader.produce(SPEC, tmp_path / "w", cfg=cfg)


def test_an_unconfirmed_mark_is_rejected_terminally(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    res = dict(GOOD, marca_agua={"ok": False, "corr": 0.12, "motivo": "marca ausente"})
    monkeypatch.setattr(produce_bittrader.subprocess, "run", _Engine(tmp_path, res))
    with pytest.raises(verify.Rejected) as exc:
        produce_bittrader.produce(SPEC, tmp_path / "w", cfg=cfg)
    assert "0.12" in str(exc.value)
    assert not (tmp_path / "w" / "video.mp4").exists()


# ── the dispatch ──────────────────────────────────────────────────────────────

def test_do_produce_job_hands_over_only_when_told_to(monkeypatch, tmp_path: Path) -> None:
    seen: dict = {}

    def _engine(spec, workdir, *, cfg, report=None):
        seen["spec"] = spec
        video = Path(workdir) / "video.mp4"
        video.write_bytes(b"x")
        return video

    def _never(*a, **k):
        raise AssertionError("produce.produce must not run under the bittrader engine")

    monkeypatch.setattr(main.produce_bittrader, "produce", _engine)
    monkeypatch.setattr(main.produce, "produce", _never)
    monkeypatch.setattr(main.verify, "check", lambda *a, **k: None)
    cfg = _cfg(tmp_path)
    video = main.do_produce_job(cfg, {"id": 9, "kind": "produce_b"}, SPEC)
    assert video.name == "video.mp4" and seen["spec"] == SPEC


def test_do_produce_job_builds_at_home_when_the_engine_is_eko(monkeypatch, tmp_path: Path) -> None:
    calls: list = []

    def _home(spec, workdir, **kw):
        calls.append(kw)
        video = Path(workdir) / "video.mp4"
        video.write_bytes(b"x")
        return video

    def _never(*a, **k):
        raise AssertionError("the BitTrader engine must not run when RENDER_ENGINE is eko")

    monkeypatch.setattr(main.produce, "produce", _home)
    monkeypatch.setattr(main.produce_bittrader, "produce", _never)
    monkeypatch.setattr(main.verify, "check", lambda *a, **k: None)
    monkeypatch.setattr(main.verify, "brand_is_present", lambda *a, **k: 0.9)
    cfg = _cfg(tmp_path, engine="eko")
    main.do_produce_job(cfg, {"id": 9, "kind": "produce_b"}, SPEC)
    assert len(calls) == 1 and "font" in calls[0] and "music" in calls[0]
