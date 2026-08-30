"""What is on screen while the narrator talks.

Kling first, Pexels behind it, and a plain branded card behind that. Three
levels because the first costs money, the second costs nothing but does not
always have the shot, and the third always works — a video with a flat card
under the words is a video, and a job that failed because a stock library had
no photo of a Denver street is not.

**The cache is at the point of PAYMENT, not at the point of use.** That
distinction is the whole reason it exists: the pipeline next door cached the
clip after generating it and paid twice for the same prompt, because the second
caller asked before the first had finished writing. Here the key is the prompt
itself and the check happens before the request.

**The daily cap is real money, shared.** That Kling package is one balance for
three projects on this machine. Going over does not degrade our video — it
takes down somebody else's publishing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import date
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_KLING_BASE = "https://api-singapore.klingai.com"
_TIMEOUT = 60.0
_POLL_SECONDS = 5
_POLL_ATTEMPTS = 24

# Vertical, because everything here is a short.
_ASPECT = "9:16"


class NoBalance(Exception):
    """Kling said 1102: the account is empty. Reported once a day and then
    degraded around — a paid service that stops working has to be visible even
    when the system survives without it, because the alternative is a channel
    that quietly changes its look for a week."""


def _cache_dir() -> Path:
    path = Path(
        os.environ.get("RENDER_CACHE_DIR", str(Path.home() / "eko-render" / "cache"))
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_key(prompt: str) -> str:
    return hashlib.sha256(prompt.strip().lower().encode("utf-8")).hexdigest()


def _ledger_path() -> Path:
    return _cache_dir() / "kling_usage.json"


def _spent_today() -> int:
    try:
        data = json.loads(_ledger_path().read_text())
    except (OSError, json.JSONDecodeError):
        return 0
    return int(data.get(date.today().isoformat(), 0))


def _charge(n: int = 1) -> None:
    today = date.today().isoformat()
    try:
        data = json.loads(_ledger_path().read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    data = {k: v for k, v in data.items() if k >= today}  # yesterday is history
    data[today] = int(data.get(today, 0)) + n
    _ledger_path().write_text(json.dumps(data))


def daily_cap() -> int:
    return int(os.environ.get("RENDER_KLING_IMAGES_PER_DAY", "8"))


def _kling_token() -> str | None:
    """A short-lived JWT from the access/secret pair, as Kling requires."""
    access = os.environ.get("KLING_ACCESS_KEY", "").strip()
    secret = os.environ.get("KLING_SECRET_KEY", "").strip()
    if not access or not secret:
        return None
    try:
        import jwt
    except ImportError:
        log.warning("PyJWT is not installed; Kling cannot be reached")
        return None
    now = int(time.time())
    return jwt.encode(
        {"iss": access, "exp": now + 1800, "nbf": now - 5},
        secret,
        algorithm="HS256",
        headers={"alg": "HS256", "typ": "JWT"},
    )


def _kling_image(prompt: str, destination: Path) -> bool:
    token = _kling_token()
    if token is None:
        return False

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        created = httpx.post(
            f"{_KLING_BASE}/v1/images/generations",
            headers=headers,
            json={"model_name": "kling-v1-5", "prompt": prompt, "aspect_ratio": _ASPECT, "n": 1},
            timeout=_TIMEOUT,
        )
        payload = created.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        log.warning("Kling did not answer (%s)", exc)
        return False

    if payload.get("code") == 1102:
        # Money, not code. Raised so the caller can report it exactly once a
        # day; every clip in a render would otherwise raise it seven times.
        raise NoBalance("Kling account balance is not enough (code 1102)")
    if payload.get("code") not in (0, None):
        log.warning("Kling refused: %s %s", payload.get("code"), payload.get("message"))
        return False

    task_id = (payload.get("data") or {}).get("task_id")
    if not task_id:
        return False

    # Charged HERE, at the point of payment — before the image exists and
    # whether or not the poll below succeeds. A ledger that only counts
    # finished images under-counts exactly the spend nobody wanted.
    _charge()

    for _ in range(_POLL_ATTEMPTS):
        time.sleep(_POLL_SECONDS)
        try:
            state = httpx.get(
                f"{_KLING_BASE}/v1/images/generations/{task_id}",
                headers=headers,
                timeout=_TIMEOUT,
            ).json()
        except (httpx.HTTPError, json.JSONDecodeError):
            continue
        data = state.get("data") or {}
        if data.get("task_status") == "succeed":
            images = (data.get("task_result") or {}).get("images") or []
            if not images:
                return False
            url = images[0].get("url")
            if not url:
                return False
            try:
                blob = httpx.get(url, timeout=_TIMEOUT)
                blob.raise_for_status()
                destination.write_bytes(blob.content)
                return True
            except httpx.HTTPError as exc:
                log.warning("Kling image could not be downloaded (%s)", exc)
                return False
        if data.get("task_status") == "failed":
            log.warning("Kling task failed: %s", data.get("task_status_msg"))
            return False
    log.warning("Kling did not finish within %ds", _POLL_SECONDS * _POLL_ATTEMPTS)
    return False


def _pexels(prompt: str, destination: Path) -> bool:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return False
    # Two or three words: a stock search takes a subject, not a sentence, and
    # sending the whole prompt reliably returns nothing.
    query = " ".join(prompt.split()[:3])
    try:
        resp = httpx.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": key},
            params={"query": query, "orientation": "portrait", "per_page": 1},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos") or []
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        log.warning("Pexels did not answer (%s)", exc)
        return False
    if not photos:
        return False
    photo = photos[0]
    # The photographer, for the log. Pexels does not require attribution in the
    # video, and a credit burned into a short is a credit nobody can read; the
    # record belongs somewhere a person can find it.
    log.info("Pexels: %s by %s", photo.get("url"), photo.get("photographer"))
    src = (photo.get("src") or {}).get("portrait") or (photo.get("src") or {}).get("large")
    if not src:
        return False
    try:
        blob = httpx.get(src, timeout=_TIMEOUT)
        blob.raise_for_status()
        destination.write_bytes(blob.content)
        return True
    except httpx.HTTPError:
        return False


def fetch(prompt: str, destination: Path) -> str:
    """An image for this prompt. Returns which provider gave it.

    `"none"` means neither did, and the caller draws a branded card instead —
    a plain frame under the words rather than a job that failed because a
    stock library had no photo of a street.
    """
    cached = _cache_dir() / f"{cache_key(prompt)}.jpg"
    if cached.is_file():
        destination.write_bytes(cached.read_bytes())
        return "cache"

    if _spent_today() < daily_cap():
        if _kling_image(prompt, destination):
            cached.write_bytes(destination.read_bytes())
            return "kling"
    else:
        log.info(
            "Kling daily cap reached (%d); this package is shared with two "
            "other projects, so going over would stop their publishing too",
            daily_cap(),
        )

    if _pexels(prompt, destination):
        # Not cached: stock results are free and change, and caching them would
        # freeze one photo onto a phrase for every future video.
        return "pexels"
    return "none"
