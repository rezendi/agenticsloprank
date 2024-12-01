import datetime, json, random, requests, os
from redis import Redis
from rq import Worker
import django_rq
from bs4 import BeautifulSoup
from openai import OpenAI
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from .util import *
from .models import *
from .prompts import get_prompt_from_github


def copy_mission(mission_id, new_prompts=None):
    mission = Mission.objects.get(id=mission_id)
    log("Copying", mission)
    mission.pk = None
    mission.status = mission.MissionStatus.CREATED
    mission.extras["is_duplicate"] = "true"
    mission.extras["original_mission_id"] = mission_id
    mission.response = ""
    mission.save()
    new_mission = Mission.objects.all().order_by("-id")[:1].first()
    key_changes = {}
    mission = Mission.objects.get(id=mission_id)
    for task in mission.task_set.all():
        # don't copy over final reports
        if task.is_final_or_post():
            continue
        log("Copying task", task)
        old_key = task.pk
        task.mission = new_mission
        task.extras.pop("errors", "")
        if task.requires_llm_response():
            task.status = TaskStatus.CREATED
            task.response = ""
        task.pk = None
        if old_key in new_prompts:
            task.prompt = new_prompts[old_key]
        task.save()
        key_changes[old_key] = task.pk
    for task in new_mission.task_set.all():
        if task.parent_id:
            task.parent_id = key_changes[task.parent_id]
            task.save()
    return new_mission.id


def llm_evaluate_completion(mission):
    problems = []
    if mission.is_test():
        return problems
    client = OpenAI()
    prompt = get_prompt_from_github("evaluate_report")
    completion = client.chat.completions.create(
        model=EVALUATION_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt + mission.response,
            },
        ],
        response_format={"type": "json_object"},
    )
    response_json = completion.choices[0].message.content
    response = json.loads(response_json)
    if response.get("incomplete"):
        mission.extras["incomplete"] = "true"
        mission.save()
        problems = [
            {
                "name": "LLM completeness evaluation",
                "problem": response.get("reason", "n/a"),
            }
        ]
    mission.extras["llm_says_completed"] = "true"
    mission.extras["llm_completeness_reason"] = response.get("reason", "n/a")
    return problems


def email_mission(mission_id, email, bcc_ops=False):
    try:
        log("Preparing email")
        mission = Mission.objects.get(id=mission_id)
        if mission.status != Mission.MissionStatus.COMPLETE:
            raise Exception("Mission not finished")
        md_text = mission.mission_report()
        md_text += "\n\n---\n\n## Report Sources\n\n"
        for source in mission.sources_with_links():
            md_text += "\n- [%s](%s)" % (source["name"], source["link"])

        log("About to send mission email")
        email = EmailMultiAlternatives(
            from_email=settings.DEFAULT_FROM_EMAIL,
            reply_to=[settings.REPLY_TO_EMAIL],
            bcc=[settings.NOTIFICATION_EMAIL] if bcc_ops else None,
            to=[email],
            subject="[YamLLMs] %s" % mission.name,
            body=md_text,
        )
        # render the external HTML template with the MD-generated HTML content
        context = {"raw_md": md_text, "mission": mission}
        full_html = render_to_string("email-report.html", context)
        email.attach_alternative(full_html, "text/html")
        email.send(fail_silently=settings.DEBUG)
        log("sent")

    except Exception as ex:
        log("Failed to send mail", ex)
        if not settings.DEBUG:
            raise ex


def get_trending_repos(window):
    trending_url = "https://github.com/trending?since=%s" % window
    req = requests.get(trending_url, SCRAPE_HEADERS)
    source = req.text
    soup = BeautifulSoup(source, "html.parser")
    articles = soup.find_all("article")
    repos = {}
    for article in articles:
        h2 = article.find("h2")
        repo = h2.text.strip().replace(" ", "").replace("\n", "")
        nextp = h2.find_next("p")
        if nextp:
            desc = nextp.text.strip()
            repos[repo] = desc
    return repos


def get_random_repo(care=False):
    selected = None
    repos = get_trending_repos("daily")
    if not repos:
        repos = get_trending_repos("weekly")

    if care:
        for repo in repos.keys():
            mission_info = MissionInfo.objects.get(name=GENERIC_MISSION)
            existing = Mission.objects.filter(
                flags__github=repo,
                mission_info=mission_info,
                created_at__gte=datetime.datetime.now() - datetime.timedelta(days=14),
            )
            if existing.count() > 0:
                log("Already reported on %s this fortnight" % repo)
                continue
            if "LLM" in repos[repo]:
                selected = repo
                break
            if "AI" in repos[repo]:
                selected = repo
                break
            if "API" in repos[repo]:
                selected = repo
                break

    if not selected:
        keys = list(repos.keys())
        selected = keys[random.randrange(len(keys))]

    return selected


def latest_missions_for_repos(task):
    repos = [r.replace(GITHUB_PREFIX, "") for r in task.depends_on_urls]
    missions = []
    for repo in repos:
        mission = (
            Mission.objects.filter(
                flags__github=repo,
                visibility=Visibility.PUBLIC,
                status=Mission.MissionStatus.COMPLETE,
            )
            .order_by("-created_at")
            .first()
        )
        if mission:
            missions.append(mission)
    return missions


