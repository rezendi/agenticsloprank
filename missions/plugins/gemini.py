import os
import google.generativeai as genai
from google.generativeai.generative_models import GenerativeModel
from ..prompts import get_prompt_from_github
from ..util import *
from missions import plugins

# https://cloud.google.com/docs/authentication/provide-credentials-adc#how-to


@plugins.hookimpl
def chat_llm(task, input, tool_key):
    if task.get_llm() in GEMINI_MODELS:
        return chat_gemini(task, input)
    return None


@plugins.hookimpl
def ask_llm(task):
    log("Checking gemini")
    return ask_gemini(task)


def get_gemini(model):
    GOOGLE_AI_TOKEN = os.getenv("GOOGLE_AI_TOKEN")
    genai.configure(api_key=GOOGLE_AI_TOKEN)
    # log("models", list(genai.list_models()))
    return genai.GenerativeModel(model)


def chat_gemini(task, prompt):
    prompt = (prompt or "").strip()
    sized_prompt = get_sized_prompt(task, prompt)
    final_prompt = (task.prompt or "").strip() + "\n\n" + sized_prompt
    task.extras["system_prompt"] = task.prompt
    task.extras["final_prompt"] = final_prompt

    gemini = get_gemini(task.get_llm())
    log("Asking Gemini, prompt length", len(sized_prompt))
    model = GenerativeModel(task.get_llm())
    log("token length", model.count_tokens(sized_prompt))
    response = gemini.generate_content(final_prompt)
    log("gemini response", response.text)
    return response.text


# Accumulate all of the mission's fetch tasks, then ask with prompt and final report
def ask_gemini(task, input_tasks=[]):

    # by default, look at all of a mission's fetch tasks
    if not input_tasks:
        input_tasks = task.mission.key_context_tasks() + task.mission.fetch_tasks()

    log("Gemini input tasks", input_tasks)
    input_data = (task.prompt or "") + "\n\n---\n\n"
    if task.parent or task.mission.followup_tasks():
        if task.is_test():
            input_data = "Test prompt %s"
        else:
            input_data += get_prompt_from_github("gemini_followup_preamble")
        report = task.parent.response if task.parent else "No report available."
        input_data = input_data % report
        input_data += "\n\n---\n\n"
        questions = "No questions yet."
        if task.mission.followup_tasks():
            questions = "\n\n\n".join(
                [
                    f"### Question\n{t.extras.get('followup_question')}\n\n### Answer\n{t.response}"
                    for t in task.mission.followup_tasks()
                    if t.is_complete()
                ]
            )
        input_data += questions

    if not task.is_test():
        input_data += get_prompt_from_github("gemini_preamble")
    input_data += "\nConcatenated Datasets\n---------------------\n\n"
    texts = []
    for idx, t in enumerate(input_tasks):
        texts += [f"\n# Dataset {idx+1}\n\n## {t.name}\n\n{t.response}"]
    text = "\n\n---\n\n".join(texts)
    task.llm = GEMINI_1_5_PRO
    task.save()
    while is_too_long(input_data + text, task.get_llm()):
        lengths = [len(t) for t in texts]
        max_len = max(lengths)
        max_idx = lengths.index(max_len)
        long_text = texts[max_idx]
        texts[max_idx] = long_text[: len(long_text) // 2] + "\n\n(truncated)\n..."
        text = "\n\n---\n\n".join(texts)

    sized_prompt = get_sized_prompt(task, input_data + text)
    task.extras["system_prompt"] = task.prompt
    task.extras["final_prompt"] = sized_prompt
    task.extras["final_prompt_length"] = len(sized_prompt)

    if task.is_test():
        return "Test Gemini response"

    gemini = get_gemini(task.get_llm())
    log("Asking Gemini, prompt length", len(sized_prompt))
    response = gemini.generate_content(sized_prompt, request_options={"timeout": 600})
    log("gemini response", response.text)
    return response.text
