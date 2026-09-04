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
        # The WORD, not just the letter. "$1.2 million" is the commonest
        # written form of a seven-figure price and it came out as "one point
        # two DOLLARS million" — the same shape as the "$70B" -> "seventy
        # thousand million" bug recorded next door. Testing only "$1.2M"
        # blessed the broken form.
        ("The median hit $1.2 million.", "one million, two hundred thousand dollars"),
        ("$5 million homes are rare.", "five million dollars"),
        ("A $1.5 Million listing.", "one million, five hundred thousand dollars"),
        ("Rare above $1 billion.", "one billion dollars"),
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


def test_the_cache_key_is_the_prompt_itself() -> None:
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

    monkeypatch.setattr(pictures, "_kling_image", _never)
    monkeypatch.setattr(pictures, "_pexels", lambda p, d, w=None: False)
    # No paid image, no stock image — and still an answer the caller can use.
    assert pictures.fetch("a house", tmp_path / "o.jpg") == "none"


def test_the_ledger_charges_a_request_that_then_fails(
    monkeypatch, tmp_path: Path
) -> None:
    """A ledger that only counts finished images under-counts exactly the
    spend nobody wanted: a request that was billed and then failed.

    The earlier version of this test called `_charge()` by hand and asserted
    the counter, so moving the charge to after a successful download — which
    re-creates the under-count it names — left it green. It has to go through
    the real path: a task Kling accepted and then never delivered.
    """
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KLING_ACCESS_KEY", "ak")
    monkeypatch.setenv("KLING_SECRET_KEY", "sk")
    pytest.importorskip("jwt")

    class _Created:
        def json(self):
            return {"code": 0, "data": {"task_id": "t-1"}}

    class _Polled:
        def json(self):
            return {"data": {"task_status": "failed", "task_status_msg": "nope"}}

    monkeypatch.setattr(pictures.httpx, "post", lambda *a, **k: _Created())
    monkeypatch.setattr(pictures.httpx, "get", lambda *a, **k: _Polled())
    monkeypatch.setattr(pictures.time, "sleep", lambda _s: None)

    assert pictures._kling_image("a house", tmp_path / "o.jpg") is False
    # Accepted, billed, and no image. The money left the account either way.
    assert pictures._spent_today() == 1


def test_a_refusal_is_not_charged(monkeypatch, tmp_path: Path) -> None:
    """The other side of the same line: a request Kling never accepted costs
    nothing, and counting it would make the cap stop work that was free."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KLING_ACCESS_KEY", "ak")
    monkeypatch.setenv("KLING_SECRET_KEY", "sk")
    pytest.importorskip("jwt")

    class _Refused:
        def json(self):
            return {"code": 1200, "message": "bad prompt"}

    monkeypatch.setattr(pictures.httpx, "post", lambda *a, **k: _Refused())
    assert pictures._kling_image("a house", tmp_path / "o.jpg") is False
    assert pictures._spent_today() == 0


def test_stock_photos_are_not_cached(monkeypatch, tmp_path: Path) -> None:
    """Caching a free result would freeze one photo onto a phrase for every
    future video."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(pictures, "_kling_image", lambda p, d: False)

    def _stock(prompt: str, destination: Path, people_words=None) -> bool:
        destination.write_bytes(b"stock")
        return True

    monkeypatch.setattr(pictures, "_pexels", _stock)
    out = tmp_path / "o.jpg"
    assert pictures.fetch("a house", out) == "pexels"
    assert not (tmp_path / f"{pictures.cache_key('a house')}.jpg").exists()


def _never(*args, **kwargs):  # pragma: no cover - the assertion is that it is not run
    raise AssertionError("this supplier should not have been asked")


# ── The generated picture ────────────────────────────────────────────────
#
# fal.ai answers `fal.run` synchronously, so unlike Kling there is nothing to
# poll. What these hold is the money and the order: which supplier is asked,
# who gets charged, and what an empty account looks like from outside.


class _FalAnswer:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None

    @property
    def content(self) -> bytes:
        return b"jpeg"


