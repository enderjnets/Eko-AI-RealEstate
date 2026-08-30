"""render_jobs: work this box cannot do, handed to the machine that can.

Rendering lives in the backend today (`services/content_render.py`), and for
lane A — normalise a phone clip to 9:16 and burn the brokerage line — that is
fine: ffmpeg, one clip at a time, done. Two things this table exists for are
not fine there.

**Subtitles.** A short with no captions is half a video, and transcription
means Whisper. Putting a speech model inside the API container makes every
deploy carry it and every restart load it, on a box whose actual job is
answering leads.

**Generated video.** Narration, images, assembly. That is minutes of CPU per
piece and a stack of media dependencies, next to the process a lead is waiting
on.

So the work moves to the machine that already renders video, and this table is
the contract between them. It is a QUEUE, not a transport: the worker asks for
a job, fetches its input, and hands back a file. Nothing is pushed to the
worker and no port is opened on it — it reaches in, which is the only direction
that works through the tunnel and the only one that needs no firewall change.

`(piece_id, kind)` is unique because a piece needs each kind of work at most
once, and that constraint — not the code — is what makes "enqueue if missing"
idempotent under a restart.

`claimed_at` and `attempts` are the whole recovery story: a worker that dies
mid-job leaves a CLAIMED row, and a claim older than the timeout returns to
QUEUED with one more attempt against it. Three attempts and it is FAILED with
the reason on the row, because a job that killed three workers will kill the
fourth and a person should read it instead.

Revision ID: 046_render_jobs
Revises: 045_agent_scheduling
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

APP_ROLE = os.environ.get("APP_DB_ROLE", "eko_app")

revision = "046_render_jobs"
down_revision = "045_agent_scheduling"
branch_labels = None
depends_on = None


RENDER_KIND = postgresql.ENUM(
    # Lane A: an uploaded clip becomes a vertical, subtitled, signed video.
    "subtitle_a",
    # Lane B: a written script becomes a video — narration, visuals, assembly.
    "produce_b",
    name="render_job_kind",
    create_type=False,
)

RENDER_STATUS = postgresql.ENUM(
    "queued",
    "claimed",
    "done",
    "failed",
    name="render_job_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*RENDER_KIND.enums, name=RENDER_KIND.name).create(
        bind, checkfirst=True
    )
    postgresql.ENUM(*RENDER_STATUS.enums, name=RENDER_STATUS.name).create(
        bind, checkfirst=True
    )

    op.create_table(
        "render_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "piece_id",
            sa.BigInteger(),
            sa.ForeignKey("content_pieces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", RENDER_KIND, nullable=False),
        sa.Column("status", RENDER_STATUS, nullable=False, server_default="queued"),
        # Which worker holds it, and since when. Both nullable: an unclaimed job
        # has neither, and writing a placeholder would make "nobody has this"
        # indistinguishable from "somebody with no name has this".
        sa.Column("worker", sa.String(length=64), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("piece_id", "kind", name="uq_render_job"),
    )
    op.create_index("ix_render_jobs_org_id", "render_jobs", ["org_id"])
    # The claim query's index: it asks for queued work, oldest first.
    op.create_index("ix_render_jobs_status", "render_jobs", ["status", "id"])

    op.execute("ALTER TABLE render_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE render_jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY render_jobs_tenant_isolation ON render_jobs
            USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
            WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::bigint)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE render_jobs TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE render_jobs_id_seq TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_render_jobs_status", table_name="render_jobs")
    op.drop_index("ix_render_jobs_org_id", table_name="render_jobs")
    op.drop_table("render_jobs")
    postgresql.ENUM(name=RENDER_STATUS.name).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name=RENDER_KIND.name).drop(op.get_bind(), checkfirst=True)
