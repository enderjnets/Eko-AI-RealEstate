"""Every dollar figure a piece states, checked against the calculator.

Five videos went out on 12-14 September saying things like "Renting at $2,600 a
month? — Buying is ~$21,000 ahead in five years." The calculator the same
caption sends people to answers **$52,210** for that rent under the assumptions
the page actually uses. Somebody who watched the video, clicked the link and
typed their rent would be shown a number two and a half times larger than the
one they had just been promised. The owner spotted it and set all five to
private.

The figures were not invented — $21,000 reproduces at a flat **2%** annual
appreciation against the page's 3.75% — which is the worse problem, because
"wrong" and "right under assumptions nobody wrote down" look identical from
outside. `docs/content/calculator-consistency.md` has required recording the
inputs since 14-sep-2026. It was prose; nothing read it.

**The text is the source of truth, not the record.** This module extracts the
figures from the approved wording and asks the calculator to account for them,
rather than comparing the record against itself. A record that agrees with a
record is the failure mode this whole exercise keeps running into: the piece
would carry a tidy snapshot saying $52,210 while the hook said $21,000, the
check would pass, and the video would still be wrong.

A number in a piece can be one of exactly three things:

* something we were **given** — the rent, the savings, the credit band;
* something the calculator **computed** from them — a price ceiling, a
  five-year net, a monthly payment;
* the **difference** between the same computed field across two scenarios,
  which is how "doubling your down payment adds $35,000 to the price" is said.

Anything else is unexplained, and unexplained is what this refuses.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.calculator import build_snapshot

# `$2,600`, `~$21,700`, `$343,475.34`. The leading `$` is required: a bare
# number in a hook is a year, a street, a percentage, or a count of anything,
# and demanding that the calculator explain "five years" would make the gate
# useless within a week.
_FIGURE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{1,2}))?")

# Below this a dollar amount is not a calculator claim. The calculator's
# smallest meaningful output is a monthly payment in the hundreds; "$5 a month
# in HOA" is not a claim anybody needs a snapshot for, and treating it as one
# would block a piece over a rounding of pocket change.
MINIMUM_CLAIM = 100


def claimed_text(
    hook: str | None,
    caption: str | None,
    scenes: dict[str, Any] | None,
    script: str | None = None,
) -> str:
    """Every way a dollar figure in a piece reaches a person.

    One definition, used by the approval gate and by the writer's own check.
    `content_writer._all_violations` says why that matters in the Fair Housing
    case — "three copies of 'which fields count' is how a field gets added to
    the product and forgotten by the filter" — and this is the same shape of
    thing one layer down.

    **Read, heard, and seen — all three.** The gate this replaced read the hook
    and the caption. The five videos pulled on 15-sep-2026 said their wrong
    number *on screen*, and `docs/content/otono-2026.md` requires the screen to
    stand alone precisely because nobody reads a caption before deciding
    whether to keep watching: a caption edit away, that gate passes all five.

    The script is in here too, and the first draft of this function left it out
    on the reasoning that `worker/spoken.py` turns "$450,000" into words before
    anybody hears it. That is backwards. Converting it to words does not remove
    the claim — it is what makes a person *hear* it. A narrated figure nothing
    checked is the same defect with a microphone in front of it.
    """
    plan = scenes or {}
    screen = " ".join(
        str(scene.get("on_screen_text") or "")
        for scene in (plan.get("scenes") or [])
    )
    narration = str(plan.get("narration") or "")
    return "\n".join(
        part for part in (hook, caption, script, narration, screen) if part
    )


def figures_in(text: str | None) -> list[int]:
    """Every dollar amount in the text, in whole dollars, in order of appearance.

    Duplicates are kept: they cost nothing to check and dropping them would
    hide the case where the same wrong number is repeated in the caption after
    being corrected in the hook.
    """
    out: list[int] = []
    for whole, cents in _FIGURE.findall(text or ""):
        amount = int(whole.replace(",", ""))
        if cents:
            # Round to the dollar rather than truncating: the calculator's own
            # outputs are rounded, and a published `$343,475.34` should be
            # explained by a computed `$343,475`.
            amount += 1 if int(cents.ljust(2, "0")) >= 50 else 0
        out.append(amount)
    return out


def rounds_to(published: int, computed: float) -> bool:
    """Whether `computed` becomes `published` at the precision it was published at.

    A hook says `$361,000` for a computed `$360,794`, and that is honest
    rounding, not a discrepancy. The tolerance is therefore read off the
    published number itself — trailing zeros are a statement about how precise
    the claim is — instead of being a fixed percentage, which would wave
    through a $21,000-for-$52,210 on a large enough figure.
    """
    if published <= 0:
        return round(computed) == published
    step = 1
    # Capped at a thousand, and the cap is the load-bearing part. `$40,000`
    # divides by ten thousand, and reading that as "anything from 35,000 to
    # 45,000" would make every savings figure unfalsifiable — a gate that
    # cannot be failed is decoration. Nothing published here has ever been
    # rounded coarser than the nearest thousand.
    for candidate in (1_000, 100, 10):
        if published % candidate == 0:
            step = candidate
            break
    return round(computed / step) * step == published


def _scenario_values(scenario: dict[str, Any]) -> tuple[dict[str, float], list[float]]:
    """The computed fields of one scenario, and every number it was given.

    Returns the outputs keyed by name so differences can be taken field by
    field — subtracting a price from a monthly payment would manufacture an
    explanation for a number nobody computed.
    """
    inputs = dict(scenario.get("inputs") or {})
    overrides = scenario.get("overrides") or None
    snapshot = build_snapshot(inputs, overrides, lang=None)
    result = snapshot["result"]

    outputs: dict[str, float] = {}
    for key in ("price", "loan", "down", "net_5y"):
        value = result.get(key)
        if isinstance(value, int | float):
            outputs[key] = float(value)
    for key, value in (result.get("monthly") or {}).items():
        if isinstance(value, int | float):
            outputs[f"monthly.{key}"] = float(value)

    given = [
        float(v)
        for v in (inputs.get("rent"), inputs.get("savings"))
        if isinstance(v, int | float)
    ]
    return outputs, given


def unexplained_figures(text: str, check: dict[str, Any] | None) -> list[int]:
    """The figures in `text` that the recorded scenarios cannot account for.

    An empty list is a pass. `check` of None with figures present is a refusal
    listing all of them — that is the whole point of the record being required.
    """
    claims = [f for f in figures_in(text) if f >= MINIMUM_CLAIM]
    if not claims:
        return []
    if not check:
        return claims

    scenarios = check.get("scenarios") or []
    explainable: list[float] = []
    per_field: list[dict[str, float]] = []
    for scenario in scenarios:
        outputs, given = _scenario_values(scenario)
        per_field.append(outputs)
        explainable.extend(outputs.values())
        explainable.extend(given)

    # "Doubling your down payment adds $35,000 to the price": a figure nobody
    # computed directly, and the real difference is $34,638. Same field only,
    # and both directions, because a piece may phrase it as a gain or a cost.
    for i, left in enumerate(per_field):
        for right in per_field[i + 1 :]:
            for field, value in left.items():
                other = right.get(field)
                if other is not None:
                    explainable.append(abs(value - other))

    # Numbers that are deliberately not from the calculator — a listing price,
    # a recording fee. They have to be written down one by one, which is the
    # point: an escape hatch nobody can take by accident.
    explainable.extend(
        float(v) for v in (check.get("literal") or []) if isinstance(v, int | float)
    )

    return [c for c in claims if not any(rounds_to(c, value) for value in explainable)]
