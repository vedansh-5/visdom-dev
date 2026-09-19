# Copyright 2017-present, The Visdom Authors
"""The admin panel's pages render.

The panel is templates plus formatters, and neither is exercised by the rest of
the suite: a template that does not parse, or a formatter that raises on a row
it was not expecting, ships and is found by whoever opens the page. These are
deliberately shallow. They ask for each page and check it came back, which is
the failure that was going unnoticed.
"""
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from app.admin import panel
from app.models import AdminUser, Workspace
from app.security import get_password_hash

PAGES = [
    ("/admin/", "the overview"),
    ("/admin/user/list", "users"),
    ("/admin/workspace/list", "workspaces"),
    ("/admin/membership/list", "memberships"),
    ("/admin/api-key/list", "api keys"),
    ("/admin/workspace-invite/list", "invites"),
    ("/admin/shared-link/list", "shared links"),
    ("/admin/admin-user/list", "staff accounts"),
    ("/admin/admin-action/list", "the audit trail"),
    ("/admin/janitor", "the cleanup page"),
]


@pytest.fixture
def admin_client(db_session, monkeypatch):
    """A signed-in superadmin, and a session whose writes the panel can see.

    The engine comes from the session fixture rather than by importing conftest,
    which under pytest would load a second copy of that module with its own
    in-memory database and none of the tables in it.

    Rows for these tests are written through ``staff_db`` and committed, because
    sqladmin opens its own sessions and cannot see anything still sitting in the
    fixture's transaction.
    """
    bind = db_session.get_bind()
    engine = getattr(bind, "engine", bind)
    staff_sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(panel, "SessionLocal", staff_sessions)
    monkeypatch.setattr(panel, "engine", engine)
    from app.admin import usage_view

    monkeypatch.setattr(usage_view, "SessionLocal", staff_sessions)

    staff_db = staff_sessions()
    staff_db.add(
        AdminUser(
            id=uuid.uuid4(),
            email="staff@example.com",
            password_hash=get_password_hash("staffpassword"),
            role="superadmin",
            is_active=True,
        )
    )
    staff_db.commit()

    app = FastAPI()
    panel.mount_admin(app, secret_key="test-secret-for-the-admin-session")
    with TestClient(app) as client:
        signed_in = client.post(
            "/admin/login",
            data={"username": "staff@example.com", "password": "staffpassword"},
            follow_redirects=False,
        )
        assert signed_in.status_code in (302, 303), signed_in.text
        client.staff_db = staff_db
        yield client
    staff_db.close()


@pytest.mark.parametrize("path,what", PAGES)
def test_every_admin_page_renders(admin_client, path, what):
    response = admin_client.get(path, follow_redirects=False)
    assert response.status_code == 200, f"{what} at {path}: {response.status_code}"
    assert response.text.strip(), f"{what} rendered nothing"


def test_the_workspace_pages_render_with_a_workspace_in_every_standing(admin_client):
    """The standing formatter reads two columns and a cached activity lookup, so
    a workspace in each state is what actually exercises it."""
    import datetime

    db = admin_client.staff_db
    now = datetime.datetime.now(datetime.timezone.utc)
    ordinary = Workspace(id=uuid.uuid4(), name="Ordinary", slug="ordinary")
    db.add_all(
        [
            ordinary,
            Workspace(id=uuid.uuid4(), name="Stopped", slug="stopped", is_active=False),
            Workspace(
                id=uuid.uuid4(),
                name="Binned",
                slug="binned",
                trashed_at=now - datetime.timedelta(days=45),
            ),
        ]
    )
    db.commit()

    listing = admin_client.get("/admin/workspace/list", follow_redirects=False)
    assert listing.status_code == 200
    assert "suspended" in listing.text
    assert "in trash" in listing.text

    detail = admin_client.get(
        f"/admin/workspace/details/{ordinary.id}", follow_redirects=False
    )
    assert detail.status_code == 200

    cleanup = admin_client.get("/admin/janitor", follow_redirects=False)
    assert cleanup.status_code == 200
    assert "due for purge" in cleanup.text


def test_the_audit_trail_names_what_was_changed(admin_client):
    """A bare row id says a workspace was suspended without saying which one."""
    from app.models import AdminAction

    db = admin_client.staff_db
    workspace = Workspace(id=uuid.uuid4(), name="Named", slug="named-one")
    db.add(workspace)
    db.add(
        AdminAction(
            id=uuid.uuid4(),
            admin_email="staff@example.com",
            action="edit",
            model="Workspace",
            row_id=str(workspace.id),
            changes={"is_active": False},
        )
    )
    db.commit()

    trail = admin_client.get("/admin/admin-action/list", follow_redirects=False)
    assert trail.status_code == 200
    assert "named-one" in trail.text


def test_the_audit_trail_still_renders_once_the_row_is_gone(admin_client):
    """An entry outlives what it describes, which is the point of keeping one."""
    from app.models import AdminAction

    db = admin_client.staff_db
    db.add(
        AdminAction(
            id=uuid.uuid4(),
            admin_email="staff@example.com",
            action="delete",
            model="Workspace",
            row_id=str(uuid.uuid4()),
            changes={"purged_from_trash": "long-gone"},
        )
    )
    db.commit()

    trail = admin_client.get("/admin/admin-action/list", follow_redirects=False)
    assert trail.status_code == 200
    assert "long-gone (purged)" in trail.text


