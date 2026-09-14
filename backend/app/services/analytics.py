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

*The range follows the acquisition anchor, not every downstream event.* Lead
cards anchor on when the lead was created. The website funnel anchors on when
its measured session began, then asks how far that same cohort eventually got.
That keeps a closed period interpretable instead of mixing in people acquired
elsewhere merely because somebody contacted or booked them during the range.

*Con una excepción, y está señalada donde vive:* `calls()` acota por el instante
de la llamada, no por el del lead. Es la única tarjeta que no pregunta por una
cohorte, y acotarla como las demás la hacía imposible de leer — con cero leads
nuevos en la ventana, las llamadas entrantes salían cero por aritmética,
llamara quien llamara.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    Select,
    String,
    and_,
    case,
    cast,
    column,
    distinct,
    func,
    or_,
    select,
    values,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    CallLog,
    ContentPiece,
    ContentPublication,
    Conversation,
    LandingSession,
    Lead,
    LeadEvent,
    LeadStatus,
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
    Visit,
    VisitStatus,
)
from app.models.landing import HOME_SECTIONS
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


def _measured_session() -> ColumnElement[bool]:
    return LandingSession.traffic_class == "unknown"


def _lead_attribution(meta: object) -> dict:
    """The immutable first-touch mapping, defensive against legacy junk JSON."""
    if not isinstance(meta, dict):
        return {}
    attribution = meta.get("attribution")
    return attribution if isinstance(attribution, dict) else {}


def _measured_lead() -> ColumnElement[bool]:
    """A lead that represents a real acquisition in Analytics.

    QA submissions stay in the CRM so the complete form flow remains testable,
    but their calls, appointments and deals must not become business results.
    The marker is read only from the immutable first-touch attribution: a real
    lead who later visits a QA link therefore remains real.

    The explicit UTM pair covers QA leads captured before ``traffic_class`` was
    persisted.  ``json_extract_path_text`` is deliberate: ``Lead.meta`` is a
    plain JSON column, and SQLAlchemy's indexed JSON expression has previously
    produced an uncacheable query in this module.
    """
    source = func.json_extract_path_text(Lead.meta, "attribution", "utm_source")
    medium = func.json_extract_path_text(Lead.meta, "attribution", "utm_medium")
    traffic_class = func.json_extract_path_text(Lead.meta, "attribution", "traffic_class")
    return and_(
        or_(
            func.coalesce(source, "") != "eko_qa",
            func.coalesce(medium, "") != "test",
        ),
        func.coalesce(traffic_class, "unknown").not_in(("test", "automated")),
    )


# ── Traffic: what happened on the landing page ───────────────────────────


