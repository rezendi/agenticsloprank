import time

from django_rq import job  # type: ignore

from .admin_jobs import evaluate_mission, evaluate_task
from .models import *
from .plugins.text_links import *
from .run import get_customer_missions_since, run
from .util import *


@job("default", timeout=6000)
def fulfil_mission(mission_id, copy_mission=None):
    mission = Mission.objects.get(id=mission_id)
    log("Fulfilling mission", mission)
    mission_info = mission.mission_info

    # for dev and 'generic' mission templates, we need to set the name
    mission.name = correct_name(mission)

    # some missions have dependencies on a previous data mission
    if mission_info:
        if mission_info.depends_on and not mission.depends_on:
            mission.depends_on = mission_info.depends_on.latest_mission()
        data = mission.depends_on
        if mission_info.depends_on and not data:
            log("Mission dependency not found", mission_info.depends_on)
            return
        if data and data.status != Mission.MissionStatus.COMPLETE:
            log("Mission dependency not completed", data)
            return

    mission.status = Mission.MissionStatus.IN_PROCESS
    mission.save()

    if mission.task_set.count() > 0:  # rerunning
        for task in mission.reject_on_rerun_tasks():  # always rerun finalization tasks
            task.status = TaskStatus.REJECTED
            task.save()
    else:  # first run
        if not mission_info:
            raise Exception("Cannot create base tasks without a mission info")
        for ti in mission_info.task_templates():
            ti.create_task(mission)
        for task in mission.task_set.all():
            if task.task_info.parent:
                parent_id = task.task_info.parent_id
                task.parent = mission.task_set.filter(task_info_id=parent_id).first()
                if data and not task.parent:
                    task.parent = data.task_set.filter(task_info_id=parent_id).first()
            if task.category == TaskCategory.API and copy_mission:
                original = copy_mission.task_set.filter(
                    category=TaskCategory.API, url=task.url
                ).first()
                if original:
                    task.response = original.response
                    task.status = TaskStatus.COMPLETE
                    task.save()
            task.save()
        log("Created base tasks", mission.task_set.all())
        for task in mission.task_set.all():
            create_child_tasks_for(task)

    for task in mission.tasks_to_run():
        run_task(task.id)
    finalize_mission(mission.id)
    log("Mission completed", mission)


def create_child_tasks_for(task):
    # for now, this just creates report tasks
    # we do create other tasks in individual invocation methods
    # those should arguably be moved here
    if task.requires_report():
        if not [t for t in task.child_tasks() if t.is_llm_report()]:
            report_task = TaskInfo.create_report_task(task)
            log("Created report task", report_task)


@job("default", timeout=3000)
def run_task(task_id, iteration=0):
    start = int(time.time())
    task = Task.objects.get(id=task_id)
    if task.status == TaskStatus.COMPLETE:
        log("Task already complete", task)
        return task

    if iteration > 10:  # arbitrary paranoia
        task.add_error("Too many recursive iterations")
        task.status = TaskStatus.FAILED
        task.save()
        return task

    # note we only require non-empty for the direct parent task, not all prereqs
    if task.parent and task.parent.status == TaskStatus.EMPTY:
        log("Empty prerequisite, bailing out", task.parent)
        task.status = TaskStatus.EMPTY
        task.save()
        return task

    task.extras.pop("errors", "")  # reset errors
    log("Performing task %s" % task, start)
    prerequisites = task.prerequisite_tasks()
    log("prereqs", prerequisites)
    for prereq in prerequisites:
        # avoid infinite loops
        predep = prereq.parent
        if prereq.id == task.id or predep and predep.id == task.id:  # paranoia
            continue
        # a chain of three tasks with identical URLs counts as a loop
        if predep and predep.url == task.url and prereq.url == task.url:  # paranoiia
            continue
        if prereq.status == TaskStatus.CREATED:
            log("Found unstarted prerequisite, running", prereq)
            run_task(prereq.id, iteration + 1)
        elif prereq.status in [TaskStatus.FAILED, TaskStatus.IN_PROCESS]:
            return log("Found incomplete prerequisite, bailing out", prereq)
    task.status = TaskStatus.IN_PROCESS
    task.rendered = ""
    task.save()

    run(task)  # in run.py
    post_process(task)

    # just make sure this all happens sequentially, and go easy on the external APIs
    if not task.is_test():
        time.sleep(1)
    return task


