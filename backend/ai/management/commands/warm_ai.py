"""Write the AI summaries for every fraud ring now, so pages show them at once (run before a demo)."""

from django.core.management.base import BaseCommand

from ai import summaries
from graph.builder import find_rings


class Command(BaseCommand):
    help = "Generate and store AI summaries for all fraud rings."

    def handle(self, *args, **options):
        rings = find_rings()
        for ring in rings:
            if not ring["summary_pending"]:
                self.stdout.write(f"{ring['id']}: ready ({ring['summary_source']})")
                continue
            result = summaries.generate(ring["stats"])
            self.stdout.write(f"{ring['id']}: " + (f"written by {result['source']}" if result
                                                    else self.style.WARNING("model unavailable, try again")))
