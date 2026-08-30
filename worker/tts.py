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

# The channel's voice, chosen by the owner on 30-Aug from four variants of the
# same reading. `English_CalmWoman` at 1.06 with the "happy" emotion: warm
# without sounding like an advertisement, which matters because the landing
# page promises "fifteen minutes, no pitch" and a salesman's delivery would
# contradict the product in the first three seconds.
#
# The speed is not decoration. Emotion alone stretched the same script from
# 15.5s to 17.9s — nearly three extra seconds in a format where people leave —
# and 1.06 gives the whole thing back while keeping the expression.
DEFAULT_VOICE = "English_CalmWoman"
DEFAULT_SPEED = 1.06
DEFAULT_EMOTION = "happy"


class NoVoice(Exception):
    """Nothing could narrate this. The job fails rather than shipping silence:
    a short built for a voice, delivered mute, is not the same video with a
    missing feature — it is a different, worse video nobody asked for."""


def _voice_setting(voice: str) -> dict[str, object]:
    """How the channel sounds. Overridable, so a second agency is not stuck
    with this one's choice."""
    setting: dict[str, object] = {
        "voice_id": voice,
        "speed": float(os.environ.get("RENDER_TTS_SPEED", DEFAULT_SPEED)),
        "vol": 1.0,
    }
    emotion = os.environ.get("RENDER_TTS_EMOTION", DEFAULT_EMOTION).strip()
    if emotion:
        setting["emotion"] = emotion
    return setting


def _minimax(text: str, destination: Path) -> bool:
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    voice = os.environ.get("RENDER_TTS_VOICE_ID", "").strip() or DEFAULT_VOICE
    if not key:
        log.info("MiniMax narration is not configured; falling back")
        return False

    # `GroupId` was mandatory on the older keys and is not on the current ones,
    # which authenticate on the bearer token alone — measured against the live
    # API with this account's key, which has no group. Requiring it made the
    # narrator refuse before it ever tried, and the video would have fallen
    # through to the free fallback voice with nothing in the log but "not
    # configured". Sent when it is set, omitted when it is not.
    group = os.environ.get("MINIMAX_GROUP_ID", "").strip()
    params = {"GroupId": group} if group else None

    try:
        resp = httpx.post(
            _MINIMAX_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _MODEL,
                "text": text,
                "stream": False,
                "voice_setting": _voice_setting(voice),
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
