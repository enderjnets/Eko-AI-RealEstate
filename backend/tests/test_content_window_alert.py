"""El aviso de ventana: que suene una vez, y que no suene cuando no toca.

Lo que fijan estos tests, en el orden en que importa:

1. **Un aviso por cambio, no por estado.** Dos tics seguidos con la misma
   situación mandan UN aviso. Es la propiedad entera: una alarma que se repite
   cada hora deja de leerse, y entonces parece cobertura sin serlo.
2. **Un aviso por tanda, no por pieza.** Seis piezas que entran el mismo día
   son un mensaje, no seis — el cupo de alertas se comparte con las averías.
3. **Ver y decir son dos hechos.** Si ningún transporte acepta el aviso, las
   piezas quedan SIN sellar y el siguiente tic reintenta.
4. **Nada que ya esté resuelto molesta.** Aprobada, publicando o publicada no
   generan aviso; una pieza sin ventana tampoco, jamás.
5. **La fecha se compara en la zona de la agencia**, que es donde el dueño
   vive el calendario.
"""
from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_bypass_session_factory, get_session_factory
from app.models import (
    AgentSettings,
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentStatus,
)
from app.services import content_window_alert
from app.services.content_window_alert import alert_due_windows
from app.services.tenant_context import org_scope

ORG = 1


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set — estos tests necesitan Postgres vivo")
    return url


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "CONTENT_WINDOW_ALERT_ENABLED", True, raising=False)
    # Esta instalación lleva de verdad una segunda organización (la "Demo" que
    # crea la migración 015). Decir de quién es el carril no es andamiaje: es
    # lo que producción también configura, y sin ello `not_our_rail` para.
    monkeypatch.setattr(s, "CONTENT_ORG_ID", ORG, raising=False)


class _Avisos:
    """Sustituye a `send_operator_alert`. Cuenta llamadas y puede fallar."""

    def __init__(self, acepta: bool = True) -> None:
        self.acepta = acepta
        self.enviados: list[tuple[str, str]] = []

    async def __call__(self, subject: str, body: str) -> bool:
        self.enviados.append((subject, body))
        return self.acepta


async def _zona(nombre: str = "America/Denver") -> None:
    async with get_bypass_session_factory()() as db:
        row = (
            await db.execute(text("SELECT id FROM agent_settings WHERE org_id=1"))
        ).first()
        if row is None:
            db.add(AgentSettings(org_id=ORG, timezone=nombre))
        else:
            await db.execute(
                text("UPDATE agent_settings SET timezone=:v WHERE org_id=1"),
                {"v": nombre},
            )
        await db.commit()


async def _limpiar() -> None:
    async with get_bypass_session_factory()() as db:
        await db.execute(text("DELETE FROM content_publications"))
        await db.execute(text("DELETE FROM content_pieces"))
        await db.commit()


async def _pieza(
    *,
    inicio: date | None,
    estado: ContentStatus = ContentStatus.NEEDS_APPROVAL,
    fin: date | None = None,
    gancho: str = "Aspens turn from the top down",
) -> int:
    async with get_bypass_session_factory()() as db:
        piece = ContentPiece(
            org_id=ORG,
            kind=ContentKind.GENERATED,
            language=ContentLanguage.EN,
            status=estado,
            hook=gancho,
            caption="12 places near Denver, sorted by elevation.",
            media_path="b" * 32 + ".mp4",
            publish_window_start=inicio,
            publish_window_end=fin,
        )
        db.add(piece)
        await db.commit()
        return piece.id


async def _sello(piece_id: int) -> datetime | None:
    async with get_bypass_session_factory()() as db:
        return (
            await db.execute(
                text("SELECT window_alerted_at FROM content_pieces WHERE id=:i"),
                {"i": piece_id},
            )
        ).scalar_one()


async def _tic() -> int:
    with org_scope(ORG):
        async with get_session_factory()() as db:
            return await alert_due_windows(db)


