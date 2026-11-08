import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create or update the demo seller login from DEMO_USERNAME and DEMO_PASSWORD (set them in .env)."

    def handle(self, *args, **options):
        username = os.environ.get("DEMO_USERNAME", "").strip()
        password = os.environ.get("DEMO_PASSWORD", "")
        if not username or not password:
            raise CommandError("Set DEMO_USERNAME and DEMO_PASSWORD in .env first.")
        if len(password) < 12:
            raise CommandError("DEMO_PASSWORD must be at least 12 characters.")
        User = get_user_model()
        user, created = User.objects.get_or_create(username=username, defaults={"email": username})
        user.first_name, user.last_name = "Juniper Lane", "Apparel"
        user.is_staff = user.is_superuser = False
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Updated'} demo user {username}"))
