from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0006_broadcastmessage"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="agentcompanymembership",
            name="custom_commission_plan",
        ),
    ]
