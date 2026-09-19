# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""The staff admin panel, mounted on its own route with its own login."""

import asyncio
import base64
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import wtforms
from sqladmin import Admin, BaseView, ModelView, expose
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy.orm import joinedload
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app import billing
from app import email as outbound
from app.admin import activity, janitor, roles
from app.admin.audit import StaffAuditBackend
from app.config import settings
from app.database import SessionLocal, engine
from app.models import (
    AdminAction,
    AdminUser,
    APIKey,
    APIKeyWorkspace,
    Membership,
    Plan,
    SharedLink,
    User,
    Workspace,
    WorkspaceInvite,
    utcnow,
)
from app.security import get_password_hash, verify_password

SESSION_KEY = "admin_user"
ROLE_KEY = "admin_role"
EMAIL_KEY = "admin_email"

# Environment names that should make the panel visibly alarming to be looking at.
DANGEROUS_ENVIRONMENTS = ("prod", "production", "live")


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
            request.session.update(
                {SESSION_KEY: str(admin.id), ROLE_KEY: admin.role, EMAIL_KEY: admin.email}
            )
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
        try:
            # The session carries the id as text, and the column is a UUID.
            # Converting here rather than leaving it to the driver also turns a
            # tampered cookie into a signed-out visitor instead of an error.
            admin_key = uuid.UUID(str(admin_id))
        except ValueError:
            request.session.clear()
            return RedirectResponse(request.url_for("admin:login"), status_code=302)
        db = SessionLocal()
        try:
            admin = db.query(AdminUser).filter(AdminUser.id == admin_key).first()
            if admin is None or not admin.is_active:
                request.session.clear()
                return RedirectResponse(request.url_for("admin:login"), status_code=302)
            request.session[ROLE_KEY] = admin.role
            request.session[EMAIL_KEY] = admin.email
        finally:
            db.close()
        return True


class RoleScopedView(ModelView):
    """A view that hides itself from roles not allowed to see the model."""

    details_template = "sqladmin/record_details.html"
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False
    page_size = 50

    def is_visible(self, request: Request) -> bool:
        return roles.can_see(request.session.get(ROLE_KEY), self.model.__name__)

    def is_accessible(self, request: Request) -> bool:
        return roles.can_see(request.session.get(ROLE_KEY), self.model.__name__)


class ChangeableView(RoleScopedView):
    """A view whose rows a sufficiently privileged role may also change.

    Nothing here can be created or deleted. A staff member stopping an account
    or a key is undoing something reversible, and a deleted row takes its own
    audit trail with it.
    """

    can_edit = True

    async def check_can_edit(self, request: Request, model) -> bool:
        """The real gate. `can_edit` is a class attribute, so it cannot vary by
        role; sqladmin calls this per request, which is what makes the hidden
        button and the typed URL agree."""
        return roles.can_change(request.session.get(ROLE_KEY), self.model.__name__)

    async def on_model_change(
        self, data: dict, model, is_created: bool, request: Request
    ) -> None:
        """Drop any field this role is not allowed to set.

        The form is the same for every role that can edit at all, because
        sqladmin builds it without knowing the request. So the field level rule
        is applied to what was submitted instead, which also covers a request
        that never came from the form.
        """
        allowed = roles.editable_fields(
            request.session.get(ROLE_KEY), self.model.__name__
        )
        refused = [
            key
            for key, value in data.items()
            if key not in allowed and value != getattr(model, key, None)
        ]
        if refused:
            raise HTTPException(
                status_code=403,
                detail=f"Your role cannot change: {', '.join(sorted(refused))}.",
            )
        for key in list(data):
            if key not in allowed:
                data.pop(key)


def _to_the_minute(field, empty=""):
    """A list column showing a moment to the minute.

    Seconds, microseconds and the offset are noise in a table someone is
    scanning, and on a narrow screen two full timestamps are enough to push the
    last columns out of the card.
    """

    def render(model, _attr):
        value = getattr(model, field, None)
        return value.strftime("%Y-%m-%d %H:%M") if value else empty

    return render


def _tier_choices():
    """Every plan, marked when it is hidden or archived.

    Archived plans are offered so an account already on one still shows its
    plan; moving an account onto one is refused when the form is saved.
    """
    db = SessionLocal()
    try:
        plans = db.query(Plan).order_by(Plan.sort_order, Plan.id).all()
    finally:
        db.close()

    def label(plan):
        if plan.archived_at is not None:
            return f"{plan.name} (archived)"
        if not plan.is_public:
            return f"{plan.name} (hidden)"
        return plan.name

    return [(plan.id, label(plan)) for plan in plans]


class UserAdmin(ChangeableView, model=User):
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"
    category = "People"
    category_icon = "fa-solid fa-users"
    column_list = [
        User.email,
        User.username,
        User.tier,
        User.is_active,
        User.created_at,
        User.last_login_at,
    ]
    column_searchable_list = [User.email, User.username]
    column_sortable_list = [
        User.email,
        User.tier,
        User.created_at,
        User.last_login_at,
    ]
    column_default_sort = (User.created_at, True)
    column_details_exclude_list = [User.password_hash]
    column_formatters = {
        User.created_at: _to_the_minute("created_at"),
        User.last_login_at: _to_the_minute("last_login_at", "never"),
    }
    form_columns = [User.is_active, User.tier]
    form_include_pk = True
    form_overrides = {"tier": wtforms.SelectField}
    form_args = {"tier": {"label": "Plan", "choices": lambda: _tier_choices()}}

    async def on_model_change(
        self, data: dict, model, is_created: bool, request: Request
    ) -> None:
        """Refuse moving an account onto a plan staff may not assign.

        Only a change is checked. An account already on an archived plan keeps
        it, so saving that account for an unrelated reason, such as suspending
        it, must not be refused for a plan nobody is changing.
        """
        await super().on_model_change(data, model, is_created, request)
        tier = data.get("tier")
        if tier is None or tier == model.tier:
            return
        db = SessionLocal()
        try:
            allowed = billing.assignable(db, tier)
        finally:
            db.close()
        if not allowed:
            raise HTTPException(
                status_code=400,
                detail=f"{tier} is archived or does not exist, so no account can be put on it.",
            )


