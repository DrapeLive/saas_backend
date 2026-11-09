from django.db import migrations, models


def backfill_category_rate_company(apps, schema_editor):
    CategoryCommissionRate = apps.get_model("commissions", "CategoryCommissionRate")
    for rate in CategoryCommissionRate.objects.select_related("plan").iterator():
        if rate.plan_id and rate.company_id is None:
            rate.company_id = rate.plan.company_id
            rate.save(update_fields=["company_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("commissions", "0003_backfill_payouts"),
    ]

    operations = [
        migrations.AddField(
            model_name="categorycommissionrate",
            name="company",
            field=models.ForeignKey(
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s_set",
                to="companies.company",
            ),
        ),
        migrations.RunPython(
            backfill_category_rate_company, migrations.RunPython.noop
        ),
        # SQLite: the field must be dropped from unique_together BEFORE the
        # FK is removed, or the table remake fails on the old constraint.
        migrations.AlterUniqueTogether(
            name="categorycommissionrate",
            unique_together=set(),
        ),
        migrations.RemoveField(
            model_name="categorycommissionrate",
            name="plan",
        ),
        migrations.AlterUniqueTogether(
            name="categorycommissionrate",
            unique_together={("company", "category")},
        ),
        migrations.RemoveField(
            model_name="commissionentry",
            name="plan",
        ),
        migrations.AlterField(
            model_name="categorycommissionrate",
            name="company",
            field=models.ForeignKey(
                on_delete=models.deletion.CASCADE,
                related_name="%(app_label)s_%(class)s_set",
                to="companies.company",
            ),
            preserve_default=False,
        ),
        migrations.DeleteModel(
            name="CommissionPlan",
        ),
        migrations.DeleteModel(
            name="CommissionSlab",
        ),
    ]