def test_the_workspace_page_reports_the_work_a_workspace_caused(admin_client, monkeypatch):
    """The counters come from the instances, so the page is asked with a known
    answer rather than a live deployment."""
    from app.admin import activity

    workspace = Workspace(id=uuid.uuid4(), name="Busy", slug="busy-one")
    admin_client.staff_db.add(workspace)
    admin_client.staff_db.commit()

    monkeypatch.setattr(
        activity,
        "cached_activity",
        lambda: {
            str(workspace.id): {
                "viewers": 1,
                "writers": 0,
                "writes": 12,
                "broadcasts": 30,
                "broadcast_bytes": 4096,
            }
        },
    )

    detail = admin_client.get(
        f"/admin/workspace/details/{workspace.id}", follow_redirects=False
    )
    assert detail.status_code == 200
    assert "12 writes" in detail.text
    assert "30 pushes" in detail.text
    assert "4.0 KB" in detail.text


def test_a_workspace_whose_instance_reports_no_counters_says_so(admin_client, monkeypatch):
    """A visdom without the counters should read as unknown rather than as a
    workspace that has done nothing."""
    from app.admin import activity

    workspace = Workspace(id=uuid.uuid4(), name="Quiet", slug="quiet-one")
    admin_client.staff_db.add(workspace)
    admin_client.staff_db.commit()

    monkeypatch.setattr(
        activity, "cached_activity", lambda: {str(workspace.id): {"viewers": 0}}
    )

    detail = admin_client.get(
        f"/admin/workspace/details/{workspace.id}", follow_redirects=False
    )
    assert detail.status_code == 200
    assert "not reported" in detail.text


def test_a_workspace_no_instance_mentions_has_never_been_written_to(
    admin_client, monkeypatch
):
    """Absent from an answer is a real answer.

    Every instance shares the env volume, so one that replies at all reports
    every workspace that has a directory. A workspace it does not mention has
    none, which means nobody has ever written to it.
    """
    from app.admin import activity

    workspace = Workspace(id=uuid.uuid4(), name="Fresh", slug="fresh-one")
    admin_client.staff_db.add(workspace)
    admin_client.staff_db.commit()

    monkeypatch.setattr(
        activity, "cached_snapshot", lambda: {"answered": True, "workspaces": {}}
    )

    detail = admin_client.get(
        f"/admin/workspace/details/{workspace.id}", follow_redirects=False
    )
    assert detail.status_code == 200
    assert "never" in detail.text
    assert "nothing yet" in detail.text


def test_a_workspace_stays_unknown_when_no_instance_answered(admin_client, monkeypatch):
    """Silence from every instance is not evidence that nothing has happened."""
    from app.admin import activity

    workspace = Workspace(id=uuid.uuid4(), name="Offline", slug="offline-one")
    admin_client.staff_db.add(workspace)
    admin_client.staff_db.commit()

    monkeypatch.setattr(
        activity, "cached_snapshot", lambda: {"answered": False, "workspaces": {}}
    )

    detail = admin_client.get(
        f"/admin/workspace/details/{workspace.id}", follow_redirects=False
    )
    assert detail.status_code == 200
    assert "unknown" in detail.text


def test_suspending_a_workspace_through_the_form_actually_saves(admin_client):
    """The write path, not just the page it is reached from.

    Every other test here asks for a page and checks it came back, which a
    broken save survives untouched: the form renders, the POST fails, and the
    only sign is an error banner nobody automated. sqladmin runs
    ``on_model_change`` through ``anyio.from_thread``, so a dependency that
    moves that attribute takes out every edit in the console at once while
    leaving all ten pages returning 200.
    """
    workspace = Workspace(id=uuid.uuid4(), name="Noisy", slug="noisy-one", is_active=True)
    admin_client.staff_db.add(workspace)
    admin_client.staff_db.commit()

    saved = admin_client.post(
        f"/admin/workspace/edit/{workspace.id}",
        data={"is_active": "false"},
        follow_redirects=False,
    )
    assert saved.status_code in (302, 303), saved.text

    admin_client.staff_db.expire_all()
    assert admin_client.staff_db.get(Workspace, workspace.id).is_active is False


def _staff_form(email, role="support", password="a-long-enough-password"):
    return {"email": email, "role": role, "password_hash": password}


def test_a_superadmin_can_add_a_staff_account(admin_client):
    """The reason this exists: adding a colleague without a shell on the box."""
    from app.models import AdminUser

    made = admin_client.post(
        "/admin/admin-user/create",
        data=_staff_form("new-colleague@example.com"),
        follow_redirects=False,
    )
    assert made.status_code in (302, 303), made.text

    admin_client.staff_db.expire_all()
    added = (
        admin_client.staff_db.query(AdminUser)
        .filter(AdminUser.email == "new-colleague@example.com")
        .first()
    )
    assert added is not None
    assert added.role == "support"


def test_the_password_is_stored_hashed_and_works(admin_client):
    """A stored plaintext password would be readable by anyone with the panel."""
    from app.models import AdminUser
    from app.security import verify_password

    admin_client.post(
        "/admin/admin-user/create",
        data=_staff_form("hashed@example.com", password="correct-horse-battery"),
        follow_redirects=False,
    )

    admin_client.staff_db.expire_all()
    added = (
        admin_client.staff_db.query(AdminUser)
        .filter(AdminUser.email == "hashed@example.com")
        .first()
    )
    assert added is not None
    assert added.password_hash != "correct-horse-battery"
    assert verify_password("correct-horse-battery", added.password_hash)


