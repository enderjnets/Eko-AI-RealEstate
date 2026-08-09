"""Give a booking an attendee address it can actually use.

Cal.com refuses a booking with no attendee email. Leads are keyed by phone —
the main channel is WhatsApp — so `attendee_email` was derived as "the phone,
if it happens to contain an @", which is true only for email-channel leads.
Every WhatsApp, SMS and voice lead therefore failed to book against a real
Cal.com account. Nothing caught it because CALENDAR_SIMULATED short-circuits
before the HTTP call and simulated is the default everywhere but production.

Two columns: somewhere to keep a lead's real address when we learn one, and
the agency's own inbox to use when we never do.

Revision ID: 025_lead_email_contact
Revises: 024_role_password_and_refs
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "025_lead_email_contact"
down_revision = "024_role_password_and_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("email", sa.String(length=255), nullable=True))
    op.create_index("ix_leads_email", "leads", ["email"])
    op.add_column(
        "agent_settings",
        sa.Column("booking_contact_email", sa.String(length=255), nullable=True),
    )
    # Backfill from what is already there: an email-channel lead's identifier
    # IS its address, and it has been sitting in `phone` all along.
    op.execute("UPDATE leads SET email = phone WHERE phone LIKE '%@%'")


def downgrade() -> None:
    op.drop_column("agent_settings", "booking_contact_email")
    op.drop_index("ix_leads_email", table_name="leads")
    op.drop_column("leads", "email")
