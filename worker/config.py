"""What the worker needs to know, read from the environment.

Deliberately not pydantic-settings and deliberately not importing anything from
`backend/`: this program runs on a different machine, in its own virtualenv,
and every dependency it shares is a dependency that has to be installed and
kept in step over there.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _hours(raw: str) -> frozenset[int]:
    """`"13,15,16"` → {13, 15, 16}. Empty means every hour.

    Empty is permissive on purpose: an operator running the worker by hand to
    debug it should not have to know today's schedule. The service file always
    sets it.
    """
    out = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            hour = int(part)
        except ValueError:
            continue
        if 0 <= hour <= 23:
            out.add(hour)
    return frozenset(out)


@dataclass(frozen=True)
class Config:
    api_base: str
    token: str
    name: str
    hours: frozenset[int]
    workdir: Path
    poll_seconds: int
    # Refuse to start a job below this, in gigabytes. A render that fills the
    # disk on a machine three projects share does not fail politely.
    min_free_gb: float = field(default=15.0)
    # Twice the measured peak of the heaviest step, on a 15 GB machine three
    # projects share. See `enough_memory` for the measurements.
    min_memory_gb: float = field(default=1.5)
    # v0.99.0 — which engine builds lane B. "eko" is our own maker (fal.ai +
    # Pexels, `produce.py`); "bittrader" hands the approved script to the
    # BitTrader engine installed on this same machine with the Denver Home
    # Story profile (owner's decision D6b, 9-sep-2026). Unset means "eko", so a
    # worker that never heard of the other engine behaves exactly as before.
    engine: str = field(default="eko")
    bittrader_python: Path = field(
        default_factory=lambda: Path.home() / ".venvs" / "bittrader" / "bin" / "python"
    )
    bittrader_agents: Path = field(
        default_factory=lambda: Path.home() / ".openclaw" / "workspace" / "bittrader" / "agents"
    )
    bittrader_channel: str = field(default="denver_home_story")

    @property
    def configured(self) -> str | None:
        """Why this worker cannot run, or None."""
        if not self.api_base:
            return "EKO_API_BASE is unset"
        if not self.token:
            return "RENDER_WORKER_TOKEN is unset"
        if self.engine not in ("eko", "bittrader"):
            return f"RENDER_ENGINE={self.engine!r} is not an engine (eko or bittrader)"
        if self.engine == "bittrader":
            if not self.bittrader_python.is_file():
                return f"RENDER_ENGINE=bittrader but {self.bittrader_python} is not there"
            if not (self.bittrader_agents / "render_externo.py").is_file():
                return (
                    "RENDER_ENGINE=bittrader but render_externo.py is not in "
                    f"{self.bittrader_agents} (BitTrader >= 2.14.112)"
                )
        return None


def load() -> Config:
    return Config(
        api_base=os.environ.get("EKO_API_BASE", "").strip().rstrip("/"),
        token=os.environ.get("RENDER_WORKER_TOKEN", "").strip(),
        name=os.environ.get("RENDER_WORKER_NAME", "worker").strip()[:64],
        hours=_hours(os.environ.get("RENDER_WORKER_HOURS", "")),
        workdir=Path(
            os.environ.get("RENDER_WORKER_DIR", str(Path.home() / "eko-render" / "tmp"))
        ),
        poll_seconds=int(os.environ.get("RENDER_WORKER_POLL_SECONDS", "60")),
        min_free_gb=float(os.environ.get("RENDER_WORKER_MIN_FREE_GB", "15")),
        min_memory_gb=float(os.environ.get("RENDER_WORKER_MIN_MEMORY_GB", "1.5")),
        engine=os.environ.get("RENDER_ENGINE", "eko").strip().lower() or "eko",
        bittrader_python=Path(
            os.environ.get("RENDER_BITTRADER_PYTHON", "").strip()
            or str(Path.home() / ".venvs" / "bittrader" / "bin" / "python")
        ),
        bittrader_agents=Path(
            os.environ.get("RENDER_BITTRADER_AGENTS", "").strip()
            or str(Path.home() / ".openclaw" / "workspace" / "bittrader" / "agents")
        ),
        bittrader_channel=(
            os.environ.get("RENDER_BITTRADER_CHANNEL", "").strip() or "denver_home_story"
        ),
    )