def test_a_short_password_is_refused(admin_client):
    """Twelve characters, the same floor the bootstrap script enforces."""
    from app.models import AdminUser

    refused = admin_client.post(
        "/admin/admin-user/create",
        data=_staff_form("tooshort@example.com", password="short"),
        follow_redirects=False,
    )
    assert refused.status_code not in (302, 303)

    admin_client.staff_db.expire_all()
    assert (
        admin_client.staff_db.query(AdminUser)
        .filter(AdminUser.email == "tooshort@example.com")
        .first()
        is None
    )


def test_an_unknown_role_is_refused(admin_client):
    """The role decides what the account can read, so it is not free text."""
    from app.models import AdminUser

    refused = admin_client.post(
        "/admin/admin-user/create",
        data=_staff_form("badrole@example.com", role="root"),
        follow_redirects=False,
    )
    assert refused.status_code not in (302, 303)

    admin_client.staff_db.expire_all()
    assert (
        admin_client.staff_db.query(AdminUser)
        .filter(AdminUser.email == "badrole@example.com")
        .first()
        is None
    )


def test_the_audit_trail_does_not_keep_the_password(admin_client):
    """Recording who added an account is useful. Recording the password they
    chose is a second place to steal it from, and it outlives the account."""
    from app.models import AdminAction

    admin_client.post(
        "/admin/admin-user/create",
        data=_staff_form("audited@example.com", password="a-memorable-secret"),
        follow_redirects=False,
    )

    admin_client.staff_db.expire_all()
    rows = admin_client.staff_db.query(AdminAction).all()
    assert rows, "the creation should have been recorded at all"
    for row in rows:
        assert "a-memorable-secret" not in str(row.changes)


def test_a_staff_account_can_be_stopped(admin_client):
    """Removing someone's access should not need a shell on the box either."""
    from app.models import AdminUser

    admin_client.post(
        "/admin/admin-user/create",
        data=_staff_form("leaver@example.com"),
        follow_redirects=False,
    )
    admin_client.staff_db.expire_all()
    leaver = (
        admin_client.staff_db.query(AdminUser)
        .filter(AdminUser.email == "leaver@example.com")
        .first()
    )
    assert leaver is not None and leaver.is_active

    stopped = admin_client.post(
        f"/admin/admin-user/edit/{leaver.id}", data={}, follow_redirects=False
    )
    assert stopped.status_code in (302, 303), stopped.text

    admin_client.staff_db.expire_all()
    assert admin_client.staff_db.get(AdminUser, leaver.id).is_active is False


def test_the_last_superadmin_cannot_be_stopped(admin_client):
    """A console that can lock everyone out of itself is recovered with a shell
    on the box, which is the thing this view exists to avoid."""
    from app.models import AdminUser

    only = (
        admin_client.staff_db.query(AdminUser)
        .filter(AdminUser.role == "superadmin", AdminUser.is_active.is_(True))
        .all()
    )
    assert len(only) == 1, "the fixture should sign in the only superadmin"

    refused = admin_client.post(
        f"/admin/admin-user/edit/{only[0].id}", data={}, follow_redirects=False
    )
    assert refused.status_code not in (302, 303)

    admin_client.staff_db.expire_all()
    assert admin_client.staff_db.get(AdminUser, only[0].id).is_active is True


def test_editing_a_staff_account_cannot_change_the_role(admin_client):
    """Changing what a colleague may see is a different decision from taking
    their access away, and the edit form is only for the second."""
    from app.models import AdminUser

    admin_client.post(
        "/admin/admin-user/create",
        data=_staff_form("support-only@example.com", role="support"),
        follow_redirects=False,
    )
    admin_client.staff_db.expire_all()
    account = (
        admin_client.staff_db.query(AdminUser)
        .filter(AdminUser.email == "support-only@example.com")
        .first()
    )
    assert account is not None

    admin_client.post(
        f"/admin/admin-user/edit/{account.id}",
        data={"is_active": "y", "role": "superadmin"},
        follow_redirects=False,
    )

    admin_client.staff_db.expire_all()
    assert admin_client.staff_db.get(AdminUser, account.id).role == "support"


def test_suspending_a_workspace_evicts_its_sockets(admin_client, monkeypatch):
    """Refusing the next resolve is not enough: a socket already open never
    resolves again, so a tab watching at the moment of suspension keeps
    watching until something else breaks the connection."""
    from app.admin import activity

    called = []
    monkeypatch.setattr(
        activity,
        "evict_workspace",
        lambda slug, reason=None: called.append((slug, reason)),
    )

    workspace = Workspace(id=uuid.uuid4(), name="Loud", slug="loud-one", is_active=True)
    admin_client.staff_db.add(workspace)
    admin_client.staff_db.commit()

    suspended = admin_client.post(
        f"/admin/workspace/edit/{workspace.id}", data={}, follow_redirects=False
    )
    assert suspended.status_code in (302, 303), suspended.text

    assert called, "suspending should have asked the instances to close its sockets"
    assert called[-1][0] == "loud-one"
    assert "suspended" in called[-1][1]


