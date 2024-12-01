from django.core.management.base import BaseCommand
import openai
from missions.util import log


class Command(BaseCommand):
    help = "Clean up the OpeenAI files"

    def handle(self, *args, **options):
        log("Cleaning up")
        for file in openai.files.list():
            log("Deleting", file)
            openai.files.delete(file.id)
