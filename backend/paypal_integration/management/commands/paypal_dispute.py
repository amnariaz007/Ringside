"""
Drive a real sandbox dispute for testing and the demo.

    manage.py paypal_dispute PP-D-123 --sync               fetch it from PayPal now (if a webhook is slow)
    manage.py paypal_dispute PP-D-123 --require-evidence   sandbox: move it to "waiting for seller evidence"
    manage.py paypal_dispute PP-D-123 --adjudicate seller  sandbox: PayPal rules for the seller (or: buyer)

--require-evidence and --adjudicate are sandbox-only PayPal endpoints. PayPal
then sends the usual CUSTOMER.DISPUTE.* webhooks; --sync applies the result at once.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from paypal_integration.client import PayPalError, SandboxPayPalClient
from paypal_integration.ingest import MissingDependency
from webhooks.service import apply_dispute


class Command(BaseCommand):
    help = "Sync or move along a PayPal sandbox dispute."

    def add_arguments(self, parser):
        parser.add_argument("dispute_id")
        parser.add_argument("--sync", action="store_true", help="Fetch the dispute from PayPal and apply it")
        parser.add_argument("--require-evidence", action="store_true", help="Sandbox: ask PayPal to wait for seller evidence")
        parser.add_argument("--adjudicate", choices=["seller", "buyer"], help="Sandbox: ask PayPal to rule")

    def handle(self, *args, dispute_id, sync, require_evidence, adjudicate, **options):
        if settings.PAYPAL_MODE != "sandbox" or "sandbox" not in settings.PAYPAL_API_BASE:
            raise CommandError("This command only works with PAYPAL_MODE=sandbox against the PayPal sandbox.")
        if not (sync or require_evidence or adjudicate):
            raise CommandError("Choose --sync, --require-evidence or --adjudicate.")
        client = SandboxPayPalClient()
        try:
            if require_evidence:
                client.require_evidence(dispute_id)
                self.stdout.write(f"{dispute_id}: PayPal now waits for the seller's evidence.")
            if adjudicate:
                client.adjudicate(dispute_id, "SELLER_FAVOR" if adjudicate == "seller" else "BUYER_FAVOR")
                self.stdout.write(f"{dispute_id}: PayPal ruled in favour of the {adjudicate}.")
            dispute = apply_dispute(client.get_dispute(dispute_id))
            case = getattr(dispute, "case", None)
            self.stdout.write(f"{dispute_id}: {dispute.status}"
                              + (f", copilot {case.status}" if case else ", copilot not started"))
        except MissingDependency as exc:
            raise CommandError(f"Ringside doesn't have this dispute's order yet ({exc}). "
                               "Check the capture webhook arrived and PAYPAL_MERCHANT_ID is set.")
        except PayPalError as exc:
            raise CommandError(str(exc))
