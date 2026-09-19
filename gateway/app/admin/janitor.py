# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Finds the leftovers a running deployment accumulates.

None of these are errors on their own, and none are deleted here. They are the
rows that stop matching reality over time: a workspace nobody belongs to, a key
issued and never used, an invite to someone who has since signed up. Left alone
they are what turns into a manual cleanup against the live database, which has
already happened once here with 268 orphaned workspace directories.
"""

import datetime

from sqlalchemy.orm import joinedload

from app.models import (
    APIKey,
    Membership,
    SharedLink,
    User,
    Workspace,
    WorkspaceInvite,
    utcnow,
)

# A key that has sat unused this long was probably issued and forgotten, rather
# than being between runs.
STALE_KEY_DAYS = 90

# How long a workspace sits in the trash before this page starts saying it is
# due. Nothing here purges anything, so this only decides when to mention it.
TRASH_DAYS = 30
NOTICE_DAYS = 30


def _aware(moment):
    """Treat a naive timestamp as UTC, which is what the columns hold."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=datetime.timezone.utc)
    return moment


def empty_workspaces(db):
    """Workspaces with no active member.

    Nobody can reach these through the app, so they are invisible until someone
    goes looking, and they still hold whatever is on disk.
    """
    active = (
        db.query(Membership.workspace_id)
        .filter(Membership.status == "active")
        .distinct()
        .subquery()
    )
    return (
        db.query(Workspace)
        .options(joinedload(Workspace.creator))
        .filter(
            ~Workspace.id.in_(db.query(active.c.workspace_id)),
            Workspace.trashed_at.is_(None),
        )
        .order_by(Workspace.slug)
        .all()
    )


def unused_keys(db):
    """Keys that have never been used, or not for a long time.

    A key is a live credential, so one nobody is using is only risk. Keys made
    in the last day are skipped, since a new key not yet used is normal.
    """
    cutoff = utcnow() - datetime.timedelta(days=STALE_KEY_DAYS)
    fresh = utcnow() - datetime.timedelta(days=1)
    rows = (
        db.query(APIKey)
        .options(joinedload(APIKey.owner))
        .filter(APIKey.is_active.is_(True))
        .all()
    )
    stale = []
    for key in rows:
        created, used = _aware(key.created_at), _aware(key.last_used_at)
        if used is None:
            if created is not None and created < fresh:
                stale.append((key, "never used"))
        elif used < cutoff:
            stale.append((key, f"last used {used.date()}"))
    return stale


def revoke_unused_keys(db, key_ids=None):
    """Switch off keys the cleanup page lists as unused, all of them or some.

    Checked against the list again here rather than trusted from the page,
    since the route is reachable without it: a key used since the page loaded
    is no longer unused and is left alone. Revoking only clears the active
    flag, so a key switched off by mistake can be switched back on.
    """
    wanted = None if key_ids is None else {str(key_id) for key_id in key_ids}
    revoked = []
    for key, _why in unused_keys(db):
        if wanted is not None and str(key.id) not in wanted:
            continue
        key.is_active = False
        revoked.append((str(key.id), key.name))
    if revoked:
        db.commit()
    return revoked


def notice_is_current(key):
    """Whether the owner was warned about this key and has not used it since.

    A key used after its owner was warned has earned its keep, so the warning no
    longer counts; if it falls unused again it needs a fresh one.
    """
    notified = _aware(key.owner_notified_at)
    if notified is None:
        return False
    used = _aware(key.last_used_at)
    return used is None or used < notified


def key_standing(key, now=None):
    """Where an unused key stands, as a short phrase for the page."""
    now = now or utcnow()
    if notice_is_current(key):
        deadline = _aware(key.revoke_after)
        if deadline is not None and deadline <= now:
            return "due for revocation"
        return f"owner told, revoke after {deadline:%-d %b}" if deadline else "owner told"
    used = _aware(key.last_used_at)
    return "never used" if used is None else f"last used {used.date()}"


