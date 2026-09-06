"""The landing beacon: a second unauthenticated write, and its guard rails.

Like `test_public_capture.py`, every test drives the real ASGI stack rather
than the handler, and for the same reason: the suite's conftest binds the
default organization into every test, so calling the service directly would
hand a test the one thing production does not have — a tenant already bound.
A row that appears here proves the handler resolved and bound one itself.

The single most important test in this file is the one that spends the beacon
budget and then submits the form. That is the failure this endpoint could
cause: analytics quietly eating the capacity of the thing that produces leads.
"""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.api.v1.public import (
    EVENTS_MAX_BODY,
    EVENTS_MAX_PER_BATCH,
    EVENTS_PER_IP_LIMIT,
    reset_rate_limits,
)
from app.db.base import get_bypass_session_factory
from app.main import app
from app.models.channel_route import CHANNEL_WEB
from app.services import tenant_resolver

SESSION = "0123456789abcdef0123456789abcdef"
OTHER_SESSION = "fedcba9876543210fedcba9876543210"
SLUG = "beacon-agency"
FORM = "beacon-agency-form"

# Every request here names its own agency by form key rather than leaning on
# the single-tenant fallback. That fallback depends on how many organizations
# happen to exist when the file runs, so a test built on it passes or fails
# according to which OTHER test file ran first — and this suite has files that
# leave an agency behind. `test_public_capture.py` owns the fallback's coverage;
# what belongs here is that the beacon resolves a named tenant and writes into
# it, which is also the shape a second real agency will have.

UA_INSTAGRAM = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 Instagram 331.0.0.35.90 (iPhone14,3; iOS 17_5)"
)


@pytest.fixture(autouse=True)
async def org() -> object:
    reset_rate_limits()
    await _wipe()
    org_id = await _seed()
    yield org_id
    reset_rate_limits()
    await _wipe()


async def _seed() -> int:
    async with get_bypass_session_factory()() as db:
        org_id = (
            await db.execute(
                text(
                    "INSERT INTO organizations (name, slug, status, plan) "
                    "VALUES (:n, :s, 'active', 'pilot') RETURNING id"
                ),
                {"n": SLUG, "s": SLUG},
            )
        ).scalar_one()
        await db.execute(
            text(
                "INSERT INTO channel_routes (org_id, channel, destination) "
                "VALUES (:o, :c, :d)"
            ),
            {"o": org_id, "c": CHANNEL_WEB, "d": FORM},
        )
        await db.commit()
    tenant_resolver.reset_cache()
    return org_id


async def _wipe() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(
            text("DELETE FROM landing_sessions WHERE session_key IN (:a, :b)"),
            {"a": SESSION, "b": OTHER_SESSION},
        )
        await db.execute(
            text("DELETE FROM leads WHERE email LIKE :pat"), {"pat": "%@beacon.test"}
        )
        await db.execute(text("DELETE FROM organizations WHERE slug = :s"), {"s": SLUG})
        await db.commit()
    tenant_resolver.reset_cache()


def _batch(*events: tuple[str, dict], **extra) -> dict:
    payload = {
        "form": FORM,
        "session": SESSION,
        "path": "/",
        "lang": "en",
        "screen_w": 390,
        "events": [{"t": t, "meta": m} for t, m in events] or [{"t": "page_view"}],
    }
    payload.update(extra)
    return payload


async def _beacon(payload: dict | str, **headers: str) -> int:
    """POST as the browser really does it: a text/plain body from sendBeacon."""
    body = payload if isinstance(payload, str) else json.dumps(payload)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/api/v1/public/landing",
            content=body,
            headers={"content-type": "text/plain", **headers},
        )
    return response.status_code


async def _session_row(key: str = SESSION) -> dict | None:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(
                text("SELECT * FROM landing_sessions WHERE session_key = :k"), {"k": key}
            )
        ).mappings().first()
    return dict(row) if row else None


async def _event_rows(key: str = SESSION) -> list[dict]:
    async with get_bypass_session_factory()() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT e.type, e.meta, e.org_id FROM landing_events e "
                    "JOIN landing_sessions s ON s.id = e.session_id "
                    "WHERE s.session_key = :k ORDER BY e.id"
                ),
                {"k": key},
            )
        ).mappings().all()
    return [dict(r) for r in rows]


