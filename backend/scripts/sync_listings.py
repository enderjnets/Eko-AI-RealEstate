#!/usr/bin/env python3
"""Ingest MLS/IDX listings into the local `properties` table.

In SIMULATED mode (dev default) this seeds the curated Miami dataset so the
`/properties` dashboard + per-lead matches look alive. With a real RESO Web API
feed configured (RESO_BASE_URL + RESO_ACCESS_TOKEN, LISTINGS_SIMULATED=false) it
pulls live listings. Idempotent — upserts by (source, external_id), safe to cron.

Usage:
  docker compose exec backend python scripts/sync_listings.py
  docker compose exec backend python scripts/sync_listings.py --city Miami
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Allow `python scripts/sync_listings.py` from the backend root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.base import dispose_engine, get_session_factory  # noqa: E402
from app.services.listings import sync_listings  # noqa: E402


async def main() -> int:
    p = argparse.ArgumentParser(description="Sync MLS/IDX listings into the DB.")
    p.add_argument("--city", default=None, help="filter to a city (e.g. Miami)")
    args = p.parse_args()

    Session = get_session_factory()
    try:
        async with Session() as session:
            result = await sync_listings(session, city=args.city)
        print(
            f"🏠 listings sync: created {result['created']}, updated {result['updated']} "
            f"(total {result['total']})"
        )
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
