"""AgentSettings — singleton (id=1) row holding the per-deploy agency configuration.

One deploy = one inmobiliaria. The agent reads its persona, agency name, business
hours, and language preferences from this row at request time.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentSettings(Base):
    __tablename__ = "agent_settings"

    # Declared as a unique INDEX in __table_args__, not `unique=True` here.
    # `unique=True` emits a UniqueConstraint while migration 016 built an index,
    # so every `alembic revision --autogenerate` emitted a spurious drop/create
    # pair — and a permanently non-empty autogenerate is a broken drift alarm:
    # real schema drift hides behind the noise.
    __table_args__ = (Index("uq_agent_settings_org_id", "org_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # One row per organization — this stopped being a singleton when the product
    # became multi-tenant.
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    agency_name: Mapped[str] = mapped_column(String(160), default="Inmobiliaria", nullable=False)
    agency_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    agent_persona: Mapped[str] = mapped_column(
        Text,
        default=(
            "Eres el asistente virtual de una inmobiliaria. Atiendes en castellano "
            "natural, empático y profesional. Tu objetivo es captar leads, clasificar "
            "su intención (alquiler / compra / tasación), recopilar zona y presupuesto, "
            "y agendar visitas cuando proceda. Nunca inventes datos sobre propiedades; "
            "si no sabes algo, dilo y ofrece consultar al agente humano."
        ),
        nullable=False,
    )
    greeting_template: Mapped[str] = mapped_column(
        Text,
        default=(
            "¡Hola! Soy el asistente de {agency_name}. ¿En qué puedo ayudarte hoy? "
            "Cuéntame qué buscas (alquiler, compra o tasación) y en qué zona."
        ),
        nullable=False,
    )

    languages: Mapped[list] = mapped_column(JSON, default=lambda: ["es", "en"], nullable=False)

    # IANA timezone of the office (e.g. "America/Denver"). Used to interpret the
    # times the voice agent hears ("2 PM" → 2 PM local, not UTC) and to display
    # visits. Default UTC; the Settings page auto-detects the browser tz on load.
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)

    business_hours: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: {
            "monday":    {"open": "09:00", "close": "19:00"},
            "tuesday":   {"open": "09:00", "close": "19:00"},
            "wednesday": {"open": "09:00", "close": "19:00"},
            "thursday":  {"open": "09:00", "close": "19:00"},
            "friday":    {"open": "09:00", "close": "19:00"},
            "saturday":  {"open": "10:00", "close": "14:00"},
            "sunday":    None,
        },
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<AgentSettings id={self.id} agency={self.agency_name!r}>"
