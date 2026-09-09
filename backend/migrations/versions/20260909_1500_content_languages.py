"""The languages the daily video is written in, kept apart from the chat's.

`agent_settings.languages` is what the chat agent answers in, and the content
writer was taking turns over it. The live agency answers Spanish-speaking
clients in Spanish and wants every video in English, so every other daily
draft came out in Spanish and the owner rejected each one by hand (pieces 13,
15 and 20). Nothing Spanish was published — the approval queue held — but a
draft a person has to refuse every other day costs a generation and a decision
each time it happens.

One list per agency, English only by default, edited from Settings. With a
server_default because the table has rows: NOT NULL without one fails on the
live row, and `["en"]` is also the right answer for any row that reaches this
column without going through the ORM.

No policy and no grant: RLS on `agent_settings` is per row and covers every
column, and the app role's privileges are per table. Code from before this
revision ignores the column, so migrating first and starting after is safe,
and rolling the code back does not need `downgrade`.

Revision ID: 057_content_languages
Revises: 056_publish_window
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "057_content_languages"
down_revision = "056_publish_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_settings",
        sa.Column(
            "content_languages",
            sa.JSON(),
            nullable=False,
            server_default='["en"]',
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_settings", "content_languages")
