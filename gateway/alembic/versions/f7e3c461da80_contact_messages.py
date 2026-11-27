# Copyright 2017-present, The Visdom Authors
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f7e3c461da80"
down_revision = "c4d8a1e6f925"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("topic", sa.String(20), nullable=False),
        sa.Column("message", sa.String(5000), nullable=False),
        sa.Column("handled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sender_key", sa.String(64), unique=True),
        sa.Column("proxy_sender_key", sa.String(64), unique=True),
    )
    op.create_index("ix_contact_messages_created_at", "contact_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_contact_messages_created_at", table_name="contact_messages")
    op.drop_table("contact_messages")
