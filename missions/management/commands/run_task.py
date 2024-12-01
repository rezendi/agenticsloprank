from django.core.management.base import BaseCommand
from missions.models import *
from missions.hub import run_task, fulfil_mission


class Command(BaseCommand):
    help = "Run a task or mission"

    def add_arguments(self, parser):
        parser.add_argument("--task_id", help="Task ID")
        parser.add_argument("--mission_id", help="Mission ID")

    def handle(self, *args, **options):
        if options["task_id"]:
            opt = options["task_id"]
            ids = opt[1:-1].split(",") if opt.startswith("[") else [opt]
            for id in ids:
                task = Task.objects.get(id=id)
                task.status = TaskStatus.IN_PROCESS
                task.save()
                run_task(task.id)
                task.refresh_from_db()
                task.rendered = ""
                task.save()
                log(task.response)

        elif options["mission_id"]:
            mission = Mission.objects.get(id=options["mission_id"])
            fulfil_mission(mission.id)
            mission.refresh_from_db()
            log(mission.response)

        else:
            pass