def _email_of(user):
    return user.email if user is not None else "unknown"


def _slug_of(workspace):
    return workspace.slug if workspace is not None else "unknown"


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
    snapshot = activity.cached_snapshot()
    entry = snapshot["workspaces"].get(str(model.id))
    last = entry.get("last_active_at") if entry else None
    if not last:
        return "never" if snapshot["answered"] else "unknown"
    seconds = max(0, int(time.time() - last))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _member_lines(model, name):
    """Members and their roles, so the page answers who is actually in here.

    These read the database directly rather than walking relationships. sqladmin
    closes its session before the formatters run, so a lazy load here raises
    DetachedInstanceError, and eager loading through the view would still leave
    the second hop (a membership's user) detached.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(Membership)
            .options(joinedload(Membership.user))
            .filter(Membership.workspace_id == model.id)
            .all()
        )
        if not rows:
            return "no members"
        rows.sort(key=lambda m: (m.role, _email_of(m.user)))
        return ", ".join(
            f"{_email_of(m.user)} ({m.role}"
            f"{'' if m.status == 'active' else ', ' + m.status})"
            for m in rows
        )
    finally:
        db.close()


def _invite_lines(model, name):
    db = SessionLocal()
    try:
        rows = (
            db.query(WorkspaceInvite)
            .filter(WorkspaceInvite.workspace_id == model.id)
            .all()
        )
        return ", ".join(f"{i.email} ({i.role})" for i in rows) or "none"
    finally:
        db.close()


def _key_lines(model, name):
    """Only keys bound to this workspace.

    An org scoped key works everywhere, so listing those would name every key
    its owner holds and say nothing about this workspace in particular.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(APIKey)
            .join(APIKeyWorkspace, APIKeyWorkspace.api_key_id == APIKey.id)
            .options(joinedload(APIKey.owner))
            .filter(APIKeyWorkspace.workspace_id == model.id)
            .all()
        )
        return ", ".join(f"{k.name} ({_email_of(k.owner)})" for k in rows) or "none"
    finally:
        db.close()


def _link_lines(model, name):
    db = SessionLocal()
    try:
        rows = db.query(SharedLink).filter(SharedLink.workspace_id == model.id).all()
        return (
            ", ".join(
                f"{link.role}"
                f"{' for ' + link.invite_email if link.invite_email else ''}"
                for link in rows
            )
            or "none"
        )
    finally:
        db.close()


def _workspace_size(model, name):
    """Render how much disk a workspace is using.

    Worth showing because nothing limits it. Image plots are base64 and orders
    of magnitude heavier than line plots, so one account can fill the volume
    without doing anything obviously wrong, and this is the only place that
    would show it before the disk filled.
    """
    snapshot = activity.cached_snapshot()
    entry = snapshot["workspaces"].get(str(model.id))
    size = entry.get("bytes") if entry else None
    if size is None:
        return "nothing yet" if snapshot["answered"] else "unknown"
    return _human_bytes(size)


def _human_bytes(size):
    """A byte count in the largest unit that leaves a number worth reading."""
    if size < 1024:
        return f"{size} B"
    for unit in ("KB", "MB", "GB"):
        size /= 1024.0
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"


def _workspace_traffic(model, name):
    """How much work this workspace has caused since the instances came up.

    Counted inside visdom against the workspace that caused it, because one
    process serves many and its own CPU cannot be divided between them
    afterwards. Writes are environments saved; pushes are messages sent to
    viewers, counted once per viewer reached.

    Said to be since the instances started because that is what it is. The
    counters live in memory and begin again at zero on restart, and a number
    that looks like a lifetime total but silently is not would be worse than no
    number.
    """
    entry = activity.cached_activity().get(str(model.id)) or {}
    writes = entry.get("writes")
    pushes = entry.get("broadcasts")
    if writes is None and pushes is None:
        return "not reported"
    sent = entry.get("broadcast_bytes") or 0
    return (
        f"{writes or 0} writes, {pushes or 0} pushes"
        f" ({_human_bytes(sent)}) since the instances started"
    )


def _workspace_created(model, name):
    """Workspaces created before the created_at column existed have no true age.

    The column was added nullable and never backfilled, because there was no
    honest source to backfill it from. Saying so beats inventing a date.
    """
    if model.created_at is None:
        return "before this was recorded"
    return model.created_at.strftime("%Y-%m-%d %H:%M")


def _days_since(moment):
    """Whole days between then and now, or None when there is no timestamp."""
    if moment is None:
        return None
    now = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, (now - moment).days)


# What the socket says on its way out. Worth distinguishing, because one of
# these is something a member can undo by asking and the other is not.
_SUSPENDED_REASON = "this workspace has been suspended, contact an administrator"
_TRASHED_REASON = "this workspace is in the trash, ask an administrator to restore it"


def _workspace_standing(model, name):
    """Whether the workspace is usable, and why not when it is not.

    Trash is reported first. A trashed workspace is refused whatever its
    suspension flag says, so leading with the suspension would name a reason
    that is not the operative one.
    """
    days = _days_since(model.trashed_at)
    if days is not None:
        overdue = " (due for purge)" if days >= janitor.TRASH_DAYS else ""
        return f"in trash {days}d{overdue}"
    return "active" if model.is_active else "suspended"


