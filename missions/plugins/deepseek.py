import os
from openai import OpenAI
from ..util import get_sized_prompt
from missions import plugins

# DeepSeek integration: specify the model(s) this adapter supports.
DEEPSEEK_MODELS = {"deepseek-reasoner"}

@plugins.hookimpl
def chat_llm(task, input, tool_key):
    if task.get_llm() in DEEPSEEK_MODELS:
        return chat_deepseek(task, input)
    return None

def chat_deepseek(task, prompt):
    prompt = (prompt or "").strip()
    sized_prompt = get_sized_prompt(task, prompt)
    # Assemble a final prompt for logging and debugging purposes.
    final_prompt = (task.prompt or "").strip() + "\n\n" + sized_prompt
    task.extras["system_prompt"] = task.prompt
    task.extras["final_prompt"] = final_prompt

    # Retrieve DeepSeek API key from environment variables.
    api_key = os.environ["DEEPSEEK_API_KEY"]
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    model = "deepseek-reasoner"

    # Construct the conversation messages.
    # DeepSeek expects an explicit system prompt and a user prompt.
    system_message = {"role": "system", "content": task.prompt or "You are a helpful assistant"}
    user_message = {"role": "user", "content": sized_prompt}
    messages = [system_message, user_message]

    # Note: DeepSeek currently does not support streaming responses via this client.
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=False
    )

    task.response = response.choices[0].message.content
    task.extras["response_length"] = len(task.response)
    task.save()
    return task.response