def test_fal_is_asked_first_and_kling_is_never_reached(
    monkeypatch, tmp_path: Path
) -> None:
    """The order is the decision. Kling's account moved to a single API key
    and the pair this code signs a JWT with is the scheme being retired."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FAL_KEY", "id:secret")
    monkeypatch.setattr(pictures, "_kling_image", _never)

    def _drew(prompt: str, destination: Path) -> bool:
        destination.write_bytes(b"generated")
        return True

    monkeypatch.setattr(pictures, "_fal_image", _drew)
    out = tmp_path / "o.jpg"
    assert pictures.fetch("a house", out) == "fal"
    # Generated pictures ARE cached: this one cost money, unlike stock.
    assert (tmp_path / f"{pictures.cache_key('a house')}.jpg").exists()


def test_without_a_key_nothing_is_sent_to_fal(monkeypatch, tmp_path: Path) -> None:
    """The guard that keeps a test suite from buying pictures. The developer
    machine has a fal credential in `~/.config/fal/key`; reading it here would
    have made every unstubbed test a paid request that passed."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(pictures.httpx, "post", _never)

    assert pictures._fal_image("a house", tmp_path / "o.jpg") is False
    assert pictures._spent_today() == 0


def test_kling_answers_only_when_fal_has_no_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("FAL_KEY", raising=False)

    def _drew(prompt: str, destination: Path) -> bool:
        destination.write_bytes(b"kling")
        return True

    monkeypatch.setattr(pictures, "_kling_image", _drew)
    assert pictures.fetch("a house", tmp_path / "o.jpg") == "kling"


def test_a_fal_failure_does_not_then_bill_kling_for_the_same_picture(
    monkeypatch, tmp_path: Path
) -> None:
    """`_fal_image` charges the ledger before it calls out. Falling through to
    Kling after it failed would put two charges behind one image."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FAL_KEY", "id:secret")
    monkeypatch.setattr(pictures, "_fal_image", lambda p, d: False)
    monkeypatch.setattr(pictures, "_kling_image", _never)
    monkeypatch.setattr(pictures, "_pexels", lambda p, d, w=None: False)

    assert pictures.fetch("a house", tmp_path / "o.jpg") == "none"


def test_an_empty_fal_account_is_loud_but_does_not_stop_the_video(
    monkeypatch, tmp_path: Path
) -> None:
    """403, not 401: the credential is good and the balance is gone, measured
    on the live account.

    It must NOT raise. `NoBalance` unwinds out of `fetch` without reaching
    Pexels, so an empty account would give every scene a blank card, the guard
    in `produce.py` would fail the whole job, and the retry would buy the
    narration again — the incident this supplier was brought in to end.
    """
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FAL_KEY", "id:secret")
    monkeypatch.setattr(pictures.httpx, "post", lambda *a, **k: _FalAnswer(403))

    assert pictures._fal_image("a house", tmp_path / "o.jpg") is False
    # The day is spent, so nothing asks an empty account a second time.
    assert pictures._spent_today() >= pictures.daily_cap()


def test_after_a_403_the_day_asks_nobody_and_stock_carries_the_video(
    monkeypatch, tmp_path: Path
) -> None:
    """One 403 per day, not one per scene — and the video still comes out."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FAL_KEY", "id:secret")
    monkeypatch.setattr(pictures.httpx, "post", lambda *a, **k: _FalAnswer(403))
    assert pictures._fal_image("a house", tmp_path / "first.jpg") is False

    monkeypatch.setattr(pictures.httpx, "post", _never)

    def _stock(prompt: str, destination: Path, people_words=None) -> bool:
        destination.write_bytes(b"stock")
        return True

    monkeypatch.setattr(pictures, "_pexels", _stock)
    assert pictures.fetch("a barn", tmp_path / "second.jpg") == "pexels"


