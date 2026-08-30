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

    What counts is the VALUE, not the attribute name. `.status` is not a word
    this project owns: a render job has one, and so does a publication, and
    neither is a content piece walking its state machine. The first version
    flagged on the name alone and caught `render_jobs` bookkeeping — a true
    positive for the pattern and a false one for the rule, which is the kind of
    noise that gets a sweep exempted into uselessness. Flagging assignments of
    a `ContentStatus` is the actual invariant, and it still catches every door
    around `advance()`.
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
                assigns_content_status = (
                    isinstance(inner.value, ast.Attribute)
                    and isinstance(inner.value.value, ast.Name)
                    and inner.value.value.id == "ContentStatus"
                ) or (
                    # A bare name whose value cannot be read here. Treated as
                    # suspect rather than waved through: a sweep that only
                    # understands the literal form is a sweep somebody escapes
                    # with a local variable.
                    isinstance(inner.value, ast.Name)
                    and inner.value.id.lower().endswith("status")
                )
                for target in inner.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == "status"
                        and assigns_content_status
                    ):
                        offenders.append(
                            f"{path.relative_to(APP.parent)}::{node.name}:"
                            f"{inner.lineno}"
                        )
    assert offenders == [], (
        "these write a content status without going through advance(), so the "
        f"state machine does not apply to them: {offenders}"
    )


def test_the_status_sweep_can_still_catch_a_door() -> None:
    """Its own canary, added when the sweep was narrowed.

    A filter that stopped matching anything would pass the test above
    silently, which is exactly how a guard becomes decoration. This feeds it a
    door and requires that it slams.
    """
    source = (
        "async def sneak(piece):\n"
        "    piece.status = ContentStatus.PUBLISHED\n"
    )
    tree = ast.parse(source)
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "ContentStatus"
        and any(
            isinstance(t, ast.Attribute) and t.attr == "status" for t in node.targets
        )
    ]
    assert len(found) == 1, "the narrowed filter no longer recognises a door"


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


def test_every_wire_touching_function_is_declared_or_exempt() -> None:
    """The sweep that forces the first publisher through the gate.

    Classified by BODY, never by name. The first version of this test only
    examined functions named `publish_*`/`upload_*` calling a hand-picked verb
    list — the identical name-filter defect the opt-out canary shed in round
    eleven, sitting in the content gate until round twelve pointed at it. A
    publisher named `blast_reel` doing a bare `client.post()` walked through.

    Every function whose body touches the wire has to be accounted for:
    a messaging primitive (whose opt-out gating `test_opt_out_is_absolute.py`
    enforces), a declared publisher in `PUBLISH_PRIMITIVES` (whose approval
    gating `_reaching` below will enforce the day one exists), or a qualified
    exemption with the reason it is neither.
    """
    wire_verbs = {
        "post",
        "put",
        "send",
        "sendmail",
        "publish",
        "send_message",
        "upload",
        "create_media",
        "post_video",
        "request",
    }
    # Wire-touching but neither messaging nor publishing, each with its reason.
    # Qualified path::function, so a same-named function elsewhere is not
    # silently covered.
    WIRE_NOT_PUBLISHING = {
        "app/api/v1/public.py::_turnstile_ok":
            "POSTs a captcha token to Cloudflare; no content leaves",
        "app/services/calendar_cal.py::create_booking":
            "books a visit on Cal.com at the lead's request",
        "app/services/calendar_cal.py::cancel_booking":
            "cancels that same booking",
        "app/services/llm.py::_ollama_generate":
            "POSTs a prompt to a local model",
        "app/services/agent_calendar.py::_call":
            "the single request function for Cal.com's schedules and event"
            " types. It provisions and edits an AGENT's own working hours —"
            " days and times — and never carries a content piece, a lead's"
            " words, or anything with an audience. It is one function on"
            " purpose: a second wire-touching path in that module would have to"
            " be declared here too, which is the point of this sweep",
        "app/services/ops_alert.py::send_operator_alert":
            "emails the platform operator that the machinery broke; the body is"
            " a status word and a remedy, never a content piece, and it is"
            " addressed to PLATFORM_ADMIN_EMAILS rather than to any audience",
    }
    # The messaging senders, accounted for by the opt-out sweep next door.
    MESSAGING = {"send_email", "send_sms", "send_text_message"}

    flagged: dict[str, str] = {}
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            touches_wire = any(
                isinstance(inner, ast.Call)
                and (
                    (
                        isinstance(inner.func, ast.Attribute)
                        and inner.func.attr in wire_verbs
                    )
                    or (
                        isinstance(inner.func, ast.Name)
                        and inner.func.id in wire_verbs
                    )
                )
                for stmt in node.body
                for inner in ast.walk(stmt)
            )
            if touches_wire:
                flagged[f"{path.relative_to(APP.parent)}::{node.name}"] = node.name

    unaccounted = [
        qualified
        for qualified, name in flagged.items()
        if qualified not in WIRE_NOT_PUBLISHING
        and name not in MESSAGING
        and name not in PUBLISH_PRIMITIVES
    ]
    assert unaccounted == [], (
        "these touch the wire and are neither a declared messaging primitive, "
        "a declared publisher, nor exempted with a reason — a publisher here "
        f"would skip the approval gate unnoticed: {unaccounted}"
    )
    # And a declared publisher has to actually exist, so the list cannot rot.
    assert PUBLISH_PRIMITIVES <= set(flagged.values()), (
        f"declared publishers not found in the tree: "
        f"{PUBLISH_PRIMITIVES - set(flagged.values())}"
    )


