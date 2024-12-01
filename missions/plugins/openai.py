import json, os, time
from openai import OpenAI, AzureOpenAI
from ..functions import get_openai_functions_for
from ..util import get_sized_prompt, get_provider_llm, OPENAI_MODELS, AZURE_MODELS, log
from missions import plugins
from missions.models import TaskCategory


COMPLETED_STATUSES = ["completed", "failed", "cancelled", "expired"]


@plugins.hookimpl
def chat_llm(task, input, tool_key):
    llm = task.get_llm()
    # need to handle fine-tunes
    if llm in OPENAI_MODELS or llm in AZURE_MODELS or llm.startswith("ft:gpt-"):
        return chat_openai(task, input, tool_key)
    return None


@plugins.hookimpl
def show_llm(task, input):
    if task.get_llm() in OPENAI_MODELS:
        return show_openai(task, input)
    return None


@plugins.hookimpl
def ask_llm(task):
    if task.get_llm() in OPENAI_MODELS:
        run = ask_openai(task)
        if task.category == TaskCategory.LLM_QUESTION:
            return run  # just a followup question

        if run.status == "requires_action":
            log("Updating function")
            try:
                update_with_function_run(task, run)
            except Exception as ex:
                log("Could not update function run", task, run, ex)
                task.add_error(ex, "%s" % run)

            complete_function_run(task)

    return None


def get_client(obj=None, llm=None):
    if not obj:
        return OpenAI()
    if not llm:
        llm = get_provider_llm(obj.get_llm())
    if llm.endswith("-azure"):
        return AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version="2024-08-01-preview",
        )
    op = getattr(obj, "get_openai_key", None)
    if not op or not callable(op):
        return OpenAI()
    return OpenAI(api_key=op())


def wait_for_openai(task, run, thread_id=None):
    openai = get_client(task)
    # wait for the run to complete
    tout = 0
    while run.status not in (COMPLETED_STATUSES + ["requires_action"]) and tout < 300:
        time.sleep(1)
        tout += 1
        if tout % 10 == 0:
            log("seconds", tout, "status", run.status)
        run = openai.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
    log("run done", run.status)
    if run.status == "requires_action":
        log("Run requires action", run)
    return run


def run_openai(task, instructions=None):
    openai = get_client(task)
    assistant_id = task.get_assistant_id()
    thread_id = task.get_thread_id()
    run = openai.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id,
        instructions=instructions,
    )
    task.set_run_id(run.id)
    task.save()
    run = wait_for_openai(task, run, thread_id)
    task.extras["openai_run_status"] = run.status
    task.set_failed(run.status == "failed")
    task.save()
    return run


def ask_openai(task):
    if task.is_test():
        log("Not asking, using test model")
        task.response = "Test TDTest response"
        return None

    openai = get_client(task)
    thread_id = task.get_thread_id()
    # get all the data from previous fetch tasks, add as messages if not already there
    for subtask in task.prerequisite_tasks():
        if not subtask.get_message_id():
            prompt = get_sized_prompt(subtask, subtask.response or "")
            log("asking prev task", subtask, "prompt_length", len(prompt))
            message = openai.beta.threads.messages.create(
                thread_id=thread_id, role="user", content=prompt
            )
            subtask.set_message_id(message.id)
            subtask.save()
            time.sleep(1)  # go easy on the OpenAI API

    prompt = task.assemble_prompt()
    prompt = get_sized_prompt(task, prompt)
    log("asking task", task, "prompt_length", len(prompt))
    message = openai.beta.threads.messages.create(
        thread_id=thread_id, role="user", content=prompt
    )
    task.set_message_id(message.id)
    task.save()
    if not task.requires_llm_response():
        # we're just feeding the assistant data, not asking for a response
        return None
    run = run_openai(task)
    if run.status in COMPLETED_STATUSES:
        log("Saving OpenAI response for", task)
        time.sleep(1)  # give OpenAI a chance to catch up
        task.response = get_latest_openai_response(task)
        task.save()
        log("Saved, response length", len(task.response or ""))
    return run