def test_a_request_fal_refused_costs_nothing(monkeypatch, tmp_path: Path) -> None:
    """The same line the Kling path draws: a request the supplier never
    accepted costs nothing, and counting it would let a ten-minute outage
    spend the whole day's cap and quietly drop the rest to stock."""
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FAL_KEY", "id:secret")
    monkeypatch.setattr(pictures.httpx, "post", lambda *a, **k: _FalAnswer(500))

    assert pictures._fal_image("a house", tmp_path / "o.jpg") is False
    assert pictures._spent_today() == 0


def test_an_accepted_request_is_charged_once(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FAL_KEY", "id:secret")
    monkeypatch.setattr(
        pictures.httpx,
        "post",
        lambda *a, **k: _FalAnswer(200, {"images": [{"url": "https://x/y.jpg"}]}),
    )
    monkeypatch.setattr(pictures.httpx, "get", lambda *a, **k: _FalAnswer(200))

    assert pictures._fal_image("a house", tmp_path / "o.jpg") is True
    assert pictures._spent_today() == 1


def test_an_answer_without_an_image_is_not_a_crash(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RENDER_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("FAL_KEY", "id:secret")
    monkeypatch.setattr(
        pictures.httpx, "post", lambda *a, **k: _FalAnswer(200, {"images": []})
    )
    assert pictures._fal_image("a house", tmp_path / "o.jpg") is False


def test_the_cap_still_answers_to_the_name_the_machines_have(monkeypatch) -> None:
    """Renaming a setting without reading the old name is how a cap silently
    becomes the default. The render machines have the Kling-era name."""
    monkeypatch.delenv("RENDER_IMAGES_PER_DAY", raising=False)
    monkeypatch.setenv("RENDER_KLING_IMAGES_PER_DAY", "3")
    assert pictures.daily_cap() == 3

    monkeypatch.setenv("RENDER_IMAGES_PER_DAY", "11")
    assert pictures.daily_cap() == 11

    monkeypatch.setenv("RENDER_IMAGES_PER_DAY", "not a number")
    assert pictures.daily_cap() == 8


# ── The narrator ─────────────────────────────────────────────────────────


def test_a_key_without_a_group_still_narrates(monkeypatch, tmp_path) -> None:
    """Measured against the live API, not assumed: the current MiniMax keys
    authenticate on the bearer token alone.

    Requiring `MINIMAX_GROUP_ID` made the narrator refuse before it ever tried,
    and the video fell through to the free fallback voice with nothing in the
    log but "not configured" — a silent downgrade of the thing the audience
    hears most.
    """
    from worker import tts

    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test")
    monkeypatch.setenv("RENDER_TTS_VOICE_ID", "English_CalmWoman")
    monkeypatch.delenv("MINIMAX_GROUP_ID", raising=False)

    seen: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"base_resp": {"status_code": 0}, "data": {"audio": "00ff"}}

    def _post(url, **kwargs):
        seen.update(kwargs)
        return _Resp()

    monkeypatch.setattr(tts.httpx, "post", _post)
    assert tts._minimax("hello", tmp_path / "v.mp3") is True
    # And no empty GroupId is sent along, which their API rejects.
    assert seen["params"] is None


def test_a_key_with_a_group_still_sends_it(monkeypatch, tmp_path) -> None:
    """An older account that does need one is not broken by the fix."""
    from worker import tts

    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test")
    monkeypatch.setenv("RENDER_TTS_VOICE_ID", "English_CalmWoman")
    monkeypatch.setenv("MINIMAX_GROUP_ID", "12345")

    seen: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"base_resp": {"status_code": 0}, "data": {"audio": "00ff"}}

    monkeypatch.setattr(tts.httpx, "post", lambda url, **kw: (seen.update(kw), _Resp())[1])
    assert tts._minimax("hello", tmp_path / "v.mp3") is True
    assert seen["params"] == {"GroupId": "12345"}


def test_a_200_with_a_failure_inside_is_not_audio(monkeypatch, tmp_path) -> None:
    """Their API answers 200 and puts the refusal in the body, like most of
    the ones this project talks to."""
    from worker import tts

    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test")
    monkeypatch.setenv("RENDER_TTS_VOICE_ID", "English_CalmWoman")

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"base_resp": {"status_code": 1004, "status_msg": "bad voice"}}

    monkeypatch.setattr(tts.httpx, "post", lambda url, **kw: _Resp())
    assert tts._minimax("hello", tmp_path / "v.mp3") is False


