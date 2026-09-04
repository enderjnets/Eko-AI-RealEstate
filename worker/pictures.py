"""What is on screen while the narrator talks.

fal.ai first, Pexels behind it, and a plain branded card behind that. Three
levels because the first costs money, the second costs nothing but does not
always have the shot, and the third always works — a video with a flat card
under the words is a video, and a job that failed because a stock library had
no photo of a Denver street is not.

Kling is still here but only answers when fal.ai has no credential. Its own
account moved to a single API key and the pair this code signs a JWT with is
the scheme being retired; leaving the branch in costs nothing and keeps the
worker usable by the projects next door that still hold a pair.

**The cache is at the point of PAYMENT, not at the point of use.** That
distinction is the whole reason it exists: the pipeline next door cached the
clip after generating it and paid twice for the same prompt, because the second
caller asked before the first had finished writing. Here the key is the prompt
itself and the check happens before the request.

**The daily cap is real money, shared.** These accounts are one balance for
three projects on this machine. Going over does not degrade our video — it
takes down somebody else's publishing. The cap counts generated images, not
Kling images: which supplier drew them does not change whose money it was.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_KLING_BASE = "https://api-singapore.klingai.com"
_FAL_BASE = "https://fal.run"
_FAL_DEFAULT_MODEL = "fal-ai/flux/schnell"
# fal's name for 9:16. `_ASPECT` below is Kling's name for the same frame.
_FAL_SIZE = "portrait_16_9"
_TIMEOUT = 60.0
_POLL_SECONDS = 5
_POLL_ATTEMPTS = 24

# Vertical, because everything here is a short.
_ASPECT = "9:16"


class NoBalance(Exception):
    """The supplier says the account is empty — Kling with `1102`, fal.ai with
    an HTTP 403. Reported once a day and then
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
    """How many pictures may be paid for today.

    `RENDER_KLING_IMAGES_PER_DAY` is still read because it is what the render
    machines actually have in their environment; renaming a setting without
    reading the old name is how a cap silently becomes the default.
    """
    for name in ("RENDER_IMAGES_PER_DAY", "RENDER_KLING_IMAGES_PER_DAY"):
        raw = os.environ.get(name, "").strip()
        if raw:
            try:
                return int(raw)
            except ValueError:
                log.warning("%s is not a number; using the default", name)
                break
    return 8


def _fal_model() -> str:
    return os.environ.get("RENDER_FAL_MODEL", "").strip() or _FAL_DEFAULT_MODEL


def _fal_key() -> str | None:
    """The fal.ai credential, from the environment and nowhere else.

    An earlier draft also read `~/.config/fal/key`, where the CLI on these
    machines keeps it. That is one line of convenience and one real hazard:
    the developer machine has that file, so any test reaching `fetch` without
    stubbing this would have posted a paid request to fal.ai and passed. The
    worker takes every other credential from its environment; this one is not
    the exception.
    """
    return os.environ.get("FAL_KEY", "").strip() or None


