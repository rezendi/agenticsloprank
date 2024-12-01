import json, time
from datetime import timedelta
from django.db import models
from django.utils import timezone
from .base import *
from .templates import TaskInfo
from .mission import *
from ..util import *
from ..plugins.text_links import process_text


class Task(BaseModel):
    class Meta:
        ordering = [
            "mission_id",
            "order",
            "id",
        ]

    structured_data = models.JSONField(default=dict, blank=True)
    status = models.IntegerField(choices=TaskStatus.choices, default=TaskStatus.CREATED)
    category = models.IntegerField(choices=TaskCategory.choices)
    reporting = models.IntegerField(choices=Reporting.choices, default=0)
    mission = models.ForeignKey(Mission, on_delete=models.CASCADE)
    order = models.IntegerField(default=0)
    task_info = models.ForeignKey(
        TaskInfo, on_delete=models.SET_NULL, null=True, blank=True
    )
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True)
    # other data dependencies, if any
    depends_on_urls = models.JSONField(default=list, blank=True)
    visibility = models.IntegerField(
        choices=Visibility.choices, default=Visibility.PRIVATE
    )
    url = models.URLField(null=True, blank=True)
    llm = models.CharField(max_length=256, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    prompt = models.TextField(null=True, blank=True)
    response = models.TextField(null=True, blank=True)
    rendered = models.TextField(null=True, blank=True)
    flags = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"({self.mission_id}, {self.id}) {self.name} | {self.get_status_char()}"

    def subnav_name(self):
        name = self.name or ""
        name = name.replace("Report On:", "")
        name = name.replace("Report on", "")
        name = name.replace("Aggregate for", "")
        name = name.replace("Aggregate", "")
        name = name.replace("Fetch", "")
        name = name.replace(" For Assessment", "")
        name = name.strip().capitalize()
        name = name.replace("Pr ", "Pull Request ")
        name = name.replace(" Api", " API")
        name = name.replace(" api", " API")
        name = name.replace("Api", "API ")
        name = name.replace(" jira", " Jira")
        return name

    def pretty_extras(self):
        extras = dict(self.extras)
        extras.pop("final_prompt", "")
        return json.dumps(extras, indent=2)

    def pretty_structured_data(self):
        return json.dumps(self.structured_data, indent=2)

    def final_prompt(self):
        return self.extras.get("final_prompt")

    # we don't report on LLM decisions, though we may report on the fetch tasks generated in response to them
    def requires_report(self):
        # if there is a key context report task already, don't create more
        if self.is_key_context():
            if self.mission.task_set.filter(
                reporting=Reporting.KEY_CONTEXT, category=TaskCategory.LLM_REPORT
            ).exists():
                return False
        # otherwise, create report tasks if the reporting field says so
        report_requirements = [Reporting.ALWAYS_REPORT, Reporting.KEY_CONTEXT]
        return self.reporting in report_requirements and not self.is_llm_decision()

    def requires_llm_response(self):
        return self.category in [
            TaskCategory.LLM_DECISION,
            TaskCategory.LLM_REPORT,
            TaskCategory.LLM_QUESTION,
            TaskCategory.FINALIZE_MISSION,
        ]

    def get_status_char(self):
        return self.get_status_display()[0] if self.status else "O"

    def mark_complete(self):
        self.status = TaskStatus.COMPLETE
        self.completed_at = timezone.now()
        self.save()

    def is_complete(self):
        return self.status == TaskStatus.COMPLETE

    def is_prompted(self):
        explicit = self.category in [
            TaskCategory.LLM_REPORT,
            TaskCategory.FINALIZE_MISSION,
            TaskCategory.LLM_DECISION,
        ]
        return explicit or self.reporting != Reporting.NO_REPORT

    def is_final_or_post(self):
        return self.category in [
            TaskCategory.FINALIZE_MISSION,
            TaskCategory.POST_MISSION,
        ]

    def is_time_series(self):
        if self.flags.get("time_series") == "false":
            return False
        if self.parent and self.parent.category == TaskCategory.FETCH_FOR_LLM:
            return False
        if not self.mission.is_time_series():
            return False
        previous = self.previous()
        if not previous:
            return False

        if not self.flags.get("time_series_days"):
            delta = self.created_at - previous.created_at
            self.extras["time_series_previous"] = "%s" % previous
            self.flags["time_series_days"] = "%s" % delta.days
            self.save()
        return True

    def cadence_days(self):
        return self.mission.cadence_days()

    # return cadence if there's a chain or a cadence, otherwise double it to cover a gap
    def commit_days(self):
        if self.is_fixed_window():
            return self.window_days()
        if self.flags.get("commit_days"):
            return self.flags["commit_days"]
        days = self.cadence_days()
        if not days:
            return MAX_CADENCE_DAYS
        previous_mission = self.mission.previous
        if previous_mission and self.category == TaskCategory.FINALIZE_MISSION:
            days = get_days_between(
                self.mission.created_at, previous_mission.created_at
            )
        return days if previous_mission else days * 2

    def get_repo(self):
        # flags is primary, structured_data secondary
        repo = self.flags.get("github", self.structured_data.get("repo", None))
        if not repo and self.parent:
            repo = self.parent.get_repo()
        if not repo and self.url and self.url.startswith(GITHUB_PREFIX):
            elements = self.url.split("/")
            repo = "/".join(elements[3:5]) if len(elements) > 4 else None
        if not repo:
            repo = self.mission.get_repo(from_task=True)
        return repo

    def default_git_branch(self):
        # extras is primary, structured_data secondary
        branch = self.flags.get("default_branch")
        if not branch:
            branch = self.structured_data.get("default_branch")
        if not branch:
            chain = self.ancestry_chain()
            for task in chain:
                branch = task.flags.get("default_branch")
                if not branch:
                    branch = task.structured_data.get("default_branch")
                if branch:
                    break
        return branch

    def github_metadata_only(self):
        if self.flags.get("github_metadata_only") == "true":
            return True
        integration = self.get_integration("github")
        return integration and integration.metadata_only()

    def is_confluence(self):
        return self.url and self.url.startswith(CONFLUENCE_API)

    def is_azure(self):
        return self.url and self.url.startswith(AZURE_API)

    def get_openai_key(self):
        return self.mission.get_openai_key()

    def is_vision(self):
        return self.llm == VISION_MODEL and self.extras.get("vision") == "true"

    def is_quantified_report(self):
        return self.category == TaskCategory.QUANTIFIED_REPORT

    def is_key_context(self):
        return self.reporting == Reporting.KEY_CONTEXT

    def is_aggregate(self):
        return self.category in [
            TaskCategory.AGGREGATE_TASKS,
            TaskCategory.AGGREGATE_REPORTS,
        ]

    def default_ordering_info(self):
        return Task.objects.filter(id=self.parent_id).values("url").first()

    def get_project(self):
        return self.mission.get_project()

    def get_integration(self, vendor):
        return self.mission.get_integration(vendor)

    def get_project_value(self, key, default=None):
        if key in self.extras:
            return self.extras.get(key, default)
        project = self.get_project()
        if project and key in project.extras:
            return project.extras.get(key)
        customer = self.get_customer()
        return customer.extras.get(key, default) if customer else default

    def is_test(self):
        return self.name.startswith("TDTest") or self.get_llm() in TEST_LLMS

    def is_data(self):
        return self.category in [
            TaskCategory.API,
            TaskCategory.SCRAPE,
            TaskCategory.FETCH_FOR_LLM,
        ]

    def is_llm_fetch(self):
        return self.category == TaskCategory.FETCH_FOR_LLM

    def is_llm_report(self):
        return self.category == TaskCategory.LLM_REPORT

    def is_llm_decision(self):
        return self.category == TaskCategory.LLM_DECISION

    def is_llm_rating(self):
        return self.category == TaskCategory.LLM_RATING

    def get_assistant_id(self):
        return self.extras.get("openai_assistant_id")

    def get_thread_id(self):
        return self.extras.get("openai_thread_id")

    def get_message_id(self):
        return self.extras.get("openai_message_id")

    def set_message_id(self, id):
        self.extras["openai_message_id"] = id

    def get_run_id(self):
        return self.extras.get("openai_run_id")

    def set_run_id(self, id):
        self.extras["openai_run_id"] = id

    def set_failed(self, failed):
        self.status = TaskStatus.FAILED if failed else self.status

    def get_customer(self):
        if not self.mission.mission_info:
            return None
        return self.mission.mission_info.customer

    def add_error(self, ex, due=None):
        log("Task error", self, ex)
        error = {int(time.time()): f"{ex} due to {due}" if due else str(ex)}
        if "errors" in self.extras:
            self.extras["errors"].append(error)
        else:
            self.extras["errors"] = [error]
        self.status = TaskStatus.FAILED
        self.save()

    def get_llm(self):
        if (self.name or "").startswith("TDTest"):
            if (self.llm or "").startswith("gemini"):
                return "gpt-4"  # just for testing, to avoid tokenizing API call
        if self.llm == "gpt-4o":
            return GPT_4O
        return self.llm or self.mission.get_llm() or GPT_4O_AZURE

    def get_repos(self):
        return self.mission.get_pr_repos() or {"repo": self.get_repo()}

    def render(self):
        if not self.rendered:
            self.rendered = process_text(self, self.response)
            self.save()
        return self.rendered

    def prep_for_rerun(self):
        self.status = TaskStatus.IN_PROCESS
        self.save()

    def get_email_re(self, default):
        email_to = self.flags.get("email_to", [])
        if not email_to:
            email_to = [self.mission.get("email_to", [])]
        if not email_to:
            email_to = default
        return email_to

    def followup_prompt(self):
        prompt = self.prompt or ""
        pieces = prompt.split("\n")
        if len(pieces) > 3:
            return "\n".join(pieces[3:]).strip()
        return prompt

    def child_tasks(self):
        # an eval is not a child
        ts = self.mission.task_set.filter(parent=self).exclude(
            category=TaskCategory.LLM_EVALUATION
        )
        if self.url and not is_sqlite():
            ts = ts | self.mission.task_set.filter(depends_on_urls__contains=self.url)
        return ts

    def prerequisite_tasks(self):
        all = self.ancestry_chain() + self.aggregate_dependencies()
        if self.category > TaskCategory.FETCH_FOR_LLM:
            all += self.mission.key_context_tasks()
        all = [t for t in all if t.id != self.id]
        # ensure key context goes at the end, even if from another mission
        return [t for t in all if not t.is_key_context()] + [
            t for t in all if t.is_key_context()
        ]

    def ancestry_chain(self):
        ancestors = []
        current = self.parent
        while current and current != self and current not in ancestors:
            ancestors.append(current)
            current = current.parent
        ancestors.reverse()
        return ancestors

    # return a list of all dependencies, incl. parent and any spanning task dependencies
    def aggregate_dependencies(self):
        tasks = []
        urls = self.depends_on_urls
        if self.url == ALL_REPORTS_URL or ALL_REPORTS_URL in urls:
            tasks += list(self.mission.sub_report_tasks().exclude(id=self.id))
        tasks += self.mission.task_set.filter(url__in=urls).exclude(
            id=self.id, category=TaskCategory.LLM_DECISION
        )
        # dependency to other missions
        for url in urls:
            if url.startswith("mission:"):  # format is mission:id:url
                target_id = int(url.split(":")[1])
                task_url = ":".join(url.split(":")[2:])
                targets = Task.objects.filter(mission_id=target_id, url=task_url)
                tasks += list(targets)
            if url.startswith("data_mission:"):
                target_id = self.mission.depends_on_id
                target = Mission.objects.filter(id=target_id).first()
                if target:
                    task_url = ":".join(url.split(":")[1:])
                    tasks += list(target.task_set.filter(url=task_url))
                else:
                    log("Data mission for dependent URL not found")
        return list(tasks)

    def assemble_prompt(self):
        if (
            self.reporting == Reporting.REPORT
            and self.category != TaskCategory.LLM_DECISION
        ):
            return f"{self.prompt or ''}\n\n{self.response or ''}"
        return self.prompt

    def prerequisite_input_tasks(self):
        prereqs = self.prerequisite_tasks()
        if not prereqs:
            return []

        # if based on LLM decisions, only get decision response and subsequent
        if self.flags.get("include_decision_chaing") != "true":
            ds = [
                p
                for p in prereqs
                if p.category == TaskCategory.LLM_DECISION
                or p.category == TaskCategory.FETCH_FOR_LLM
            ]
            if ds:
                last_idx = prereqs.index(ds[-1])
                prereqs = prereqs[last_idx:]

        if self.flags.get("alternating_reports") == "true":  # last two tasks only
            prereq = prereq[-2:]

        if self.flags.get("last_n_prereqs"):  # last N tasks only
            n = int(self.flags.get("last_n_prereqs"))
            prereq = prereq[-n:]

        for prereq in prereqs:  # paranoia
            prereq.refresh_from_db()

        return prereqs

    # return responses from the first and last task in the dependency set
    # the first is context, the last the most recent relevant response
    # if there are other LLM reports in between that are not decision inputs, include them too
    def assemble_prerequisite_inputs(self):
        tasks = self.prerequisite_input_tasks()

        # default overflow behavior: take the longest dataset, cut it in half
        # and simply repeat until we fit into the context window
        # for recency-ordered datasets this usually works surprisingly well!
        # other approaches via plugin are probably desirable for other cases
        texts = [t.response or t.structured_data or "" for t in tasks]
        text = "\n\n---\n\n".join(texts)
        while is_too_long(text, self.get_llm()):
            lengths = [len(t) for t in texts]
            max_len = max(lengths)
            max_idx = lengths.index(max_len)
            long_text = texts[max_idx]
            texts[max_idx] = long_text[: len(long_text) // 2] + "\n\n(truncated)\n..."
            text = "\n\n---\n\n".join(texts)

        input_data = text
        if len(texts) > 1:
            input_data = "\nConcatenated Datasets\n---------------------\n\n"
            for idx, t in enumerate(tasks):
                name = "Key Context" if t.is_key_context() else t.name
                input_data += (
                    f"\n# Dataset {idx+1}\n\n## {name}\n\n{texts[idx]}\n\n---\n"
                )
        return input_data

    # Get the task from the previous mission in the series, if any.
    def previous(self):
        prev_mission = self.mission.previous
        if not prev_mission:
            return None

        previous = (
            prev_mission.task_set.filter(task_info_id=self.task_info_id)
            .filter(status=TaskStatus.COMPLETE)
            .exclude(task_info_id__isnull=True)
            .order_by("-created_at")
            .first()
        )
        # this is pretty brittle
        if not previous and not self.task_info:
            previous = (
                prev_mission.task_set.filter(category=self.category)
                .filter(status=TaskStatus.COMPLETE)
                .filter(task_info_id__isnull=True)
                .filter(name=self.name)
                .order_by("-created_at")
                .first()
            )
        # this will hopefully catch name changes
        if not previous and self.parent:
            previous_parent = (
                prev_mission.task_set.filter(task_info_id=self.parent.task_info_id)
                .filter(status=TaskStatus.COMPLETE)
                .exclude(task_info_id__isnull=True)
                .order_by("-created_at")
                .first()
            )
            if previous_parent:
                previous = (
                    prev_mission.task_set.filter(parent_id=previous_parent.id)
                    .filter(status=TaskStatus.COMPLETE)
                    .filter(category=self.category)
                    .filter(url=self.url)
                    .order_by("-created_at")
                    .first()
                )
        if previous:
            days = get_days_between(self.created_at, previous.created_at)
            if days > self.cadence_days() * 4:
                return None
        return previous

    def window_start(self):
        start = self.flags.get("window_start")
        return datetime.datetime.fromisoformat(start) if start else None

    def window_final(self):
        end = self.flags.get("window_final")
        return datetime.datetime.fromisoformat(end) if end else None

    def window_end(self):
        task_end = self.flags.get("window_end")
        return datetime.datetime.fromisoformat(task_end) if task_end else None

    def window_days(self):
        return (self.window_end() - self.window_start()).days

    def is_fixed_window(self):
        # lazy initialize window breakpoint so we don't have to do it in the UI
        if self.window_start() and not self.window_end():
            breakpoint = self.window_start() + timedelta(days=self.cadence_days())
            self.flags["window_end"] = breakpoint.isoformat()
            self.save()
        if self.window_start() and self.window_final() and self.window_end():
            return True
        return False

    def raw_data(self):
        return RawData.objects.filter(task=self).first()

    def store_data(self, data):
        existing = self.raw_data()
        if existing:
            existing.data = data
            existing.save()
        else:
            RawData.objects.create(task=self, name="Raw data - %s" % self, data=data)


# don't fetch the actual data unless we need it
class RawDataManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().defer("data")


# raw data associated with a fetch task, usually
class RawData(BaseModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    data = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"Raw {self.id} - {self.task}"

    def to_yaml(self):
        return super().to_yaml()

    objects = RawDataManager()

    class Meta:
        base_manager_name = "objects"
        verbose_name_plural = "Raw data"
