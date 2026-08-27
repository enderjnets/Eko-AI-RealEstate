"""Email the calendar invitation for a booked visit.

The gap this closes, measured in production on 27-ago-2026: every visit ever
booked carries an `external_booking_id` of `calcom-sim-…`. `CALENDAR_SIMULATED`
defaults to true, so `create_booking` invents an id and books nothing. The
dashboard showed the appointment, the phone assistant told the caller out loud
that it was confirmed, and no calendar anywhere heard about it.

An `.ics` attachment is not a scheduling product and does not pretend to be:
it cannot read anyone's availability, so it does not stop us offering an hour
the agent is already busy. What it does is put the appointment in their
calendar and give the lead something to accept — which is the part the product
was promising and not doing.

**This must never break a booking.** The visit is the fact; the invitation is a
notification about it. Every failure here is caught and logged, because a
booking that exists and was not announced is recoverable, and a booking that
did not happen because an email server was down is not.
"""
from __future__ import annotations

import logging
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent_settings import AgentSettings
from app.models.lead import Lead
from app.models.visit import Visit
from app.services.email import Attachment, send_email
from app.services.icalendar import build_visit_ics

log = logging.getLogger(__name__)

_TEXT = {
    "en": {
        "subject": "Your visit is booked — {when}",
        "summary": "Property visit with {agency}",
        "body": (
            "Your visit is confirmed for {when}.\n\n"
            "{where}"
            "The calendar invitation is attached — open it to add the visit to your "
            "calendar.\n\n"
            "If you need to move or cancel it, just reply to this message.\n\n"
            "{agency}"
        ),
        "where": "Address: {address}\n\n",
        "agent_subject": "New visit booked — {when}",
        "agent_body": (
            "A visit has been booked for {when}.\n\n"
            "{who}{where}"
            "The calendar invitation is attached — open it to add the visit to "
            "your calendar.\n"
        ),
        # Everything needed to walk into the meeting informed, in the one email
        # that arrives. The agent should not have to open the dashboard to find
        # out who they are about to meet or how to reach them if they are late.
        "who": "Who: {name}\nPhone: {phone}\nEmail: {email}\n{notes}",
        "notes": "What they asked for: {notes}\n",
    },
    "es": {
        "subject": "Tu visita está agendada — {when}",
        "summary": "Visita a propiedad con {agency}",
        "body": (
            "Tu visita queda confirmada para el {when}.\n\n"
            "{where}"
            "Adjuntamos la invitación de calendario — ábrela para añadir la visita "
            "a tu calendario.\n\n"
            "Si necesitas cambiarla o cancelarla, responde a este mensaje.\n\n"
            "{agency}"
        ),
        "where": "Dirección: {address}\n\n",
        "agent_subject": "Nueva visita agendada — {when}",
        "agent_body": (
            "Se ha agendado una visita para el {when}.\n\n"
            "{who}{where}"
            "Adjuntamos la invitación de calendario — ábrela para añadirla a tu "
            "calendario.\n"
        ),
        "who": "Quién: {name}\nTeléfono: {phone}\nCorreo: {email}\n{notes}",
        "notes": "Qué pidió: {notes}\n",
    },
}


def _uid(visit: Visit) -> str:
    """Stable per visit, so a later update or cancellation replaces the event
    instead of leaving a duplicate next to it. Derived from the row id, never
    random: a random UID regenerated on reschedule is the classic way to end up
    with two appointments in someone's calendar and no way to remove the first.
    """
    return f"eko-visit-{visit.id}@realtors.ekoaiautomation.com"


def _when(visit: Visit) -> str:
    """The appointment in the OFFICE's timezone, spelled out.

    Not UTC and not the server's local time: a lead reading "16:00" for a 10am
    Denver showing is the same class of error this project fixed in four places
    in v0.56.0, only this time it is the human who is misled rather than the
    database.
    """
    from app.services.timezones import resolve_zone

    zone = resolve_zone(visit.timezone) or UTC
    return visit.scheduled_at.astimezone(zone).strftime("%A %d %B %Y, %H:%M (%Z)")


