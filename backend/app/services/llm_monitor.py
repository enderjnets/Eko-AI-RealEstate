"""Watching the LLM safety net, and telling someone when it goes.

v0.54.2 taught this install that `OLLAMA_ENABLED=true` asserts nothing about the
world: the flag stood for twelve weeks while the server was unreachable AND the
model was missing. It added a probe — but the probe ran once at startup and its
result sat on `/api/v1/health`, which is a question nobody was asking. A
measurement nobody reads is the same shape of mistake as a flag nobody checks.

So this module does two things a startup probe cannot:

**Re-measures.** Every tick, not once. Probing `/api/tags` is a local request
that costs nothing and does not load the model into VRAM, which is why the check
can be frequent while the alert stays rare.

**Waits for a second opinion before waking anyone.** A reading has to repeat
before it is allowed to spend an attempt. This is not caution for its own sake:
on 5-sep-2026 a flapping provider turned three genuine transitions into three
spent attempts, and the sustained outage that followed had no budget left to be
reported with. The damage sweep below is deliberately NOT debounced — a canned
reply is something that already happened to a customer, not a reading that might
settle.

**Reads the ground truth.** The probe says whether the net *could* catch a fall.
A message stamped ``llm_provider='fallback'`` says one already happened and was
missed: a real customer got "someone will get back to you shortly" instead of an
answer. That is the only signal here that describes damage rather than risk, so
it is reported even when everything else looks healthy.

What it deliberately does NOT do is probe Kimi and MiniMax. Every probe would
spend subscription quota, so the watchman would cause the exhaustion he is
watching for. They are observed for free from real traffic instead — and the
reason that is tolerable is precisely that the local fallback is now provably
healthy: if both paid providers die, the lead still gets a real reply.

**Seeing and saying are two separate facts.** `MonitorState.state` is the last
reading; `MonitorState.alerted_state` is the last thing the operator was
confirmed to have received, and only a 2xx from the mail provider advances it.
The first version collapsed them, so a transport failure at the wrong moment
retired the transition and the outage went unreported forever — this module
reproducing, internally, the exact failure it was built to catch.

The retry is simply the next tick, and it is **budgeted by attempt**, not by
delivery. An earlier draft charged only successful sends, reasoning that a
retry costs nothing; that reasoning was wrong in the expensive direction. A
send whose response times out has often already been delivered, so an unbudgeted
retry loop does not fail quietly — it mails the operator 288 times a day out of
the same quota that answers leads. A capped retry can delay an alert by a day.
An uncapped one can take down the product it is watching.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.db.base import get_bypass_session_factory
from app.models.message import Message
from app.models.monitor_state import MonitorState
from app.services.llm import FallbackStatus, check_fallback_provider
from app.services.ops_alert import (
    MAX_ALERTS_PER_DAY,
    send_operator_alert,
    undeliverable_reason,
)
from app.services.tenant_context import run_for_every_org

log = logging.getLogger(__name__)

MONITOR_KEY = "llm_fallback"

# What each status means for the person reading the email at 7am. The probe
# returns a word; this turns it into the command that fixes it, because an alert
# that does not say what to do gets postponed until it is forgotten.
# The remedy is BUILT, not looked up, and this is not decoration.
#
# The probe returns one word about the whole net, and one word cannot carry a
# pair: with Groq unreachable and the laptop merely missing its model, `unreachable`
# is the honest summary — but a fixed template then told the owner "neither link
# responds" (false: one does) and sent him to run `systemctl status`, which comes
# back green, instead of the `ollama pull` that would actually restore the net.
# The mirror case sent him to `ollama pull` on a machine that was off the network.
#
# So no line here asserts the state of a provider. It says what the net could not
# do, and lists what to check on the links that EXIST — an install with no
# GROQ_API_KEY was being told to go and check a Groq that was never configured,
# and being shown a GROQ_MODEL the probe had never looked at.
def _remedy(status: str) -> str:
    s = get_settings()
    groq_on = bool((s.GROQ_API_KEY or "").strip())
    ollama_on = bool(s.OLLAMA_ENABLED)

    if status == "off":
        return (
            "No hay red de seguridad configurada: ni GROQ_API_KEY ni\n"
            "OLLAMA_ENABLED. Kimi y MiniMax son lo unico que le responde a un\n"
            "lead, y si fallan los dos a la vez recibe la linea de espera.\n"
            "  - Si es a proposito, ignora este aviso."
        )

    lines = [
        "La red de seguridad no puede responder a un lead.",
        "",
        f"La sonda midio: {status}. Esa palabra describe la RED entera, no un",
        "proveedor: con dos eslabones no puede decir cual de los dos falla ni",
        "como. Revisa el que tengas puesto.",
        "",
    ]
    if groq_on:
        lines += [
            f"  - Groq ({s.GROQ_BASE_URL}) — este es el eslabon que sostiene",
            "    la red, y se arregla desde cualquier sitio:",
            "      * clave: revisa GROQ_API_KEY en el .env del VPS. Un 401 o un",
            "        403 sale en el log del backend nombrando la variable.",
            f"      * modelo: GROQ_MODEL={s.GROQ_MODEL} tiene que seguir en la",
            "        lista de console.groq.com. Lo gratis se retira sin avisar,",
            "        que es exactamente como se rompio Kling.",
        ]
    else:
        lines += [
            "  - Groq: NO configurado (GROQ_API_KEY vacia). Es el unico eslabon",
            "    que no depende de que haya alguien en casa; ponerlo es la",
            "    mejora mas barata que tiene esto.",
        ]
    if ollama_on:
        lines += [
            f"  - Ollama ({s.OLLAMA_BASE_URL}) — opcional, en el ROG:",
            "      * systemctl status ollama-bridge && systemctl status ollama",
            f"      * ollama pull {s.OLLAMA_MODEL}",
            "      * El puente escucha en la IP del bridge de Docker, que Docker",
            "        asigna por orden de creacion: si alguna red se recreo, esa",
            "        IP pudo migrar.",
        ]
    else:
        lines.append("  - Ollama: NO habilitado (OLLAMA_ENABLED=false).")
    return "\n".join(lines)


_HEALTHY: tuple[str, ...] = ("ok",)


def _today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


async def _load_or_create(session: Any) -> MonitorState:
    row = (
        await session.execute(select(MonitorState).where(MonitorState.key == MONITOR_KEY))
    ).scalar_one_or_none()
    if row is None:
        row = MonitorState(key=MONITOR_KEY)
        session.add(row)
        await session.flush()
    return row


def _budget_left(row: MonitorState) -> bool:
    """Is there room in today's alert budget?

    The counter belongs to a UTC day; a new day resets it in place rather than
    on a rolling window, which is how mail providers reset their quota too.
    """
    if row.alerts_day != _today_utc():
        row.alerts_day = _today_utc()
        row.alerts_today = 0
    return row.alerts_today < MAX_ALERTS_PER_DAY


async def _count_canned_replies(cutoff: datetime) -> tuple[int, datetime | None]:
    """Canned replies written after `cutoff`, across every organization.

    A background worker has no org bound, and under default-deny RLS that means
    it would see zero rows in every tenant forever — silently, which is the
    exact failure mode this module exists to prevent. `run_for_every_org` walks
    the tenants explicitly so the silence is impossible.
    """
    total = 0
    newest: datetime | None = None

    async def work(session: Any) -> None:
        nonlocal total, newest
        count, latest = (
            await session.execute(
                select(func.count(Message.id), func.max(Message.created_at)).where(
                    Message.llm_provider == "fallback",
                    Message.created_at > cutoff,
                )
            )
        ).one()
        total += int(count or 0)
        if latest is not None and (newest is None or latest > newest):
            newest = latest

    await run_for_every_org(work)
    return total, newest


def _describe(status: str, previous: str | None) -> tuple[str, str]:
    if status in _HEALTHY:
        return (
            "[Eko Realtors] La red de seguridad LLM se ha recuperado",
            f"llm_fallback: {previous} -> {status}\n\n"
            "La red de seguridad (Groq / Ollama) vuelve a poder responder. "
            "No hace falta hacer nada.",
        )
    remedy = _remedy(status)
    return (
        "[Eko Realtors] La red de seguridad LLM ha caido",
        f"llm_fallback: {previous or 'desconocido'} -> {status}\n\n"
        f"{remedy}\n\n"
        "Kimi y MiniMax no se ven afectados por esto. El riesgo es que fallen "
        "los dos a la vez (paso el 1-jun-2026: 403 y 429 en el mismo minuto): "
        "sin la red de seguridad, los leads reciben la linea de espera en vez "
        "de una respuesta.\n\n"
        "Estado en vivo: https://inmo-demo.ekoaiautomation.com/api/v1/health",
    )


async def run_monitor_tick() -> FallbackStatus:
    """One pass: re-measure, compare, report what changed. Returns the reading.

    Pulled out of the worker loop so it can be tested without a running app —
    the same reason `_startup_isolation_state` lives outside the startup hook.
    """
    status = await check_fallback_provider()

    session_factory = get_bypass_session_factory()
    async with session_factory() as session:
        row = await _load_or_create(session)
        # What the operator last HEARD — not what we last saw. The distinction
        # is the whole point: comparing against `row.state` meant a send that
        # failed still consumed the transition, and the outage was never
        # mentioned again.
        previous = row.alerted_state

        # ── the debounce: two readings agree before anyone is woken ──────
        #
        # Measured on 5-sep-2026, and it is why the outage that day went
        # unreported: the ROG flapped in and out of the tailnet, each flip was
        # a real transition, three of them spent the entire daily budget, and
        # when the machine finally hung for good there was nothing left to send
        # the alert with. `alerted_state` sat at "ok" through the whole thing.
        #
        # `row.state` already holds the PREVIOUS reading, so confirmation costs
        # no schema. The price is one tick of delay (five minutes) before the
        # first alert of an episode — including the first bad reading after a
        # boot, which used to be immediate.
        #
        # It compares **health, not the exact word**, and that is not a detail.
        # An earlier draft compared the strings, and a net that alternated
        # between two different failures (`unreachable` while the box is off
        # the network, `model-missing` once it answers with the model evicted)
        # would never see the same word twice: down one hundred percent of the
        # time and silent for ever, which is the failure this module exists to
        # prevent, reproduced inside the fix for it. Two consecutive readings
        # that agree on *whether the net can catch a fall* are a confirmation.
        healthy = status in _HEALTHY
        confirmed = row.state is not None and healthy == (row.state in _HEALTHY)

        # `row.state` is observability and moves unconditionally; it is what
        # /api/v1/health reports, so the live reading is never debounced — only
        # the decision to wake somebody is.
        if row.state != status:
            log.warning("LLM fallback state changed: %s -> %s", row.state, status)
        row.state = status

        # Committed HERE, before anything that can fail. The debounce reads the
        # previous reading back out of this column, so a reading that never
        # lands is a confirmation that can never happen: an exception later in
        # this tick (the per-tenant sweep, the sender, the final commit) would
        # roll the reading back, and every following tick would find the same
        # stale value and stay quiet — for ever, while the net is down. Before
        # the debounce the same rollback merely re-sent an alert that had
        # already gone out; now it would send none at all, so the observation
        # has to be durable on its own.
        await session.commit()

        # ── the probe: alert until the operator has actually been told ───
        #
        # `previous is None` is the first observation ever, not a change. It
        # still alerts when the reading is bad: discovering at boot that the net
        # is missing is exactly what we want to hear about. A first reading of
        # "ok" is silent, because nothing happened.
        # The operator is told about health changing, not about which flavour
        # of broken it is: `unreachable` and `model-missing` both mean the net
        # cannot catch a fall, and re-alerting as one becomes the other would
        # spend the day's budget describing a distinction that does not change
        # what he has to do. The body still names the specific reading and its
        # remedy.
        told_healthy = previous is not None and previous in _HEALTHY
        changed = previous is None or healthy != told_healthy

        if healthy and previous is None:
            row.alerted_state = status
        elif changed and not confirmed:
            # Seen once, not yet twice. Say nothing and let the next tick decide
            # — a flap dies here instead of spending an attempt.
            log.info(
                "LLM fallback read %s (was %s); waiting for a second reading "
                "before alerting", status, previous,
            )
        elif changed:
            subject, body = _describe(status, previous)
            undeliverable = undeliverable_reason()
            if undeliverable:
                # Nothing here is worth retrying: no number of attempts reaches
                # anyone until a human edits the configuration. Consume the
                # transition, say why once, and let /api/v1/health and the
                # external heartbeat carry the state in the meantime.
                log.error(
                    "LLM monitor: %s -> %s but the alert channel cannot deliver "
                    "(%s); not retrying. Subject was %r.",
                    previous, status, undeliverable, subject,
                )
                row.alerted_state = status
            elif _budget_left(row):
                # The ATTEMPT is charged, not the delivery, and that asymmetry
                # is deliberate. Charging only successes means a failing send
                # costs nothing, so the budget never closes and the next tick
                # tries again — 288 times a day, forever. Worse, a message the
                # provider accepted whose response timed out reads as a failure
                # here, so those 288 would be real duplicates spending the same
                # quota that answers leads. A capped retry can delay an alert by
                # a day; an uncapped one can take down the product it watches.
                row.alerts_today += 1
                row.last_alert_at = datetime.now(UTC)
                if await send_operator_alert(subject, body):
                    row.alerted_state = status
                else:
                    # `alerted_state` stays put: the next tick finds the same
                    # gap and tries again, within the budget above.
                    log.error(
                        "LLM monitor: %s -> %s but the alert did not go out; "
                        "will retry (attempt %d of %d today).",
                        previous, status, row.alerts_today, MAX_ALERTS_PER_DAY,
                    )
            else:
                log.error(
                    "LLM monitor: %s -> %s but the daily alert budget (%d) is spent; "
                    "not sending. Will retry after the UTC day rolls over. Live "
                    "state stays on /api/v1/health.",
                    previous, status, MAX_ALERTS_PER_DAY,
                )

        # ── the ground truth: a customer already paid for an outage ──────
        cutoff = row.last_seen_fallback_at
        if cutoff is None:
            # First run: take a high-water mark instead of reporting history.
            # This row is created once ever, so "first run" is not a recurring
            # excuse to stay quiet.
            row.last_seen_fallback_at = datetime.now(UTC)
        else:
            count, newest = await _count_canned_replies(cutoff)
            if count and newest is not None:
                undeliverable = undeliverable_reason()
                if undeliverable:
                    # Same reasoning as above, plus one specific to this branch:
                    # holding the mark back for a channel that can never deliver
                    # would freeze the cutoff, and this sweep re-counts from it
                    # on every tick across every organization — an unbounded
                    # window over a column with no index.
                    log.error(
                        "LLM monitor: %d canned replies since %s but the alert "
                        "channel cannot deliver (%s); not retrying.",
                        count, cutoff, undeliverable,
                    )
                    row.last_seen_fallback_at = newest
                elif _budget_left(row):
                    row.alerts_today += 1
                    row.last_alert_at = datetime.now(UTC)
                    sent = await send_operator_alert(
                        "[Eko Realtors] Un cliente recibio la respuesta enlatada",
                        f"{count} mensaje(s) salieron sellados provider='fallback' "
                        "desde el ultimo control.\n\n"
                        "Eso significa que la cadena entera (Kimi, MiniMax, Groq "
                        "y el Ollama local) fallo mientras un lead escribia, y "
                        "recibio 'alguien te respondera en breve' en vez de una "
                        "respuesta.\n\n"
                        f"Estado actual de la red de seguridad: {status}\n"
                        "Revisa las conversaciones recientes en la consola.",
                    )
                    if sent:
                        # The mark moves only now. Advancing it before the send
                        # meant a rejected message erased the evidence that a
                        # real customer had been let down — the one signal here
                        # that describes damage rather than risk.
                        row.last_seen_fallback_at = newest
                    else:
                        log.error(
                            "LLM monitor: %d canned replies since %s but the alert did "
                            "not go out; will retry (attempt %d of %d today).",
                            count, cutoff, row.alerts_today, MAX_ALERTS_PER_DAY,
                        )
                else:
                    log.error(
                        "LLM monitor: %d canned replies since %s but the daily alert "
                        "budget is spent; not sending.", count, cutoff,
                    )

        await session.commit()

    return status
