"""agent_calendars + visits.purpose/assigned_email: whose time is this?

Until now the product had no way to say *when a particular person can work*, and
that is not a missing feature so much as a missing noun. Nothing in the schema
belonged to a realtor: `grep` over `app/models` finds no assignment column on
`leads` or on `visits`, so "Natalia's availability" could not even be written
down, let alone honoured.

Three things already existed and none of them filled the gap:

  * `agent_settings.business_hours` — a per-ORG JSON blob whose only reader is
    `conversation.py`, which pastes it into the LLM prompt as prose. It does not
    filter a single offered slot. It stays exactly as it is; this table is not a
    replacement for it, and the two answer different questions ("when is the
    agency open" vs "when can this person be booked").
  * `calendar_cal.SIMULATED_HOURS_OF_DAY` — a hardcoded (10, 11, 14, 15, 16)
    used only while CALENDAR_SIMULATED is on.
  * The single Cal.com schedule of the brand account.

`agent_calendars` deliberately stores **no hours**. It holds the *link* between
a person, a kind of appointment, and the Cal.com objects that own the schedule.
Cal.com already implements recurring weekly windows, timezones, DST, buffers,
minimum notice and calendar conflicts; duplicating that here would create a
fourth source of truth for availability, and the three above are already one too
many. What is ours is the mapping and the identity; what is Cal.com's is time.

`visits.purpose` and `visits.assigned_email` are the other half: a booking has to
record *what kind* of appointment it is and *whose* it is, or the per-person
schedule above can never be checked against reality.

Existing rows: the four live visits become `showing` (they are property visits —
the only kind the product could book) and stay unassigned, which is the truth.
`assigned_email` is nullable on purpose: an unassigned visit is a real state (a
manual calendar block, or a booking made before this migration), not a defect.

Revision ID: 045_agent_scheduling
Revises: 044_message_internal
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")

revision = "045_agent_scheduling"
down_revision = "044_message_internal"
branch_labels = None
depends_on = None


# `create_type=False`: the type is created once, explicitly, in upgrade().
# Letting each column declaration create it races with itself when the same
# enum is used twice (here: agent_calendars.activity and visits.purpose).
ACTIVITY = postgresql.ENUM(
    "showing",
    "valuation",
    "call",
    "open_house",
    name="appointment_activity",
    create_type=False,
)


def _isolate(table: str) -> None:
    """The same default-deny policy every tenant table in this schema carries."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO {APP_ROLE}")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*ACTIVITY.enums, name=ACTIVITY.name).create(bind, checkfirst=True)

    op.create_table(
        "agent_calendars",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The login identity, not a display name: sessions carry the email
        # (`services/auth.py::token_email`) and `allowed_users.email` is what
        # grants access. Keyed on it so a row can never belong to somebody who
        # cannot sign in. Deliberately NOT a foreign key to allowed_users:
        # revoking someone's access should not silently delete the schedule
        # their booked visits were made against.
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("activity", ACTIVITY, nullable=False),
        # Cal.com's own ids. Text, not integers: they are opaque handles from
        # another system and nothing here does arithmetic on them.
        sa.Column("calcom_schedule_id", sa.String(length=64), nullable=True),
        sa.Column("calcom_event_type_id", sa.String(length=64), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="45"),
        # An agent who does not do open houses turns that row off rather than
        # deleting it, so the Cal.com ids survive and re-enabling is not a
        # re-provision.
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # One row per person per kind of appointment. This is what makes
        # provisioning idempotent: a second `ensure_calendars` cannot create a
        # second schedule for the same pair, it collides here.
        sa.UniqueConstraint("org_id", "email", "activity", name="uq_agent_calendar"),
    )
    op.create_index("ix_agent_calendars_org_id", "agent_calendars", ["org_id"])
    op.create_index(
        "ix_agent_calendars_org_email", "agent_calendars", ["org_id", "email"]
    )
    _isolate("agent_calendars")

    # No RLS policy and no GRANT for these two, for the reason checked in 043
    # and 044: `visits` already carries an org policy and `eko_app` holds
    # table-level DML on it, so new columns are reachable without a new grant.
    op.add_column(
        "visits",
        sa.Column("purpose", ACTIVITY, nullable=False, server_default="showing"),
    )
    op.add_column(
        "visits", sa.Column("assigned_email", sa.String(length=254), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("visits", "assigned_email")
    op.drop_column("visits", "purpose")
    op.drop_index("ix_agent_calendars_org_email", table_name="agent_calendars")
    op.drop_index("ix_agent_calendars_org_id", table_name="agent_calendars")
    op.drop_table("agent_calendars")
    # Dropped last: both users of the type are gone by now.
    postgresql.ENUM(name=ACTIVITY.name).drop(op.get_bind(), checkfirst=True)
