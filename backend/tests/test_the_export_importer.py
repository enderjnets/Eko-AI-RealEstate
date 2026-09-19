"""Reading a Matrix Full export, and the two things it must never do.

The fixture beside this file has the **real 394-column header** and **invented
rows**. That split is deliberate: the header is the shape the importer has to
survive and a shape is not somebody's listing, while the values in a real export
belong to other Subscribers and would be sitting in this repository for ever.

The confidential columns are present in the fixture, filled with sentinels. An
allow-list cannot be tested by a file that never contained what it is supposed
to keep out — that test would pass against an importer with no allow-list at all.
"""
from __future__ import annotations

import os
import pathlib

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory
from app.models import Property, PropertySource, PropertyStatus
from app.services.listing_import import (
    COLUMNS,
    MAX_ROWS,
    ExportRejected,
    import_export_csv,
    parse_export,
)
from app.services.tenant_context import set_org_id

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "recolorado_full_sample.csv"
CONFIDENTIAL = (
    "CONFIDENTIAL-private-remarks",
    "CONFIDENTIAL-showing-phone",
    "CONFIDENTIAL-agent-email",
    "CONFIDENTIAL-earnest",
    "CONFIDENTIAL-exclusions",
    "CONFIDENTIAL-title",
    "CONFIDENTIAL-net-close",
)


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


@pytest.fixture
def export_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM properties WHERE external_id LIKE 'TEST%'")
        )
        await db.commit()


def test_the_fixture_still_looks_like_a_full_export(export_text: str) -> None:
    """If this fails, the fixture has drifted and every test below proves less.

    394 is what Matrix produced on 2026-09-19 with `Export file format: Full`.
    The number is pinned because a fixture quietly trimmed to the columns we
    happen to read would make the allow-list untestable.
    """
    header = export_text.splitlines()[0].split(",")
    assert len(header) == 394
    for name in COLUMNS:
        assert name in export_text.splitlines()[0], f"{name} is gone from the header"
    for sentinel in CONFIDENTIAL:
        assert sentinel in export_text, (
            f"{sentinel} is not in the fixture, so nothing here proves it is "
            "kept out of the database"
        )


def test_only_the_named_columns_are_read(export_text: str) -> None:
    rows, report = parse_export(export_text)
    assert len(rows) == 2
    assert report.skipped == 1, "the row with no Listing Id is counted, not raised on"

    for row in rows:
        blob = "|".join(str(v) for v in row.values())
        for sentinel in CONFIDENTIAL:
            assert sentinel not in blob, f"{sentinel} survived the allow-list"
        assert "great schools" not in blob, "Public Remarks is not read at all"


def test_a_single_line_export_is_refused_before_anything_is_written() -> None:
    """The most likely mistake, and it has to fail loudly.

    Matrix's default is "Single Line", which has no `Listing Id` column and no
    price. Read leniently it would produce a screenful of listings with nothing
    in them, and the person who uploaded it would have no idea why.
    """
    with pytest.raises(ExportRejected) as caught:
        parse_export("MLS #,Address,Price\n1234,100 S Nowhere St,725000\n")
    assert "Full" in str(caught.value)

    # And each half of the header check on its own, because a file can be
    # wrong in one way at a time. Without this, removing either check leaves
    # the other one catching the sample above and the test stays green — which
    # is how a guard-of-two becomes a guard-of-one without anybody noticing.
    with pytest.raises(ExportRejected) as no_id:
        parse_export("List Price,City,Standard Status\n725000,Denver,Active\n")
    assert "Listing Id" in str(no_id.value)

    with pytest.raises(ExportRejected) as no_price:
        parse_export("Listing Id,Subdivision Name\nTEST9999,Washington Park\n")
    assert "List Price" in str(no_price.value)


def test_a_file_over_the_allowance_is_refused_whole() -> None:
    """Refused, not truncated — and that is the whole point of the number.

    REcolorado allows 500 Property records every 30 days. A file with more than
    that could not have been produced inside the allowance, so importing the
    first 500 would quietly bless an export that had already gone past it.
    """
    header = "Listing Id,List Price,City,Standard Status\n"
    body = "".join(f"X{i},100000,Denver,Active\n" for i in range(MAX_ROWS + 1))
    with pytest.raises(ExportRejected) as caught:
        parse_export(header + body)
    assert str(MAX_ROWS) in str(caught.value)

    # And exactly at the ceiling it is fine: an off-by-one here would refuse a
    # legitimate maximum export, which is the file somebody worked hardest for.
    exact = "".join(f"X{i},100000,Denver,Active\n" for i in range(MAX_ROWS))
    rows, _ = parse_export(header + exact)
    assert len(rows) == MAX_ROWS