# ── Lo que devuelve el banco de fotos ────────────────────────────────────


def test_the_search_uses_the_subject_not_the_first_three_words() -> None:
    """"A set of residential house keys" was searched as "A set of".

    English sentences start with articles, so taking the first three words
    searched for nothing at all — and the picture that came back was a
    stranger's branded cutlery box, in a real estate video. Recognisable
    third-party trademarks are also the one thing every stock licence refuses
    for commercial use, so an off-topic result is not merely ugly.
    """
    assert pictures.search_terms("A set of residential house keys") == (
        "residential house keys"
    )
    assert pictures.search_terms("A for-sale sign in a front yard") == (
        "for-sale sign front yard"
    )


def test_a_prompt_of_pure_noise_still_searches_for_something() -> None:
    """A bad search beats no search: the alternative is a branded card."""
    assert pictures.search_terms("a set of the") == "a set of the"


def test_a_photo_that_describes_people_is_skipped() -> None:
    """The filter screens the PROMPT; the library answers with whatever it
    has. "residential house keys" came back as "woman real estate agent
    placing a sign" — clean prompt, regulated picture."""
    words = ["woman", "family", "couple", "children"]
    assert pictures.shows_people("Woman real estate agent placing a sign", words)
    assert pictures.shows_people("A young family moving into their new home", words)
    assert not pictures.shows_people("Close-up of house keys on a table", words)
    assert not pictures.shows_people("Rocky Mountains with dramatic clouds", words)


def test_no_vocabulary_screens_nothing_rather_than_everything() -> None:
    """An older panel that does not ship the list must not silently reject
    every photograph — the human gate is still behind this."""
    assert not pictures.shows_people("Woman real estate agent", [])


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


def test_the_scenes_cover_the_whole_narration_with_no_gaps() -> None:
    """The bug that cut four words off the end of a piece a person was shown.

    Each scene used to end on the last word of its group and the next began on
    the first word of the next group, so every PAUSE between them belonged to
    no scene. The picture track came out shorter than the voice by the sum of
    those pauses and `-shortest` took the difference off the end — silently,
    exit code 0. The spans must tile the audio: no gap, no overlap.
    """
    words = [
        subtitles.Word(0.0, 0.8, "one"),
        subtitles.Word(0.8, 1.6, "two"),
        # A breath. This is the time that used to disappear.
        subtitles.Word(3.0, 3.8, "three"),
        subtitles.Word(3.8, 4.6, "four"),
        subtitles.Word(6.0, 6.8, "five"),
        subtitles.Word(6.8, 7.6, "six"),
    ]
    spans = produce.plan_shots([{}, {}, {}], words, total=9.0)
    assert spans[0][0] == 0.0
    assert spans[-1][1] == 9.0
    for (_, earlier_end), (later_start, _) in zip(spans, spans[1:], strict=False):
        assert earlier_end == later_start, spans
    covered = sum(end - start for start, end in spans)
    assert covered == pytest.approx(9.0), spans


def test_a_shot_lasts_exactly_its_span() -> None:
    """A floor on the length is a desynchroniser, not a safety net: the shots
    are concatenated, so padding one pushes every later shot off the words it
    belongs to and makes the picture track longer than the voice."""
    shot = produce.Shot(image=None, text="", start=2.0, end=2.4)
    assert shot.seconds == pytest.approx(0.4)


def test_without_a_transcript_the_scenes_share_the_time_evenly() -> None:
    """A fallback, not a failure: no words means no boundaries to cut on."""
    spans = produce.plan_shots([{}, {}, {}], [], total=9.0)
    assert spans == [(0.0, 3.0), (3.0, 6.0), (6.0, 9.0)]