def is_due(key, now=None):
    now = now or utcnow()
    deadline = _aware(key.revoke_after)
    return notice_is_current(key) and deadline is not None and deadline <= now


def notice_email(owner_email, keys, deadline):
    """The warning an owner gets: which keys, and the date they go."""
    lines = "\n".join(f"  - {key.name} (created {key.created_at:%Y-%m-%d})" for key in keys)
    when = f"{deadline:%-d %B %Y}"
    return (
        f"Your unused Visdom API keys will be switched off on {when}",
        (
            "Hello,\n\n"
            "These API keys on your Visdom account have not been used in a while:\n\n"
            f"{lines}\n\n"
            f"To keep accounts tidy and safe we plan to switch them off on {when}. "
            "If you still need one, using it before then keeps it active. "
            "If you do not, there is nothing you need to do.\n\n"
            "The Visdom team"
        ),
    )


def notify_owners(db, key_ids, send):
    """Warn the owners of these unused keys, one message per owner.

    A key is only marked as warned once its owner's message went out, so a
    failure to send can never lead to a key being revoked without warning.
    Returns the keys warned and the owners who could not be reached.
    """
    wanted = {str(key_id) for key_id in key_ids}
    by_owner = {}
    for key, _why in unused_keys(db):
        if str(key.id) in wanted and key.owner is not None:
            by_owner.setdefault(key.owner.email, []).append(key)

    now = utcnow()
    deadline = now + datetime.timedelta(days=NOTICE_DAYS)
    warned, unreachable = [], []
    for owner_email, keys in by_owner.items():
        subject, body = notice_email(owner_email, keys, deadline)
        if not send(owner_email, subject, body):
            unreachable.append(owner_email)
            continue
        for key in keys:
            key.owner_notified_at = now
            key.revoke_after = deadline
            warned.append((str(key.id), key.name))
    if warned:
        db.commit()
    return warned, unreachable


def due_key_ids(db):
    now = utcnow()
    return [str(key.id) for key, _why in unused_keys(db) if is_due(key, now)]


def expired_links(db):
    """Shared links whose expiry has passed. They no longer work, so they are
    only a list of addresses somebody was once given access to."""
    now = utcnow()
    rows = (
        db.query(SharedLink)
        .options(joinedload(SharedLink.workspace))
        .filter(SharedLink.expires_at.isnot(None))
        .all()
    )
    return [link for link in rows if _aware(link.expires_at) < now]


def answered_invites(db):
    """Email invites whose recipient has since registered.

    Registering converts pending invites into memberships, so one left behind
    means the two paths disagreed, and the person is now holding an invite they
    can never accept.
    """
    return (
        db.query(WorkspaceInvite)
        .options(joinedload(WorkspaceInvite.workspace))
        .join(User, User.email == WorkspaceInvite.email)
        .order_by(WorkspaceInvite.created_at)
        .all()
    )


def _slug(row):
    return row.workspace.slug if row.workspace else "unknown"


def link_summary(link):
    return {
        "workspace": _slug(link),
        "issued_to": link.invite_email or "anyone",
        "expired": _aware(link.expires_at).date().isoformat(),
    }


def invite_summary(invite):
    return {"workspace": _slug(invite), "email": invite.email}


def _delete_listed(db, rows, ids, describe):
    wanted = None if ids is None else {str(row_id) for row_id in ids}
    removed = []
    for row in rows:
        if wanted is None or str(row.id) in wanted:
            removed.append((str(row.id), describe(row)))
            db.delete(row)
    db.commit()
    return removed


def delete_expired_links(db, link_ids=None):
    """Delete shared links past their expiry: the ones named, or every one.

    Which links have expired is worked out again rather than taken from the
    page, so a link whose expiry was pushed back since it loaded is kept.
    Returns ``(id, summary)`` for each one removed, for the audit trail.
    """
    return _delete_listed(db, expired_links(db), link_ids, link_summary)


def delete_answered_invites(db, invite_ids=None):
    """Delete invites whose recipient has since signed up, as above."""
    return _delete_listed(db, answered_invites(db), invite_ids, invite_summary)


