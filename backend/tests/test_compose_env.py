"""A setting the container cannot read is a setting that does not exist.

`test_config_example.py` checks that `.env.example` agrees with `Settings`. It
never checked the step in between: that `docker-compose.yml` actually hands the
value to the backend process. Eighteen settings had fallen through that gap,
and the failures were all silent —

- `TURNSTILE_SECRET` was documented, warned about at startup, and read per
  request, and the container never received it. The captcha therefore accepted
  every submission without verifying anything, which looks identical from the
  outside to a captcha that works.
- The entire Cal.com block was unreachable, so a production install's calendar
  was simulated and could not be switched to a real account no matter what the
  operator put in `.env`.
- `LOG_LEVEL` was set in the running install's `.env` and ignored.
- `RESO_PAGE_SIZE` diverged when a fix raised the `Settings` default to the
  documented API cap and left compose behind, so the alignment never reached a
  running install.

The shape is always the same: the operator changes a documented value, nothing
happens, and nothing says so.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

_COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
_ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

# Settings the backend legitimately does not read from compose.
#
# APP_VERSION is deliberately absent everywhere — it lives in code so a
# deployment cannot serve a version string that disagrees with what is running.
# The DATABASE_URL family is assembled by compose under different names.
_NOT_FROM_COMPOSE = {"APP_VERSION"}


def _backend_env_block() -> str:
    text = _COMPOSE.read_text()
    start = text.index("  backend:")
    end = text.index("  frontend:")
    return text[start:end]


def _documented() -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", _ENV_EXAMPLE.read_text(), re.M))


def _declared() -> set[str]:
    """Every variable the backend service passes, however it passes it."""
    return set(re.findall(r"^\s{6}([A-Z][A-Z0-9_]*):", _backend_env_block(), re.M))


def _defaults() -> dict[str, str]:
    """Only the ones written `NAME: ${NAME:-default}`, mapped to that default.

    Deliberately excludes `NAME: ${NAME}` (pass through, no fallback) and
    `NAME: ${NAME:?msg}` (refuse to boot). Treating those as "a default of the
    empty string" is what made the first version of this test fail on every
    secret the compose file correctly declines to invent a value for.
    """
    out: dict[str, str] = {}
    for name, value in re.findall(
        r"^\s{6}([A-Z][A-Z0-9_]*):\s*(.*)$", _backend_env_block(), re.M
    ):
        m = re.match(rf"^\$\{{{re.escape(name)}:-(.*)\}}$", value.strip())
        if m:
            out[name] = m.group(1)
    return out


def test_every_documented_setting_reaches_the_container() -> None:
    documented = _documented()
    passed = _declared()
    missing = sorted(
        name
        for name in Settings.model_fields
        if name in documented and name not in passed and name not in _NOT_FROM_COMPOSE
    )
    assert not missing, (
        "documented in .env.example but never passed to the backend container, "
        "so setting them does nothing: " + ", ".join(missing)
    )


def test_compose_defaults_do_not_contradict_the_code() -> None:
    """Where compose supplies a fallback, it must be the same value the code uses.

    A compose fallback that disagrees is worse than a missing one: the operator
    reads the default in `.env.example`, the code agrees with it, and the
    running container quietly uses a third value.
    """
    disagreements: list[str] = []
    for name, written in _defaults().items():
        field = Settings.model_fields.get(name)
        if field is None:
            continue
        expected = field.default
        if isinstance(expected, bool):
            expected = str(expected).lower()
        elif expected is None:
            expected = ""
        if str(expected) == written:
            continue
        # 120 and 120.0 are the same number written two ways.
        try:
            if float(written) == float(expected):
                continue
        except (TypeError, ValueError):
            pass
        disagreements.append(f"{name}: compose={written!r} Settings={expected!r}")
    assert not disagreements, "compose contradicts the code: " + "; ".join(
        disagreements
    )


def test_required_settings_are_not_given_a_silent_default() -> None:
    """A secret must fail loudly when unset, not fall back to something usable.

    `${VAR:?message}` makes compose refuse to start. These two carry the
    database credentials the tenant isolation depends on, and a default for
    either would mean an install silently running as the wrong role.
    """
    block = _backend_env_block()
    for name in ("APP_DB_PASSWORD", "DATABASE_URL_APP"):
        found = re.search(rf"{name}:\s*\$\{{[A-Z_]+:\?", block)
        assert found, f"{name} must use ${{...:?message}} so an unset value stops the boot"
