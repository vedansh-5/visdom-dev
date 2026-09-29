# Copyright 2017-present, The Visdom Authors
"""Removing the work a plan no longer keeps.

The window comes from the plan of whoever owns the workspace, and the sweep has
to reach the instance that holds it, because the instances share a disk and a
file deleted from the wrong one comes back. Deleting is off unless asked for,
which is the behaviour most worth pinning down: this is the one job whose
purpose is destroying work.
"""
import uuid

import pytest

from app import retention
from app.models import Plan, User, Workspace


@pytest.fixture
def instances(monkeypatch):
    monkeypatch.setattr(retention, "instance_addresses", lambda: ["visdom-1:8097", "visdom-2:8097"])


class Recorder:
    """Stands in for the instances, remembering what each was asked."""

    def __init__(self, loaded_at=None, envs=("january",)):
        self.loaded_at = loaded_at
        self.envs = list(envs)
        self.calls = []

    def __call__(self, address, workspace_id, days, dry_run, timeout):
        self.calls.append({"address": address, "days": days, "dry_run": dry_run})
        return {
            "workspace_id": str(workspace_id),
            "loaded": address == self.loaded_at,
            "envs": self.envs,
            "removed": 0 if dry_run else len(self.envs),
        }


def _owner(db_session, tier):
    user = User(
        id=uuid.uuid4(),
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        username=f"owner-{uuid.uuid4().hex[:6]}",
        password_hash="x",
        tier=tier,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _workspace(db_session, owner, slug="kept", **extra):
    workspace = Workspace(id=uuid.uuid4(), name=slug, slug=slug, created_by=owner.id, **extra)
    db_session.add(workspace)
    db_session.commit()
    return workspace


def test_the_window_comes_from_the_owners_plan(db_session):
    free = _workspace(db_session, _owner(db_session, "free"), slug="free-one")
    paid = _workspace(db_session, _owner(db_session, "pro"), slug="pro-one")

    assert retention.window_for(db_session, free) == 7
    assert retention.window_for(db_session, paid) == 90


def test_a_plan_that_keeps_everything_is_never_swept(db_session, instances):
    plan = db_session.query(Plan).filter(Plan.id == "enterprise").one()
    assert plan.retention_days is None
    _workspace(db_session, _owner(db_session, "enterprise"), slug="forever")

    asked = Recorder()
    summary = retention.sweep(db_session, enforce=True, ask=asked)

    assert summary["visited"] == 0
    assert asked.calls == []


def test_reporting_asks_every_instance_and_removes_nothing(db_session, instances):
    _workspace(db_session, _owner(db_session, "free"), slug="reported")

    asked = Recorder(loaded_at="visdom-2:8097")
    summary = retention.sweep(db_session, enforce=False, ask=asked)

    assert summary["with_expired"] == 1
    assert summary["removed"] == 0
    assert [call["dry_run"] for call in asked.calls] == [True, True]
    assert summary["workspaces"][0]["expired"] == ["january"]


def test_the_removal_is_sent_to_the_instance_holding_the_workspace(db_session, instances):
    """The instances share a disk. Sweeping from one that does not hold the
    workspace deletes files the holder writes back from memory."""
    _workspace(db_session, _owner(db_session, "free"), slug="held")

    asked = Recorder(loaded_at="visdom-2:8097")
    summary = retention.sweep(db_session, enforce=True, ask=asked)

    removals = [call for call in asked.calls if not call["dry_run"]]
    assert len(removals) == 1
    assert removals[0]["address"] == "visdom-2:8097"
    assert summary["removed"] == 1


def test_a_workspace_no_instance_holds_is_swept_anyway(db_session, instances):
    """A dormant workspace is nobody's, and its files still age."""
    _workspace(db_session, _owner(db_session, "free"), slug="dormant")

    asked = Recorder(loaded_at=None)
    retention.sweep(db_session, enforce=True, ask=asked)

    removals = [call for call in asked.calls if not call["dry_run"]]
    assert len(removals) == 1


def test_suspended_and_trashed_workspaces_are_left_alone(db_session, instances):
    import datetime

    owner = _owner(db_session, "free")
    _workspace(db_session, owner, slug="stopped", is_active=False)
    _workspace(
        db_session,
        owner,
        slug="binned",
        trashed_at=datetime.datetime.now(datetime.timezone.utc),
    )

    asked = Recorder()
    summary = retention.sweep(db_session, enforce=True, ask=asked)

    assert summary["visited"] == 0
    assert asked.calls == []


def test_an_instance_that_does_not_answer_does_not_stop_the_sweep(db_session, instances):
    _workspace(db_session, _owner(db_session, "free"), slug="patchy")

    def flaky(address, workspace_id, days, dry_run, timeout):
        if address == "visdom-1:8097":
            return None
        return {"loaded": True, "envs": ["january"], "removed": 0 if dry_run else 1}

    summary = retention.sweep(db_session, enforce=True, ask=flaky)

    assert summary["removed"] == 1
