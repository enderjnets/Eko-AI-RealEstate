"""Re-export every model so Alembic autogenerate sees them via Base.metadata.

Order matters for cascades: parents before children.
"""
from app.models.account import Account
from app.models.agent_calendar import (
    DEFAULT_DURATION_MINUTES,
    AgentCalendar,
    AppointmentActivity,
)
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
from app.models.landing import (
    LANDING_EVENT_TYPES,
    LANDING_SECTIONS,
    LandingEvent,
    LandingSession,
)
from app.models.lead import WON_KINDS, Lead, LeadIntent, LeadStatus
from app.models.lead_event import LEAD_EVENT_TYPES, LeadEvent
from app.models.message import (
    Message,
    MessageDirection,
    MessageSender,
    MessageStatus,
)
from app.models.monitor_state import MonitorState
from app.models.organization import (
    DEFAULT_ORG_ID,
    DEMO_ORG_ID,
    Organization,
)
from app.models.property import Property, PropertySource, PropertyStatus
from app.models.render_job import RenderJob, RenderJobKind, RenderJobStatus
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
    "AgentCalendar",
    "AppointmentActivity",
    "DEFAULT_DURATION_MINUTES",
    "AllowedUser",
    "CallLog",
    "ContentKind",
    "ContentLanguage",
    "ContentPiece",
    "ContentPublication",
    "ContentStatus",
    "PublicationPlatform",
    "PublicationStatus",
    "RenderJob",
    "RenderJobKind",
    "RenderJobStatus",
    "CallOutcome",
    "Conversation",
    "ConversationStatus",
    "FollowUp",
    "FollowUpKind",
    "FollowUpStatus",
    "LEAD_EVENT_TYPES",
    "LandingEvent",
    "LeadEvent",
    "WON_KINDS",
    "LandingSession",
    "LANDING_EVENT_TYPES",
    "LANDING_SECTIONS",
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
    "MonitorState",
    "SyncState",
    "UserActivity",
    "Visit",
    "VisitStatus",
]