async def traffic(db: AsyncSession, w: Window) -> dict:
    """Visits, how far they read, and where they came from.

    Read off `landing_sessions` and never off `landing_events`: the events are
    purged after ninety days, so summing them would make last quarter's numbers
    shrink every night. The session row carries the same facts already merged.
    """
    base = LandingSession.first_seen_at
    date_scope = w.within(base)
    scope = and_(date_scope, _measured_session())

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
                                LandingSession.cta_clicks > 0,
                                LandingSession.tel_clicks > 0,
                                LandingSession.form_started_at.is_not(None),
                                LandingSession.form_submitted_at.is_not(None),
                            ),
                            1,
                        )
                    )
                ),
                func.coalesce(func.avg(LandingSession.max_scroll_pct), 0),
                func.coalesce(func.sum(LandingSession.cta_clicks), 0),
                func.coalesce(func.sum(LandingSession.tel_clicks), 0),
                # A successful submit necessarily started the form. Count it
                # even when the earlier focus beacon was lost or raced the
                # capture request.
                func.count(
                    case(
                        (
                            or_(
                                LandingSession.form_started_at.is_not(None),
                                LandingSession.form_submitted_at.is_not(None),
                            ),
                            1,
                        )
                    )
                ),
                func.count(LandingSession.form_submitted_at),
                # ── Y los mismos hechos contados en PERSONAS ────────────────
                # Los cuatro de arriba son sumas de contadores, y sirven para
                # la tarjeta de tráfico: "cuántos toques hubo". El embudo
                # necesita lo otro — cuántas personas distintas —, porque todos
                # sus demás peldaños cuentan leads distintos y mezclar las dos
                # unidades es lo que hacía que un peldaño pudiera superar al de
                # encima. Medido el 12-sep-2026: 6 clics de 5 personas.
                func.count(
                    case((LandingSession.cta_clicks > 0, 1))
                ),
                # Los que de verdad hicieron algo: tocar el teléfono o meter
                # el cursor en el formulario. Su condición es parte de la del
                # peldaño de abajo, así que este conjunto está CONTENIDO en
                # aquel por construcción, nunca mayor. Iguales cuando nadie
                # se limitó a navegar.
                # Eso es lo que impide que el embudo se ensanche aquí con
                # ningún dato.
                func.count(
                    case(
                        (
                            or_(
                                LandingSession.tel_clicks > 0,
                                LandingSession.form_started_at.is_not(None),
                                LandingSession.form_submitted_at.is_not(None),
                            ),
                            1,
                        )
                    )
                ),
                # Cualquiera de las tres cosas. El peldaño ancho.
                func.count(
                    case(
                        (
                            or_(
                                LandingSession.cta_clicks > 0,
                                LandingSession.tel_clicks > 0,
                                LandingSession.form_started_at.is_not(None),
                                LandingSession.form_submitted_at.is_not(None),
                            ),
                            1,
                        )
                    )
                ),
                # Cuántas veces se estrelló un envío, y a cuánta gente.
                func.coalesce(func.sum(LandingSession.form_error_count), 0),
                func.count(case((LandingSession.form_error_count > 0, 1))),
                # **El detector de leads perdidos.** `landing_analytics.py` lo
                # describe desde que existe —"pressed send and no lead ever
                # arrived"— y hasta hoy ninguna consulta lo hacía. Es el
                # honeypot que contesta 202, el captcha rechazado, la conexión
                # caída: el visitante ve "enviado" y no hay lead.
                func.count(
                    case(
                        (
                            and_(
                                LandingSession.form_submitted_at.is_not(None),
                                LandingSession.lead_id.is_(None),
                            ),
                            1,
                        )
                    )
                ),
            ).where(scope)
        )
    ).one()

    traffic_class_rows = (
        await db.execute(
            select(LandingSession.traffic_class, func.count())
            .where(date_scope)
            .group_by(LandingSession.traffic_class)
        )
    ).all()
    traffic_class_counts = {traffic_class: count for traffic_class, count in traffic_class_rows}

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
    for name in HOME_SECTIONS:
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
        "people_clicked_cta": totals[7],
        "people_tapped": totals[8],
        "people_reached_out": totals[9],
        "form_errors": int(totals[10]),
        "people_with_errors": totals[11],
        "submitted_without_lead": totals[12],
        "excluded_sessions": {
            "total": traffic_class_counts.get("automated", 0)
            + traffic_class_counts.get("test", 0),
            "automated": traffic_class_counts.get("automated", 0),
            "test": traffic_class_counts.get("test", 0),
        },
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
    scope = and_(w.within(Lead.created_at), _measured_lead())
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
        attribution = _lead_attribution(meta)
        # `no_web` is not a measurement failure: it is a lead that never
        # touched the landing page — imported, phoned in, found by discovery —
        # and folding it into `direct` would invent web traffic that never
        # happened.
        candidates = (attribution.get("utm_source"), attribution.get("referrer"))
        key = next(
            (candidate for candidate in candidates if isinstance(candidate, str) and candidate),
            "no_web",
        )
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

    `internal=True` is a note an advisor left on the thread. Pending and failed
    rows are delivery attempts, not replies. Counting either shape made a lead
    nobody ever reached look answered and understated the real response time.
    """
    return and_(
        Message.direction == MessageDirection.OUTBOUND,
        Message.internal.is_(False),
        Message.delivery_status.in_(
            (MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.READ)
        ),
    )


async def response(db: AsyncSession, w: Window) -> dict:
    scope = and_(w.within(Lead.created_at), _measured_lead())
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
            .where(scope)
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
            .where(_real_outbound(), scope)
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
        .where(scope, first_reply.c.replied_at.is_(None)),
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
    """La única tarjeta que NO es una cohorte de leads, y a propósito.

    El resto de este módulo acota por `Lead.created_at`: "de los leads que
    llegaron entonces, a cuántos alcanzamos". Aquí eso daba una respuesta
    imposible de interpretar y a veces falsa. Con **cero leads** creados en la
    ventana, `JOIN Lead ... WHERE Lead.created_at IN ventana` obliga a que las
    llamadas entrantes salgan **0 aritméticamente** — llamara quien llamara. El
    12-sep-2026 el panel enseñaba "CALLS IN 0" y se leyó como "nadie llamó",
    cuando lo único que decía era "no hubo leads nuevos".

    Una llamada existe aunque el lead sea de otro mes, y el docstring de
    `funnel()` ya dice por qué esto vive en una tarjeta y no en un peldaño: es
    un hecho sobre la oficina, no un escalón de la escalera. Así que cada
    consulta se acota por **su propio** instante: el evento de llamada por
    `LeadEvent.at`, y el registro manual por el suyo.

    `appointments()` y `deals()` NO cambian: ésas sí son preguntas de cohorte.
    """
    by_event = w.within(LeadEvent.at)

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
            .where(LeadEvent.type == "call_inbound", by_event, _measured_lead())
        )
    ).one()

    reason_col = LeadEvent.meta["ended_reason"].astext.label("reason")
    reasons = (
        await db.execute(
            select(reason_col, func.count())
            .select_from(LeadEvent)
            .join(Lead, Lead.id == LeadEvent.lead_id)
            .where(LeadEvent.type == "call_inbound", by_event, _measured_lead())
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
            # Por cuándo se apuntó la llamada, no por cuándo llegó el lead:
            # apuntar hoy una llamada a un lead de agosto es trabajo de hoy.
            .where(w.within(CallLog.created_at), _measured_lead())
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
    scope = and_(w.within(Lead.created_at), _measured_lead())
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
    won_scope = and_(w.within(Lead.won_at), _measured_lead())

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
            .where(
                w.within(lost_at.c.at),
                Lead.status == LeadStatus.LOST,
                _measured_lead(),
            )
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


def _empty_attribution() -> dict[str, int]:
    return {
        "sessions": 0,
        "engaged": 0,
        "cta_clickers": 0,
        "contact_intents": 0,
        "form_starts": 0,
        "form_submits": 0,
        "leads": 0,
        "appointments_set": 0,
        "appointments_held": 0,
    }


def _publication_windows(starts_by_piece: dict[int, list[datetime]]):
    """A bounded SQL table of each publication's 48-hour association window."""
    rows = [
        (piece_id, start, start + timedelta(hours=48))
        for piece_id, starts in starts_by_piece.items()
        for start in starts
    ]
    return (
        values(
            column("piece_id", Integer),
            column("start_at", DateTime(timezone=True)),
            column("end_at", DateTime(timezone=True)),
            name="publication_windows",
        )
        .data(rows)
        .alias("publication_windows")
    )


