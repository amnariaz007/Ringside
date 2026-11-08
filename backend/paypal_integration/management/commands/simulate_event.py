from django.core.management.base import BaseCommand, CommandError

from paypal_integration import demo


class Command(BaseCommand):
    help = "Deliver one demo event through the webhook pipeline: normal | scammer | ring | dispute"

    def add_arguments(self, parser):
        parser.add_argument("scenario", choices=["normal", "scammer", "ring", "dispute"])

    def handle(self, *args, scenario, **options):
        try:
            result = demo.live_scenario(scenario)
        except RuntimeError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"{result.status} {result.message}")
