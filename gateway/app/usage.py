# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
How much of a plan's countable allowance an account is using.

Shared by the billing page and by the checks that refuse a creation, so the
number someone is shown and the number they are held to are the same one.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.billing import at_limit
from app.models import APIKey, Membership, User, Workspace


def owned_workspace_ids(db: Session, user: User) -> list:
    return [
        row[0]
        for row in db.query(Workspace.id)
        .filter(Workspace.created_by == user.id, Workspace.trashed_at.is_(None))
        .all()
    ]


def workspaces_used(db: Session, user: User) -> int:
    return len(owned_workspace_ids(db, user))


def members_used(db: Session, user: User) -> int:
    owned = owned_workspace_ids(db, user)
    if not owned:
        return 0
    return (
        db.query(Membership)
        .filter(
            Membership.workspace_id.in_(owned),
            Membership.user_id != user.id,
            Membership.status == "active",
        )
        .count()
    )


def api_keys_used(db: Session, user: User) -> int:
    return db.query(APIKey).filter(APIKey.user_id == user.id).count()


COUNTERS = {
    "workspaces": workspaces_used,
    "members": members_used,
    "api_keys": api_keys_used,
}

_REFUSALS = {
    "workspaces": "You have reached the workspace limit for the {plan} plan.",
    "members": "You have reached the team member limit for the {plan} plan.",
    "api_keys": "You have reached the API key limit for the {plan} plan.",
}


def usage(db: Session, user: User) -> dict:
    return {name: count(db, user) for name, count in COUNTERS.items()}


def refuse_if_at_limit(db: Session, user: User, resource: str) -> None:
    """Stop a creation that the account's plan does not allow."""
    tier = user.tier or "free"
    if not at_limit(db, tier, resource, COUNTERS[resource](db, user)):
        return
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=_REFUSALS[resource].format(plan=tier),
    )