@pytest.mark.asyncio
async def test_avisa_una_vez_y_no_se_repite(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La propiedad entera: dos tics, un aviso."""
    await _limpiar()
    await _zona()
    avisos = _Avisos()
    monkeypatch.setattr(content_window_alert, "send_operator_alert", avisos)
    try:
        pid = await _pieza(inicio=date.today() - timedelta(days=1))

        assert await _tic() == 1
        assert len(avisos.enviados) == 1
        assert f"#{pid}" in avisos.enviados[0][1]
        sellada = await _sello(pid)
        assert sellada is not None

        # Segundo tic con TODO igual. Si esto manda otro, la alarma es ruido.
        assert await _tic() == 0
        assert len(avisos.enviados) == 1
        assert await _sello(pid) == sellada
    finally:
        await _limpiar()


@pytest.mark.asyncio
async def test_varias_piezas_del_mismo_dia_son_un_solo_aviso(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seis piezas de la banda alta entran juntas: un mensaje, seis sellos."""
    await _limpiar()
    await _zona()
    avisos = _Avisos()
    monkeypatch.setattr(content_window_alert, "send_operator_alert", avisos)
    try:
        ayer = date.today() - timedelta(days=1)
        ids = [await _pieza(inicio=ayer, gancho=f"pieza {n}") for n in range(4)]

        assert await _tic() == 4
        assert len(avisos.enviados) == 1, "una llamada, no una por pieza"
        cuerpo = avisos.enviados[0][1]
        for pid in ids:
            assert f"#{pid}" in cuerpo
            assert await _sello(pid) is not None
        assert avisos.enviados[0][0].startswith("4 piezas")
    finally:
        await _limpiar()


@pytest.mark.asyncio
async def test_si_no_se_pudo_avisar_no_se_sella_y_se_reintenta(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ver y decir son dos hechos: sin entrega aceptada, no hay sello."""
    await _limpiar()
    await _zona()
    fallando = _Avisos(acepta=False)
    monkeypatch.setattr(content_window_alert, "send_operator_alert", fallando)
    try:
        pid = await _pieza(inicio=date.today())

        assert await _tic() == 0
        assert len(fallando.enviados) == 1, "se intentó"
        assert await _sello(pid) is None, "no se sella lo que no se dijo"

        # El transporte se recupera: el siguiente tic sí avisa.
        bueno = _Avisos()
        monkeypatch.setattr(content_window_alert, "send_operator_alert", bueno)
        assert await _tic() == 1
        assert await _sello(pid) is not None
    finally:
        await _limpiar()


@pytest.mark.asyncio
async def test_no_avisa_de_lo_que_ya_esta_resuelto_ni_de_lo_que_no_toca(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _limpiar()
    await _zona()
    avisos = _Avisos()
    monkeypatch.setattr(content_window_alert, "send_operator_alert", avisos)
    try:
        ayer = date.today() - timedelta(days=1)
        await _pieza(inicio=ayer, estado=ContentStatus.APPROVED)
        await _pieza(inicio=ayer, estado=ContentStatus.PUBLISHING)
        await _pieza(inicio=ayer, estado=ContentStatus.PUBLISHED)
        # Sin ventana: no participa jamás, tenga el estado que tenga.
        await _pieza(inicio=None)
        # Su ventana empieza dentro de mucho: fuera de la antelación.
        await _pieza(inicio=date.today() + timedelta(days=30))

        assert await _tic() == 0
        assert avisos.enviados == []
    finally:
        await _limpiar()


@pytest.mark.asyncio
async def test_la_fecha_se_compara_en_la_zona_de_la_agencia(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """En Denver todavía es ayer cuando en UTC ya es hoy.

    A las 03:00 UTC de un día, en `America/Denver` son las 21:00 del anterior.
    Una ventana que abre "hoy en UTC" NO ha abierto para la agencia, y avisar
    entonces es el aviso un día antes que nadie notaría.
    """
    await _limpiar()
    await _zona()
    avisos = _Avisos()
    monkeypatch.setattr(content_window_alert, "send_operator_alert", avisos)
    try:
        hoy_utc = datetime.now(UTC).date()
        await _pieza(inicio=hoy_utc + timedelta(days=30))
        assert await _tic() == 0, "dentro de un mes no entra en la antelación"

        # Y con la zona rota no se adivina: mejor callar que una fecha falsa.
        await _limpiar()
        await _zona("Marte/Olympus")
        await _pieza(inicio=hoy_utc - timedelta(days=5))
        assert await _tic() == 0
        assert avisos.enviados == []
    finally:
        await _limpiar()
        await _zona()


@pytest.mark.asyncio
async def test_avisa_con_antelacion_porque_aprobar_no_es_publicar(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El borde exacto: con 3 días de antelación, el día 3 entra y el 4 no.

    No es cortesía. Una pieza aprobada no sale ese día: entra en la cola y
    compite por el cupo diario con las que siguen en `publishing`. Medido el
    9-sep-2026: la pieza 21 se aprobó a las 00:14 y seguía sin reclamar horas
    después, con franja estimada dos días más tarde. Avisar el día del `start`
    es avisar tarde.
    """
    await _limpiar()
    await _zona()
    avisos = _Avisos()
    monkeypatch.setattr(content_window_alert, "send_operator_alert", avisos)
    monkeypatch.setattr(
        get_settings(), "CONTENT_WINDOW_ALERT_LEAD_DAYS", 3, raising=False
    )
    try:
        justo = await _pieza(inicio=date.today() + timedelta(days=3))
        await _pieza(inicio=date.today() + timedelta(days=4))

        assert await _tic() == 1, "el día 3 entra, el 4 todavía no"
        assert f"#{justo}" in avisos.enviados[0][1]

        # Y con la antelación a cero vuelve a ser el comportamiento de "el
        # mismo día", que es justo el que llegaba tarde.
        await _limpiar()
        monkeypatch.setattr(
            get_settings(), "CONTENT_WINDOW_ALERT_LEAD_DAYS", 0, raising=False
        )
        await _pieza(inicio=date.today() + timedelta(days=1))
        assert await _tic() == 0
    finally:
        await _limpiar()
