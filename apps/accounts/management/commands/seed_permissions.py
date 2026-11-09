from django.core.management.base import BaseCommand

from apps.accounts.models import AppModule, Permission


class Command(BaseCommand):
    help = "Seed the 13 module Permission rows if they do not exist."

    def handle(self, *args, **options):
        created_count = 0
        for module in AppModule.values:
            _, created = Permission.objects.get_or_create(
                module=module,
                defaults={
                    "can_view": False,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_export": False,
                },
            )
            if created:
                created_count += 1
                self.stdout.write(f"Created permission for module '{module}'.")
            else:
                self.stdout.write(f"Permission for module '{module}' already exists.")

        self.stdout.write(
            self.style.SUCCESS(f"Seed complete. {created_count} permission(s) created.")
        )
