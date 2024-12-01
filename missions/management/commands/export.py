import sys, yaml
from django.core.management.base import BaseCommand
from missions.models import *


# for now, just the new task types
class Command(BaseCommand):
    help = "Import a YAML file and convert to mission/task templates"

    def add_arguments(self, parser):
        parser.add_argument("--dry_run", help="Set to true to not actually save to DB")
        parser.add_argument("--template_id", help="ID of mission template to export")
        parser.add_argument("--skip_prompts", help="Don't output prompts")
        parser.add_argument("--file", help="Path to YAML file")

    def handle(self, *args, **options):
        dry_run = options["dry_run"] == "true"

        mission_info = MissionInfo.objects.get(id=options["template_id"])
        data = {
            "mission": mission_info.name,
            "tasks": [],
        }
        if mission_info.visibility != Visibility.PRIVATE:
            data["visibility"] = mission_info.get_visibility_display()
        if mission_info.cadence != MissionInfo.Cadence.NONE:
            data["cadence"] = mission_info.get_cadence_display()
        if mission_info.depends_on:
            data["depends_on"] = mission_info.depends_on_id
        if mission_info.description:
            data["description"] = mission_info.description
        if mission_info.base_llm:
            data["base_llm"] = mission_info.base_llm
        if mission_info.base_prompt and options["skip_prompts"] != "true":
            data["base_prompt"] = mission_info.base_prompt
        if mission_info.flags:
            data["flags"] = mission_info.flags
        if mission_info.extras:
            data["extras"] = mission_info.extras

        for task_info in mission_info.taskinfo_set.all():
            name = task_info.name.lower().replace(" ", "_")
            if task_info.base_url and not name:
                name = task_info.base_url.split("/")[-1].lower()

            task_data = {"category": task_info.get_category_display()}
            if task_info.reporting != Reporting.NO_REPORT:
                task_data["report"] = get_report_for_display(task_info.reporting)
            if task_info.base_url:
                task_data["base_url"] = task_info.base_url
            if task_info.depends_on_urls:
                task_data["depends_on_urls"] = task_info.depends_on_urls
            if task_info.order:
                task_data["order"] = task_info.order
            if task_info.base_llm:
                task_data["base_llm"] = task_info.base_llm
            if task_info.base_prompt and options["skip_prompts"] != "true":
                task_data["base_prompt"] = task_info.base_prompt
            if task_info.flags:
                task_data["flags"] = task_info.flags
            if task_info.extras:
                task_data["extras"] = task_info.extras
            if task_info.description:
                task_data["description"] = task_info.description

            if task_info.parent:
                parent_name = task_info.name.lower().replace(" ", "_")
                if task_info.parent.base_url:
                    parent_name = task_info.parent.base_url.split("/")[-1].lower()
                task_data["parent"] = parent_name
            data["tasks"].append({name: task_data})

        # print or write
        if not dry_run:
            file = options["file"] + ".yaml"
            with open(file, "w") as f:
                yaml.dump(data, f)
        else:
            yaml.dump(data, sys.stdout)


def get_report_for_display(reporting):
    if reporting == Reporting.KEY_CONTEXT:
        return "key_context"
    if reporting == Reporting.ALWAYS_REPORT:
        return "yes"
    return "no"
