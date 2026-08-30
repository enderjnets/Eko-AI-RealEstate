"""Print the Buffer channel ids for the configured organization.

Read-only: one GraphQL query, no mutation. Run it inside the container so the
token travels from `.env` into the process and never through a shell history,
a process list or this output:

    docker exec eko-realestate-backend python scripts/buffer_channels.py

The ids are not secrets — they name public channels and belong in `.env` as
`BUFFER_CHANNEL_*`. The token is, and is never printed.
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app")

from app.config import get_settings  # noqa: E402
from app.services.buffer_publisher import _CHANNELS, _graphql  # noqa: E402


async def main() -> int:
    s = get_settings()
    if not (s.BUFFER_ACCESS_TOKEN or "").strip():
        print("BUFFER_ACCESS_TOKEN is unset")
        return 1
    if not (s.BUFFER_ORG_ID or "").strip():
        print("BUFFER_ORG_ID is unset — set it to the organization that owns the channels")
        return 1

    payload = await _graphql(_CHANNELS, {"input": {"organizationId": s.BUFFER_ORG_ID}})
    if payload.get("errors"):
        for err in payload["errors"]:
            print("error:", err.get("message"))
        return 1

    channels = (payload.get("data") or {}).get("channels") or []
    if not channels:
        print("the organization has no channels")
        return 1
    for channel in channels:
        flags = []
        if channel.get("isDisconnected"):
            flags.append("DISCONNECTED")
        if channel.get("isLocked"):
            flags.append("LOCKED")
        print(
            f"{channel.get('service', '?'):<12} {channel.get('id', '?')}"
            + (f"  [{', '.join(flags)}]" if flags else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
