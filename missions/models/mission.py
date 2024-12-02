import json, time
from django.db import models
from .base import *
from .templates import MissionInfo
from ..util import *
from ..plugins.text_links import process_text
from ..prompts import get_prompt_from_github


class Mission(BaseModel):
    class MissionStatus(models.IntegerChoices):
        CREATED = 0, "Created"
        BLOCKED = -1, "Blocked"
        FAILED = -2, "Failed"
        IN_PROCESS = 1, "In Process"
        COMPLETE = 2, "Complete"

    status = models.IntegerField(
        choices=MissionStatus.choices, default=MissionStatus.CREATED
    )
    mission_info = models.ForeignKey(
        MissionInfo, on_delete=models.SET_NULL, null=True, blank=True
    )
    visibility = models.IntegerField(
        choices=Visibility.choices, default=Visibility.PUBLIC
    )
    llm = models.CharField(max_length=256, null=True, blank=True)
    previous = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="next"
    )
    # generally used for a "data mission" that fetches general data for a family of missions
    depends_on = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True
    )
    prompt = models.TextField(null=True, blank=True)
    response = models.TextField(null=True, blank=True)
    rendered = models.TextField(null=True, blank=True)
    flags = models.JSONField(default=dict, blank=True)

    def create_base_tasks(self):
        if not self.mission_info:
            raise Exception("Cannot create tasks without a mission info")
        for ti in self.mission_info.task_templates():
            ti.create_task(self)
            time.sleep(settings.TASK_CREATION_DELAY)

    def __str__(self):
        return f"({self.id}) {self.name} | {self.get_status_char()}"

    def next(self):
        return Mission.objects.filter(previous=self).first()

    def to_yaml(self):
        top = super().to_yaml()
        tasks = YAML_DIVIDER.join([t.to_yaml() for t in self.task_set.all()])
        return top + YAML_DIVIDER + tasks

    def is_test(self):
        return self.name.startswith("TDTest") or self.get_llm() in TEST_LLMS

    def is_duplicate(self):
        return self.extras.get("is_duplicate") == "true"

    def is_time_series(self):
        # manual override
        if self.flags.get("time_series") == "false":
            return False
        if self.flags.get("time_series") == "true":
            return True
        return self.previous

    def is_multi_repo(self):
        gh = self.flags.get("github", [])
        return isinstance(gh, list) and len(gh) > 1

    def is_report_on_reports(self):
        finals = self.task_set.filter(category=TaskCategory.FINALIZE_MISSION)
        return any(
            f.parent and f.parent.category == TaskCategory.AGGREGATE_REPORTS
            for f in finals
        )

    def cadence_days(self):
        return self.mission_info.cadence_days() if self.mission_info else 0

    def get_status_char(self):
        return self.get_status_display()[0] if self.status else "O"

    def name_with_link(self):
        repo = self.get_repo()
        if not repo:
            return self.name
        for divider in [":", " -"]:
            if self.name and repo and divider in self.name:
                bits = [s.strip() for s in self.name.split(divider)]
                return f"{bits[0]}{divider} <a target='_blank' rel='noopener noreferrer' href='{GITHUB_PREFIX}{repo}'>{bits[1]}</a>"
        return self.name

    def get_llm(self):
        if self.llm:
            return GPT_4O if self.llm == "gpt-4o" else self.llm
        return self.mission_info.base_llm if self.mission_info else None

    # note that if the mission is multi-repo, this returns the first repo
    def get_repo(self, from_task=False):
        repo = self.flags.get("github", [])
        if repo:
            if isinstance(repo, str):
                return repo.strip()
            if isinstance(repo, list) and len(repo) > 0:
                return repo[0]
        if not from_task:
            tasks = self.task_set.all()
            for t in tasks:
                task_repo = t.get_repo()
                if task_repo:
                    return task_repo
        return None

    def get_customer(self):
        return self.mission_info.customer if self.mission_info else None

    def get_project(self):
        return self.mission_info.project if self.mission_info else None

    def restricted_tasks(self):
        return self.task_set.filter(visibility=Visibility.RESTRICTED)

    def get_openai_key(self):
        secret = None
        if self.get_customer():
            secret = self.get_customer().secret_set.filter(vendor="openai").last()
        return secret.value if secret else None

    def get_integration(self, vendor):
        integration = None
        if self.get_project():
            integration = self.get_project().get_integration(vendor)
        if not integration and self.get_customer():
            integration = self.get_customer().get_integration(vendor)
        return integration

    def reject_on_rerun_tasks(self):
        include = [
            TaskCategory.FINALIZE_MISSION,
            TaskCategory.POST_MISSION,
        ]
        return self.task_set.filter(category__in=include)

    # by default, we report on all the previous reports except interim agent reports
    def final_input_tasks(self):
        exclude = [
            TaskCategory.FETCH_FOR_LLM,
            TaskCategory.LLM_DECISION,
            TaskCategory.LLM_EVALUATION,
            TaskCategory.FINALIZE_MISSION,
            TaskCategory.POST_MISSION,
        ]
        valid_tasks = self.task_set.exclude(category__in=exclude)
        if self.flags.get("single_task_chain") == "true":
            return [valid_tasks.last()]

        input_tasks = valid_tasks.filter(category=TaskCategory.LLM_REPORT)
        input_tasks = input_tasks.order_by("order")

        # exclude interim agent reports
        if self.flags.get("include_all_agent_reports") != "true":
            agent_tasks = self.task_set.filter(category=TaskCategory.AGENT_TASK)
            agent_tasks = agent_tasks.exclude(parent__in=agent_tasks)
            input_tasks = input_tasks | agent_tasks

        # by default, don't report on quant reports, LLMs get confused
        if self.flags.get("include_quantified_reports") == "true":
            input_tasks = input_tasks | self.task_set.filter(
                category=TaskCategory.QUANTIFIED_REPORT
            )

        return input_tasks or [valid_tasks.last()]

    def tasks_to_run(self):
        return (
            self.task_set.exclude(status__in=[TaskStatus.COMPLETE, TaskStatus.HIDDEN])
            .exclude(category=TaskCategory.FINALIZE_MISSION)
            .exclude(category=TaskCategory.POST_MISSION)
            .order_by("order")
        )

    def fetch_tasks(self):
        categories = [
            TaskCategory.SCRAPE,
            TaskCategory.FILTER,
            TaskCategory.API,
        ]
        tasks = self.task_set.filter(category__in=categories).order_by("order")
        return list(tasks)

    def key_context_tasks(self):
        tasks = self.task_set.filter(reporting=Reporting.KEY_CONTEXT).exclude(
            id=self.id
        )
        if len(tasks) > 1:
            tasks = tasks.filter(category=TaskCategory.LLM_REPORT)
        return list(tasks)

    def followup_tasks(self):
        return self.task_set.filter(category=TaskCategory.LLM_QUESTION).order_by("-id")

    def two_phase_reporting_tasks(self):
        return self.task_set.all().filter(reporting=Reporting.REPORT)

    def tldr_task(self):
        return self.task_set.filter(
            category=TaskCategory.POST_MISSION, url__endswith="tldr"
        ).last()

    def llm_report_tasks(self):
        # for now, spanning tasks are always reports
        report_categories = [
            TaskCategory.LLM_REPORT,
            TaskCategory.AGGREGATE_TASKS,
            TaskCategory.AGGREGATE_REPORTS,
        ]
        return (
            self.task_set.all().filter(category__in=report_categories).order_by("order")
        )

    def sub_report_tasks(self):
        sub_report_categories = [
            TaskCategory.LLM_REPORT,
            TaskCategory.QUANTIFIED_REPORT,
            TaskCategory.AGGREGATE_TASKS,
        ]
        queryset = self.task_set.all().filter(category__in=sub_report_categories)
        return queryset

    def sub_reports(self):
        tasks = (
            self.sub_report_tasks()
            .filter(status=TaskStatus.COMPLETE)
            .exclude(visibility=Visibility.BLOCKED)
            .exclude(reporting=Reporting.KEY_CONTEXT)
            .order_by("order")
        ).prefetch_related("parent")
        tasks = order_sub_reports(tasks)
        return tasks

    def render(self):
        if not self.rendered:
            log("Rendering mission", self)
            text = self.response
            tldr = self.tldr_task()
            if tldr and tldr.response:
                text = "## Report tl;dr\n\n" + tldr.response + "\n\n---\n\n" + text
            self.rendered = process_text(self, text)
            self.save()
        return self.rendered

    def mission_report(self):
        if not self.response:
            return "No mission report yet..."
        return self.render()

    # this is pretty brittle tbh, but works for now
    # failure mode is that multi-repo reports don't get PR/issue links
    def get_pr_repos(self):
        repos = {}
        dep = self.depends_on
        if self.is_multi_repo() or dep and dep.is_multi_repo():
            exclude = []
            tasks = self.task_set.all().filter(url__endswith="pulls")
            tasks = tasks.only("structured_data")
            for task in tasks:
                prs = []
                for key in ["open", "closed"]:
                    prs += task.structured_data.get(key, [])
                for pr in prs:
                    number = pr["number"]
                    if number in exclude:
                        continue
                    if number in repos:  # multiple PRs with same number, don't link
                        del repos[number]
                        exclude.append(number)
                    else:
                        repos[number] = pr.get("repo")
        return repos

    def get_repos(self):
        return self.get_pr_repos() or {"repo": self.get_repo()}

    def get_final_prompt(self):
        if not self.prompt and "prompt_template" in self.flags:
            filename = self.flags["prompt_template"]
            if not filename.startswith("final-"):
                filename = "final-" + filename
            self.prompt = get_prompt_from_github(filename)
        if not self.prompt and self.mission_info:
            self.prompt = self.mission_info.base_prompt
        if self.prompt and len(self.prompt) < 64 and not " " in self.prompt.strip():
            self.prompt = get_prompt_from_github(self.prompt)
        self.save()
        return self.prompt or ""

    def default_git_branch(self):
        if self.is_multi_repo():
            return None
        defaults = [t.default_git_branch() for t in self.task_set.all()]
        return next((d for d in defaults if d), None)

    def sources_with_links(self):
        sources = []
        for task in self.task_set.all():
            source = source_from_task(task)
            if source.get("link") and not source["link"] in [
                s["link"] for s in sources
            ]:
                sources.append(source)
        return sources

    def commit_tasks(self):
        commit_categories = [
            TaskCategory.API,
            TaskCategory.AGGREGATE_REPORTS,
        ]
        return self.task_set.all().filter(
            category__in=commit_categories, url__endswith="commits"
        )


