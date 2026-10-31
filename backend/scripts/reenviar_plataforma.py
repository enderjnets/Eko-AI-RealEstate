"""Send a published piece again to one platform where it failed, at a slot the owner chose.

The publisher never does this on its own: a FAILED row on a published piece is a
verdict, and it only completes platforms a piece never reached within seven days.
On 31-oct-2026 that left nine legends that TikTok had blocked as "potential spam"
at 08:30 (the same videos went out fine at 17:30) with no way back short of
uploading each one again, which would post it twice on Instagram and YouTube.

    docker exec eko-realestate-backend python scripts/reenviar_plataforma.py \\
        --piece 129 --platform tiktok --at "2026-11-01 19:30" \\
        --approved-by "Ender in the chat, 2026-10-31: 'aprobado'"

Refuses unless: the piece is PUBLISHED, that platform's row is FAILED, the time is
in the future, it is one of the platform's configured slots, and the slot is free.
On success the row becomes SCHEDULED with the new Buffer post; the reconciler
takes it from there exactly as for any other scheduled post.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

sys.path.insert(0, "/app")


def parse_at(raw: str) -> tuple[datetime, str]:
    """'YYYY-MM-DD HH:MM' in the agency's local time; returns the naive instant and HH:MM."""
    when = datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M")
    return when, when.strftime("%H:%M")


async def run(a: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.db.base import dispose_engine, get_session_factory
    from app.models.content import (
        ContentPiece,
        ContentPublication,
        ContentStatus,
        PublicationPlatform,
        PublicationStatus,
    )
    from app.models.organization import DEFAULT_ORG_ID
    from app.services import buffer_publisher as bp
    from app.services.tenant_context import org_scope

    platform = PublicationPlatform(a.platform)
    local, hhmm = parse_at(a.at)
    try:
        with org_scope(a.org_id or DEFAULT_ORG_ID):
            async with get_session_factory()() as db:
                piece = await db.get(ContentPiece, a.piece)
                if piece is None or piece.status is not ContentStatus.PUBLISHED:
                    print(f"REFUSED: piece {a.piece} is not published")
                    return 2
                row = (await db.execute(select(ContentPublication).where(
                    ContentPublication.piece_id == piece.id,
                    ContentPublication.platform == platform))).scalar_one_or_none()
                if row is None or row.status is not PublicationStatus.FAILED:
                    print(f"REFUSED: piece {a.piece} has no failed {platform.value} post to send again")
                    return 2
                channel_id = bp.channels_for(piece).get(platform)
                if not channel_id:
                    print(f"REFUSED: piece {a.piece} does not go to {platform.value}")
                    return 2
                zone = await bp.agency_zone(db)
                if zone is None:
                    print("REFUSED: the agency timezone is unusable")
                    return 2
                due_at = local.replace(tzinfo=zone).astimezone(UTC)
                if due_at <= datetime.now(UTC):
                    print("REFUSED: that time has passed")
                    return 2
                slots = [s.strftime("%H:%M") for s in bp._slots_for(platform)]
                if hhmm not in slots:
                    print(f"REFUSED: {hhmm} is not a {platform.value} slot ({', '.join(slots)})")
                    return 2
                free = [s.strftime("%H:%M") for s in await bp._free_slots(db, platform, local.date(), zone)]
                if hhmm not in free:
                    print(f"REFUSED: {platform.value} {local.date()} {hhmm} is taken (free: {', '.join(free) or 'none'})")
                    return 2
                old = row.external_id
                if a.dry_run:
                    print(json.dumps({"dry_run": True, "piece": piece.id, "platform": platform.value,
                                      "at": due_at.isoformat(), "old_post": old}))
                    return 0
                external_id = await bp._send(piece, platform, channel_id, due_at)
                row.external_id = external_id
                row.status = PublicationStatus.SCHEDULED
                row.scheduled_at = due_at
                row.published_at = None
                row.external_url = None
                row.last_error = None
                await db.commit()
                print(json.dumps({"piece": piece.id, "platform": platform.value, "scheduled_at": due_at.isoformat(),
                                  "post": external_id, "old_post": old,
                                  "approved_by": " ".join(a.approved_by.split())[:255]}, ensure_ascii=False))
                return 0
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--piece", required=True, type=int)
    ap.add_argument("--platform", required=True, choices=["tiktok", "instagram", "youtube"])
    ap.add_argument("--at", required=True, help="local time, 'YYYY-MM-DD HH:MM'")
    ap.add_argument("--approved-by", default="")
    ap.add_argument("--org-id", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        parse_at(a.at)
    except ValueError:
        print("REFUSED: --at must be 'YYYY-MM-DD HH:MM'")
        return 2
    if not a.dry_run and len(a.approved_by.strip()) < 8:
        print("REFUSED: needs --approved-by with the owner's words and when he wrote them")
        return 2
    return asyncio.run(run(a))


if __name__ == "__main__":
    raise SystemExit(main())