def _publication_keys(publication_keys: set[tuple[int, str]]):
    """The piece/platform pairs whose exact conversion counters are requested."""
    rows = [
        (piece_id, platform, f"piece-{piece_id}") for piece_id, platform in sorted(publication_keys)
    ]
    return (
        values(
            column("piece_id", Integer),
            column("platform", String),
            column("content_tag", String),
            name="publication_keys",
        )
        .data(rows)
        .alias("publication_keys")
    )


def _normalized_first_touch_source() -> ColumnElement[str]:
    """The three publishable social sources, with the same aliases as visits."""
    raw = func.lower(
        func.trim(
            func.coalesce(
                func.json_extract_path_text(Lead.meta, "attribution", "utm_source"),
                "",
            )
        )
    )
    return case(
        (raw.in_(("youtube", "yt", "youtube_shorts", "shorts")), "youtube"),
        (raw.in_(("tiktok", "tt")), "tiktok"),
        (raw.in_(("instagram", "ig")), "instagram"),
        else_="other",
    )


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

    `limit` counts videos rather than posts, because the page groups by video:
    counting posts ends the list inside a video and drops the platforms that
    did not fit, which reads as "we never posted it there".

    **The association is per VIDEO, over the union of its posts' windows.**
    The platforms of one video go out half a day apart, so their 48-hour
    windows overlap for most of their length; counted per post, a visit in the
    overlap sat on both rows and the owner adding the rows up got a number of
    people that never existed. Every row of a video carries the same block, so
    the payload keeps its shape and the card shows it once.
    """
    recent = (
        select(ContentPublication.piece_id)
        .where(
            ContentPublication.published_at.is_not(None),
            w.within(ContentPublication.published_at),
        )
        .group_by(ContentPublication.piece_id)
        .order_by(
            func.max(ContentPublication.published_at).desc(),
            ContentPublication.piece_id.desc(),
        )
        .limit(limit)
    )
    rows = (
        await db.execute(
            select(
                ContentPublication.id,
                ContentPublication.piece_id,
                ContentPublication.platform,
                ContentPublication.published_at,
                ContentPublication.external_url,
                ContentPiece.hook,
            )
            .join(ContentPiece, ContentPiece.id == ContentPublication.piece_id)
            .where(
                ContentPublication.published_at.is_not(None),
                w.within(ContentPublication.published_at),
                ContentPublication.piece_id.in_(recent),
            )
            .order_by(
                ContentPublication.published_at.desc(), ContentPublication.id.desc()
            )
        )
    ).all()

    if not rows:
        return []

    starts_by_piece: dict[int, list[datetime]] = {}
    for _publication_id, piece_id, _platform, published_at, _url, _hook in rows:
        starts_by_piece.setdefault(piece_id, []).append(published_at)

    publication_keys = {
        (
            piece_id,
            platform.value if hasattr(platform, "value") else str(platform),
        )
        for _publication_id, piece_id, platform, _published_at, _url, _hook in rows
    }
    attribution_by_key = {key: _empty_attribution() for key in publication_keys}
    association_by_piece = {
        piece_id: {"window_hours": 48, "sessions": 0, "leads": 0} for piece_id in starts_by_piece
    }
    leads_tagged_by_piece = {piece_id: 0 for piece_id in starts_by_piece}
    windows = _publication_windows(starts_by_piece)
    keys = _publication_keys(publication_keys)

    # Every result below is bounded by the number of displayed pieces or
    # publications. PostgreSQL scans and aggregates the underlying visitors;
    # the API worker never materialises a year's worth of session JSON and
    # never performs sessions × pieces comparisons in Python.
    session_associations = (
        await db.execute(
            select(
                windows.c.piece_id,
                func.count(distinct(LandingSession.id)),
            )
            .select_from(windows)
            .join(
                LandingSession,
                and_(
                    LandingSession.first_seen_at >= windows.c.start_at,
                    LandingSession.first_seen_at < windows.c.end_at,
                    _measured_session(),
                ),
            )
            .group_by(windows.c.piece_id)
        )
    ).all()
    for piece_id, count in session_associations:
        association_by_piece[piece_id]["sessions"] = count

    lead_associations = (
        await db.execute(
            select(windows.c.piece_id, func.count(distinct(Lead.id)))
            .select_from(windows)
            .join(
                Lead,
                and_(
                    Lead.created_at >= windows.c.start_at,
                    Lead.created_at < windows.c.end_at,
                    _measured_lead(),
                ),
            )
            .group_by(windows.c.piece_id)
        )
    ).all()
    for piece_id, count in lead_associations:
        association_by_piece[piece_id]["leads"] = count

    engaged = or_(
        LandingSession.max_scroll_pct >= 50,
        func.jsonb_array_length(LandingSession.sections_viewed) >= 2,
        LandingSession.cta_clicks > 0,
        LandingSession.tel_clicks > 0,
        LandingSession.form_started_at.is_not(None),
        LandingSession.form_submitted_at.is_not(None),
    )
    exact_sessions = (
        await db.execute(
            select(
                keys.c.piece_id,
                keys.c.platform,
                func.count(distinct(LandingSession.id)),
                func.count(distinct(case((engaged, LandingSession.id)))),
                func.count(distinct(case((LandingSession.cta_clicks > 0, LandingSession.id)))),
                func.count(
                    distinct(
                        case(
                            (
                                or_(
                                    LandingSession.tel_clicks > 0,
                                    LandingSession.form_started_at.is_not(None),
                                    LandingSession.form_submitted_at.is_not(None),
                                ),
                                LandingSession.id,
                            )
                        )
                    )
                ),
                func.count(
                    distinct(
                        case(
                            (
                                or_(
                                    LandingSession.form_started_at.is_not(None),
                                    LandingSession.form_submitted_at.is_not(None),
                                ),
                                LandingSession.id,
                            )
                        )
                    )
                ),
                func.count(
                    distinct(
                        case(
                            (
                                LandingSession.form_submitted_at.is_not(None),
                                LandingSession.id,
                            )
                        )
                    )
                ),
            )
            .select_from(keys)
            .join(
                LandingSession,
                and_(
                    LandingSession.utm_content == keys.c.content_tag,
                    LandingSession.source == keys.c.platform,
                ),
            )
            .where(w.within(LandingSession.first_seen_at), _measured_session())
            .group_by(keys.c.piece_id, keys.c.platform)
        )
    ).all()
    for row in exact_sessions:
        counters = attribution_by_key[(row[0], row[1])]
        for field, count in zip(
            (
                "sessions",
                "engaged",
                "cta_clickers",
                "contact_intents",
                "form_starts",
                "form_submits",
            ),
            row[2:],
            strict=True,
        ):
            counters[field] = count

    first_touch_content = func.json_extract_path_text(Lead.meta, "attribution", "utm_content")
    tagged_leads = (
        await db.execute(
            select(keys.c.piece_id, func.count(distinct(Lead.id)))
            .select_from(keys)
            .join(Lead, first_touch_content == keys.c.content_tag)
            .where(w.within(Lead.created_at), _measured_lead())
            .group_by(keys.c.piece_id)
        )
    ).all()
    for piece_id, count in tagged_leads:
        leads_tagged_by_piece[piece_id] = count

    exact_leads = (
        await db.execute(
            select(
                keys.c.piece_id,
                keys.c.platform,
                func.count(distinct(Lead.id)),
                func.count(distinct(Visit.id)),
                func.count(distinct(case((Visit.status == VisitStatus.COMPLETED, Visit.id)))),
            )
            .select_from(keys)
            .join(
                Lead,
                and_(
                    first_touch_content == keys.c.content_tag,
                    _normalized_first_touch_source() == keys.c.platform,
                ),
            )
            .outerjoin(Visit, Visit.lead_id == Lead.id)
            .where(w.within(Lead.created_at), _measured_lead())
            .group_by(keys.c.piece_id, keys.c.platform)
        )
    ).all()
    for piece_id, platform, leads_count, appointments_set, appointments_held in exact_leads:
        counters = attribution_by_key[(piece_id, platform)]
        counters["leads"] = leads_count
        counters["appointments_set"] = appointments_set
        counters["appointments_held"] = appointments_held

    newest = await video_metrics.latest_metrics(db, [row[0] for row in rows])

    out: list[dict] = []
    for publication_id, piece_id, platform, published_at, url, hook in rows:
        platform_name = platform.value if hasattr(platform, "value") else str(platform)
        snapshot = newest.get(publication_id)
        out.append(
            {
                "piece_id": piece_id,
                "publication_id": publication_id,
                # The video's name in the console. A row identified only by a
                # piece id is a number nobody recognises.
                "hook": hook,
                "platform": platform_name,
                "published_at": published_at.isoformat(),
                "external_url": url,
                "association": association_by_piece[piece_id],
                "leads_tagged": leads_tagged_by_piece[piece_id],
                "attribution": attribution_by_key[(piece_id, platform_name)],
                "latest_metrics": (
                    {
                        "views": snapshot.views,
                        "likes": snapshot.likes,
                        "comments": snapshot.comments,
                        "captured_on": snapshot.captured_on.isoformat(),
                        "source": snapshot.source,
                    }
                    if snapshot is not None
                    else None
                ),
                "views": (
                    {
                        "count": snapshot.views,
                        "captured_on": snapshot.captured_on.isoformat(),
                        # `manual` means a person typed it off their phone,
                        # and the page says so: a hand-read number and an API
                        # reading must not sit in a column looking alike.
                        "source": snapshot.source,
                    }
                    if snapshot is not None
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
    scope = and_(w.within(Lead.created_at), _measured_lead())

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


async def funnel(db: AsyncSession, w: Window) -> list[dict]:
    """One measured website cohort, narrowed at every successive step.

    The first four steps count landing sessions. ``leads`` starts only with the
    distinct leads whose immutable acquisition-session key matches a measured
    form submission; imported, telephone, returning and legacy unmarked leads
    remain in their own cards. Every later CTE starts from the previous CTE and
    requires its event to happen after the website conversion. That is what
    makes the percentages honest shares of the step immediately above rather
    than unrelated totals.

    All nine counts come from one SELECT.  At PostgreSQL's READ COMMITTED
    isolation level each statement gets its own snapshot, so reusing the
    an earlier ``traffic()`` result and issuing one statement per later stage can
    briefly put a newly committed lead underneath an older, smaller session
    count. The funnel therefore reads its own atomic view.

    **`called_back` is deliberately not a step**, and finding that out needed
    real data: a seeded month showed four appointments sitting under zero
    call-backs, because an appointment can be booked by the voice agent or from
    the panel without anybody logging a call. A stage wider than the one above
    it is not a funnel, it is two questions drawn as one. How many leads were
    phoned lives in the calls card, as a fact about the office rather than a
    rung on a ladder.
    """
    session_scope = and_(
        w.within(LandingSession.first_seen_at),
        _measured_session(),
    )
    engaged = or_(
        LandingSession.max_scroll_pct >= 50,
        func.jsonb_array_length(LandingSession.sections_viewed) >= 2,
        LandingSession.cta_clicks > 0,
        LandingSession.tel_clicks > 0,
        LandingSession.form_started_at.is_not(None),
        LandingSession.form_submitted_at.is_not(None),
    )
    tapped = or_(
        LandingSession.tel_clicks > 0,
        LandingSession.form_started_at.is_not(None),
        LandingSession.form_submitted_at.is_not(None),
    )
    reached_out = or_(LandingSession.cta_clicks > 0, tapped)
    session_counts = (
        select(
            func.count().label("sessions"),
            func.count(case((engaged, 1))).label("engaged"),
            func.count(case((reached_out, 1))).label("reached_out"),
            func.count(case((tapped, 1))).label("tapped"),
        )
        .select_from(LandingSession)
        .where(session_scope)
        .cte("measured_funnel_sessions")
    )

    cohort = (
        select(
            LandingSession.lead_id.label("lead_id"),
            func.min(LandingSession.form_submitted_at).label("converted_at"),
        )
        .select_from(LandingSession)
        .join(Lead, Lead.id == LandingSession.lead_id)
        .where(
            w.within(LandingSession.first_seen_at),
            _measured_session(),
            LandingSession.form_submitted_at.is_not(None),
            func.json_extract_path_text(Lead.meta, "acquisition_session_key")
            == LandingSession.session_key,
            _measured_lead(),
        )
        .group_by(LandingSession.lead_id)
        .cte("measured_funnel_leads")
    )

    contacted_cohort = (
        select(cohort.c.lead_id, cohort.c.converted_at)
        .select_from(cohort)
        .join(Conversation, Conversation.lead_id == cohort.c.lead_id)
        .join(Message, Message.conversation_id == Conversation.id)
        .where(
            _real_outbound(),
            Message.created_at >= cohort.c.converted_at,
        )
        .group_by(cohort.c.lead_id, cohort.c.converted_at)
        .cte("contacted_funnel_leads")
    )
    appointment_cohort = (
        select(contacted_cohort.c.lead_id, contacted_cohort.c.converted_at)
        .select_from(contacted_cohort)
        .join(
            Visit,
            and_(
                Visit.lead_id == contacted_cohort.c.lead_id,
                Visit.created_at >= contacted_cohort.c.converted_at,
            ),
        )
        .group_by(contacted_cohort.c.lead_id, contacted_cohort.c.converted_at)
        .cte("appointment_funnel_leads")
    )
    held_cohort = (
        select(appointment_cohort.c.lead_id, appointment_cohort.c.converted_at)
        .select_from(appointment_cohort)
        .join(
            Visit,
            and_(
                Visit.lead_id == appointment_cohort.c.lead_id,
                Visit.created_at >= appointment_cohort.c.converted_at,
                Visit.status == VisitStatus.COMPLETED,
            ),
        )
        .group_by(appointment_cohort.c.lead_id, appointment_cohort.c.converted_at)
        .cte("held_funnel_leads")
    )
    won_cohort = (
        select(held_cohort.c.lead_id)
        .select_from(held_cohort)
        .join(Lead, Lead.id == held_cohort.c.lead_id)
        .where(
            Lead.status == LeadStatus.WON,
            Lead.won_at >= held_cohort.c.converted_at,
        )
        .group_by(held_cohort.c.lead_id)
        .cte("won_funnel_leads")
    )

    counts = (
        await db.execute(
            select(
                session_counts.c.sessions,
                session_counts.c.engaged,
                session_counts.c.reached_out,
                session_counts.c.tapped,
                select(func.count())
                .select_from(cohort)
                .scalar_subquery()
                .label("leads"),
                select(func.count())
                .select_from(contacted_cohort)
                .scalar_subquery()
                .label("contacted"),
                select(func.count())
                .select_from(appointment_cohort)
                .scalar_subquery()
                .label("appointment_set"),
                select(func.count())
                .select_from(held_cohort)
                .scalar_subquery()
                .label("appointment_held"),
                select(func.count())
                .select_from(won_cohort)
                .scalar_subquery()
                .label("won"),
            ).select_from(session_counts)
        )
    ).one()

    steps = [
        ("sessions", counts.sessions),
        ("engaged", counts.engaged),
        # Dos peldaños donde había uno, y contados en PERSONAS.
        #
        # Era `SUM(cta_clicks) + SUM(tel_clicks) + COUNT(form_starts)`: una suma
        # de eventos en el único escalón que no contaba gente, contra lo que
        # promete el docstring de arriba. Alguien que pulsa tres veces valía 3.
        #
        # Y la etiqueta mentía. `cta_click` se dispara con cualquier
        # `<a href="#consult">`, que es un salto dentro de la página: en los 30
        # días medidos el 12-sep-2026 los seis clics fueron **el menú de
        # navegación** (`nav-buying`, `nav-selling`, el "Book" del móvil) y el
        # botón de verdad tuvo **cero**. Llamar a eso "tocó llamar o empezó el
        # formulario" es contar curiosidad como intención.
        #
        # `tapped` está CONTENIDO en `reached_out` por construcción —los dos
        # salen de la misma fila y la condición del primero es parte de la del
        # segundo—, así que el embudo no puede ensancharse aquí por mucho que
        # cambien los datos. Iguales cuando nadie se limitó a navegar. Los
        # tres grupos salieron disjuntos en la medición (5 del menú,
        # 3 del teléfono, 6 del formulario), que es justo la forma que habría
        # roto un embudo de peldaños independientes.
        ("reached_out", counts.reached_out),
        ("tapped", counts.tapped),
        ("leads", counts.leads),
        ("contacted", counts.contacted),
        ("appointment_set", counts.appointment_set),
        ("appointment_held", counts.appointment_held),
        ("won", counts.won),
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
