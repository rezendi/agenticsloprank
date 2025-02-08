import os

from anthropic import Anthropic

from missions import plugins

from ..functions import get_openai_functions_for
from ..util import *

# https://cloud.google.com/docs/authentication/provide-credentials-adc#how-to

MAX_CLAUDE_TOKENS = 4096


@plugins.hookimpl
def chat_llm(task, input, tool_key):
    if task.get_llm() in CLAUDE_MODELS:
        if tool_key:
            return chat_claude_json(task, input, tool_key)
        else:
            return chat_claude(task, input)
    return None


def get_anthropic():
    client = Anthropic(
        # This is the default and can be omitted
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    return client


def chat_claude(task, input):
    input = (input or "").strip()
    task_prompt = (task.prompt or "").strip()
    sized_input = get_sized_prompt(task, input)
    final_prompt = (
        "<Instructions>\n"
        + task_prompt
        + "\n</Instructions>\n"
        + "\n<Information>\n"
        + sized_input
        + "\n</Information>\n"
    )
    task.extras["task_prompt"] = task_prompt
    task.extras["final_prompt"] = final_prompt
    log("final prompt length", len(final_prompt))

    anthropic = get_anthropic()
    message = anthropic.messages.create(
        max_tokens=MAX_CLAUDE_TOKENS,
        messages=[
            {
                "role": "user",
                "content": final_prompt,
            }
        ],
        model=task.get_llm(),
    )
    task.response = message.content[0].text
    return task.response


def chat_claude_json(task, input, tool_key):
    input = (input or "").strip()
    task_prompt = (task.prompt or "").strip()
    sized_input = get_sized_prompt(task, input)
    final_prompt = (
        "<Instructions>\n"
        + task_prompt
        + "\n</Instructions>\n"
        + "\n<Information>\n"
        + sized_input
        + "\n</Information>\n"
    )
    if tool_key:
        tools = get_openai_functions_for(tool_key)
        tool_prompt = "\n<OutputFormat/>"
        tool_prompt += "\nYour response MUST be in the form of a JSON object which exactly matches the following OpenAI Structured Output definition:\n"
        tool_prompt += "\n%s\n" % tools[0]
        tool_prompt = "\nAgain it MUST consist entirely of such a JSON object with no wrapper, prologue, epilogue, or other description. Do not nest keys; it MUST be a flat dictionary.\n"
        tool_prompt = "\n</OutputFormat/>"
        final_prompt += tool_prompt

    task.extras["task_prompt"] = task_prompt
    task.extras["final_prompt"] = final_prompt
    log("final JSON prompt length", len(final_prompt))

    anthropic = get_anthropic()
    message = anthropic.messages.create(
        max_tokens=MAX_CLAUDE_TOKENS,
        messages=[
            {
                "role": "user",
                "content": final_prompt,
            }
        ],
        model=task.get_llm(),
    )
    task.response = message.content[0].text
    return task.response
