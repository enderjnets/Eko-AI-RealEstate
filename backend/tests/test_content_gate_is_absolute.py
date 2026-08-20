"""Nothing reaches a platform that a person has not approved, now.

Modelled on `test_opt_out_is_absolute.py`, which exists because a gate that
lived only in the producer let everything already queued go out unchecked. The
same shape of mistake is available here and costs more: the exposure of a Fair
Housing violation in advertising lands on the broker's licence.

Three things are checked.

* The state machine is closed. `advance()` is the only door, and every
  transition that is not declared raises.
* `ensure_publishable()` re-asks at publish time rather than trusting approval
  time, because the text can change after a person reads it.
* An AST sweep, so the two above cannot be bypassed by writing
  `piece.status = ...` somewhere else, and so the first publisher to arrive has
  to declare itself.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    AgentSettings,
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentStatus,
)
from app.services.content_studio import (
    PUBLISH_PRIMITIVES,
    IllegalTransition,
    NotPublishable,
    advance,
    ensure_publishable,
)
from app.services.tenant_context import org_scope

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
ORG = 1

CLEAN_HOOK = "Three things to check before you make an offer in Denver."
BROKERAGE = "Natalia & Robbie · Engel & Völkers"


# --------------------------------------------------------------------------
# The state machine
# --------------------------------------------------------------------------

ALL = list(ContentStatus)

LEGAL = {
    (ContentStatus.DRAFT, ContentStatus.NEEDS_APPROVAL),
    (ContentStatus.DRAFT, ContentStatus.REJECTED),
    (ContentStatus.NEEDS_APPROVAL, ContentStatus.APPROVED),
    (ContentStatus.NEEDS_APPROVAL, ContentStatus.REJECTED),
    (ContentStatus.NEEDS_APPROVAL, ContentStatus.DRAFT),
    (ContentStatus.APPROVED, ContentStatus.PUBLISHING),
    (ContentStatus.APPROVED, ContentStatus.REJECTED),
    (ContentStatus.APPROVED, ContentStatus.NEEDS_APPROVAL),
    (ContentStatus.PUBLISHING, ContentStatus.PUBLISHED),
    (ContentStatus.PUBLISHING, ContentStatus.FAILED),
    (ContentStatus.REJECTED, ContentStatus.DRAFT),
    (ContentStatus.FAILED, ContentStatus.DRAFT),
}


@pytest.mark.parametrize("frm", ALL)
@pytest.mark.parametrize("to", ALL)
def test_only_declared_transitions_are_possible(
    frm: ContentStatus, to: ContentStatus
) -> None:
    """Every pair, both ways. Spelling out the legal set here rather than
    importing it means a quiet widening of `_ALLOWED` fails instead of
    redefining what the test checks."""
    piece = ContentPiece(
        org_id=ORG,
        kind=ContentKind.GENERATED,
        language=ContentLanguage.EN,
        status=frm,
        hook=CLEAN_HOOK,
    )
    if (frm, to) in LEGAL:
        advance(piece, to)
        assert piece.status is to
    else:
        with pytest.raises(IllegalTransition):
            advance(piece, to)
        assert piece.status is frm, "a refused transition still moved the piece"


def test_published_is_terminal() -> None:
    """Nothing here can un-post a video, so nothing here may pretend to."""
    for to in ALL:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.PUBLISHED,
        )
        with pytest.raises(IllegalTransition):
            advance(piece, to)


def test_an_edit_after_approval_can_revoke_it() -> None:
    """The edge the whole gate leans on.

    Without APPROVED → NEEDS_APPROVAL, "approve, then change the words" is a
    way to publish text no person ever read.
    """
    piece = ContentPiece(
        org_id=ORG,
        kind=ContentKind.GENERATED,
        language=ContentLanguage.EN,
        status=ContentStatus.APPROVED,
        hook=CLEAN_HOOK,
    )
    advance(piece, ContentStatus.NEEDS_APPROVAL)
    assert piece.status is ContentStatus.NEEDS_APPROVAL


# --------------------------------------------------------------------------
# The publish gate
# --------------------------------------------------------------------------


async def _org_with_brokerage(line: str | None) -> None:
    async with get_bypass_session_factory()() as db:
        settings = (
            await db.execute(
                select(AgentSettings).where(AgentSettings.org_id == ORG)
            )
        ).scalar_one_or_none()
        if settings is None:
            settings = AgentSettings(org_id=ORG)
            db.add(settings)
        settings.brokerage_line = line
        await db.commit()


async def _seed(status: ContentStatus, **kw) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=status,
            hook=kw.pop("hook", CLEAN_HOOK),
            **kw,
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _cleanup() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_pieces WHERE org_id = 1"))
        await db.commit()


@pytest.mark.asyncio
async def test_an_approved_piece_with_a_brokerage_line_passes() -> None:
    await _org_with_brokerage(BROKERAGE)
    piece_id = await _seed(ContentStatus.APPROVED)
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                assert (await ensure_publishable(db, piece_id)).id == piece_id
    finally:
        await _cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [s for s in ContentStatus if s is not ContentStatus.APPROVED],
)
async def test_nothing_but_approved_may_publish(status: ContentStatus) -> None:
    await _org_with_brokerage(BROKERAGE)
    piece_id = await _seed(status)
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with pytest.raises(NotPublishable):
                    await ensure_publishable(db, piece_id)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_no_brokerage_line_means_nothing_publishes() -> None:
    """Colorado requires advertising to identify the brokerage. An unanswered
    question stops content rather than releasing it unlabelled."""
    await _org_with_brokerage(None)
    piece_id = await _seed(ContentStatus.APPROVED)
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with pytest.raises(NotPublishable, match="brokerage"):
                    await ensure_publishable(db, piece_id)
    finally:
        await _cleanup()
        await _org_with_brokerage(BROKERAGE)


@pytest.mark.asyncio
async def test_whitespace_is_not_a_brokerage_line() -> None:
    await _org_with_brokerage("   ")
    piece_id = await _seed(ContentStatus.APPROVED)
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with pytest.raises(NotPublishable, match="brokerage"):
                    await ensure_publishable(db, piece_id)
    finally:
        await _cleanup()
        await _org_with_brokerage(BROKERAGE)


@pytest.mark.asyncio
async def test_the_filter_runs_again_at_publish_time() -> None:
    """Approval is a fact about the text that existed when the button was
    pressed. A person fixing a hook afterwards is not thinking about familial
    status, and the draft-time filter has long since run."""
    await _org_with_brokerage(BROKERAGE)
    piece_id = await _seed(
        ContentStatus.APPROVED, hook="Perfect for families in a safe neighborhood."
    )
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with pytest.raises(NotPublishable, match="housing advertising"):
                    await ensure_publishable(db, piece_id)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_the_filter_sees_the_caption_and_the_script_too() -> None:
    """A hook is what gets reviewed hardest; the caption is what gets pasted."""
    await _org_with_brokerage(BROKERAGE)
    caption_id = await _seed(ContentStatus.APPROVED, caption="Great schools nearby!")
    script_id = await _seed(ContentStatus.APPROVED, script="Ideal para familias.")
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                for piece_id in (caption_id, script_id):
                    with pytest.raises(NotPublishable, match="housing advertising"):
                        await ensure_publishable(db, piece_id)
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_a_piece_of_another_org_is_not_publishable_here() -> None:
    """The gate reads the row itself, so it has to be reading it under the
    tenant boundary rather than around it."""
    await _org_with_brokerage(BROKERAGE)
    async with get_bypass_session_factory()() as db:
        other = ContentPiece(
            org_id=2,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=ContentStatus.APPROVED,
            hook=CLEAN_HOOK,
        )
        db.add(other)
        await db.commit()
        other_id = other.id
    try:
        with org_scope(ORG):
            async with get_session_factory()() as db:
                with pytest.raises(NotPublishable):
                    await ensure_publishable(db, other_id)
    finally:
        async with get_bypass_session_factory()() as db:
            await db.execute(text("DELETE FROM content_pieces WHERE org_id = 2"))
            await db.commit()
        await _cleanup()


# --------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------

CONTENT_FILES = ("content_studio.py", "content_writer.py", "content_topics.py")


def test_advance_is_the_only_thing_that_writes_a_status() -> None:
    """Otherwise the state machine is decoration.

    Any `something.status = ...` in the content code that is not the one line
    inside `advance()` is a door around it, and the next person to add a
    convenience assignment will not notice they have opened one.
    """
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if path.name not in CONTENT_FILES and "content" not in path.name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name == "advance":
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Assign):
                    continue
                for target in inner.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == "status"
                    ):
                        offenders.append(
                            f"{path.relative_to(APP.parent)}::{node.name}:"
                            f"{inner.lineno}"
                        )
    assert offenders == [], (
        "these write a content status without going through advance(), so the "
        f"state machine does not apply to them: {offenders}"
    )


def test_the_sweep_is_looking_at_something() -> None:
    """Its own canary. A sweep whose file filter matches nothing passes."""
    seen = [
        p.name
        for p in APP.rglob("*.py")
        if p.name in CONTENT_FILES or "content" in p.name
    ]
    assert "content_studio.py" in seen, (
        f"the sweep did not even open the gate's own module: {seen}"
    )


def test_no_publisher_exists_yet_and_the_list_says_so() -> None:
    """`PUBLISH_PRIMITIVES` is empty and has to stay honest.

    When the first publisher lands it must be declared here, and the assertion
    below is what forces that: it fails the moment a function that hands a
    video to a platform exists without being listed.
    """
    platform_calls = {"upload", "publish", "create_media", "post_video"}
    found: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.name.startswith(("publish_", "upload_")):
                continue
            if any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr in platform_calls
                for inner in ast.walk(node)
            ):
                found.append(node.name)
    assert set(found) == PUBLISH_PRIMITIVES, (
        f"publishers found in the tree: {sorted(found)}, declared: "
        f"{sorted(PUBLISH_PRIMITIVES)} — a publisher that is not declared is "
        "one nothing checks the approval gate for"
    )