def chat_openai(task, input, tool_key=None):
    if tool_key:
        return chat_openai_json(task, input, tool_key)
    input = (input or "").strip()
    sized_input = get_sized_prompt(task, input)
    task_prompt = (task.prompt or "").strip()
    prefix = """

Instructions
------------

"""
    divider = (
        "\n\n---\n\n"
        if task.is_time_series()
        else """

---

Information to analyze and report on
------------------------------------

"""
    )
    final_prompt = prefix + task_prompt + divider + sized_input
    log("final prompt length", len(final_prompt))
    task.extras["task_prompt"] = task_prompt
    task.extras["final_prompt"] = final_prompt

    openai = get_client(task)
    llm = get_provider_llm(task.get_llm())
    o1 = llm.startswith("o1-")
    azure = llm.endswith("-azure")
    if o1:
        completion = openai.chat.completions.create(
            model=llm,
            messages=[
                {"role": "user", "content": final_prompt},
            ],
        )
        task.response = completion.choices[0].message.content
    elif azure:
        log("Using Azure OpenAI")
        completion = openai.chat.completions.create(
            model=llm,
            messages=[
                {"role": "user", "content": final_prompt},
            ],
            temperature=0.3,
            frequency_penalty=0.2,
            presence_penalty=0.2,
            stream=False,
        )
        task.response = completion.choices[0].message.content
    else:
        completion = openai.chat.completions.create(
            model=llm,
            messages=[
                {"role": "user", "content": final_prompt},
            ],
            temperature=0.3,
            frequency_penalty=0.2,
            presence_penalty=0.2,
            stream=True,
        )
        counter = 0
        task.response = ""
        for chunk in completion:
            counter += 1
            chunk_message = chunk.choices[0].delta
            if chunk_message.content:
                task.response += chunk_message.content
            if counter % 40 == 0:
                task.save()

    task.extras["response_length"] = len(task.response)
    task.extras["llm_used"] = llm
    return task.response


def chat_openai_json(task, input, tool_key=None):
    input = (input or "").strip()
    # OpenAI function calls currently appear to have this limit
    sized_input = get_sized_prompt(task, input)
    task_prompt = (task.prompt or "").strip()
    prefix = """

Instructions
------------

"""
    divider = (
        "\n\n---\n\n"
        if task.is_time_series()
        else """

---

Information to analyze and report on
------------------------------------

"""
    )
    final_prompt = prefix + task_prompt + divider + sized_input
    log("final JSON prompt length", len(final_prompt))
    task.extras["task_prompt"] = task_prompt
    task.extras["final_prompt"] = final_prompt

    llm = get_provider_llm(task.get_llm(), use_azure_mini=False)
    if llm.startswith("o1-"):
        return chat_openai(task, input)  # remove when o1- can handle Structured Outputs
    if llm.endswith("-azure"):
        log("Using Azure OpenAI")

    tool_choice = None
    match tool_key:
        case "files":
            tool_choice = {"type": "function", "function": {"name": "get_files"}}
        case "pulls":
            tool_choice = {"type": "function", "function": {"name": "get_prs"}}
        case "issues":
            tool_choice = {"type": "function", "function": {"name": "estimate_issues"}}
        case "data_check":
            tool_choice = {"type": "function", "function": {"name": "data_check"}}
        case "detective_report":
            tool_choice = {"type": "function", "function": {"name": "detective_report"}}
        case "perform_rating":
            tool_choice = {"type": "function", "function": {"name": "perform_rating"}}
        case "analyze_risks":
            tool_choice = {"type": "function", "function": {"name": "analyze_risks"}}
        case "assess_risks":
            tool_choice = {"type": "function", "function": {"name": "assess_risks"}}
        case "identify_issue":
            tool_choice = {"type": "function", "function": {"name": "identify_issue"}}
    if tool_choice:
        log("tool choice", tool_key, "llm", llm)

    task.extras["llm_used"] = llm
    openai = get_client(task, llm)
    tools = get_openai_functions_for(tool_key)
    completion = openai.chat.completions.create(
        model=llm,
        messages=[
            {"role": "user", "content": final_prompt},
        ],
        temperature=0.3,
        frequency_penalty=0.2,
        presence_penalty=0.2,
        response_format={"type": "json_object"},
        tools=tools,
        tool_choice=tool_choice,
    )
    response_message = completion.choices[0].message
    tool_calls = response_message.tool_calls
    if tool_calls:
        log("tool call response")
        for tool_call in tool_calls:
            task.extras["openai_tool_call_id"] = tool_call.id
            # for noww, assume only one function
            if tool_call.type == "function":
                arguments = tool_call.function.arguments
                args = json.loads(arguments)
                task.response = json.dumps(args, indent=2)
    else:
        log("Tool call failed")
        task.response = response_message.content
    return task.response


