"""AUDIT-16 SCRATCH PROBE — delete after the round. Not part of the suite."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Lead
from app.services._common import ParsedMessage, clip_identifier

RAW = "z" * 260 + "@audit16.invalid"


def test_A_model_slices_phone_while_parse_digests_it() -> None:
    """The two normalisations of the SAME identity key disagree."""
    at_model = Lead(phone=RAW).phone
    at_parse = ParsedMessage(
        channel="email", external_id="a1", from_identifier=RAW,
        from_name=None, content="hi",
    ).from_identifier
    print(f"\nMODEL___={at_model[-50:]!r} len={len(at_model)}")
    print(f"PARSE___={at_parse[-50:]!r} len={len(at_parse)}")
    assert at_model != at_parse, "if these ever agree the finding is void"
    assert at_model == RAW[:254]          # plain slice, no digest
    assert at_parse == clip_identifier(RAW)


def test_B_model_merges_two_identities_that_parse_keeps_apart() -> None:
    a = "c" * 254 + "-alice@x.invalid"
    b = "c" * 254 + "-bob@x.invalid"
    assert Lead(phone=a).phone == Lead(phone=b).phone      # MERGED at the model
    assert clip_identifier(a) != clip_identifier(b)        # kept apart at parse


@pytest.mark.asyncio
async def test_C_lookup_and_write_disagree_in_postgres() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("no DATABASE_URL")
    engine = create_async_engine(url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as s:
            # what app/api/v1/leads.py:235 does
            s.add(Lead(phone=RAW))
            await s.commit()
            # what app/api/v1/leads.py:230 does on the NEXT request
            again = (
                await s.execute(select(Lead).where(Lead.phone == RAW))
            ).scalar_one_or_none()
            print(f"\nSECOND_REQUEST_FINDS_EXISTING_LEAD = {again!r}")
            assert again is None, "lookup by raw value must miss the sliced row"
            # so create_lead does NOT 409 and falls through to the insert:
            with pytest.raises(IntegrityError) as exc:
                s.add(Lead(phone=RAW))
                await s.flush()
            print(f"SECOND_INSERT_RAISES = {type(exc.value).__name__}")
            await s.rollback()
            row = (
                await s.execute(select(Lead).where(Lead.phone == RAW[:254]))
            ).scalar_one_or_none()
            if row is not None:
                await s.delete(row)
                await s.commit()
    finally:
        await engine.dispose()
