#!/usr/bin/env python3
"""Send due nurture follow-ups once (post-visit sequence + visit reminders).

The backend already runs this in-process on an interval (FOLLOWUPS_ENABLED), but
this CLI lets you run it from cron instead (set FOLLOWUPS_ENABLED=false) or
trigger a manual pass.

Usage:
  docker compose exec backend python scripts/run_followups.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.base import dispose_engine  # noqa: E402
from app.services.followups import process_due_followups  # noqa: E402


async def main() -> int:
    from app.services.tenant_context import run_for_every_org

    totals = {"sent": 0, "skipped": 0, "failed": 0}

    async def _one_org(session) -> None:
        result = await process_due_followups(session)
        for key in totals:
            totals[key] += result[key]

    try:
        # Per organization. A cron run with no org bound sees zero rows under
        # default-deny RLS and reports success having sent nothing.
        await run_for_every_org(_one_org)
        result = totals
        print(f"📨 follow-ups: sent={result['sent']} skipped={result['skipped']} failed={result['failed']}")
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