class WorkspaceAdmin(ChangeableView, model=Workspace):
    name = "Workspace"
    name_plural = "Workspaces"
    icon = "fa-solid fa-folder"
    category = "Workspaces"
    category_icon = "fa-solid fa-folder"
    column_list = [
        Workspace.name,
        Workspace.slug,
        Workspace.creator,
        Workspace.created_at,
        "standing",
        "activity",
        "last_active",
        "size",
    ]
    column_labels = {
        Workspace.creator: "Created by",
        Workspace.created_at: "Created",
        "standing": "Standing",
        "activity": "Active now",
        "last_active": "Last write",
        "size": "On disk",
    }
    column_formatters = {
        Workspace.creator: lambda m, a: _email_of(m.creator),
        Workspace.created_at: _workspace_created,
        "standing": _workspace_standing,
        "activity": _workspace_activity,
        "last_active": _workspace_last_active,
        "size": _workspace_size,
    }
    form_columns = [Workspace.is_active, Workspace.trashed_at]

    async def after_model_change(
        self, data: dict, model, is_created: bool, request: Request
    ) -> None:
        """Close the workspace's open sockets once it is no longer usable.

        After the change rather than during it, so a save that fails does not
        disconnect anybody. The refusal at resolve time already stops anybody
        new; without this a tab open at the moment of suspension keeps watching
        and a training run keeps writing, because a live socket never resolves
        again.
        """
        if model.trashed_at is not None:
            activity.evict_workspace(model.slug, _TRASHED_REASON)
        elif not model.is_active:
            activity.evict_workspace(model.slug, _SUSPENDED_REASON)
    column_searchable_list = [Workspace.name, Workspace.slug]
    column_sortable_list = [Workspace.name, Workspace.slug, Workspace.created_at]
    column_default_sort = (Workspace.created_at, True)
    column_details_list = [
        Workspace.name,
        Workspace.slug,
        Workspace.creator,
        Workspace.created_at,
        "standing",
        "activity",
        "last_active",
        "traffic",
        "size",
        "members",
        "invites",
        "keys",
        "links",
    ]
    column_labels_detail = {
        Workspace.creator: "Created by",
        Workspace.created_at: "Created",
        "standing": "Standing",
        "activity": "Active now",
        "last_active": "Last write",
        "traffic": "Work done",
        "size": "On disk",
        "members": "Members",
        "invites": "Pending email invites",
        "keys": "Keys bound to this workspace",
        "links": "Shared links",
    }
    column_formatters_detail = {
        Workspace.creator: lambda m, a: _email_of(m.creator),
        Workspace.created_at: _workspace_created,
        "standing": _workspace_standing,
        "activity": _workspace_activity,
        "last_active": _workspace_last_active,
        "traffic": _workspace_traffic,
        "size": _workspace_size,
        "members": _member_lines,
        "invites": _invite_lines,
        "keys": _key_lines,
        "links": _link_lines,
    }


def _other_active_admins(db, membership):
    """Active admins of the same workspace other than this member.

    Locked while it is read, because the answer is being used to decide whether
    this member may stop being an admin. Two staff demoting the last two admins
    at once would otherwise each see the other and both be allowed through,
    leaving a workspace nobody can administer.
    """
    return (
        db.query(Membership)
        .filter(
            Membership.workspace_id == membership.workspace_id,
            Membership.role == "admin",
            Membership.status == "active",
            Membership.user_id != membership.user_id,
        )
        .with_for_update()
        .all()
    )


class MembershipAdmin(ChangeableView, model=Membership):
    """Who belongs to a workspace, and what they may do there.

    The only place staff can change someone's access without also changing
    their account. Read as: the workspace keeps working afterwards, which is
    what the two guards below are for.
    """

    name = "Membership"
    name_plural = "Memberships"
    icon = "fa-solid fa-users"
    category = "Workspaces"
    category_icon = "fa-solid fa-folder"
    form_columns = [Membership.role]
    column_list = [
        Membership.workspace,
        Membership.user,
        Membership.role,
        Membership.status,
    ]
    column_labels = {Membership.workspace: "Workspace", Membership.user: "Member"}
    column_formatters = {
        Membership.workspace: lambda m, a: _slug_of(m.workspace),
        Membership.user: lambda m, a: _email_of(m.user),
    }
    column_sortable_list = [Membership.role, Membership.status]

    @property
    def can_delete(self) -> bool:
        """Advertised for everyone; refused per request by ``check_can_delete``.

        sqladmin reads this off the class without a request in hand, so it
        cannot vary by role here. The gate is the per-request check below, which
        is what makes the hidden button and the typed URL agree.
        """
        return True

    async def check_can_delete(self, request: Request, model) -> bool:
        return roles.can_remove(request.session.get(ROLE_KEY), "Membership")

    async def on_model_change(
        self, data: dict, model, is_created: bool, request: Request
    ) -> None:
        """Apply the field rules, then refuse a change that orphans a workspace.

        The owner's role is fixed, matching what the API already refuses. That
        rule is what guarantees a workspace always has an admin, so the console
        cannot be the one place it does not hold.
        """
        await super().on_model_change(data, model, is_created, request)
        new_role = data.get("role")
        if new_role is None or new_role == model.role or model.role != "admin":
            return

        db = SessionLocal()
        try:
            workspace = (
                db.query(Workspace).filter(Workspace.id == model.workspace_id).first()
            )
            if workspace is not None and workspace.created_by == model.user_id:
                raise HTTPException(
                    status_code=403,
                    detail="The workspace owner is always an admin.",
                )
            if not _other_active_admins(db, model):
                raise HTTPException(
                    status_code=400,
                    detail="This is the workspace's last admin.",
                )
        finally:
            db.close()

    async def on_model_delete(self, model, request: Request) -> None:
        """Refuse a removal that would leave a workspace with no admin.

        The same rule the API applies when a member removes another. A console
        that could do what the product refuses would be a way around the rule
        rather than a way to administer it.
        """
        if model.role != "admin" or model.status != "active":
            return
        db = SessionLocal()
        try:
            if not _other_active_admins(db, model):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot remove the last admin of a workspace.",
                )
        finally:
            db.close()


