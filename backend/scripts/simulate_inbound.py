#!/usr/bin/env python3
"""Simulate an inbound WhatsApp message and POST it to the local webhook.

Usage:
  docker compose exec backend python scripts/simulate_inbound.py \\
      "+34666123456" "Hola, busco piso en alquiler en Malasaña por 1200€"

Defaults to localhost:8000 (the backend container listens on :8000 internally).
Useful for manual smoke testing of the orchestrator without setting up a real
Meta Business App.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid

import httpx


def build_payload(phone: str, text: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "SIMULATED_BUSINESS_ACCOUNT",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "16505551234",
                                "phone_number_id": "SIMULATED_PHONE_NUMBER_ID",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Simulated Lead"},
                                    "wa_id": phone,
                                }
                            ],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": f"wamid.SIM_{uuid.uuid4().hex[:12].upper()}",
                                    "timestamp": str(int(time.time())),
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("phone", help='e.g. "+34666123456"')
    p.add_argument("text", help="message body in Spanish")
    p.add_argument("--url", default="http://localhost:8000/api/v1/webhooks/whatsapp",
                   help="webhook URL (default: localhost:8000 — change for remote)")
    args = p.parse_args()

    payload = build_payload(args.phone, args.text)
    print(f"\n→ POST {args.url}")
    print(f"  from={args.phone}  text={args.text!r}\n")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(args.url, json=payload)

    print(f"← HTTP {resp.status_code}")
    try:
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except Exception:
        print(resp.text[:2000])

    return 0 if resp.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