class TestWritingASession:
    async def test_a_batch_creates_the_session_and_its_events(self, org: int) -> None:
        status = await _beacon(
            _batch(
                ("page_view", {}),
                ("section_view", {"section": "about"}),
                ("scroll", {"pct": 50}),
                referrer="https://www.tiktok.com/@denverhomestory",
            ),
            **{"user-agent": UA_INSTAGRAM},
        )
        assert status == 204

        row = await _session_row()
        assert row is not None
        assert row["org_id"] == org
        assert row["source"] == "tiktok"
        assert row["referrer_host"] == "tiktok.com"
        assert row["device"] == "phone"
        assert row["in_app"] == "instagram"
        assert row["max_scroll_pct"] == 50
        assert row["sections_viewed"] == ["about"]
        assert row["event_count"] == 3
        assert row["lead_id"] is None
        assert [e["type"] for e in await _event_rows()] == [
            "page_view",
            "section_view",
            "scroll",
        ]

    async def test_the_raw_user_agent_is_nowhere_on_the_row(self) -> None:
        """The whole privacy claim rests on this. A user agent is close enough
        to an identifier that storing it would undo not setting a cookie."""
        await _beacon(_batch(("page_view", {})), **{"user-agent": UA_INSTAGRAM})
        row = await _session_row()
        assert all(
            "Instagram 331" not in str(value) for value in row.values()
        ), "the user agent reached a column"

    async def test_a_second_batch_merges_into_the_same_row(self) -> None:
        await _beacon(_batch(("scroll", {"pct": 75}), ("cta_click", {})))
        await _beacon(
            _batch(
                ("scroll", {"pct": 25}),
                ("cta_click", {}),
                ("tel_click", {"where": "hero"}),
                ("form_start", {}),
            )
        )
        row = await _session_row()
        assert row["max_scroll_pct"] == 75  # never goes backwards
        assert row["cta_clicks"] == 2
        assert row["tel_clicks"] == 1
        assert row["form_started_at"] is not None
        assert row["event_count"] == 6

    async def test_the_first_touch_wins_on_attribution(self) -> None:
        """A reload with a different query string has not changed where the
        visitor came from. Same rule the lead's own attribution follows."""
        await _beacon(_batch(("page_view", {}), utm={"utm_source": "youtube"}))
        await _beacon(_batch(("page_view", {}), utm={"utm_source": "tiktok"}))
        row = await _session_row()
        assert row["utm_source"] == "youtube"
        assert row["source"] == "youtube"

    async def test_geo_headers_land_and_their_absence_is_null(self) -> None:
        await _beacon(
            _batch(("page_view", {})),
            **{"cf-ipcountry": "US", "cf-region-code": "CO", "cf-ipcity": "Denver"},
        )
        row = await _session_row()
        assert (row["country"], row["region"], row["city"]) == ("US", "CO", "Denver")

        await _beacon(_batch(("page_view", {}), session=OTHER_SESSION))
        other = await _session_row(OTHER_SESSION)
        assert (other["country"], other["region"], other["city"]) == (None, None, None)

    async def test_only_whitelisted_attribution_is_kept(self) -> None:
        await _beacon(
            _batch(
                ("page_view", {}),
                utm={"utm_source": "youtube", "utm_campaign": "video", "evil": "x"},
            )
        )
        row = await _session_row()
        assert row["utm_source"] == "youtube"
        assert row["utm_campaign"] == "video"
        assert "evil" not in str(row)


