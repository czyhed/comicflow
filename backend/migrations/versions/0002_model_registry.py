"""Persistent, encrypted model configuration versions."""

import sqlalchemy as sa
from alembic import op

revision = "0002_model_registry"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_registry_versions",
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("model_registry_versions")
