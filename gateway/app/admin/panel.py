# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""The staff admin panel, mounted on its own route with its own login."""

import logging
import os
import time

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.admin import activity, roles
from app.database import SessionLocal, engine
from app.models import (
    AdminUser,
    APIKey,
    Membership,
    SharedLink,
    User,
    Workspace,
    WorkspaceInvite,
    utcnow,
)
from app.security import verify_password

SESSION_KEY = "admin_user"
ROLE_KEY = "admin_role"


class StaffAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        email = (form.get("username") or "").strip().lower()
        password = form.get("password") or ""
        db = SessionLocal()
        try:
            admin = db.query(AdminUser).filter(AdminUser.email == email).first()
            if admin is None or not admin.is_active:
                logging.info("admin login refused for %s", email)
                return False
            if not verify_password(password, admin.password_hash):
                logging.info("admin login refused for %s", email)
                return False
            admin.last_login_at = utcnow()
            db.commit()
            request.session.update({SESSION_KEY: str(admin.id), ROLE_KEY: admin.role})
            logging.info("admin login for %s as %s", email, admin.role)
            return True
        finally:
            db.close()

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request):
        admin_id = request.session.get(SESSION_KEY)
        if not admin_id:
            return RedirectResponse(request.url_for("admin:login"), status_code=302)
        db = SessionLocal()
        try:
            admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
            if admin is None or not admin.is_active:
                request.session.clear()
                return RedirectResponse(request.url_for("admin:login"), status_code=302)
            request.session[ROLE_KEY] = admin.role
        finally:
            db.close()
        return True


class RoleScopedView(ModelView):
    """A view that hides itself from roles not allowed to see the model."""

    can_create = False
    can_edit = False
    can_delete = False
    can_export = False
    page_size = 50

    def is_visible(self, request: Request) -> bool:
        return roles.can_see(request.session.get(ROLE_KEY), self.model.__name__)

    def is_accessible(self, request: Request) -> bool:
        return roles.can_see(request.session.get(ROLE_KEY), self.model.__name__)


class UserAdmin(RoleScopedView, model=User):
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"
    column_list = [
        User.email,
        User.username,
        User.tier,
        User.is_active,
        User.created_at,
    ]
    column_searchable_list = [User.email, User.username]
    column_sortable_list = [User.email, User.tier, User.created_at]
    column_default_sort = (User.created_at, True)
    column_details_exclude_list = [User.password_hash]


def _workspace_activity(model, name):
    """Render one workspace's live socket counts for the list view.

    Reads the fan-out's answer rather than the database: "active" here means
    someone is connected to the workspace right now, which only the visdom
    instances know.
    """
    entry = activity.cached_activity().get(str(model.id))
    if entry is None:
        return "idle"
    viewers, writers = entry.get("viewers", 0), entry.get("writers", 0)
    if not viewers and not writers:
        return "idle"
    parts = []
    if viewers:
        parts.append(f"{viewers} reading")
    if writers:
        parts.append(f"{writers} writing")
    return ", ".join(parts)


def _workspace_last_active(model, name):
    """Render how long ago the workspace was last written to."""
    entry = activity.cached_activity().get(str(model.id))
    last = entry.get("last_active_at") if entry else None
    if not last:
        return "unknown"
    seconds = max(0, int(time.time() - last))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _workspace_created(model, name):
    """Workspaces created before the created_at column existed have no true age."""
    return model.created_at.strftime("%Y-%m-%d %H:%M") if model.created_at else "unknown"


class WorkspaceAdmin(RoleScopedView, model=Workspace):
    name = "Workspace"
    name_plural = "Workspaces"
    icon = "fa-solid fa-folder"
    column_list = [
        Workspace.name,
        Workspace.slug,
        Workspace.created_by,
        Workspace.created_at,
        "activity",
        "last_active",
    ]
    column_labels = {
        Workspace.created_at: "Created",
        "activity": "Active now",
        "last_active": "Last write",
    }
    column_formatters = {
        Workspace.created_at: _workspace_created,
        "activity": _workspace_activity,
        "last_active": _workspace_last_active,
    }
    column_searchable_list = [Workspace.name, Workspace.slug]
    column_sortable_list = [Workspace.name, Workspace.slug, Workspace.created_at]
    column_default_sort = (Workspace.created_at, True)


