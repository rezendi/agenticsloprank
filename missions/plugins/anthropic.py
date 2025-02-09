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
        tool_prompt += (
            "\nYour response MUST be in the form of a JSON object like the following:\n"
        )
        example_json = generate_example_json(tools[0])
        tool_prompt += "\n```json\n%s\n```\n" % example_json
        tool_prompt = "\nNote that all of those fields are mandatory and must be followed exactly.\n"
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


def generate_example(schema, key_name=None):
    """
    Recursively generate an example value based on a JSON schema.
    """
    schema_type = schema.get("type")

    if schema_type == "object":
        example = {}
        properties = schema.get("properties", {})
        # If "required" is specified, use those keys; otherwise use all defined properties.
        keys = schema.get("required", list(properties.keys()))
        for prop in keys:
            prop_schema = properties.get(prop, {})
            example[prop] = generate_example(prop_schema, key_name=prop)
        return example

    elif schema_type == "array":
        items_schema = schema.get("items", {})
        # Create an example array with one item
        return [generate_example(items_schema)]

    elif schema_type == "string":
        # You might customize this based on the key or description.
        # For instance, if the description hints at a multi-paragraph text,
        # you could provide a longer example.
        return f"example {key_name}" if key_name else "example string"

    elif schema_type == "number":
        desc = schema.get("description", "").lower()
        # If the description indicates a significance scale of 1 to 5, choose a mid value.
        if "1 to 5" in desc:
            return 3
        return 1

    elif schema_type == "boolean":
        return True

    # Fallback for types that aren’t explicitly handled.
    return None


def generate_example_json(structured_output_def):
    """
    Given an OpenAI Structured Output definition (a dict),
    generate an example JSON object conforming to its parameters schema.
    """
    # In our Structured Output definition, the example JSON is defined
    # by the "parameters" field inside the "function" key.
    parameters_schema = structured_output_def.get("function", {}).get("parameters", {})
    return generate_example(parameters_schema)
