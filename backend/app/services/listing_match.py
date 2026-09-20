"""Scoring one listing against what somebody asked for, and saying why.

Deterministic and pure, like `scoring.py` next door, and for the same reason:
what comes out of here is printed to a buyer in an email, so every word of it
has to be traceable to a comparison a person can check. Nothing here calls a
model. Nothing here reads `description`, `Public Remarks`, or any other free
text another brokerage wrote — the reason line is assembled from the checks and
only from the checks, which is what keeps "great schools" out of a sentence
nobody screened for it.

Components, out of 100, counted only over what could actually be compared:

    beds 30 · garage 25 · budget 20 · baths 15 · zone 10

"Could actually be compared" is the load-bearing half. A requirement the buyer
never stated, or a fact the export does not carry, scores NOTHING in either
direction and is reported as `unknown`. The alternative — reading a missing
`Garage Spaces` as a failed garage — ranks a house we know nothing about below
a house we know is wrong, which is backwards, and it happens constantly because
the column is blank on plenty of real rows.

Budget is scored and never gates. `api/v1/options.py` already documents why:
the figure a lead gives is routinely their savings rather than a price ceiling,
measured on a real lead whose $35,000 would have excluded every house in Denver.
A price outside the range costs points and says so; it never removes a listing
somebody might still want to see.

An office is never scored at all. The REcolorado Full export has no office or
den column — checked against the real 394-column header — so a study somebody
asked for comes back `unknown` and is printed as "not stated in the MLS". The
one thing this module must never do is let a requirement disappear quietly
because we had nowhere to check it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

MET = "met"
MISSED = "missed"
UNKNOWN = "unknown"

WEIGHTS = {"beds": 30, "garage": 25, "budget": 20, "baths": 15, "zone": 10}

#: The same headroom `match_properties_for_lead` allows, and for the same
#: reason: a ceiling somebody says out loud is a round number, not a limit.
BUDGET_HEADROOM = Decimal("1.10")
BUDGET_FLOOR = Decimal("0.90")


@dataclass(frozen=True)
class Check:
    """One comparison: what was asked, how it went, and the words for it."""

    key: str
    status: str
    detail: str


@dataclass(frozen=True)
class Requirement:
    """What the lead asked for, projected out of the row.

    A dataclass rather than the `Lead` itself so this module can be tested
    without a database and so a snapshot of it can be stored beside the request
    — the notice's arithmetic has to stay reproducible against what the agent
    was actually told, not drift when a later message changes the lead.
    """

    zone: str | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    beds_min: int | None = None
    baths_min: Decimal | None = None
    garage_min: int | None = None
    wants_office: bool | None = None

    @property
    def stated_anything(self) -> bool:
        return any(
            v is not None
            for v in (
                self.zone, self.budget_min, self.budget_max, self.beds_min,
                self.baths_min, self.garage_min, self.wants_office,
            )
        )


def _decimal(value: object) -> Decimal | None:
    """Anything numeric as a Decimal, or nothing. Never raises.

    `Property.price` is NUMERIC and arrives as a Decimal; a requirement may
    arrive as an int from JSON. Comparing the two directly is the crash this
    codebase has already paid for once.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out.is_finite() else None


def requirements_of(lead: object) -> Requirement:
    """Project a `Lead` into the shape this module compares against."""
    return Requirement(
        zone=getattr(lead, "zone", None),
        budget_min=_decimal(getattr(lead, "budget_min", None)),
        budget_max=_decimal(getattr(lead, "budget_max", None)),
        beds_min=getattr(lead, "beds_min", None),
        baths_min=_decimal(getattr(lead, "baths_min", None)),
        garage_min=getattr(lead, "garage_min", None),
        wants_office=getattr(lead, "wants_office", None),
    )


