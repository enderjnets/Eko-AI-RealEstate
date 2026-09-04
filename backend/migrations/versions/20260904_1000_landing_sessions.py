"""landing_sessions + landing_events: what happened before the form.

Everything this product knows about a visitor begins the moment they submit the
form. Whoever read the page and left is invisible, so "the video brought a
hundred people and two wrote" and "the video brought two people and both wrote"
are the same picture today — and they call for opposite decisions.

Two tables rather than one, and the split is the point. `landing_sessions` is
the row a person is: one per visit, rolled up as they go, and the only thing a
report ever reads. `landing_events` is the raw stream behind it, kept for a
window and then deleted, because a scroll depth from three months ago answers
no question anybody asks.

**No cookie, no identifier that survives the visit.** The session key lives in
`sessionStorage` and dies with the tab, so this cannot follow anybody anywhere.
The IP is never stored — it is read for the rate limit and dropped — and the
user agent is reduced to a family (`phone`/`Chrome`/`iOS`) before it is
written. What is left is a shape, not a person.

`(org_id, session_key)` is unique per organization, not globally: the key is a
random client-side value with no authority behind it, so two agencies could
collide by chance, and scoping it means one visitor can never be merged into
another agency's row.

`lead_id` is how this joins the funnel: set once, when a submission arrives
carrying the same session key. Nullable and staying that way for most rows is
the honest state — the great majority of visits never become a lead, and that
ratio is the number this table exists to produce.

Revision ID: 051_landing_sessions
Revises: 050_publication_schedule
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")

revision = "051_landing_sessions"
down_revision = "050_publication_schedule"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
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
    op.create_table(
        "landing_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Text, not String(n), everywhere in these two tables. The values come
        # from a browser we do not control, and a bounded column turns a long
        # one into a 500 on a beacon nobody is watching. The API clips them.
        sa.Column("session_key", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("landing_path", sa.Text(), nullable=True),
        sa.Column("lang", sa.Text(), nullable=True),
        sa.Column("utm_source", sa.Text(), nullable=True),
        sa.Column("utm_medium", sa.Text(), nullable=True),
        sa.Column("utm_campaign", sa.Text(), nullable=True),
        sa.Column("utm_content", sa.Text(), nullable=True),
        sa.Column("utm_term", sa.Text(), nullable=True),
        sa.Column("referrer_host", sa.Text(), nullable=True),
        # Derived once, on the way in, from utm_source and the referrer host.
        # Stored rather than computed at read time so a report never has to
        # re-implement the classification and get a different answer.
        sa.Column("source", sa.Text(), nullable=False, server_default="direct"),
        sa.Column("device", sa.Text(), nullable=True),
        sa.Column("browser", sa.Text(), nullable=True),
        sa.Column("os", sa.Text(), nullable=True),
        # Instagram's and TikTok's embedded browsers, named. They strip the
        # referrer and sometimes the query string, so a visit through one of
        # them is under-attributed by construction — worth being able to count.
        sa.Column("in_app", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("screen_w", sa.Integer(), nullable=True),
        sa.Column("max_scroll_pct", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "sections_viewed",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("cta_clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tel_clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("form_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("form_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "lead_id",
            sa.Integer(),
            sa.ForeignKey("leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint("org_id", "session_key", name="uq_landing_session"),
    )
    op.create_index("ix_landing_sessions_org_id", "landing_sessions", ["org_id"])
    op.create_index("ix_landing_sessions_lead_id", "landing_sessions", ["lead_id"])
    # Every report is "this range, this agency", so that is the index.
    op.create_index(
        "ix_landing_sessions_org_first_seen",
        "landing_sessions",
        ["org_id", "first_seen_at"],
    )

    op.create_table(
        "landing_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.BigInteger(),
            sa.ForeignKey("landing_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.Text(), nullable=False),
        # When it happened according to the SERVER. A client clock is wrong on
        # a surprising number of phones and is trivially forgeable on a public
        # endpoint; a beacon that batches a few seconds of activity is close
        # enough for every question this answers.
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_landing_events_org_id", "landing_events", ["org_id"])
    op.create_index("ix_landing_events_session_id", "landing_events", ["session_id"])
    # The purge reads this, and so does any per-day breakdown of raw events.
    op.create_index("ix_landing_events_org_at", "landing_events", ["org_id", "at"])

    _rls("landing_sessions")
    _rls("landing_events")


def downgrade() -> None:
    op.drop_index("ix_landing_events_org_at", table_name="landing_events")
    op.drop_index("ix_landing_events_session_id", table_name="landing_events")
    op.drop_index("ix_landing_events_org_id", table_name="landing_events")
    op.drop_table("landing_events")
    op.drop_index("ix_landing_sessions_org_first_seen", table_name="landing_sessions")
    op.drop_index("ix_landing_sessions_lead_id", table_name="landing_sessions")
    op.drop_index("ix_landing_sessions_org_id", table_name="landing_sessions")
    op.drop_table("landing_sessions")
