from datetime import timedelta
from django.apps import apps
from django.db import models
from django.utils import timezone
from .base import *
from ..util import *
from ..prompts import get_prompt_from_github


# Templates for individual missions
class MissionInfo(BaseModel):
    class Meta:
        verbose_name = "Mission Template"

    class Cadence(models.IntegerChoices):
        NONE = 0, "None"
        HOURLY = 1, "Hourly"
        DAILY = 2, "Daily"
        WEEKLY = 3, "Weekly"
        BIWEEKLY = 4, "Biweekly"
        MONTHLY = 5, "Monthly"

    description = models.TextField(null=True, blank=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, null=True, blank=True
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, blank=True
    )
    # generally used for a "data mission" that fetches general data for a family of missions
    depends_on = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True
    )
    cadence = models.IntegerField(choices=Cadence.choices, default=Cadence.NONE)
    visibility = models.IntegerField(
        choices=Visibility.choices, default=Visibility.PRIVATE
    )
    # day of week (0-6) or day of month (1-31)
    run_at = models.IntegerField(null=True, blank=True)
    base_prompt = models.TextField(null=True, blank=True)
    base_llm = models.CharField(max_length=256, null=True, blank=True)
    flags = models.JSONField(default=dict, blank=True)

    def to_yaml(self):
        top = super().to_yaml()
        tasks = YAML_DIVIDER.join([t.to_yaml() for t in self.taskinfo_set.all()])
        return top + YAML_DIVIDER + tasks

    def cadence_days(self):
        return {
            MissionInfo.Cadence.HOURLY: 1 / 25,
            MissionInfo.Cadence.DAILY: 1,
            MissionInfo.Cadence.WEEKLY: 7,
            MissionInfo.Cadence.BIWEEKLY: 14,
            MissionInfo.Cadence.MONTHLY: 30,
        }.get(self.cadence, 0)

    # return task templates in order they should be run, if any
    def task_templates(self):
        return self.taskinfo_set.exclude(category=TaskCategory.OTHER)

    def all_repos(self, prefix):
        urls = [ti.base_url for ti in self.task_templates() if ti.base_url]
        urls = [u for u in urls if u.startswith(prefix)]
        end = 6 if prefix == AZURE_API else 5
        repos = ["/".join(u.split("/")[3:end]) for u in urls]
        return list(set(repos))

    def latest_mission(self):
        # if there's no complete mission from the last cadence / 2 days, return None
        cutoff = timezone.now() - timedelta(days=self.cadence_days() / 2)
        # hack to avoid circular dependencies, TODO  more elegance
        Mission = apps.get_model("missions", "Mission")
        return (
            self.mission_set.filter(status=Mission.MissionStatus.COMPLETE)
            .filter(created_at__gte=cutoff)
            .order_by("-created_at")
            .first()
        )

    def create_mission(self):
        Mission = apps.get_model("missions", "Mission")
        mission = Mission.objects.create(
            mission_info=self,
            name=self.name,
            visibility=self.visibility,
            llm=self.base_llm,
            prompt=self.base_prompt,
            extras=self.extras | {"mission_info_id": self.id},
            flags=self.flags,
        )
        mission.save()

        # missions are linked lists as well as standalone
        cutoff_after = mission.created_at - timedelta(days=mission.cadence_days() / 2)
        cutoff_before = mission.created_at - timedelta(days=mission.cadence_days() * 4)
        prev = (
            Mission.objects.exclude(id=mission.id)
            .filter(status=Mission.MissionStatus.COMPLETE)
            .filter(mission_info_id=mission.mission_info_id)
            .exclude(created_at__gte=cutoff_after)
            .exclude(created_at__lte=cutoff_before)
            .order_by("-created_at")
        )
        if not is_sqlite():
            prev = prev.exclude(extras__contains={"is_duplicate": "true"})
        if mission.flags.get("dynamic_repo"):
            prev = prev.filter(flags__github=mission.get_repo())

        mission.previous = prev.first()
        mission.save()
        return mission


