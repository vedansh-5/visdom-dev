# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Turn the instances' live counters into a durable hourly record.

Every number the instances report is cumulative since whenever that instance
last started, and the fan-out sums them across instances. Two things follow.
A restart makes the total drop, and that drop is not usage going backwards, it
is a counter that went back to zero. And the useful quantity is not the total
but how much of it is new since the last sample.

So each tick reads the merged totals, subtracts what it saw last time, and adds
the difference to the current hour. A total lower than last time is read as a
restart, and the new total is taken as the difference, which is what the
instance has counted since it came back.

The last-seen totals live in this process. Losing them costs one tick, because
the next sample treats the totals as a fresh start and the hour keeps whatever
had already been written to it.
"""

import datetime
import logging
import uuid

from sqlalchemy.orm import Session

from app.models import Workspace, WorkspaceUsageHour, utcnow

_COUNTERS = ("writes", "broadcasts", "broadcast_bytes")

_last_seen: dict = {}


def hour_start(moment: datetime.datetime | None = None) -> datetime.datetime:
    """The top of the hour a moment belongs to."""
    moment = moment or utcnow()
    return moment.replace(minute=0, second=0, microsecond=0)


def counter_delta(previous: int, current: int) -> int:
    """How much of a cumulative counter is new since it was last read."""
    if current < previous:
        return max(current, 0)
    return current - previous


def deltas_from(snapshot: dict, last_seen: dict) -> dict:
    """Per workspace, what changed since the last sample.

    Only workspaces with something to record are returned, so an idle
    deployment writes nothing rather than a row of zeroes every tick.
    """
    changes = {}
    for workspace_id, entry in (snapshot or {}).items():
        previous = last_seen.get(workspace_id, {})
        counters = {
            name: counter_delta(previous.get(name, 0), int(entry.get(name) or 0))
            for name in _COUNTERS
        }
        peak_bytes = int(entry.get("bytes") or 0)
        if any(counters.values()) or peak_bytes:
            changes[workspace_id] = {**counters, "peak_bytes": peak_bytes}
        last_seen[workspace_id] = {
            name: int(entry.get(name) or 0) for name in _COUNTERS
        }
    return changes


def _as_uuid(value):
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _fold(db: Session, workspace_id, bucket, change) -> None:
    row = (
        db.query(WorkspaceUsageHour)
        .filter(
            WorkspaceUsageHour.workspace_id == workspace_id,
            WorkspaceUsageHour.hour_start == bucket,
        )
        .first()
    )
    if row is None:
        db.add(
            WorkspaceUsageHour(
                workspace_id=workspace_id,
                hour_start=bucket,
                writes=change["writes"],
                broadcasts=change["broadcasts"],
                broadcast_bytes=change["broadcast_bytes"],
                peak_bytes=change["peak_bytes"],
            )
        )
        return
    row.writes = (row.writes or 0) + change["writes"]
    row.broadcasts = (row.broadcasts or 0) + change["broadcasts"]
    row.broadcast_bytes = (row.broadcast_bytes or 0) + change["broadcast_bytes"]
    row.peak_bytes = max(row.peak_bytes or 0, change["peak_bytes"])


def record(db: Session, snapshot: dict, when: datetime.datetime | None = None) -> int:
    """Fold one sample into the hourly rows. Returns the number folded in."""
    changes = deltas_from(snapshot, _last_seen)
    if not changes:
        return 0

    bucket = hour_start(when)
    known = {
        str(row_id)
        for (row_id,) in db.query(Workspace.id).filter(
            Workspace.id.in_([_as_uuid(k) for k in changes if _as_uuid(k)])
        )
    }

    folded = 0
    for workspace_id, change in changes.items():
        as_uuid = _as_uuid(workspace_id)
        if as_uuid is None or str(as_uuid) not in known:
            continue
        _fold(db, as_uuid, bucket, change)
        folded += 1

    if folded:
        db.commit()
    return folded


def reset_last_seen() -> None:
    """Forget the cumulative totals, as a fresh process would."""
    _last_seen.clear()


def sample_once(db: Session, snapshot_fn) -> int:
    """One tick: ask the instances, fold what they say into the current hour."""
    try:
        answer = snapshot_fn()
    except Exception as exc:
        logging.warning("usage sample could not reach the instances: %s", exc)
        return 0
    if not answer.get("answered"):
        return 0
    return record(db, answer.get("workspaces") or {})