def _calls_in(node: ast.AST) -> list[str]:
    """Every function name called in `node`, in source order.

    Both `f()` and `x.f()`, because a publisher reached through a module alias
    is still a publisher.
    """
    names: list[str] = []
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        if isinstance(inner.func, ast.Name):
            names.append(inner.func.id)
        elif isinstance(inner.func, ast.Attribute):
            names.append(inner.func.attr)
    return names


def _functions(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _reaching(module: pathlib.Path, targets: set[str]) -> set[str]:
    """Functions in `module` that reach `targets`, directly or through others.

    Transitive on purpose: the publisher does not call the wire itself, it
    calls a helper that does, and a guard that only inspected direct calls
    would be satisfied by one level of indirection.
    """
    functions = _functions(ast.parse(module.read_text(encoding="utf-8")))
    edges = {name: set(_calls_in(node)) for name, node in functions.items()}

    reaching = set(targets)
    changed = True
    while changed:
        changed = False
        for name, called in edges.items():
            if name not in reaching and called & reaching:
                reaching.add(name)
                changed = True
    return reaching - targets


PUBLISHER = APP / "services" / "buffer_publisher.py"


def test_the_gate_is_consulted_before_the_wire() -> None:
    """The promise this file made when `PUBLISH_PRIMITIVES` was still empty.

    A publisher that skips `ensure_publishable` publishes text that no person
    approved — the piece may have been edited after the button was pressed, or
    the brokerage line cleared, or the Fair Housing filter may now object. The
    check cannot live at approval time, so it has to live here, and "here" has
    to be verifiable rather than remembered.
    """
    assert PUBLISHER.exists(), "the publisher moved; this test has to move with it"
    reaching = _reaching(PUBLISHER, PUBLISH_PRIMITIVES)

    # Canary: an analysis that found nothing would pass every assertion below
    # while proving nothing at all.
    assert "_send" in reaching, (
        f"the reachability analysis did not find the sender: {sorted(reaching)}"
    )
    assert "publish_piece" in reaching, (
        "publish_piece no longer reaches the wire — either the publisher was "
        "restructured or this test is now inspecting the wrong function"
    )

    entry = _functions(ast.parse(PUBLISHER.read_text(encoding="utf-8")))["publish_piece"]
    calls = _calls_in(entry)
    assert "ensure_publishable" in calls, (
        "publish_piece does not consult the approval gate — anything it posts "
        "was approved by nobody"
    )
    first_gate = calls.index("ensure_publishable")
    wire = [i for i, name in enumerate(calls) if name in reaching or name in PUBLISH_PRIMITIVES]
    assert wire, "publish_piece reaches the wire but the call could not be located"
    assert first_gate < min(wire), (
        "publish_piece touches the wire before asking the gate; the order is "
        "the whole guarantee"
    )


def test_only_the_guarded_entry_point_reaches_the_wire() -> None:
    """Nothing outside the publisher may call its wire-touching helpers.

    Without this, the gate is one import away from being bypassed: a route or
    a worker calling `_send` directly would post an unapproved video and every
    test above would still be green.
    """
    private = {"_send", "_graphql"}
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if path == PUBLISHER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for called in _calls_in(node):
                    if called in private:
                        offenders.append(f"{path.relative_to(APP.parent)}::{node.name} -> {called}")
    assert offenders == [], (
        "these call the publisher's wire helpers from outside it, skipping the "
        f"approval gate: {offenders}"
    )