# extremely open-ended for now, we'll make it more precise as we iterate
class MissionEvaluation(BaseModel):
    class Meta:
        verbose_name = "Mission Evaluation"

    mission = models.ForeignKey(Mission, on_delete=models.SET_NULL, null=True)
    errors = models.JSONField(default=dict, blank=True)

    def get_problems(self):
        return self.errors.get("problems", [])

    def get_evaluation_tasks(self):
        if not self.mission:
            return []
        return self.mission.task_set.filter(category=TaskCategory.LLM_EVALUATION)

    def get_evals(self):
        evals = []
        for task in self.get_evaluation_tasks():
            raw = task.response
            if not raw:
                continue
            e = {"raw": raw, "task_id": task.id, "task_name": task.name}
            try:
                raw = json.loads(get_json_from_raw(raw, array_expected=True))
                criteria = []
                if isinstance(raw, list):
                    criteria = raw
                if isinstance(raw, dict):
                    for d in raw:
                        vals = raw[d]
                        if isinstance(vals, dict) and len(vals) == 1:
                            vals = vals[vals.keys()[0]]
                        criteria.append(vals)
                e["criteria"] = criteria
                e["score"] = self.get_score(criteria)
                evals.append(e)
            except Exception as ex:
                log("ex", ex)
                e["error"] = str(ex)
                evals.append(e)
        return evals

    def get_score(self, criteria):
        scores = ["poor", "mediocre", "fair", "good", "excellent"]
        ratings = [e["rating"] for e in criteria if "rating" in e]
        numbers = [1 + scores.index(r) for r in ratings]
        return sum(numbers)