class MembershipAdmin(RoleScopedView, model=Membership):
    name = "Membership"
    name_plural = "Memberships"
    icon = "fa-solid fa-users"
    column_list = [
        Membership.workspace_id,
        Membership.user_id,
        Membership.role,
        Membership.status,
    ]
    column_sortable_list = [Membership.role, Membership.status]


class APIKeyAdmin(RoleScopedView, model=APIKey):
    name = "API key"
    name_plural = "API keys"
    icon = "fa-solid fa-key"
    column_list = [
        APIKey.name,
        APIKey.prefix,
        APIKey.scope,
        APIKey.is_active,
        APIKey.user_id,
        APIKey.created_at,
        APIKey.last_used_at,
    ]
    column_details_exclude_list = [APIKey.hashed_key]
    column_sortable_list = [APIKey.created_at, APIKey.last_used_at]


class WorkspaceInviteAdmin(RoleScopedView, model=WorkspaceInvite):
    name = "Invite"
    name_plural = "Invites"
    icon = "fa-solid fa-envelope"
    column_list = [
        WorkspaceInvite.email,
        WorkspaceInvite.workspace_id,
        WorkspaceInvite.role,
        WorkspaceInvite.created_at,
    ]
    column_searchable_list = [WorkspaceInvite.email]


class SharedLinkAdmin(RoleScopedView, model=SharedLink):
    name = "Shared link"
    name_plural = "Shared links"
    icon = "fa-solid fa-link"
    column_list = [
        SharedLink.workspace_id,
        SharedLink.role,
        SharedLink.invite_email,
        SharedLink.expires_at,
    ]
    column_details_exclude_list = [SharedLink.password_hash]


class AdminUserAdmin(RoleScopedView, model=AdminUser):
    name = "Staff account"
    name_plural = "Staff accounts"
    icon = "fa-solid fa-user-shield"
    column_list = [
        AdminUser.email,
        AdminUser.role,
        AdminUser.is_active,
        AdminUser.created_at,
        AdminUser.last_login_at,
    ]
    column_details_exclude_list = [AdminUser.password_hash]


VIEWS = (
    UserAdmin,
    WorkspaceAdmin,
    MembershipAdmin,
    APIKeyAdmin,
    WorkspaceInviteAdmin,
    SharedLinkAdmin,
    AdminUserAdmin,
)


_CARDS = (
    ("Users", User, "user"),
    ("Workspaces", Workspace, "workspace"),
    ("Memberships", Membership, "membership"),
    ("API keys", APIKey, "api-key"),
    ("Shared links", SharedLink, "shared-link"),
    ("Staff", AdminUser, "admin-user"),
)


def overview_cards(request):
    """Counts for the models the signed-in role is allowed to see."""
    role = request.session.get(ROLE_KEY)
    base = str(request.base_url).rstrip("/")
    cards = []
    db = SessionLocal()
    try:
        for label, model, slug in _CARDS:
            if not roles.can_see(role, model.__name__):
                continue
            cards.append({
                "label": label,
                "count": db.query(model).count(),
                "url": "%s/admin/%s/list" % (base, slug),
            })
    except Exception as exc:
        logging.warning("overview counts failed: %s", exc)
    finally:
        db.close()
    return cards


def overview_recent(request, limit=5):
    """The newest accounts, for roles allowed to see users."""
    if not roles.can_see(request.session.get(ROLE_KEY), "User"):
        return []
    db = SessionLocal()
    try:
        rows = db.query(User).order_by(User.created_at.desc()).limit(limit).all()
        return [
            {
                "email": u.email,
                "tier": u.tier,
                "joined": u.created_at.strftime("%Y-%m-%d") if u.created_at else "",
            }
            for u in rows
        ]
    except Exception as exc:
        logging.warning("overview recent failed: %s", exc)
        return []
    finally:
        db.close()


def mount_admin(app, secret_key, base_url="/admin"):
    """Attach the admin panel to a FastAPI app."""
    admin = Admin(
        app=app,
        engine=engine,
        base_url=base_url,
        title="Visdom Dev staff",
        templates_dir=os.path.join(os.path.dirname(__file__), "templates"),
        authentication_backend=StaffAuth(secret_key=secret_key),
    )
    admin.templates.env.globals["overview_cards"] = overview_cards
    admin.templates.env.globals["overview_recent"] = overview_recent
    for view in VIEWS:
        admin.add_view(view)
    return admin
