from django.core.management.base import BaseCommand
from missions.models import *


# for now, just the new task types
class Command(BaseCommand):
    help = "Add a task or template to a mission or template"

    def add_arguments(self, parser):
        parser.add_argument("--template_id", help="Mission ID")

    def handle(self, *args, **options):
        if options["template_id"]:
            mission_info = MissionInfo.objects.get(id=options["template_id"])
            for dep in mission_info.taskinfo_set.filter(
                category=TaskCategory.API, base_url__endswith="/pulls"
            ):
                assess = mission_info.taskinfo_set.filter(
                    base_url=dep.base_url, category=TaskCategory.LLM_RATING
                ).first()
                if not assess:
                    assess = TaskInfo.objects.create(
                        mission_info=mission_info,
                        name="Assess pull requests",
                        category=TaskCategory.LLM_RATING,
                        parent=dep,
                        base_url=dep.base_url,
                        order=98,
                    )
                quant = mission_info.taskinfo_set.filter(
                    parent=assess, category=TaskCategory.QUANTIFIED_REPORT
                ).first()
                if not quant:
                    quant = TaskInfo.objects.create(
                        mission_info=mission_info,
                        name="Rate pull requests",
                        category=TaskCategory.QUANTIFIED_REPORT,
                        parent=assess,
                        order=99,
                    )

            risks = mission_info.taskinfo_set.filter(
                base_url=ASSESS_RISK_URL,
                category=TaskCategory.AGENT_TASK,
            ).first()
            if not risks:
                risks = TaskInfo.objects.create(
                    mission_info=mission_info,
                    name="Risk Detective",
                    category=TaskCategory.AGENT_TASK,
                    order=998,
                    base_url=ASSESS_RISK_URL,
                )
            quant = mission_info.taskinfo_set.filter(
                base_url=QUANTIFY_RISK_URL,
                category=TaskCategory.QUANTIFIED_REPORT,
            ).first()
            if not quant:
                quant = TaskInfo.objects.create(
                    mission_info=mission_info,
                    name="Quantify risks",
                    category=TaskCategory.QUANTIFIED_REPORT,
                    parent=risks,
                    order=999,
                    base_url=QUANTIFY_RISK_URL,
                )
        else:
            pass
