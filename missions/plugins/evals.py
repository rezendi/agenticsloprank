from ..prompts import get_prompt_from_github
from missions.util import *
from missions.models import TaskCategory
from missions.run import chat_llm
from missions import plugins


@plugins.hookimpl
def run_eval(task):
    to_eval = task.parent
    if task.url == DATA_CHECK_URL:
        if not task.prompt:
            task.prompt = get_prompt_from_github("data-check")

        # get the task which is the raw data here
        source = to_eval.parent
        while source and source.category > TaskCategory.FILTER:
            source = source.parent

        to_eval.refresh_from_db()  # paranoia
        assertions = to_eval.response
        report_input = f"# Assertions\n\n{assertions}\n\n# Source Data\n\n{source}"
        task.response = chat_llm(task, report_input, tool_key="data_check")
        task.structured_data = json.loads(task.response)
        # generate readable report
        md = ""
        for assertion in task.structured_data.get("assertions", []):
            if assertion.get("factual") == True:
                md += f"### {assertion['assertion']}\n"
                md += f"{assertion['supported']} - supported by: {assertion['support']}\n\n"
        task.response = md

        factual_error = False
        factual_errors = []
        for assertion in task.structured_data.get("assertions", []):
            if assertion.get("factual") == True and assertion.get("supported") == False:
                factual_error = True
                factual_errors.append(assertion["assertion"])

        if factual_error:
            task.structured_data["eval_actions"] = {
                "reject": True,
                "rerun": True,
                "email_after_reattempting": True,
                "errors": factual_errors,
            }
        return task

    elif task.url == FACT_LIST_URL:
        report_input = to_eval.response
        if to_eval.category == TaskCategory.FINALIZE_MISSION:
            input_tasks = task.mission.final_input_tasks()
            texts = [t.response or "" for t in input_tasks]
            report_input = "\n\n---\n".join(texts)
        if not task.prompt:
            task.prompt = get_prompt_from_github("fact-list")
        task.response = chat_llm(task, report_input)
        return task

    # legacy evals
    elif task.url == GENERAL_EVAL_URL:
        if to_eval.category == TaskCategory.FINALIZE_MISSION:
            input_tasks = task.mission.final_input_tasks()
            texts = [t.response or "" for t in input_tasks]
            report_input = "\n\n---\n".join(texts)
        else:
            report_input = to_eval.assemble_prerequisite_inputs()
        task.prompt = get_prompt_from_github("eval-2")
        data_frame = get_prompt_from_github("eval-2-data")
        input = data_frame % (to_eval.response, report_input)
        task.response = chat_llm(task, input, tool_key="evaluate_report")
        return task
