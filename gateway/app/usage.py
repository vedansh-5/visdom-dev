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
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.billing import at_limit, limit_for
from app.models import APIKey, Membership, User, Workspace, WorkspaceUsageHour


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


def latest_storage(db: Session, workspace_ids) -> dict:
    """Bytes on disk per workspace, as of the most recent hour recorded.

    Storage is a level rather than a total, so this is the latest reading and
    never a sum over the month.
    """
    if not workspace_ids:
        return {}
    newest = (
        db.query(
            WorkspaceUsageHour.workspace_id,
            func.max(WorkspaceUsageHour.hour_start).label("hour_start"),
        )
        .filter(WorkspaceUsageHour.workspace_id.in_(workspace_ids))
        .group_by(WorkspaceUsageHour.workspace_id)
        .subquery()
    )
    rows = (
        db.query(WorkspaceUsageHour.workspace_id, WorkspaceUsageHour.peak_bytes)
        .join(
            newest,
            and_(
                WorkspaceUsageHour.workspace_id == newest.c.workspace_id,
                WorkspaceUsageHour.hour_start == newest.c.hour_start,
            ),
        )
        .all()
    )
    return {workspace_id: int(size or 0) for workspace_id, size in rows}


MEGABYTE = 1024 * 1024


def storage_used(db: Session, user: User) -> int:
    """Bytes on disk across every workspace the account owns, as last sampled."""
    return sum(latest_storage(db, owned_workspace_ids(db, user)).values())


def refuse_writes_over_storage(db: Session, workspace: Workspace) -> None:
    """Stop new plots once the workspace owner's plan is out of storage.

    The owner's plan is the one that pays, so a member writing into someone
    else's workspace is held to the owner's limit, not their own. Only writes
    are refused: reading and deleting still work, which is how an account gets
    back under the limit.
    """
    owner = workspace.creator
    if owner is None:
        return
    limit_mb = limit_for(db, owner.tier, "storage_mb")
    if limit_mb is None:
        return
    used = storage_used(db, owner)
    if used < limit_mb * MEGABYTE:
        return
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=(
            f"This workspace's owner has used all {limit_mb:,} MB of storage on the "
            f"{owner.tier} plan, so new plots are refused. Viewing still works; "
            "deleting old environments frees space."
        ),
    )
