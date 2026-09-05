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


def test_deleting_a_workspace_puts_it_in_the_trash(client, make_user, make_workspace, db_session):
    """The rows survive, so an administrator can put it back."""
    user = make_user()
    workspace = make_workspace(user)

    removed = client.delete(f"{WORKSPACES}/{workspace['id']}", headers=user["headers"])
    assert removed.status_code == 204

    row = (
        db_session.query(Workspace)
        .filter(Workspace.id == uuid.UUID(workspace["id"]))
        .one()
    )
    assert row.trashed_at is not None


def test_a_trashed_workspace_keeps_its_memberships(client, make_user, make_workspace, add_member, db_session):
    """Deleting outright took these with it, which is what made it unrecoverable."""
    from app.models import Membership

    owner = make_user()
    member = make_user()
    workspace = make_workspace(owner)
    add_member(owner, workspace, member)

    assert client.delete(f"{WORKSPACES}/{workspace['id']}", headers=owner["headers"]).status_code == 204

    kept = (
        db_session.query(Membership)
        .filter(Membership.workspace_id == uuid.UUID(workspace["id"]))
        .count()
    )
    assert kept == 2


def test_a_trashed_workspace_is_gone_from_every_member_route(client, make_user, make_workspace, add_member):
    """Invisible, not merely absent from the listing, or the trash would leak."""
    owner = make_user()
    member = make_user()
    workspace = make_workspace(owner)
    add_member(owner, workspace, member)

    assert client.delete(f"{WORKSPACES}/{workspace['id']}", headers=owner["headers"]).status_code == 204

    for user in (owner, member):
        assert client.get(WORKSPACES, headers=user["headers"]).json() == []
        members = client.get(f"{WORKSPACES}/{workspace['id']}/members", headers=user["headers"])
        assert members.status_code == 404


def test_deleting_a_trashed_workspace_answers_as_missing(client, make_user, make_workspace):
    """The same answer deleting an already-deleted one used to give."""
    user = make_user()
    workspace = make_workspace(user)

    assert client.delete(f"{WORKSPACES}/{workspace['id']}", headers=user["headers"]).status_code == 204
    again = client.delete(f"{WORKSPACES}/{workspace['id']}", headers=user["headers"])
    assert again.status_code == 404


def test_restoring_gives_the_workspace_back_to_its_members(client, make_user, make_workspace, add_member, db_session):
    """What a superadmin clearing trashed_at in the console amounts to."""
    owner = make_user()
    member = make_user()
    workspace = make_workspace(owner)
    add_member(owner, workspace, member)

    assert client.delete(f"{WORKSPACES}/{workspace['id']}", headers=owner["headers"]).status_code == 204
    _set(db_session, workspace, trashed_at=None)

    for user in (owner, member):
        listed = client.get(WORKSPACES, headers=user["headers"])
        assert [ws["id"] for ws in listed.json()] == [workspace["id"]]

    resolved = client.post(
        RESOLVE_SESSION, json={"workspace_slug": workspace["slug"]}, headers=owner["headers"]
    )
    assert resolved.status_code == 200


def _trash(db_session, workspace, days):
    import datetime

    _set(
        db_session,
        workspace,
        trashed_at=datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days),
    )


def test_only_workspaces_past_the_waiting_period_are_purgeable(client, make_user, make_workspace, db_session):
    user = make_user()
    fresh = make_workspace(user)
    due = make_workspace(user)

    _trash(db_session, fresh, 2)
    _trash(db_session, due, janitor.TRASH_DAYS + 1)

    assert [ws.slug for ws, _ in janitor.purgeable(db_session)] == [due["slug"]]


def test_purging_removes_the_workspace_and_its_memberships(client, make_user, make_workspace, add_member, db_session):
    from app.models import Membership

    owner = make_user()
    member = make_user()
    workspace = make_workspace(owner)
    add_member(owner, workspace, member)
    _trash(db_session, workspace, janitor.TRASH_DAYS + 1)

    slug = janitor.purge(db_session, uuid.UUID(workspace["id"]))

    assert slug == workspace["slug"]
    assert (
        db_session.query(Workspace)
        .filter(Workspace.id == uuid.UUID(workspace["id"]))
        .first()
        is None
    )
    assert (
        db_session.query(Membership)
        .filter(Membership.workspace_id == uuid.UUID(workspace["id"]))
        .count()
        == 0
    )


def test_purging_refuses_a_workspace_that_is_not_due(client, make_user, make_workspace, db_session):
    """The waiting period is checked here too, not only by the page offering
    the button, since the route is reachable without it."""
    import pytest

    user = make_user()
    workspace = make_workspace(user)
    _trash(db_session, workspace, 3)

    with pytest.raises(ValueError, match="not due"):
        janitor.purge(db_session, uuid.UUID(workspace["id"]))

    assert (
        db_session.query(Workspace)
        .filter(Workspace.id == uuid.UUID(workspace["id"]))
        .first()
        is not None
    )


def test_purging_refuses_a_workspace_that_is_not_in_the_trash(client, make_user, make_workspace, db_session):
    import pytest

    user = make_user()
    workspace = make_workspace(user)

    with pytest.raises(ValueError, match="not in the trash"):
        janitor.purge(db_session, uuid.UUID(workspace["id"]))


def test_purging_something_already_gone_says_so(db_session):
    import pytest

    with pytest.raises(LookupError):
        janitor.purge(db_session, uuid.uuid4())


def test_the_listing_says_whether_a_workspace_is_suspended(client, make_user, make_workspace, db_session):
    """The console has nothing to show the member without this, so a suspended
    workspace looked ordinary and simply failed to open."""
    user = make_user()
    workspace = make_workspace(user)

    listed = client.get(WORKSPACES, headers=user["headers"])
    assert listed.json()[0]["is_active"] is True

    _set(db_session, workspace, is_active=False)

    listed = client.get(WORKSPACES, headers=user["headers"])
    assert listed.json()[0]["is_active"] is False
