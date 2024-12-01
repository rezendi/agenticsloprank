import time, traceback
from django_rq import job
from django.conf import settings
from missions.apps import get_plugin_manager
from .models import TaskStatus, TaskCategory, Task, Mission
from .admin_jobs import *
from .util import *

MAX_RERUNS = 3


@job("default", timeout=3000)
def run(task):
    start = int(time.time())
    try:
        match task.category:
            # collect-data tasks
            case TaskCategory.SCRAPE:
                run_scrape(task)
            case TaskCategory.API:
                run_api(task)
            case TaskCategory.FILTER:
                run_filter(task)
            # Simple / one-off LLM-based tasks
            case TaskCategory.LLM_REPORT:  # report on a single chain of data sources
                run_llm_report(task)
            case TaskCategory.LLM_RATING:  # rate an entity such as a pull request
                run_llm_rating(task)
            case TaskCategory.LLM_DECISION:  # ask LLM what data to fetch
                run_llm_decision(task)
            case TaskCategory.FETCH_FOR_LLM:  # fetch data for LLM analysis
                run_fetch_for_llm(task)
            # Aggregate tasks across multiple missions
            case TaskCategory.AGGREGATE_REPORTS:
                aggregate_reports(task)
            # Recursive LLM-based agent tasks
            case TaskCategory.AGENT_TASK:
                run_agent(task)
            # Programmatic quantified reports
            case TaskCategory.QUANTIFIED_REPORT:
                run_quantified_report(task)
            # Post-report tasks
            case TaskCategory.POST_MISSION:  # run a task after the main report
                run_post_mission(task)
            case TaskCategory.LLM_QUESTION:  # followup question from a user
                run_llm_question(task)
            case TaskCategory.LLM_EVALUATION:  # evaluate a previous LLM response
                run_llm_evaluation(task)
            case TaskCategory.FINALIZE_MISSION:  # final report for a mission
                run_final_report(task)
            # Other tasks: currently, data tasks populated by a call to our API
            case TaskCategory.OTHER:
                run_other(task)
            case _:
                raise Exception("Task category not yet implemented", task)
    except Exception as ex:
        log("Task error at %s seconds" % int(time.time() - start))
        traceback.print_exc()
        task.status = TaskStatus.FAILED
        task.add_error(ex)

    # mark empty tasks as empty unless already marked complete or failed
    if not task.response and not task.structured_data:
        if task.status not in [TaskStatus.FAILED, TaskStatus.COMPLETE]:
            task.status = TaskStatus.EMPTY

    log("Task complete", task, "%s seconds" % int(time.time() - start))
    task.extras["time_taken"] = f"{int(time.time())} elapsed {int(time.time()) - start}"
    # mark as complete if not marked as failed or empty
    task.mark_complete() if task.status == TaskStatus.IN_PROCESS else task.save()


def run_scrape(task):
    pm = get_plugin_manager()
    completion = pm.hook.run_scrape(task=task)
    if not completion:
        raise Exception("No implementation for scrape task available: %s" % task)


def run_api(task):
    if task.is_test():
        task.response = "Test API response to %s" % task.name
        return
    pm = get_plugin_manager()
    completion = pm.hook.run_api(task=task)
    if not completion:
        raise Exception("No implementation for API task is available: %s" % task)


# Actually run an LLM report based on data from previous task(s)
def run_llm_report(task):
    input_data = task.assemble_prerequisite_inputs()

    if task.is_vision():
        show_llm(task, input_data)
        return

    # for time series analysis, the prompt must have two variables
    if task.is_time_series() and not task.is_key_context():
        previous = task.previous()
        days = get_days_between(task.created_at, previous.created_at)
        prompt = "Test %s %s" if task.is_test() else get_prompt_from_github("deltas")
        previous_response = previous.response or "" if previous else ""
        input_data = prompt % (days, input_data) + previous_response
        log("Time series analysis, days:", days)
    else:
        log("Not a time series task")

    if task.mission.flags.get("append_date_to_prompt") == "true":
        input_data += (
            "\n\nRender your analysis bearing in mind that today's date is %s."
            % task.created_at.strftime("%Y-%m-%d")
        )

    task.response = chat_llm(task, input_data)


# Chat with an LLM using the appropriate provided plugin if any
def chat_llm(task, input, tool_key=""):
    if not task.prompt:
        log("No prompt for task", task)
        return ""
    if tool_key:
        task.extras["tool_key"] = tool_key
    if task.is_test():
        log("Not chatting, using test model")
        task.response = '{"test":"true"}' if tool_key else "Test TDTest response"
        return task.response

    pm = get_plugin_manager()
    completion = pm.hook.chat_llm(task=task, input=input, tool_key=tool_key)
    if not completion:
        raise Exception("No implementation for LLM chat available: %s" % task)
    return completion


def show_llm(task, input):
    if not task.prompt:
        log("No prompt for task", task)
        return ""
    pm = get_plugin_manager()
    completion = pm.hook.show_llm(task=task, input=input)
    if not completion:
        raise Exception("No implementation for LLM image available: %s" % task)


