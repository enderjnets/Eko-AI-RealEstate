"""Real photos of the place, fetched once, checked, and made vertical.

The panel names, per shot, an approved Wikimedia Commons photo and the SHA-1 it
was approved with (`backend/app/services/place_photos.py`). This module turns
that into a file on this machine the engine can use as the shot's picture:

* **Fetched once.** Originals are kept in the cache under their SHA-1 and never
  fetched again. Commons answers a burst of downloads with 429 — measured on
  30-sep-2026 at the tenth file in a row — so the cache is seeded ahead of the
  first render and a download here is the exception, spaced and retried.
* **Checked.** A file whose SHA-1 is not the approved one is refused. Commons
  lets anyone upload a new version over a file; what Ender approved is the
  bytes he saw, not the name.
* **Vertical.** The engine crops every picture to 9:16 from its centre. A
  portrait photo survives that; a landscape one would lose two thirds of its
  width — the amphitheatre without its rocks. So a landscape photo is squared
  from its centre and laid across the frame over a blurred copy of itself,
  and only a portrait one is cropped to fill.

A photo that cannot be had is not a failed video: the shot keeps its drawn
picture, and the log says which photo and why.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger("worker.place_photos")

WIDTH, HEIGHT = 1080, 1920
#: Wikimedia asks every client to name itself and a way to reach its owner.
USER_AGENT = "DenverHomeStory-render/1.0 (https://www.denverhomestory.com/contact)"
ATTEMPTS = 4
BACKOFF_SECONDS = (10, 30, 90)
#: Narrower than this (width / height) is cropped; wider is laid over blur.
PORTRAIT_UP_TO = 0.75


class PhotoRefused(Exception):
    """This photo cannot be used for this video."""


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def original(url: str, sha1: str, cache: Path, *, sleep=time.sleep) -> Path:
    """The approved original, from the cache or from Commons."""
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / sha1
    if target.is_file():
        if _sha1(target) == sha1:
            return target
        target.unlink()
    partial = cache / f"{sha1}.part"
    last = ""
    for attempt in range(ATTEMPTS):
        if attempt:
            sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
        try:
            with httpx.stream(
                "GET", url, headers={"User-Agent": USER_AGENT},
                timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True,
            ) as resp:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = f"HTTP {resp.status_code}"
                    continue
                if resp.status_code != 200:
                    raise PhotoRefused(f"Commons answered {resp.status_code} for {url}")
                with partial.open("wb") as handle:
                    for chunk in resp.iter_bytes(1024 * 256):
                        handle.write(chunk)
        except httpx.TransportError as exc:
            last = str(exc)
            continue
        got = _sha1(partial)
        if got != sha1:
            partial.unlink(missing_ok=True)
            raise PhotoRefused(
                f"the file at {url} is not the one approved (SHA-1 {got}, approved {sha1})"
            )
        partial.replace(target)
        return target
    partial.unlink(missing_ok=True)
    raise PhotoRefused(f"could not fetch {url} after {ATTEMPTS} attempts ({last})")


def vertical(source: Path, sha1: str, cache: Path) -> Path:
    """A 1080x1920 JPEG of the photo, made once per photo."""
    from PIL import Image, ImageFilter, ImageOps

    # The largest approved original is 5304x7952; this refuses anything past
    # twice that rather than decoding it on a machine three projects share.
    Image.MAX_IMAGE_PIXELS = 90_000_000
    target = cache / f"{sha1}-{WIDTH}x{HEIGHT}.jpg"
    if target.is_file():
        return target
    with Image.open(source) as opened:
        picture = ImageOps.exif_transpose(opened).convert("RGB")
    if picture.width / picture.height <= PORTRAIT_UP_TO:
        frame = ImageOps.fit(picture, (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    else:
        frame = ImageOps.fit(picture, (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        frame = frame.filter(ImageFilter.GaussianBlur(40))
        frame = Image.eval(frame, lambda v: int(v * 0.55))
        # Squared from the centre first: laid whole, a 3:2 photo is a band a
        # third of the screen tall (seen on the twelve approved ones). Square,
        # it fills more than half and keeps its middle, where the place is.
        side = min(picture.width, picture.height)
        square = picture.crop((
            (picture.width - side) // 2, (picture.height - side) // 2,
            (picture.width + side) // 2, (picture.height + side) // 2,
        ))
        whole = ImageOps.contain(square, (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        frame.paste(whole, ((WIDTH - whole.width) // 2, (HEIGHT - whole.height) // 2))
    partial = cache / f"{sha1}-{WIDTH}x{HEIGHT}.part.jpg"
    frame.save(partial, "JPEG", quality=92)
    partial.replace(target)
    return target


def attach(spec: dict, cache: Path, *, sleep=time.sleep) -> dict:
    """The spec with `image` set on every shot whose photo could be had."""
    photos = spec.get("photos") or []
    plan = spec.get("scenes") if isinstance(spec.get("scenes"), dict) else None
    shots = plan.get("scenes") if plan else None
    if not photos or not isinstance(shots, list):
        return spec
    shots = [dict(shot) if isinstance(shot, dict) else shot for shot in shots]
    for photo in photos:
        scene = photo.get("scene")
        if not isinstance(scene, int) or not 0 <= scene < len(shots):
            log.warning("photo %s names shot %r, which this plan does not have", photo.get("id"), scene)
            continue
        if not isinstance(shots[scene], dict):
            continue
        try:
            path = vertical(
                original(str(photo["url"]), str(photo["sha1"]), cache, sleep=sleep),
                str(photo["sha1"]),
                cache,
            )
        except Exception as exc:  # noqa: BLE001 — a photo never stops a video
            log.warning(
                "photo %s for shot %d not used, the shot stays drawn: %s",
                photo.get("id"), scene, exc,
            )
            continue
        shots[scene]["image"] = str(path)
        log.info("shot %d shows photo %s", scene, photo.get("id"))
    return {**spec, "scenes": {**plan, "scenes": shots}}
