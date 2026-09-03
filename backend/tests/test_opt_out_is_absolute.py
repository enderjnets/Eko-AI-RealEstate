"""Nobody gets a message after they asked us to stop. Not even by hand.

Every automated path already refused: the follow-up sweep, the delivery retry,
the dispatch gate, the booking route. The one that did not was the one where a
person types a message and clicks send — which is the path most likely to be
used on a lead who has gone quiet, and the reason they have gone quiet may be
that they opted out.

Measured before the guard was written: a lead who texted STOP got HTTP 200 and
the message was delivered. Under the TCPA that is $500, or $1,500 where it is
willful — and having recorded the opt-out and sent anyway is what the word
willful is for.
"""
import ast
import pathlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Conversation, ConversationStatus, Lead, Message
from app.models.lead import LeadStatus
from app.services.tenant_context import org_scope


@pytest.fixture
def database_url() -> str:
    import os

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — these need live Postgres")
    return url


def _session(database_url: str):
    engine = create_async_engine(database_url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _lead_with(database_url: str, *, opted_out: bool) -> tuple[int, int]:
    engine, Session = _session(database_url)
    try:
        with org_scope(1):
            async with Session() as s:
                extra = (
                    {
                        "opted_out_at": datetime.now(UTC),
                        "opted_out_keyword": "STOP",
                        "opted_out_channel": "sms",
                    }
                    if opted_out
                    else {}
                )
                lead = Lead(
                    org_id=1,
                    phone=f"+1720T{uuid.uuid4().hex[:8].upper()}",
                    status=LeadStatus.QUALIFIED,
                    **extra,
                )
                s.add(lead)
                await s.flush()
                conv = Conversation(
                    org_id=1,
                    lead_id=lead.id,
                    channel="sms",
                    status=ConversationStatus.ACTIVE,
                )
                s.add(conv)
                await s.commit()
                return lead.id, conv.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_person_cannot_message_someone_who_said_stop(database_url: str) -> None:
    lead_id, conversation_id = await _lead_with(database_url, opted_out=True)
    engine, Session = _session(database_url)
    try:
        with org_scope(1):
            async with await _client() as c:
                r = await c.post(f"/api/v1/leads/{lead_id}/messages", json={"text": "Hi again"})
            assert r.status_code == 409, r.text
            assert "opted_out" in r.text

            async with Session() as s:
                written = (
                    await s.execute(
                        select(func.count())
                        .select_from(Message)
                        .where(Message.conversation_id == conversation_id)
                    )
                ).scalar_one()
            assert written == 0, "a message was recorded for someone who opted out"
    finally:
        await engine.dispose()
        with org_scope(1):
            async with Session() as s:
                await s.execute(text("DELETE FROM leads WHERE id = :i"), {"i": lead_id})
                await s.commit()


@pytest.mark.asyncio
async def test_an_ordinary_lead_is_unaffected(database_url: str) -> None:
    # The guard must not cost the normal case: this is the realtor's main way
    # of talking to people.
    lead_id, conversation_id = await _lead_with(database_url, opted_out=False)
    engine, Session = _session(database_url)
    try:
        with org_scope(1):
            async with await _client() as c:
                r = await c.post(f"/api/v1/leads/{lead_id}/messages", json={"text": "Hi"})
            assert r.status_code == 200, r.text

            async with Session() as s:
                written = (
                    await s.execute(
                        select(func.count())
                        .select_from(Message)
                        .where(Message.conversation_id == conversation_id)
                    )
                ).scalar_one()
            assert written == 1
    finally:
        await engine.dispose()
        with org_scope(1):
            async with Session() as s:
                await s.execute(text("DELETE FROM leads WHERE id = :i"), {"i": lead_id})
                await s.commit()


# The real primitives, taken from where they are defined rather than from a
# list I typed. The first version of this sweep named `send_whatsapp`, which
# exists nowhere in this codebase, and `send_email`, which every caller imports
# under an alias — so two of its four names never matched anything and the
# sweep was blind to WhatsApp and email entirely. A guard-of-guards with the
# defect it was written to catch.
SENDING_PRIMITIVES = {
    "send_text_message",  # app/services/whatsapp.py
    "send_sms",           # app/services/sms.py
    "send_email",         # app/services/email.py
}

# Functions allowed to reach a send without consulting the opt-out, each for a
# reason that has been checked:
# Qualified `path::function`, not bare names. A bare name exempts that function
# in EVERY module, so any file could acquire a `handle_inbound_message` and be
# waved through this check forever — an exemption is granted to one reviewed
# function, not to a spelling.
SEND_EXEMPT = {
    # The funnel every other sender goes through — it is the thing guarded.
    "app/services/conversation.py::_dispatch_send",
    # Answering someone who has just written to us. It sends only the STOP/START
    # confirmation the carriers require and then returns; any later message is
    # refused further down as `opted_out_no_reply`.
    "app/services/conversation.py::handle_inbound_message",
    # The adapters themselves: they are the primitive.
    "app/services/whatsapp.py::send_text_message",
    "app/services/sms.py::send_sms",
    "app/services/email.py::send_email",
    # Emails the AGENCY about a lead who just submitted the public form,
    # addressed to `booking_contact_email` from Settings and never to the lead.
    # The exemption runs both ways and both matter: a lead's earlier STOP must
    # not hide their own fresh form submission from the agent (the submission
    # IS inbound contact), and this notice must never be dispatched to the
    # lead — its thread record is `internal=True`, which the delivery sweep
    # skips by construction.
    "app/services/lead_notify.py::_send_and_record",
}

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _reads_opt_out(node: ast.AST) -> bool:
    """Does this function actually look at `opted_out_at`?

    An attribute access (`lead.opted_out_at`) or a keyword of that name. Text
    that merely contains the words does not count — that is the hole this
    replaced.
    """
    for inner in ast.walk(node):
        if isinstance(inner, ast.Attribute) and inner.attr == "opted_out_at":
            return True
        if isinstance(inner, ast.keyword) and inner.arg == "opted_out_at":
            return True
        # `getattr(lead, "opted_out_at")` is a real read and used to slip
        # through: it is neither an Attribute node nor a keyword, so the check
        # said "not aware" and the sweep would have flagged a careful function.
        # The reverse of the docstring hole, and worth closing for the same
        # reason — the sweep should answer about the code, not about its shape.
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "getattr"
            and len(inner.args) >= 2
            and isinstance(inner.args[1], ast.Constant)
            and inner.args[1].value == "opted_out_at"
        ):
            return True
    return False