class TestRefusals:
    @pytest.mark.parametrize(
        "payload",
        [
            {"session": SESSION, "events": [{"t": "not_a_real_event"}]},
            {"session": "short", "events": [{"t": "page_view"}]},
            {"session": SESSION, "events": []},
            {"session": SESSION, "events": [{"t": "page_view"}] * (EVENTS_MAX_PER_BATCH + 1)},
            {"session": SESSION, "events": [{"t": "page_view"}], "surprise": 1},
            {"events": [{"t": "page_view"}]},
        ],
    )
    async def test_a_bad_batch_is_refused_and_writes_nothing(self, payload: dict) -> None:
        assert await _beacon(payload) == 400
        assert await _session_row() is None

    async def test_a_malformed_body_is_refused(self) -> None:
        assert await _beacon("{not json") == 400
        assert await _beacon("") == 400

    async def test_an_oversized_body_is_refused_before_it_is_parsed(self) -> None:
        payload = _batch(("page_view", {}), path="x" * 100)
        payload["referrer"] = "y" * (EVENTS_MAX_BODY + 100)
        assert await _beacon(payload) == 413
        assert await _session_row() is None

    async def test_a_full_legitimate_batch_still_fits(self) -> None:
        """The size cap has to admit the largest batch the tracker can send, or
        it is a refusal of ordinary traffic dressed as a security control."""
        events = [
            ("section_view", {"section": "markets", "pad": "z" * 120})
            for _ in range(EVENTS_MAX_PER_BATCH)
        ]
        payload = _batch(*events, referrer="https://www.tiktok.com/" + "r" * 400)
        payload["utm"] = {
            "utm_source": "t" * 200,
            "utm_medium": "m" * 200,
            "utm_campaign": "c" * 200,
            "utm_content": "n" * 200,
            "utm_term": "e" * 200,
        }
        assert len(json.dumps(payload)) < EVENTS_MAX_BODY
        assert await _beacon(payload) == 204

    async def test_oversized_metadata_is_refused(self) -> None:
        assert await _beacon(_batch(("page_view", {f"k{i}": "v" for i in range(6)}))) == 400

    @pytest.mark.parametrize(
        "meta",
        [
            {"k" * 41: "v"},          # a key longer than the bound
            {"pct": 66.7},            # a float where a label or an integer belongs
            {"where": ["hero"]},      # a structure, not a value
        ],
    )
    async def test_bad_metadata_is_refused_and_writes_nothing(self, meta: dict) -> None:
        assert await _beacon(_batch(("page_view", meta))) == 400
        assert await _session_row() is None

    async def test_metadata_that_carries_no_usable_value_is_dropped_not_refused(self) -> None:
        """A null or a boolean is not a label and not a number. Dropping the
        entry keeps the other 24 events in the batch, which refusing would
        throw away."""
        assert await _beacon(_batch(("page_view", {"a": None, "b": True, "c": "kept"}))) == 204
        assert [e["meta"] for e in await _event_rows()] == [{"c": "kept"}]

    async def test_a_path_of_only_a_query_string_becomes_the_root(self) -> None:
        assert await _beacon(_batch(("page_view", {}), path="?utm_source=x")) == 204
        assert (await _session_row())["landing_path"] == "/"


class TestBudgets:
    async def test_beacons_cannot_spend_the_lead_captures_budget(self) -> None:
        """The reason these counters are separate. One attentive visitor sends
        four beacons; sharing the capture budget of five would mean reading the
        page carefully costs you the ability to submit the form."""
        for _ in range(EVENTS_PER_IP_LIMIT):
            assert await _beacon(_batch(("page_view", {}))) == 204
        assert await _beacon(_batch(("page_view", {}))) == 429

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.post(
                "/api/v1/public/leads",
                json={
                    "form": FORM,
                    "name": "Budget Check",
                    "email": "budget@beacon.test",
                    "message": "still able to submit",
                },
            )
        assert response.status_code == 202, response.text


class TestDroppingQuietly:
    """Three ways this endpoint declines, and all of them answer the same.

    The sameness is the security property: a public endpoint that distinguishes
    "no such agency" from "that agency, but something broke" is an oracle for
    enumerating an operator's tenants, and the sender — a beacon — has nothing
    it could do with the difference anyway.
    """

    async def test_an_unknown_form_key_writes_nothing(self) -> None:
        assert await _beacon(_batch(("page_view", {}), form="no-such-agency")) == 204
        assert await _session_row() is None

    async def test_the_platform_ceiling_refuses_without_writing(self, monkeypatch) -> None:
        import app.api.v1.public as public

        monkeypatch.setattr(public, "EVENTS_GLOBAL_LIMIT", 0)
        assert await _beacon(_batch(("page_view", {}))) == 429
        assert await _session_row() is None

    async def test_a_database_failure_is_swallowed(self, monkeypatch) -> None:
        """A beacon has nobody to report to, and the marketing page must not
        change behaviour because analytics had a bad minute."""
        import app.api.v1.public as public

        def _boom(*args, **kwargs):
            raise RuntimeError("no")

        monkeypatch.setattr(public, "pg_insert", _boom)
        assert await _beacon(_batch(("page_view", {}))) == 204
        assert await _session_row() is None


class TestTheSwitch:
    async def test_disabled_writes_nothing_and_still_answers(self, monkeypatch) -> None:
        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "LANDING_EVENTS_ENABLED", False)
        assert await _beacon(_batch(("page_view", {}))) == 204
        assert await _session_row() is None