# Filter data from a previous mission for this particular task
def run_filter(task):
    data_mission = task.mission.depends_on
    if not data_mission:
        raise Exception("No data mission found for filter task %s" % task)

    data_tasks = data_mission.task_set.filter(status=TaskStatus.COMPLETE)
    pm = get_plugin_manager()
    completion = pm.hook.filter_from_data_tasks(task=task, data_tasks=data_tasks)
    if not completion:
        raise Exception("No implementation for filter task: %s" % task)


# ask the LLM what data to fetch for subsequent analysis
def run_llm_decision(task):
    input_data = task.assemble_prerequisite_inputs()
    if not input_data:
        task.response = ""
        task.status = TaskStatus.EMPTY
        task.save()
    else:
        tool_key = (task.url or "").split("/")[-1]
        task.response = chat_llm(task, input_data, tool_key=tool_key)
        task.mark_complete()

    # for now, base fetch creation on the URL because that can include
    # both the source (e.g. github) and the target (e.g. pulls/files)
    # possible TODO something more elegant
    if task.response and task.status == TaskStatus.COMPLETE:
        pm = get_plugin_manager()
        completion = pm.hook.run_llm_decision(task=task)
        if not completion:
            raise Exception("No implementation for LLM decision available: %s" % task)


# Fetch data requested by the LLM
def run_fetch_for_llm(task):
    if not task.parent:
        raise Exception("No predecessor task found for LLM fetch %s" % task)
    if task.url and task.url.startswith(GITHUB_PREFIX + "test"):
        log("Running test fetch for LLM")
        task.response = '{"type":"test"}'
        task.save()
        return task

    # ensure we haven't already run this fetch
    if (
        task.mission.task_set.filter(category=TaskCategory.FETCH_FOR_LLM)
        .filter(url=task.url)
        .count()
    ) > 1:
        log("Already fetched", task.url)
        return

    pm = get_plugin_manager()
    completion = pm.hook.run_fetch_for_llm(task=task)
    if not completion:
        raise Exception("No implementation for LLM fetch available: %s" % task)


# Rate the quality an entity - a PR, an issue, etc. - from 1 to 5 based on our report and its raw data
# currently only PRs are supported, other entities will need their own plugins
def run_llm_rating(task):
    pm = get_plugin_manager()
    completion = pm.hook.run_rating(task=task)
    if not completion:
        raise Exception("No implementation for rating task available: %s" % task)


# a "report aggregator" task that aggregates/summarizes multiple tasks across multiple missions
def aggregate_reports(task):
    # get all the missions for this customer since the given cadence
    # for each of those missions, get the corresponding tasks and aggregate their responses
    log("aggregating tasks since", task.cadence_days())
    missions = get_customer_missions_since(task).exclude(id=task.mission_id)
    mission_ids = [m.id for m in missions]
    log("initial mission_ids to aggregate", mission_ids)
    tasks = Task.objects.filter(mission_id__in=mission_ids).filter(
        status=TaskStatus.COMPLETE
    )
    log("initial tasks to aggregate", tasks)

    # exclude any mission marked as previous to a more recent mission - we only want the latest
    previous_ids = [m.previous_id for m in missions if m.previous_id]
    log("missions marked as previous", previous_ids)
    tasks = tasks.exclude(mission_id__in=previous_ids)

    if task.flags.get("aggregate_final_reports") == "true":
        tasks = tasks.filter(category=TaskCategory.FINALIZE_MISSION)
    else:
        # optionally aggregate by task/parent URL, have a plugin handle it
        url_key = task.url.split("/")[-1] if task.url else None
        if url_key:
            pm = get_plugin_manager()
            completion = pm.hook.run_aggregate(task=task, tasks=tasks, url_key=url_key)
            if completion:
                return

        # otherwise default to aggregating LLM reports
        tasks = tasks.filter(category=TaskCategory.LLM_REPORT)
        log("potential reports to aggregate", tasks)
        if url_key:
            # note task parents must have correct URL suffix to be aggregated in turn
            tasks = tasks.filter(parent__url__endswith=url_key)

    tasks = tasks.exclude(parent__category=TaskCategory.AGGREGATE_REPORTS)
    tasks = tasks.order_by("mission_id", "created_at")
    log("aggregate tasks", tasks)

    # concatenate the responses
    r = ""
    mission_id = None
    for t in tasks:
        if t.mission_id != mission_id:
            mission_id = t.mission_id
            r += f"\n---\n## {t.mission.name}\n\n"
        r += f"### {t.name}\n\n"
        r += t.response or ""
    task.response = r

    if task.url and task.url.endswith("commits"):
        all_devs = concatenate_dev_data(tasks)
        task.structured_data["devs"] = all_devs
        task.save()

    # don't launch a report - the assumption is this is the last task in a mission
    # without LLM reports, so the mission's "final report" task will handle that


# Run a seris of agent tasks to perform in-depth, recursive fetching/analysis.
# Keep running agent tasks until the agent returns None, indicating it's done
def run_agent(task):
    pm = get_plugin_manager()
    next_task = pm.hook.run_agent(task=task)
    if next_task:
        run(next_task)


