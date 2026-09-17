"""The link is the whole point of the video, so nothing goes out without one.

Measured, not theorised. Between 11 and 15 September 2026 the channel put out
seven cards that took 3,833 views between them, and the landing page recorded
**one** visit from all of them. The captions did carry the address, but a Shorts
description is collapsed behind "…more" and almost nobody opens it. The videos
were working; the path out of them was not.

Two things live here, and they are halves of the same idea.

**A caption with no link cannot be published.** `caption_carries_link` asks the
publisher's own tagger whether it can find and tag one of our addresses in the
text. Asking the tagger rather than writing a second regex is deliberate: two
matchers drift, and the one that decides what gets published would then differ
from the one that decides what the link says. The check runs at publish time,
beside the brokerage line and the Fair Housing filter, for the same reason
those do — the caption a person approved is not necessarily the caption that
exists now, and the link is the first thing an edit drops.

**A held piece says so out loud.** `publish_approved` catches `NotPublishable`
and logs it at INFO, which is right for its ordinary cause — a piece edited
back into review between the query and the gate. A missing link is not that: it
is a piece that will sit still, silently, until somebody happens to read a log.
So the refusal rings the owner's phone. A gate nobody hears about is how
`pending_alerts.json` ended up written by one process and read by none.

**And a published piece hands over the comment to paste.** We publish through
Buffer, which posts videos and cannot write comments, and the module that does
the posting explains why adding YouTube's own OAuth was refused. So the last
step stays manual — but it does not stay *remembered*: the notice arrives with
the finished text, the piece number already in the link, so posting it is a
copy and a paste rather than a thing to look up. `utm_medium=comment` is what
will finally answer whether the comment is worth the trouble, separately from
the description and from the channel's bio link.

Nothing here may break a publish. A notice that fails is a notice that failed.
"""

from __future__ import annotations

import logging

from app.models import PublicationPlatform
from app.services.telegram_notify import send_operator_telegram

log = logging.getLogger(__name__)


def caption_carries_link(text: str, cta_url: str) -> bool:
    """Whether the publisher would find one of our addresses in this caption.

    Delegates to `with_platform_utm`, which returns the text byte-for-byte when
    it finds nothing to tag. That equality is the answer: if tagging changed
    nothing, there is no link for a viewer to follow either.

    Imported inside the function because `buffer_publisher` imports this module;
    at module scope the two would not load.
    """
    from app.services.buffer_publisher import with_platform_utm

    if not (cta_url or "").strip():
        # No destination is configured at all. That is a deployment state, not
        # a bad caption, and refusing every piece over it would stop the
        # channel rather than fix it — `undeliverable_reason` is where a
        # missing configuration belongs.
        return True

    # Any platform and any campaign: the question is whether a link EXISTS, and
    # the tagger finds the same link for all three.
    tagged = with_platform_utm(text or "", cta_url, PublicationPlatform.YOUTUBE, 0, "probe")
    return tagged != (text or "")


def comment_for(
    piece_id: int, cta_url: str, campaign: str = "video", caption: str | None = None
) -> str:
    """The comment to paste under the video, with this piece's own tag.

    Short on purpose: a comment is truncated after about two lines, so the link
    goes on the first one a reader sees, not after an explanation.

    **The caption chooses the destination, and the comment follows it.** Given
    the caption, the link is the one the approved text already names: a
    calculator piece says `/calculator`, an autumn piece says `/fall/2`. Without
    it, the configured address is the fallback, and a bare root routes to the
    social hub.

    That mattered more than it looks. Until 15-sep-2026 this used the configured
    root for every piece, so every comment pointed at `/start` — a menu asking
    "what brings you here?" — while the caption above it pointed at the page
    with the answer. Somebody who had just watched thirty seconds about a
    mortgage figure was asked to choose a path instead of being given the
    figure. The test named `the comment lands where the caption lands` has
    always been the right idea; it was checking the configured address, which is
    not where the caption lands.

    The link is built by the publisher's own router either way, with
    `medium="comment"`. Assembling one here would have been three lines and a
    bug the first time either destination moved.
    """
    from app.services.buffer_publisher import link_the_text_chose, with_platform_utm

    base = (cta_url or "").strip() or "denverhomestory.com"
    link = (
        link_the_text_chose(
            caption or "", base, PublicationPlatform.YOUTUBE, piece_id, campaign, medium="comment"
        )
        or with_platform_utm(
            base, base, PublicationPlatform.YOUTUBE, piece_id, campaign, medium="comment"
        )
    )
    return (
        f"Run your own number — nothing to fill in to see it:\n{link}\n"
        "Every assumption on that page is a slider you can move: rate, "
        "appreciation, taxes, insurance. None of it is a promise."
    )


