import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0002_alter_plan_tier"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionPayment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("currency", models.CharField(default="INR", max_length=3)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("refunded", "Refunded")], default="pending", max_length=10)),
                ("payment_method", models.CharField(max_length=30)),
                ("provider", models.CharField(blank=True, max_length=50)),
                ("provider_payment_id", models.CharField(blank=True, max_length=150)),
                ("idempotency_key", models.CharField(max_length=100, unique=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("recorded_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("subscription", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="subscriptions.subscription")),
            ],
            options={
                "db_table": "subscriptions_payment",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="subscriptionpayment",
            index=models.Index(fields=["subscription", "status"], name="subscriptio_subscri_0bac84_idx"),
        ),
        migrations.AddIndex(
            model_name="subscriptionpayment",
            index=models.Index(fields=["provider_payment_id"], name="subscriptio_provide_d9b983_idx"),
        ),
    ]
