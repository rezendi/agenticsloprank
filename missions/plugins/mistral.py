import os
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage
from ..util import *
from missions import plugins


@plugins.hookimpl
def chat_llm(task, input, tool_key):
    if task.get_llm() in MISTRAL_MODELS:
        return chat_mistral(task, input)
    return None


def chat_mistral(task, prompt):
    prompt = (prompt or "").strip()
    sized_prompt = get_sized_prompt(task, prompt)
    final_prompt = (task.prompt or "").strip() + "\n\n" + sized_prompt
    task.extras["system_prompt"] = task.prompt
    task.extras["final_prompt"] = final_prompt

    api_key = os.environ["MISTRAL_API_KEY"]
    model = MISTRAL_MODEL
    client = MistralClient(api_key=api_key)

    counter = 0
    task.response = ""
    for chunk in client.chat_stream(
        model=model,
        messages=[ChatMessage(role="user", content=final_prompt)],
    ):
        counter += 1
        if chunk.choices[0].delta.content is not None:
            task.response += chunk.choices[0].delta.content
        if counter % 40 == 0:
            task.save()
    task.extras["response_length"] = len(task.response)
    return task.response