class APIKeyAdmin(ChangeableView, model=APIKey):
    name = "API key"
    name_plural = "API keys"
    icon = "fa-solid fa-key"
    category = "Access"
    category_icon = "fa-solid fa-key"
    column_list = [
        APIKey.name,
        APIKey.prefix,
        APIKey.scope,
        APIKey.is_active,
        APIKey.owner,
        APIKey.created_at,
        APIKey.last_used_at,
    ]
    column_labels = {APIKey.owner: "Owner", APIKey.last_used_at: "Last used"}
    column_formatters = {
        APIKey.owner: lambda m, a: _email_of(m.owner),
        APIKey.created_at: _to_the_minute("created_at"),
        APIKey.last_used_at: _to_the_minute("last_used_at", "never"),
    }
    column_details_exclude_list = [APIKey.hashed_key]
    column_sortable_list = [APIKey.created_at, APIKey.last_used_at]
    form_columns = [APIKey.is_active]


class WorkspaceInviteAdmin(RoleScopedView, model=WorkspaceInvite):
    name = "Invite"
    name_plural = "Invites"
    icon = "fa-solid fa-envelope"
    category = "Access"
    category_icon = "fa-solid fa-key"
    column_list = [
        WorkspaceInvite.email,
        WorkspaceInvite.workspace,
        WorkspaceInvite.role,
        WorkspaceInvite.created_at,
    ]
    column_labels = {WorkspaceInvite.workspace: "Workspace"}
    column_formatters = {
        WorkspaceInvite.workspace: lambda m, a: _slug_of(m.workspace),
        WorkspaceInvite.created_at: _to_the_minute("created_at"),
    }
    column_searchable_list = [WorkspaceInvite.email]


class SharedLinkAdmin(RoleScopedView, model=SharedLink):
    name = "Shared link"
    name_plural = "Shared links"
    icon = "fa-solid fa-link"
    category = "Access"
    category_icon = "fa-solid fa-key"
    column_list = [
        SharedLink.workspace,
        SharedLink.role,
        SharedLink.invite_email,
        SharedLink.expires_at,
    ]
    column_labels = {SharedLink.workspace: "Workspace", SharedLink.invite_email: "Issued to"}
    column_formatters = {
        SharedLink.workspace: lambda m, a: _slug_of(m.workspace),
        SharedLink.expires_at: _to_the_minute("expires_at", "never"),
    }
    column_details_exclude_list = [SharedLink.password_hash]


MIN_STAFF_PASSWORD = 12


def _other_active_superadmins(db, admin):
    """Superadmins other than this one who can still sign in.

    Locked while it is read, for the same reason the workspace admin check is:
    two staff stopping the last two superadmins at once would each see the
    other and both be let through, leaving a console nobody can open.
    """
    return (
        db.query(AdminUser)
        .filter(
            AdminUser.role == roles.SUPERADMIN,
            AdminUser.is_active.is_(True),
            AdminUser.id != admin.id,
        )
        .with_for_update()
        .all()
    )


def _plan_standing(model, _attr):
    if model.archived_at is not None:
        return "archived"
    return "public" if model.is_public else "hidden"


def _plan_limits(model, _attr):
    limits = model.limits or {}

    def one(key, singular, plural):
        value = limits.get(key)
        if value is None:
            return f"\u221e {plural}"
        return f"{value} {singular if value == 1 else plural}"

    return ", ".join(
        one(key, singular, plural)
        for key, singular, plural in (
            ("workspaces", "workspace", "workspaces"),
            ("members", "member", "members"),
            ("api_keys", "API key", "API keys"),
        )
    )


