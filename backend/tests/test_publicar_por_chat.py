"""The chat-approved publishing path and TikTok's caption limit (0.143.56)."""

import hashlib
import importlib.util
from datetime import date, timedelta
from pathlib import Path

from app.services.buffer_publisher import TIKTOK_TEXT_LIMIT, fit_tiktok_text

_SPEC = importlib.util.spec_from_file_location(
    "publicar_pieza", Path(__file__).resolve().parents[1] / "scripts" / "publicar_pieza.py"
)
publicar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(publicar)

BROKERAGE = "Engel & Voelkers · Each office independently owned and operated"
AI = "Clara, our host, is an AI-generated character. Narrated with a synthetic voice."


def _caption(story_len: int = 300, credits: bool = True) -> str:
    parts = ["Why does downtown Denver have a bell tower?", "", "x" * story_len, "",
             "Follow for more Denver, decoded.", "", BROKERAGE, AI]
    if credits:
        parts += ["Photos: " + "p" * 400, "Music: original track made with vidIQ.", "Sources: " + "s" * 400]
    return "\n".join(parts)


def test_a_caption_that_fits_is_not_touched():
    c = _caption()
    assert len(c) <= TIKTOK_TEXT_LIMIT
    assert fit_tiktok_text(c) == c


def test_credits_go_first_and_the_disclosures_stay():
    c = _caption(story_len=1500)
    assert len(c) > TIKTOK_TEXT_LIMIT
    out = fit_tiktok_text(c)
    assert len(out) <= TIKTOK_TEXT_LIMIT
    assert BROKERAGE in out and AI in out
    assert "Sources:" not in out
    assert "x" * 1500 in out, "the story is only shortened when dropping credits is not enough"


def test_a_story_too_long_even_without_credits_is_shortened_but_not_the_disclosures():
    c = _caption(story_len=3000)
    out = fit_tiktok_text(c)
    assert len(out) <= TIKTOK_TEXT_LIMIT
    assert BROKERAGE in out and AI in out
    assert "…" in out


def test_the_piece_142_shape_now_fits():
    # 19-oct-2026: "[InvalidInputError] Invalid post: TikTok posts cannot exceed 2200 characters."
    c = _caption(story_len=1350)
    assert len(fit_tiktok_text(c)) <= TIKTOK_TEXT_LIMIT


def test_a_caption_without_the_brokerage_or_the_ai_line_is_refused():
    assert publicar.caption_problems(_caption()) == []
    no_brk = _caption().replace(BROKERAGE, "")
    no_ai = _caption().replace(AI, "")
    assert any("brokerage" in p for p in publicar.caption_problems(no_brk))
    assert any("AI-generated" in p for p in publicar.caption_problems(no_ai))
    assert publicar.caption_problems(no_ai, generated=False) == []


def test_the_approval_records_whose_words_it_was():
    label = publicar.approver_label("Ender in the chat,   2026-10-31 13:20: 'Aprobado'")
    assert label == "chat: Ender in the chat, 2026-10-31 13:20: 'Aprobado'"
    assert len(publicar.approver_label("x" * 400)) == 255


def _files(tmp_path: Path, caption: str | None = None) -> tuple[Path, str, Path, Path]:
    v = tmp_path / "v.mp4"
    v.write_bytes(b"video bytes")
    hk = tmp_path / "hook.txt"
    hk.write_text("Why does downtown Denver have a bell tower?")
    cp = tmp_path / "cap.txt"
    cp.write_text(caption if caption is not None else _caption())
    return v, hashlib.sha256(b"video bytes").hexdigest(), hk, cp


def _args(v, sha, hk, cp, *extra):
    return ["--video", str(v), "--sha256", sha, "--hook-file", str(hk), "--caption-file", str(cp),
            "--date", (date.today() + timedelta(days=3)).isoformat(), "--dry-run", *extra]


def test_a_different_file_is_refused(tmp_path):
    v, sha, hk, cp = _files(tmp_path)
    assert publicar.main(_args(v, "0" * 64, hk, cp)) == 2


def test_approve_without_the_owners_words_is_refused(tmp_path):
    v, sha, hk, cp = _files(tmp_path)
    assert publicar.main(_args(v, sha, hk, cp, "--approve")) == 2
    assert publicar.main(_args(v, sha, hk, cp, "--approve", "--approved-by", "Ender, chat 31-oct: Aprobado")) == 0


def test_a_caption_missing_the_disclosures_is_refused_before_anything_is_sent(tmp_path):
    v, sha, hk, cp = _files(tmp_path, caption="Just a story, no brokerage, no AI line.")
    assert publicar.main(_args(v, sha, hk, cp)) == 2


def test_a_past_date_is_refused(tmp_path):
    v, sha, hk, cp = _files(tmp_path)
    args = _args(v, sha, hk, cp)
    args[args.index("--date") + 1] = (date.today() - timedelta(days=1)).isoformat()
    assert publicar.main(args) == 2
