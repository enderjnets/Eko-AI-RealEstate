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
from app.services.ops_alert import MAX_ALERTS_PER_DAY, send_operator_alert
from app.services.tenant_context import run_for_every_org

log = logging.getLogger(__name__)

MONITOR_KEY = "llm_fallback"

# What each status means for the person reading the email at 7am. The probe
# returns a word; this turns it into the command that fixes it, because an alert
# that does not say what to do gets postponed until it is forgotten.
_REMEDY: dict[str, str] = {
    "unreachable": (
        "Ollama no responde en {base_url}.\n"
        "  - En el ROG: systemctl status ollama-bridge && systemctl status ollama\n"
        "  - El puente escucha en la IP del bridge de Docker, que Docker asigna\n"
        "    por orden de creacion: si alguna red se recreo, esa IP pudo migrar."
    ),
    "model-missing": (
        "Ollama responde en {base_url} pero no tiene el modelo {model}.\n"
        "  - En el ROG: ollama pull {model}"
    ),
    "off": (
        "OLLAMA_ENABLED esta en false, asi que no hay tercer eslabon.\n"
        "  - Si es a proposito, ignora este aviso."
    ),
}

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
    s = get_settings()
    if status in _HEALTHY:
        return (
            "[Eko Realtors] La red de seguridad LLM se ha recuperado",
            f"llm_fallback: {previous} -> {status}\n\n"
            "El tercer eslabon (Ollama local) vuelve a poder responder. "
            "No hace falta hacer nada.",
        )
    remedy = _REMEDY.get(status, "Estado desconocido: {status}").format(
        base_url=s.OLLAMA_BASE_URL, model=s.OLLAMA_MODEL, status=status
    )
    return (
        "[Eko Realtors] La red de seguridad LLM ha caido",
        f"llm_fallback: {previous or 'desconocido'} -> {status}\n\n"
        f"{remedy}\n\n"
        "Kimi y MiniMax no se ven afectados por esto. El riesgo es que fallen "
        "los dos a la vez (paso el 1-jun-2026: 403 y 429 en el mismo minuto): "
        "sin el eslabon local, los leads reciben la linea de espera en vez de "
        "una respuesta.\n\n"
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
        previous = row.state

        # ── the probe: alert only on a transition ────────────────────────
        #
        # `previous is None` is the first observation ever, not a change. It
        # still alerts when the reading is bad: discovering at boot that the net
        # is missing is exactly what we want to hear about. A first reading of
        # "ok" is silent, because nothing happened.
        changed = previous != status
        worth_saying = status not in _HEALTHY or previous is not None
        if changed and worth_saying:
            subject, body = _describe(status, previous)
            if _budget_left(row):
                if await send_operator_alert(subject, body):
                    row.alerts_today += 1
                    row.last_alert_at = datetime.now(UTC)
            else:
                # The state still advances. Holding it back so the next tick
                # retries would spend tomorrow's budget on today's loop, and the
                # reading is on /api/v1/health either way — which is what the
                # external heartbeat reads.
                log.error(
                    "LLM monitor: %s -> %s but the daily alert budget (%d) is spent; "
                    "not sending. Live state stays on /api/v1/health.",
                    previous, status, MAX_ALERTS_PER_DAY,
                )
        if changed:
            log.warning("LLM fallback state changed: %s -> %s", previous, status)
        row.state = status

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
                row.last_seen_fallback_at = newest
                if _budget_left(row):
                    sent = await send_operator_alert(
                        "[Eko Realtors] Un cliente recibio la respuesta enlatada",
                        f"{count} mensaje(s) salieron sellados provider='fallback' "
                        "desde el ultimo control.\n\n"
                        "Eso significa que la cadena entera (Kimi, MiniMax y el "
                        "Ollama local) fallo mientras un lead escribia, y recibio "
                        "'alguien te respondera en breve' en vez de una respuesta.\n\n"
                        f"Estado actual del eslabon local: {status}\n"
                        "Revisa las conversaciones recientes en la consola.",
                    )
                    if sent:
                        row.alerts_today += 1
                        row.last_alert_at = datetime.now(UTC)
                else:
                    log.error(
                        "LLM monitor: %d canned replies since %s but the daily alert "
                        "budget is spent; not sending.", count, cutoff,
                    )

        await session.commit()

    return status
