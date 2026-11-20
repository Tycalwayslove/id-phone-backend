"""Track fine matting and retain the previous source for concurrent renders.

Revision ID: f17b93a4c280
Revises: e4a8bc6192d0
"""

import sqlalchemy as sa

from alembic import op

revision = "f17b93a4c280"
down_revision = "e4a8bc6192d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("photos", sa.Column("matting_level", sa.Text()))
    op.add_column("photos", sa.Column("fine_matting_requested_at", sa.DateTime(timezone=True)))
    op.add_column("photos", sa.Column("previous_matting_file_id", sa.BigInteger()))
    op.create_foreign_key(
        "fk_photos_previous_matting_file_id_files",
        "photos",
        "files",
        ["previous_matting_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_photos_previous_matting_file_id", "photos", ["previous_matting_file_id"])
    op.create_check_constraint(
        op.f("ck_photos_matting_level_valid"), "photos", "matting_level IN ('fast', 'fine', 'failed')"
    )
    op.create_index(
        "ix_photos_fine_matting_pending",
        "photos",
        ["fine_matting_requested_at", "id"],
        postgresql_where=sa.text("matting_level = 'fast' AND status IN ('active', 'expired')"),
    )


def downgrade() -> None:
    op.drop_index("ix_photos_fine_matting_pending", table_name="photos")
    op.drop_constraint(op.f("ck_photos_matting_level_valid"), "photos", type_="check")
    op.drop_index("ix_photos_previous_matting_file_id", table_name="photos")
    op.drop_constraint("fk_photos_previous_matting_file_id_files", "photos", type_="foreignkey")
    op.drop_column("photos", "previous_matting_file_id")
    op.drop_column("photos", "fine_matting_requested_at")
    op.drop_column("photos", "matting_level")