def _garage_spaces(prop: object) -> int | None:
    """How many cars fit in the garage, and never the driveway.

    `Parking Total` counts a pad. Somebody who asked for "a garage with space
    for two SUVs" did not ask for a pad, so reading one for the other would put
    a house with no garage on a shortlist under a line claiming it has one.
    """
    raw = getattr(prop, "raw", None)
    if not isinstance(raw, dict):
        return None
    value = raw.get("garage_spaces")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def score_property(prop: object, req: Requirement) -> tuple[int, list[Check]]:
    """`(score 0-100, checks)` for one listing. Pure — no database, no model.

    The score is the share of the WEIGHT THAT APPLIED, not of the total: a lead
    who only stated a zone is scored out of 10, not out of 100, so a perfect
    match on everything they said comes back as 100 rather than as 10.
    """
    checks: list[Check] = []
    earned = possible = 0

    # ── beds ────────────────────────────────────────────────────────────
    beds = getattr(prop, "bedrooms", None)
    if req.beds_min is None:
        pass
    elif beds is None:
        checks.append(Check("beds", UNKNOWN, "bedrooms not listed"))
    else:
        possible += WEIGHTS["beds"]
        if beds >= req.beds_min:
            earned += WEIGHTS["beds"]
            checks.append(Check("beds", MET, f"{beds} bd"))
        else:
            checks.append(
                Check("beds", MISSED, f"{beds} bd, you asked for {req.beds_min}+")
            )

    # ── baths ───────────────────────────────────────────────────────────
    baths = _decimal(getattr(prop, "bathrooms", None))
    if req.baths_min is None:
        pass
    elif baths is None:
        checks.append(Check("baths", UNKNOWN, "bathrooms not listed"))
    else:
        possible += WEIGHTS["baths"]
        shown = f"{baths.normalize():f}".rstrip(".")
        if baths >= req.baths_min:
            earned += WEIGHTS["baths"]
            checks.append(Check("baths", MET, f"{shown} ba"))
        else:
            asked = f"{req.baths_min.normalize():f}".rstrip(".")
            checks.append(Check("baths", MISSED, f"{shown} ba, you asked for {asked}+"))

    # ── garage ──────────────────────────────────────────────────────────
    spaces = _garage_spaces(prop)
    if req.garage_min is None:
        pass
    elif spaces is None:
        # Not a penalty. The column is blank on plenty of real rows, and that
        # is a fact about the export rather than about the house.
        checks.append(Check("garage", UNKNOWN, "garage not stated in the MLS"))
    else:
        possible += WEIGHTS["garage"]
        if spaces >= req.garage_min:
            earned += WEIGHTS["garage"]
            checks.append(Check("garage", MET, f"garage for {spaces}"))
        else:
            checks.append(
                Check(
                    "garage",
                    MISSED,
                    f"garage for {spaces}, you asked for {req.garage_min}",
                )
            )

    # ── budget ──────────────────────────────────────────────────────────
    price = _decimal(getattr(prop, "price", None))
    if req.budget_max is None and req.budget_min is None:
        pass
    elif price is None:
        checks.append(Check("budget", UNKNOWN, "no price listed"))
    else:
        possible += WEIGHTS["budget"]
        over = req.budget_max is not None and price > req.budget_max * BUDGET_HEADROOM
        under = req.budget_min is not None and price < req.budget_min * BUDGET_FLOOR
        if not over and not under:
            earned += WEIGHTS["budget"]
            ceiling = req.budget_max or req.budget_min
            checks.append(Check("budget", MET, f"within your {_money(ceiling)}"))
        elif over:
            checks.append(
                Check("budget", MISSED, f"{_money(price)}, over your {_money(req.budget_max)}")
            )
        else:
            checks.append(
                Check("budget", MISSED, f"{_money(price)}, under your {_money(req.budget_min)}")
            )

    # ── zone ────────────────────────────────────────────────────────────
    if req.zone:
        from app.services.listings import zone_matches  # noqa: PLC0415

        possible += WEIGHTS["zone"]
        where = getattr(prop, "zone", None)
        if where and zone_matches(req.zone, where):
            earned += WEIGHTS["zone"]
            checks.append(Check("zone", MET, f"in {where}"))
        else:
            checks.append(Check("zone", MISSED, f"in {where or 'an unnamed area'}"))

    # ── the office, never scored ─────────────────────────────────────────
    if req.wants_office:
        checks.append(Check("office", UNKNOWN, "office not stated in the MLS"))

    score = round(100 * earned / possible) if possible else 0
    return score, checks