def test_an_active_workspace_is_not_evicted(admin_client, monkeypatch):
    """Saving the form without stopping anything should disconnect nobody."""
    from app.admin import activity

    called = []
    monkeypatch.setattr(
        activity, "evict_workspace", lambda slug, reason=None: called.append(slug)
    )

    workspace = Workspace(id=uuid.uuid4(), name="Fine", slug="fine-one", is_active=True)
    admin_client.staff_db.add(workspace)
    admin_client.staff_db.commit()

    admin_client.post(
        f"/admin/workspace/edit/{workspace.id}",
        data={"is_active": "y"},
        follow_redirects=False,
    )
    assert called == []


def _key(db, owner, name, *, age_days=5, used_days_ago=None):
    import datetime

    from app.models import APIKey

    now = datetime.datetime.now(datetime.timezone.utc)
    key = APIKey(
        id=uuid.uuid4(),
        name=name,
        prefix="visdom_live",
        hashed_key=uuid.uuid4().hex,
        user_id=owner.id,
        created_at=now - datetime.timedelta(days=age_days),
        last_used_at=(
            None if used_days_ago is None else now - datetime.timedelta(days=used_days_ago)
        ),
    )
    db.add(key)
    return key


def _owner(db):
    from app.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        username=f"owner-{uuid.uuid4().hex[:6]}",
        password_hash="x",
    )
    db.add(user)
    return user


def test_the_cleanup_page_links_to_the_unused_keys_page(admin_client):
    db = admin_client.staff_db
    _key(db, _owner(db), "forgotten")
    db.commit()

    cleanup = admin_client.get("/admin/janitor").text
    assert 'href="?section=keys"' in cleanup
    assert "Revoke forgotten" not in cleanup

    keys = admin_client.get("/admin/janitor?section=keys").text
    assert "forgotten" in keys
    assert 'name="revoke_one"' in keys


def test_revoking_one_unused_key_switches_it_off_and_records_it(admin_client):
    from app.models import AdminAction, APIKey

    db = admin_client.staff_db
    owner = _owner(db)
    forgotten = _key(db, owner, "forgotten")
    other = _key(db, owner, "also-forgotten")
    db.commit()

    done = admin_client.post(
        "/admin/janitor",
        data={"intent": "revoke", "key_id": str(forgotten.id)},
        follow_redirects=False,
    )
    assert done.status_code == 303
    assert "Revoked+1+unused+key" in done.headers["location"]

    db.expire_all()
    assert db.get(APIKey, forgotten.id).is_active is False
    assert db.get(APIKey, other.id).is_active is True
    entry = db.query(AdminAction).filter(AdminAction.row_id == str(forgotten.id)).one()
    assert entry.model == "APIKey"
    assert entry.changes["is_active"] is False


def test_revoke_all_switches_off_every_unused_key_and_nothing_else(admin_client):
    from app.models import APIKey

    db = admin_client.staff_db
    owner = _owner(db)
    stale = [_key(db, owner, f"stale-{n}") for n in range(3)]
    in_use = _key(db, owner, "in-use", used_days_ago=1)
    brand_new = _key(db, owner, "brand-new", age_days=0)
    db.commit()

    admin_client.post("/admin/janitor", data={"intent": "revoke_all"}, follow_redirects=False)

    db.expire_all()
    assert all(db.get(APIKey, key.id).is_active is False for key in stale)
    assert db.get(APIKey, in_use.id).is_active is True
    assert db.get(APIKey, brand_new.id).is_active is True


def test_a_key_that_is_in_use_cannot_be_revoked_from_the_cleanup_page(admin_client):
    """The route is reachable without the page, so the page's list is not
    trusted: a key that is not on it is left alone."""
    from app.models import APIKey

    db = admin_client.staff_db
    in_use = _key(db, _owner(db), "in-use", used_days_ago=1)
    db.commit()

    done = admin_client.post(
        "/admin/janitor",
        data={"intent": "revoke", "key_id": str(in_use.id)},
        follow_redirects=False,
    )
    assert "Nothing+was+revoked" in done.headers["location"]
    db.expire_all()
    assert db.get(APIKey, in_use.id).is_active is True


def test_a_key_name_cannot_reach_the_pages_javascript(admin_client):
    """Key names are typed by users; they reach the confirmation only as text."""
    db = admin_client.staff_db
    _key(db, _owner(db), '"><script>alert(1)</script>')
    db.commit()

    page = admin_client.get("/admin/janitor?section=keys").text
    assert "Revoke &#34;&gt;&lt;script&gt;alert(1)&lt;/script&gt;?" in page
    assert "<script>alert(1)" not in page


def _flashes(page):
    import json
    import re

    found = re.search(r'<script type="application/json" id="ap-flash">(.*?)</script>', page, re.S)
    assert found, "the page carries no notifications block"
    return json.loads(found.group(1))


def test_an_action_reports_back_as_a_notification_of_its_kind(admin_client):
    done = admin_client.post("/admin/janitor?section=keys", data={"intent": "revoke"}, follow_redirects=False)
    assert "notice_kind=error" in done.headers["location"]

    page = admin_client.get(done.headers["location"]).text
    assert _flashes(page) == [{"kind": "error", "message": "Select at least one key first."}]


def test_a_notice_cannot_break_out_of_the_notifications_block(admin_client):
    sneaky = "</script><script>alert(1)</script>"
    page = admin_client.get("/admin/janitor", params={"notice": sneaky, "notice_kind": "success"}).text
    assert "<script>alert(1)" not in page
    assert _flashes(page) == [{"kind": "success", "message": sneaky}]