class PlanAdmin(RoleScopedView, model=Plan):
    """Subscription tiers, edited here rather than in code.

    Superadmin only: a change here is a change to what every account on that
    tier gets, the moment it is saved. A plan is never deleted but archived,
    which stops anyone new being put on it while leaving accounts already on it
    exactly as they were. Limits are checked when saved rather than trusted, so
    a missing or misspelt marker is refused instead of being read as unlimited.
    """

    name = "Plan"
    name_plural = "Plans"
    icon = "fa-solid fa-layer-group"
    category = "Billing"
    category_icon = "fa-solid fa-credit-card"
    can_create = True
    can_edit = True
    form_include_pk = True
    column_list = [
        Plan.id,
        Plan.name,
        Plan.price,
        "standing",
        Plan.limits,
        Plan.retention_days,
    ]
    column_labels = {"standing": "Standing", "retention_days": "Retention (days)"}
    column_formatters = {"standing": _plan_standing, Plan.limits: _plan_limits}
    column_default_sort = (Plan.sort_order, False)
    form_columns = [
        Plan.id,
        Plan.name,
        Plan.price,
        Plan.sort_order,
        Plan.is_public,
        Plan.archived_at,
        Plan.limits,
        Plan.features,
        Plan.retention_days,
    ]
    form_create_rules = [
        "id",
        "name",
        "price",
        "sort_order",
        "is_public",
        "limits",
        "features",
        "retention_days",
    ]
    form_edit_rules = [
        "name",
        "price",
        "sort_order",
        "is_public",
        "archived_at",
        "limits",
        "features",
        "retention_days",
    ]
    form_args = {
        "id": {"description": "Lowercase letters, numbers and hyphens. Cannot be changed later."},
        "price": {"description": "Monthly price in whole units. Leave empty to show 'Custom'."},
        "is_public": {
            "label": "Public",
            "description": "Shown on the pricing page and pickable by users. Hidden plans are assigned by staff.",
        },
        "archived_at": {
            "label": "Archived",
            "description": "Set to retire the plan. Accounts on it keep it; nobody new can be put on it.",
        },
        "limits": {
            "default": dict.fromkeys(billing.LIMIT_KEYS, 0),
            "description": "Every limit must be set; null means unlimited.",
        },
        "features": {"default": [], "description": "The bullet points on the pricing page."},
        "retention_days": {"description": "Leave empty for unlimited."},
    }

    async def check_can_create(self, request: Request) -> bool:
        return roles.can_add(request.session.get(ROLE_KEY), self.model.__name__)

    async def check_can_edit(self, request: Request, model) -> bool:
        return roles.can_change(request.session.get(ROLE_KEY), self.model.__name__)

    async def on_model_change(
        self, data: dict, model, is_created: bool, request: Request
    ) -> None:
        """Check the whole plan, and keep its id fixed once made.

        The id is what accounts point at, so changing it would move every
        account on the plan onto whatever the new id named.
        """
        role = request.session.get(ROLE_KEY)
        if is_created:
            if not roles.can_add(role, self.model.__name__):
                raise HTTPException(status_code=403, detail="Your role cannot add plans.")
            plan_id = (data.get("id") or "").strip().lower()
            if not billing.PLAN_ID_PATTERN.match(plan_id):
                raise HTTPException(
                    status_code=400,
                    detail="The id must be lowercase letters, numbers and hyphens, up to 40 characters.",
                )
            db = SessionLocal()
            try:
                taken = db.get(Plan, plan_id) is not None
            finally:
                db.close()
            if taken:
                raise HTTPException(status_code=400, detail=f"A plan called {plan_id} already exists.")
            data["id"] = plan_id
        else:
            allowed = roles.editable_fields(role, self.model.__name__)
            if not allowed:
                raise HTTPException(status_code=403, detail="Your role cannot change plans.")
            data.pop("id", None)
            for key in list(data):
                if key not in allowed:
                    data.pop(key)

        if not (data.get("name") or "").strip() and (is_created or "name" in data):
            raise HTTPException(status_code=400, detail="A plan needs a name.")
        try:
            if is_created or "limits" in data:
                data["limits"] = billing.validate_limits(data.get("limits"))
            if is_created or "features" in data:
                data["features"] = billing.validate_features(data.get("features") or [])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for key in ("price", "retention_days"):
            value = data.get(key)
            if value is not None and value < 0:
                raise HTTPException(status_code=400, detail=f"{key} cannot be negative.")


class AdminUserAdmin(RoleScopedView, model=AdminUser):
    """Staff accounts, and the one thing in the panel staff may create.

    Until now the only way to add a colleague was to open a shell on the box
    that serves production and run `app.admin.bootstrap`. Granting someone a
    read only console role therefore meant granting them the machine first,
    which is a far larger thing than the role being handed over.
    """

    name = "Staff account"
    name_plural = "Staff accounts"
    icon = "fa-solid fa-user-shield"
    category = "People"
    category_icon = "fa-solid fa-users"
    can_create = True
    can_edit = True
    column_list = [
        AdminUser.email,
        AdminUser.role,
        AdminUser.is_active,
        AdminUser.created_at,
        AdminUser.last_login_at,
    ]
    column_formatters = {
        AdminUser.created_at: _to_the_minute("created_at"),
        AdminUser.last_login_at: _to_the_minute("last_login_at", "never"),
    }
    column_details_exclude_list = [AdminUser.password_hash]
    form_columns = [
        AdminUser.email,
        AdminUser.role,
        AdminUser.password_hash,
        AdminUser.is_active,
    ]
    form_create_rules = ["email", "role", "password_hash"]
    form_edit_rules = ["is_active"]
    form_overrides = {"role": wtforms.SelectField, "password_hash": wtforms.PasswordField}
    form_args = {
        "email": {"validators": [wtforms.validators.Email()]},
        "role": {"choices": [(name, name) for name in roles.ROLES]},
        "password_hash": {
            "label": "Password",
            "description": f"At least {MIN_STAFF_PASSWORD} characters. Shown to nobody after this.",
            "validators": [wtforms.validators.Length(min=MIN_STAFF_PASSWORD)],
        },
    }

    async def check_can_create(self, request: Request) -> bool:
        """The real gate, for the same reason `check_can_edit` is one: the class
        attribute cannot vary by role, and sqladmin calls this per request."""
        return roles.can_add(request.session.get(ROLE_KEY), self.model.__name__)

    async def check_can_edit(self, request: Request, model) -> bool:
        return roles.can_change(request.session.get(ROLE_KEY), self.model.__name__)

    async def on_model_change(
        self, data: dict, model, is_created: bool, request: Request
    ) -> None:
        """Creating checks the whole form. Editing may only stop an account."""
        role = request.session.get(ROLE_KEY)
        if not is_created:
            self._check_edit(data, model, role)
            return

        if not roles.can_add(role, self.model.__name__):
            raise HTTPException(status_code=403, detail="Your role cannot add staff.")

        data["email"] = (data.get("email") or "").strip().lower()
        if not data["email"]:
            raise HTTPException(status_code=400, detail="An email is required.")

        if data.get("role") not in roles.ROLES:
            raise HTTPException(
                status_code=400,
                detail="Role must be one of: %s." % ", ".join(roles.ROLES),
            )

        password = data.get("password_hash") or ""
        if len(password) < MIN_STAFF_PASSWORD:
            raise HTTPException(
                status_code=400,
                detail=f"The password must be at least {MIN_STAFF_PASSWORD} characters.",
            )
        data["password_hash"] = get_password_hash(password)

        db = SessionLocal()
        try:
            taken = (
                db.query(AdminUser).filter(AdminUser.email == data["email"]).first()
            )
        finally:
            db.close()
        if taken is not None:
            raise HTTPException(
                status_code=400,
                detail="A staff account already exists for that email.",
            )

    def _check_edit(self, data, model, role):
        """Drop anything but the fields this role may set, then hold the line
        that at least one superadmin is left able to sign in.

        A panel that can lock everyone out of itself is a panel whose recovery
        is a shell on the box, which is the thing this view exists to avoid.
        """
        allowed = roles.editable_fields(role, self.model.__name__)
        refused = [
            key
            for key, value in data.items()
            if key not in allowed and value != getattr(model, key, None)
        ]
        if refused:
            raise HTTPException(
                status_code=403,
                detail=f"Your role cannot change: {', '.join(sorted(refused))}.",
            )
        for key in list(data):
            if key not in allowed:
                data.pop(key)

        if data.get("is_active") is False and model.role == roles.SUPERADMIN:
            db = SessionLocal()
            try:
                if not _other_active_superadmins(db, model):
                    raise HTTPException(
                        status_code=400,
                        detail="This is the last superadmin who can still sign in.",
                    )
            finally:
                db.close()


