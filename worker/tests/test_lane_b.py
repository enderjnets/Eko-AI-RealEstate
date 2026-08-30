"""Lane B on the worker side: the voice, the money, and the timing.

Three things are worth holding here, and none of them is ffmpeg:

* **Numbers become words.** A published short next door spent nine of its
  thirty-one seconds reading "$10,340" digit by digit. Denver Home Story says a
  price in nearly every video.
* **An image is paid for once.** The cache key is the prompt and the check
  happens BEFORE the request, because the pipeline next door cached after
  generating and paid twice for the same picture.
* **Scenes are cut to the voice**, not to a stopwatch. An even split puts a cut
  in the middle of a sentence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worker import pictures, produce, spoken, subtitles


# ── Numbers a narrator can read ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("written", "must_contain"),
    [
        ("Listing at $450,000 today.", "four hundred and fifty thousand dollars"),
        ("Rates moved 3.5% last month.", "three point five percent"),
        ("A $1.2M listing.", "one million"),
        ("Offers from $300k.", "three hundred thousand dollars"),
        ("It sold for $1 over asking.", "one dollar"),
        ("The 2nd offer was better.", "second"),
        ("About 1,200 square feet.", "one thousand"),
    ],
)
def test_a_number_is_spoken_not_spelled(written: str, must_contain: str) -> None:
    assert must_contain in spoken.for_the_voice(written)


def test_the_words_around_a_price_survive() -> None:
    """The first version ate the space after a number with no suffix and said
    "four hundred and fifty thousand dollarsand closing"."""
    said = spoken.for_the_voice("Listing at $450,000 and closing in 21 days.")
    assert "dollars and closing" in said


def test_a_year_stays_a_year() -> None:
    """"Two thousand and twenty six" for 2026 is worse than leaving it."""
    assert "2026" in spoken.for_the_voice("The market in 2026 is slower.")


def test_a_web_address_is_not_read_aloud() -> None:
    """It is burned into the end card and it is in the caption. Spoken, it is
    "denverhomestory dot com" at best."""
    said = spoken.for_the_voice("Start at denverhomestory.com today.")
    assert "denverhomestory" not in said
    assert "today" in said


# ── Paying once ──────────────────────────────────────────────────────────


def test_the_cache_key_is_the_prompt_itself(monkeypatch, tmp_path: Path) -> None:
    """Same picture asked for twice is the same key, whatever the casing."""
    assert pictures.cache_key("A Brick Bungalow ") == pictures.cache_key("a brick bungalow")
    assert pictures.cache_key("a brick bungalow") != pictures.cache_key("a stone cottage")


def test_a_cached_image_is_never_paid_for_again(
    monkeypatch, tmp_path: Path
) -> None:
    """The check is at the point of PAYMENT. Caching after generation is how
    the same prompt gets billed twice."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    prompt = "the Front Range at sunrise"
    (tmp_path / f"{pictures.cache_key(prompt)}.jpg").write_bytes(b"cached-bytes")

    def _must_not_be_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("a cached prompt reached a paid provider")

    monkeypatch.setattr(pictures, "_kling_image", _must_not_be_called)
    monkeypatch.setattr(pictures, "_pexels", _must_not_be_called)

    out = tmp_path / "out.jpg"
    assert pictures.fetch(prompt, out) == "cache"
    assert out.read_bytes() == b"cached-bytes"


def test_the_daily_cap_stops_spending_and_still_returns_a_video(
    monkeypatch, tmp_path: Path
) -> None:
    """The Kling package is one balance shared with two other projects on that
    machine. Going over does not degrade our video — it stops their
    publishing."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("RENDER_KLING_IMAGES_PER_DAY", "2")
    from datetime import date

    (tmp_path / "kling_usage.json").write_text(
        json.dumps({date.today().isoformat(): 2})
    )

    def _must_not_be_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("spent past the daily cap")

    monkeypatch.setattr(pictures, "_kling_image", _must_not_be_called)
    monkeypatch.setattr(pictures, "_pexels", lambda p, d: False)
    # No paid image, no stock image — and still an answer the caller can use.
    assert pictures.fetch("a house", tmp_path / "o.jpg") == "none"


def test_the_ledger_charges_before_the_image_exists(
    monkeypatch, tmp_path: Path
) -> None:
    """A ledger that only counts finished images under-counts exactly the
    spend nobody wanted: a request that was billed and then failed."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    pictures._charge()
    assert pictures._spent_today() == 1


def test_stock_photos_are_not_cached(monkeypatch, tmp_path: Path) -> None:
    """Caching a free result would freeze one photo onto a phrase for every
    future video."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(pictures, "_kling_image", lambda p, d: False)

    def _stock(prompt: str, destination: Path) -> bool:
        destination.write_bytes(b"stock")
        return True

    monkeypatch.setattr(pictures, "_pexels", _stock)
    out = tmp_path / "o.jpg"
    assert pictures.fetch("a house", out) == "pexels"
    assert not (tmp_path / f"{pictures.cache_key('a house')}.jpg").exists()


# ── Timing ───────────────────────────────────────────────────────────────


def test_scenes_are_cut_at_word_boundaries() -> None:
    """An even split puts a cut in the middle of a sentence; the eye notices
    that far more than an uneven scene length."""
    words = [subtitles.Word(i * 1.0, i * 1.0 + 0.9, f"w{i}") for i in range(8)]
    spans = produce.plan_shots([{}, {}], words, total=8.0)
    assert len(spans) == 2
    assert spans[0][0] == 0.0
    # Every boundary is a real word edge, not an arithmetic one.
    edges = {w.start for w in words} | {w.end for w in words} | {8.0}
    assert all(a in edges and b in edges for a, b in spans)


def test_the_last_scene_runs_to_the_end_of_the_audio() -> None:
    """Otherwise the end card is cut off by a word that finished early."""
    words = [subtitles.Word(0.0, 1.0, "a"), subtitles.Word(1.0, 2.0, "b")]
    spans = produce.plan_shots([{}, {}], words, total=9.0)
    assert spans[-1][1] == 9.0


def test_without_a_transcript_the_scenes_share_the_time_evenly() -> None:
    """A fallback, not a failure: no words means no boundaries to cut on."""
    spans = produce.plan_shots([{}, {}, {}], [], total=9.0)
    assert spans == [(0.0, 3.0), (3.0, 6.0), (6.0, 9.0)]


def test_a_piece_with_no_plan_is_refused_rather_than_improvised(
    tmp_path: Path,
) -> None:
    """Lane B has no clip to fall back on. Inventing one is not an option."""
    with pytest.raises(ValueError, match="no scene plan"):
        produce.produce({"scenes": None}, tmp_path, font=None, mark=None, music=None)
