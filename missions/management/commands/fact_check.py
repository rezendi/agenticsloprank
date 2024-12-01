from django.core.management.base import BaseCommand
from missions.models import MissionInfo
from missions.hub import fulfil_mission
from missions.util import log

FACT_CHECK_MISSION = "Fact Check"


class Command(BaseCommand):
    help = "Fact check an online article using Bing News"

    def add_arguments(self, parser):
        parser.add_argument("--url", help="URL of the article to fact check")

    def handle(self, *args, **options):
        url = options["url"]
        log("Commencing fact check of", url)
        mission_info = MissionInfo.objects.get(name=FACT_CHECK_MISSION)
        mission = mission_info.create_mission()
        mission.flags["mission_url"] = url
        mission.save()
        fulfil_mission(mission.id)
        log("Fact check complete")
