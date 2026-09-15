"""A video nobody can click out of does not go out.

The measurement this exists because of: between 11 and 15 September 2026 the
channel published seven cards that took 3,833 views between them, and the
landing page recorded ONE visit from all seven. The captions did carry the
address — a Shorts description is simply collapsed behind "…more". So the
channel was working and the path out of it was not, and nothing anywhere
noticed, because nothing anywhere was asking.

Three properties are held here.

* A caption with no link is refused at publish time, not at approval time. The
  text can change after a person approves it, and the link is the first thing
  an edit drops.
* The refusal is announced. `publish_approved` logs `NotPublishable` at INFO
  and moves on, which is correct for its ordinary cause and would make this one
  invisible — a piece held in silence is held forever.
* A published piece hands over the comment to paste, once per piece rather than
  once per platform, with its own `piece-NN` already in the link.

The no-CTA case is deliberately permissive and is tested as such: an unset
`CONTENT_CTA_URL` is a deployment state, not a bad caption, and refusing every
piece over it would stop the channel instead of fixing it.
"""

from __future__ import annotations

import pytest

from app.services.publish_followup import caption_carries_link, comment_for

CTA = "https://denverhomestory.com/calculator"


def test_a_caption_without_a_link_is_not_publishable() -> None:
    assert not caption_carries_link("Three numbers decide the price.", CTA)


def test_a_caption_carrying_the_address_is_publishable() -> None:
    assert caption_carries_link(
        "Three numbers decide the price.\ndenverhomestory.com/calculator", CTA
    )


def test_a_schemeless_address_still_counts() -> None:
    """What the writer actually produces. It is a link once the publisher
    normalizes it, and refusing it here would hold every real caption."""
    assert caption_carries_link("See it: denverhomestory.com", CTA)


def test_somebody_elses_link_is_not_our_link() -> None:
    """A lookalike host is the failure this must not wave through: the piece
    would publish, the gate would be satisfied, and the click would go
    somewhere that is not ours."""
    assert not caption_carries_link("Read more at denverhomestory.com.evil.io", CTA)


def test_no_cta_configured_does_not_hold_the_channel() -> None:
    """`CONTENT_CTA_URL` is empty until the domain is live. That is a
    deployment state and belongs to `undeliverable_reason`, not to a gate that
    would refuse every piece one at a time."""
    assert caption_carries_link("Three numbers decide the price.", "")


def test_the_comment_carries_this_pieces_own_tag() -> None:
    text = comment_for(55, CTA)
    assert "utm_content=piece-55" in text
    # The medium is what will finally separate a click from the comment from a
    # click from the description or the channel's bio link. Without it the
    # three arrive indistinguishable, which is the state this whole change is
    # trying to leave.
    assert "utm_medium=comment" in text
    assert "utm_source=youtube" in text


def test_the_comment_puts_the_link_before_the_explanation() -> None:
    """A YouTube comment is truncated after about two lines. An explanation
    first is an explanation nobody reads followed by a link nobody sees."""
    lines = [ln for ln in comment_for(55, CTA).splitlines() if ln.strip()]
    assert lines[1].startswith("https://")


def test_a_schemeless_cta_still_produces_a_clickable_comment() -> None:
    """The setting may hold a bare domain. A bare domain in a comment is not
    reliably a link, and this is the one place we control that."""
    assert comment_for(7, "denverhomestory.com/calculator").count("https://") == 1


def test_the_comment_lands_where_the_caption_lands() -> None:
    """The configured CTA is the bare root, and the publisher routes a root to
    the social hub before posting it. A comment assembled by hand would have
    sent people to the homepage while the description above it went to
    `/start` — the same video pointing two places, and the split invisible in
    the report because both arrive tagged."""
    assert "/start" in comment_for(42, "https://www.denverhomestory.com")


def test_an_explicit_destination_is_not_rerouted() -> None:
    """A caption that names `/calculator` means it. The comment follows."""
    link = comment_for(42, "https://www.denverhomestory.com/calculator")
    assert "/calculator" in link
    assert "/start" not in link


@pytest.mark.parametrize("piece_id", [1, 42, 999])
def test_every_piece_gets_its_own_link(piece_id: int) -> None:
    assert f"piece-{piece_id}" in comment_for(piece_id, CTA)


# ─────────────────── the caption chooses, the comment follows ───────────────


ROOT = "https://www.denverhomestory.com"

CALC_CAPTION = (
    "At $2,600 a month, going from $40,000 saved to $80,000 moves the ceiling "
    "from $343,000 to $378,000.\n\nNothing to fill in to see the number: "
    "denverhomestory.com/calculator\n\nDenver Home Story · Natalia & Robbie"
)

FALL_CAPTION = (
    "Explore the scenic byway between Georgetown and Grant.\n\n"
    "Plan your route: https://www.denverhomestory.com/fall/2\n\n"
    "Save this for your next day out."
)


def test_the_comment_goes_where_the_caption_goes() -> None:
    """The one this module is named for, finally true.

    Until 15-sep-2026 every comment used the configured address, which is the
    bare root and routes to the social hub. So a video about a mortgage figure
    linked its description to `/calculator` and its comment to `/start` — a
    menu asking "what brings you here?" put in front of somebody who had just
    watched thirty seconds to get a number. One video, two destinations, and
    invisible in the report because both arrive tagged.
    """
    link = comment_for(47, ROOT, caption=CALC_CAPTION)
    assert "/calculator" in link
    assert "/start" not in link


def test_an_autumn_piece_keeps_its_own_page() -> None:
    """Not "calculator pieces go to the calculator" — whatever the approved
    text names. A rule per piece type is a rule that gets a type wrong."""
    link = comment_for(25, ROOT, caption=FALL_CAPTION)
    assert "/fall/2" in link
    assert "/calculator" not in link


def test_a_schemeless_caption_link_still_decides() -> None:
    """What the writer actually produces. `/calculator` above is schemeless;
    the router normalizes it, and refusing it here would send every real
    caption's comment to the hub instead."""
    assert "/calculator" in comment_for(47, ROOT, caption="see denverhomestory.com/calculator")


def test_without_a_caption_nothing_changes() -> None:
    """The fallback is the behaviour every caller had before, and the notice
    for a piece with no caption still has to produce a usable comment."""
    assert "/start" in comment_for(42, ROOT)
    assert "/start" in comment_for(42, ROOT, caption="")


def test_a_caption_with_no_link_of_ours_falls_back() -> None:
    """A caption naming somebody else's site is not a destination. It must not
    silently become one, and it must not produce a comment with no link."""
    link = comment_for(42, ROOT, caption="Read more at example.com/elsewhere")
    assert "/start" in link
    assert "example.com" not in link


def test_the_comment_still_carries_its_own_medium_and_piece() -> None:
    """Following the caption must not cost the two values that make a click
    from the comment countable apart from one from the description."""
    link = comment_for(47, ROOT, caption=CALC_CAPTION)
    assert "utm_medium=comment" in link
    assert "utm_content=piece-47" in link
    assert "utm_source=youtube" in link


def test_a_lookalike_host_in_the_caption_is_not_our_link() -> None:
    """The caption is approved text, not trusted text. A lookalike would send
    the comment somewhere that is not ours, under our video."""
    link = comment_for(42, ROOT, caption="go to denverhomestory.com.evil.io/now")
    assert "evil.io" not in link
    assert "/start" in link