# If we're creating a chain of time-windowed tasks, we need to create the next one
# time-windowed tasks must have a task info with "window_start" and "window_final"
def create_window_task_if_necessary(task):
    if not task.is_data() or not task.is_fixed_window():
        return None
    end = task.window_end()
    if end >= task.window_final():
        log("Done with window tasks")
        return None

    # ensure we avoid an infinite chain
    # how many tasks have been created from this template?
    count = task.task_info.task_set.filter(mission=task.mission).count()
    if count > MAX_WINDOW_TASKS:
        log("Too many window tasks already, bailing out", task)
        return None

    new_end = end + timedelta(days=task.cadence_days())
    if new_end > task.window_final():
        new_end = task.window_final()
    new_task = task.task_info.create_task(task.mission)
    new_task.parent = task.parent
    new_task.flags["window_start"] = end.isoformat()
    new_task.flags["window_end"] = new_end.isoformat()
    new_task.flags["window_final"] = task.window_final().isoformat()
    new_task.name = (task.name or "").split(" over")[0]
    new_task.name += f" over {new_task.window_days()} days ending {new_end.isoformat().split(' ')[0]}"
    new_task.save()
    return new_task


def post_process(task):
    task.save()
    if task.status == TaskStatus.COMPLETE:
        fix_titles(task)
        eval = evaluate_task(task)
        if eval:
            run_task(eval.id)
        create_child_tasks_for(task)
        for child in task.child_tasks().filter(status=TaskStatus.CREATED):
            run_task(child.id)
    # if it's a report-on-reports, link to individual reports
    if task.category == TaskCategory.FINALIZE_MISSION:
        if task.parent and task.parent.category == TaskCategory.AGGREGATE_REPORTS:
            missions = get_customer_missions_since(task)
            link_to_leaf_reports(task, missions)
    if task.is_fixed_window():
        new_task = create_window_task_if_necessary(task)
        if new_task:
            run_task(new_task.id)
    task.save()


def assemble_final_tasks(mission):
    existing = mission.task_set.all()
    final = existing.filter(category=TaskCategory.FINALIZE_MISSION).filter(
        status__gte=TaskStatus.CREATED
    )
    if final.count() > 0:
        return final

    # not necessary but conceptually nice to have a prerequisite
    exclude = [
        TaskCategory.AGENT_TASK,
        TaskCategory.FINALIZE_MISSION,
        TaskCategory.POST_MISSION,
    ]
    prereqs = existing.filter(status=TaskStatus.COMPLETE).exclude(category__in=exclude)

    # if no final tasks exist, by default, we create a final report-of-reports task
    if mission.flags.get("no_new_final") != "true":
        log("Creating final task")
        final = []
        # never use gpt-4o-mini for final tasks
        llm = GPT_4O if mission.llm == GPT_4O_MINI else mission.get_llm()
        task = Task.objects.create(
            mission=mission,
            parent=prereqs.last(),
            llm=llm,
            status=TaskStatus.CREATED,
            category=TaskCategory.FINALIZE_MISSION,
            visibility=mission.visibility,
            name="Final Report Task",
            prompt=mission.get_final_prompt(),
            order=9999,  # just to put them at the end
        )
        return [task]
    return []


# Run the final tasks, one per mission variant, to generate the final reports
def finalize_mission(mission_id):
    mission = Mission.objects.get(id=mission_id)
    log("Finalizing", mission)

    # in general we onlyl expect one final task, but support multiple for e.g. variants
    final_tasks = list(assemble_final_tasks(mission))
    final_input_tasks = list(mission.final_input_tasks())
    if final_tasks and not final_input_tasks:
        raise Exception("No final input tasks found for mission %s" % mission)

    for task in final_tasks:
        run_task(task.id)
        task.refresh_from_db()

    mission.response = FINAL_TASK_DIVIDER.join([t.response or "" for t in final_tasks])
    mission.status = Mission.MissionStatus.COMPLETE
    if mission.mission_info and mission.mission_info.flags.get("autoblock") == "true":
        mission.visibility = Visibility.BLOCKED
    mission.rendered = ""
    mission.save()

    # post-mission actions
    evaluate_mission(mission)
    add_email_mission_task(mission)  # convenience
    posts = mission.task_set.filter(category=TaskCategory.POST_MISSION)
    for post in posts:
        run_task(post.id)


def add_email_mission_task(mission):
    if mission.flags.get("email_to"):
        existing = mission.task_set.filter(
            category=TaskCategory.POST_MISSION, url=EMAIL_TASK_URL
        )
        if existing.exists():
            return
        Task.objects.create(
            mission=mission,
            name="Email Final Report",
            category=TaskCategory.POST_MISSION,
            url=EMAIL_TASK_URL,
            order=1000,
        )
