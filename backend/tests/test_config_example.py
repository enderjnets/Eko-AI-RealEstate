"""`.env.example` is documentation, and documentation that lies is worse than none.

Eighteen settings were added to it in one go and three of the values were
invented rather than read: an Ollama host that does not resolve on Linux, a
model nothing pulls, and half the timeout the code allows for a cold load. Each
would have failed a fresh on-prem install in a way that looks like a broken
provider rather than a wrong example file.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _documented() -> dict[str, str]:
    text = EXAMPLE.read_text()
    values: dict[str, str] = {}
    for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.M):
        # Trailing `# …` is a note to the operator, not part of the value.
        values[m.group(1)] = m.group(2).split("#", 1)[0].strip()
    return values


def test_no_example_value_contradicts_the_code() -> None:
    documented = _documented()
    wrong: list[str] = []
    for name, value in documented.items():
        field = Settings.model_fields.get(name)
        if field is None or value == "":
            continue  # not a setting, or deliberately blank for the operator
        default = field.default
        if default is None or type(default).__name__ == "PydanticUndefined":
            continue
        shown = str(default).lower() if isinstance(default, bool) else str(default)
        # 30 and 30.0 are the same number; only real disagreements matter.
        try:
            if float(value) == float(shown):
                continue
        except ValueError:
            pass
        # A secret's example is a placeholder on purpose — it must NOT be the
        # working default, which for the RLS role is a password in this repo.
        if "CHANGE" in value.upper() or "your" in value.lower():
            continue
        if value != shown:
            wrong.append(f"{name}: example={value!r} but config={shown!r}")
    assert not wrong, "\n".join(wrong)


def test_every_setting_is_documented() -> None:
    text = EXAMPLE.read_text()
    missing = [
        name
        for name in Settings.model_fields
        if not re.search(rf"\b{re.escape(name)}\b", text)
    ]
    assert not missing, f"undocumented settings: {missing}"
