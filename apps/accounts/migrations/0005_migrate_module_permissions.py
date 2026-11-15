from django.db import migrations

MODULE_CHOICES = [
    "dashboard",
    "customers",
    "products",
    "inventory",
    "orders",
    "dispatch",
    "invoicing",
    "payments",
    "commissions",
    "agents",
    "reports",
    "tally_sync",
    "settings",
]


def _flags(permission):
    """Copy legacy flags, treating a selected module as viewable."""
    values = {
        "can_view": permission.can_view,
        "can_add": permission.can_add,
        "can_edit": permission.can_edit,
        "can_delete": permission.can_delete,
        "can_export": permission.can_export,
    }
    if not any(values.values()):
        values["can_view"] = True
    return values


def migrate_forward(apps, schema_editor):
    RoleTemplate = apps.get_model("accounts", "RoleTemplate")
    RoleTemplatePermission = apps.get_model("accounts", "RoleTemplatePermission")
    SubAdminProfile = apps.get_model("accounts", "SubAdminProfile")
    SubAdminPermission = apps.get_model("accounts", "SubAdminPermission")

    for template in RoleTemplate.objects.prefetch_related("permissions"):
        for permission in template.permissions.all():
            RoleTemplatePermission.objects.get_or_create(
                role_template=template,
                module=permission.module,
                defaults=_flags(permission),
            )

    for profile in SubAdminProfile.objects.prefetch_related(
        "custom_permissions", "role_template__module_permissions"
    ):
        for permission in profile.custom_permissions.all():
            SubAdminPermission.objects.get_or_create(
                sub_admin=profile,
                module=permission.module,
                defaults=_flags(permission),
            )

    # Upgrade compatibility: sub-admins that had no explicit rules previously
    # resolved to view-only for every module. Persist that behaviour once so
    # the stricter default-deny resolver does not lock anyone out on deploy.
    for profile in SubAdminProfile.objects.all():
        has_template_rules = (
            profile.role_template_id is not None
            and profile.role_template.module_permissions.exists()
        )
        if has_template_rules or profile.module_permissions.exists():
            continue
        for module in MODULE_CHOICES:
            SubAdminPermission.objects.get_or_create(
                sub_admin=profile,
                module=module,
                defaults={"can_view": True},
            )


def migrate_backward(apps, schema_editor):
    # Keep the legacy M2M rows intact; nothing to do on rollback.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_roletemplatepermission_subadminpermission"),
    ]

    operations = [
        migrations.RunPython(migrate_forward, migrate_backward),
    ]
