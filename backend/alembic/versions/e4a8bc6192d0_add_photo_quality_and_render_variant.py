"""Add photo quality and distinguish renders by blemish points.

Revision ID: e4a8bc6192d0
Revises: b7c1d2e3f4a5
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "e4a8bc6192d0"
down_revision = "b7c1d2e3f4a5"
branch_labels = None
depends_on = None

VARIANT_COLUMNS = ["photo_id", "spec_id", "bg_color", "beauty_level", "watermarked"]
CONSTRAINT = "uq_photo_renders_variant"


def upgrade() -> None:
    op.add_column("photos", sa.Column("quality", JSONB(), nullable=True))
    op.add_column("photo_renders", sa.Column("variant_key", sa.Text(), server_default="", nullable=False))
    op.drop_constraint(CONSTRAINT, "photo_renders", type_="unique")
    op.create_unique_constraint(CONSTRAINT, "photo_renders", [*VARIANT_COLUMNS, "variant_key"])


def downgrade() -> None:
    # PostgreSQL 会在旧约束无法容纳已有祛痘变体时回滚整次迁移，避免静默丢图。
    op.drop_constraint(CONSTRAINT, "photo_renders", type_="unique")
    op.create_unique_constraint(CONSTRAINT, "photo_renders", VARIANT_COLUMNS)
    op.drop_column("photo_renders", "variant_key")
    op.drop_column("photos", "quality")
