"""Company services: orchestration helpers shared across apps."""

from apps.companies.models import Company, CompanySettings
from apps.subscriptions.models import Plan


def apply_plan_to_company(company: Company, plan: Plan) -> None:
    # Feature toggles mirrored onto the Company record
    company.tally_enabled = plan.tally_sync_enabled
    company.whatsapp_enabled = plan.whatsapp_enabled
    company.gst_verify_enabled = plan.gst_verify_enabled
    company.save(
        update_fields=[
            "tally_enabled",
            "whatsapp_enabled",
            "gst_verify_enabled",
        ]
    )

    # Capacity limits + advanced features snapshotted onto CompanySettings
    settings, _ = CompanySettings.objects.get_or_create(company=company)
    settings.current_plan_tier = plan.tier
    settings.current_plan_name = plan.name
    settings.plan_max_agents = plan.max_agents
    settings.plan_max_customers = plan.max_customers
    settings.plan_max_products = plan.max_products
    settings.plan_max_orders_per_month = plan.max_orders_per_month
    settings.plan_storage_gb = plan.storage_gb
    settings.analytics_advanced = plan.analytics_advanced
    settings.offline_mode_enabled = plan.offline_mode_enabled
    settings.api_access_enabled = plan.api_access_enabled
    settings.custom_domain_enabled = plan.custom_domain_enabled
    settings.dedicated_support = plan.dedicated_support
    settings.save(
        update_fields=[
            "current_plan_tier",
            "current_plan_name",
            "plan_max_agents",
            "plan_max_customers",
            "plan_max_products",
            "plan_max_orders_per_month",
            "plan_storage_gb",
            "analytics_advanced",
            "offline_mode_enabled",
            "api_access_enabled",
            "custom_domain_enabled",
            "dedicated_support",
        ]
    )