def test_a_page_with_nothing_to_report_shows_no_notification(admin_client):
    assert _flashes(admin_client.get("/admin/janitor").text) == []


def test_no_admin_page_falls_back_to_the_browsers_own_dialogs():
    import pathlib
    import re

    templates = pathlib.Path(panel.__file__).parent / "templates"
    for template in templates.rglob("*.html"):
        text = template.read_text()
        assert not re.search(r"(?<![\w.])confirm\(", text), template.name
        assert not re.search(r"\son(?:click|submit|change)=", text), template.name


def test_deleting_a_row_asks_in_the_consoles_own_dialog(admin_client):
    page = admin_client.get("/admin/membership/list").text
    assert 'class="modal-content ap-confirm"' in page
    assert 'id="modal-delete-button"' in page


def _workspace(db, slug):
    workspace = Workspace(id=uuid.uuid4(), name=slug, slug=slug)
    db.add(workspace)
    return workspace


def _shared_link(db, workspace, *, expired_days_ago, email=None):
    import datetime

    from app.models import SharedLink

    now = datetime.datetime.now(datetime.timezone.utc)
    link = SharedLink(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        role="member",
        invite_email=email,
        expires_at=now - datetime.timedelta(days=expired_days_ago),
    )
    db.add(link)
    return link


def _invite(db, workspace, email):
    from app.models import WorkspaceInvite

    invite = WorkspaceInvite(id=uuid.uuid4(), workspace_id=workspace.id, email=email, role="member")
    db.add(invite)
    return invite


def test_each_leftover_list_links_to_a_page_of_its_own(admin_client):
    db = admin_client.staff_db
    workspace = _workspace(db, "left-behind")
    _shared_link(db, workspace, expired_days_ago=3, email="gone@example.com")
    _invite(db, workspace, _owner(db).email)
    db.commit()

    cleanup = admin_client.get("/admin/janitor").text
    assert 'href="?section=links"' in cleanup
    assert 'href="?section=invites"' in cleanup

    links = admin_client.get("/admin/janitor?section=links").text
    assert "gone@example.com" in links
    assert 'name="delete_one"' in links
    invites = admin_client.get("/admin/janitor?section=invites").text
    assert "left-behind" in invites
    assert 'name="delete_one"' in invites


def test_a_list_with_nothing_on_it_still_links_to_its_page(admin_client):
    """The way in cannot depend on there being something to clean up: staff open
    the page to check, and an empty card with no link reads as a missing feature."""
    cleanup = admin_client.get("/admin/janitor").text
    assert "Nothing to clean up here." in cleanup
    for section in ("keys", "links", "invites"):
        assert f'href="?section={section}"' in cleanup

    empty = admin_client.get("/admin/janitor?section=links")
    assert empty.status_code == 200
    assert "No links to clean up." in empty.text


def test_deleting_one_expired_link_leaves_the_rest_and_records_it(admin_client):
    from app.models import AdminAction, SharedLink

    db = admin_client.staff_db
    workspace = _workspace(db, "two-links")
    doomed = _shared_link(db, workspace, expired_days_ago=3, email="a@example.com")
    kept = _shared_link(db, workspace, expired_days_ago=5, email="b@example.com")
    db.commit()
    doomed_id, kept_id = doomed.id, kept.id

    done = admin_client.post(
        "/admin/janitor?section=links", data={"delete_one": str(doomed_id)}, follow_redirects=False
    )
    assert "Deleted+1+link" in done.headers["location"]
    assert "section=links" in done.headers["location"]

    db.expire_all()
    assert db.get(SharedLink, doomed_id) is None
    assert db.get(SharedLink, kept_id) is not None
    entry = db.query(AdminAction).filter(AdminAction.row_id == str(doomed_id)).one()
    assert (entry.action, entry.model) == ("delete", "SharedLink")
    assert entry.changes["issued_to"] == "a@example.com"


def test_a_link_still_in_date_cannot_be_deleted_from_the_cleanup_page(admin_client):
    from app.models import SharedLink

    db = admin_client.staff_db
    live = _shared_link(db, _workspace(db, "live-link"), expired_days_ago=-3)
    db.commit()

    done = admin_client.post(
        "/admin/janitor?section=links", data={"delete_one": str(live.id)}, follow_redirects=False
    )
    assert "notice_kind=info" in done.headers["location"]
    db.expire_all()
    assert db.get(SharedLink, live.id) is not None


def test_delete_all_removes_only_invites_to_people_who_signed_up(admin_client):
    from app.models import WorkspaceInvite

    db = admin_client.staff_db
    workspace = _workspace(db, "invites-here")
    answered = [_invite(db, workspace, _owner(db).email) for _ in range(2)]
    pending = _invite(db, workspace, "not-yet@example.com")
    db.commit()
    answered_ids, pending_id = [invite.id for invite in answered], pending.id

    done = admin_client.post(
        "/admin/janitor?section=invites", data={"intent": "delete_all"}, follow_redirects=False
    )
    assert "Deleted+2+invites" in done.headers["location"]
    db.expire_all()
    assert all(db.get(WorkspaceInvite, invite_id) is None for invite_id in answered_ids)
    assert db.get(WorkspaceInvite, pending_id) is not None


