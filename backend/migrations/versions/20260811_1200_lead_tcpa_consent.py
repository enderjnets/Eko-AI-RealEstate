"""Proof of what a lead consented to, not just that they did.

The public capture form is the first place this product asks a stranger for
permission to text them. TCPA does not treat "the box was ticked" as consent —
it asks what disclosure the person was looking at when they ticked it, and the
burden of producing that sits with the caller. A bare timestamp answers the
wrong question.

So four columns, not one: when, the exact wording rendered on the page, and the
IP + user agent that place the submission. They are columns rather than keys in
`leads.meta` because this is the record you hand a regulator or a plaintiff's
lawyer — it has to be queryable across every lead in one statement, and it must
not share a JSON blob with enrichment writers that overwrite each other.

No backfill. Nobody has web consent yet and NULL is the truthful answer for
every existing row: a WhatsApp lead who messaged us first is covered by having
initiated contact, which is a different exemption, not by consent we never
collected.

Revision ID: 027_lead_consent
Revises: 026_message_retry
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "027_lead_consent"
down_revision = "026_message_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("leads", sa.Column("consent_text", sa.Text(), nullable=True))
    # 45 characters holds any IPv6 address in its longest textual form
    # (IPv4-mapped, 45 chars). Stored as text, not INET: the value can arrive
    # from a proxy header as something that is not an address at all, and a
    # cast that raises would lose the lead over a field that is evidence, not
    # a key.
    op.add_column("leads", sa.Column("consent_ip", sa.String(length=45), nullable=True))
    op.add_column(
        "leads", sa.Column("consent_user_agent", sa.String(length=400), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("leads", "consent_user_agent")
    op.drop_column("leads", "consent_ip")
    op.drop_column("leads", "consent_text")
    op.drop_column("leads", "consent_at")
