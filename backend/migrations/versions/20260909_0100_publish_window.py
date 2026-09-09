"""Cuándo debería salir esta pieza, y si ya avisamos de que no se aprobó.

La escalera de otoño publica cuatro bandas de altitud en ventanas distintas
(`frontend/lib/fallGuide.ts`): por encima de 9.500 ft es *mid to late
September*, Denver a 5.280 ft es *October into November*. El repartidor no
sabe nada de eso — `next_free_slot` busca el siguiente día libre y ya está — y
**esta migración no cambia eso.** El orden de publicación sigue siendo el orden
de `approved_at`, que es la única palanca de calendario que tiene el dueño.

Lo que estas columnas permiten es lo otro: **avisar** cuando una pieza entra en
su ventana y todavía nadie la ha aprobado. Guardar la ventana por pieza, y no
copiar las cuatro bandas de `fallGuide.ts` a Python, es deliberado: dos fuentes
de la misma verdad se separan en cuanto alguien toca una, y la que se quedaría
atrás sería justo la que decide cuándo avisar.

`window_alerted_at` es una columna aparte de la ventana por la misma razón por
la que `monitor_state` separa `state` de `alerted_state`: **ver y decir son dos
hechos distintos.** Se sella solo cuando el aviso fue aceptado por un
transporte; si el envío falla, la pieza sigue sin sellar y el siguiente tic lo
reintenta. Colapsar las dos cosas es como un envío fallido marca un problema
como reportado y lo silencia para siempre.

Las tres son nullable y sin defecto. Una pieza sin ventana **no genera ningún
aviso** y se comporta exactamente como hoy, así que ninguna de las piezas ya
existentes cambia de conducta, y el código anterior a esta revisión sigue
funcionando contra una base que ya la tenga: migrar primero y arrancar después
es seguro, y volver el código atrás no exige `downgrade`.

Fechas y no timestamps: una ventana editorial es «del 15 al 26 de septiembre»,
no un instante. La comparación con «hoy» la hace quien avisa, en la zona de la
agencia (`America/Denver`) — este carril ya convive con dos calendarios
(`_claimed_today` cuenta por día UTC, los huecos por día local) y un tercero
desalineado daría avisos un día antes o después sin que se note.

Sin policy y sin grant: la RLS de `content_pieces` es por fila y cubre todas
sus columnas, y los permisos del rol de aplicación son por tabla.

Revision ID: 056_publish_window
Revises: 055_calculator_snapshot
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "056_publish_window"
down_revision = "055_calculator_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_pieces",
        sa.Column("publish_window_start", sa.Date(), nullable=True),
    )
    op.add_column(
        "content_pieces",
        sa.Column("publish_window_end", sa.Date(), nullable=True),
    )
    op.add_column(
        "content_pieces",
        sa.Column("window_alerted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_pieces", "window_alerted_at")
    op.drop_column("content_pieces", "publish_window_end")
    op.drop_column("content_pieces", "publish_window_start")