class TestJoiningTheFunnel:
    async def _submit(self, **extra) -> int:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            response = await c.post(
                "/api/v1/public/leads",
                json={
                    "form": FORM,
                    "name": "Beacon Lead",
                    "email": "lead@beacon.test",
                    "message": "I want to sell",
                    **extra,
                },
            )
        return response.status_code

    async def test_a_submission_claims_its_session(self) -> None:
        await _beacon(_batch(("page_view", {}), ("form_start", {})))
        assert await self._submit(session_id=SESSION) == 202

        row = await _session_row()
        assert row["lead_id"] is not None
        assert row["form_submitted_at"] is not None

    async def test_a_session_that_does_not_exist_is_not_an_error(self) -> None:
        assert await self._submit(session_id=OTHER_SESSION) == 202

    async def test_a_malformed_session_id_costs_the_row_not_the_lead(self) -> None:
        """A bug in the tracker's key generator must not stop somebody from
        becoming a lead. A `pattern` on this field would have made it a 422 on
        the whole submission, which inverts the rule the link is built on."""
        assert await self._submit(session_id="../../etc") == 202
        async with get_bypass_session_factory()() as db:
            found = (
                await db.execute(
                    text("SELECT id FROM leads WHERE email = :e"), {"e": "lead@beacon.test"}
                )
            ).scalar_one_or_none()
        assert found is not None

    async def test_the_lead_survives_a_broken_link(self, monkeypatch) -> None:
        """The join is analytics; the lead is the product. If this update
        fails the visitor must still see a success, or they resubmit and the
        agency gets the same person twice."""
        import app.api.v1.public as public

        real = public.update

        def _boom(*args, **kwargs):
            raise RuntimeError("no")

        await _beacon(_batch(("page_view", {})))
        monkeypatch.setattr(public, "update", _boom)
        try:
            assert await self._submit(session_id=SESSION) == 202
        finally:
            monkeypatch.setattr(public, "update", real)

        async with get_bypass_session_factory()() as db:
            found = (
                await db.execute(
                    text("SELECT id FROM leads WHERE email = :e"), {"e": "lead@beacon.test"}
                )
            ).scalar_one_or_none()
        assert found is not None
        assert (await _session_row())["lead_id"] is None


class TestPurge:
    async def test_old_events_go_and_sessions_stay(self, org: int) -> None:
        from app.services.landing_analytics import purge_landing_events

        await _beacon(_batch(("page_view", {}), ("cta_click", {})))
        async with get_bypass_session_factory()() as db:
            await db.execute(
                text(
                    "UPDATE landing_events SET at = now() - interval '91 days' "
                    "WHERE session_id = (SELECT id FROM landing_sessions "
                    "WHERE session_key = :k)"
                ),
                {"k": SESSION},
            )
            await db.commit()
        await _beacon(_batch(("scroll", {"pct": 30})))

        from app.db.base import get_session_factory
        from app.services.tenant_context import org_scope

        with org_scope(org):
            async with get_session_factory()() as db:
                deleted = await purge_landing_events(db)

        assert deleted == 2
        remaining = await _event_rows()
        assert [e["type"] for e in remaining] == ["scroll"]
        assert await _session_row() is not None