def update_with_function_run(task, run):
    required = run.required_action
    task.extras["openai_response"] = "%s" % required
    # for now we only support one tool call at a time
    for tool_call in required.submit_tool_outputs.tool_calls:
        log("tool_call", tool_call)
        task.extras["openai_tool_call_id"] = tool_call.id
        if tool_call.type == "function":
            arguments = tool_call.function.arguments
            args = json.loads(arguments)
            task.response = json.dumps(args, indent=2)
    task.set_message_id("tool")
    task.save()


def complete_function_run(task):
    # notify the assistant that we're done
    openai = get_client(task)
    thread_id = task.get_thread_id()
    run_id = task.get_run_id()
    openai.beta.threads.runs.submit_tool_outputs(
        thread_id=thread_id,
        run_id=run_id,
        tool_outputs=[
            {
                "tool_call_id": task.extras["openai_tool_call_id"],
                "output": "The provision of the requested data is complete",
            },
        ],
    )
    run = openai.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
    run = wait_for_openai(run, thread_id)
    log("Tool call complete, ready to continue")
    task.extras["openai_run_status"] = run.status
    task.set_failed(run.status == "failed")
    task.save()


def get_openai_messages(task):
    openai = get_client(task)
    messages = openai.beta.threads.messages.list(thread_id=task.get_thread_id())
    assistant_messages = [m for m in messages.data if m.role == "assistant"]
    return assistant_messages


# TODO handle annotations
def get_openai_responses(task):
    responses = get_openai_messages(task)
    contents = [r.content for r in responses]
    return [c[0].text.value for c in contents if c]


def get_latest_openai_response(task):
    openai = get_client(task)
    responses = get_openai_responses(task)
    if responses:
        return responses[0]
    log("No responses found for thread", task.get_thread_id())
    return ""


def set_up_assistant(mission):
    log("Using assistant")
    mission_info = mission.mission_info
    if not mission_info:
        raise Exception("Can't use Assistant when no mission info")

    if mission.is_test():
        mission.set_thread_id("TDTest Thread")
        mission_info.set_assistant_id("TDTest Assistant")
        mission_info.save()
        return

    # check we have a valid assistant
    openai = get_client(mission)
    if mission.get_assistant_id():
        try:
            assistant = openai.beta.assistants.retrieve(mission.get_assistant_id())
        except Exception as ex:
            log("Error getting assistant", mission.get_assistant_id(), ex)
            mission_info.set_assistant_id(None)

    # create a new assistant if no ID in mission info or assistant fetch failed
    if not mission.get_assistant_id():

        log("Creating new assistant")
        tools = []
        if mission_info.flags.get("openai_tools") == "true":
            tools = [
                {"type": "code_interpreter"},
                # {"type": "retrieval"}, // enable later?
            ] + get_openai_assistant_functions()
        assistant = openai.beta.assistants.create(
            name=mission_info.name,
            instructions=mission_info.base_prompt,
            tools=tools,
            model=mission.get_llm(),
        )
        log("New assistant created")
        mission_info.set_assistant_id(assistant.id)
        mission_info.save()
        log("New mission assistant:", mission.get_assistant_id())

    # create new threads for new missions, TODO: consider reruns
    if mission.task_set.count() == 0 or not mission.get_thread_id():
        thread = openai.beta.threads.create()
        log("Mission thread:", thread.id)
        mission.set_thread_id(thread.id)


def show_openai(task, input):
    openai = get_client(task)
    input = json.loads(input)
    task.response = ""
    idx = 0
    for key in input:
        idx += 1
        url = input[key]
        response = openai.chat.completions.create(
            model="gpt-4-vision-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "%s" % task.prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": url,
                            },
                        },
                    ],
                }
            ],
            max_tokens=300,
        )
        log("response", response.choices[0].message.content)
        task.response += "\n\n[Input %s](%s):\n" % (idx, url)
        task.response += "%s" % response.choices[0].message.content
