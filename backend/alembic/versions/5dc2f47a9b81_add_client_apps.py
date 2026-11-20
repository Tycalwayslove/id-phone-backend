"""Register client apps and track each user's first app.

Revision ID: 5dc2f47a9b81
Revises: f17b93a4c280
"""

import sqlalchemy as sa

from alembic import op

revision = "5dc2f47a9b81"
down_revision = "f17b93a4c280"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_apps",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("app_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "platform IN ('wx_mini', 'wx_mp', 'alipay_mini', 'douyin_mini', 'web')",
            name=op.f("ck_client_apps_platform_valid"),
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name=op.f("ck_client_apps_status_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_apps")),
        sa.UniqueConstraint("platform", "app_id", name="uq_client_apps_platform_app_id"),
    )
    op.add_column("users", sa.Column("source_app_id", sa.BigInteger()))
    op.create_foreign_key(
        "fk_users_source_app_id_client_apps",
        "users",
        "client_apps",
        ["source_app_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_users_source_app_id", "users", ["source_app_id"])


def downgrade() -> None:
    op.drop_index("ix_users_source_app_id", table_name="users")
    op.drop_constraint("fk_users_source_app_id_client_apps", "users", type_="foreignkey")
    op.drop_column("users", "source_app_id")
    op.drop_table("client_apps")
