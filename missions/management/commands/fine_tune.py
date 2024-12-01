import json
from collections import defaultdict

from django.core.management.base import BaseCommand
from openai import OpenAI
from missions.models import *
from missions.util import token_count_for


class Command(BaseCommand):
    help = "Fine tune a type of report"

    def add_arguments(self, parser):
        parser.add_argument("--status", help="Check job status")
        parser.add_argument("--suffix", help="A fetch/report pair type to fine-tune")
        parser.add_argument("--check_file", help="Whether to check the file")
        parser.add_argument("--write_file", help="Whether to write the file")
        parser.add_argument("--dry_run", help="Just generate the training file")

    def handle(self, *args, **options):
        if options["check_file"]:
            return self.check_file(options["suffix"])
        if options["suffix"]:
            return self.fine_tune(options["suffix"], options["dry_run"] == "true")
        else:
            return self.get_status()

    def get_status(self):
        client = OpenAI()
        statuses = client.fine_tuning.jobs.list()
        for status in statuses:
            log("Job status", status)

    def fine_tune(self, suffix, dry_run):
        mission_info = MissionInfo.objects.filter(name=GENERIC_MISSION).first()
        missions = Mission.objects.filter(
            mission_info=mission_info,
            visibility=Visibility.PUBLIC,
            llm__startswith="gpt-4",
        ).values("id")
        mission_ids = [m["id"] for m in missions]

        if suffix == "pulls":
            tasks = Task.objects.filter(
                mission_id__in=mission_ids,
                category=TaskCategory.API,
                url__endswith="pulls",
            )
        else:  # just a PRs POC for now
            log("Unsupported suffix", suffix)
            tasks = []

        log("tasks count", len(tasks))
        ftd = []  # fine tune data
        total_tokens = 0
        for task in tasks:
            if total_tokens > 2000000:
                break
            report = Task.objects.filter(
                mission_id=task.mission_id,
                category=TaskCategory.LLM_REPORT,
                parent=task,
            ).first()
            if not report:
                continue
            if not report.prompt or not task.response or not report.response:
                continue
            m1 = {"role": "system", "content": report.prompt.replace('"', "'")}
            m2 = {"role": "user", "content": task.response.replace('"', "'")}
            m3 = {"role": "assistant", "content": report.response.replace('"', "'")}
            total_text = "%s %s %s" % (m1["content"], m2["content"], m3["content"])
            task_tokens = token_count_for(total_text)
            if task_tokens < 65536:
                ftd.append({"messages": [m1, m2, m3]})
                total_tokens += task_tokens
            else:
                log("Skipping task", task, "with tokens", task_tokens)

        log("Fine tune data count", len(ftd), "token count", total_tokens)
        filename = "%s.jsonl" % suffix

        if not ftd:
            log("No fine-tuning data")
            return

        with open(filename, "w") as f:
            for line in ftd:
                f.write(json.dumps(line) + "\n")
            f.close()

        if dry_run:
            log("Dry run, not uploading file")
            return

        log("Uploading training file", filename)
        client = OpenAI()
        file_id = client.files.create(
            file=open(filename, "rb"),
            purpose="fine-tune",
            suffix="yamllms-%s" % suffix,
        )
        log("Uploaded training file ID", file_id)

        # TODO wait for file to be processed
        retval = client.fine_tuning.jobs.create(
            training_file=file_id, model="gpt-4o-mini"
        )
        log("Job started", retval)

    # from https://cookbook.openai.com/examples/chat_finetuning_data_prep
    def check_file(self, suffix):
        filename = "%s.jsonl" % suffix
        with open(filename, "r", encoding="utf-8") as f:
            dataset = [json.loads(line) for line in f]
        log("Num examples:", len(dataset))

        # Format error checks
        format_errors = defaultdict(int)

        for ex in dataset:
            if not isinstance(ex, dict):
                format_errors["data_type"] += 1
                continue

            messages = ex.get("messages", None)
            if not messages:
                format_errors["missing_messages_list"] += 1
                continue

            for message in messages:
                if "role" not in message or "content" not in message:
                    format_errors["message_missing_key"] += 1

                if any(
                    k not in ("role", "content", "name", "function_call", "weight")
                    for k in message
                ):
                    format_errors["message_unrecognized_key"] += 1

                if message.get("role", None) not in (
                    "system",
                    "user",
                    "assistant",
                    "function",
                ):
                    format_errors["unrecognized_role"] += 1

                content = message.get("content", None)
                function_call = message.get("function_call", None)

                if (not content and not function_call) or not isinstance(content, str):
                    format_errors["missing_content"] += 1

            if not any(
                message.get("role", None) == "assistant" for message in messages
            ):
                format_errors["example_missing_assistant_message"] += 1

        if format_errors:
            log("Found errors:")
            for k, v in format_errors.items():
                log(f"{k}: {v}")
        else:
            log("No errors found")

        # Warnings and tokens counts
        n_missing_system = 0
        n_missing_user = 0
        n_messages = []

        for ex in dataset:
            messages = ex["messages"]
            if not any(message["role"] == "system" for message in messages):
                n_missing_system += 1
            if not any(message["role"] == "user" for message in messages):
                n_missing_user += 1
            n_messages.append(len(messages))

        log("Num examples missing system message:", n_missing_system)
        log("Num examples missing user message:", n_missing_user)
