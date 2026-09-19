"""Reading a REcolorado Matrix "Full" export into `properties`.

This is what stands in for an MLS API, and the reason there is no API is worth
keeping in front of whoever reads this next. Natalia pays about $70 a month for
her REcolorado subscription. Matrix shows the allowance on the screen before
every download, and on 2026-09-19 it read:

    Records allowed per 30 days:   500
    Records exported thus far:       0
    Remaining allowance:           500

That allowance is hers. The penalty for abusing it — §12.4, up to $15,000 and
suspension — lands on her licence, not on this software. So every rule in this
module is about somebody else's livelihood, not about tidiness.

── The allow-list is the whole design ──────────────────────────────────────
The Full export carries **394 columns**. Ten of them are notes between brokers
about another firm's client, and they are populated in nearly every row:

    Private Remarks         9/10   "Seller is motivated, will take 3.75M."
    Showing Contact Phone  10/10
    List Agent Email       10/10
    Contract Min Earnest   10/10
    Exclusions             10/10
    Title Company           9/10
    Net Close Price         9/10

`COLUMNS` names what may be read. Everything else is dropped at the door, and
`raw` is built from named keys rather than from the row — because the obvious
shortcut, `raw=dict(row)`, would park the seller's floor price in our database
and leave nothing but a template between it and a consumer's inbox.

`Public Remarks` is excluded on purpose too. It is another brokerage's
marketing copy, and it is exactly where a listing agent writes "great schools",
which this product's own Fair Housing screen blocks on the email lane.

── The ceiling refuses, it does not truncate ───────────────────────────────
A file with more than `MAX_ROWS` rows is rejected whole. Truncating would be
worse than useless: it would quietly ingest the first 500 and hide the fact
that the export which produced the file had already spent more of the
allowance than it is allowed to hold in thirty days.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Property, PropertySource, PropertyStatus

log = logging.getLogger("app.listing_import")

__all__ = [
    "COLUMNS",
    "MAX_ROWS",
    "ExportRejected",
    "ImportReport",
    "import_export_csv",
    "parse_export",
]

#: REcolorado allows 500 records per 30 days on a Property export, read off
#: Matrix's own screen. A file bigger than this could not have been produced
#: within the allowance, so it is refused rather than partially read.
MAX_ROWS = 500

#: The allow-list: export header → what we do with it. Nothing outside this map
#: is read, and `raw` below is assembled from it rather than from the row.
COLUMNS = {
    "Listing Id": "external_id",
    "Standard Status": "status",
    "Mls Status": "mls_status",
    "Property Type": "property_type_group",
    "Property Sub Type": "property_type",
    "Street Number": "street_number",
    "Street Dir Prefix": "street_dir",
    "Street Name": "street_name",
    "Street Suffix": "street_suffix",
    "Unit Number": "unit_number",
    "City": "city",
    "State Or Province": "state",
    "Postal Code": "zip_code",
    "Subdivision Name": "zone",
    "List Price": "price",
    "Bedrooms Total": "bedrooms",
    "Bathrooms Total Integer": "bathrooms",
    "Living Area": "sqft",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Virtual Tour URL Unbranded": "url",
    "List Office Name": "list_office_name",
    "Originating System Name": "originating_system",
    "Listing Contract Date": "listed_at",
}


class ExportRejected(RuntimeError):
    """The file cannot be imported at all, and the message says why."""


@dataclass
class ImportReport:
    created: int = 0
    updated: int = 0
    #: Rows that carried no `Listing Id`. Counted rather than raised: one broken
    #: line must not cost the other 499.
    skipped: int = 0
    problems: list[str] = field(default_factory=list)


def _clean(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _decimal(value: object) -> Decimal | None:
    text = _clean(value).replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _int(value: object) -> int | None:
    number = _decimal(value)
    return int(number) if number is not None else None


def _date(value: object) -> datetime | None:
    """Matrix writes `09/18/2026 12:00:00 AM`, not ISO-8601.

    Returns None on anything else rather than guessing at the order of the
    numbers: a listing dated 3 December instead of 12 March is a fact about
    somebody's house that nothing downstream would question.
    """
    text = _clean(value)
    if not text:
        return None
    for shape in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, shape).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _address(row: dict[str, str]) -> str:
    """Street address including the unit, when there is one.

    The unit is not a detail here. Measured on the first real import that
    mattered — the eight listings in Washington Park a lead with $315,000 could
    actually buy — SIX of the eight were condos in two buildings: four at
    352/400 S Lafayette Street and two at 21 N Washington Street. Without the
    unit the email would have offered the same address twice and told somebody
    to go and look at a building.

    Empty on houses, where the export leaves the column blank, so nothing is
    appended and the line is unchanged.
    """
    parts = [
        _clean(row.get("street_number")),
        _clean(row.get("street_dir")),
        _clean(row.get("street_name")),
        _clean(row.get("street_suffix")),
    ]
    street = " ".join(p for p in parts if p)
    unit = _clean(row.get("unit_number"))
    if street and unit:
        return f"{street} Unit {unit}"
    return street


def _listing_type(row: dict[str, str]) -> str:
    """`sale` unless the export says otherwise.

    REcolorado files rentals under a Property Type of its own. Defaulting to
    sale is the safe direction here: `match_properties_for_lead` shows sales to
    everyone who is not a rent lead, so a mislabelled rental appears where a
    person can see it is wrong — while a mislabelled sale disappears from every
    search and looks like no inventory at all.
    """
    group = _clean(row.get("property_type_group")).lower()
    subtype = _clean(row.get("property_type")).lower()
    if "lease" in group or "rental" in group or "rent" in subtype:
        return "rent"
    return "sale"


def parse_export(text: str) -> tuple[list[dict], ImportReport]:
    """Read the CSV into rows this module understands. Raises `ExportRejected`.

    Only the columns in `COLUMNS` survive. The header is checked first, because
    a file that is not a Full export — a Single Line export, a spreadsheet
    somebody assembled by hand — should say so before anything is written,
    rather than producing four hundred listings with no price.
    """
    try:
        reader = csv.DictReader(io.StringIO(text))
        header = reader.fieldnames or []
    except csv.Error as exc:
        raise ExportRejected(f"this does not read as a CSV file: {exc}") from None

    if "Listing Id" not in header:
        raise ExportRejected(
            "no 'Listing Id' column. In Matrix this is the Full export: select "
            "the listings, press Export, and choose 'Full' as the file format."
        )
    missing = [
        name for name in ("List Price", "City", "Standard Status") if name not in header
    ]
    if missing:
        raise ExportRejected(
            f"missing columns: {', '.join(missing)}. That is not a Full export."
        )

    report = ImportReport()
    rows: list[dict] = []
    for raw_row in reader:
        if len(rows) >= MAX_ROWS:
            raise ExportRejected(
                f"more than {MAX_ROWS} listings in one file. REcolorado allows "
                f"{MAX_ROWS} records every 30 days on a Property export, so a "
                "larger file has already spent more of the allowance than it "
                "holds. Nothing was imported."
            )
        row = {
            field_name: _clean(raw_row.get(header_name))
            for header_name, field_name in COLUMNS.items()
        }
        if not row["external_id"]:
            report.skipped += 1
            continue
        rows.append(row)
    return rows, report


async def import_export_csv(text: str, db: AsyncSession) -> ImportReport:
    """Upsert a Full export into `properties`. Raises `ExportRejected`.

    Keyed on `(source, external_id)` like the feed is, so re-uploading the same
    search updates the rows it already created instead of doubling them — which
    matters, because the way this gets used is "export Wash Park again next
    Tuesday".
    """
    from app.services.listings import _map_status, _state_code

    rows, report = parse_export(text)

    existing = {}
    if rows:
        found = (
            await db.execute(
                select(Property).where(
                    Property.source == PropertySource.MLS,
                    Property.external_id.in_([r["external_id"] for r in rows]),
                )
            )
        ).scalars().all()
        existing = {p.external_id: p for p in found}

    for row in rows:
        address = _address(row)
        values = {
            "status": _map_status(row["status"]) or PropertyStatus.OFF_MARKET,
            # The title is built, never taken from the listing's own headline:
            # `Public Remarks` is another firm's copy and is not read at all.
            "title": address or row["external_id"],
            "description": None,
            "property_type": row["property_type"] or None,
            "address": address or None,
            "city": row["city"] or None,
            "state": _state_code(row["state"]),
            "zip_code": row["zip_code"] or None,
            "zone": row["zone"] or None,
            "latitude": _decimal(row["latitude"]),
            "longitude": _decimal(row["longitude"]),
            "price": _decimal(row["price"]),
            "bedrooms": _int(row["bedrooms"]),
            "bathrooms": _decimal(row["bathrooms"]),
            "sqft": _int(row["sqft"]),
            "url": row["url"] or None,
            # No photos, and not an oversight: the Full export carries a
            # `Photos Count` and not one media URL. Another Subscriber's listing
            # photographs are theirs, and we have no licence to reproduce them.
            "photos": [],
            "raw": {
                "list_office_name": row["list_office_name"] or None,
                "originating_system": row["originating_system"] or None,
                "mls_status": row["mls_status"] or None,
                "listing_type": _listing_type(row),
                "imported_at": datetime.now(UTC).isoformat(),
            },
            "listed_at": _date(row["listed_at"]),
        }
        current = existing.get(row["external_id"])
        if current is None:
            db.add(
                Property(
                    source=PropertySource.MLS, external_id=row["external_id"], **values
                )
            )
            report.created += 1
        else:
            for name, value in values.items():
                setattr(current, name, value)
            report.updated += 1

    await db.commit()
    log.info(
        "Listing import: %d created, %d updated, %d skipped",
        report.created, report.updated, report.skipped,
    )
    return report
