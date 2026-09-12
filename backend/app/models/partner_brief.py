"""A page we hand to the people we work with, and the answers they tap back.

The problem this solves is not "the agents need a form". It is that every ask
we had for Natalia and Robbie was arriving as an email with a list at the
bottom, and the reply we needed was a human retyping nine names into a mail
client on a phone. They are not going to do that, and asking them to was our
failure, not theirs.

So the ask moves to a page: they open a link, read what the work is, and tap.
The row below is both halves of that — `payload` is what the page shows them,
`answers` is what they tapped.

── Why the content lives in the row and not in the code ────────────────────
`payload` holds the whole brief: the sections, the nine names, the letter for
the broker. That looks like schemaless sprawl until you notice what the
alternative costs — a brief is written once, read for a week, and then never
again, so a hardcoded page means a deploy for every campaign and a migration
for every question we think of. Nine of these will exist by Christmas and no
two will have the same shape.

The shape `answers` takes is therefore the page's business, not this table's.
What the table guarantees is that an answer is attached to the brief it was
given, under the organization that owns both.

── The token is the credential ─────────────────────────────────────────────
There is no login here, and there cannot be: the whole point is that a person
who does not work inside this product can answer in one tap. `token` is what
stands in for the session, so it is generated with `secrets.token_urlsafe` and
never derived from anything (an id, a name, a date) that somebody could guess
from outside. It is unique globally and not per-org: two tenants must never be
able to collide into each other's brief by accident.

`opened_at` is not analytics. It answers the one question we actually ask
before chasing somebody — "did they even see it?" — and distinguishes "hasn't
read it" from "read it and had nothing to say", which are two very different
conversations to have with a partner.
"""

from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Bytes of entropy behind `token`. 32 urlsafe bytes is ~43 characters and
#: ~256 bits — far past anything an attacker enumerates, and still short
#: enough to survive being pasted into a text message without wrapping.
TOKEN_BYTES = 32


def new_token() -> str:
    """A fresh brief token.

    Its own function rather than a default on the column, because the script
    that creates a brief prints the URL, and it needs the value before the row
    exists.
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


class PartnerBrief(Base):
    """One brief, its content, and whatever has been answered so far."""

    __tablename__ = "partner_briefs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    token: Mapped[str] = mapped_column(String(length=64), nullable=False, unique=True)

    #: Shown in the panel and in the operator's notification, never on the page
    #: itself — the page carries its own headline inside `payload`.
    title: Mapped[str] = mapped_column(String(length=200), nullable=False)

    #: Who this link was handed to, in plain words ("Natalia and Robbie").
    #: Free text on purpose: the recipients of a brief are not necessarily
    #: users of this product, so there is nobody to foreign-key to.
    recipient: Mapped[str] = mapped_column(String(length=200), nullable=False, default="")

    #: Everything the page renders. See the module docstring for why.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    #: Everything they tapped or typed. Empty until the first save.
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    #: First time the page was fetched. Never overwritten — the question is
    #: "have they seen it", and the answer stops changing once it is yes.
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Last time they saved. Overwritten on every save: a second pass is a
    #: correction of the first, not a separate event.
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_partner_briefs_org_created", "org_id", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PartnerBrief id={self.id} org={self.org_id} title={self.title!r}>"
