"""Re-export every model so Alembic autogenerate sees them via Base.metadata.

Order matters for cascades: parents before children.
"""
from app.models.account import Account
from app.models.agent_settings import AgentSettings
from app.models.allowed_user import AllowedUser
from app.models.call_log import CallLog, CallOutcome
from app.models.channel_route import CHANNELS, ChannelRoute, normalize_destination
from app.models.content import (
    ContentKind,
    ContentLanguage,
    ContentPiece,
    ContentPublication,
    ContentStatus,
    PublicationPlatform,
    PublicationStatus,
)
from app.models.conversation import Conversation, ConversationStatus
from app.models.follow_up import FollowUp, FollowUpKind, FollowUpStatus
from app.models.lead import Lead, LeadIntent, LeadStatus
from app.models.message import (
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
)
from app.models.organization import (
    DEFAULT_ORG_ID,
    DEMO_ORG_ID,
    Organization,
)
from app.models.property import Property, PropertySource, PropertyStatus
from app.models.sync_state import SyncState
from app.models.user_activity import UserActivity
from app.models.visit import Visit, VisitStatus

__all__: list[str] = [
    "DEFAULT_ORG_ID",
    "DEMO_ORG_ID",
    "Organization",
    "ChannelRoute",
    "CHANNELS",
    "normalize_destination",
    "Account",
    "AgentSettings",
    "AllowedUser",
    "CallLog",
    "ContentKind",
    "ContentLanguage",
    "ContentPiece",
    "ContentPublication",
    "ContentStatus",
    "PublicationPlatform",
    "PublicationStatus",
    "CallOutcome",
    "Conversation",
    "ConversationStatus",
    "FollowUp",
    "FollowUpKind",
    "FollowUpStatus",
    "Lead",
    "LeadIntent",
    "LeadStatus",
    "Message",
    "MessageDirection",
    "MessageSender",
    "MessageStatus",
    "Property",
    "PropertySource",
    "PropertyStatus",
    "SyncState",
    "UserActivity",
    "Visit",
    "VisitStatus",
]
