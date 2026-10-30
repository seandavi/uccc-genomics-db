"""request intake: IRB document references, requester attestations

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # no file passes through the app, so a reference has nothing to hash
    op.alter_column("irb_document", "sha256", existing_type=sa.Text(), nullable=True)
    op.add_column("irb_document", sa.Column("title", sa.Text(), nullable=True))
    op.create_table(
        "request_attestation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("attestation_version", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("signed_by", sa.Text(), nullable=False),
        sa.Column("signed_as", sa.Text(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["request.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_request_attestation_request_id", "request_attestation", ["request_id"])


def downgrade() -> None:
    """Deletes the document references #133 wrote (rows with a NULL sha256) so that sha256 can be NOT NULL again."""
    op.drop_index("ix_request_attestation_request_id", table_name="request_attestation")
    op.drop_table("request_attestation")
    op.drop_column("irb_document", "title")
    op.execute("DELETE FROM irb_document WHERE sha256 IS NULL")
    op.alter_column("irb_document", "sha256", existing_type=sa.Text(), nullable=False)
