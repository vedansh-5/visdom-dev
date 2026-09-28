# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Removing the work a workspace's plan no longer keeps.

Every plan states how far back it keeps data and, until this, nothing acted on
it, so the free plan's seven days and the paid plan's ninety meant the same
thing: forever. The window belongs to the account that owns the workspace, the
same rule the storage limit follows, because the workspace is what the plan is
sold against and a member on a bigger plan should not quietly extend it.

Deleting is off by default. ``RETENTION_ENFORCE`` starts false so a deployment
runs this as a report for a while first, and what it says it would remove can be
read before anything is gone. That matters more here than anywhere else in the
product, because this is the one job whose whole purpose is destroying work.

The instances behind the proxy share one disk, so the sweep has to reach the
instance that actually holds a workspace. Each one is asked first, in report
mode, and the one that says it holds it is the one told to remove. When none
holds it, the workspace is dormant and any instance can sweep its files.
"""

import json
import logging
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app.admin.activity import instance_addresses
from app.config import settings
from app.models import Plan, User, Workspace

logger = logging.getLogger("visdom.retention")


def window_for(db: Session, workspace: Workspace) -> int | None:
    """How many days of work this workspace keeps, or None for all of it."""
    if workspace.created_by is None:
        return None
    owner = db.query(User).filter(User.id == workspace.created_by).first()
    if owner is None:
        return None
    plan = db.query(Plan).filter(Plan.id == (owner.tier or "")).first()
    if plan is None:
        return None
    return plan.retention_days


def sweepable(db: Session) -> list[Workspace]:
    """Workspaces a sweep should visit.

    A suspended or trashed workspace is left alone. Its owner cannot reach it to
    save anything, and the trash has a deletion rule of its own; taking work out
    of it while it waits would make that rule mean something else.
    """
    return (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.trashed_at.is_(None))
        .all()
    )


def ask_instance(address: str, workspace_id, days, dry_run: bool, timeout: float) -> dict | None:
    """One instance's answer about one workspace, or None if it did not give one."""
    request = urllib.request.Request(
        f"http://{address}/vis/_retire",
        data=json.dumps(
            {
                "workspace_id": str(workspace_id),
                "older_than_days": days,
                "dry_run": dry_run,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("could not reach %s about %s: %s", address, workspace_id, exc)
        return None


def _holder(answers: list[tuple[str, dict]]) -> str | None:
    """The address of the instance holding the workspace, if one does."""
    for address, answer in answers:
        if answer.get("loaded"):
            return address
    return None


def sweep_workspace(workspace: Workspace, days, enforce: bool, ask=ask_instance, timeout=None) -> dict:
    """Report, and optionally remove, one workspace's expired environments."""
    timeout = settings.RETENTION_TIMEOUT if timeout is None else timeout
    addresses = instance_addresses()
    answers = []
    for address in addresses:
        answer = ask(address, workspace.id, days, True, timeout)
        if answer is not None:
            answers.append((address, answer))

    expired = sorted({eid for _address, answer in answers for eid in answer.get("envs", [])})
    result = {
        "workspace": workspace.slug,
        "days": days,
        "expired": expired,
        "removed": 0,
        "enforced": bool(enforce),
    }
    if not expired or not enforce:
        return result

    target = _holder(answers) or (addresses[0] if addresses else None)
    if target is None:
        return result
    done = ask(target, workspace.id, days, False, timeout)
    result["removed"] = (done or {}).get("removed", 0)
    return result


def sweep(db: Session, enforce: bool | None = None, ask=ask_instance) -> dict:
    """Visit every workspace, reporting and optionally removing what has aged out.

    An account on a plan that keeps everything is skipped without asking any
    instance, which is most of the cost of this when the paid plans are the ones
    with work in them.
    """
    enforce = settings.RETENTION_ENFORCE if enforce is None else enforce
    summary = {"visited": 0, "with_expired": 0, "removed": 0, "workspaces": []}
    for workspace in sweepable(db):
        days = window_for(db, workspace)
        if not days:
            continue
        summary["visited"] += 1
        result = sweep_workspace(workspace, days, enforce, ask=ask)
        if not result["expired"]:
            continue
        summary["with_expired"] += 1
        summary["removed"] += result["removed"]
        summary["workspaces"].append(result)
        logger.info(
            "retention: %s keeps %s days, %d env(s) past it, %d removed",
            result["workspace"],
            days,
            len(result["expired"]),
            result["removed"],
        )
    return summary