def get_customer_missions_since(task):
    customer = task.get_customer()
    if not customer:
        return Mission.objects.none()
    since = datetime.datetime.now() - timedelta(days=task.cadence_days())
    return (
        Mission.objects.filter(mission_info__in=customer.missioninfo_set.all())
        .filter(created_at__gte=since)
        .filter(status=Mission.MissionStatus.COMPLETE)
        .order_by("-created_at")
    )


def evaluate_task(task):
    eval_categories = [
        TaskCategory.LLM_REPORT,
        TaskCategory.FINALIZE_MISSION,
    ]
    if task.category not in eval_categories:
        return None

    if task.flags.get("data_check") == "true":
        fact_list = Task.objects.create(
            mission=task.mission,
            name="List facts from report: %s" % task.name,
            category=TaskCategory.LLM_EVALUATION,
            url=REPORT_FACT_LIST_URL,
            parent=task,
        )
        data_check = Task.objects.create(
            mission=task.mission,
            name="Data check: %s" % task.name,
            category=TaskCategory.LLM_EVALUATION,
            url=DATA_CHECK_URL,
            parent=fact_list,
            flags={"max_reruns": 1},
        )
        return data_check

    if task.mission.flags.get("general_eval") == "true":
        return Task.objects.create(
            llm=TEST_MODEL_CLAUDE if task.is_test() else CLAUDE_HAIKU,
            mission=task.mission,
            name="Evaluate %s" % task.name,
            category=TaskCategory.LLM_EVALUATION,
            url=GENERAL_EVAL_URL,
            parent=task,
        )


# do internal evaluation of a mission and its tasks, and LLM evaluation of obvious incompleteness
def evaluate_mission(mission):
    log("Evaluating", mission)
    mission_info = mission.mission_info
    problems = []
    # first, just check for task errors
    problems += [evaluate_task_errors(t) for t in mission.task_set.all()]
    if mission.status == Mission.MissionStatus.CREATED:
        problems += [{"name": "%s" % mission, "problem": "Mission not started"}]
    if mission.status == Mission.MissionStatus.IN_PROCESS:
        problems += [{"name": "%s" % mission, "problem": "Mission not finished"}]
    if mission.status == Mission.MissionStatus.BLOCKED:
        problems += [{"name": "%s" % mission, "problem": "Mission blocked"}]
    if mission.status == Mission.MissionStatus.FAILED:
        problems += [{"name": "%s" % mission, "problem": "Mission failed"}]
    if mission.visibility == Visibility.BLOCKED:
        problems += [{"name": "%s" % mission, "problem": "Mission hidden"}]
    report_tasks = mission.sub_report_tasks()
    problems += [report_problems("%s" % t, t.response) for t in report_tasks]
    problems = [e for e in problems if e]

    evaluation = MissionEvaluation.objects.create(
        name=mission.name,
        mission=mission,
        errors={"problems": problems},
        extras={
            "customer": mission_info.customer_id if mission_info else None,
            "mission_id": mission.id,
            "mission_template": mission.mission_info_id,
            "mission_name": mission.name,
            "mission_repo": mission.get_repo(),
            "mission_llm": mission.get_llm(),
            "mission_created": mission.created_at.isoformat(),
            "mission_prompt": mission.prompt,
            "mission_response": mission.response,
        },
    )

    try:
        problems += llm_evaluate_completion(mission)
        evaluation.errors = {"problems": problems}
        evaluation.save()
    except Exception as ex:
        log("Could not perform LLM evaluation", ex)

    mission.extras["evaluated"] = "true"
    mission.save()

    if problems:
        log("Problems found:", problems)
        root = BASE_PREFIX
        text = f"[Evals]({root}/staff/evals/{mission.id})\n"
        text += f"[{mission.name}]({root}/reports/%s){mission.id}"
        html = f"<html><body><h1>Problems with {mission.name}</h1>\n"
        html += "<ul>"
        html += "".join(["<li>%s</li>\n" % p["problem"] for p in problems])
        html += "</ul>"
        html += f"<p><a href='{root}/staff/errors'>View Latest Error List</a></p>"
        html += f"<p><a href='{root}/staff/evals/{mission.id}/'>View Evals</a></p>"
        html += f"<p><a href='{root}/running/{mission.id}/'>View Run</a></p>"
        html += f"<p><a href='{root}/reports/{mission.id}/'>View Report</a></p>"
        html += "</body></html>"

        email_ops(
            subject="[YamLLMs] %s" % mission.name,
            body=text,
            html=html,
            fail_silently=False,
        )

    return evaluation


def report_problems(name, report):
    if not report:
        return {"name": name, "problem": "No report: %s" % name}
    # the LLM evaluation tasks take care of more sophisticated analysis


def evaluate_task_errors(task):
    errors = task.extras.get("errors", "")
    if errors:
        return {"name": "%s" % task, "problem": "Errors: %s" % errors}
    # the LLM evaluation tasks take care of more sophisticated analysis


def active_workers():
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    if url.startswith("rediss://"):
        url = url + "?ssl_cert_reqs=none"
    r = Redis.from_url(url)
    workers = Worker.all(connection=r)
    return [w for w in workers if w.state != "?"]


def queue_length():
    queue = django_rq.get_queue()
    return len(queue)
