"""Avisar cuando una pieza entra en su ventana y sigue sin aprobar.

**Por qué existe.** El repartidor no sabe de calendario: `next_free_slot` busca
el siguiente día libre, y el orden de publicación es el orden de `approved_at`.
Así que la única palanca que tiene el dueño para que una pieza salga en su
semana es **aprobarla en su semana** — y una palanca que hay que acordarse de
usar no es una palanca. Esto no cambia el reparto: solo avisa.

Dos reglas heredadas de `ops_alert`, y las dos vienen de fallos ya pagados:

1. **Avisar de un cambio, nunca de un estado.** Repetir el mismo aviso cada
   hora lo convierte en ruido, y entonces la alarma es peor que nada porque
   parece cobertura. Aquí el cambio es «esta pieza entró en ventana sin
   aprobar», y `window_alerted_at` es lo que impide repetirlo.
2. **Ver y decir son dos hechos distintos.** El sello se pone **solo si un
   transporte aceptó el aviso**. Si el envío falla, la pieza sigue sin sellar y
   el próximo tic reintenta. Sellar antes de enviar es como un envío fallido
   marca algo como reportado y lo silencia para siempre.

Y una tercera, propia: **un aviso por tic, no uno por pieza.** Las seis piezas
de la banda alta entran en ventana el mismo día; seis correos serían seis
sextas partes del cupo diario de alertas —que se comparte con las averías de
verdad— para decir una sola cosa.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ContentPiece, ContentStatus
from app.services.buffer_publisher import agency_zone
from app.services.content_studio import not_our_rail
from app.services.ops_alert import send_operator_alert

log = logging.getLogger(__name__)

# Una pieza en cualquiera de estos estados ya no necesita que nadie la apruebe.
# `rejected` y `failed` NO están: una pieza rechazada cuya ventana llega es una
# decisión que el dueño puede querer revisar, y callarse sobre ella sería
# decidir por él. `draft` y `needs_approval` son el caso normal.
_YA_RESUELTAS = (
    ContentStatus.APPROVED,
    ContentStatus.PUBLISHING,
    ContentStatus.PUBLISHED,
)


def _linea(piece: ContentPiece) -> str:
    gancho = (piece.hook or "").strip() or "(sin gancho)"
    if len(gancho) > 90:
        gancho = gancho[:87] + "..."
    ventana = piece.publish_window_start.isoformat()
    if piece.publish_window_end:
        ventana += f" a {piece.publish_window_end.isoformat()}"
    return f"  #{piece.id} [{piece.status.value}] {ventana} — {gancho}"


async def alert_due_windows(db: AsyncSession) -> int:
    """Un tic, para una organización. Devuelve cuántas piezas se avisaron.

    Corre bajo `run_for_every_org`, así que la RLS ya lo acota al inquilino
    para el que se invocó.
    """
    settings = get_settings()
    if not settings.CONTENT_WINDOW_ALERT_ENABLED:
        return 0

    # De quién es este carril. La misma pregunta que hacen el escritor, la cola
    # de render y el publicador, contestada en un solo sitio — tres copias es
    # como se separan, y aquí la separación mandaría al dueño avisos sobre las
    # piezas de otra agencia.
    blocked = await not_our_rail()
    if blocked is not None:
        return 0

    # Sin zona no se compara. `agency_zone` devuelve None cuando la de la
    # agencia no sirve, y sus otros usuarios se niegan a programar antes que
    # adivinar: una fecha en la zona equivocada es peor que ninguna porque
    # parece correcta. Este carril ya convive con dos calendarios —
    # `_claimed_today` cuenta por día UTC y los huecos por día local— y un
    # tercero desalineado daría avisos un día antes o después sin que se note.
    zone = await agency_zone(db)
    if zone is None:
        log.warning("No se avisa de ventanas: la zona horaria de la agencia no sirve")
        return 0
    hoy = datetime.now(zone).date()
    # **Aprobar no es publicar.** Una pieza aprobada entra en la cola y compite
    # por el cupo diario con las que siguen en `publishing`; avisar el mismo dia
    # del `start` haria que saliera dos o tres dias tarde. Se avisa con
    # antelacion para que la aprobacion llegue antes que la fecha.
    limite = hoy + timedelta(days=max(0, settings.CONTENT_WINDOW_ALERT_LEAD_DAYS))

    vencidas = (
        (
            await db.execute(
                select(ContentPiece)
                .where(
                    ContentPiece.publish_window_start.is_not(None),
                    ContentPiece.publish_window_start <= limite,
                    ContentPiece.window_alerted_at.is_(None),
                    ContentPiece.status.not_in(_YA_RESUELTAS),
                )
                .order_by(
                    ContentPiece.publish_window_start.asc(), ContentPiece.id.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    if not vencidas:
        return 0

    cuantas = len(vencidas)
    subject = (
        f"{cuantas} pieza sin aprobar y su fecha se acerca"
        if cuantas == 1
        else f"{cuantas} piezas sin aprobar y sus fechas se acercan"
    )
    body = "\n".join(
        [
            "Estas piezas entran en la ventana en la que deberían "
            "publicarse y siguen sin aprobar.",
            "",
            "El orden de publicación es el orden en que se aprueban: el "
            "repartidor no mira estas fechas, solo busca el siguiente día "
            "libre. Y aprobar no es publicar — una pieza aprobada espera hueco "
            "un par de días. Por eso este aviso llega antes de la fecha: "
            "aprobarlas ahora es lo que hace que salgan en su semana.",
            "",
            *[_linea(p) for p in vencidas],
            "",
            f"Hoy es {hoy.isoformat()} en {zone.key}.",
            "Se aprueban en el panel, en Content Studio.",
        ]
    )

    # El sello va DESPUÉS y solo si alguien lo aceptó. `send_operator_alert`
    # nunca lanza: devuelve False cuando ningún transporte lo aceptó, y en ese
    # caso estas piezas quedan sin sellar a propósito para que el próximo tic
    # lo reintente.
    if not await send_operator_alert(subject, body):
        log.error("No se pudo avisar de %d pieza(s) en ventana; se reintentará", cuantas)
        return 0

    ahora = datetime.now(UTC)
    for piece in vencidas:
        piece.window_alerted_at = ahora
    await db.commit()
    log.info("Avisadas %d pieza(s) en ventana sin aprobar: %s",
             cuantas, ", ".join(f"#{p.id}" for p in vencidas))
    return cuantas
