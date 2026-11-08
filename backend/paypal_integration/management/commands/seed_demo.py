from django.core.management.base import BaseCommand
from django.db import transaction

from audit.models import AuditEvent
from core.models import Address, Buyer, Dispute, Order, Seller
from paypal_integration import demo
from paypal_integration.models import MockPayPalObject
from webhooks.models import WebhookEvent


class Command(BaseCommand):
    help = "Seed the 'Juniper Lane Apparel' demo shop. --live also plays the four live scenarios."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete all PayGuard data first")
        parser.add_argument("--live", action="store_true", help="Also deliver normal, scammer, ring and dispute events")

    def handle(self, *args, reset, live, **options):
        if reset:
            with transaction.atomic():
                for model in (Dispute, Order, Buyer, Address, Seller, WebhookEvent, MockPayPalObject, AuditEvent):
                    model.objects.all().delete()
            self.stdout.write("Reset done.")
        counts = demo.seed_history()
        self.stdout.write(self.style.SUCCESS(f"Seeded history: {counts}"))
        if live:
            for name in ("normal", "scammer", "ring", "dispute"):
                result = demo.live_scenario(name)
                self.stdout.write(f"  live {name:8s} -> {result.status} {result.message}")