async def send_visit_invitation(
    db: AsyncSession,
    visit: Visit,
    lead: Lead | None,
    *,
    language: str = "en",
    cancelled: bool = False,
) -> None:
    """Send the .ics to the lead and to the agency. Never raises."""
    try:
        cfg = (await db.execute(select(AgentSettings))).scalars().first()
        agency = (getattr(cfg, "agency_name", None) or "").strip() or "our team"
        agent_email = (getattr(cfg, "booking_contact_email", None) or "").strip() or None

        # The organizer is the agency's booking mailbox when it has one. Falling
        # back to the platform's own from-address is deliberate: an invitation
        # with no ORGANIZER is rejected outright by Outlook, so "no booking
        # contact configured" must not mean "no invitation".
        s = get_settings()
        organizer = agent_email or _address_of(s.RESEND_FROM)
        if not organizer:
            log.error("Visit %s: no organizer address available; invitation not sent", visit.id)
            return

        t = _TEXT.get(language, _TEXT["en"])
        when = _when(visit)
        where = t["where"].format(address=visit.property_address) if visit.property_address else ""
        lead_email = ((lead.email if lead else None) or "").strip() or None
        lead_name = ((lead.name if lead else None) or "").strip() or None

        ics = build_visit_ics(
            uid=_uid(visit),
            starts_at=visit.scheduled_at,
            duration_minutes=visit.duration_minutes,
            summary=t["summary"].format(agency=agency),
            organizer_email=organizer,
            organizer_name=agency,
            attendee_email=lead_email,
            attendee_name=lead_name,
            location=visit.property_address,
            cancelled=cancelled,
        )
        attachment = Attachment(
            filename="invite.ics",
            content=ics.encode("utf-8"),
            # Explicit, so clients offer "Add to calendar" instead of a file to
            # download. `method=` tells them it is an invitation, not a copy.
            content_type=f"text/calendar; charset=utf-8; method={'CANCEL' if cancelled else 'REQUEST'}",
        )

        if lead_email:
            await _send_one(
                to=lead_email,
                subject=t["subject"].format(when=when),
                body=t["body"].format(when=when, where=where, agency=agency),
                attachment=attachment,
                visit_id=visit.id,
                who="lead",
                # This one IS a message to a lead, so it goes through the
                # opt-out funnel like every other. The agency copy below passes
                # no lead because it is not a message to one.
                lead=lead,
                db=db,
            )
        else:
            # Worth a line in the log rather than silence: with SMS parked, a
            # lead who left only a phone cannot be reached by any automatic
            # channel, and the agent needs to know to call them.
            log.warning(
                "Visit %s: the lead has no email address, so only the agency was "
                "notified — nobody has told this person their visit is booked",
                visit.id,
            )

        if agent_email:
            await _send_one(
                to=agent_email,
                subject=t["agent_subject"].format(when=when),
                body=t["agent_body"].format(
                    when=when,
                    who=t["who"].format(
                        # "—" rather than an empty line, so a missing field
                        # reads as "we do not have it" instead of looking like
                        # a formatting fault.
                        name=lead_name or "—",
                        phone=(lead.phone if lead else None) or "—",
                        email=lead_email or "—",
                        notes=t["notes"].format(notes=visit.notes) if visit.notes else "",
                    ),
                    where=where,
                ),
                attachment=attachment,
                visit_id=visit.id,
                who="agency",
            )
        else:
            log.warning(
                "Visit %s: booking_contact_email is empty in Settings, so the "
                "appointment did not reach the agency's calendar",
                visit.id,
            )
    except Exception as exc:  # noqa: BLE001 — the booking is the fact, this is the notice
        log.error("Visit %s: could not send the calendar invitation: %s", visit.id, exc)


async def _send_one(
    *,
    to: str,
    subject: str,
    body: str,
    attachment: Attachment,
    visit_id: int,
    who: str,
    lead: Lead | None = None,
    db: AsyncSession | None = None,
) -> None:
    """One recipient, failing on its own.

    Separated so that a bad lead address does not cost the agency its copy —
    they are two independent notifications and the earlier draft lost both to
    the first bounce.

    `lead` is passed ONLY when the recipient is that lead, and then this goes
    through `may_send_automated` like every other outbound message. The repo's
    AST sweep caught the first version of this file for skipping it, which is
    exactly what that sweep is for: opt-out is revoked consent and it outranks
    a booking. An opted-out lead still gets their visit — the agent is told and
    can phone them — they just do not get an email they asked not to receive.
    """
    if lead is not None and db is not None:
        from app.models.channel_route import CHANNEL_EMAIL
        from app.services.capture import may_send_automated

        if not await may_send_automated(lead, CHANNEL_EMAIL, db):
            log.info(
                "Visit %s: the lead has opted out, so the invitation went only to the agency",
                visit_id,
            )
            return
    try:
        await send_email(to=to, subject=subject, body_text=body, attachments=[attachment])
        log.info("Visit %s: calendar invitation sent to the %s", visit_id, who)
    except Exception as exc:  # noqa: BLE001
        log.error("Visit %s: invitation to the %s failed: %s", visit_id, who, exc)


def _address_of(value: str) -> str | None:
    """Pull the bare address out of `Name <a@b.c>`, which is how RESEND_FROM is
    written. Handed to ORGANIZER whole, the display name ends up inside the
    mailto: and the invitation is malformed."""
    raw = (value or "").strip()
    if "<" in raw and ">" in raw:
        raw = raw[raw.index("<") + 1 : raw.index(">")]
    raw = raw.strip()
    return raw or None
