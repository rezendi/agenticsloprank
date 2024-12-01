import json, openai
from .github import get_gh_repo, get_gh_file, get_gh_pr
from ..prompts import get_prompt_from_github
from ..util import *
from ..models import Task, TaskCategory, Reporting
from missions import plugins


# don't let individual source files overwhelm the context window
MAX_SOURCE_FILE_LENGTH = 12288


@plugins.hookimpl
def run_llm_decision(task):
    if task.url.startswith(GITHUB_PREFIX) or task.url.startswith(AZURE_API):
        create_fetch_tasks(task)
        return task
    return None


@plugins.hookimpl
def run_fetch_for_llm(task):
    if task.parent and task.parent.url:
        if task.parent.url.endswith("/files"):
            run_llm_file_fetch(task)
            return task
        elif task.parent.url.endswith("/pulls"):
            run_llm_pr_fetch(task)
            return task
    return None


# arguably move fetch task creation to create_child_tasks in hub2
def create_fetch_tasks(task):
    log("Creating fetch tasks")
    # right now only two types, files or PRs, will need more elegance eventually
    fetch_files = task.url.endswith("files")

    if fetch_files:  # simple
        new_task = create_fetch_task(task, "files")
        log("Created file fetch task", new_task)

    else:  # create a task for each PR analysis request
        task.response = get_json_from(task)
        pr_list = json.loads(task.response)
        if isinstance(pr_list, dict):  # sometimes we just get a dict
            if len(pr_list) == 1:
                key = list(pr_list.keys())[0]
                pr_list = pr_list[key]
            else:
                pr_list = [pr_list]
        for pr in pr_list:
            number = pr["number"]
            if isinstance(number, str):
                number = number.replace("#", "").replace("PR", "").strip()
            if number:
                url = task.url + "/%s" % id
                if not task.mission.task_set.filter(url=url).exists():
                    new_task = create_fetch_task(task, number)
                    log("Created PR fetch task", new_task)

            # by default, only create one PR task per decision task, two is too noisy
            if not task.extras.get("assess_multiple_prs", "false") == "true":
                break


# arguably move fetch task creation to create_child_tasks in hub2?
def create_fetch_task(task, id):
    name = "PR %s" % id if id != "files" else "Files"
    new_task = Task.objects.create(
        mission=task.mission,
        parent=task,
        llm=task.llm,
        url=task.url if id == "files" else task.url + "/%s" % id,
        order=task.order,
        visibility=task.visibility,
        reporting=task.reporting,
        category=TaskCategory.FETCH_FOR_LLM,
        name="Fetch %s For Assessment" % name,
    )

    if task.is_test():
        new_task.prompt = "Test prompt"
    elif task.reporting == Reporting.ALWAYS_REPORT:
        if id == "files":
            new_task.prompt = get_prompt_from_github("assess-source")
        else:
            new_task.prompt = get_prompt_from_github("assess-pr")

    for val in [
        "github",
        "openai_run_id",
        "openai_tool_call_id",
    ]:
        if val in task.extras:
            new_task.extras[val] = task.extras.get(val)

    new_task.save()
    return new_task


def run_llm_file_fetch(task):
    response = get_json_from(task.parent.response)
    file_list = json.loads(response)
    if isinstance(file_list, dict):  # sometimes we just get a dict
        if len(file_list) == 1:
            key = list(file_list.keys())[0]
            file_list = file_list[key]
        else:
            file_list = [file_list]
    log("file_list", file_list)
    fetched_filenames = []
    repo = get_gh_repo(task)

    task.response = ""
    for finfo in file_list:
        key = "path" if "path" in finfo else "url" if "url" in finfo else "name"
        path = finfo.get(key)
        filename = path.replace(GITHUB_PREFIX, "")
        if path.startswith("http") and not path.startswith(GITHUB_PREFIX):
            log("Cannot fetch files from", path)
            continue

        try:
            log(f"Fetching file {filename} from {path}")
            filedata = get_gh_file(repo, finfo)
            fetched_filenames.append(finfo)
            log("fetched file with lines", len(filedata.splitlines()))
        except Exception as ex:
            log("could not fetch file", path, "due to", ex)
            continue

        # append the file content to the prompt
        content = "\n\n" + get_file_intro(filename, filedata)
        lines = filedata.splitlines()
        if len(lines) > 1024:
            log("truncating source file", filename)
            truncated = "\n".join(lines[:1024])
            truncated += (
                "\n\n[File truncated after 1024 lines to fit in context window]\n"
            )
            task.response += content + truncated
        else:
            task.response += content + filedata

    # all files have been uploaded
    task.prompt = "" if not task.prompt else task.prompt
    task.prompt += "\n" + "\n".join(["%s" % f for f in fetched_filenames])
    task.save()


def run_llm_pr_fetch(task):
    repo = get_gh_repo(task)
    number = int(task.url.split("/")[-1])
    get_gh_pr(task, repo, number)