def test_the_sweep_cannot_be_satisfied_by_a_docstring() -> None:
    """The detector, on two functions written to fool it.

    A sweep that can be silenced by writing prose about the rule is worse than
    no sweep: it reports a clean run over code nobody checked.
    """
    talks_about_it = ast.parse(
        'def f(lead):\n'
        '    """We deliberately do not check opted_out_at here."""\n'
        '    log.info("opted_out_at is somebody else\'s problem")\n'
        '    return send_sms(lead.phone, "hi")\n'
    ).body[0]
    actually_checks = ast.parse(
        "def g(lead):\n"
        "    if lead.opted_out_at is not None:\n"
        "        return None\n"
        '    return send_sms(lead.phone, "hi")\n'
    ).body[0]

    reads_it_indirectly = ast.parse(
        "def h(lead):\n"
        '    if getattr(lead, "opted_out_at") is not None:\n'
        "        return None\n"
        '    return send_sms(lead.phone, "hi")\n'
    ).body[0]

    assert _reads_opt_out(talks_about_it) is False
    assert _reads_opt_out(actually_checks) is True
    assert _reads_opt_out(reads_it_indirectly) is True


def _reaching_functions() -> tuple[list[str], int]:
    """Every function that can reach a send, following aliases and one hop.

    Aliased imports (`send_text_message as whatsapp_send`) are resolved per
    module, because the alias is what appears at the call site and matching on
    the original name finds nothing.
    """
    reaching, walked = [], 0
    for path in sorted(APP.rglob("*.py")):
        walked += 1
        tree = ast.parse(path.read_text())

        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for name in node.names:
                    if name.name in SENDING_PRIMITIVES:
                        aliases[name.asname or name.name] = name.name

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if f"{path.relative_to(APP.parent)}::{node.name}" in SEND_EXEMPT:
                continue
            called = {
                n.func.id
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            } | {
                n.func.attr
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }
            sends = called & (SENDING_PRIMITIVES | set(aliases) | {"_dispatch_send"})
            if not sends:
                continue
            # A real attribute access, not a substring of the dumped tree.
            # `ast.dump` includes every string constant, so a docstring or a log
            # line that merely mentioned `opted_out_at` certified the function as
            # careful — and the more thoroughly somebody documented why their
            # sender was safe, the more certainly this check stopped looking.
            aware = _reads_opt_out(node) or "may_send_automated" in called
            if not aware:
                reaching.append(f"{path.relative_to(APP.parent)}::{node.name}")
    return reaching, walked


