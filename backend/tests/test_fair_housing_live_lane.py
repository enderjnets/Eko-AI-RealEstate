"""The Fair Housing filter, on the lane that actually talks to leads.

The filter shipped in v0.52 and for four months ran only on the video rail.
`conversation.py` — SMS, email and WhatsApp, the thing answering real people
today — never called it. These tests hold the wiring that fixed that, and,
just as importantly, hold the SHAPE of the fix: it records and sends, it does
not block. A future change that turns this into a review queue should have to
delete a test that says so out loud, not merely fail to notice.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select, text

from app.db.base import get_bypass_session_factory, get_session_factory
from app.models.message import Message, MessageDirection, MessageSender
from app.models.monitor_state import MonitorState
from app.services import tenant_resolver
from app.services.tenant_context import org_scope

AGENCY = 940


async def _make_agency() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, plan) "
                "VALUES (:i, 'FH Agency', 'fh-agency', 'active', 'pilot') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"i": AGENCY},
        )
        await db.commit()


async def _clear() -> None:
    """Remove everything this module creates, in dependency order.

    **The organization row is the one that matters**, and leaving it behind is
    not merely untidy: `tenant_resolver` falls back to the only agency when
    exactly one is routable, so a second org surviving this module turns every
    later webhook test in the suite into an `unrouted` refusal. Measured, not
    theorised — omitting this line cost 117 failures in files that never
    mention Fair Housing. Same shape as `test_shared_resources._cleanup`.
    """
    async with get_bypass_session_factory()() as db:
        for table in (
            "follow_ups",
            "messages",
            "conversations",
            "visits",
            "leads",
            "agent_settings",
            "channel_routes",
        ):
            await db.execute(
                text(f"DELETE FROM {table} WHERE org_id = :o"), {"o": AGENCY}
            )
        await db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": AGENCY})
        await db.execute(text("DELETE FROM monitor_state WHERE key = 'fair_housing'"))
        # The watcher sweeps EVERY organization by design, so these tests can
        # only assert a global reading from a known global state. Any other
        # module whose fixtures happen to produce a flagged reply would
        # otherwise make `test_a_quiet_day_is_not_an_email` fail here while
        # passing alone — the kind of order-dependent failure that gets a test
        # deleted instead of understood. Cheap, and scoped to the test database.
        await db.execute(
            text("UPDATE messages SET fair_housing_flags = NULL "
                 "WHERE fair_housing_flags IS NOT NULL")
        )
        await db.commit()
    tenant_resolver.reset_cache()


async def _inbound(reply_text: str, phone: str) -> list[Message]:
    """Run one full inbound turn with a stubbed LLM, return the outbound rows."""
    from app.services._common import ParsedMessage
    from app.services.conversation import handle_inbound_message
    from app.services.llm import LLMResult

    sent: list[tuple] = []

    async def _reply(**kwargs: object) -> LLMResult:
        return LLMResult(
            text=reply_text, provider="kimi", model="k2",
            input_tokens=1, output_tokens=1,
        )

    async def _sent(*a: object, **k: object) -> tuple[str, None]:
        sent.append((a, k))
        # Unique per call: `messages` carries UNIQUE (org_id, external_id), so
        # a constant id makes the second `_inbound` in one test collide on the
        # provider-id write rather than on anything the test is about.
        return f"ext-{phone}-{len(sent)}", None

    arriving = ParsedMessage(
        channel="sms",
        external_id=f"fh-{phone}",
        from_identifier=phone,
        from_name="A Lead",
        content="Hi, looking for a place.",
    )
    with org_scope(AGENCY):
        async with get_session_factory()() as db:
            with patch("app.services.conversation.generate_reply", _reply), patch(
                "app.services.conversation._dispatch_send", _sent
            ):
                await handle_inbound_message(arriving, db)

        async with get_session_factory()() as db:
            rows = (
                await db.execute(
                    select(Message)
                    .where(Message.direction == MessageDirection.OUTBOUND)
                    .order_by(Message.id)
                )
            ).scalars().all()
    # The send actually happened — that is half of what these tests assert.
    assert len(sent) == 1, f"expected exactly one dispatch, got {len(sent)}"
    return list(rows)


@pytest.mark.asyncio
async def test_a_flagged_reply_is_recorded_and_still_sent() -> None:
    """The decision, in one test: record, do not block.

    Holding the reply would trade a compliance risk for a service outage — a
    lead writing at 11pm would get nothing until somebody reviewed it. So the
    assertion is deliberately two-sided: the flags landed AND the message went
    out. Delete either half and the design has changed.
    """
    await _clear()
    await _make_agency()
    try:
        rows = await _inbound(
            "This home is perfect for families with young children.", "+13035551001"
        )
        assert len(rows) == 1
        flags = rows[0].fair_housing_flags
        assert flags, "the forbidden phrase was not recorded"
        assert any(f["category"] == "familial_status" for f in flags), flags
        assert rows[0].content.startswith("This home is perfect for families")
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_a_screened_clean_reply_is_an_empty_list_not_null() -> None:
    """NULL and `[]` are different claims, and this column is a compliance record.

    NULL means "never screened" — every row written before v0.56, the inbound
    side (the lead's own words, not ours to police) and the lanes that do not
    run this filter. `[]` means "screened, nothing found". Collapsing them into
    NULL to keep the column sparse was the first implementation, and it made
    the honest answer to "was this reply checked?" permanently unavailable
    while three docstrings claimed otherwise.

    Asserted in SQL as well as through the ORM, because a Python `None` reaches
    a JSON column as the JSON value `null` unless `none_as_null=True` is set —
    which is NOT SQL NULL, and which had `IS NOT NULL` matching every clean
    reply and the watcher reporting a flagged day, every day.
    """
    await _clear()
    await _make_agency()
    try:
        rows = await _inbound(
            "The listing has three bedrooms and a two-car garage.", "+13035551002"
        )
        assert len(rows) == 1
        assert rows[0].fair_housing_flags == [], rows[0].fair_housing_flags

        async with get_bypass_session_factory()() as db:
            stored = (
                await db.execute(
                    text(
                        "SELECT fair_housing_flags IS NULL, "
                        "fair_housing_flags::text FROM messages WHERE id = :i"
                    ),
                    {"i": rows[0].id},
                )
            ).one()
        assert stored[0] is False, "a screened reply was stored as NULL"
        assert stored[1] == "[]", f"expected an empty JSON array, got {stored[1]!r}"

        # And an INBOUND row — the lead's own words — is left untouched.
        async with get_bypass_session_factory()() as db:
            inbound_null = (
                await db.execute(
                    text(
                        "SELECT bool_and(fair_housing_flags IS NULL) FROM messages "
                        "WHERE org_id = :o AND direction = 'inbound'"
                    ),
                    {"o": AGENCY},
                )
            ).scalar()
        assert inbound_null is True, "the inbound side was screened; it should not be"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_the_filter_runs_after_the_broker_credit_is_added() -> None:
    """The ORDER of the two calls in production, asserted structurally.

    IDX attribution is reproduced verbatim by legal obligation, so the brokerage
    name is text we must publish and cannot edit. A brokerage called "Perfect
    for Families Realty" therefore walks straight past a filter pointed at the
    model's raw output, and only a filter on the credited string sees it.

    The first version of this test built the credited string itself and checked
    that `find_violations` caught the phrase — which it does, and which proves
    nothing: moving the production call back onto `reply.text` left that test
    green. It asserted a property of the filter while claiming to assert a
    property of the wiring. This one reads the real function's AST, so the
    mutation it names is the mutation that turns it red.
    """
    import ast
    import inspect

    from app.services import conversation

    tree = ast.parse(inspect.getsource(conversation))
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "handle_inbound_message"
    )

    credit_at: int | None = None
    filter_at: int | None = None
    filter_arg: str | None = None
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name == "_with_broker_credits":
            credit_at = node.lineno
        elif name == "find_violations":
            filter_at = node.lineno
            first = node.value.args[0] if node.value.args else None
            filter_arg = ast.unparse(first) if first is not None else None

    assert credit_at is not None, "_with_broker_credits vanished from the reply path"
    assert filter_at is not None, "nothing screens the outbound reply any more"
    assert filter_at > credit_at, (
        "the Fair Housing filter now runs BEFORE the broker credit is appended, "
        "so a brokerage name carrying a forbidden phrase is no longer seen"
    )
    assert filter_arg == "reply_text", (
        f"the filter is reading {filter_arg!r}; it must read the credited string "
        "`reply_text`, which is what is persisted and sent"
    )


@pytest.mark.asyncio
async def test_the_canned_fallback_reply_is_screened_too() -> None:
    """When every LLM is down the lead still gets a sentence, and that sentence
    is ours — so it goes through the same gate. It is clean today; this test is
    what notices if somebody edits it into something that is not."""
    from app.models.agent_settings import AgentSettings
    from app.services.conversation import _fallback_reply
    from app.services.fair_housing import find_violations

    cfg = AgentSettings(org_id=AGENCY, agency_name="FH Agency")
    for lang in ("es", "en"):
        canned = _fallback_reply(cfg, lang)
        # Non-empty FIRST. `find_violations("") == []` is trivially true, so
        # without this the test stayed green with the emergency reply gutted
        # to the empty string — a lead who wrote at 11pm getting silence, and
        # a test reporting that the silence was compliant.
        assert canned.text.strip(), f"the {lang} fallback reply is empty"
        assert len(canned.text) > 20, f"the {lang} fallback is too short to be a reply"
        assert find_violations(canned.text) == [], (lang, canned.text)
    # `cfg` is never added to a session, so there is nothing to clean up here.


@pytest.mark.asyncio
async def test_the_fixed_templates_carry_no_forbidden_language() -> None:
    """The outbound paths that are NOT screened at runtime, checked at build time.

    Human replies are a licensed person's own words. The STOP/START
    acknowledgement and the nurture templates are fixed strings of ours, so
    re-running a filter over a constant on every send would burn CPU to
    re-derive the same verdict. They are checked here instead — once.

    The first version of this test named `followups` in its docstring and
    iterated only `optout`, which is the same species of lie as a test that
    cannot fail: the coverage was claimed, not written. `_TEMPLATES` is now
    actually read, and a `KeyError` here is the point — if the constant is
    renamed, this test must break rather than quietly check nothing.
    """
    from app.services import optout
    from app.services.fair_housing import find_violations
    from app.services.followups import _TEMPLATES

    checked = 0
    for name in ("CONFIRMATION", "RESUMED"):
        for txt in getattr(optout, name).values():
            assert find_violations(str(txt)) == [], (name, txt)
            checked += 1

    for kind, by_lang in _TEMPLATES.items():
        for lang, txt in by_lang.items():
            # Rendered with a hostile agency name on purpose. The template is
            # ours, but `{agency}` is the client's own display name and it is
            # interpolated verbatim — so a brokerage called "Perfect for
            # Families Realty" reaches the lead through this lane too. This
            # asserts the TEMPLATE is clean, and documents that the
            # interpolated value is not screened anywhere. See the backlog.
            rendered = str(txt).format(name=" Ana", agency="Denver Home Story")
            assert find_violations(rendered) == [], (kind, lang, txt)
            checked += 1

    # Without this the loops could iterate nothing and the test would pass
    # green over an empty check — the failure it exists to prevent.
    assert checked >= 12, f"only {checked} strings were checked; the constants moved"


@pytest.mark.asyncio
async def test_the_watch_alerts_once_and_retries_a_failed_send() -> None:
    """The alarm has to be heard once, and has to survive not being heard.

    Three properties in one flow, because they are one mechanism: a clean day
    turning flagged sends exactly one mail; the same state on the next tick
    sends nothing; and a send the provider rejected is retried instead of being
    consumed — the defect v0.54.4 fixed in the other watcher, which this one
    copies rather than re-earns.
    """
    from app.services import fair_housing_watch as fhw

    await _clear()
    await _make_agency()
    try:
        await _inbound("This home is perfect for families.", "+13035551003")

        calls: list[tuple[str, str]] = []
        outcome = {"ok": False}

        async def _send(subject: str, body: str) -> bool:
            calls.append((subject, body))
            return outcome["ok"]

        with patch.object(fhw, "send_operator_alert", _send), patch.object(
            fhw, "undeliverable_reason", lambda: None
        ):
            # 1. The send fails: nothing is consumed.
            assert await fhw.run_fair_housing_tick() == fhw.FLAGGED
            assert len(calls) == 1
            async with get_bypass_session_factory()() as db:
                row = (
                    await db.execute(
                        select(MonitorState).where(MonitorState.key == fhw.WATCH_KEY)
                    )
                ).scalar_one()
                assert row.alerted_state is None, "a failed send was consumed"
                assert row.state == fhw.FLAGGED
                # The ATTEMPT is charged, not the delivery. Charging only
                # successes makes a failing send free, so the budget never
                # closes and the retry becomes 288 attempts a day against the
                # same quota that answers leads — and a send whose response
                # timed out may already have been delivered, so those are real
                # duplicates. Nothing asserted this before.
                assert row.alerts_today == 1, (
                    f"a failed attempt cost nothing ({row.alerts_today}); the "
                    "circuit breaker is defeated"
                )

            # 2. Next tick retries, and this time it lands.
            outcome["ok"] = True
            assert await fhw.run_fair_housing_tick() == fhw.FLAGGED
            assert len(calls) == 2, "the failed alert was not retried"

            # 3. Same state again: silence.
            assert await fhw.run_fair_housing_tick() == fhw.FLAGGED
            assert len(calls) == 2, "a level-triggered alert slipped in"

        # The body names counts and categories, never the lead's text.
        subject, body = calls[-1]
        assert "familial_status" in body
        assert "perfect for families" not in body.lower()
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_a_spent_budget_does_not_send_and_does_not_consume() -> None:
    """The cap is shared with the mail that answers leads, so it is real. But a
    capped alert must not be a LOST alert: with the budget spent, the state is
    left outstanding so the next UTC day delivers it."""
    from app.services import fair_housing_watch as fhw

    await _clear()
    await _make_agency()
    try:
        await _inbound("Ideal para familias jóvenes.", "+13035551004")

        async with get_bypass_session_factory()() as db:
            db.add(
                MonitorState(
                    key=fhw.WATCH_KEY,
                    state=fhw.CLEAN,
                    alerts_today=fhw.MAX_ALERTS_PER_DAY,
                    alerts_day=datetime.now(UTC).strftime("%Y-%m-%d"),
                )
            )
            await db.commit()

        calls: list[tuple[str, str]] = []

        async def _send(subject: str, body: str) -> bool:
            calls.append((subject, body))
            return True

        with patch.object(fhw, "send_operator_alert", _send), patch.object(
            fhw, "undeliverable_reason", lambda: None
        ):
            await fhw.run_fair_housing_tick()
            assert calls == [], "the budget did not hold"

            async with get_bypass_session_factory()() as db:
                row = (
                    await db.execute(
                        select(MonitorState).where(MonitorState.key == fhw.WATCH_KEY)
                    )
                ).scalar_one()
                assert row.alerted_state is None, "a debt was written off unpaid"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_a_busy_but_clean_day_is_not_an_email() -> None:
    """A quiet day is not an empty table — it is a table full of clean replies.

    This is the test the first version was missing, and the gap was not
    academic. Screened-clean replies are stored as `[]`, so a sweep filtering
    on `IS NOT NULL` counts every one of them as a hit: one ordinary day of
    normal conversations would have sent the operator a "flagged" alert. An
    alarm that fires on all-clear is ignored within a week, taking the real
    ones with it.

    So this sends real traffic first — clean traffic — and only then ticks.
    Measured: reverting the sweep to `isnot(None)` turns this red, and turns
    nothing else red.
    """
    from app.services import fair_housing_watch as fhw

    await _clear()
    await _make_agency()
    try:
        await _inbound("Three bedrooms, two baths, garage.", "+13035551008")
        await _inbound("La casa tiene tres habitaciones.", "+13035551009")

        async with get_bypass_session_factory()() as db:
            stored = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM messages WHERE org_id = :o "
                        "AND fair_housing_flags = '[]'::jsonb"
                    ),
                    {"o": AGENCY},
                )
            ).scalar()
        assert stored == 2, f"expected two screened-clean rows, got {stored}"

        calls: list[tuple[str, str]] = []

        async def _send(subject: str, body: str) -> bool:
            calls.append((subject, body))
            return True

        with patch.object(fhw, "send_operator_alert", _send), patch.object(
            fhw, "undeliverable_reason", lambda: None
        ):
            assert await fhw.run_fair_housing_tick() == fhw.CLEAN
            assert calls == []

            async with get_bypass_session_factory()() as db:
                row = (
                    await db.execute(
                        select(MonitorState).where(MonitorState.key == fhw.WATCH_KEY)
                    )
                ).scalar_one()
                assert row.alerted_state == fhw.CLEAN
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_an_unconfigured_alert_channel_is_said_once_not_retried() -> None:
    """With no sender configured, no number of attempts reaches anybody.

    The distinction `undeliverable_reason` draws is between "this attempt
    failed" and "no attempt can succeed", and only the first deserves a retry.
    Looping on the second produces an identical log line every five minutes
    forever, which is how a real alert gets lost in the noise later.
    """
    from app.services import fair_housing_watch as fhw

    await _clear()
    await _make_agency()
    try:
        await _inbound("This home is perfect for families.", "+13035551005")

        calls: list[tuple[str, str]] = []

        async def _send(subject: str, body: str) -> bool:
            calls.append((subject, body))
            return True

        with patch.object(fhw, "send_operator_alert", _send), patch.object(
            fhw, "undeliverable_reason", lambda: "OPS_ALERT_FROM is not set"
        ):
            assert await fhw.run_fair_housing_tick() == fhw.FLAGGED
            assert calls == [], "it tried to send with no channel configured"

            async with get_bypass_session_factory()() as db:
                row = (
                    await db.execute(
                        select(MonitorState).where(MonitorState.key == fhw.WATCH_KEY)
                    )
                ).scalar_one()
                # Consumed on purpose: retrying cannot help until a human edits
                # the configuration, and /api/v1/health carries the state.
                assert row.alerted_state == fhw.FLAGGED
                assert row.alerts_today == 0, "an impossible send charged budget"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_a_flag_just_after_midnight_is_still_reported() -> None:
    """The UTC midnight hole, closed — with the clock frozen so it is provable.

    The first version scoped the reading to the calendar day, which produced two
    defects with one cause. A flagged reply landing in the up-to-300s gap
    between 00:00 UTC and the next tick was read as "still flagged" against
    yesterday's already-consumed state, so it raised no alert — and because the
    reading could not return to clean within that day, neither did anything else
    for the rest of it. In Denver that window is 18:00-18:05, an active
    messaging hour. The same boundary silently wrote off any alert that had not
    gone out, while the log promised a retry "after the UTC day rolls over" that
    could never happen.

    The clock is frozen on purpose. The first version of THIS test aged the old
    message by 30 hours, which is outside both a rolling 24h window and the
    calendar day — so it passed identically under the bug and proved nothing.
    Measured: reverting the window to `start of UTC day` left it green. The
    message now sits 12 minutes before midnight, which is inside the rolling
    window and outside the calendar day, and that is the only placement where
    the two implementations disagree.
    """
    from app.services import fair_housing_watch as fhw

    frozen = datetime(2026, 8, 27, 0, 2, tzinfo=UTC)
    yesterday_late = datetime(2026, 8, 26, 23, 50, tzinfo=UTC)

    class _FrozenClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # noqa: ARG003
            return frozen

    await _clear()
    await _make_agency()
    try:
        await _inbound("This home is perfect for families.", "+13035551006")
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text("UPDATE messages SET created_at = :t WHERE org_id = :o"),
                {"t": yesterday_late, "o": AGENCY},
            )
            await db.commit()

        calls: list[tuple[str, str]] = []

        async def _send(subject: str, body: str) -> bool:
            calls.append((subject, body))
            return True

        with patch.object(fhw, "send_operator_alert", _send), patch.object(
            fhw, "undeliverable_reason", lambda: None
        ), patch.object(fhw, "datetime", _FrozenClock):
            # 00:02 UTC. The flagged reply is 12 minutes old and belongs to
            # yesterday's calendar day. A day-scoped reading calls this clean
            # and the violation is never mentioned; the rolling window sees it.
            assert await fhw.run_fair_housing_tick() == fhw.FLAGGED, (
                "a reply flagged minutes before midnight vanished at the "
                "calendar boundary"
            )
            assert len(calls) == 1

            # And the other half of the window, which is what makes it a window
            # at all. Age the same reply past 24h: it must stop counting. Without
            # this the sweep could drop its time filter entirely and every test
            # above would still pass — a single old violation would then read as
            # "flagged" forever, and since the alert only fires on a CHANGE, the
            # alarm would never sound again.
            async with get_bypass_session_factory()() as db:
                await db.execute(
                    text("UPDATE messages SET created_at = :t WHERE org_id = :o"),
                    {"t": datetime(2026, 8, 25, 18, 0, tzinfo=UTC), "o": AGENCY},
                )
                await db.commit()

            assert await fhw.run_fair_housing_tick() == fhw.CLEAN, (
                "a violation older than the window is still being counted; the "
                "reading can never return to clean and the alarm never re-arms"
            )
            assert len(calls) == 1, "a clean reading sent mail"
    finally:
        await _clear()


@pytest.mark.asyncio
async def test_the_watch_is_actually_scheduled() -> None:
    """A watcher nobody runs is a file, not a watchdog.

    This repo has paid for that once already: a producer was written, tested
    and never added to any schedule, so it sat inert while everyone assumed it
    was working. Every test above drives `run_fair_housing_tick` by hand, which
    proves the function and says nothing about whether production ever calls
    it. This reads the loop's AST and fails if the call is removed.

    Also pins the separate try/except: the first version shared one handler
    with the LLM monitor, so a fair-housing failure was logged as "LLM monitor
    tick failed" and pointed whoever was debugging at the wrong module.
    """
    import ast
    import inspect

    from app import main as app_main

    tree = ast.parse(inspect.getsource(app_main))
    loop = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_llm_monitor_loop"
    )

    called = {
        node.func.id
        for node in ast.walk(loop)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "run_fair_housing_tick" in called, (
        "nothing in _llm_monitor_loop calls run_fair_housing_tick; the watch "
        "exists but never runs"
    )

    # Two handlers, so neither watch can hide or misattribute the other's failure.
    handlers = [n for n in ast.walk(loop) if isinstance(n, ast.Try)]
    assert len(handlers) >= 2, (
        "the two watches share one try/except; a failure in either is reported "
        "under the other's name"
    )


@pytest.mark.asyncio
async def test_a_none_written_to_the_column_becomes_sql_null() -> None:
    """`none_as_null=True` on the column, exercised directly.

    SQLAlchemy's default for JSON columns stores a Python `None` as the JSON
    value `null`, which is NOT SQL NULL. That shipped first, and it made
    `fair_housing_flags IS NOT NULL` true for every screened reply — the
    watcher would have reported a flagged day, every day.

    The reply path no longer writes `None` (it writes `[]` for clean), so that
    bug is no longer reachable from there and no other test exercises the flag
    any more. It is still the right setting for the next writer, and a guard
    nobody exercises is a guard that quietly stops working, so this writes
    `None` on purpose and reads the answer back in SQL — the ORM reports both
    forms as Python None and cannot tell them apart.
    """
    await _clear()
    await _make_agency()
    try:
        # Reuse the normal path to get a real conversation, then write the
        # column by hand — the reply path never passes None any more, which is
        # exactly why this guard needs its own exercise.
        await _inbound("Three bedrooms.", "+13035551099")
        async with get_bypass_session_factory()() as db:
            conv_id = (
                await db.execute(
                    text("SELECT id FROM conversations WHERE org_id = :o LIMIT 1"),
                    {"o": AGENCY},
                )
            ).scalar()

        async with get_bypass_session_factory()() as db:
            msg = Message(
                org_id=AGENCY,
                conversation_id=conv_id,
                direction=MessageDirection.OUTBOUND,
                sender=MessageSender.AGENT,
                content="written with an explicit None",
                fair_housing_flags=None,
            )
            db.add(msg)
            await db.commit()
            msg_id = msg.id

        async with get_bypass_session_factory()() as db:
            is_sql_null, as_text = (
                await db.execute(
                    text(
                        "SELECT fair_housing_flags IS NULL, "
                        "fair_housing_flags::text FROM messages WHERE id = :i"
                    ),
                    {"i": msg_id},
                )
            ).one()
        assert is_sql_null is True, (
            f"a Python None reached the column as {as_text!r}, not SQL NULL; "
            "none_as_null is off and IS NOT NULL will match screened rows"
        )
    finally:
        await _clear()

