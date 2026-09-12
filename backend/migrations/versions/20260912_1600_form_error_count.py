"""Cuántas veces falló el envío del formulario en una visita.

**Por qué existe.** `form_error` se emite desde `ConsultForm` con el motivo
(`captcha`, `rate`, `email`, `contact`, `generic`), el endpoint lo acepta y
`landing_events` lo guarda desde que existe la tabla. Y **nadie lo lee**: el
12-sep-2026 un `grep -rn form_error backend/app` devolvía un solo resultado, la
lista de tipos permitidos. Un visitante que pulsa enviar y recibe un error es
exactamente el caso que el panel debería gritar, y era el único que no aparecía
en ninguna pantalla.

**Por qué una columna y no una consulta a `landing_events`.** El docstring de
`traffic()` lo prohíbe, y con razón: los eventos se purgan a los noventa días
(`LANDING_EVENTS_RETENTION_DAYS`) mientras que un rango puede pedir hasta
`MAX_RANGE_DAYS = 366`. Sumar eventos haría que el trimestre pasado **encogiera
cada noche**, sin que nada fallara. La fila de sesión ya carga los demás
contadores por ese mismo motivo; éste va con ellos.

Un contador y no un `timestamp` como `form_started_at`: la pregunta aquí no es
«¿cuándo falló?» sino «¿cuántas veces se estrelló esta persona?». Tres intentos
fallidos y un abandono es una historia distinta de un fallo y un reintento con
éxito, y un `COALESCE` del primero las cuenta igual.

`NOT NULL DEFAULT 0`, igual que `cta_clicks` y `tel_clicks`: una visita que
nunca falló vale cero, no «se desconoce», y así ninguna suma necesita
`COALESCE`. Las filas ya existentes quedan en 0, y eso es una **aproximación honesta, no un
hecho medido**: en los 30 días previos no hubo ningún `form_error` en
`landing_events` (comprobado el 12-sep-2026, cero filas), así que para esa
ventana el 0 es cierto. Para sesiones más antiguas cuyos eventos ya se purgaron
no hay forma de saberlo, y no la habrá. **El contador empieza a contar desde el
despliegue**, y quien lea la cifra debe saberlo.

Sin `policy` ni `grant`: la RLS de `landing_sessions` es por fila y cubre todas
sus columnas, y los permisos del rol de aplicación son por tabla.

Migrar antes de arrancar es seguro y volver el código atrás no exige
`downgrade`: el código anterior a esta revisión no nombra la columna, y la
columna tiene defecto.

Revision ID: 058_form_error_count
Revises: 057_content_languages
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "058_form_error_count"
down_revision = "057_content_languages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "landing_sessions",
        sa.Column(
            "form_error_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("landing_sessions", "form_error_count")
