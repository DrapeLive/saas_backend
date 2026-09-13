from decimal import Decimal

from apps.accounts.models import AppModule, RoleType, SubAdminProfile


def get_subadmin_profile(user):
    """
    Return the SubAdminProfile for a subadmin user, or None.
    """
    if getattr(user, "role", None) != RoleType.SUB_ADMIN:
        return None
    return getattr(user, "subadmin_profile", None)


def can_manage_module(user, module):
    """
    RBAC check: whether a subadmin is allowed to work with a module.

    Admins and superadmins are always allowed. For subadmins, the check
    resolves permissions from:
      1. the assigned RoleTemplate (rank-order default), then
      2. explicit SubAdminProfile.custom_permissions overrides.
    Modules without any template permission default to read-only for subadmins.
    """
    if getattr(user, "role", None) in (RoleType.ADMIN, RoleType.SUPER_ADMIN):
        return True

    profile = get_subadmin_profile(user)
    if profile is None:
        return False

    permission = None
    template = profile.role_template
    if template is not None:
        permission = template.permissions.filter(module=module).first()
    if permission is None:
        permission = profile.custom_permissions.filter(module=module).first()
    if permission is None:
        # No explicit rule -> default to view-only (module visible).
        return True
    return permission.can_view


def get_effective_permission_map(user):
    """
    Resolve a subadmin's effective permissions across every module.

    Precedence matches ``can_manage_module``: RoleTemplate rules win,
    custom overrides fill modules missing from the template, and modules
    without any rule default to view-only. Returns a list of dicts.
    """
    profile = get_subadmin_profile(user)
    if profile is None:
        return []

    module_map = {}
    template = profile.role_template
    if template is not None:
        for perm in template.permissions.all():
            module_map.setdefault(perm.module, perm)
    for perm in profile.custom_permissions.all():
        module_map.setdefault(perm.module, perm)

    result = []
    for module, _label in AppModule.choices:
        perm = module_map.get(module)
        result.append(
            {
                "module": module,
                "can_view": perm.can_view if perm else True,
                "can_add": perm.can_add if perm else False,
                "can_edit": perm.can_edit if perm else False,
                "can_delete": perm.can_delete if perm else False,
                "can_export": perm.can_export if perm else False,
            }
        )
    return result


def get_subadmin_restrictions(user):
    """
    Return a subadmin's restrictions for the login payload, or None.
    """
    profile = get_subadmin_profile(user)
    if profile is None:
        return None
    return {
        "role_template": profile.role_template_id,
        "agent_ids": list(
            profile.restricted_agents.values_list("id", flat=True)
        ),
        "category_ids": list(
            profile.restricted_categories.values_list("id", flat=True)
        ),
        "approval_threshold": profile.approval_threshold,
    }


def get_subadmin_restricted_agent_ids(user):
    """Agent IDs a subadmin is restricted to (empty = unrestricted)."""
    profile = get_subadmin_profile(user)
    if profile is None or not profile.restricted_agents.exists():
        return set()
    return set(profile.restricted_agents.values_list("id", flat=True))


def get_subadmin_restricted_category_ids(user):
    """Category IDs a subadmin is restricted to (empty = unrestricted)."""
    profile = get_subadmin_profile(user)
    if profile is None or not profile.restricted_categories.exists():
        return set()
    return set(profile.restricted_categories.values_list("id", flat=True))


def scope_order_queryset(user, qs):
    """
    Scope an Order queryset to the subadmin's restricted agents.
    Unrestricted subadmins (or admins) see everything.
    """
    agent_ids = get_subadmin_restricted_agent_ids(user)
    if agent_ids:
        return qs.filter(agent_id__in=agent_ids)
    return qs


def scope_customer_queryset(user, qs):
    """
    Scope a Customer queryset to the subadmin's restricted agents.
    """
    agent_ids = get_subadmin_restricted_agent_ids(user)
    if agent_ids:
        return qs.filter(assigned_agent_id__in=agent_ids)
    return qs


def scope_category_queryset(user, qs):
    """
    Scope a Category queryset to the subadmin's restricted categories.
    Unrestricted subadmins (or admins) see everything.
    """
    category_ids = get_subadmin_restricted_category_ids(user)
    if category_ids:
        return qs.filter(pk__in=category_ids)
    return qs


def scope_product_queryset(user, qs):
    """
    Scope a Product queryset to the subadmin's restricted categories.
    """
    category_ids = get_subadmin_restricted_category_ids(user)
    if category_ids:
        return qs.filter(category_id__in=category_ids)
    return qs


def scope_agent_membership_queryset(user, qs):
    """
    Scope an AgentCompanyMembership queryset to the subadmin's restricted agents.
    """
    agent_ids = get_subadmin_restricted_agent_ids(user)
    if agent_ids:
        return qs.filter(agent_id__in=agent_ids)
    return qs


def compute_subadmin_approval_threshold(profile, amount):
    """
    Resolve whether an order amount exceeds the subadmin's approval threshold.
    Returns True when the order needs Admin approval.
    """
    threshold = profile.approval_threshold
    if threshold is None:
        return False
    return Decimal(amount) > Decimal(threshold)