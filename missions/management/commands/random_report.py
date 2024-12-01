import os
from django.core.management.base import BaseCommand
from missions.models import MissionInfo
from missions.hub import fulfil_mission
from missions.admin_jobs import get_random_repo
from missions.util import GENERIC_MISSION, log

from django.db.models import CharField
from django.db.models.functions import Lower

CharField.register_lookup(Lower, "lower")


class Command(BaseCommand):
    help = "Grab a random repo from GitHub's Daily Trending and run a report on it"

    def add_arguments(self, parser):
        parser.add_argument("--repo", help="not a random report if you set the repo")

    def handle(self, *args, **options):
        log("Commencing random report")
        selected = options["repo"] if options["repo"] else get_random_repo(care=True)
        log("Reporting on", selected)
        mission_info = MissionInfo.objects.get(name=GENERIC_MISSION)
        mission = mission_info.create_mission()
        if "NVIDIA_API_KEY" in os.environ and not "OPENAI_API_KEY" in os.environ:
            mission.base_llm = "nvidia/llama-3.1-nemotron-70b-instruct"
        mission.flags["github"] = selected
        mission.save()

        fulfil_mission(mission.id)
        log("Random report complete")
