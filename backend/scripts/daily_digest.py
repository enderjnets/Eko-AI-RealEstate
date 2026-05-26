#!/usr/bin/env python3
"""Print the daily 'hot leads' digest — top leads to follow up on, by score.

Recomputes all scores first (cheap, no LLM), then prints the warm/hot leads
ranked. Designed for a host cron; the output can be piped to email/Telegram
later. Excludes closed (won/lost) and paused leads.

Usage:
  docker compose exec backend python scripts/daily_digest.py
  docker compose exec backend python scripts/daily_digest.py --limit 10
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.db.base import dispose_engine, get_session_factory  # noqa: E402
from app.models import Lead, LeadStatus  # noqa: E402
from app.services.scoring import rescore_all, score_tier  # noqa: E402

_TIER_ICON = {"hot": "🔥", "warm": "🟡", "cold": "⚪"}


async def main() -> int:
    p = argparse.ArgumentParser(description="Daily hot-leads digest.")
    p.add_argument("--limit", type=int, default=5)
    args = p.parse_args()

    Session = get_session_factory()
    try:
        async with Session() as session:
            await rescore_all(session)
            rows = (
                await session.execute(
                    select(Lead)
                    .where(
                        Lead.status.notin_([LeadStatus.WON, LeadStatus.LOST, LeadStatus.PAUSED]),
                        Lead.score > 0,
                    )
                    .order_by(Lead.score.desc(), Lead.last_message_at.desc().nullslast())
                    .limit(args.limit)
                )
            ).scalars().all()

        print(f"\n🔔 Leads calientes — top {len(rows)}\n" + "─" * 44)
        if not rows:
            print("(sin leads activos con score > 0)")
        for r in rows:
            icon = _TIER_ICON.get(score_tier(r.score), "⚪")
            zone = r.zone or "?"
            print(f"{icon} {r.score:>3}  {r.name or r.phone:<24} {r.status.value:<11} {zone}")
        print()
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
