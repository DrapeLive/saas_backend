from decimal import Decimal

from apps.accounts.models import AppModule, RoleType, SubAdminProfile

ACTION_FLAGS = {
    "view": "can_view",
    "add": "can_add",
    "edit": "can_edit",
    "delete": "can_delete",
    "export": "can_export",
}

ALL_MODULES = [module for module, _label in AppModule.choices]


def get_subadmin_profile(user):
    """
    Return the SubAdminProfile for a subadmin user, or None.
    """
    if getattr(user, "role", None) != RoleType.SUB_ADMIN:
        return None
    return getattr(user, "subadmin_profile", None)


def get_module_rules(profile):
    """
    Resolve a sub-admin's module rules.

    The role template provides defaults; explicit ``SubAdminPermission`` rows
    override the template one module at a time.
    """
    rules = {}
    template = profile.role_template
    if template is not None:
        for rule in template.module_permissions.all():
            rules[rule.module] = rule
    for rule in profile.module_permissions.all():
        rules[rule.module] = rule
    return rules


def can_manage_module(user, module, action="view"):
    """
    RBAC check for one module action.

    Admins and superadmins always pass. Non-subadmin staff (e.g. agents) are
    left to the existing role permission classes. For sub-admins, a module
    without an explicit rule is denied.
    """
    role = getattr(user, "role", None)
    if role in (RoleType.ADMIN, RoleType.SUPER_ADMIN):
        return True
    if role != RoleType.SUB_ADMIN:
        return True

    profile = get_subadmin_profile(user)
    if profile is None:
        return False

    rule = get_module_rules(profile).get(module)
    if rule is None:
        return False

    flag = ACTION_FLAGS.get(action)
    if flag is None:
        return False
    return bool(getattr(rule, flag))


def get_effective_permission_map(user):
    """
    Resolve the effective permission map returned to the mobile app.

    Every module is always present so the client can reason about a complete
    matrix. Modules without a rule are explicitly disabled for sub-admins.
    """
    role = getattr(user, "role", None)
    if role in (RoleType.ADMIN, RoleType.SUPER_ADMIN):
        return [
            {
                "module": module,
                "can_view": True,
                "can_add": True,
                "can_edit": True,
                "can_delete": True,
                "can_export": True,
            }
            for module in ALL_MODULES
        ]

    if role != RoleType.SUB_ADMIN:
        return []

    profile = get_subadmin_profile(user)
    if profile is None:
        return []

    rules = get_module_rules(profile)
    result = []
    for module in ALL_MODULES:
        rule = rules.get(module)
        result.append(
            {
                "module": module,
                "can_view": bool(rule.can_view) if rule else False,
                "can_add": bool(rule.can_add) if rule else False,
                "can_edit": bool(rule.can_edit) if rule else False,
                "can_delete": bool(rule.can_delete) if rule else False,
                "can_export": bool(rule.can_export) if rule else False,
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


def serialize_module_permissions(rules):
    """Serialize module rules (template or override rows) for API responses."""
    return [rule.as_dict() | {"id": str(rule.id)} for rule in rules]


def set_subadmin_permissions(profile, rows):
    """
    Replace a sub-admin's explicit module overrides.

    ``rows`` is a list of dicts carrying ``module`` plus action flags. Duplicate
    modules are collapsed (last one wins).
    """
    from apps.accounts.models import SubAdminPermission

    normalized = {}
    for row in rows:
        normalized[row["module"]] = row

    profile.module_permissions.all().delete()
    SubAdminPermission.objects.bulk_create(
        [
            SubAdminPermission(
                sub_admin=profile,
                module=row["module"],
                can_view=bool(row.get("can_view", False)),
                can_add=bool(row.get("can_add", False)),
                can_edit=bool(row.get("can_edit", False)),
                can_delete=bool(row.get("can_delete", False)),
                can_export=bool(row.get("can_export", False)),
            )
            for row in normalized.values()
        ]
    )


def set_template_permissions(template, rows):
    """Replace a role template's module rules."""
    from apps.accounts.models import RoleTemplatePermission

    normalized = {}
    for row in rows:
        normalized[row["module"]] = row

    template.module_permissions.all().delete()
    RoleTemplatePermission.objects.bulk_create(
        [
            RoleTemplatePermission(
                role_template=template,
                module=row["module"],
                can_view=bool(row.get("can_view", False)),
                can_add=bool(row.get("can_add", False)),
                can_edit=bool(row.get("can_edit", False)),
                can_delete=bool(row.get("can_delete", False)),
                can_export=bool(row.get("can_export", False)),
            )
            for row in normalized.values()
        ]
    )


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


def revoke_user_refresh_tokens(user):
    """Blacklist every outstanding refresh token for a deactivated user."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)
