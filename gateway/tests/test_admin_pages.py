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
