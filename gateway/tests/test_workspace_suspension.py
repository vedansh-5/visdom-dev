# Copyright 2017-present, The Visdom Authors
import uuid

from app.admin import janitor, roles
from app.models import Workspace

WORKSPACES = "/api/v1/workspaces"
KEYS = "/api/v1/keys"
RESOLVE = "/api/v1/visdom/resolve"
RESOLVE_SESSION = "/api/v1/visdom/resolve-session"


def _write_key(client, user, workspace):
    created = client.post(
        KEYS,
        json={"name": "writer", "scope": "workspace", "workspace_ids": [workspace["id"]]},
        headers=user["headers"],
    )
    assert created.status_code == 201, created.text
    return created.json()["raw_key"]


def _set(db_session, workspace, **fields):
    row = (
        db_session.query(Workspace)
        .filter(Workspace.id == uuid.UUID(workspace["id"]))
        .one()
    )
    for name, value in fields.items():
        setattr(row, name, value)
    db_session.commit()


def test_a_new_workspace_is_active_and_not_trashed(client, make_user, make_workspace, db_session):
    user = make_user()
    workspace = make_workspace(user)

    row = (
        db_session.query(Workspace)
        .filter(Workspace.id == uuid.UUID(workspace["id"]))
        .one()
    )
    assert row.is_active is True
    assert row.trashed_at is None


def test_suspending_refuses_the_write_path(client, make_user, make_workspace, db_session):
    user = make_user()
    workspace = make_workspace(user)
    raw_key = _write_key(client, user, workspace)
    payload = {"workspace_slug": workspace["slug"]}

    allowed = client.post(RESOLVE, json=payload, headers={"X-API-KEY": raw_key})
    assert allowed.status_code == 200, allowed.text

    _set(db_session, workspace, is_active=False)

    refused = client.post(RESOLVE, json=payload, headers={"X-API-KEY": raw_key})
    assert refused.status_code == 403
    assert "suspended" in refused.json()["detail"].lower()


def test_suspending_refuses_the_browser_path(client, make_user, make_workspace, db_session):
    user = make_user()
    workspace = make_workspace(user)
    payload = {"workspace_slug": workspace["slug"]}

    allowed = client.post(RESOLVE_SESSION, json=payload, headers=user["headers"])
    assert allowed.status_code == 200, allowed.text

    _set(db_session, workspace, is_active=False)

    refused = client.post(RESOLVE_SESSION, json=payload, headers=user["headers"])
    assert refused.status_code == 403


def test_unsuspending_gives_the_workspace_back(client, make_user, make_workspace, db_session):
    user = make_user()
    workspace = make_workspace(user)
    payload = {"workspace_slug": workspace["slug"]}

    _set(db_session, workspace, is_active=False)
    assert client.post(RESOLVE_SESSION, json=payload, headers=user["headers"]).status_code == 403

    _set(db_session, workspace, is_active=True)
    restored = client.post(RESOLVE_SESSION, json=payload, headers=user["headers"])
    assert restored.status_code == 200
    assert restored.json()["workspace_id"] == workspace["id"]


def test_trashing_refuses_access_and_says_so(client, make_user, make_workspace, db_session):
    from app.models import utcnow

    user = make_user()
    workspace = make_workspace(user)
    payload = {"workspace_slug": workspace["slug"]}

    _set(db_session, workspace, trashed_at=utcnow())

    refused = client.post(RESOLVE_SESSION, json=payload, headers=user["headers"])
    assert refused.status_code == 403
    assert "trash" in refused.json()["detail"].lower()


def test_a_trashed_workspace_is_refused_even_when_active(client, make_user, make_workspace, db_session):
    """Trash wins over the suspension flag, so the reason given is the real one."""
    from app.models import utcnow

    user = make_user()
    workspace = make_workspace(user)
    _set(db_session, workspace, is_active=True, trashed_at=utcnow())

    refused = client.post(
        RESOLVE_SESSION, json={"workspace_slug": workspace["slug"]}, headers=user["headers"]
    )
    assert refused.status_code == 403
    assert "trash" in refused.json()["detail"].lower()


def test_trashed_workspaces_leave_the_members_listing(client, make_user, make_workspace, db_session):
    from app.models import utcnow

    user = make_user()
    kept = make_workspace(user)
    binned = make_workspace(user)

    listed = client.get(WORKSPACES, headers=user["headers"])
    assert {ws["id"] for ws in listed.json()} == {kept["id"], binned["id"]}

    _set(db_session, binned, trashed_at=utcnow())

    listed = client.get(WORKSPACES, headers=user["headers"])
    assert [ws["id"] for ws in listed.json()] == [kept["id"]]


def test_a_suspended_workspace_still_shows_in_the_listing(client, make_user, make_workspace, db_session):
    """Suspension is meant to be visible. A member who cannot get in is better
    off seeing the workspace than finding it silently gone."""
    user = make_user()
    workspace = make_workspace(user)
    _set(db_session, workspace, is_active=False)

    listed = client.get(WORKSPACES, headers=user["headers"])
    assert [ws["id"] for ws in listed.json()] == [workspace["id"]]


def test_support_may_suspend_but_not_trash():
    assert roles.can_change(roles.SUPPORT, "Workspace")
    assert roles.editable_fields(roles.SUPPORT, "Workspace") == {"is_active"}
    assert roles.editable_fields(roles.SUPERADMIN, "Workspace") == {
        "is_active",
        "trashed_at",
    }


def test_a_viewer_may_change_nothing():
    assert not roles.can_change(roles.VIEWER, "Workspace")
    assert roles.editable_fields(roles.VIEWER, "Workspace") == set()


def test_the_cleanup_page_reports_the_trash_with_its_age(client, make_user, make_workspace, db_session):
    import datetime

    user = make_user()
    fresh = make_workspace(user)
    old = make_workspace(user)
    now = datetime.datetime.now(datetime.timezone.utc)

    _set(db_session, fresh, trashed_at=now - datetime.timedelta(days=2))
    _set(db_session, old, trashed_at=now - datetime.timedelta(days=janitor.TRASH_DAYS + 1))

    ages = {ws.slug: days for ws, days in janitor.trashed_workspaces(db_session)}
    assert ages == {fresh["slug"]: 2, old["slug"]: janitor.TRASH_DAYS + 1}

    section = next(s for s in janitor.findings(db_session) if s["title"] == "In the trash")
    assert any("due for purge" in row for row in section["rows"])
    assert not any(row.startswith(fresh["slug"]) and "due" in row for row in section["rows"])


def test_a_trashed_workspace_is_not_also_reported_as_orphaned(client, make_user, make_workspace, db_session):
    """The two sections would otherwise name the same workspace twice."""
    from app.models import Membership, utcnow

    user = make_user()
    workspace = make_workspace(user)
    db_session.query(Membership).filter(
        Membership.workspace_id == uuid.UUID(workspace["id"])
    ).delete()
    db_session.commit()

    assert workspace["slug"] in {ws.slug for ws in janitor.empty_workspaces(db_session)}

    _set(db_session, workspace, trashed_at=utcnow())
    assert workspace["slug"] not in {ws.slug for ws in janitor.empty_workspaces(db_session)}