def test_every_function_that_sends_consults_the_opt_out() -> None:
    """The sweep that found the defect, kept so it cannot come back.

    Guarding the path in front of me while its sibling keeps the defect is the
    single most repeated mistake in this codebase; this enumerates the paths
    instead of relying on me to remember them.
    """
    unguarded, _ = _reaching_functions()
    assert not unguarded, (
        f"these reach a send without consulting the opt-out: {unguarded}. "
        "Opt-out is revoked consent — it outranks everything else on record."
    )


def test_the_sweep_is_actually_looking_at_something() -> None:
    """A sweep that matches nothing passes silently.

    The previous canary asserted a string was present in a module — true
    regardless of whether the sweep had walked a single file. Run from the repo
    root rather than `backend/`, the sweep's relative path resolved to nothing,
    it walked zero files, found zero problems, and both tests went green. The
    path is absolute now and this counts what was actually examined.
    """
    unguarded, walked = _reaching_functions()
    assert walked > 50, f"the sweep only walked {walked} files — has the path moved?"

    # And it can still see a sender: prove the matching works rather than
    # trusting that an empty result means a clean codebase.
    seen = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                called = {
                    n.func.id
                    for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                }
                if called & (SENDING_PRIMITIVES | {"_dispatch_send"}):
                    seen.append(node.name)
    assert seen, "the sweep matched no sender at all — the names must be wrong"


@pytest.mark.asyncio
async def test_the_same_person_typed_differently_is_still_opted_out(
    database_url: str,
) -> None:
    """The opt-out has to attach to a person, not to a string.

    `+17205558217` and `720-555-8217` are one handset. They were two leads, so
    a STOP recorded against one said nothing about the other: re-add somebody
    from your own notes with the number typed differently and the system would
    message a person who had asked it to stop. No bad intent required — a
    hyphen is enough.
    """
    engine, Session = _session(database_url)
    canonical = "+17205559911"
    try:
        with org_scope(1):
            async with Session() as s:
                s.add(
                    Lead(
                        org_id=1,
                        phone=canonical,
                        status=LeadStatus.QUALIFIED,
                        opted_out_at=datetime.now(UTC),
                        opted_out_keyword="STOP",
                        opted_out_channel="sms",
                    )
                )
                await s.commit()

            async with await _client() as c:
                for typed in ("720-555-9911", "(720) 555-9911", "7205559911"):
                    r = await c.post(
                        "/api/v1/leads",
                        json={"phone": typed, "first_message": "Checking in!"},
                    )
                    assert r.status_code == 409, (
                        f"{typed!r} created a second lead for someone who opted out: {r.text}"
                    )

            async with Session() as s:
                count = (
                    await s.execute(
                        select(func.count())
                        .select_from(Lead)
                        .where(Lead.phone.like("%5559911"))
                    )
                ).scalar_one()
            assert count == 1, "the same person exists as more than one lead"
    finally:
        await engine.dispose()
        with org_scope(1):
            async with Session() as s:
                await s.execute(
                    text("DELETE FROM leads WHERE phone LIKE :p"), {"p": "%5559911"}
                )
                await s.commit()


