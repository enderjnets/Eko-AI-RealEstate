"""The version is one number, and the release rule is mechanical.

`APP_VERSION` lives in backend code and `CURRENT_VERSION` in frontend code, with
nothing tying them together — so a release that bumped one and forgot the other
shipped happily, and `/api/v1/health` reported the old number while the tag said
the new one. That is not a cosmetic mismatch: health is what a deploy is
verified against, so the check meant to catch a half-finished deploy quietly
certified one.

CLAUDE.md also requires a CHANGELOG.md entry per released version. A rule that
is only written down is a rule that gets skipped under pressure.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
VERSION_TS = ROOT / "frontend" / "lib" / "version.ts"
CHANGELOG = ROOT / "CHANGELOG.md"


def _frontend_version() -> str:
    assert VERSION_TS.is_file(), f"expected {VERSION_TS} to exist"
    match = re.search(
        r'export const CURRENT_VERSION\s*=\s*"([^"]+)"', VERSION_TS.read_text()
    )
    assert match is not None, "CURRENT_VERSION not found in version.ts"
    return match.group(1)


def test_the_backend_and_the_dashboard_report_the_same_version() -> None:
    assert get_settings().APP_VERSION == _frontend_version(), (
        "backend APP_VERSION and frontend CURRENT_VERSION disagree — /api/v1/health "
        "would report one number while the dashboard shows another"
    )


def test_the_released_version_has_a_changelog_entry() -> None:
    version = _frontend_version()
    assert CHANGELOG.is_file(), f"expected {CHANGELOG} to exist"
    headings = re.findall(r"^## \[([^\]]+)\]", CHANGELOG.read_text(), re.MULTILINE)
    assert version in headings, (
        f"{version} is the current version but has no CHANGELOG.md entry"
    )