class JanitorView(BaseView):
    """Leftovers worth a look, on one page.

    Staff only, and the purge is narrower still: reading across every workspace
    at once is a wide view of other people's data, and deleting what it finds is
    irreversible.
    """

    name = "Cleanup"
    icon = "fa-solid fa-broom"
    category = "Operations"
    category_icon = "fa-solid fa-screwdriver-wrench"
    template = "sqladmin/janitor.html"

    def is_visible(self, request: Request) -> bool:
        return self._allowed(request)

    def is_accessible(self, request: Request) -> bool:
        return self._allowed(request)

    @staticmethod
    def _allowed(request: Request) -> bool:
        return roles.can_sweep(request.session.get(ROLE_KEY))

    @expose("/janitor", methods=["GET", "POST"])
    async def page(self, request: Request):
        """Render the cleanup page, or one of its sections, and act on POST.

        One route taking both methods and both pages, rather than a route each:
        sqladmin names a custom view's route after the exposed function and the
        sidebar links to that name, so a second exposed method would rename the
        view out from under its own menu entry. A section is chosen with
        ``?section=``, which also keeps Cleanup selected in the sidebar.

        The role check below is load bearing and must not be removed. sqladmin
        applies ``is_accessible`` to the menu entry only, not to an exposed
        route, so without it anyone who typed the URL would be served the page.
        ModelViews are gated by sqladmin itself; this one is not.
        """
        if not self._allowed(request):
            return Response("Forbidden", status_code=403)

        section = request.query_params.get("section")
        if request.method == "POST":
            kind, message = await self._act(request)
            query = {"notice": message, "notice_kind": kind}
            if section:
                query["section"] = section
            return RedirectResponse(request.url.replace(query=urlencode(query)), status_code=303)

        role = request.session.get(ROLE_KEY)
        may_revoke = "is_active" in roles.editable_fields(role, "APIKey")
        if section == "keys":
            return await self._keys_page(request, may_revoke)
        return await self.templates.TemplateResponse(
            request,
            self.template,
            {"may_purge": role == roles.SUPERADMIN},
        )

    async def _keys_page(self, request: Request, may_revoke: bool):
        now = utcnow()
        db = SessionLocal()
        try:
            rows = [
                {
                    "id": str(key.id),
                    "name": key.name,
                    "owner": key.owner.email if key.owner else "unknown",
                    "created": key.created_at,
                    "last_used": key.last_used_at,
                    "standing": janitor.key_standing(key, now),
                    "due": janitor.is_due(key, now),
                    "told": janitor.notice_is_current(key),
                }
                for key, _why in janitor.unused_keys(db)
            ]
        finally:
            db.close()
        return await self.templates.TemplateResponse(
            request,
            "sqladmin/janitor_keys.html",
            {
                "rows": rows,
                "due_count": sum(1 for row in rows if row["due"]),
                "may_revoke": may_revoke,
                "email_ready": outbound.configured(),
                "stale_days": janitor.STALE_KEY_DAYS,
                "notice_days": janitor.NOTICE_DAYS,
            },
        )

    async def _act(self, request: Request):
        """Work out which action a submitted form asked for, and run it."""
        form = await request.form()
        if form.get("revoke_one"):
            return await self._revoke(request, [str(form["revoke_one"])])
        if form.get("notify_one"):
            return await self._notify(request, [str(form["notify_one"])])
        intent = form.get("intent")
        chosen = [str(key_id) for key_id in form.getlist("key_ids")]
        if intent == "revoke":
            single = str(form.get("key_id") or "")
            if not chosen and not single:
                return "error", "Select at least one key first."
            return await self._revoke(request, chosen or [single])
        if intent == "revoke_all":
            return await self._revoke(request, None)
        if intent == "notify":
            return await self._notify(request, chosen)
        if intent == "revoke_due":
            db = SessionLocal()
            try:
                due = janitor.due_key_ids(db)
            finally:
                db.close()
            if not due:
                return "info", "No key is past its notice yet."
            return await self._revoke(request, due)
        return await self._purge(request)

    @staticmethod
    def _may_touch_keys(request: Request) -> bool:
        return "is_active" in roles.editable_fields(request.session.get(ROLE_KEY), "APIKey")

    async def _revoke(self, request: Request, key_ids):
        """Switch off unused API keys: the ones named, or every one listed.

        Open to any role that may switch a key off from the API keys view, since
        it is the same change made from a different page. Which keys count as
        unused is worked out again rather than taken from the form, so a key
        used since the page loaded is left alone.
        """
        if not self._may_touch_keys(request):
            return "error", "Your role cannot revoke keys."
        db = SessionLocal()
        try:
            revoked = janitor.revoke_unused_keys(db, key_ids)
        finally:
            db.close()
        for revoked_id, _name in revoked:
            _record_action(
                request, "update", "APIKey", revoked_id,
                {"is_active": False, "revoked_from": "cleanup"},
            )
        if not revoked:
            return "info", "Nothing was revoked. The key may have been used since the page loaded."
        count = len(revoked)
        return "success", f"Revoked {count} unused key{'' if count == 1 else 's'}."

    async def _notify(self, request: Request, key_ids):
        """Email the owners of these unused keys that they will be revoked.

        A key only counts as warned once its owner's message was accepted by the
        relay, so a failure here can never lead to a key revoked without notice.
        """
        if not self._may_touch_keys(request):
            return "error", "Your role cannot notify key owners."
        if not outbound.configured():
            return "error", "Email is not set up yet, so no owner was told and nothing changed."
        if not key_ids:
            return "error", "Select at least one key first."

        def warn():
            db = SessionLocal()
            try:
                return janitor.notify_owners(db, key_ids, outbound.send)
            finally:
                db.close()

        warned, unreachable = await asyncio.to_thread(warn)
        for warned_id, _name in warned:
            _record_action(
                request, "notify", "APIKey", warned_id,
                {"revoke_after_days": janitor.NOTICE_DAYS},
            )
        parts = []
        if warned:
            count = len(warned)
            parts.append(
                f"Told the owners of {count} key{'' if count == 1 else 's'}; "
                f"they can be revoked after {janitor.NOTICE_DAYS} days."
            )
        if unreachable:
            parts.append("Could not email " + ", ".join(sorted(unreachable)) + "; their keys were not marked.")
        if not parts:
            return "info", "Nothing was sent. The keys may have been used since the page loaded."
        return ("error" if unreachable else "success"), " ".join(parts)

    async def _purge(self, request: Request):
        """Remove one workspace that has served its time in the trash.

        The only thing in the panel that destroys a row, so it is the narrowest
        it can be: a superadmin, one workspace named by id, and only once the
        waiting period has passed. That period is checked again in
        ``janitor.purge`` rather than trusted from the page offering the button,
        because this route is reachable without it.
        """
        if request.session.get(ROLE_KEY) != roles.SUPERADMIN:
            return "error", "Only a superadmin can purge a workspace."

        form = await request.form()
        raw_id = str(form.get("workspace_id", ""))
        db = SessionLocal()
        try:
            slug = janitor.purge(db, uuid.UUID(raw_id))
        except (ValueError, LookupError) as exc:
            return "error", str(exc) or "That workspace could not be purged."
        finally:
            db.close()
        _record_action(request, "delete", "Workspace", raw_id, {"purged_from_trash": slug})
        return "success", f"Purged {slug}."


