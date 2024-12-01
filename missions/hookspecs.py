import pluggy
from .models import Task

hookspec = pluggy.HookspecMarker("YamLLMs")


# Task plugins


@hookspec(firstresult=True)
def run_scrape(task: Task):
    """Run a YamLLMs task - generally, to fetch data

    :param task: the task in question
    """


@hookspec(firstresult=True)
def run_api(task: Task):
    """Run a YamLLMs API fetch task

    :param task: the task in question
    """


@hookspec(firstresult=True)
def filter_from_data_tasks(task, data_tasks):
    """Filter data fetched in a previous mission

    :param task: the task in question
    :param data_tasks: the set of data tasks from the data mission
    """


@hookspec(firstresult=True)
def run_llm_decision(task: Task):
    """Have an LLM make a decision, usually about what data to fetch

    :param task: the task in question
    """


@hookspec(firstresult=True)
def fetch_for_llm(task: Task):
    """Fetch data in response to an LLM request

    :param task: the task in question
    """


@hookspec(firstresult=True)
def run_aggregate(task: Task, tasks: list, url_key: str):
    """Run an aggregation of previous tasks.

    :param task: the task in question
    :param tasks: an initial set of previous tasks to aggregate
    :param url_key: the key to use for the URL in the aggregate
    """


@hookspec(firstresult=True)
def run_rating(task: Task):
    """Run a rating task through an LLM.

    :param task: the task in question
    """


@hookspec(firstresult=True)
def quantify(task):
    """Run a quantify task based on previous data

    :param task: the task in question
    """


@hookspec(firstresult=True)
def run_agent(task: Task):
    """Run an agent task through an LLM.

    :param task: the task in question
    """


@hookspec(firstresult=True)
def run_eval(task):
    """Run an evaluation of a previous task

    :param task: the evaluation task, which has the task to be evaluated as its parent
    """


# LLM plugins


@hookspec(firstresult=True)
def chat_llm(task: Task, input: str, tool_key: str):
    """Request / response chat with a LLM

    :param task: the task in question
    :param input: the new input for the LLM (the prompt prefix is part of the task)
    :param tool_key: the LLM tool, function call, or structured output definition, if any
    """


@hookspec(firstresult=True)
def show_llm(task: Task, input: str):
    """Image input for an LLM

    :param task: the task in question
    :param input: the URL of the image in question
    """


@hookspec(firstresult=True)
def ask_llm(task: Task):
    """Ask an LLM a question

    :param task: the task in question
    """
