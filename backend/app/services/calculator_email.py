"""The breakdown a visitor calculated, emailed back to them.

Forty-eight sessions reached a figure on `/calculator` in ninety days and none of
them ever touched the form. The first half of the fix was the offer (the page now
asks for an address instead of a meeting); this is the artefact that makes the
address worth leaving — their own numbers, in writing, while they are still
thinking about them.

**It ships dark.** `build_footer` raises without `POSTAL_ADDRESS`, and nothing
here catches that and sends anyway. Until the agency supplies one line of config
this function loads a lead, decides it may write to them, builds a body and then
logs that it cannot send it. That is the intended state, and the log line is how
somebody finds out the channel is waiting rather than broken.

**The numbers are recomputed, never re-derived.** `build_snapshot` keeps only the
net; everything the page shows as a breakdown — appreciation, amortization, the
cash-flow difference, closing, the cost to sell — it throws away. So this re-runs
`solve_price` and `compare` over the assumptions **exactly as they were stored**.
Not merged with today's `DEFAULTS`: an assumption someone edits next month must
not silently rewrite what this person was looking at.

**And the assumptions are printed.** `docs/content/calculator-consistency.md`
has required that since 14-sep-2026, after five videos went out claiming
"~$21,000 ahead" where the calculator said $52,210 — right under assumptions
nobody recorded, which is indistinguishable from wrong. A figure in an email to
a consumer is held to the same rule as a figure in a video.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.channel_route import CHANNEL_EMAIL
from app.services.calculator import _round, compare, solve_price
from app.services.email import send_email
from app.services.email_compliance import MissingPostalAddress, build_footer, unsubscribe_url
from app.services.fair_housing import find_violations

log = logging.getLogger(__name__)

__all__ = ["render_breakdown", "send_calculator_breakdown"]

_CREDIT = {
    "en": {"excellent": "Excellent", "good": "Good", "fair": "Fair"},
    "es": {"excellent": "Excelente", "good": "Bueno", "fair": "Regular"},
}

_T: dict[str, dict[str, str]] = {
    "en": {
        "subject": "Your Denver rent-vs-buy numbers",
        "intro": "Here is the breakdown you ran, so you have it in writing.",
        "told": "WHAT YOU ENTERED",
        "rent": "Rent today",
        "savings": "Savings",
        "credit": "Credit",
        "points": "WHAT IT POINTS TO",
        "price": "Could buy up to",
        "monthly": "Monthly cost",
        "monthly_note": "principal, interest, taxes, insurance, PMI and HOA",
        "net": "OVER {years} YEARS, COMPARED WITH RENTING",
        "growth": "Home value growth",
        "paid": "Loan paid down",
        "cash": "Monthly difference",
        "closing": "Closing costs",
        "selling": "Cost to sell",
        "assum": "THE ASSUMPTIONS BEHIND IT",
        "a_appr": "Home value growth",
        "a_rent": "Rent growth",
        "a_rate": "Mortgage rate",
        "a_tax": "Property tax",
        "a_ins": "Insurance",
        "a_maint": "Upkeep",
        "a_maint_note": "counted in the comparison, not in the monthly cost",
        "a_close": "Closing",
        "a_sell": "Cost to sell",
        "floor": (
            "At these numbers the estimate came out below what homes in Denver "
            "actually sell for, so the page showed no price. That is worth a "
            "conversation rather than a number."
        ),
        "caveat": (
            "These are estimates, not a quote and not a guarantee. They move with "
            "the market and with what a lender actually offers you."
        ),
        "sign": "Reply to this email if you want to talk any of it through.",
    },
    "es": {
        "subject": "Tus números: alquilar o comprar en Denver",
        "intro": "Aquí tienes el desglose que calculaste, para que lo tengas por escrito.",
        "told": "LO QUE PUSISTE",
        "rent": "Renta actual",
        "savings": "Ahorro",
        "credit": "Crédito",
        "points": "LO QUE INDICA",
        "price": "Podrías comprar hasta",
        "monthly": "Cuota mensual",
        "monthly_note": "capital, intereses, impuestos, seguro, PMI y HOA",
        "net": "A {years} AÑOS, FRENTE A SEGUIR ALQUILANDO",
        "growth": "Revalorización",
        "paid": "Préstamo amortizado",
        "cash": "Diferencia mensual",
        "closing": "Costos de cierre",
        "selling": "Costo de vender",
        "assum": "LOS SUPUESTOS CON LOS QUE SALE",
        "a_appr": "Revalorización",
        "a_rent": "Subida de la renta",
        "a_rate": "Tasa hipotecaria",
        "a_tax": "Impuesto predial",
        "a_ins": "Seguro",
        "a_maint": "Mantenimiento",
        "a_maint_note": "cuenta en la comparación, no en la cuota mensual",
        "a_close": "Cierre",
        "a_sell": "Costo de vender",
        "floor": (
            "Con estos números la estimación queda por debajo de lo que se vende "
            "en Denver, así que la página no mostró precio. Eso da para una "
            "conversación más que para una cifra."
        ),
        "caveat": (
            "Son estimaciones, no una oferta ni una garantía. Se mueven con el "
            "mercado y con lo que un prestamista te ofrezca de verdad."
        ),
        "sign": "Responde a este correo si quieres repasar cualquier parte.",
    },
}


def _money(n: float) -> str:
    """Half-up, like the page. `round()` is half-to-even and the two disagree on
    exact halves — which is how an email ends up showing $1 less than the screen
    the reader is comparing it against."""
    v = _round(abs(n))
    return f"{'-' if n < 0 else ''}${v:,}"


def _pct(x: float, places: int = 2) -> str:
    return f"{x * 100:.{places}f}".rstrip("0").rstrip(".") + "%"


def _row(label: str, value: str, note: str | None = None) -> str:
    line = f"  {label:<22}{value}"
    return f"{line}  ({note})" if note else line


def render_breakdown(snapshot: dict[str, Any]) -> tuple[str, str]:
    """`(subject, body)` for one stored snapshot. Pure: no I/O, no settings.

    Split out from the sender so the wording can be held by a test — the prose
    is the part with Fair Housing exposure, and prose that only exists inside an
    async function that talks to Resend is prose nobody asserts on.
    """
    lang = snapshot.get("lang") if snapshot.get("lang") in ("en", "es") else "en"
    t = _T[lang]
    inputs = snapshot["inputs"]
    a = snapshot["assumptions"]
    result = snapshot["result"]
    years = int(a.get("years", 5))

    out: list[str] = [t["intro"], ""]
    out += [
        t["told"],
        _row(t["rent"], f"{_money(inputs['rent'])}/mo" if lang == "en" else f"{_money(inputs['rent'])}/mes"),
        _row(t["savings"], _money(inputs["savings"])),
        _row(t["credit"], _CREDIT[lang][inputs["credit"]]),
        "",
    ]

    if result.get("capped_by") == "floor":
        # No price was shown, so there is no comparison to print. Saying one
        # anyway would describe a purchase that was never offered.
        out += [t["floor"], "", t["caveat"], "", t["sign"]]
        return t["subject"], "\n".join(out)

    # Recomputed from what was stored, never merged with today's defaults.
    solved = solve_price(inputs, a)
    horizon = compare(inputs, a, solved["price"])

    out += [
        t["points"],
        _row(t["price"], _money(result["price"])),
        _row(
            t["monthly"],
            f"{_money(result['monthly']['total'])}/mo"
            if lang == "en"
            else f"{_money(result['monthly']['total'])}/mes",
            t["monthly_note"],
        ),
        "",
        t["net"].format(years=years) + f"   {_money(horizon['net'])}",
        _row(t["growth"], _money(horizon["appreciation"])),
        _row(t["paid"], _money(horizon["amortization"])),
        _row(t["cash"], _money(horizon["cashflow_diff"])),
        _row(t["closing"], _money(-horizon["closing"])),
        _row(t["selling"], _money(-horizon["selling"])),
        "",
        t["assum"],
        _row(t["a_appr"], _pct(a["appreciation"])),
        _row(t["a_rent"], _pct(a["rent_growth"])),
        _row(t["a_rate"], _pct(a["rate"] + a["rate_spread"][inputs["credit"]])),
        _row(t["a_tax"], _pct(a["tax_rate"])),
        _row(t["a_ins"], _pct(a["insurance_rate"])),
        _row(t["a_maint"], _pct(a["maintenance_rate"]), t["a_maint_note"]),
        _row(t["a_close"], _pct(a["closing_rate"], 1)),
        _row(t["a_sell"], _pct(a["selling_rate"], 1)),
        "",
        t["caveat"],
        "",
        t["sign"],
    ]
    return t["subject"], "\n".join(out)


async def send_calculator_breakdown(lead_id: int) -> None:
    """Email one lead the breakdown they calculated. Never raises.

    Called after the capture has committed, beside `send_new_lead_notice`, and
    like it this must never be able to cost the submission: everything below
    either returns or is swallowed.

    Resubmission is deliberate. A person who goes back, moves a slider and sends
    the form again arrives as a fresh `"ok"` with a NEW snapshot ("last one
    wins"), and they get the new breakdown — they changed their mind and asked
    again, and mailing them the figures they have stopped looking at would be
    the same screen-vs-record mismatch this feature exists to avoid. A true
    duplicate never reaches here: capture returns `"duplicate"` and the caller
    skips it.
    """
    from sqlalchemy import select

    from app.db.base import get_session_factory
    from app.models import Lead, Message, MessageDirection, MessageSender, MessageStatus
    from app.services.capture import may_send_automated
    from app.services.delivery import MAX_ATTEMPTS

    async with get_session_factory()() as db:
        lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
        if lead is None or not lead.email or not lead.calculator_snapshot:
            return

        # Reads `opted_out_at` first, for every channel. An unsubscribed lead is
        # the whole reason this call is here and not an `if lead.email` alone.
        if not await may_send_automated(lead, CHANNEL_EMAIL, db):
            log.info("Lead %d: breakdown not sent, automated email is not permitted", lead_id)
            return

        snapshot = lead.calculator_snapshot
        try:
            subject, body = render_breakdown(snapshot)
        except Exception as exc:  # noqa: BLE001 — a bad snapshot must not raise here
            log.warning("Lead %d: breakdown could not be rendered (%s)", lead_id, type(exc).__name__)
            return

        settings_row = await _agency_brokerage_line(db)
        try:
            footer = build_footer(
                lead_id=lead_id,
                brokerage_line=settings_row,
                lang=snapshot.get("lang"),
            )
        except MissingPostalAddress as exc:
            # The dark state, and it is loud on purpose: somebody grepping the
            # log should find the channel waiting on one line of config rather
            # than wondering why nobody ever receives anything.
            log.info("Lead %d: breakdown not sent — %s", lead_id, exc)
            return

        body = f"{body}\n\n—\n{footer}"
        # Record and warn, never block — the same policy every other lead-facing
        # lane uses. NULL would mean "never screened"; `[]` means "screened, clean".
        flags = find_violations(f"{subject} {body}", snapshot.get("lang"))

        external_id: str | None = None
        failure: str | None = None
        try:
            sent = await send_email(
                to=lead.email,
                subject=subject,
                body_text=body,
                unsubscribe_url=unsubscribe_url(lead_id),
            )
            external_id = str(sent.get("id") or "") or None
        except Exception as exc:  # noqa: BLE001
            failure = f"{type(exc).__name__}: {exc}"[:500]
            log.error("Lead %d: breakdown send failed: %s", lead_id, failure)

        # AFTER the send, never before: a row left PENDING is what
        # `delivery.py::_still_owed` sweeps up and sends again.
        conv = await _thread_for(db, lead)
        if conv is None:
            log.warning("Lead %d: breakdown sent but no thread to file it in", lead_id)
            return
        db.add(
            Message(
                conversation_id=conv.id,
                direction=MessageDirection.OUTBOUND,
                sender=MessageSender.AGENT,
                content=body,
                subject=subject[:500],
                internal=False,
                external_id=external_id,
                delivery_status=MessageStatus.SENT if external_id else MessageStatus.FAILED,
                last_error=failure,
                # Spent on failure so the retry sweep leaves it alone rather
                # than re-sending a message whose body it cannot rebuild.
                send_attempts=0 if external_id else MAX_ATTEMPTS,
                # `flags` as it comes back, NOT `flags or None`: the model says
                # NULL means the text never went through the filter and `[]`
                # means it did and came back clean, and collapsing the second
                # into the first throws away the only evidence that the screen
                # ran. Everything this function sends is lead-facing, so it is
                # always screened and this is never NULL.
                fair_housing_flags=flags,
            )
        )
        await db.commit()


async def _agency_brokerage_line(db: Any) -> str | None:
    from sqlalchemy import select

    from app.models import AgentSettings

    row = (await db.execute(select(AgentSettings.brokerage_line))).scalars().first()
    return row


async def _thread_for(db: Any, lead: Any) -> Any:
    """The lead's newest ACTIVE conversation whatever its channel, else an email
    one. Same order, and the same reason, as `visit_invite._record_in_thread`:
    always creating an email thread makes it 'primary' and flips the dashboard
    composer for a lead who has never used email."""
    from sqlalchemy import select

    from app.models import Conversation, ConversationStatus

    conv = (
        await db.execute(
            select(Conversation)
            .where(Conversation.lead_id == lead.id, Conversation.status == ConversationStatus.ACTIVE)
            .order_by(Conversation.id.desc())
        )
    ).scalars().first()
    if conv is not None:
        return conv
    conv = Conversation(lead_id=lead.id, channel=CHANNEL_EMAIL)
    db.add(conv)
    await db.flush()
    return conv
