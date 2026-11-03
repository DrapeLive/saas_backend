from django.core.management.base import BaseCommand

from apps.orders.order_flow import expire_draft_orders


class Command(BaseCommand):
    help = "Expire stale DRAFT orders, release their stock reservations and delete them."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        expired = expire_draft_orders(batch_size=options["batch_size"])
        self.stdout.write(
            self.style.SUCCESS(f"Expired {len(expired)} draft order(s)")
        )
