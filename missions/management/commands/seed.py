import os
from django.core import management
from django.core.management.base import BaseCommand
from missions.models import *


class Command(BaseCommand):
    help = "Seed the YamLLMs database with initial mission / tasks for reporting on open-source GitHub repos"

    def handle(self, *args, **options):
        log("Seeding database")
        existing = User.objects.filter(username="admin").first()
        if not existing:
            User.objects.create_superuser(
                "admin",
                "admin@example.com",
                os.environ.get("ADMIN_PASSWORD", "adyamllms"),
            )
        # overwrite not set, so we won't overwrite existing templates
        management.call_command("import", file="missions/management/seed.yaml")
        log("Database seeded")
