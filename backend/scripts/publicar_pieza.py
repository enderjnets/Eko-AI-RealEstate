"""Upload, caption, date and (with the owner's written approval) approve a finished video.

The console does this by hand: upload as Finished video + Made with AI, paste the hook and
the caption, pick the date, submit, approve. When the owner is away from a computer he
approves in the chat with Claude instead, and Claude runs this inside the container:

    docker exec eko-realestate-backend python scripts/publicar_pieza.py \\
        --video /tmp/DANIELS-FISHER-TOWER.mp4 --sha256 7f83b2a6... \\
        --hook-file /tmp/hook.txt --caption-file /tmp/caption.txt --date 2026-11-04 \\
        --approve --approved-by "Ender in the chat, 2026-10-31 13:20: 'Aprobado'"

It goes through the same HTTP routes as the console (on localhost, inside the
container), so every gate the console has still applies: the content filter on
submit, the figures check on approve, the brokerage hold in the publisher. A
session token is minted for this run only (one hour) and never printed.

What it adds, because nobody is looking at a screen:
- the file must be the one the owner saw: `--sha256` of the copy sent to him;
- the caption must carry the brokerage line and the AI disclosure;
- `--approve` needs `--approved-by`, the owner's words and when he wrote them, which
  becomes the piece's `approved_by`. Without `--approve` the piece stops at
  needs_approval, for the console.
Exit code 0 only when every step it was asked to do succeeded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "/app")

BROKERAGE_MARKER = "independently owned and operated"
AI_MARKERS = ("ai-generated", "synthetic voice")
BASE = os.environ.get("PUBLICAR_BASE", "http://localhost:8000/api/v1/content")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def caption_problems(caption: str, generated: bool = True) -> list[str]:
    """What is missing from a caption before it may go out without a person reading it."""
    low = caption.lower()
    out = []
    if BROKERAGE_MARKER not in low:
        out.append("the caption has no brokerage line ('... independently owned and operated')")
    if generated and not any(m in low for m in AI_MARKERS):
        out.append("the caption does not say the video is AI-generated / uses a synthetic voice")
    return out


def approver_label(approved_by: str) -> str:
    """What `approved_by` will read: who approved, through what, in their words."""
    return ("chat: " + " ".join(approved_by.split()))[:255]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--sha256", required=True, help="sha256 of the copy the owner watched")
    ap.add_argument("--hook-file", required=True, type=Path)
    ap.add_argument("--caption-file", required=True, type=Path)
    ap.add_argument("--date", required=True, type=date.fromisoformat, help="publish date, YYYY-MM-DD")
    ap.add_argument("--language", default="en")
    ap.add_argument("--recorded", action="store_true", help="filmed by a person (not AI-generated)")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--approved-by", default="")
    ap.add_argument("--org-id", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="check everything, send nothing")
    a = ap.parse_args(argv)

    if not a.video.is_file():
        print(f"REFUSED: {a.video} does not exist")
        return 2
    got = sha256_of(a.video)
    if got != a.sha256.strip().lower() and not got.startswith(a.sha256.strip().lower()):
        print(f"REFUSED: the file is not the one the owner watched (sha256 {got[:16]}…, expected {a.sha256[:16]}…)")
        return 2
    if len(a.sha256.strip()) < 16:
        print("REFUSED: give at least 16 hex characters of the sha256")
        return 2
    hook = a.hook_file.read_text(encoding="utf-8").strip()
    caption = a.caption_file.read_text(encoding="utf-8").strip()
    if not hook or len(hook) > 300:
        print("REFUSED: the hook is empty or longer than 300 characters")
        return 2
    problems = caption_problems(caption, generated=not a.recorded)
    if problems:
        print("REFUSED: " + "; ".join(problems))
        return 2
    if a.approve and len(a.approved_by.strip()) < 8:
        print("REFUSED: --approve needs --approved-by with the owner's words and when he wrote them")
        return 2
    if a.date < date.today():
        print("REFUSED: the publish date is in the past")
        return 2
    if a.dry_run:
        print(json.dumps({"dry_run": True, "sha256": got[:16], "hook": hook[:80], "caption_chars": len(caption),
                          "date": a.date.isoformat(), "approve": a.approve}, ensure_ascii=False))
        return 0

    import httpx

    from app.models.organization import DEFAULT_ORG_ID
    from app.services.auth import ROLE_MEMBER, make_token

    who = approver_label(a.approved_by) if a.approve else "chat: Claude (upload only)"
    token = make_token(email=who, role=ROLE_MEMBER, ttl_hours=1, org_id=a.org_id or DEFAULT_ORG_ID)
    h = {"Authorization": f"Bearer {token}"}
    kind = "recorded" if a.recorded else "generated"
    with httpx.Client(base_url=BASE, headers=h, timeout=600) as c:
        def call(method: str, path: str, **kw):
            r = c.request(method, path, **kw)
            if r.status_code >= 400:
                raise SystemExit(f"FAILED {method} {path}: HTTP {r.status_code} {r.text[:400]}")
            return r.json()

        with a.video.open("rb") as f:
            piece = call("POST", "/upload", params={"filename": a.video.name, "language": a.language,
                                                    "kind": kind, "finished": "true"},
                         content=f, headers={"Content-Type": "application/octet-stream"})
        pid = piece["id"]
        print(f"uploaded: piece {pid}")
        call("PATCH", f"/{pid}", json={"hook": hook, "caption": caption})
        call("PUT", f"/{pid}/publish-date", json={"publish_date": a.date.isoformat()})
        piece = call("POST", f"/{pid}/submit")
        print(f"submitted: {piece['status']}")
        if a.approve:
            piece = call("POST", f"/{pid}/approve")
            print(f"approved: {piece['status']}")
    # the stored copy must still be the watched file
    from app.config import get_settings
    stored = Path(get_settings().CONTENT_MEDIA_DIR) / (piece.get("media_path") or "")
    ok = stored.is_file() and sha256_of(stored) == got
    print(json.dumps({"piece": pid, "status": piece["status"], "publish_date": piece.get("publish_window_start"),
                      "stored_sha256_matches": ok, "approved_by": who if a.approve else None}, ensure_ascii=False))
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