@pytest.mark.asyncio
async def test_no_drafts_are_offered_for_someone_who_opted_out(
    database_url: str,
) -> None:
    """Nothing here sends, so this is not the violation itself — it is the step
    before it. Three ready-made messages for a person who asked us to stop
    invites the realtor to pick one, and the refusal then lands after they have
    written and clicked. It also stops us paying a language model to draft a
    message that cannot be sent."""
    lead_id, _ = await _lead_with(database_url, opted_out=True)
    engine, Session = _session(database_url)
    try:
        with org_scope(1):
            async with await _client() as c:
                r = await c.post(f"/api/v1/leads/{lead_id}/suggestions", json={"count": 3})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["suggestions"] == []
            assert body["error"] == "lead_opted_out"
    finally:
        await engine.dispose()
        with org_scope(1):
            async with Session() as s:
                await s.execute(text("DELETE FROM leads WHERE id = :i"), {"i": lead_id})
                await s.commit()


def test_every_outbound_primitive_is_on_the_list_the_sweep_checks() -> None:
    """The inverse assertion, which is the one that survives a fourth channel.

    `SENDING_PRIMITIVES` is hand-written. Everything above depends on it being
    complete, and nothing made it so: add MMS, or a voice callout, or push, and
    the sweep would go on reporting a clean run over code it never looked at —
    quietly, because a missing entry removes work rather than adding a failure.
    That is the original defect of this file (it once named `send_whatsapp`,
    which did not exist) moved up one level.

    So: anything in `app/services` that is shaped like an outbound primitive —
    a module-level `async def send_*` that performs an HTTP POST — must be
    declared. A new channel then fails this test instead of disappearing from
    the others.
    """
    # Every clause below was once narrower, and each narrowing is an exit a real
    # sender could leave through: `glob` missed sub-packages, `tree.body` missed
    # methods on a client class, `AsyncFunctionDef` missed sync helpers, and
    # `post` alone missed the Twilio SDK, which sends with `messages.create`.
    # Widened twice by things that walked straight through. `client.send(req)`
    # is how httpx sends a pre-built request and it carried a real POST out of
    # here; `resend.Emails.send`, `sns.publish` and `smtp.sendmail` are the same
    # shape. The bare-name case matters too: `from httpx import post` makes the
    # call an `ast.Name`, not an `ast.Attribute`, and the old check only looked
    # at attributes.
    # The wire-touching verbs, matched in function BODIES only. Decorators are
    # excluded on purpose: `@router.post` made every POST route in the API
    # look like a sender. `request`/`create` are deliberately NOT here — every
    # LLM client calls `.create` — because this list is for the narrow shapes
    # that actually put bytes on a messaging wire.
    outbound_verbs = {
        "post",
        "put",
        "send",
        "sendmail",
        "publish",
        "send_message",
    }

    # Functions the classifier flags that are OUTBOUND but not MESSAGING —
    # each with the reason it does not need the opt-out gate. Qualified, so a
    # same-named function in a new module is not silently covered.
    OUTBOUND_NOT_MESSAGING = {
        "app/api/v1/public.py::_turnstile_ok":
            "POSTs a captcha token to Cloudflare; no lead is addressed",
        "app/services/calendar_cal.py::create_booking":
            "books a visit on Cal.com at the lead's own request; transactional,"
            " lead-initiated, not nurture",
        "app/services/calendar_cal.py::cancel_booking":
            "cancels that same booking; same reasoning",
        "app/services/llm.py::_ollama_generate":
            "POSTs a prompt to a local model; no lead is addressed",
        "app/services/ops_alert.py::send_operator_alert":
            "emails the platform operator about the machinery, addressed to"
            " PLATFORM_ADMIN_EMAILS and never to a lead. The exemption runs both"
            " ways and both matter: a lead's STOP must not silence an outage"
            " report, and an outage report must never land in a lead's inbox",
        "app/services/telegram_notify.py::notify_video_ready":
            "messages the owner's own chat that a video is waiting for him,"
            " addressed to TELEGRAM_CHAT_ID and never to a lead. Same two-way"
            " reasoning as the operator email above: a lead's STOP must not"
            " silence the approval queue's doorbell, and that doorbell must"
            " never reach a lead",
        "app/services/buffer_publisher.py::_graphql":
            "posts a video to the agency's OWN social channels through Buffer."
            " Nobody is addressed: a marketing video on a public channel is"
            " broadcast, not a message, and there is no recipient whose consent"
            " could be checked. Applying opt-out here would be nonsense in both"
            " directions — a single lead's STOP cannot take the agency's"
            " channels offline, and publishing a video is not a way to reach"
            " somebody who asked not to be contacted. Its own gate is"
            " `content_studio.ensure_publishable` (a person approved this"
            " text), enforced by test_content_gate_is_absolute.py",
    }
    undeclared: list[str] = []
    walked = 0
    seen_per_module: dict[str, set[str]] = {}
    # The whole application tree, not just `services/`. `_reaching_functions`
    # below walks `APP.rglob("*.py")`, so a primitive living anywhere else —
    # `app/integrations/`, which is where the voice provider will land — was
    # invisible to this canary while being perfectly visible to the sweep that
    # depends on it.
    for path in sorted(APP.rglob("*.py")):
        walked += 1
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            # No name filter. The old sweep only examined functions named
            # `send_*`, which defended renames of the three known senders and
            # nothing else: a `notify_lead_by_push` doing a bare client.post()
            # shipped a whole channel with zero opt-out enforcement and every
            # test stayed green. What a function is called is not evidence
            # about what it does — its body is.
            sends = any(
                isinstance(inner, ast.Call)
                and (
                    (
                        isinstance(inner.func, ast.Attribute)
                        and inner.func.attr in outbound_verbs
                    )
                    or (
                        isinstance(inner.func, ast.Name)
                        and inner.func.id in outbound_verbs
                    )
                )
                for stmt in node.body
                for inner in ast.walk(stmt)
            )
            if not sends:
                continue
            qualified = f"{path.relative_to(APP.parent)}::{node.name}"
            if qualified in OUTBOUND_NOT_MESSAGING:
                continue
            seen_per_module.setdefault(path.name, set()).add(node.name)
            if node.name not in SENDING_PRIMITIVES:
                undeclared.append(qualified)

    # Its own canary. A sweep that walks nothing passes, and this file exists
    # because that has happened here before — the count belongs to the sweep it
    # guards, not to a neighbouring one.
    assert walked > 10, f"only walked {walked} service files — the path is wrong"
    # Per module, and by name rather than by count. A global floor of three sat
    # one below the real four, so renaming a sender — the precise way one
    # escapes an AST sweep keyed on `startswith("send_")` — dropped it to three
    # and the canary was still satisfied. Moving to a per-module floor of one
    # did not fix that: `>= 1` is `bool()`, so `send_sms` could vanish and any
    # other `send_*` in the same file would keep the assertion green.
    #
    # Names, compared as sets, is the only form with no slack in it. The sweep
    # has to find exactly what `SENDING_PRIMITIVES` claims exists: a rename, a
    # move, a deletion and an undeclared newcomer are all the same failure —
    # the two lists disagreeing — and each says which side drifted.
    expected_per_module = {
        "sms.py": {"send_sms"},
        "whatsapp.py": {"send_text_message"},
        "email.py": {"send_email"},
    }
    for module, expected in expected_per_module.items():
        found = seen_per_module.get(module, set())
        assert found == expected, (
            f"{module} contributes {sorted(found)}, expected {sorted(expected)}"
            " — a sender was renamed out of this sweep's sight, the file moved,"
            " or a new one arrived undeclared"
        )
    # The set of MODULES has to match too. The loop above only visits the names
    # this table already knows, so a primitive appearing in a module nobody
    # listed was skipped in silence — which is how a whole channel could ship
    # with no opt-out enforcement behind it.
    assert set(seen_per_module) == set(expected_per_module), (
        f"modules carrying an outbound primitive: {sorted(seen_per_module)}, "
        f"table names: {sorted(expected_per_module)} — a channel arrived or "
        "moved and this sweep was not told"
    )
    # And the union has to be the declared list itself, so a primitive cannot be
    # quietly relocated to a module this table does not name.
    assert set().union(*expected_per_module.values()) == SENDING_PRIMITIVES, (
        "the per-module table and SENDING_PRIMITIVES disagree about what the "
        "outbound primitives are"
    )
    assert not undeclared, (
        "these look like outbound primitives but are not in SENDING_PRIMITIVES, "
        f"so the opt-out sweep never follows them: {undeclared}"
    )
