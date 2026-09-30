# Copyright 2017-present, The Visdom Authors
"""Removing a workspace's plot files when its rows go for good."""
import datetime
import uuid

import pytest

from app import account_deletion
from app.admin import activity, janitor
from app.models import User, Workspace, utcnow


@pytest.fixture
def instances(monkeypatch):
    def _set(answers):
        addresses = list(answers)
        asked = []

        def fake(address, body, timeout):
            asked.append((address, body))
            return answers[address]

        monkeypatch.setattr(activity, "instance_addresses", lambda: addresses)
        monkeypatch.setattr(activity, "_drop_on", fake)
        return asked
    return _set


def test_every_instance_is_asked_and_the_bytes_are_added_up(instances):
    asked = instances({
        "visdom-1:8097": {"removed": True, "bytes": 300},
        "visdom-2:8097": {"removed": False, "bytes": 0},
    })
    workspace_id = uuid.uuid4()

    result = activity.drop_workspace(workspace_id)

    assert result == {"asked": 2, "removed": True, "bytes": 300}
    assert sorted(address for address, _ in asked) == ["visdom-1:8097", "visdom-2:8097"]
    assert all(str(workspace_id).encode() in body for _, body in asked)


def test_one_silent_instance_stops_the_removal(instances):
    instances({"visdom-1:8097": {"removed": True, "bytes": 300}, "visdom-2:8097": None})

    with pytest.raises(activity.FilesKept) as caught:
        activity.drop_workspace(uuid.uuid4())

    assert "visdom-2:8097" in str(caught.value)


def test_with_no_instances_there_is_nothing_to_ask(monkeypatch):
    monkeypatch.setattr(activity, "instance_addresses", lambda: [])
    monkeypatch.setattr(activity, "_drop_on", lambda *a: pytest.fail("nothing should be asked"))

    assert activity.drop_workspace(uuid.uuid4())["removed"] is False


def _trash(db_session, workspace, days):
    row = db_session.query(Workspace).filter(Workspace.id == uuid.UUID(workspace["id"])).first()
    row.trashed_at = utcnow() - datetime.timedelta(days=days)
    db_session.commit()


def test_purging_the_trash_removes_the_files_first(client, make_user, make_workspace, db_session, monkeypatch):
    dropped = []
    monkeypatch.setattr(janitor, "drop_workspace", lambda wid: dropped.append(wid))
    workspace = make_workspace(make_user())
    _trash(db_session, workspace, janitor.TRASH_DAYS + 1)

    janitor.purge(db_session, uuid.UUID(workspace["id"]))

    assert dropped == [uuid.UUID(workspace["id"])]


def test_a_purge_that_cannot_reach_the_instances_keeps_the_rows(
    client, make_user, make_workspace, db_session, monkeypatch
):
    def refuse(_wid):
        raise activity.FilesKept("visdom-2 did not answer")

    monkeypatch.setattr(janitor, "drop_workspace", refuse)
    workspace = make_workspace(make_user())
    _trash(db_session, workspace, janitor.TRASH_DAYS + 1)

    with pytest.raises(activity.FilesKept):
        janitor.purge(db_session, uuid.UUID(workspace["id"]))

    db_session.expire_all()
    assert db_session.query(Workspace).filter(Workspace.id == uuid.UUID(workspace["id"])).first() is not None


def _due(client, db_session, user):
    response = client.post(
        "/api/v1/auth/me/deletion", json={"password": user["password"]}, headers=user["headers"]
    )
    assert response.status_code == 202, response.text
    record = db_session.query(User).filter(User.id == uuid.UUID(user["id"])).first()
    record.deletion_requested_at = utcnow() - datetime.timedelta(days=account_deletion.GRACE_DAYS + 1)
    db_session.commit()


def test_a_deleted_account_takes_its_workspaces_files(client, make_user, make_workspace, db_session, monkeypatch):
    dropped = []
    monkeypatch.setattr(
        account_deletion,
        "drop_workspace",
        lambda wid: dropped.append(wid) or {"removed": True, "bytes": 512},
    )
    user = make_user()
    workspace = make_workspace(user)
    _due(client, db_session, user)

    assert account_deletion.erase_due(db_session) == 1
    assert dropped == [uuid.UUID(workspace["id"])]


def test_an_account_whose_files_cannot_be_removed_waits(client, make_user, make_workspace, db_session, monkeypatch):
    def refuse(_wid):
        raise activity.FilesKept("visdom-2 did not answer")

    monkeypatch.setattr(account_deletion, "drop_workspace", refuse)
    user = make_user()
    workspace = make_workspace(user)
    _due(client, db_session, user)

    assert account_deletion.erase_due(db_session) == 0
    db_session.expire_all()
    assert db_session.query(User).filter(User.id == uuid.UUID(user["id"])).first() is not None
    assert db_session.query(Workspace).filter(Workspace.id == uuid.UUID(workspace["id"])).first() is not None
