import json
from django.core.management.base import BaseCommand
from missions.models import *


class Command(BaseCommand):
    help = "Temp command for one-off jobs"

    def handle(self, *args, **options):
        log("Running temp command")
        pass
