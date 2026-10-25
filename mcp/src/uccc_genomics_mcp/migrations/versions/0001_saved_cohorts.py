"""saved cohorts: versions, cohorts, revisions, snapshots

Revision ID: 0001
Revises:
Create Date: 2026-10-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "cohort_version",
        sa.Column("cohort_id", sa.Text(), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("cohort_id"))
    op.create_table(
        "cohort",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("head", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_cohort_owner", "cohort", ["owner"])
    op.create_table(
        "cohort_revision",
        sa.Column("cohort", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("cohort_id", sa.Text(), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("op", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["cohort"], ["cohort.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohort_version.cohort_id"]),
        sa.PrimaryKeyConstraint("cohort", "seq"))
    op.create_table(
        "snapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("cohort_id", sa.Text(), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_date", sa.Date(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohort_version.cohort_id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_snapshot_created_by", "snapshot", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_snapshot_created_by", table_name="snapshot")
    op.drop_table("snapshot")
    op.drop_table("cohort_revision")
    op.drop_index("ix_cohort_owner", table_name="cohort")
    op.drop_table("cohort")
    op.drop_table("cohort_version")