async def _say(subject: str, body: str, piece_id: int) -> bool:
    """Send, and never let a failed notice cost a publish."""
    try:
        return bool(await send_operator_telegram(subject, body))
    except Exception as exc:  # noqa: BLE001 — a notice may never break a publish
        log.error("Piece %d: telegram notice failed: %s", piece_id, exc)
        return False


async def notify_held_without_link(piece_id: int, hook: str) -> bool:
    """A piece was refused for having no link. Said out loud, once per attempt."""
    return await _say(
        "Piece held: no link in the caption",
        f"Piece {piece_id} — “{(hook or '').strip()[:90]}” — was not published.\n\n"
        "Its caption has no link to the site, so the video would have had no way "
        "back to the page. Add the address to the caption and approve it again.",
        piece_id,
    )


async def notify_held_without_brokerage(piece_id: int, hook: str) -> bool:
    """A piece was refused for not naming the brokerage. Twin of the one above.

    Same reason it is said out loud: `publish_approved` treats a refusal as
    ordinary and logs it, and this particular refusal never clears itself. The
    piece stays approved, keeps being picked up, and keeps being put back —
    silently — until somebody edits its caption.
    """
    return await _say(
        "Piece held: the caption does not name the brokerage",
        f"Piece {piece_id} — “{(hook or '').strip()[:90]}” — was not published.\n\n"
        "Colorado asks that every advertisement identify the brokerage firm, "
        "and this caption names nobody. Add the line from Settings to the "
        "caption and approve it again.",
        piece_id,
    )


async def notify_slots_full(piece_id: int, hook: str, platform: str) -> bool:
    """A platform is waiting because Buffer's queue for it is full.

    On the transition into that state, never on every tick: the publisher tries
    again every fifteen minutes and a notice per attempt would be noise nobody
    reads, which is the same failure as no notice at all.

    This exists because of what happened without it. Buffer holds ten scheduled
    posts per channel; the queue was full to 26 October, and pieces 33, 34 and
    36 were refused on all three channels and marked FAILED — a state nothing
    retries unless a person approves the piece again. Three approved pieces
    stopped dead and not one thing said so. The state is now PENDING and
    recovers by itself, and this is the half that makes it visible while it
    waits.
    """
    return await _say(
        "Waiting for room at Buffer",
        f"Piece {piece_id} — “{(hook or '').strip()[:90]}” — is waiting on "
        f"{platform}.\n\n"
        "Buffer holds ten scheduled posts per channel and that channel is full. "
        "Nothing is lost: it will go out on its own as soon as one of the ten "
        "publishes. This is only so the wait is not silent.",
        piece_id,
    )


async def notify_published(
    piece_id: int, hook: str, cta_url: str, caption: str | None = None
) -> bool:
    """It went out. Here is the comment to paste under it.

    Once per piece, not once per platform: three posts are one video as far as
    the person holding the phone is concerned.
    """
    return await _say(
        "Published — paste the comment",
        f"Piece {piece_id} — “{(hook or '').strip()[:90]}” — is out.\n\n"
        "Paste this as a comment on the YouTube Short (the description link is "
        "collapsed behind “…more” and almost nobody opens it):\n\n"
        f"{comment_for(piece_id, cta_url, caption=caption)}",
        piece_id,
    )
