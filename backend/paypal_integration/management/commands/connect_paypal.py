"""
Check the PayPal sandbox connection and link the demo shop to the sandbox business account.

    manage.py connect_paypal              check keys, webhook ID, merchant ID; link the shop
    manage.py connect_paypal --discover   also find the business account's merchant ID

Prints only yes/no and IDs that are not secret (merchant IDs appear in every order).
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from paypal_integration.client import PayPalError, SandboxPayPalClient
from paypal_integration.sellers import DEMO_MERCHANT_ID, get_or_create_seller


class Command(BaseCommand):
    help = "Check the PayPal sandbox connection and link Juniper Lane to the sandbox business account."

    def add_arguments(self, parser):
        parser.add_argument("--discover", action="store_true",
                            help="Create an unpaid $1 sandbox order to read the business account's merchant ID")

    def handle(self, *args, discover, **options):
        ok = self.style.SUCCESS("yes")
        no = self.style.ERROR("no")
        self.stdout.write(f"PAYPAL_MODE            {settings.PAYPAL_MODE}")
        self.stdout.write(f"API base               {settings.PAYPAL_API_BASE}")
        self.stdout.write(f"Client ID + secret     {ok if settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET else no}")
        self.stdout.write(f"PAYPAL_WEBHOOK_ID      {ok if settings.PAYPAL_WEBHOOK_ID else no}")
        self.stdout.write(f"PAYPAL_MERCHANT_ID     {settings.PAYPAL_MERCHANT_ID or no}")
        if "sandbox" not in settings.PAYPAL_API_BASE:
            raise CommandError("PAYPAL_API_BASE is not the sandbox; this demo only talks to the sandbox.")
        try:
            client = SandboxPayPalClient()
            client._access_token()
        except PayPalError as exc:
            raise CommandError(f"Sandbox login failed: {exc}")
        self.stdout.write(f"Sandbox login          {ok}")

        if discover:
            try:
                order = client.create_order({
                    "reference_id": "ringside-connect-check", "description": "Ringside connection check (never paid)",
                    "amount": {"currency_code": "USD", "value": "1.00"},
                })
            except PayPalError as exc:
                raise CommandError(f"Could not create the check order: {exc}")
            found = order.get("purchase_units", [{}])[0].get("payee", {}).get("merchant_id", "")
            self.stdout.write(f"Business merchant ID   {found or no}")
            if found and not settings.PAYPAL_MERCHANT_ID:
                self.stdout.write(f"Add this line to .env and restart:  PAYPAL_MERCHANT_ID={found}")
            elif found and found != settings.PAYPAL_MERCHANT_ID:
                raise CommandError(f"PAYPAL_MERCHANT_ID does not match these API keys' business account ({found}). "
                                   "Fix .env and restart; the shop was not relinked.")

        if settings.PAYPAL_MERCHANT_ID:
            seller = get_or_create_seller()
            self.stdout.write(f"Shop                   {seller.name} -> {seller.paypal_merchant_id}"
                              + (" (linked)" if seller.paypal_merchant_id != DEMO_MERCHANT_ID else ""))
        ready = all([settings.PAYPAL_MODE == "sandbox", settings.PAYPAL_WEBHOOK_ID, settings.PAYPAL_MERCHANT_ID])
        self.stdout.write(self.style.SUCCESS("Ready for real sandbox orders.") if ready else
                          self.style.WARNING("Not ready yet: set PAYPAL_MODE=sandbox, PAYPAL_WEBHOOK_ID and PAYPAL_MERCHANT_ID."))