def test_deleting_with_nothing_selected_deletes_nothing(admin_client):
    from app.models import WorkspaceInvite

    db = admin_client.staff_db
    invite = _invite(db, _workspace(db, "unselected"), _owner(db).email)
    db.commit()

    done = admin_client.post(
        "/admin/janitor?section=invites", data={"intent": "delete"}, follow_redirects=False
    )
    assert "Select+at+least+one+invite" in done.headers["location"]
    db.expire_all()
    assert db.get(WorkspaceInvite, invite.id) is not None


def test_support_sees_the_leftovers_but_cannot_delete_them(admin_client):
    from app.models import SharedLink

    db = admin_client.staff_db
    link = _shared_link(db, _workspace(db, "support-view"), expired_days_ago=3)
    db.add(
        AdminUser(
            id=uuid.uuid4(),
            email="support@example.com",
            password_hash=get_password_hash("supportpassword"),
            role="support",
            is_active=True,
        )
    )
    db.commit()
    admin_client.post("/admin/login", data={"username": "support@example.com", "password": "supportpassword"})

    page = admin_client.get("/admin/janitor?section=links").text
    assert "but not delete them" in page

    done = admin_client.post(
        "/admin/janitor?section=links", data={"delete_one": str(link.id)}, follow_redirects=False
    )
    assert "notice_kind=error" in done.headers["location"]
    db.expire_all()
    assert db.get(SharedLink, link.id) is not None


def _plan_form(plan_id="team", limits='{"workspaces": 3, "members": 5, "api_keys": 4, "storage_mb": 2048}', **extra):
    form = {
        "id": plan_id,
        "name": "Team",
        "price": "12",
        "sort_order": "5",
        "is_public": "y",
        "limits": limits,
        "features": '["3 workspaces"]',
        "retention_days": "30",
    }
    form.update(extra)
    return form


def test_a_superadmin_can_add_a_plan(admin_client):
    from app.models import Plan

    made = admin_client.post("/admin/plan/create", data=_plan_form(), follow_redirects=False)
    assert made.status_code in (302, 303), made.text

    admin_client.staff_db.expire_all()
    plan = admin_client.staff_db.get(Plan, "team")
    assert plan.limits == {"workspaces": 3, "members": 5, "api_keys": 4, "storage_mb": 2048}
    assert plan.features == ["3 workspaces"]


def test_a_plan_with_a_missing_limit_is_refused(admin_client):
    from app.models import Plan

    refused = admin_client.post(
        "/admin/plan/create",
        data=_plan_form("gappy", limits='{"workspaces": 3, "members": 5}'),
        follow_redirects=False,
    )
    assert refused.status_code not in (302, 303)
    admin_client.staff_db.expire_all()
    assert admin_client.staff_db.get(Plan, "gappy") is None


def test_a_plan_id_must_be_a_slug(admin_client):
    from app.models import Plan

    refused = admin_client.post(
        "/admin/plan/create", data=_plan_form("Not A Slug!"), follow_redirects=False
    )
    assert refused.status_code not in (302, 303)
    admin_client.staff_db.expire_all()
    assert admin_client.staff_db.query(Plan).filter(Plan.name == "Team").count() == 0


def test_editing_a_plan_changes_its_limits_but_never_its_id(admin_client):
    from app.models import Plan

    admin_client.post(
        "/admin/plan/edit/pro",
        data={
            "id": "renamed",
            "name": "Pro",
            "price": "29",
            "sort_order": "1",
            "is_public": "y",
            "limits": '{"workspaces": 15, "members": null, "api_keys": 20, "storage_mb": 10240}',
            "features": "[]",
            "retention_days": "90",
        },
        follow_redirects=False,
    )
    admin_client.staff_db.expire_all()
    assert admin_client.staff_db.get(Plan, "renamed") is None
    assert admin_client.staff_db.get(Plan, "pro").limits["workspaces"] == 15


def test_the_plan_dropdown_marks_hidden_and_archived_plans(admin_client):
    import datetime

    from app.models import Plan, User

    db = admin_client.staff_db
    db.add(Plan(id="internal", name="Internal", is_public=False, limits={}, features=[]))
    db.add(
        Plan(
            id="legacy",
            name="Legacy",
            archived_at=datetime.datetime.now(datetime.timezone.utc),
            limits={},
            features=[],
        )
    )
    user = User(id=uuid.uuid4(), email="picker@example.com", username="picker", password_hash="x")
    db.add(user)
    db.commit()

    page = admin_client.get(f"/admin/user/edit/{user.id}").text
    assert "Internal (hidden)" in page
    assert "Legacy (archived)" in page


def test_an_account_cannot_be_moved_onto_an_archived_plan(admin_client):
    import datetime

    from app.models import Plan, User

    db = admin_client.staff_db
    db.add(
        Plan(
            id="legacy",
            name="Legacy",
            archived_at=datetime.datetime.now(datetime.timezone.utc),
            limits={},
            features=[],
        )
    )
    user = User(id=uuid.uuid4(), email="mover@example.com", username="mover", password_hash="x", tier="free")
    db.add(user)
    db.commit()

    admin_client.post(
        f"/admin/user/edit/{user.id}", data={"is_active": "y", "tier": "legacy"}, follow_redirects=False
    )
    db.expire_all()
    assert db.get(User, user.id).tier == "free"