def _money(value: Decimal | None) -> str:
    if value is None:
        return "budget"
    return f"${int(value):,}"


def reason_text(checks: list[Check]) -> str:
    """One sentence, built from the comparisons and from nothing else.

    What was met leads, because that is why this listing is on the list at all.
    What was missed follows, because a shortlist that hides its compromises
    sends somebody to a viewing to discover them. What could not be checked
    comes last and is named as unchecked — the whole point of carrying an
    unmatched requirement is to say so out loud.
    """
    met = [c.detail for c in checks if c.status == MET]
    missed = [c.detail for c in checks if c.status == MISSED]
    unknown = [c.detail for c in checks if c.status == UNKNOWN]

    parts: list[str] = []
    if met:
        parts.append(" · ".join(met))
    if missed:
        parts.append(" · ".join(missed))
    if unknown:
        parts.append(" · ".join(unknown))
    return " — ".join(parts)


def unmet_summary(checks_by_property: list[list[Check]], req: Requirement) -> list[str]:
    """What nothing on the list could satisfy. Requirement-level, not per house.

    Answers the only question worth asking before spending an MLS export: is
    the shortfall this zone, this price, or this garage?
    """
    if not checks_by_property:
        return _everything_asked(req)
    ever_met = {c.key for checks in checks_by_property for c in checks if c.status == MET}
    ever_seen = {c.key for checks in checks_by_property for c in checks}
    out: list[str] = []
    for key, label in (
        ("beds", f"{req.beds_min}+ bedrooms"),
        ("baths", "the bathrooms asked for"),
        ("garage", f"a garage for {req.garage_min}"),
        ("budget", "the budget"),
        ("zone", req.zone or "the area"),
    ):
        if key in ever_seen and key not in ever_met:
            out.append(f"nothing on this list has {label}")
    if req.wants_office:
        out.append("an office cannot be checked from the MLS export at all")
    return out


def _everything_asked(req: Requirement) -> list[str]:
    out = []
    if req.zone:
        out.append(f"nothing active in {req.zone}")
    if req.beds_min:
        out.append(f"nothing with {req.beds_min}+ bedrooms")
    if req.garage_min:
        out.append(f"nothing with a garage for {req.garage_min}")
    if req.wants_office:
        out.append("an office cannot be checked from the MLS export at all")
    return out or ["nothing active to compare against"]


def matrix_recipe(req: Requirement) -> str:
    """The search to run in Matrix, as a person would type it.

    Printed into the notice when the local inventory cannot fill a shortlist,
    because the alternative is an email that says "go and find some" and leaves
    somebody to reconstruct the criteria out of a conversation.

    The price line carries a caveat rather than a number we trust: the figure a
    lead states is often what they have saved, not what they will spend.
    """
    lines = ["In Matrix, search:"]
    lines.append(f"  Area:     {req.zone or '(the area they asked for)'}")
    if req.budget_max is not None:
        lines.append(
            f"  Price:    up to {_money(req.budget_max)}"
            "   — check this is a ceiling, not their savings"
        )
    if req.beds_min:
        lines.append(f"  Beds:     {req.beds_min}+")
    if req.baths_min is not None:
        lines.append(f"  Baths:    {f'{req.baths_min.normalize():f}'.rstrip('.')}+")
    if req.garage_min:
        lines.append(f"  Garage:   {req.garage_min}+ spaces")
    if req.wants_office:
        lines.append("  Interior: Study / Home Office  — the export has no column for it")
    lines.append("  Status:   Active")
    lines.append("  Export:   Full")
    return "\n".join(lines)
