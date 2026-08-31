"""The gate every piece of content has to pass, and the only door through it.

Two functions matter here.

`advance()` is the only thing in the codebase that changes a piece's status.
Every transition is declared; anything undeclared raises. That is not
bureaucracy — the difference between DRAFT and APPROVED is the difference
between a machine's opinion and a licensed agent's, and a status field that
anything may assign is a status field that means nothing.

`ensure_publishable()` is checked at the moment of publishing, not at the moment
of approving. A piece can be edited after it was approved, so approval is a fact
about the text that existed when the button was pressed. It re-reads the row
under a lock and asks again: is it APPROVED, does the organisation have a
brokerage line, does the text still pass the Fair Housing filter. The lesson
behind that shape was paid for in this repo already — a consent gate that lived
only in the producer let everything already queued go out unchecked.

Nothing here publishes. `PUBLISH_PRIMITIVES` is empty and the sweep in
`test_content_gate_is_absolute.py` asserts that it is: when the first publisher
lands it has to be declared, and every caller of it has to consult this gate.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentSettings, ContentPiece, ContentStatus
from app.services.fair_housing import find_violations

log = logging.getLogger(__name__)

# The functions that actually hand a video to a platform.
# `test_content_gate_is_absolute.py` compares this against what an AST sweep
# finds, so a publisher that arrives without being declared fails the suite
# rather than shipping unguarded, and a name declared here that no longer
# touches the wire fails it too.
#
# `_graphql` is the single request function in `services/buffer_publisher.py`.
# One function on purpose: a second wire-touching path in that module would
# have to be declared here as well, which is the point.
PUBLISH_PRIMITIVES: set[str] = {"_graphql"}


class IllegalTransition(Exception):
    """A status change nobody declared. Never caught — it is a programming
    error, and swallowing it would put the piece in the state anyway."""


class NotPublishable(Exception):
    """The gate said no. Carries why, because the operator has to be able to
    fix it rather than guess."""


# Declared transitions. A piece walks DRAFT → NEEDS_APPROVAL → APPROVED →
# PUBLISHING → PUBLISHED, and can fall out at the marked points.
#
# APPROVED → NEEDS_APPROVAL exists and is load-bearing: editing an approved
# piece has to revoke the approval, because the approval was of the old text.
# Without that edge, "approve, then change the words" is a way to publish
# something no person ever read.
_ALLOWED: dict[ContentStatus, set[ContentStatus]] = {
    ContentStatus.DRAFT: {
        ContentStatus.NEEDS_APPROVAL,
        ContentStatus.REJECTED,
    },
    ContentStatus.NEEDS_APPROVAL: {
        ContentStatus.APPROVED,
        ContentStatus.REJECTED,
        ContentStatus.DRAFT,
    },
    ContentStatus.APPROVED: {
        ContentStatus.PUBLISHING,
        ContentStatus.REJECTED,
        # Edited after approval.
        ContentStatus.NEEDS_APPROVAL,
    },
    ContentStatus.PUBLISHING: {
        ContentStatus.PUBLISHED,
        ContentStatus.FAILED,
    },
    # Terminal. PUBLISHED especially: it is a statement about the outside world,
    # and nothing in here can un-post a video.
    ContentStatus.PUBLISHED: set(),
    ContentStatus.REJECTED: {ContentStatus.DRAFT},
    ContentStatus.FAILED: {ContentStatus.DRAFT},
}


# Whether anything in this installation can actually publish to a platform.
# True since v0.65, when `services/buffer_publisher.py` landed. It stayed False
# for three versions because the tables and the API field for publications
# existed since v0.52, which made an empty `publications` list ambiguous —
# "nothing published yet" and "publishing does not exist" look identical to a
# reader. One constant so the interface cannot drift from the code.
#
# It says the machinery exists, not that it is switched on: whether a given
# install actually posts is `CONTENT_PUBLISH_ENABLED` plus a configured
# channel, and `buffer_publisher.undeliverable_reason()` is what answers that.
PUBLISHING_AVAILABLE = True


async def other_orgs_exist(acting: int | None) -> bool:
    """Is this installation serving more than this one organization?

    Read on the bypass engine: the question is about the installation rather
    than about any tenant, and under RLS a tenant cannot see that there are
    others.
    """
    from sqlalchemy import func as sa_func

    from app.db.base import get_bypass_session_factory
    from app.models.organization import STATUS_SUSPENDED, Organization

    async with get_bypass_session_factory()() as meta:
        return (
            await meta.execute(
                select(sa_func.count())
                .select_from(Organization)
                .where(
                    Organization.status != STATUS_SUSPENDED,
                    Organization.id != (acting or -1),
                )
            )
        ).scalar_one() > 0


async def not_our_rail() -> str | None:
    """Why the content rail must not run for the acting organization, or None.

    Every worker on this rail calls it — the writer, the lane B queue and the
    publisher — because they all answer the same question and three copies of
    an answer is how they drift apart. `run_for_every_org` visits every tenant
    by design; the rail belongs to exactly one.
    """
    from app.config import get_settings
    from app.services.tenant_context import get_org_id

    acting = get_org_id()
    allowed = get_settings().CONTENT_ORG_ID
    if allowed:
        return None if acting == allowed else f"the content rail belongs to org {allowed}"
    if await other_orgs_exist(acting):
        return (
            "this installation has more than one organization and "
            "CONTENT_ORG_ID does not say whose content rail this is"
        )
    return None


def text_violations(
    *,
    hook: str | None,
    script: str | None,
    caption: str | None,
    scenes: dict | None,
    language: object = None,
) -> list[dict[str, str]]:
    """Everything a Fair Housing filter objects to, across ALL of a piece.

    One function, called from every place that forms an opinion about a piece:
    the writer, the console's edit and submit routes, and the publish gate.
    Three copies of "which fields count" is how a field gets added to the
    product and forgotten by the filter — which is exactly what happened here.
    `narration` and `on_screen_text` arrived in v0.67 and neither was read by
    anything, so a script could say "great schools" and "perfect for families"
    out loud, in a video, with the row recording zero findings.

    `narration` is the text a NARRATOR SPEAKS. If only one field could be
    checked it would be that one: the audience hears it whether or not they
    read the caption, and nobody edits a sentence they cannot see.

    `visual_prompt` gets the phrase filter AND the person-descriptor denylist,
    because housing advertising is regulated in pictures too.
    """
    from app.services.fair_housing import picture_violations

    found = find_violations(
        " ".join(part for part in (hook, script, caption) if part), language
    )

    plan = scenes or {}
    narration = plan.get("narration")
    if narration:
        for hit in find_violations(str(narration), language):
            found.append({**hit, "where": "narration"})

    for index, scene in enumerate(plan.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        where = f"scene {index + 1}"
        prompt = str(scene.get("visual_prompt") or "")
        for hit in find_violations(prompt, language) + picture_violations(prompt):
            found.append({**hit, "where": where})
        # Burned into the frame when a scene falls back to a branded card, and
        # read by every viewer either way.
        on_screen = str(scene.get("on_screen_text") or "")
        for hit in find_violations(on_screen, language):
            found.append({**hit, "where": f"{where} caption"})

    return found


def advance(piece: ContentPiece, to: ContentStatus) -> None:
    """Move a piece to `to`, or raise.

    Deliberately not `piece.status = x` anywhere else. A grep for
    `\\.status = ` in the content code should find this function and nothing
    else, and the sweep test enforces exactly that.
    """
    if to not in _ALLOWED[piece.status]:
        raise IllegalTransition(
            f"piece {piece.id}: {piece.status.value} → {to.value} is not a "
            "transition this system has"
        )
    piece.status = to


async def ensure_publishable(
    db: AsyncSession, piece_id: int, *, resuming: bool = False
) -> ContentPiece:
    """Re-read the piece under a lock and re-check everything. Or raise.

    Called at the point of publishing. Checking at approval time instead would
    be checking a piece that no longer exists: the text can change afterwards,
    the brokerage line can be cleared, and the row can be racing another
    publisher.

    `resuming` additionally accepts a piece already in PUBLISHING, and it is
    not a loosening of the gate: a piece reaches that state only by passing
    this function, and a publish run that stops halfway — a quota pause leaves
    exactly that — has platforms with no post yet. Without it those platforms
    would never be reached and the piece would sit in PUBLISHING forever. The
    brokerage line and the Fair Housing filter are re-checked either way, which
    is what actually protects the text.
    """
    piece = (
        await db.execute(
            select(ContentPiece).where(ContentPiece.id == piece_id).with_for_update()
        )
    ).scalar_one_or_none()
    if piece is None:
        raise NotPublishable(f"piece {piece_id} does not exist")

    # Not "has been approved at some point" — IS approved, now. A piece edited
    # after approval is back in NEEDS_APPROVAL and fails here, which is the
    # entire point of that edge existing.
    allowed = {ContentStatus.APPROVED}
    if resuming:
        allowed.add(ContentStatus.PUBLISHING)
    if piece.status not in allowed:
        raise NotPublishable(
            f"piece {piece_id} is {piece.status.value}, and only a piece a "
            "person has approved may be published"
        )

    settings = (
        await db.execute(
            select(AgentSettings).where(AgentSettings.org_id == piece.org_id)
        )
    ).scalar_one_or_none()
    brokerage = (settings.brokerage_line or "").strip() if settings else ""
    if not brokerage:
        raise NotPublishable(
            "this organisation has no brokerage line on record, and real "
            "estate advertising has to identify the brokerage"
        )

    # Again, not once. The filter ran when the draft was written; the text has
    # had a human edit since, and a person fixing a hook is not thinking about
    # familial status.
    violations = text_violations(
        hook=piece.hook,
        script=piece.script,
        caption=piece.caption,
        scenes=piece.scenes,
        language=piece.language,
    )
    if violations:
        raise NotPublishable(
            f"piece {piece_id} still contains language that cannot go in "
            f"housing advertising: {violations}"
        )

    return piece
