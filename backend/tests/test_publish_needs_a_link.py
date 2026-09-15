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


@pytest.mark.parametrize("piece_id", [1, 42, 999])
def test_every_piece_gets_its_own_link(piece_id: int) -> None:
    assert f"piece-{piece_id}" in comment_for(piece_id, CTA)
