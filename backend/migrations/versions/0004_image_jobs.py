"""Durable image execution journal and per-character active-operation constraint."""
import sqlalchemy as sa
from alembic import op

revision = '0004_image_jobs'
down_revision = '0003_video_jobs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('image_generation_jobs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('operation_key', sa.String(64), nullable=False, unique=True),
        sa.Column('active_slot', sa.String(64), nullable=True, unique=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False))
    op.create_index('ix_image_generation_jobs_project_id', 'image_generation_jobs', ['project_id'])


def downgrade() -> None:
    op.drop_table('image_generation_jobs')