def test_more_scenes_than_words_still_shows_every_scene() -> None:
    """The leftovers used to get a zero-length span at the very end.

    `Shot.seconds` padded those to a floor, and `-shortest` then cut them off
    when the audio ran out — so their images had already been fetched and PAID
    FOR and never appeared on screen. Every scene has to occupy real time.
    """
    words = [subtitles.Word(0.0, 0.4, "one"), subtitles.Word(0.4, 0.8, "two")]
    spans = produce.plan_shots([{}, {}, {}, {}], words, total=8.0)
    assert len(spans) == 4
    assert all(end > start for start, end in spans), spans
    assert spans[0][0] == 0.0 and spans[-1][1] == 8.0


def test_a_video_with_no_pictures_at_all_is_refused(monkeypatch, tmp_path: Path) -> None:
    """One card is a fallback. Every card is not a video.

    The first generated piece shipped as half a minute of flat navy with a
    word on it, because neither image provider had a key — and the only thing
    left to do with it was reject it, which a person did after watching the
    whole thing. Failing here puts the reason in the console instead.
    """
    from worker import tts

    monkeypatch.setattr(pictures, "fetch", lambda p, d, w=None: "none")
    monkeypatch.setattr(tts, "narrate", lambda t, d: (d.write_bytes(b"x"), d)[1])
    monkeypatch.setattr(subtitles, "transcribe", lambda a, language="en": [])
    spec = {
        "brokerage_line": "Engel & Völkers Aspen",
        "scenes": {"narration": "words", "scenes": [{"visual_prompt": "a street", "on_screen_text": "x"}]},
    }
    with pytest.raises(ValueError, match="no image provider"):
        produce.produce(spec, tmp_path, font=None, mark=None, music=None)


def test_a_piece_with_no_plan_is_refused_rather_than_improvised(
    tmp_path: Path,
) -> None:
    """Lane B has no clip to fall back on. Inventing one is not an option."""
    with pytest.raises(ValueError, match="no scene plan"):
        produce.produce({"scenes": None}, tmp_path, font=None, mark=None, music=None)


# ── The headline over each photograph ────────────────────────────────────


def test_a_long_headline_is_broken_before_it_runs_off_the_frame() -> None:
    """drawtext does not wrap: it draws one long line and lets it run off both
    edges. Measured on the render machine's own font, 35 characters is what
    fits at this size in the 960 px of usable width."""
    lines = produce.wrap_headline("What your budget actually gets you in Denver today")
    assert len(lines) == 2, lines
    assert all(len(line) <= produce.HEADLINE_CHARS for line in lines), lines
    # Words stay whole: a hyphen invented by a renderer reads as a typo.
    assert "budget" in " ".join(lines)


def test_a_short_headline_is_left_on_one_line() -> None:
    assert produce.wrap_headline("Reality") == ["Reality"]


def test_a_headline_longer_than_two_lines_is_cut_not_squeezed() -> None:
    """Better a headline that says less than one that covers the photograph."""
    assert len(produce.wrap_headline(" ".join(["word"] * 40))) == produce.HEADLINE_LINES


def test_no_headline_is_not_an_empty_one() -> None:
    assert produce.wrap_headline("") == []
    assert produce.wrap_headline("   ") == []


def test_the_spoken_domain_survives_the_url_stripper() -> None:
    """Two rules that must coexist, held together here.

    `for_the_voice` deletes anything shaped like a web address, and rightly:
    read aloud, a URL is "denverhomestory dot com" at best. The sign-off is
    written as WORDS for exactly that reason, so there is nothing to strip. If
    the stripper ever widens, this is what notices — and the symptom without it
    would be a video whose last sentence is "Buying or selling in Denver? Visit
    ." with the address silently gone.
    """
    said = spoken.for_the_voice(
        "Denver moves fast. Buying or selling in Denver? Visit Denver Home Story dot com."
    )
    assert "Denver Home Story dot com" in said
    # And the rule it has to coexist with is still doing its job.
    assert "denverhomestory" not in spoken.for_the_voice("Go to denverhomestory.com now.")