# Templates for individual tasks
class TaskInfo(BaseModel):
    class Meta:
        verbose_name = "Task Template"
        ordering = [
            "mission_info_id",
            "order",
            "id",
        ]

    category = models.IntegerField(choices=TaskCategory.choices)
    mission_info = models.ForeignKey(
        MissionInfo, null=True, blank=True, on_delete=models.CASCADE
    )
    description = models.TextField(null=True, blank=True)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True)
    # other data dependencies, if any
    depends_on_urls = models.JSONField(default=list, blank=True)
    visibility = models.IntegerField(
        choices=Visibility.choices, default=Visibility.PRIVATE
    )
    order = models.IntegerField(default=0)
    reporting = models.IntegerField(choices=Reporting.choices, default=0)
    base_url = models.URLField(null=True, blank=True)
    base_llm = models.CharField(max_length=256, null=True, blank=True)
    base_prompt = models.TextField(null=True, blank=True)
    flags = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"({self.mission_info_id}, {self.id}) {self.name}"

    def create_task(self, mission, parent=None):
        llm = self.base_llm

        url = self.base_url
        log("Creating task", self.name, url)
        if url and "repo/placeholder" in url:
            url = url.replace("repo/placeholder", mission.get_repo() or "")
        depends_on_urls = [
            u.replace("repo/placeholder", mission.get_repo() or "repo/placeholder")
            for u in self.depends_on_urls
        ]
        if url == EXAMPLE_URL:
            url = mission.flags.get("mission_url")

        prompt = (
            (self.base_prompt or "")
            .replace("repo/placeholder", mission.get_repo() or "")
            .replace(EXAMPLE_URL, mission.flags.get("mission_url", EXAMPLE_URL))
        )
        # hack to avoid circular dependencies, TODO  more elegance
        Task = apps.get_model("missions", "Task")
        task = Task.objects.create(
            mission=mission,
            task_info=self,
            parent=parent,
            depends_on_urls=depends_on_urls,
            category=self.category,
            order=self.order,
            reporting=self.reporting,
            visibility=self.visibility,
            url=url,
            llm=llm,
            name=self.name,
            prompt=prompt,
            extras=self.extras,
            flags=self.flags,
        )

        # fetch default prompt from GitHub if the task needs a prompt but has none
        # use the URL by defualt, if no URL, see if there's a prompt key
        if task.is_prompted():
            prompt = task.prompt
            try:
                if prompt and len(prompt) < 64 and not " " in prompt.strip():
                    task.prompt = get_prompt_from_github(task.prompt)
                if not task.prompt:
                    url = task.url or (task.parent.url if task.parent else "")
                    if task.url:
                        suffix = url.split("/")[-1]
                        if task.category == TaskCategory.LLM_DECISION:
                            task.prompt = get_prompt_from_github("assess-" + suffix)
                        else:
                            task.prompt = get_prompt_from_github(url)
            except Exception as ex:
                task.add_error(f"Error fetching prompt", ex)

        task.save()
        return task

    @classmethod
    def create_report_task(cls, original):
        name = "Report On: %s" % original.name
        if original.is_test():
            name = "TDTest " + name
        Task = apps.get_model("missions", "Task")
        task = Task.objects.create(
            mission=original.mission,
            parent=original,
            name=name,
            category=TaskCategory.LLM_REPORT,
            order=original.order,
            visibility=original.visibility,
            llm=original.llm,
            prompt=original.prompt,
            extras=original.extras,
            flags=original.flags,
        )
        # strip out extraneous extras
        # TODO move some of these to separate columns
        for key in [
            "errors",
            "evaluated",
            "input_length",
            "input_tokens",
            "openai_message_id",
            "openai_run_id",
            "raw",
            "time_taken",
            "time_to_error",
            "truncated",
            "truncated_length",
            "truncated_thread_max",
            "truncated_tokens",
        ]:
            task.extras.pop(key, "")  # remove the key if it exists

        if original.is_key_context():
            task.reporting = Reporting.KEY_CONTEXT
            task.url = KEY_CONTEXT_URL
            task.depends_on_urls = [
                t.url
                for t in task.mission.task_set.filter(
                    reporting=Reporting.KEY_CONTEXT, category__lte=TaskCategory.FILTER
                ).exclude(id=original.id)
            ]

        if original.url and not task.prompt and not task.is_test():
            log("getting report prompt for", task)
            task.prompt = get_prompt_from_github(original.url)

        task.save()
        return task