def _fal_image(prompt: str, destination: Path) -> bool:
    """One generated picture from fal.ai.

    Synchronous, unlike Kling: `fal.run` answers with the finished image, so
    there is no task to poll.

    **The prompt has to reach the model in English.** That is not a style
    preference. The same request written in Spanish came back as a different
    animal entirely, with a success code on it — the failure mode is a wrong
    picture, not an error. Every `visual_prompt` this worker receives is
    written in English upstream, and this note is why it must stay that way.
    """
    key = _fal_key()
    if not key:
        return False

    # Charged HERE, at the point of payment, for the same reason Kling is:
    # a ledger that only counts finished images under-counts exactly the
    # spend nobody wanted.
    _charge()
    try:
        answer = httpx.post(
            f"{_FAL_BASE}/{_fal_model()}",
            headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
            json={"prompt": prompt, "image_size": _FAL_SIZE, "num_images": 1},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        log.warning("fal.ai could not be reached (%s)", exc)
        return False

    if answer.status_code == 403:
        # 403 and not 401: the credential is good and the account is empty.
        # Measured, not guessed — an expired key answers 401 here.
        raise NoBalance("fal.ai answered 403: the account has no balance")
    if answer.status_code >= 400:
        log.warning("fal.ai refused the request (HTTP %d)", answer.status_code)
        return False

    try:
        url = (answer.json().get("images") or [])[0]["url"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        log.warning("fal.ai answered without an image")
        return False
    try:
        blob = httpx.get(url, timeout=_TIMEOUT)
        blob.raise_for_status()
        destination.write_bytes(blob.content)
        return True
    except httpx.HTTPError as exc:
        log.warning("fal.ai image could not be downloaded (%s)", exc)
        return False


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


# Words that carry no subject. A stock search takes a SUBJECT, not a sentence —
# but the first version took the first three words of the prompt, and a prompt
# written in English starts with articles: "A set of residential house keys"
# was searched as "A set of", and the picture that came back was a stranger's
# branded cutlery box on a tablecloth, in a real estate video. Recognisable
# third-party trademarks are also the one thing the stock licences all refuse
# for commercial use, so an off-topic result is not merely ugly.
_NOISE = frozenset(
    """a an the and or of in on at to for with from by into over under
    this that these those is are was were be being been it its their
    some any new set piece kind sort""".split()
)


def search_terms(prompt: str, limit: int = 4) -> str:
    """The subject of a prompt, for a stock search.

    Content words in the order they were written, so "Denver" and "keys" reach
    the search and "a set of" does not. Falls back to the raw prompt when a
    sentence is nothing but noise, because a bad search still beats none.
    """
    words = [
        w
        for w in re.findall(r"[A-Za-z][A-Za-z'-]*", prompt)
        if w.lower() not in _NOISE
    ]
    return " ".join(words[:limit]) if words else prompt


def shows_people(description: str, people_words: list[str]) -> bool:
    """Does this photo's own description say there is a person in it?

    Whole words against the list the panel ships with every job — the same one
    that screens the prompts, so there is one vocabulary and not two drifting
    copies. Imperfect by construction: a library's alt text is written to sell
    the photo, not to answer this question, and a picture of somebody with no
    description at all sails through. It is a filter on the way to the human
    who approves every piece, not a replacement for them.
    """
    if not description or not people_words:
        return False
    words = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]*", description)}
    return any(
        term.lower() in words if " " not in term else term.lower() in description.lower()
        for term in people_words
    )


def _pexels(prompt: str, destination: Path, people_words: list[str] | None = None) -> bool:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return False
    query = search_terms(prompt)
    try:
        resp = httpx.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": key},
            # Several, so a photo full of people can be skipped for the next
            # one instead of losing the scene to a branded card.
            params={"query": query, "orientation": "portrait", "per_page": 8},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos") or []
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        log.warning("Pexels did not answer (%s)", exc)
        return False

    photo = next(
        (p for p in photos if not shows_people(p.get("alt") or "", people_words or [])),
        None,
    )
    if photo is None:
        if photos:
            log.info(
                "Pexels returned %d photos for %r and every one of them "
                "describes people; using a branded card instead",
                len(photos),
                query,
            )
        return False
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


def fetch(prompt: str, destination: Path, people_words: list[str] | None = None) -> str:
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
        if _fal_image(prompt, destination):
            cached.write_bytes(destination.read_bytes())
            return "fal"
        # Only when fal.ai was never asked. `_fal_image` charges the ledger
        # before it calls out, so trying Kling after a fal failure would bill
        # the day twice for one picture.
        if _fal_key() is None and _kling_image(prompt, destination):
            cached.write_bytes(destination.read_bytes())
            return "kling"
    else:
        log.info(
            "Daily image cap reached (%d); this balance is shared with two "
            "other projects, so going over would stop their publishing too",
            daily_cap(),
        )

    if _pexels(prompt, destination, people_words):
        # Not cached: stock results are free and change, and caching them would
        # freeze one photo onto a phrase for every future video.
        return "pexels"
    return "none"
