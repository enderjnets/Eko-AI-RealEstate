"""The content rail obeys the tenant boundary.

A new tenant table without an RLS policy is readable by every tenant, and the
mistake is invisible: every query in the application keeps working, and the
isolation tests that exist keep passing because they are about other tables.
So these tests are about these two tables specifically, and they check the
boundary in both directions — reading another agency's pieces, and writing into
another agency's pieces — because a policy with `USING` but no `WITH CHECK`
passes the first and fails the second.

The stakes are not abstract. A piece carries a client agency's unpublished
video, their script, and the name of the person who approved it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentPublication,
    ContentStatus,
    PublicationPlatform,
)
from app.services.tenant_context import org_scope

ORG_A = 1
ORG_B = 2

MARKER_A = "rail-isolation-org-a"
MARKER_B = "rail-isolation-org-b"


async def _seed(hook: str, org_id: int) -> int:
    """Insert past RLS, so both agencies have something to leak."""
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=org_id,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.NEEDS_APPROVAL,
            hook=hook,
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM content_pieces WHERE hook LIKE 'rail-isolation-%'")
        )
        await db.commit()


@pytest.mark.asyncio
async def test_a_piece_is_invisible_to_the_other_agency() -> None:
    await _seed(MARKER_A, ORG_A)
    b_id = await _seed(MARKER_B, ORG_B)
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                hooks = (
                    (
                        await db.execute(
                            select(ContentPiece.hook).where(
                                ContentPiece.hook.like("rail-isolation-%")
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
        assert hooks == [MARKER_A], (
            f"an unfiltered select reached across the tenant boundary: {hooks}"
        )

        # Naming the row directly, which is what an id in a URL amounts to.
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                stolen = await db.get(ContentPiece, b_id)
        assert stolen is None, "another agency's piece was readable by primary key"
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_piece_cannot_be_written_into_the_other_agency() -> None:
    """`USING` alone hides other agencies' rows but still lets you create one."""
    from sqlalchemy.exc import DBAPIError

    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                db.add(
                    ContentPiece(
                        org_id=ORG_B,
                        kind=ContentKind.GENERATED,
                        language=ContentLanguage.EN,
                        status=ContentStatus.DRAFT,
                        hook=MARKER_B,
                    )
                )
                with pytest.raises(DBAPIError):
                    await db.commit()

        async with get_bypass_session_factory()() as db:
            planted = (
                (
                    await db.execute(
                        select(ContentPiece.id).where(ContentPiece.hook == MARKER_B)
                    )
                )
                .scalars()
                .all()
            )
        assert planted == [], (
            "a piece was planted in another agency's account: WITH CHECK is "
            "missing from the policy"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_publication_is_invisible_to_the_other_agency() -> None:
    """The second table needs its own policy; the first one's does not cover it."""
    b_piece = await _seed(MARKER_B, ORG_B)
    async with get_bypass_session_factory()() as db:
        db.add(
            ContentPublication(
                org_id=ORG_B,
                piece_id=b_piece,
                platform=PublicationPlatform.YOUTUBE,
                external_id="yt-should-not-leak",
            )
        )
        await db.commit()
    try:
        with org_scope(ORG_A):
            async with get_session_factory()() as db:
                rows = (
                    (await db.execute(select(ContentPublication.external_id)))
                    .scalars()
                    .all()
                )
        assert "yt-should-not-leak" not in rows, (
            f"another agency's publication record was readable: {rows}"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_no_org_set_sees_nothing_rather_than_everything() -> None:
    """Default-deny. A forgotten scope must return an empty list, not the lot."""
    await _seed(MARKER_A, ORG_A)
    try:
        # Explicitly unset, not merely unscoped: the acting org lives in a
        # ContextVar that outlives the block that set it, so leaving the scope
        # off tests whatever the last caller happened to leave behind.
        with org_scope(None):
            async with get_session_factory()() as db:
                rows = (
                    (
                        await db.execute(
                            select(ContentPiece.hook).where(
                                ContentPiece.hook.like("rail-isolation-%")
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
        assert rows == [], (
            f"with no organization set the rail returned rows anyway: {rows}"
        )
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_publication_cannot_reference_another_agencys_piece() -> None:
    """The foreign key sees through what row security cannot.

    FK existence checks run with the referenced table's row security out of
    the picture, so a tenant that cannot READ a piece could still REFERENCE
    it — an existence oracle over another agency's id space, and a denial of
    service through UNIQUE (piece_id, platform): a foreign row occupying
    (piece, 'instagram') blocks the real owner from ever recording its own
    publication there. The composite FK makes the database itself refuse.
    """
    from sqlalchemy.exc import IntegrityError

    b_piece = await _seed(MARKER_B, ORG_B)
    try:
        async with get_bypass_session_factory()() as db:
            db.add(
                ContentPublication(
                    org_id=ORG_A,
                    piece_id=b_piece,
                    platform=PublicationPlatform.INSTAGRAM,
                )
            )
            with pytest.raises(IntegrityError):
                await db.commit()
            await db.rollback()

        async with get_bypass_session_factory()() as db:
            squatters = (
                (
                    await db.execute(
                        select(ContentPublication.id).where(
                            ContentPublication.piece_id == b_piece
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert squatters == [], (
            "a foreign publication row was planted on another agency's piece"
        )
    finally:
        await _cleanup()
