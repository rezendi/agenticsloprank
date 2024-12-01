import yaml
from django.core.management.base import BaseCommand
from missions.models import *


# for now, just the new task types
class Command(BaseCommand):
    help = "Import a YAML file and convert to mission/task templates"

    def add_arguments(self, parser):
        parser.add_argument("--file", help="Path to YAML file")
        parser.add_argument("--dry_run", help="Set to true to not actually save to DB")
        parser.add_argument(
            "--overwrite", help="Set true to overwrite existing templates"
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"] == "true"

        # open and read the yaml file
        file = options["file"]
        if not file:
            log("No file specified")
            return
        with open(file) as f:
            data = yaml.safe_load(f)

        # create mission info
        name = data.get("mission", "Nameless Mission Template")
        existing = MissionInfo.objects.filter(name=name).first()
        if existing and not options["overwrite"]:
            log("Mission already exists, use --overwrite to replace")
            return
        if existing and options["overwrite"]:
            mission_info = existing
            mission_info.taskinfo_set.all().delete()
            mission_info.description = data.get("description")
            mission_info.depends_on = data.get("depends_on")
            mission_info.base_llm = data.get("base_llm", "gpt-4o")
            mission_info.base_prompt = data.get("base_prompt")
            mission_info.flags = data.get("flags", {})
            mission_info.extras = data.get("extras", {})
        else:
            mission_info = MissionInfo(
                name=name,
                description=data.get("description"),
                depends_on=data.get("depends_on"),
                base_llm=data.get("base_llm", "gpt-4o"),
                base_prompt=data.get("base_prompt"),
                flags=data.get("flags", {}),
                extras=data.get("extras", {}),
            )

        visibility = data.get("visibility", "Private")
        visibility = [v for v in Visibility.choices if v[1] == visibility][0]
        mission_info.visibility = visibility[0]

        cadence = data.get("cadence", "None")
        cadence = [c for c in MissionInfo.Cadence.choices if c[1] == cadence][0]
        mission_info.cadence = cadence[0]

        task_infos = []
        tasks_data = data.get("tasks", [])
        names = {}
        for info in tasks_data:
            key = list(info.keys())[0]
            info = info[key]
            names[key] = info.get("name", key)
            task_info = TaskInfo(
                name=key,
                base_url=info.get("base_url"),
                base_llm=info.get("base_llm"),
                base_prompt=info.get("base_prompt"),
                order=info.get("order", 0),
                flags=info.get("flags", {}),
                extras=info.get("extras", {}),
                depends_on_urls=info.get("depends_on_urls", []),
                description=info.get("description"),
            )

            # category is required
            category = info["category"]
            category = [c for c in TaskCategory.choices if c[1] == category][0]
            task_info.category = category[0]
            task_infos.append(task_info)

            reporting = info.get("report", "no")
            if reporting == "key context" or reporting == "key_context":
                task_info.reporting = Reporting.KEY_CONTEXT
            if not reporting or reporting == "no" or reporting == "never":
                task_info.reporting = Reporting.NO_REPORT
            else:
                task_info.reporting = Reporting.ALWAYS_REPORT

        # assign parents
        for info in tasks_data:
            key = list(info.keys())[0]
            task_info = [t for t in task_infos if t.name == key][0]
            parent = info[key].get("parent")
            if parent:
                task_info.parent = [t for t in task_infos if t.name == parent][0]

        for task_info in task_infos:
            name = task_info.name
            if names.get(task_info.name) != task_info.name:
                name = names[task_info.name]
            else:
                if task_info.category == TaskCategory.API:
                    name = "Fetch %s" % name
                name = name.replace("_", " ").title()
                name = name.replace(" Readme", " README")
                name = name.replace(" Pr", " PR")
            task_info.name = name

        if not dry_run:
            mission_info.save()
            for task_info in task_infos:
                task_info.mission_info = mission_info
                task_info.save()
        else:
            log("Ready to import mission template", mission_info)
            log("Task templates", task_infos)