async def test_production_actually_runs_the_purge() -> None:
    """The purge is wired into a loop that really ticks.

    Every test above drives `purge_landing_events` by hand, which proves the
    function and says nothing about whether anything calls it. This repo has
    shipped a correct function nobody scheduled before — the fair-housing watch
    sat inert for a version — so the wiring gets its own assertion, read from
    the loop's AST rather than from a comment.

    It also pins the per-org sweep: the table is under RLS, so a bare call with
    no organization bound would match no rows and delete nothing, for ever,
    while looking exactly like a purge that had nothing to do.
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
    swept = {
        arg.id
        for node in ast.walk(loop)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_for_every_org"
        for arg in node.args
        if isinstance(arg, ast.Name)
    }
    assert "purge_landing_events" in swept, (
        "nothing sweeps purge_landing_events per organization; raw events "
        "either grow for ever or are deleted with no tenant bound, which under "
        "RLS deletes nothing at all"
    )


class TestTheDailyCap:
    """The only thing bounding how many PERMANENT rows a stranger can create.

    The rate limit bounds the speed of writing them, not the number: 60 posts
    per address per ten minutes is 8,640 permanent session rows a day from one
    address, and sessions are never deleted by age because that would rewrite
    the denominator of every historical funnel. So the bound has to be here.
    """

    async def _seed_sessions(self, org_id: int, n: int) -> None:
        """Straight past the endpoint. Driving the cap through HTTP would test
        the rate limiter instead."""
        async with get_bypass_session_factory()() as db:
            for i in range(n):
                await db.execute(
                    text(
                        "INSERT INTO landing_sessions "
                        "(org_id, session_key, first_seen_at, last_seen_at, source) "
                        "VALUES (:o, :k, now(), now(), 'direct')"
                    ),
                    {"o": org_id, "k": f"cap{i:028d}"},
                )
            await db.commit()

    async def _cleanup_seeded(self) -> None:
        async with get_bypass_session_factory()() as db:
            await db.execute(text("DELETE FROM landing_sessions WHERE session_key LIKE 'cap%'"))
            await db.commit()

    async def test_a_new_visit_is_refused_once_the_day_is_full(
        self, org: int, monkeypatch
    ) -> None:
        import app.api.v1.public as public
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "LANDING_SESSIONS_PER_DAY", 2)
        assert public.get_settings().LANDING_SESSIONS_PER_DAY == 2
        try:
            await self._seed_sessions(org, 2)
            assert await _beacon(_batch(("page_view", {}))) == 204
            assert await _session_row() is None
        finally:
            await self._cleanup_seeded()

    async def test_a_visit_already_being_recorded_keeps_merging(
        self, org: int, monkeypatch
    ) -> None:
        """A real visitor must never be truncated mid-page. The cap is on
        creating a session, not on the beacons of one that already exists."""
        from app.config import get_settings

        assert await _beacon(_batch(("scroll", {"pct": 20}))) == 204
        monkeypatch.setattr(get_settings(), "LANDING_SESSIONS_PER_DAY", 0)
        assert await _beacon(_batch(("scroll", {"pct": 90}), ("cta_click", {}))) == 204
        row = await _session_row()
        assert row["max_scroll_pct"] == 90
        assert row["cta_clicks"] == 1

    async def test_one_agencys_cap_does_not_reach_another(
        self, org: int, monkeypatch
    ) -> None:
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "LANDING_SESSIONS_PER_DAY", 1)
        try:
            # Org 1 (the default agency) fills its own day; ours is untouched.
            await self._seed_sessions(1, 1)
            assert await _beacon(_batch(("page_view", {}))) == 204
            assert await _session_row() is not None
        finally:
            await self._cleanup_seeded()


class TestConcurrentBeacons:
    async def test_two_batches_give_the_same_totals_in_either_order(self) -> None:
        """Applied as SQL expressions, so the database resolves the overlap.

        Folded in Python against a loaded row, these two batches lose a click
        and the scroll depth goes DOWN — the second beacon writes a total it
        computed from the first beacon's starting point.
        """
        await _beacon(_batch(("scroll", {"pct": 90}), ("cta_click", {})))
        await _beacon(_batch(("scroll", {"pct": 30}), ("cta_click", {})))
        forward = await _session_row()

        await _wipe()
        await _seed()
        await _beacon(_batch(("scroll", {"pct": 30}), ("cta_click", {})))
        await _beacon(_batch(("scroll", {"pct": 90}), ("cta_click", {})))
        backward = await _session_row()

        for field in ("max_scroll_pct", "cta_clicks", "event_count"):
            assert forward[field] == backward[field], field
        assert forward["max_scroll_pct"] == 90
        assert forward["cta_clicks"] == 2


async def test_the_path_never_carries_a_query_string() -> None:
    """`location.search` can hold an email address. The promise is that nothing
    identifying is stored, so the cut happens server-side where a future client
    cannot forget it."""
    assert await _beacon(_batch(("page_view", {}), path="/?utm_source=x&email=bob@x.com")) == 204
    assert (await _session_row())["landing_path"] == "/"


class TestCalculatorResult:
    """`/calculator` reports that the visitor saw a figure. A raw event, not a
    session column: the funnel between "opened the page" and "left their
    email" is read from `landing_events` until `/analytics` learns to split
    pages (backlog I-3)."""

    async def test_it_is_accepted_and_stored_with_its_meta(self) -> None:
        status = await _beacon(
            _batch(
                ("page_view", {}),
                ("calculator_result", {"price_k": 310, "capped": "rent", "credit": "good"}),
            )
        )
        assert status == 204
        rows = await _event_rows()
        assert [e["type"] for e in rows] == ["page_view", "calculator_result"]
        assert rows[1]["meta"] == {"price_k": 310, "capped": "rent", "credit": "good"}
        # On the session row it is one more event and nothing else: no
        # dedicated counter, no flag (that is backlog I-3).
        row = await _session_row()
        assert row is not None
        assert row["event_count"] == 2
