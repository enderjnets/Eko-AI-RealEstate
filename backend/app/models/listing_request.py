"""Somebody asked to see options, and what happened to that ask.

── Why this is a row and not a reply ───────────────────────────────────────
On 2026-09-19 the email channel took its first real question: *"I'm renting at
$2,400 in Wash Park and I have around $35,000 saved. What would that actually
buy right now?"* Clara answered in nine paragraphs and offered nothing, because
there was nothing to offer — the listings table held simulated Miami condos and
`match_properties_for_lead` had no Denver row to return.

The fix is not a better paragraph. We have no MLS API: REcolorado's data comes
out of Matrix by hand, and a licence that costs $70 a month allows 500 record
exports every 30 days against Natalia's own name. So the only honest shape is
the one Ender drew — the ask becomes a piece of work with a state, a person
does the search, and the system carries it from her screen to the client and
back.

── The ask is opened by a FIELD, never by a sentence ───────────────────────
`wants_listings` comes out of the classifier's structured JSON. Nothing here is
triggered by what the reply model wrote, and that is the same rule v0.135.0
settled: an inbound email is untrusted text, so text must not be able to start
work that costs a person's licence quota. The model opines; the code decides.

── One open ask per lead ───────────────────────────────────────────────────
Enforced by a partial unique index, not by good manners. Without it, four
emails in four minutes are four searches Natalia is asked to do, and the person
who sent them gets to decide how much of her allowance to spend. The code
returns the request that already exists; the index is what makes that true even
when two workers race.

── The token is the credential ─────────────────────────────────────────────
Same reasoning as `PartnerBrief`, and the same generator: the client has no
account and must not need one. What the token opens carries **no listing data**
— only two buttons — so a leaked link exposes nothing an MLS rule protects.
The options themselves travel in the email, which is what §11.2 permits: a
Participant may reproduce and distribute listing information to a prospective
purchaser, and may not display or publish it without prior written consent.
A web page is publishing. An email to the person who asked is not.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pg_enum
from app.models.partner_brief import new_token

__all__ = ["ListingRequest", "ListingRequestStatus", "CALLBACK_TEXT_MAX", "new_token"]

#: How much of the client's own words we keep when they ask for a call. Long
#: enough for "Thursday after 4pm, or any time Friday", short enough that the
#: field cannot be used to post an essay into the realtor's inbox. Their words
#: are quoted to her verbatim and never put in front of a model.
CALLBACK_TEXT_MAX = 200

#: The ceiling on one send. Six is what Ender asked for and it is also the
#: number `match_properties_for_lead` defaults to; more than this stops being a
#: shortlist and starts being a feed, which is the thing we are not licensed to
#: publish.
MAX_SELECTED = 6


class ListingRequestStatus(str, enum.Enum):
    OPEN = "open"                              # asked for; nobody has picked yet
    SENT = "sent"                              # options emailed to the client
    MORE_REQUESTED = "more_requested"          # they pressed "show me more"
    CALLBACK_REQUESTED = "callback_requested"  # they asked Natalia to call
    CANCELLED = "cancelled"                    # closed without sending


class ListingRequest(Base):
    """One "show me options" ask, from the question to whatever came back."""

    __tablename__ = "listing_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )

    token: Mapped[str] = mapped_column(String(length=64), nullable=False, unique=True)

    status: Mapped[ListingRequestStatus] = mapped_column(
        pg_enum(ListingRequestStatus, name="listing_request_status"),
        default=ListingRequestStatus.OPEN,
        nullable=False,
        index=True,
    )

    #: Where the ask came from: "message" (they wrote in) or "more" (they
    #: pressed the button on a previous one). Kept because the two deserve
    #: different urgency and because a chain of "more" is the shape an abuse
    #: attempt takes.
    origin: Mapped[str] = mapped_column(String(length=20), nullable=False, default="message")

    #: The ids Natalia ticked, in the order she ticked them. Ids and nothing
    #: else: the listing facts live in `properties`, and copying them here would
    #: create a second, stale, unattributed copy of MLS data.
    selected_property_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    #: Their own words about when to call, verbatim and capped. Never a
    #: structured time: a free-text answer cannot be wrong about itself, and
    #: nothing in this system is allowed to hold a slot on her calendar.
    callback_text: Mapped[str | None] = mapped_column(
        String(length=CALLBACK_TEXT_MAX), nullable=True
    )

    #: What the system proposes, best first: `[{property_id, score, reason,
    #: checks}]`. Machine-generated and DISPOSABLE — recomputed wholesale every
    #: time the request is opened or a new export lands, so it is never the
    #: authority on anything and the listing facts inside it are a cache of a
    #: comparison rather than a second copy of the MLS.
    #:
    #: Always REASSIGNED, never mutated in place: SQLAlchemy does not see a
    #: list that changed under it, and the recompute would be silently lost on
    #: the next load. The same trap `conversation.py` documents for `lead.meta`.
    suggestions: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    #: What the buyer had asked for AT THE TIME. The notice says "2 matched of
    #: 8 active", and that arithmetic has to stay checkable against what she
    #: was told rather than drift when a later message changes the lead.
    requirements_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    #: What a PERSON wrote about why each listing was picked, keyed by property
    #: id. Separate from `suggestions` precisely because that one is thrown away
    #: and rebuilt: an import landing between "she edits the reason" and "she
    #: presses send" must not quietly discard her sentence.
    sent_reasons: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    #: `{"matched": N, "active": M}` — the two numbers the notice needs to tell
    #: "no inventory in this zone" from "no inventory at all".
    match_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    suggested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: First time the client opened the page. Never overwritten — the question
    #: is "did they see it", and that stops changing once it is yes.
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_listing_requests_org_created", "org_id", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ListingRequest id={self.id} lead={self.lead_id} "
            f"status={self.status.value}>"
        )