def _record_action(request, action, model, row_id, changes):
    """Write the audit entry for a change made outside sqladmin's forms.

    sqladmin records what it changes through a form, but the cleanup page's
    actions are not form saves, so the trail is written here or they would be
    the changes in the panel that leave no record. A failure to log is not
    allowed to fail the request: the change is already made, and losing the
    record is better than reporting an error for work that was done.
    """
    db = SessionLocal()
    try:
        db.add(
            AdminAction(
                admin_id=request.session.get(SESSION_KEY),
                admin_email=request.session.get(EMAIL_KEY),
                action=action,
                model=model,
                row_id=str(row_id),
                changes=changes,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logging.exception("could not record a %s on %s in the audit trail", action, model)
    finally:
        db.close()


def janitor_findings():
    """The cleanup sections, opened and closed around one render."""
    db = SessionLocal()
    try:
        return janitor.findings(db)
    finally:
        db.close()


# What to call a row of each kind, so the audit trail can name what was changed
# rather than only pointing at it.
_AUDIT_LABELS = {
    "User": (User, lambda row: row.email),
    "Workspace": (Workspace, lambda row: row.slug),
    "APIKey": (APIKey, lambda row: f"{row.name} ({_email_of(row.owner)})"),
    "AdminUser": (AdminUser, lambda row: row.email),
}


def _audit_subject(model, name):
    """Name the row an entry is about, falling back to its id.

    An entry outlives what it describes, which is the point of keeping one, so
    a row that has since been deleted still has to render. A purge writes the
    slug into its own changes for exactly that reason, and it is used here when
    the workspace itself is long gone.
    """
    if not model.row_id:
        return "unknown"
    known = _AUDIT_LABELS.get(model.model)
    if known is None:
        return model.row_id
    table, label = known
    db = SessionLocal()
    try:
        row = None
        try:
            row = db.query(table).filter(table.id == uuid.UUID(model.row_id)).first()
        except ValueError:
            pass
        if row is not None:
            return label(row)
    except Exception:
        logging.exception("could not name the subject of an audit entry")
        return model.row_id
    finally:
        db.close()

    recorded = (model.changes or {}).get("purged_from_trash")
    if recorded:
        return f"{recorded} (purged)"
    return f"{model.row_id} (deleted)"


class AdminActionAdmin(RoleScopedView, model=AdminAction):
    """What staff have changed, newest first.

    Read only, and deliberately not editable by anyone: a trail that can be
    rewritten by the people it describes is not a trail.
    """

    name = "Audit trail"
    name_plural = "Audit trail"
    icon = "fa-solid fa-clipboard-list"
    category = "Operations"
    category_icon = "fa-solid fa-screwdriver-wrench"
    column_list = [
        AdminAction.created_at,
        AdminAction.admin_email,
        AdminAction.action,
        AdminAction.model,
        AdminAction.row_id,
        AdminAction.changes,
    ]
    column_labels = {
        AdminAction.created_at: "When",
        AdminAction.admin_email: "Who",
        AdminAction.action: "Did",
        AdminAction.model: "To",
        AdminAction.row_id: "Which",
        AdminAction.changes: "Set",
    }
    column_formatters = {
        AdminAction.row_id: _audit_subject,
        AdminAction.created_at: _to_the_minute("created_at"),
    }
    column_sortable_list = [AdminAction.created_at, AdminAction.admin_email]
    column_default_sort = (AdminAction.created_at, True)
    column_searchable_list = [AdminAction.admin_email, AdminAction.model]


VIEWS = (
    UserAdmin,
    WorkspaceAdmin,
    MembershipAdmin,
    APIKeyAdmin,
    WorkspaceInviteAdmin,
    SharedLinkAdmin,
    AdminUserAdmin,
    PlanAdmin,
    AdminActionAdmin,
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


def admin_environment():
    """Which deployment this panel is attached to, for the banner.

    Two panels that look identical are a hazard as soon as one of them is
    production, and more so once the write actions land. Unset shows no banner
    rather than a wrong one.
    """
    name = (settings.ADMIN_ENVIRONMENT or "").strip()
    return {"name": name, "danger": name.lower() in DANGEROUS_ENVIRONMENTS}


def admin_identity(request):
    """Who is signed in and with what role.

    The role decides what the panel will show at all, so the answer to "why can
    I not see that" belongs on screen rather than being found by hitting a 403.
    """
    return {
        "email": request.session.get(EMAIL_KEY),
        "role": request.session.get(ROLE_KEY, ""),
    }


def overview_attention(request):
    """Cleanup sections that have something in them, for roles allowed to look.

    None says the role may not look, which is a different answer from an empty
    list saying there is nothing to find, and keeps the policy here rather than
    in the template.
    """
    if not roles.can_sweep(request.session.get(ROLE_KEY)):
        return None
    try:
        return [section for section in janitor_findings() if section["rows"]]
    except Exception as exc:
        logging.warning("overview attention failed: %s", exc)
        return []


_RECORD_LABELS = {
    "User": lambda row: row.email,
    "Workspace": lambda row: row.slug,
    "APIKey": lambda row: f"{row.name} ({_email_of(row.owner)})",
    "AdminUser": lambda row: row.email,
    "Membership": lambda row: "%s in %s" % (
        _email_of(row.user),
        row.workspace.slug if row.workspace else "?",
    ),
    "WorkspaceInvite": lambda row: row.email,
    "SharedLink": lambda row: row.workspace.slug if row.workspace else "?",
}


def record_label(model_view, model):
    """What to call the row a detail page is about.

    The topbar says which record its actions would apply to, so the name has to
    be the one a person would recognise rather than a primary key. A model
    without an entry falls back to its id, which is worse to read but never
    wrong.
    """
    label = _RECORD_LABELS.get(type(model).__name__)
    if label is None:
        return str(getattr(model, "id", ""))
    try:
        return label(model)
    except Exception:
        return str(getattr(model, "id", ""))


def _janitor_url(admin, request):
    """Where the cleanup page lives, asked of the view rather than guessed.

    sqladmin names a custom view's route after the exposed function, so the
    name is `view-page` here and would change with the method. Reading it off
    the registered view keeps that detail out of the templates.
    """
    for view in admin._views:
        if isinstance(view, JanitorView):
            return request.url_for(f"admin:view-{view.identity}")
    return None


def _creatables(admin, request):
    """The views this role may add a row to, for the New menu.

    Empty is the normal answer today. Everything the panel shows is created by
    someone using the product, so the menu stays hidden until something here is
    genuinely ours to make.
    """
    items = []
    for view in admin._views:
        if not getattr(view, "is_model", False) or not view.can_create:
            continue
        if not view.is_accessible(request) or not view.is_visible(request):
            continue
        items.append({
            "label": view.name,
            "icon": view.icon,
            "url": request.url_for("admin:create", identity=view.identity),
        })
    return items


def _favicon_data_uri():
    """The visdom mark, inlined so the panel needs no static route for it.

    The console frontend serves the same file, but the panel is reachable
    without it and should not lose its icon when it is. Under a kilobyte, so
    inlining costs less than the plumbing would.
    """
    path = os.path.join(os.path.dirname(__file__), "static", "favicon.svg")
    try:
        with open(path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("ascii")
    except OSError as exc:
        logging.warning("admin favicon missing: %s", exc)
        return ""
    return f"data:image/svg+xml;base64,{encoded}"


def mount_admin(app, secret_key, base_url="/admin"):
    """Attach the admin panel to a FastAPI app."""
    admin = Admin(
        app=app,
        engine=engine,
        base_url=base_url,
        title="Visdom Dev staff",
        favicon_url=_favicon_data_uri(),
        templates_dir=os.path.join(os.path.dirname(__file__), "templates"),
        authentication_backend=StaffAuth(secret_key=secret_key),
        audit_backend=StaffAuditBackend(SessionLocal, SESSION_KEY, EMAIL_KEY),
    )
    admin.templates.env.globals["overview_cards"] = overview_cards
    admin.templates.env.globals["admin_environment"] = admin_environment
    admin.templates.env.globals["admin_identity"] = admin_identity
    admin.templates.env.globals["janitor_findings"] = janitor_findings
    admin.templates.env.globals["overview_recent"] = overview_recent
    admin.templates.env.globals["overview_attention"] = overview_attention
    admin.templates.env.globals["admin_creatables"] = (
        lambda request: _creatables(admin, request)
    )
    admin.templates.env.globals["janitor_url"] = (
        lambda request: _janitor_url(admin, request)
    )
    admin.templates.env.globals["record_label"] = record_label
    from app.admin.usage_view import UsageView

    for view in VIEWS:
        admin.add_view(view)
    admin.add_view(JanitorView)
    admin.add_view(UsageView)
    return admin
