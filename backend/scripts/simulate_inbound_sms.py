#!/usr/bin/env python3
"""Simulate an inbound Twilio SMS and POST it to the local webhook.

Usage:
  docker compose exec backend python scripts/simulate_inbound_sms.py \\
      "+13055550123" "Hi, looking for a 2BR condo in Brickell under 800k"

Posts a Twilio-style form payload. With SMS_SIMULATED=true (dev default) the
webhook accepts it unsigned and the reply is logged instead of sent.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

import httpx


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("phone", help='sender, e.g. "+13055550123"')
    p.add_argument("text", help="message body")
    p.add_argument("--to", default="+13055559999", help="your Twilio number")
    p.add_argument("--url", default="http://localhost:8000/api/v1/webhooks/sms")
    args = p.parse_args()

    form = {
        "MessageSid": f"SM{uuid.uuid4().hex[:16].upper()}",
        "AccountSid": "ACSIMULATED",
        "From": args.phone,
        "To": args.to,
        "Body": args.text,
    }
    print(f"\n→ POST {args.url}\n  from={args.phone} body={args.text!r}\n")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(args.url, data=form)
    print(f"← HTTP {resp.status_code}\n{resp.text[:500]}")
    return 0 if resp.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
