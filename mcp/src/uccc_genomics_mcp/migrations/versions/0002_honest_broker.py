"""honest broker: snapshot id on revisions, IRB registry, requests, reviews, releases

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOW = sa.text("now()")
JSONB = postgresql.JSONB(astext_type=sa.Text())
AUTHORIZATION = ["irb_authorization.irb_number", "irb_authorization.version"]


def upgrade() -> None:
    op.add_column("cohort_revision", sa.Column("snapshot_id", sa.Text(), nullable=True))
    op.create_table(
        "irb_authorization",
        sa.Column("irb_number", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("pi", sa.Text(), nullable=False),
        sa.Column("approval_date", sa.Date(), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("hipaa_pathway", sa.Text(), nullable=False),
        sa.Column("approved_population", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("irb_number", "version"),
        sa.CheckConstraint("version >= 1"),
        sa.CheckConstraint("status IN ('active','suspended','closed')"))
    op.create_table(
        "irb_document",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("irb_number", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("file_ref", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("section_cited", sa.Text(), nullable=True),
        sa.Column("protocol_version", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["irb_number", "version"], AUTHORIZATION),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("doc_type IN ('approval_letter','personnel_list','protocol_excerpt','consent_form')"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"))
    op.create_table(
        "irb_personnel",
        sa.Column("irb_number", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["irb_number", "version"], AUTHORIZATION),
        sa.PrimaryKeyConstraint("irb_number", "version", "person_id"))
    op.create_table(
        "request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requester", sa.Text(), nullable=False),
        sa.Column("cohort", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("irb_number", sa.Text(), nullable=True),
        sa.Column("irb_version", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("fields", JSONB, nullable=False),
        sa.Column("identifiers", JSONB, nullable=False),
        sa.Column("recipients", JSONB, nullable=False),
        sa.Column("storage_location", sa.Text(), nullable=False),
        sa.Column("retention_end", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["cohort", "seq"], ["cohort_revision.cohort", "cohort_revision.seq"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["irb_number", "irb_version"], AUTHORIZATION),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('draft','submitted','returned','approved','denied','fulfilled','closed')"),
        sa.CheckConstraint("status = 'draft' OR (irb_number IS NOT NULL AND irb_version IS NOT NULL "
                           "AND retention_end IS NOT NULL)"))
    op.create_index("ix_request_requester", "request", ["requester"])
    op.create_table(
        "review",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column("checklist", JSONB, nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["request.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("decision IN ('approve','return','deny')"))
    op.create_index("ix_review_request_id", "review", ["request_id"])
    op.create_table(
        "release",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("fields_released", JSONB, nullable=False),
        sa.Column("recipients", JSONB, nullable=False),
        sa.Column("sharepoint_link", sa.Text(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closeout_attested_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["request.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"),
        sa.CheckConstraint("row_count >= 0"))
    op.create_index("ix_release_request_id", "release", ["request_id"])
    op.create_table(
        "release_patient",
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("research_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["release.id"]),
        sa.PrimaryKeyConstraint("release_id", "research_id"),
        sa.CheckConstraint("research_id ~ '^[0-9a-f]{16}$'"))
    op.create_index("ix_release_patient_research_id", "release_patient", ["research_id"])


def downgrade() -> None:
    op.drop_index("ix_release_patient_research_id", table_name="release_patient")
    op.drop_table("release_patient")
    op.drop_index("ix_release_request_id", table_name="release")
    op.drop_table("release")
    op.drop_index("ix_review_request_id", table_name="review")
    op.drop_table("review")
    op.drop_index("ix_request_requester", table_name="request")
    op.drop_table("request")
    op.drop_table("irb_personnel")
    op.drop_table("irb_document")
    op.drop_table("irb_authorization")
    op.drop_column("cohort_revision", "snapshot_id")
