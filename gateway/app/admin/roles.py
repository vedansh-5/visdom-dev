# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Who may see what in the admin panel.

Reading every user's data is itself a privilege, so the role decides which
models are visible rather than only which actions are allowed. Write
permissions attach to these same roles when actions are added.
"""

VIEWER = "viewer"
SUPPORT = "support"
SUPERADMIN = "superadmin"

ROLES = (VIEWER, SUPPORT, SUPERADMIN)

_VISIBLE = {
    VIEWER: {"User", "Workspace", "Membership"},
    SUPPORT: {
        "User",
        "Workspace",
        "Membership",
        "APIKey",
        "WorkspaceInvite",
        "SharedLink",
        "AdminAction",
    },
    SUPERADMIN: {
        "User",
        "Workspace",
        "Membership",
        "APIKey",
        "WorkspaceInvite",
        "SharedLink",
        "AdminUser",
        "AdminAction",
    },
}


# Changing data is a narrower privilege than reading it, so it is answered
# separately rather than implied by visibility. Support handles the day to day
# incident: revoking a leaked key, or stopping an account that is misbehaving.
# Anything that decides what someone is entitled to stays with a superadmin.
_CHANGEABLE = {
    VIEWER: set(),
    SUPPORT: {"APIKey", "User", "Workspace"},
    SUPERADMIN: {"APIKey", "User", "Workspace"},
}

# What each role may set, within a model it can change at all. Restricting the
# form is what keeps "suspend an account" from also being "edit an account".
# Suspending a workspace is reversible and leaves everything on disk, so it sits
# with the rest of support's day to day. Moving one to the trash starts a clock
# that ends in deletion, so it stays with a superadmin even though the step
# itself is just as reversible.
_EDITABLE_FIELDS = {
    SUPPORT: {
        "APIKey": {"is_active"},
        "User": {"is_active"},
        "Workspace": {"is_active"},
    },
    SUPERADMIN: {
        "APIKey": {"is_active"},
        "User": {"is_active", "tier"},
        "Workspace": {"is_active", "trashed_at"},
    },
}


def can_see(role, model_name):
    return model_name in _VISIBLE.get(role, set())


def can_change(role, model_name):
    return model_name in _CHANGEABLE.get(role, set())


def editable_fields(role, model_name):
    """The fields this role may set on this model, empty when it may not."""
    return _EDITABLE_FIELDS.get(role, {}).get(model_name, set())


def is_valid(role):
    return role in ROLES