def test_an_account_already_on_an_archived_plan_can_still_be_suspended(admin_client):
    """Saving for an unrelated reason must not be refused for a plan nobody is
    changing."""
    import datetime

    from app.models import Plan, User

    db = admin_client.staff_db
    db.add(
        Plan(
            id="legacy",
            name="Legacy",
            archived_at=datetime.datetime.now(datetime.timezone.utc),
            limits={},
            features=[],
        )
    )
    user = User(
        id=uuid.uuid4(), email="stayer@example.com", username="stayer", password_hash="x", tier="legacy"
    )
    db.add(user)
    db.commit()

    admin_client.post(f"/admin/user/edit/{user.id}", data={"tier": "legacy"}, follow_redirects=False)
    db.expire_all()
    record = db.get(User, user.id)
    assert record.is_active is False
    assert record.tier == "legacy"


def test_the_usage_page_renders_for_staff(admin_client):
    page = admin_client.get("/admin/usage")
    assert page.status_code == 200
    assert "Server" in page.text
    assert "This month, all workspaces" in page.text


def test_the_usage_page_lists_what_each_workspace_used(admin_client):
    import datetime

    from app.models import User, WorkspaceUsageHour
    from app.routers.usage import month_start

    db = admin_client.staff_db
    owner = User(id=uuid.uuid4(), email="busy@example.com", username="busy", password_hash="x", tier="pro")
    busy = Workspace(id=uuid.uuid4(), name="Busy", slug="busy-one", created_by=owner.id)
    quiet = Workspace(id=uuid.uuid4(), name="Quiet", slug="quiet-one", created_by=owner.id)
    db.add_all([owner, busy, quiet])
    db.commit()
    db.add(
        WorkspaceUsageHour(
            workspace_id=busy.id,
            hour_start=month_start() + datetime.timedelta(days=1, hours=9),
            active_minutes=95,
            writes=1200,
            broadcasts=3400,
            broadcast_bytes=5 * 1024 * 1024,
            peak_bytes=40 * 1024 * 1024,
        )
    )
    db.commit()

    page = admin_client.get("/admin/usage").text
    assert "busy-one" in page and "quiet-one" in page
    assert "1h 35m" in page
    assert "1,200" in page
    assert "40.0 MB" in page
    assert page.index("busy-one") < page.index("quiet-one")


def test_support_can_see_usage_and_a_stranger_cannot(admin_client):
    from app.admin.usage_view import UsageView

    class Req:
        def __init__(self, role):
            self.session = {"admin_role": role}

    assert UsageView._allowed(Req("support"))
    assert not UsageView._allowed(Req("stranger"))


def test_the_server_report_survives_a_machine_that_reports_nothing(monkeypatch, db_session):
    """On a development machine there is no /proc; the page must still render."""
    from app.admin import server_stats, usage_view

    monkeypatch.setattr(
        server_stats,
        "snapshot",
        lambda: {"cpus": 2, "load": None, "memory": None, "disk": None, "uptime_seconds": None},
    )
    report = usage_view.server_report(db_session)
    assert report["memory"] is None
    assert report["disk"] is None
    assert report["load_share"] is None


def test_a_full_disk_is_reported_as_a_share():
    from app.admin.usage_view import _share, format_bytes, format_minutes

    assert _share(69, 100) == 69
    assert _share(1, 0) is None
    assert format_bytes(40 * 1024 * 1024) == "40.0 MB"
    assert format_minutes(95) == "1h 35m"


def _nav(page_html):
    import re

    return {
        text.strip(): (href, "is-active" in cls)
        for cls, href, text in re.findall(
            r'<a class="ap-nav-row([^"]*)" href="([^"]+)">.*?<span[^>]*>([^<]+)</span>',
            page_html,
            re.S,
        )
    }


def test_each_custom_page_has_its_own_sidebar_link(admin_client):
    """Two custom views with the same exposed method name share a route name,
    so one link opens the other page. It happened with Usage and Cleanup."""
    nav = _nav(admin_client.get("/admin/janitor").text)
    assert nav["Usage"][0].endswith("/admin/usage")
    assert nav["Cleanup"][0].endswith("/admin/janitor")


def test_only_the_page_you_are_on_is_selected(admin_client):
    for path, selected in (("/admin/janitor", "Cleanup"), ("/admin/usage", "Usage")):
        nav = _nav(admin_client.get(path).text)
        active = [name for name, (_href, on) in nav.items() if on]
        assert active == [selected], (path, active)


KEYS_PAGE = "/admin/janitor?section=keys"


def _sent_to(monkeypatch, fail_for=()):
    from app.admin import panel as admin_panel

    sent = []

    def fake_send(to, subject, body):
        if to in fail_for:
            return False
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(admin_panel.outbound, "configured", lambda: True)
    monkeypatch.setattr(admin_panel.outbound, "send", fake_send)
    return sent


def test_the_keys_page_says_where_each_key_stands(admin_client):
    db = admin_client.staff_db
    owner = _owner(db)
    _key(db, owner, "never-touched")
    db.commit()

    page = admin_client.get(KEYS_PAGE).text
    assert "never-touched" in page
    assert owner.email in page
    assert "never used" in page


def test_cleanup_stays_selected_on_the_keys_page(admin_client):
    nav = _nav(admin_client.get(KEYS_PAGE).text)
    assert [name for name, (_href, on) in nav.items() if on] == ["Cleanup"]


