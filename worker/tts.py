"""The narrator.

MiniMax's text-to-speech, with edge-tts behind it. The order is not a
preference between two equals: the first costs characters and sounds like a
person, the second is free and sounds like a screen reader, and a video with a
mechanical voice is still a video while a video with no voice is not one.

The script is put through `spoken.for_the_voice` before it gets here — see that
module for the published short that spent nine of its thirty-one seconds
reading a price digit by digit.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_MINIMAX_URL = "https://api.minimax.io/v1/t2a_v2"
_MODEL = "speech-02-turbo"
_TIMEOUT = 120.0


class NoVoice(Exception):
    """Nothing could narrate this. The job fails rather than shipping silence:
    a short built for a voice, delivered mute, is not the same video with a
    missing feature — it is a different, worse video nobody asked for."""


def _minimax(text: str, destination: Path) -> bool:
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    group = os.environ.get("MINIMAX_GROUP_ID", "").strip()
    voice = os.environ.get("RENDER_TTS_VOICE_ID", "").strip()
    if not key or not group or not voice:
        log.info("MiniMax narration is not configured; falling back")
        return False

    try:
        resp = httpx.post(
            _MINIMAX_URL,
            params={"GroupId": group},
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _MODEL,
                "text": text,
                "stream": False,
                "voice_setting": {"voice_id": voice, "speed": 1.0, "vol": 1.0},
                # 44.1k mono: it is a voice over music, not music.
                "audio_setting": {
                    "sample_rate": 44100,
                    "format": "mp3",
                    "channel": 1,
                },
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        log.warning("MiniMax narration failed (%s); falling back", exc)
        return False

    # Their API answers 200 with the failure inside, like most of the ones this
    # project talks to. "The request succeeded" and "there is audio" are
    # different questions.
    status = (payload.get("base_resp") or {}).get("status_code")
    hexed = (payload.get("data") or {}).get("audio")
    if status not in (0, None) or not hexed:
        log.warning(
            "MiniMax returned no audio (status=%s); falling back", status
        )
        return False

    try:
        destination.write_bytes(bytes.fromhex(hexed))
    except ValueError:
        log.warning("MiniMax returned audio that is not hex; falling back")
        return False
    return destination.stat().st_size > 0


def _edge(text: str, destination: Path) -> bool:
    """The free fallback. No key, no quota, and it sounds like it."""
    voice = os.environ.get("RENDER_TTS_EDGE_VOICE", "en-US-JennyNeural")
    try:
        subprocess.run(
            ["edge-tts", "--voice", voice, "--text", text, "--write-media", str(destination)],
            check=True,
            capture_output=True,
            timeout=300,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        log.warning("edge-tts failed (%s)", exc)
        return False
    return destination.is_file() and destination.stat().st_size > 0


def narrate(text: str, destination: Path) -> Path:
    """Speak `text` into `destination`, or raise `NoVoice`."""
    if not text.strip():
        raise NoVoice("there is nothing to read")
    if _minimax(text, destination) or _edge(text, destination):
        return destination
    raise NoVoice("no narration provider produced audio")