@pytest.mark.asyncio
async def test_an_export_becomes_listings_with_their_broker(
    database_url: str, export_text: str
) -> None:
    set_org_id(1)
    try:
        async with get_bypass_session_factory()() as db:
            report = await import_export_csv(export_text, db)
        assert (report.created, report.updated, report.skipped) == (2, 0, 1)

        async with get_bypass_session_factory()() as db:
            row = (
                await db.execute(
                    select(Property).where(Property.external_id == "TEST0001")
                )
            ).scalar_one()

        assert row.source == PropertySource.MLS
        assert row.status == PropertyStatus.ACTIVE
        assert row.address == "100 S Nowhere Street"  # a house: no unit to add
        assert row.city == "Denver"
        # "Colorado" is what the export writes; the column takes two characters,
        # and storing "Co" would be two letters of a longer word.
        assert row.state == "CO"
        assert row.zone == "Washington Park"
        assert int(row.price) == 725000
        assert row.bedrooms == 3
        assert row.sqft == 1840
        assert row.url == "https://tour.invalid/one"
        # Rule 6.10.A.4 — without this the listing cannot lawfully be shown to
        # anybody, so it is part of the import and not of the template.
        assert row.raw["list_office_name"] == "Fictional Brokerage LLC"
        assert row.raw["listing_type"] == "sale"
        # No media URLs exist in a Full export. An empty list is the honest
        # answer; a placeholder image would be a claim about the house.
        assert row.photos == []
        assert row.listed_at is not None and row.listed_at.year == 2026

        blob = f"{row.title}|{row.description}|{row.raw}|{row.address}"
        for sentinel in CONFIDENTIAL:
            assert sentinel not in blob
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_uploading_the_same_search_again_updates_rather_than_doubles(
    database_url: str, export_text: str
) -> None:
    """The way this actually gets used is "export Wash Park again next Tuesday"."""
    set_org_id(1)
    try:
        async with get_bypass_session_factory()() as db:
            first = await import_export_csv(export_text, db)
        async with get_bypass_session_factory()() as db:
            second = await import_export_csv(export_text, db)

        assert first.created == 2 and first.updated == 0
        assert second.created == 0 and second.updated == 2

        async with get_bypass_session_factory()() as db:
            total = (
                await db.execute(
                    select(Property).where(Property.external_id.like("TEST%"))
                )
            ).scalars().all()
        assert len(total) == 2
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_condo_keeps_its_unit_number(
    database_url: str, export_text: str
) -> None:
    """Found on the first import that mattered, with real data.

    The eight Washington Park listings a lead with $315,000 could actually buy
    were six condos in two buildings — four at 352/400 S Lafayette Street and
    two at 21 N Washington Street. Dropping `Unit Number` made four of them read
    as two addresses, and would have sent somebody to look at a building.
    """
    set_org_id(1)
    try:
        async with get_bypass_session_factory()() as db:
            await import_export_csv(export_text, db)
            row = (
                await db.execute(
                    select(Property).where(Property.external_id == "TEST0002")
                )
            ).scalar_one()
        assert row.address == "205 Invented Avenue Unit 504"
        assert row.title == "205 Invented Avenue Unit 504"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_price_with_a_comma_still_arrives_as_a_number(
    database_url: str, export_text: str
) -> None:
    """Matrix writes `410,000` in some columns and `410000` in others."""
    set_org_id(1)
    try:
        async with get_bypass_session_factory()() as db:
            await import_export_csv(export_text, db)
            row = (
                await db.execute(
                    select(Property).where(Property.external_id == "TEST0002")
                )
            ).scalar_one()
        assert int(row.price) == 410000
    finally:
        await _cleanup()


# ──────────────────────────────────────────────────────────────────────────
# The route — who may upload, and when nobody may
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_panel_can_upload_an_export(database_url: str) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/properties/import",
                files={"file": ("export.csv", FIXTURE.read_bytes(), "text/csv")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["created"] == 2
        assert body["skipped"] == 1
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_second_agency_closes_the_upload_instead_of_sharing_it(
    database_url: str,
) -> None:
    """`properties` has no `org_id`, and this is the honest consequence.

    The table is shared on purpose — there is one REcolorado feed — which is
    fine with one agency and becomes a cross-tenant write with two: agency B
    would see, and overwrite, listings agency A exported under A's own licence.
    So the route refuses rather than documenting the hazard and hoping. Giving
    `properties` an `org_id` is what lifts this.

    The org added here is a THIRD one, because every install already carries two
    rows: the client agency and a seeded `Demo`. The first version of this guard
    counted both and refused every upload on an ordinary single-agency install —
    which is why the demo tenant is excluded by id rather than by hoping nobody
    seeds one.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.models import Organization

    async with get_bypass_session_factory()() as db:
        extra = Organization(name="Second Agency (test)", slug=f"second-{os.getpid()}")
        db.add(extra)
        await db.commit()
        extra_id = int(extra.id)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/properties/import",
                files={"file": ("export.csv", FIXTURE.read_bytes(), "text/csv")},
            )
        assert resp.status_code == 409, resp.text
        assert "org_id" in resp.text

        async with get_bypass_session_factory()() as db:
            landed = (
                await db.execute(
                    select(Property).where(Property.external_id.like("TEST%"))
                )
            ).scalars().all()
        assert landed == [], "nothing may be written when the boundary is in doubt"
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("DELETE FROM organizations WHERE id = :i"), {"i": extra_id}
            )
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_an_oversized_upload_is_refused_before_it_is_parsed(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ceiling on bytes is not the ceiling on rows, and both have to exist.

    `MAX_ROWS` is about somebody's MLS allowance; this one is about the server's
    memory, and it has to fire before the file is decoded — otherwise the refusal
    happens after the cost it was meant to avoid.
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.v1 import properties as properties_api
    from app.main import app

    monkeypatch.setattr(properties_api, "MAX_UPLOAD_BYTES", 128)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/properties/import",
                files={"file": ("big.csv", b"x" * 4096, "text/csv")},
            )
        assert resp.status_code == 413, resp.text
    finally:
        await _cleanup()