def test_a_row_button_revokes_only_that_key(admin_client):
    from app.models import APIKey

    db = admin_client.staff_db
    owner = _owner(db)
    target, other = _key(db, owner, "target"), _key(db, owner, "other")
    db.commit()

    done = admin_client.post(
        KEYS_PAGE,
        data={"revoke_one": str(target.id), "key_ids": [str(target.id), str(other.id)]},
        follow_redirects=False,
    )
    assert "section=keys" in done.headers["location"]
    db.expire_all()
    assert db.get(APIKey, target.id).is_active is False
    assert db.get(APIKey, other.id).is_active is True


def test_revoke_with_nothing_selected_revokes_nothing(admin_client):
    """The bulk button says 'selected'; with none selected it must not fall
    through to revoking everything."""
    from app.models import APIKey

    db = admin_client.staff_db
    keys = [_key(db, _owner(db), f"keep-{n}") for n in range(2)]
    db.commit()

    done = admin_client.post(KEYS_PAGE, data={"intent": "revoke"}, follow_redirects=False)
    assert "Select+at+least+one+key" in done.headers["location"]
    db.expire_all()
    assert all(db.get(APIKey, key.id).is_active for key in keys)


def test_revoking_the_selected_keys_leaves_the_rest(admin_client):
    from app.models import APIKey

    db = admin_client.staff_db
    owner = _owner(db)
    a, b, c = (_key(db, owner, name) for name in ("a", "b", "c"))
    db.commit()

    admin_client.post(
        KEYS_PAGE, data={"intent": "revoke", "key_ids": [str(a.id), str(b.id)]}, follow_redirects=False
    )
    db.expire_all()
    assert [db.get(APIKey, k.id).is_active for k in (a, b, c)] == [False, False, True]


def test_notifying_is_refused_while_email_is_not_set_up(admin_client, monkeypatch):
    from app.admin import panel as admin_panel
    from app.models import APIKey

    monkeypatch.setattr(admin_panel.outbound, "configured", lambda: False)
    db = admin_client.staff_db
    key = _key(db, _owner(db), "quiet")
    db.commit()

    done = admin_client.post(KEYS_PAGE, data={"notify_one": str(key.id)}, follow_redirects=False)
    assert "Email+is+not+set+up" in done.headers["location"]
    db.expire_all()
    assert db.get(APIKey, key.id).owner_notified_at is None


def test_each_owner_gets_one_email_listing_all_their_keys(admin_client, monkeypatch):
    import datetime

    from app.models import APIKey

    sent = _sent_to(monkeypatch)
    db = admin_client.staff_db
    owner = _owner(db)
    first, second = _key(db, owner, "first-key"), _key(db, owner, "second-key")
    db.commit()

    admin_client.post(
        KEYS_PAGE,
        data={"intent": "notify", "key_ids": [str(first.id), str(second.id)]},
        follow_redirects=False,
    )
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == owner.email
    assert "first-key" in body and "second-key" in body

    db.expire_all()
    marked = db.get(APIKey, first.id)
    deadline = marked.revoke_after.replace(tzinfo=marked.revoke_after.tzinfo or datetime.timezone.utc)
    days = (deadline - datetime.datetime.now(datetime.timezone.utc)).days
    assert marked.owner_notified_at is not None
    assert 29 <= days <= 30


def test_a_key_is_only_marked_once_its_owners_email_went_out(admin_client, monkeypatch):
    """Otherwise a failed send could end with a key revoked without warning."""
    from app.models import APIKey

    db = admin_client.staff_db
    reachable, unreachable = _owner(db), _owner(db)
    good, bad = _key(db, reachable, "good"), _key(db, unreachable, "bad")
    db.commit()
    _sent_to(monkeypatch, fail_for=(unreachable.email,))

    done = admin_client.post(
        KEYS_PAGE, data={"intent": "notify", "key_ids": [str(good.id), str(bad.id)]}, follow_redirects=False
    )
    assert "Could+not+email" in done.headers["location"]
    db.expire_all()
    assert db.get(APIKey, good.id).owner_notified_at is not None
    assert db.get(APIKey, bad.id).owner_notified_at is None


def test_only_keys_past_their_notice_are_revoked_as_due(admin_client):
    import datetime

    from app.models import APIKey

    now = datetime.datetime.now(datetime.timezone.utc)
    db = admin_client.staff_db
    owner = _owner(db)
    overdue, waiting = _key(db, owner, "overdue"), _key(db, owner, "waiting")
    day = datetime.timedelta(days=1)
    overdue.owner_notified_at, overdue.revoke_after = now - 31 * day, now - day
    waiting.owner_notified_at, waiting.revoke_after = now - 5 * day, now + 25 * day
    db.commit()

    assert "due for revocation" in admin_client.get(KEYS_PAGE).text
    admin_client.post(KEYS_PAGE, data={"intent": "revoke_due"}, follow_redirects=False)
    db.expire_all()
    assert db.get(APIKey, overdue.id).is_active is False
    assert db.get(APIKey, waiting.id).is_active is True


def test_using_a_key_after_its_notice_cancels_the_notice():
    import datetime
    import types

    from app.admin import janitor

    now = datetime.datetime.now(datetime.timezone.utc)
    key = types.SimpleNamespace(
        owner_notified_at=now - datetime.timedelta(days=10),
        last_used_at=now - datetime.timedelta(days=2),
        revoke_after=now - datetime.timedelta(days=1),
    )
    assert janitor.notice_is_current(key) is False
    assert janitor.is_due(key, now) is False