# Do math / generate a table programmatically, since LLMs are bad at this
def run_quantified_report(task):
    pm = get_plugin_manager()
    completion = pm.hook.quantify(task=task)
    if not completion:
        raise Exception("No implementation for quantify task: %s" % task)


# Run a task after the main body of the mission, e.g. email the report to the customer
def run_post_mission(task):
    suffix = (task.url or "").split("/")[-1]
    # email the final report to customer(s)
    if suffix == "email":
        if (
            task.mission.status == Mission.MissionStatus.COMPLETE
            and task.mission.visibility != Visibility.BLOCKED
        ):
            email_to = task.mission.flags.get("email_to", [])
            bcc_ops = "Demo" in (task.mission.name or "")
            bcc_ops = bcc_ops or "Default" in (task.mission.name or "")
            for email in email_to:
                email_mission(task.mission.id, email, bcc_ops)
        else:
            raise Exception("Mission incomplete or blocked, not emailing report")

    if suffix == "webhook":
        mission = task.mission
        if (
            mission.status == Mission.MissionStatus.COMPLETE
            and mission.visibility != Visibility.BLOCKED
        ):
            markdown = mission.mission_report()
            html = ""  # TODO
            token = task.flags.get("webhook_token", mission.flags.get("webhook_token"))
            data = {
                "token": token,
                "report_url": BASE_PREFIX + "/reports/%s" % mission.id,
                "report_date": mission.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "markdown": markdown,
                "html": html,
            }
            url = task.flags.get("webhook_url") or mission.flags.get("webhook_url")
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, data=data, headers=headers)
            if response.status_code != 200:
                task.add_error(response.text, response.status_code)
                raise Exception("Webhook failed", task, response.text)
            task.structured_data["http_response"] = response.json()

    # summarize the report even further
    if suffix == "tldr":
        if not task.prompt:
            task.prompt = get_prompt_from_github(task.url)
        input_data = task.mission.response
        task.response = chat_llm(task, input_data)


# Ask an LLM a followup question from a user
def run_llm_question(task):
    if task.is_test():
        base_prompt = "Test followup prompt\n\n"
    else:
        base_prompt = get_prompt_from_github("followup")
    task.prompt = base_prompt + task.prompt
    task.save()
    pm = get_plugin_manager()
    task.response = pm.hook.ask_llm(task=task)
    if not task.response:
        raise Exception("No implementation for LLM question available: %s" % task)


# Evaluate factuality or quality of a previous LLM response
def run_llm_evaluation(task):
    if task.is_test():
        task.response = "Test eval response"
        return

    pm = get_plugin_manager()
    eval = pm.hook.run_eval(task=task)
    if not eval:
        raise Exception("No implementation for scrape task available: %s" % task)

    # can run a chain of evals on a single task
    eval.save()
    evaluated = eval.parent
    while evaluated and evaluated.category == TaskCategory.LLM_EVALUATION:
        evaluated = evaluated.parent

    # possible actions depending on eval response: reject previous task, rerun previous task, send email
    # this depends on the eval's structured data, which must match the structure here (and can include its own)
    # eval methodss can also take their own actions, of course
    email_to = None
    actions = eval.structured_data.get("eval_actions", "")
    if "reject" in actions:
        evaluated.status = TaskStatus.REJECTED
        evaluated.save()
    if "email" in actions:
        email_to = evaluated.get_email_re(default=settings.NOTIFICATION_EMAILS)
    if "rerun" in actions:
        max_iterations = max(
            evaluated.flags.get("max_reruns", 0),
            eval.flags.get("max_reruns", 0),
            MAX_RERUNS,
        )
        rerun_iterations = evaluated.extras.get("reruns", 0)
        if rerun_iterations < max_iterations:
            log("rerunning", evaluated)
            evaluated.extras["reruns"] = rerun_iterations + 1
            evaluated.prep_for_rerun()
            run.delay(evaluated)
        elif "email_after_reattempting" in actions:
            email_to = evaluated.get_email_re(default=settings.NOTIFICATION_EMAILS)

    if email_to:
        errors = eval.structured_data.get("errors", [])
        email_eval_failure(eval, evaluated, errors, email_to)


def run_final_report(task):
    input_tasks = list(task.mission.final_input_tasks())
    log("Input tasks", input_tasks)
    if task.depends_on_urls:
        input_tasks = task.aggregate_dependencies()
    inputs = [t.response or "" for t in input_tasks]
    prompt = "\n\n---\n".join(inputs)
    task.response = chat_llm(task, prompt)

    # don't overwrite in edge case of rerunning when many final tasks
    if not FINAL_TASK_DIVIDER in (task.mission.response or ""):
        task.mission.response = task.response
        task.mission.save()


# Currenty tihs indicates a prepopulated data task, like one generated by a call to our API
# so we simply no-op, let it be marked it as complete, and run a report if its settings call for that
# more complex API handling will be a separate category with its own methods
def run_other(task):
    pass