def trashed_workspaces(db):
    """Workspaces in the trash, longest-held first, with their age in days.

    Restoring one is a superadmin clearing its trashed timestamp, so nothing
    here is lost yet. Past ``TRASH_DAYS`` the intent was to stop keeping it,
    which is worth surfacing even though no purge runs on its own.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = (
        db.query(Workspace)
        .options(joinedload(Workspace.creator))
        .filter(Workspace.trashed_at.isnot(None))
        .order_by(Workspace.trashed_at)
        .all()
    )
    return [(ws, max(0, (now - _aware(ws.trashed_at)).days)) for ws in rows]


def purgeable(db):
    """Trashed workspaces old enough that keeping them was not the intent."""
    return [(ws, days) for ws, days in trashed_workspaces(db) if days >= TRASH_DAYS]


def purge(db, workspace_id):
    """Remove one workspace that has served its time in the trash.

    Refuses anything not trashed, and anything trashed more recently than
    ``TRASH_DAYS``, so the waiting period cannot be skipped by calling this
    directly. Returns the slug that was removed, for the audit entry.

    Rows only. The workspace's directory on the visdom volume is left where it
    is and shows up under the orphan section afterwards, so reclaiming disk
    stays a separate and visible step rather than something this quietly does.
    """
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if workspace is None:
        raise LookupError("That workspace no longer exists.")
    if workspace.trashed_at is None:
        raise ValueError("That workspace is not in the trash.")
    now = datetime.datetime.now(datetime.timezone.utc)
    days = (now - _aware(workspace.trashed_at)).days
    if days < TRASH_DAYS:
        raise ValueError(
            f"That workspace has been in the trash {days} days, "
            f"and is not due until {TRASH_DAYS}."
        )
    slug = workspace.slug
    db.delete(workspace)
    db.commit()
    return slug


def findings(db):
    """Everything worth a look, as sections the page can render in order."""
    return [
        {
            "title": "In the trash",
            "note": (
                f"Restorable by a superadmin. Nothing is purged automatically; "
                f"past {TRASH_DAYS} days is flagged as due."
            ),
            "rows": [
                "%s (%s) - %dd%s"
                % (
                    ws.slug,
                    ws.creator.email if ws.creator else "unknown",
                    days,
                    ", due for purge" if days >= TRASH_DAYS else "",
                )
                for ws, days in trashed_workspaces(db)
            ],
            # Only the rows past the waiting period, so the page cannot offer a
            # button for something the purge would refuse anyway.
            "purgeable": [
                {"id": str(ws.id), "slug": ws.slug, "days": days}
                for ws, days in purgeable(db)
            ],
        },
        {
            "title": "Workspaces with no active member",
            "note": "Unreachable through the app, and still holding whatever is on disk.",
            "rows": [
                f"{ws.slug} (created by {ws.creator.email if ws.creator else 'unknown'})"
                for ws in empty_workspaces(db)
            ],
        },
        {
            "title": "Keys nobody is using",
            "note": f"Active keys never used, or unused for {STALE_KEY_DAYS} days.",
            "rows": [
                f"{key.name} ({key.owner.email if key.owner else 'unknown'}) - {why}"
                for key, why in unused_keys(db)
            ],
            "manage": {"section": "keys", "label": "Manage these keys"},
        },
        {
            "title": "Shared links past their expiry",
            "note": "These no longer grant anything.",
            "rows": [
                f"{_slug(link)} - {link.invite_email or 'anyone'}, expired {_aware(link.expires_at).date()}"
                for link in expired_links(db)
            ],
            "manage": {"section": "links", "label": "Manage these links"},
        },
        {
            "title": "Invites to people who already signed up",
            "note": "Registering should have turned these into memberships.",
            "rows": [f"{invite.email} for {_slug(invite)}" for invite in answered_invites(db)],
            "manage": {"section": "invites", "label": "Manage these invites"},
        },
    ]
