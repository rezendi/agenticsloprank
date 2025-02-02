from django.core.management.base import BaseCommand
from missions.models import MissionInfo
from missions.hub import fulfil_mission
from missions.admin_jobs import get_random_repo
from missions.util import log

from django.db.models import CharField
from django.db.models.functions import Lower

CharField.register_lookup(Lower, "lower")


SLOPRANK_MISSION = "SlopRank Repo Analysis"

class Command(BaseCommand):
    help = "Grab a random repo from GitHub's Daily Trending and run a report on it"

    def add_arguments(self, parser):
        parser.add_argument("--repo", help="not a random report if you set the repo")
        parser.add_argument("--llm", help="llm to use")

    def handle(self, *args, **options):
        log("Commencing Sloprank report")
        selected = options["repo"] if options["repo"] else get_random_repo(care=False)
        log("Reporting on", selected)
        mission_info = MissionInfo.objects.get(name=SLOPRANK_MISSION)
        mission = mission_info.create_mission()
        if options["llm"]:
            mission.llm = options["llm"] # by default we use OpenAI if not set
        mission.flags["github"] = selected
        mission.save()

        fulfil_mission(mission.id)
        log("SlopRank report complete")

        # TODO append report to CSV file for SlopRank
