"""Re-export every model so Alembic autogenerate sees them via Base.metadata.

Order matters for cascades: parents before children.
"""
from app.models.agent_settings import AgentSettings
from app.models.conversation import Conversation, ConversationStatus
from app.models.lead import Lead, LeadIntent, LeadStatus
from app.models.message import (
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
)
from app.models.property import Property, PropertySource
from app.models.visit import Visit, VisitStatus

__all__: list[str] = [
    "AgentSettings",
    "Conversation",
    "ConversationStatus",
    "Lead",
    "LeadIntent",
    "LeadStatus",
    "Message",
    "MessageDirection",
    "MessageSender",
    "MessageStatus",
    "Property",
    "PropertySource",
    "Visit",
    "VisitStatus",
]
