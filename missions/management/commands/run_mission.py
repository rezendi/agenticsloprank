from django.core.management.base import BaseCommand
from missions.models import MissionInfo
from missions.hub import fulfil_mission
from missions.util import log


class Command(BaseCommand):
    help = "Run a YamLLMs mission"

    def add_arguments(self, parser):
        parser.add_argument("--mission_id", help="ID of the mission template to run")
        parser.add_argument("--name", help="Name of the mission template to run")
        parser.add_argument(
            "--flag_name", help="Name of an argument to pass to the mission"
        )
        parser.add_argument(
            "--flag_val", help="Value of an argument to pass to the mission"
        )

    def handle(self, *args, **options):
        id = options["mission_id"]
        name = options["name"]
        if not id and not name:
            log("No mission template specified")
            return

        if id:
            mission_info = MissionInfo.objects.get(id=id)
        else:
            mission_info = MissionInfo.objects.get(name=name)

        log("Commencing mission", mission_info.name)
        mission = mission_info.create_mission()
        if options["flag_name"]:
            mission.flags[options["flag_name"]] = options["flag_val"]
        mission.save()
        fulfil_mission(mission.id)
        log("Mission complete")
