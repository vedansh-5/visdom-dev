# Copyright 2017-present, The Visdom Authors
import json

import sqlalchemy as sa
from alembic import op

revision = "c7d4a9b10e62"
down_revision = "f7e3c461da80"
branch_labels = None
depends_on = None

OLD_FEATURES = ["Unlimited workspaces", "SSO & audit logs", "Unlimited retention", "Dedicated support", "Custom SLAs"]
NEW_FEATURES = [
    "Unlimited workspaces", "Unlimited members", "Unlimited storage", "Unlimited retention", "Dedicated support"
]
UNLIMITED = dict.fromkeys(["workspaces", "members", "api_keys", "storage_mb", "workspace_storage_mb"])


def replace_default_features(previous, replacement):
    op.get_bind().execute(
        sa.text("""
            UPDATE plans SET features = CAST(:replacement AS json)
            WHERE id = 'enterprise' AND price IS NULL AND retention_days IS NULL
            AND CAST(limits AS jsonb) = CAST(:limits AS jsonb)
            AND CAST(features AS jsonb) = CAST(:previous AS jsonb)
        """),
        {"replacement": json.dumps(replacement), "limits": json.dumps(UNLIMITED), "previous": json.dumps(previous)},
    )


def upgrade() -> None:
    replace_default_features(OLD_FEATURES, NEW_FEATURES)


def downgrade() -> None:
    replace_default_features(NEW_FEATURES, OLD_FEATURES)
