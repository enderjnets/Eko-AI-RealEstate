"""The shots the panel names show the approved photo, and only the approved one.

Nothing here reaches Commons: the downloads are a fake `httpx.stream`.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from worker import config, finish, main, place_photos  # noqa: E402


def _cfg(tmp_path: Path, **more) -> config.Config:
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    agents = tmp_path / "agents"
    agents.mkdir(exist_ok=True)
    (agents / "render_externo.py").write_text("# stub\n", encoding="utf-8")
    return config.Config(
        api_base="https://panel.example", token="t" * 20, name="rog-test",
        hours=frozenset(), workdir=tmp_path / "work", poll_seconds=1,
        engine="bittrader", bittrader_python=python, bittrader_agents=agents,
        **more,
    )


def _jpeg(width: int, height: int, colour=(180, 70, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, "JPEG")
    return buf.getvalue()


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _spec(photos: list[dict], shots: int = 6) -> dict:
    return {
        "piece_id": 103,
        "scenes": {
            "narration": "Red Rocks.",
            "scenes": [
                {"visual_prompt": f"Red Rocks shot {i}", "on_screen_text": "Red Rocks"}
                for i in range(shots)
            ],
        },
        "photos": photos,
    }


class _Response:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status_code = status
        self._body = body

    def iter_bytes(self, _size):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _commons(monkeypatch, answers: list[_Response]) -> list[str]:
    asked: list[str] = []

    def _stream(method, url, **kw):
        asked.append(kw["headers"]["User-Agent"])
        return answers.pop(0)

    monkeypatch.setattr(place_photos.httpx, "stream", _stream)
    return asked


def test_a_cached_photo_goes_on_its_shot_and_nowhere_else(tmp_path: Path) -> None:
    data = _jpeg(1200, 1800)
    (tmp_path / _sha1(data)).write_bytes(data)
    spec = _spec([{"scene": 0, "id": "R3", "url": "https://upload.wikimedia.org/a.jpg",
                   "sha1": _sha1(data)}])
    out = place_photos.attach(spec, tmp_path)
    shots = out["scenes"]["scenes"]
    assert Image.open(shots[0]["image"]).size == (1080, 1920)
    assert all("image" not in shot for shot in shots[1:])
    # The panel's plan is not edited in place.
    assert "image" not in spec["scenes"]["scenes"][0]


def test_a_landscape_photo_is_kept_whole_not_cropped_to_a_sliver(tmp_path: Path) -> None:
    data = _jpeg(3600, 2400, colour=(250, 250, 250))
    (tmp_path / _sha1(data)).write_bytes(data)
    out = place_photos.attach(
        _spec([{"scene": 2, "id": "R5", "url": "u", "sha1": _sha1(data)}]), tmp_path
    )
    frame = Image.open(out["scenes"]["scenes"][2]["image"]).convert("RGB")
    assert frame.size == (1080, 1920)
    # Squared from its centre and laid across the middle, full width and 1080
    # tall; above it is the darkened blur, not more photo.
    assert frame.getpixel((540, 960)) > (240, 240, 240)
    assert frame.getpixel((540, 430)) > (240, 240, 240)
    assert frame.getpixel((540, 40)) < (160, 160, 160)
    assert frame.getpixel((540, 1880)) < (160, 160, 160)


def test_a_nearly_portrait_photo_is_not_squared(tmp_path: Path) -> None:
    """R3 is 3400x4310: wider than the cut-off, taller than wide. Squared, it
    lost the top of the rocks; laid whole it keeps them."""
    picture = Image.new("RGB", (340, 431), (250, 250, 250))
    picture.paste((0, 0, 0), (0, 0, 340, 20))
    buf = io.BytesIO()
    picture.save(buf, "JPEG")
    data = buf.getvalue()
    (tmp_path / _sha1(data)).write_bytes(data)
    out = place_photos.attach(
        _spec([{"scene": 0, "id": "R3", "url": "u", "sha1": _sha1(data)}]), tmp_path
    )
    frame = Image.open(out["scenes"]["scenes"][0]["image"]).convert("RGB")
    # The black strip at the very top of the photo is still in the frame.
    top = (1920 - round(1080 * 431 / 340)) // 2
    assert frame.getpixel((540, top + 5)) < (60, 60, 60)


def test_a_cache_made_by_an_older_rule_is_not_served(tmp_path: Path) -> None:
    data = _jpeg(1200, 1800)
    (tmp_path / _sha1(data)).write_bytes(data)
    stale = tmp_path / f"{_sha1(data)}-1080x1920.jpg"
    stale.write_bytes(b"made by the first rule")
    out = place_photos.attach(
        _spec([{"scene": 0, "id": "R3", "url": "u", "sha1": _sha1(data)}]), tmp_path
    )
    assert Path(out["scenes"]["scenes"][0]["image"]) != stale


def test_a_file_that_is_not_the_approved_one_is_refused(monkeypatch, tmp_path: Path) -> None:
    approved = _jpeg(1200, 1800)
    replaced = _jpeg(1200, 1800, colour=(0, 0, 255))
    _commons(monkeypatch, [_Response(200, replaced)])
    out = place_photos.attach(
        _spec([{"scene": 0, "id": "R3", "url": "u", "sha1": _sha1(approved)}]), tmp_path,
        sleep=lambda s: None,
    )
    assert "image" not in out["scenes"]["scenes"][0]
    assert not any(tmp_path.iterdir())


def test_commons_saying_slow_down_is_waited_out(monkeypatch, tmp_path: Path) -> None:
    data = _jpeg(1200, 1800)
    asked = _commons(monkeypatch, [_Response(429), _Response(200, data)])
    waited: list[float] = []
    out = place_photos.attach(
        _spec([{"scene": 5, "id": "R9", "url": "u", "sha1": _sha1(data)}]), tmp_path,
        sleep=waited.append,
    )
    assert out["scenes"]["scenes"][5]["image"]
    assert waited == [10]
    assert all("denverhomestory.com" in ua for ua in asked)
    assert (tmp_path / _sha1(data)).read_bytes() == data


def test_a_photo_that_never_arrives_leaves_the_shot_drawn(monkeypatch, tmp_path: Path) -> None:
    _commons(monkeypatch, [_Response(503)] * place_photos.ATTEMPTS)
    out = place_photos.attach(
        _spec([{"scene": 0, "id": "R3", "url": "u", "sha1": "0" * 40}]), tmp_path,
        sleep=lambda s: None,
    )
    assert "image" not in out["scenes"]["scenes"][0]


def test_a_shot_the_plan_does_not_have_is_skipped(tmp_path: Path) -> None:
    out = place_photos.attach(
        _spec([{"scene": 9, "id": "R3", "url": "u", "sha1": "0" * 40}], shots=3), tmp_path
    )
    assert all("image" not in shot for shot in out["scenes"]["scenes"])


def test_no_photos_is_the_spec_as_it_was(tmp_path: Path) -> None:
    spec = _spec([])
    assert place_photos.attach(spec, tmp_path) is spec
    legacy = {"scenes": {"scenes": [{"visual_prompt": "x"}]}}
    assert place_photos.attach(legacy, tmp_path) is legacy


def test_the_engine_receives_the_photo_path(monkeypatch, tmp_path: Path) -> None:
    data = _jpeg(1200, 1800)
    cache = tmp_path / "places"
    cache.mkdir()
    (cache / _sha1(data)).write_bytes(data)
    seen: dict = {}

    def _engine(spec, workdir, *, cfg, report=None):
        seen["spec"] = spec
        video = Path(workdir) / "video.mp4"
        video.write_bytes(b"x")
        return video

    monkeypatch.setattr(main.produce_bittrader, "produce", _engine)
    monkeypatch.setattr(main.verify, "check", lambda *a, **k: None)
    monkeypatch.setattr(main.finish, "validate", lambda spec: None)
    monkeypatch.setattr(
        main.finish, "apply",
        lambda video, destination, **kw: (
            destination.write_bytes(b"f"),
            finish.FinishReport(duration=25.0, used_calculator=False),
        )[1],
    )
    cfg = _cfg(tmp_path, photo_cache=cache)
    main.do_produce_job(
        cfg, {"id": 11, "kind": "produce_b"},
        _spec([{"scene": 0, "id": "R3", "url": "u", "sha1": _sha1(data)}]),
    )
    image = seen["spec"]["scenes"]["scenes"][0]["image"]
    assert Path(image).parent == cache
