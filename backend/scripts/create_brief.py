#!/usr/bin/env python3
"""Create a partner brief and print the link to send.

A brief is the page we hand to the people we work with instead of an email
with a list at the bottom. This is the only way one gets made: there is no
screen for it, because writing a brief is an editorial act — somebody decides
what to ask and how to say it — and a form would only be a worse text editor.

Usage:
  docker compose exec backend python scripts/create_brief.py --list-orgs
  docker compose exec backend python scripts/create_brief.py \\
      --org 2 --title "Nine names and a listing" \\
      --recipient "Natalia and Robbie" --payload /tmp/brief.json

  # and to read the answers back without opening anything:
  docker compose exec backend python scripts/create_brief.py --show <token>

`--list-orgs` exists because getting this wrong is not a typo, it is handing
one agency's link to another. Organization 1 is a real client agency on this
install, not a placeholder — look before you pass a number.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.base import (  # noqa: E402
    dispose_engine,
    get_bypass_session_factory,
)
from app.models import Organization, PartnerBrief, new_token  # noqa: E402


async def _list_orgs() -> int:
    async with get_bypass_session_factory()() as db:
        rows = (
            await db.execute(select(Organization).order_by(Organization.id))
        ).scalars().all()
    if not rows:
        print("No organizations. Something is very wrong with this install.")
        return 1
    print(f"{'id':>4}  {'status':<12} name")
    for org in rows:
        print(f"{org.id:>4}  {getattr(org, 'status', '?'):<12} {org.name}")
    return 0


async def _show(token: str) -> int:
    async with get_bypass_session_factory()() as db:
        brief = (
            await db.execute(select(PartnerBrief).where(PartnerBrief.token == token))
        ).scalar_one_or_none()
    if brief is None:
        print("No brief with that token.")
        return 1
    print(f"title     {brief.title}")
    print(f"for       {brief.recipient}")
    print(f"org       {brief.org_id}")
    print(f"opened    {brief.opened_at or '— never'}")
    print(f"answered  {brief.answered_at or '— not yet'}")
    print()
    print(json.dumps(brief.answers or {}, indent=2, ensure_ascii=False))
    return 0


def _read_payload(path: str) -> dict | None:
    """The brief's content, or None after saying why.

    Sync, and called before the coroutine starts: a blocking read inside the
    event loop is the kind of thing that is harmless in a one-shot script and
    copied into something that is not.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read {path}: {exc}")
        return None


async def _create(args: argparse.Namespace, payload: dict) -> int:
    if not isinstance(payload, dict):
        print("The payload must be a JSON object — it is what the page renders.")
        return 1

    async with get_bypass_session_factory()() as db:
        org = await db.get(Organization, args.org)
        if org is None:
            print(f"No organization {args.org}. Run --list-orgs first.")
            return 1

        token = new_token()
        # `org_id` passed explicitly and not left to the flush hook: a bypass
        # session has no acting organization, so nothing stamps it. A row
        # inserted here without it would be rejected by the RLS WITH CHECK —
        # or, worse on an install where the owner is a superuser, inserted
        # with a NULL org nobody can read back.
        db.add(
            PartnerBrief(
                org_id=args.org,
                token=token,
                title=args.title,
                recipient=args.recipient,
                payload=payload,
                answers={},
            )
        )
        await db.commit()

    base = (get_settings().PANEL_URL or "").strip().rstrip("/")
    print(f"Created for organization {args.org} ({org.name}).")
    print()
    if base:
        print(f"  {base}/brief/{token}")
    else:
        print(f"  token: {token}")
        print("  (PANEL_URL is not set, so there is no address to build.)")
    print()
    print("That link is the credential. Anyone holding it can read the brief.")
    return 0


async def main() -> int:
    p = argparse.ArgumentParser(description="Create or read a partner brief.")
    p.add_argument("--list-orgs", action="store_true", help="who the orgs are")
    p.add_argument("--show", metavar="TOKEN", help="print a brief's answers")
    p.add_argument("--org", type=int, help="organization id the brief belongs to")
    p.add_argument("--title", help="shown in the panel and the notification")
    p.add_argument("--recipient", default="", help='e.g. "Natalia and Robbie"')
    p.add_argument("--payload", help="path to the JSON the page renders")
    args = p.parse_args()

    try:
        if args.list_orgs:
            return await _list_orgs()
        if args.show:
            return await _show(args.show)
        missing = [f for f in ("org", "title", "payload") if getattr(args, f) is None]
        if missing:
            p.error("missing: " + ", ".join("--" + f for f in missing))
        payload = _read_payload(args.payload)
        if payload is None:
            return 1
        return await _create(args, payload)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
