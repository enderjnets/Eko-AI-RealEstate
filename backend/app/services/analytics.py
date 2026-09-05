"""The numbers behind `/analytics`, one function per section.

A service rather than a fat handler, and the reason is testing: each section
seeds its own rows and asserts its own values, so a test about response times
does not have to invent visits and deals to get there.

**Two decisions that shape every query here.**

*The day is the agency's day.* Every grouping goes through
`timezone(<agency tz>, col)` before `date()`. Grouped in UTC, a lead that
arrived at 23:30 in Denver lands on tomorrow's report, and the two busiest
hours of the evening are permanently attributed to the wrong day — a six-hour
error that is invisible because every individual number looks plausible.

*The range applies to the lead, not to the thing that happened.* A lead created
in August and called back today counts as "called back" in August's report,
because the question the funnel answers is "of the leads that arrived then, how
many did we reach" — not "how many calls did we make this week". Counting it the
other way makes the conversion of any closed month change every time someone
touches an old lead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Float, Select, and_, case, cast, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CallLog,
    ContentPublication,
    Conversation,
    LandingSession,
    Lead,
    LeadEvent,
    LeadStatus,
    Message,
    MessageDirection,
    MessageSender,
    Visit,
    VisitStatus,
)
from app.services import video_metrics

# The office's day, when the agency has not said otherwise. Denver because that
# is where this product's only customer is; a second agency sets its own.
DEFAULT_TZ = "America/Denver"


@dataclass(frozen=True)
class Window:
    """A range of instants, and the timezone whose days it is made of."""

    start: datetime
    end: datetime
    tz: str

    def day(self, column):
        """The local calendar day of a timestamp column."""
        return func.date(func.timezone(self.tz, column))

    def within(self, column):
        return and_(column >= self.start, column < self.end)


def _days(window: Window) -> list[str]:
    """Every day in the range, so a quiet Tuesday is a zero and not a gap.

    A chart drawn from the rows alone silently closes up empty days, which
    turns a week with two dead days into a smooth line that never happened.

    **Converted to the agency's zone before taking the date.** The window is
    stored as UTC instants, and `.date()` on those is a UTC day: asking for the
    1st to the 7th in Denver ends at 06:00 UTC on the 8th, so the naive version
    produced an eighth column that was six hours long and always empty.
    """
    zone = ZoneInfo(window.tz)
    first = window.start.astimezone(zone).date()
    last = (window.end - timedelta(microseconds=1)).astimezone(zone).date()
    out: list[str] = []
    cursor: date = first
    while cursor <= last:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


async def _scalar(db: AsyncSession, stmt: Select) -> int:
    return int((await db.execute(stmt)).scalar() or 0)


# ── Traffic: what happened on the landing page ───────────────────────────


async def traffic(db: AsyncSession, w: Window) -> dict:
    """Visits, how far they read, and where they came from.

    Read off `landing_sessions` and never off `landing_events`: the events are
    purged after ninety days, so summing them would make last quarter's numbers
    shrink every night. The session row carries the same facts already merged.
    """
    base = LandingSession.first_seen_at
    scope = w.within(base)

    totals = (
        await db.execute(
            select(
                func.count(),
                # "Engaged" is a judgement, so it is stated once and here: read
                # past halfway, or reached two different sections. Either alone
                # misses a real reader — a short screen scrolls further, and a
                # long one shows fewer sections.
                func.count(
                    case(
                        (
                            or_(
                                LandingSession.max_scroll_pct >= 50,
                                func.jsonb_array_length(LandingSession.sections_viewed) >= 2,
                            ),
                            1,
                        )
                    )
                ),
                func.coalesce(func.avg(LandingSession.max_scroll_pct), 0),
                func.coalesce(func.sum(LandingSession.cta_clicks), 0),
                func.coalesce(func.sum(LandingSession.tel_clicks), 0),
                func.count(LandingSession.form_started_at),
                func.count(LandingSession.form_submitted_at),
            ).where(scope)
        )
    ).one()

    # One expression object, used in both places. Calling `w.day()` twice would
    # emit two bind parameters for the same timezone, and Postgres then sees two
    # different expressions and refuses to group by either.
    day = w.day(base).label("day")
    by_day_rows = (
        await db.execute(select(day, func.count()).where(scope).group_by(day))
    ).all()
    seen = {str(d): n for d, n in by_day_rows}

    async def _breakdown(column, limit: int | None = None) -> list[dict]:
        stmt = (
            select(column, func.count(), func.count(LandingSession.lead_id))
            .where(scope)
            .group_by(column)
            .order_by(func.count().desc())
        )
        if limit:
            stmt = stmt.limit(limit)
        return [
            {"name": name or "unknown", "sessions": n, "leads": leads}
            for name, n, leads in (await db.execute(stmt)).all()
        ]

    sections = {}
    for name in ("about", "how", "markets", "consult"):
        sections[name] = await _scalar(
            db,
            select(func.count()).where(
                scope,
                LandingSession.sections_viewed.contains([name]),
            ),
        )

    return {
        "sessions": totals[0],
        "engaged": totals[1],
        "avg_scroll_pct": round(float(totals[2]), 1),
        "cta_clicks": int(totals[3]),
        "tel_clicks": int(totals[4]),
        "form_starts": totals[5],
        "form_submits": totals[6],
        "by_day": [{"date": d, "sessions": seen.get(d, 0)} for d in _days(w)],
        "by_source": await _breakdown(LandingSession.source),
        "by_device": await _breakdown(LandingSession.device),
        "by_in_app": await _breakdown(LandingSession.in_app),
        "by_country": await _breakdown(LandingSession.country, 10),
        "by_region": await _breakdown(LandingSession.region, 10),
        "by_city": await _breakdown(LandingSession.city, 10),
        "by_lang": await _breakdown(LandingSession.lang),
        "sections": sections,
    }


# ── Leads: who arrived, from where, and what happened to them ────────────


async def leads(db: AsyncSession, w: Window) -> dict:
    scope = w.within(Lead.created_at)
    total = await _scalar(db, select(func.count()).where(scope).select_from(Lead))

    by_status_rows = (
        await db.execute(
            select(Lead.status, func.count()).where(scope).group_by(Lead.status)
        )
    ).all()
    counts = {s.value if hasattr(s, "value") else str(s): n for s, n in by_status_rows}

    by_intent_rows = (
        await db.execute(
            select(Lead.intent, func.count()).where(scope).group_by(Lead.intent)
        )
    ).all()

    # Channel of the FIRST conversation: a lead who wrote by SMS and later got a
    # call arrived by SMS, and the report is about arrival.
    first_conv = (
        select(
            Conversation.lead_id.label("lead_id"),
            func.min(Conversation.started_at).label("first_at"),
        )
        .group_by(Conversation.lead_id)
        .subquery()
    )
    by_channel_rows = (
        await db.execute(
            select(Conversation.channel, func.count(distinct(Lead.id)))
            .select_from(Lead)
            .join(first_conv, first_conv.c.lead_id == Lead.id)
            .join(
                Conversation,
                and_(
                    Conversation.lead_id == Lead.id,
                    Conversation.started_at == first_conv.c.first_at,
                ),
            )
            .where(scope)
            .group_by(Conversation.channel)
        )
    ).all()

    # Where the web leads came from. `no_web` is not a failure to measure: it is
    # a lead that never touched the landing page — imported, called in, or found
    # by discovery — and folding it into `direct` would invent web traffic.
    # Grouped in Python, not in SQL. `Lead.meta` is a plain JSON column, and
    # indexing into it produces an expression SQLAlchemy cannot cache, so the
    # query fails outright rather than merely being slow. The rows are small
    # and few — the whole point of this table is that leads are precious, not
    # numerous — and the day that stops being true, the fix is a real column,
    # not a cleverer query.
    metas = (await db.execute(select(Lead.meta).where(scope))).scalars().all()
    by_source: dict[str, int] = {}
    for meta in metas:
        attribution = (meta or {}).get("attribution") or {}
        # `no_web` is not a measurement failure: it is a lead that never
        # touched the landing page — imported, phoned in, found by discovery —
        # and folding it into `direct` would invent web traffic that never
        # happened.
        key = attribution.get("utm_source") or attribution.get("referrer") or "no_web"
        by_source[key] = by_source.get(key, 0) + 1

    day = w.day(Lead.created_at).label("day")
    day_rows = (
        await db.execute(select(day, func.count()).where(scope).group_by(day))
    ).all()
    seen = {str(d): n for d, n in day_rows}

    return {
        "total": total,
        "by_status": counts,
        "by_intent": {
            (i.value if hasattr(i, "value") else str(i or "unknown")): n
            for i, n in by_intent_rows
        },
        "by_channel": {str(c): n for c, n in by_channel_rows},
        "by_source": by_source,
        "new_by_day": [{"date": d, "leads": seen.get(d, 0)} for d in _days(w)],
    }


# ── Response: how long we take, and who answers ──────────────────────────


def _real_outbound():
    """An outbound message that a person could actually receive.

    `internal=True` is a note an advisor left on the thread. Counting it as a
    reply is the defect this section exists to fix: the old metric averaged
    every outbound row, so a lead nobody ever answered showed a two-minute
    response time because somebody typed "called, no answer" into the notes.
    """
    return and_(
        Message.direction == MessageDirection.OUTBOUND,
        Message.internal.is_(False),
    )


async def response(db: AsyncSession, w: Window) -> dict:
    # First real reply per conversation, for conversations whose LEAD arrived in
    # range — the window is about the leads, not about when we got around to it.
    first_reply = (
        select(
            Message.conversation_id.label("cid"),
            func.min(Message.created_at).label("replied_at"),
        )
        .where(_real_outbound())
        .group_by(Message.conversation_id)
        .subquery()
    )

    rows = (
        await db.execute(
            select(
                func.extract(
                    "epoch", first_reply.c.replied_at - Conversation.started_at
                )
            )
            .select_from(Conversation)
            .join(Lead, Lead.id == Conversation.lead_id)
            .join(first_reply, first_reply.c.cid == Conversation.id)
            .where(w.within(Lead.created_at))
        )
    ).scalars().all()
    seconds = sorted(float(s) for s in rows if s is not None and s >= 0)

    def _pick(fraction: float) -> float | None:
        if not seconds:
            return None
        index = min(len(seconds) - 1, int(len(seconds) * fraction))
        return round(seconds[index], 1)

    # Human, canned fallback, or a model. The middle one matters: a fallback is
    # what goes out when every provider is unreachable, and counting it as an AI
    # reply hides an outage behind a healthy-looking response time.
    kind_col = case(
        (Message.sender == MessageSender.HUMAN, "human"),
        (Message.llm_provider == "fallback", "fallback"),
        else_="ai",
    ).label("kind")
    kind_rows = (
        await db.execute(
            select(kind_col, func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .join(Lead, Lead.id == Conversation.lead_id)
            .where(_real_outbound(), w.within(Lead.created_at))
            .group_by(kind_col)
        )
    ).all()

    # Conversations of in-range leads with no real reply at all. The number the
    # office actually needs: not "how fast were we" but "who is still waiting".
    unanswered = await _scalar(
        db,
        select(func.count())
        .select_from(Conversation)
        .join(Lead, Lead.id == Conversation.lead_id)
        .outerjoin(first_reply, first_reply.c.cid == Conversation.id)
        .where(w.within(Lead.created_at), first_reply.c.replied_at.is_(None)),
    )

    return {
        "first_response_seconds": {
            "median": _pick(0.5),
            "p90": _pick(0.9),
            "avg": round(sum(seconds) / len(seconds), 1) if seconds else None,
        },
        "by_kind": {k: n for k, n in kind_rows},
        "unanswered": unanswered,
    }


# ── Calls, appointments, deals ───────────────────────────────────────────


async def calls(db: AsyncSession, w: Window) -> dict:
    scope = w.within(Lead.created_at)

    inbound = (
        await db.execute(
            select(
                func.count(),
                # Cast, because the duration lives inside JSONB and averaging
                # text gives an error rather than a wrong number — which is the
                # good outcome, but only once.
                func.avg(cast(LeadEvent.meta["duration_seconds"].astext, Float)),
            )
            .select_from(LeadEvent)
            .join(Lead, Lead.id == LeadEvent.lead_id)
            .where(LeadEvent.type == "call_inbound", scope)
        )
    ).one()

    reason_col = LeadEvent.meta["ended_reason"].astext.label("reason")
    reasons = (
        await db.execute(
            select(reason_col, func.count())
            .select_from(LeadEvent)
            .join(Lead, Lead.id == LeadEvent.lead_id)
            .where(LeadEvent.type == "call_inbound", scope)
            .group_by(reason_col)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()

    logged_rows = (
        await db.execute(
            select(CallLog.outcome, func.count())
            .select_from(CallLog)
            .join(Lead, Lead.id == CallLog.lead_id)
            .where(scope)
            .group_by(CallLog.outcome)
        )
    ).all()

    return {
        "inbound": inbound[0],
        "avg_duration_seconds": round(float(inbound[1]), 1) if inbound[1] else None,
        "by_ended_reason": {(r or "unknown"): n for r, n in reasons},
        "logged": sum(n for _, n in logged_rows),
        "by_outcome": {
            (o.value if hasattr(o, "value") else str(o)): n for o, n in logged_rows
        },
    }


async def appointments(db: AsyncSession, w: Window) -> dict:
    scope = w.within(Lead.created_at)
    rows = (
        await db.execute(
            select(Visit.status, func.count())
            .select_from(Visit)
            .join(Lead, Lead.id == Visit.lead_id)
            .where(scope)
            .group_by(Visit.status)
        )
    ).all()
    by_status = {
        (s.value if hasattr(s, "value") else str(s)): n for s, n in rows
    }

    by_purpose = (
        await db.execute(
            select(Visit.purpose, func.count())
            .select_from(Visit)
            .join(Lead, Lead.id == Visit.lead_id)
            .where(scope)
            .group_by(Visit.purpose)
        )
    ).all()

    return {
        "set": sum(by_status.values()),
        "completed": by_status.get(VisitStatus.COMPLETED.value, 0),
        "no_show": by_status.get(VisitStatus.NO_SHOW.value, 0),
        "cancelled": by_status.get(VisitStatus.CANCELLED.value, 0),
        "by_purpose": {
            (p.value if hasattr(p, "value") else str(p or "unknown")): n
            for p, n in by_purpose
        },
    }


async def deals(db: AsyncSession, w: Window, *, with_value: bool) -> dict:
    """Closed business. `with_value` is the admin gate, decided by the router.

    **Both halves are scoped on when it ended**, not on when the lead arrived:
    a deal closed in September is September's revenue even if the lead came in
    June. This is the one section where the question is about the event and not
    about the cohort — and it has to be true on both sides, or `close_rate`
    divides one month's closings by another month's losses and reads like a
    single number.
    """
    won_scope = w.within(Lead.won_at)

    kinds = (
        await db.execute(
            select(Lead.won_kind, func.count(), func.coalesce(func.sum(Lead.won_value), 0))
            .where(won_scope)
            .group_by(Lead.won_kind)
        )
    ).all()

    # Lost is scoped on WHEN IT WAS LOST, not on when the lead arrived — the
    # same cohort as `won` above. Mixed, `close_rate` would divide September's
    # closings by August's arrivals and produce a ratio of two different
    # months that looks like one number.
    lost_at = (
        select(
            LeadEvent.lead_id.label("lead_id"),
            func.max(LeadEvent.at).label("at"),
        )
        .where(LeadEvent.type == "status_changed", LeadEvent.to_status == "lost")
        .group_by(LeadEvent.lead_id)
        .subquery()
    )
    lost_rows = (
        await db.execute(
            select(Lead.lost_reason, func.count())
            .select_from(Lead)
            .join(lost_at, lost_at.c.lead_id == Lead.id)
            .where(w.within(lost_at.c.at), Lead.status == LeadStatus.LOST)
            .group_by(Lead.lost_reason)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()
    lost = sum(n for _, n in lost_rows)

    days = (
        await db.execute(
            select(
                func.extract("epoch", Lead.won_at - Lead.created_at) / 86400.0
            ).where(won_scope)
        )
    ).scalars().all()
    spans = sorted(float(d) for d in days if d is not None)

    won = sum(n for _, n, _ in kinds)
    return {
        "won": won,
        "by_kind": {(k or "unknown"): n for k, n, _ in kinds},
        "total_value": float(sum(v for _, _, v in kinds)) if with_value else None,
        "median_days_lead_to_won": (
            round(spans[len(spans) // 2], 1) if spans else None
        ),
        "lost": lost,
        "lost_reasons": {(r or "unstated"): n for r, n in lost_rows},
        "close_rate": round(won / (won + lost), 3) if (won + lost) else 0.0,
    }


# ── Content: what each published piece was followed by ───────────────────


async def content(db: AsyncSession, w: Window, limit: int = 20) -> list[dict]:
    """Recent publications and what happened in the two days after each.

    **This is association, not attribution, and the difference is the whole
    honesty of the section.** A link in a Shorts description is not clickable
    and Instagram strips the referrer, so most people who see a video and come
    to the site arrive typing the domain — indistinguishable from anyone else.
    What can be said truthfully is "these visits happened in the 48 hours after
    this went out". The response says `association` so the page cannot round it
    up into a claim it does not support.

    Anchored on `published_at`, never `scheduled_at`: a post still queued has
    not been seen by anybody, and a window starting at its scheduled time would
    hand it visits that happened before it existed.
    """
    rows = (
        await db.execute(
            select(
                ContentPublication.id,
                ContentPublication.piece_id,
                ContentPublication.platform,
                ContentPublication.published_at,
                ContentPublication.external_url,
            )
            .where(
                ContentPublication.published_at.is_not(None),
                w.within(ContentPublication.published_at),
            )
            .order_by(ContentPublication.published_at.desc())
            .limit(limit)
        )
    ).all()

    # Scoped to the window like everything else. Unscoped this read every lead
    # the agency has ever had, on every request, to answer a question about
    # twenty publications.
    all_metas = (
        await db.execute(select(Lead.meta).where(w.within(Lead.created_at)))
    ).scalars().all()

    # How many people actually saw it, which is the number that separates "the
    # video reached nobody" from "the video reached people and the page lost
    # them" — opposite problems that look identical without it. One query for
    # the whole list; `None` for anything nobody has read yet.
    newest = await video_metrics.latest_metrics(db, [row[0] for row in rows])

    out: list[dict] = []
    for publication_id, piece_id, platform, published_at, url in rows:
        until = published_at + timedelta(hours=48)
        sessions = await _scalar(
            db,
            select(func.count()).where(
                LandingSession.first_seen_at >= published_at,
                LandingSession.first_seen_at < until,
            ),
        )
        leads_after = await _scalar(
            db,
            select(func.count())
            .select_from(Lead)
            .where(Lead.created_at >= published_at, Lead.created_at < until),
        )
        # The one honest number in the row: a lead that carried this piece's own
        # tag. Zero for anything published before the tagging existed, which is
        # most of them today, and that zero is the truth rather than a gap.
        tagged = sum(
            1
            for meta in all_metas
            if ((meta or {}).get("attribution") or {}).get("utm_content")
            == f"piece-{piece_id}"
        )
        out.append(
            {
                "piece_id": piece_id,
                "platform": platform.value if hasattr(platform, "value") else str(platform),
                "published_at": published_at.isoformat(),
                "external_url": url,
                "association": {
                    "window_hours": 48,
                    "sessions": sessions,
                    "leads": leads_after,
                },
                "leads_tagged": tagged,
                "views": (
                    {
                        "count": snapshot.views,
                        "captured_on": snapshot.captured_on.isoformat(),
                        # `manual` means a person typed it off their phone,
                        # and the page says so: a hand-read number and an API
                        # reading must not sit in a column looking alike.
                        "source": snapshot.source,
                    }
                    if (snapshot := newest.get(publication_id)) is not None
                    else None
                ),
            }
        )
    return out


# ── Per agent ────────────────────────────────────────────────────────────

# Actors that are not people. They do real work — the voice agent books real
# appointments — but a table headed "per agent" that lists `vapi` next to two
# humans invites a comparison that means nothing.
#
# `office` is deliberately NOT here. It is what gets written when somebody
# signs in with the master password instead of Google, which is how the owner
# himself often works: filtering it would make his own actions vanish from his
# own report. It appears as a row named `office`, which is at least the truth.
_NOT_A_PERSON = ("vapi", "system")


async def by_agent(db: AsyncSession, w: Window) -> list[dict]:
    scope = w.within(Lead.created_at)

    logged = dict(
        (
            await db.execute(
                select(CallLog.logged_by, func.count())
                .select_from(CallLog)
                .join(Lead, Lead.id == CallLog.lead_id)
                .where(scope)
                .group_by(CallLog.logged_by)
            )
        ).all()
    )
    booked = dict(
        (
            await db.execute(
                select(Visit.assigned_email, func.count())
                .select_from(Visit)
                .join(Lead, Lead.id == Visit.lead_id)
                .where(scope)
                .group_by(Visit.assigned_email)
            )
        ).all()
    )
    closed = dict(
        (
            await db.execute(
                select(LeadEvent.actor, func.count())
                .select_from(LeadEvent)
                .join(Lead, Lead.id == LeadEvent.lead_id)
                .where(LeadEvent.type == "deal_closed", scope)
                .group_by(LeadEvent.actor)
            )
        ).all()
    )

    emails = {
        e
        for e in (*logged, *booked, *closed)
        if e and e not in _NOT_A_PERSON
    }
    return sorted(
        (
            {
                "email": e,
                "calls_logged": logged.get(e, 0),
                "appointments": booked.get(e, 0),
                "won": closed.get(e, 0),
            }
            for e in emails
        ),
        key=lambda r: (-r["won"], -r["calls_logged"], r["email"]),
    )


# ── The funnel, which is every section above read as one line ────────────


async def funnel(db: AsyncSession, w: Window, traffic_now: dict) -> list[dict]:
    """Each step counts LEADS that reached it, not events.

    A lead contacted twice is one lead contacted. Counting events would make a
    stage exceed the one above it, which is the shape that makes a funnel chart
    obviously wrong and a funnel table quietly wrong.

    **`called_back` is deliberately not a step**, and finding that out needed
    real data: a seeded month showed four appointments sitting under zero
    call-backs, because an appointment can be booked by the voice agent or from
    the panel without anybody logging a call. A stage wider than the one above
    it is not a funnel, it is two questions drawn as one. How many leads were
    phoned lives in the calls card, as a fact about the office rather than a
    rung on a ladder.
    """
    scope = w.within(Lead.created_at)

    async def _leads_with(join_table, extra=None) -> int:
        stmt = (
            select(func.count(distinct(Lead.id)))
            .select_from(Lead)
            .join(join_table, join_table.lead_id == Lead.id)
            .where(scope)
        )
        return int((await db.execute(stmt if extra is None else stmt.where(extra))).scalar() or 0)

    total_leads = await _scalar(db, select(func.count()).where(scope).select_from(Lead))
    contacted = await _scalar(
        db,
        select(func.count(distinct(Lead.id)))
        .select_from(Lead)
        .join(Conversation, Conversation.lead_id == Lead.id)
        .join(Message, Message.conversation_id == Conversation.id)
        .where(scope, _real_outbound()),
    )
    appointment_set = await _leads_with(Visit)
    appointment_held = await _leads_with(Visit, Visit.status == VisitStatus.COMPLETED)
    won = await _scalar(
        db, select(func.count()).where(scope, Lead.status == LeadStatus.WON).select_from(Lead)
    )

    steps = [
        ("sessions", traffic_now["sessions"]),
        ("engaged", traffic_now["engaged"]),
        ("cta", traffic_now["cta_clicks"] + traffic_now["tel_clicks"] + traffic_now["form_starts"]),
        ("leads", total_leads),
        ("contacted", contacted),
        ("appointment_set", appointment_set),
        ("appointment_held", appointment_held),
        ("won", won),
    ]

    out: list[dict] = []
    previous: int | None = None
    for name, count in steps:
        out.append(
            {
                "stage": name,
                "count": count,
                # Against the step above, not against the top: "half the people
                # who reached the form sent it" is actionable; "3% of visitors
                # sent it" is a number nobody can do anything with.
                "pct_of_previous": (
                    round(count / previous, 3) if previous else None
                ),
            }
        )
        previous = count
    return out
