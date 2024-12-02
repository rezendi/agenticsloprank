# YamLLMs

A framework for defining, running, and storing sequences of LLM-related tasks with minimal code (sometimes, none.)

YamLLMs is focused on using LLMs as 'software Swiss Army Knives' or '[anything-to-anything machines](https://www.strangeloopcanon.com/p/generative-ai-or-the-anything-from)' rather than chatbots — automating missions such as analyzing projects, fact-checking articles, assessing and rating artifacts such as documents or pull requests, transcribing videos, turning unstructured data into structured JSON or structured data into prose reports, and in general automating aspects of pipelines or processes that were previously manual because they required judgement, fuzzy logic, or difficult / unpredictable / ill-defined inputs or outputs. YamLLMs lets you easily define, configure, run, and persist such missions.

These missions are broken down into sets of individual tasks, such as fetching data from an API, scraping a web site, or invoking an LLM to make a decision, report on a set of inputs, generate a structured JSON output, or evaluate a previous output. These tasks can be defined by simple YAML files. The [YAML which defines a mission](./missions/management/seed.yaml) that:

1. Fetches a public GitHub repo's README, recent commits, issues, and pull requests
2. Generates reports for each dataset, and assess and quantifies the commits and PRs
3. Fetches several recently modified files and assess their code quality
4. Runs a recursive agent to assess the potential risks this project may face
5. Summarizes all of the above in a final report

...is only 45 lines long:

```yaml
mission: "GitHub Repo Analysis"
description: Analyze a GitHub repository and generate an insightful report
base_llm: gpt-4o
base_prompt: final-oss
flags: { "repo_in_name": "true" }
tasks: # repo/placeholder in URL is special-case, to be replaced with the actual repo
  - readme:
      category: API
      base_url: https://github.com/repo/placeholder/README
      report: key_context # this report will be used as context for all other reports
  - commits:
      category: API
      base_url: https://github.com/repo/placeholder/commits
      report: yes
  - issues:
      category: API
      base_url: https://github.com/repo/placeholder/issues
      report: yes
  - pulls:
      category: API
      base_url: https://github.com/repo/placeholder/pulls
      report: yes
  - quantify_commits:
      parent: commits
      category: Quantified Report
  - assess_prs:
      parent: pulls
      category: LLM Rating
      base_url: https://github.com/repo/placeholder/pulls/assess
  - quantify_prs:
      parent: assess_prs
      category: Quantified Report
  - assess_files:
      parent: commits
      category: LLM Decision
      base_url: https://github.com/repo/placeholder/files
      report: yes
  - risk_detective:
      category: Agent Task
      base_url: https://yamllms.ai/risk/assess
  - quantify_risks:
      parent: risk_detective
      category: Quantified Report
      base_url: https://yamllms.ai/risk/quantify
      flags: { "max_iterations": 8 }
```

Obviously the framework is optimized for such missions (which were the basis for [Dispatch AI](https://thedispatch.ai/), from which YamLLMs was birthed) but our flexible approach allows anyone to easily add on custom tasks, data sources, LLMs, prompts, and other integrations as (optionally closed-source) plugins. Every mission, task, and LLM input/output is stored in the database for future and/or time-series analysis; alternatively, it is very easy to delete the input data and retain only the LLM outputs for data security purposes.

YamLLMs is built atop [Django](https://www.djangoproject.com/) so it can easily run locally, on a PaaS service such as Heroku, and/or in Docker containers, and can be managed via either the command line or Django's web admin interface. Its dependencies are minimal: Python, Django, Redis, (optionally) RQWorker, and a database — locally, by default, just SQLite.

## How To Use It

1. Start with a problem, preferably recurring, that LLMs might help solve.
2. Install YamLLMs as per the Installation / Quickstart below.
3. Determine a solution composed of a series of individual tasks, including LLM outputs. For instance:
    1. Fetch raw article text from the Internet.
    2. Use an LLM to generate an intelligently structured list of factual claims in that text.
    3. For each such claim, run a news search to see if it is supported by media you trust.
    4. Use an LLM to conver those search results into a report on the validity of the initial article.
4. Describe mission, tasks, and prompts in one compact YAML file, per our examples / documentation / code.
5. Import that mission template into the database: e.g. `python manage.py import --file "fact_check.yaml"`
6. Run a mission, via the web admin interface, a custom command, or the generic `run_mission` command.
7. Incorporate that mission, and others, into fully automated processes to help solve ever larger problems.

## Example

See [EXAMPLE.md](./EXAMPLE.md) for a detailed step-by-step walkthrough of the fact-checker example.

## Installation / Quickstart

To install YamLLMs locally and run a sophisticated LLM analysis of a public GitHub repo, without writing any new code at all, you need only a GitHub Personal Access Token and an OpenAI or (free) Nvidia LLM API key:

### Code and API Keys

Pull this repo down to your local machine

`git clone https://github.com/thedispatch/yamllms`

and in its root directory, save a `.env` file with the following environment variables:

- `NVIDIA_API_KEY` (available for free [here](https://build.nvidia.com/nvidia/llama-3_1-nemotron-70b-instruct)) or `OPENAI_API_KEY` (if you have one)
- `GITHUB_TOKEN` (a free GitHub [Personal Access Token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens))

(GitHub kindly allows a tiny number of unauthorized API calls, so you can actually get things running without any of the above, but you will likely hit GitHub rate limits before you are rejected by the LLM API for the lack of a key.)

### Running Locally: Directly

- [Install Python](https://realpython.com/installing-python/)
- [Install pip](https://pip.pypa.io/en/stable/installation/) (Python's package manager) if necessary
- [Install Redis](https://redis.io/docs/getting-started/installation/) and ensure `redis-server` is running
- Run `pip install -r requirements.txt` to installs the necessary libraries

### Running Locally: Docker Compose

- Alternatively, just run `docker-compose build && docker-compose run`

### Setup and Seed

(If using Docker Compose, preface all commands with `docker-compose run worker`.)
In the root directory, open a command-line window and install/configure the framework:

- Run `python manage.py migrate` (sets up your local SQLite database)
- Optionally run `pytest` (confirm the install is working; ignore the time-zone warnings)
- Run `python manage.py seed` (populates your local database with initial data, including the Public Repo Report mission YAML; also creates a Django admin user with the credentials `admin`/`adyamllms`)

### Run A Sample Report

Your installation/configuration complete is now complete, and you can run a Public Repo Report mission:

- Run `python manage.py random_report` and witness your report being generated by hundreds of API calls and dozens of tasks.
(This command automatically uses the Nvidia API if an Nvidia API key is set and an OpenAI API is not.)

### Administration

Subsequently, to administer your missions and tasks:

- If not using Docker Compose, run `python manage.py runserver` to launch the local web server
- Navigate to [http://localhost:8000/running](http://localhost:8000/running) to view the currently active or most recent mission.
- To view task details from that page, or to administer YamLLMs in general, log in to [http://localhost:8000/admin](http://localhost:8000/admin) with `admin`/`adyamllms`.
- If not using Docker Compose, you need a background worker process to run missions and tasks from the web admin interface; open another command-line window and run `python manage.py rqworker`.

## Configuring Missions and LLM Tasks with YAML

Let's look at that Public Repo Report YAML in more detail. First, the mission definition:

```yaml
mission: "GitHub Repo Analysis"
description: Analyze a GitHub repository and generate an insightful report
base_llm: gpt-4o
base_prompt: final-oss
flags: { "repo_in_name": "true" }
```

A name, a description, which LLM to use; pretty straightforward. There is also a "base prompt," which is the prompt to use for the mission's final LLM report task, if any. Prompts can be explicitly included in the YAML, or, for more sophisticated installations, stored in a separate repository and accessed at runtime when missions and tasks are created, so they can be independently administered and version-controlled. (You can also keep them in the same repo if you really want.) More on that below. The key `final-oss` here maps to the file `final-oss.md` in the prompts repo, which by default is [https://github.com/rezendi/yamllms-prompts](https://github.com/rezendi/yamllms-prompts). `repo_in_name` is a special case used for reports on GitHub repos, which illustrates the use of `flags`.

Now let's look at a few of the tasks:

```yaml
tasks:
  # repo/placeholder in URL is special-case, to be replaced with the actual repo
  - readme:
      category: API
      base_url: https://github.com/repo/placeholder/README
      report: key_context # this report will be used as context for all other reports
  - commits:
      category: API
      base_url: https://github.com/repo/placeholder/commits
      report: yes
  - quantify_commits:
      parent: commits
      category: Quantified Report
  - risk_detective:
      category: Agent Task
      base_url: https://yamllms.ai/risk/assess
      flags: { "max_iterations": 8 }
```

Tasks are defined by their `category`, the set of which is in [base.py](./missions/models/base.py); their `parent` task, e.g. Quantify Commits task is a child of Fetch Commits; and their `url`. Each task may have an individual URL, which is used to route them to the appropriate plugin, see below. (Their parent task's URL may also be used.) We define a _base_ URL here because these are task _templates_; each individual task may, at runtime, override that template.

As the comment says, `repo/placeholder` is a special case used to target a different repo with each mission.

A common pattern is to fetch data and then process that data with an LLM. We call that LLM output a _report_. If a fetch task has a _report_ field in the YAML, it means that after the fetch is run, a corresponding report task will be created and run.

You may wonder: what LLM and prompt will be used for these reports? We already defined the 'base' LLM at the mission level, though individual tasks may override this. As for the prompt, by default we use the last component of the task's URL as the prompt key, so in this cases, the prompt for the `commits` task would be the contents of the file `commits.md` in the prompts repo. You can of course instead explicitly define prompts in YAML.

The initial README report is marked as _key context_, which means that LLM report will be the first one generated, and will be appended to the context window input for all subsequent 'LLM Report' tasks. We find that such context significantly improves subsequent LLM outputs.

The quantify task is _not_ an LLM task (because LLMs are bad at math and quantification) - rather, it does its own traditional-software calculation/generation of a table, graph, or other quantified report. That said, one could e.g. use a quantified task to run the numbers, and than an LLM to take the numbers and generate a graph.

Finally, the last task is an 'Agent' Task. Those run recursively and indefinitely; each task can generate and return _another_ agent task to run. (Setting a maximum number of iterations is considered desirable. The default is 16.) Here, our 'risk detective' trawls through all the available fetch/data tasks, accumulating an assessment of the overall risks to this project. New kinds of agents can be added very easily, again keyed on the agent task's URL. Example agent code is found in [agent.py](./missions/plugins/agent.py)

## Code Overview

There are really only a few files you need to understand to grasp the overall system, all in the `missions` Django subproject: [`hub.py`](/missions/hub.py), [`run.py`](/missions/run.py), and the model files in [`models`](/missions/models). Of those:

- `hub` orchestrates a mission run from start to finish
- `run` handles the running of each individual task within a mission
- the files in `models` describe the class hierarchy, and are best read in the order [`base.py`, `templates.py`, `mission.py`, `task.py`]. Key methods include `create_mission` on MissionInfo, `create_task` and `create_report_task` on TaskInfo, and `prerequisite_tasks`, `aggregate_dependencies`, `assemble_prerequisite_inputs`, and `previous` on Task.

[`util.py`](/missions/util.py), a grab bag of definitions and (mostly) dependency-free utility functions, is also widely used.

The web interface, including a default reports UX, is found in the separate `web` Django subproject.

## Plugins

We use [Pluggy](https://pluggy.readthedocs.io/en/stable/) for our plugin framework. Methods which can be implemented by plugins are defined in [hookspecs.py](./missions/hookspecs.py). There are two presently two cohorts of plugins:

### Task Plugins

Here, each `category` of task has a different plugin method defined in `hookspecs`, e.g. `run_api(task)` to perform an API task. An implementation simply checks the task properties, generally just its URL, but its parent and `flags` may also be relevant. If a task matches a plugin, that plugin _must_ return a value from its implementation; otherwise, it _must_ return None. A very simple example, from the [Slack API plugin](./missions/jobs/slack.py):

```python
from missions import jobs  # the hookimpl annotation

@jobs.hookimpl
def run_api(task):
    if task.url and task.url.startswith(SLACK_API):
        get_slack_chatter(task, get_slack(task))
        return task
    return None
```

Here, `get_slack` gets the Slack token and returns a [Slack Python client](https://tools.slack.dev/python-slack-sdk/). All our framework knows, though, is whether this plugin returned a value from the `run_api` method or not. Note that plugins are configured so that we cease processing after a successful implementation: only one plugin can perform any given task. It is up to developers to ensure there is no conflict between plugins. Keying on task URLs should make this quite easy.

### LLM Plugins

We also use plugins for LLM implementations. Out of the box the framework provides varying levels of support for:

- OpenAI (including Azure OpenAI)
- Anthropic
- Google
- Mistral
- Nvidia

each of which implements one or more of the following methods:

- `chat_llm(task: Task, input: str, tool_key: str)` (text request for an LLM: `input` is any dynamic text to be added to the task's defined prompt, `tool_key` indicates a request for a function call / structured output.)
- `show_llm(task: Task, input: str)` (image request: here `input` is the URL of the image in question)
- `ask_llm` (edge case of asking a follow-up question based on multiple previous inputs; at present, this is implemented via Gemini by simply dumping all of the mission's data tasks into the prompt.)

### Adding Plugins

As is hopefully apparent, adding (and redefining) task and LLM plugins is very, very easy. You need simply:

- implement an existing hookspec and, per the Slack example above, annotating that method with `@job.hookimpl`
- register your new implementation in [apps.py](./missions/apps.py)

## Prompts

Prompts may simply be written into the YAML that defines tasks and missions.

A more sophisticated approach is to store prompts in a separate repository, defined in `settings.GITHUB_PROMPTS_REPO`. (Out of the box this is [thedispatch/yamllms-prompts](https://github.com/thedispatch/yamllms-prompts)) This encapsulation of prompts as separate first-class concerns allows for independent version control and evolution of prompts over repeated iterations of mission and task templates.

Fetching from the prompts repo is performed by the `get_prompt_from_github` method in [prompts.py](./missions/jobs/prompts.py). This accepts a `key` parameter, which can be any string. There is some special-case handling for various APIs, but as a general fallback, if a URL is passed in, `.md` is appended to the last component of that URL, and that filename is fetched from the prompts repo. The responses for prompt keys are by default cached for 60 minutes (1 minute in a debug/test environments.)

The prompt text is fetched using the GitHub API. This calls for a `GITHUB_TOKEN`, although if the prompts are in a public repository, GitHub's limit of 60 unauthorized API requests per hour will likely suffice. You could use the YamLLMs repos as the prompts repo as well, with minor tweaks to `get_prompt_from_github`.

## Administration

YamLLMs has three sets of administrative tools:

- a classic Django admin interface at `/admin`
- custom admin/inspection pages at `/staff`
- custom Django command-line commands in [management/commands](./missions/management/commands/)

Every YamLLMs `Mission` is subdivided into multiple`Task`s. Individual are generally defined in Mission Templates (`MissionInfo` in code) and Tasks in Task Templates (`TaskInfo`). That said, Tasks are often dynamically created during the course of a Mission.

Formally, a mission's Tasks form a [Directed Acyclic Graph](https://en.wikipedia.org/wiki/Directed_acyclic_graph). As such, tasks may have 'parent' tasks, indicating their position in the graph. A single task might take data fetched or generated by its parent task, interpolate that content with an LLM prompt, submit the combined prompt and data to an LLM API, and store the response.

Tasks are generally defined by their `mission`, their `parent`, their `category` and their `url`. They may incorporate data from multiple previous tasks; such data dependencies beyond their immediate `parent` are itemized in their `depends_on_urls` field. A task ensures all its prerequisites are complete before it runs.

Tasks may have prompts, responses, or both. A frequent pattern is "fetch from an API / report on that fetch." For the sake of convenience it is possible to encapsulate this in a single Task Template, via the `reporting` field. In that case, when the mission is run, the data will be fetched, a new LLM Report Task will be dynamically created, and the `prompt` defined by the original task will be sent to the LLM along with the fetched data.

It's worth noting that one reason our "fetch data" tasks are separate from our "generate LLM output" tasks is that it makes it very easy to delete the input data once the LLM outputs are complete. This is advantageous when dealing with data security requirements.

It is also possible for tasks to be generated in response to an LLM decision; we might, for instance, have a task that asks an LLM which files to fetch, which in turn would create a new Task to actually fetch those files, and a subsequent Task which would send their contents to the LLM and prompt it for further output.

Tasks have not one but two fields for outputs. `response` is used for unstructured text; usually, collation of input data _for_ an LLM, and/or, the verbatim response _from_ an LLM. `structured_data` is used for structured text, such as programmatically generated or LLM Structured Output JSON. Sometimes one might have both: for instance, our default task which fetches GitHub commit data collates that data into Markdown for an LLM input, but also collects quantitatve data as structured JSON for subsequent rendering in table/graph format.

Missions and tasks include a `flags` JSON field which stores individual settings to tweak their behavior. In addition, all classes include an `extras` JSON field used to dynamically store generated values and diagnostics. This combination of columnar and document data would be hotly contested by some engineers but is very useful for development speed, expediency, and reducing the number and overhead of database migrations. That said, both `flags` and `extras` can be viewed as a staging area for our database model; certain values will likely eventually be migrated to full-fledged database columns of their own.

Note that missions and tasks initiated from the web interface are run in a background worker process. To get this running locally:

- Run `redis-server` (starts Redis)
- Open another console and run `python manage.py rqworker` (process which queues and handles long-running jobs like API calls)

(We could tweak things so that we don't need Redis or RQ Worker at all locally, but it's generally good for the local development
environment to be broadly similar to production. If this gets to be a hassle, we may revisit.)

To run a new mission defined by an existing Mission Template, go to that template's `admin` page and select "Run" at the bottom. To rerun a mission, go to its `admin` page and select Rerun Mission. This will attempt to rerun any incomplete or failed tasks, but will _not_ rerun any tasks which have successfully completed _except_ those categorized as Finalize Mission, such as generating a final report, and Post Mission, such as sending the final mission via email and/or webhooks.

To rerun an individual task, go to its `admin` page and select Rerun Task. This will rerun all tasks, including completed ones, from scratch. You can access a task's edit page via its box in the `/running` page, which in general is a good place to inspect a mission.

The `/staff/mission_info/<id>`, `/staff/task_info/<id>`, `/staff/mission/<id>`, and `/staff/task/<id>` pages are primarily there to let you inspect the data sent to and from LLMs in its entirety, in preformatted text, and also inspect the `flags` and `extras` of any given object, without having to deal with the textareas of the Django admin interface.

Third-party OAuth integrations (to e.g. GitHub, Jira, Notion, Figma, Sentry, etc.) are encapsulated in the Integration class. Each integration in turn may have one or more relevant Secrets, such as access tokens. Secrets are encrypted at rest, and unavailable in the admin interface. The use of OAuth is optional; API tokens can simply be stored as environment variables instead. Custom per-integration methods are implemented as _plugins_, described below.

Missions and Mission Templates can be grouped by Customer. An Integration should always correspond to a Customer. When a customer has multiple projects, integrations may or may not correspond to a Project. For instance, a customer might have a single GitHub integration, that most Projects use, but a specific Project which has its own, different GitHub integration because its repo belongs to a different organization.

## Evaluations

Automated evaluations are key to successful LLM solutions. By default we support evaluation of individual tasks and overall missions. Because evaluations are simply implemented as a category of Task, they are therefore also part of the plugin framework, and can easily be added to or superseded.

We also provide a convenience `data_check` eval to test for hallucinations; in our experience, hallucinations are extremely rare in outputs generated from properly collated data, except when fetch errors leave the data tasks empty, but data checks remain useful to assuage users' concerns.

To data-check a report task, simply set `"data_check":"true"` (we lean towards using string `"true"` and `"false"` even for Booleans, lest future complexity call for making those fields non-boolean) in the `flags` dictionary of a task for which `reporting` is set to `Reporting.ALWAYS_REPORT`. If this flag is set, then after the report is run, two more tasks will be created: one will list the factual assertions in the generated report, and the next will compare those assertions to the initial data.

At present evalutions can include any combination of these outcomes if a failure occurs:

- send an email
- rerun the initial task
- mark initial task as Rejected and move on

## Caveats

This framework evolved from and with a startup, rather than having been conceived _de novo_, and so has various idiosyncracies as a result of that: task categorization, in particular, is clearly an evolved rather than designed taxonomy, and concepts such as "customers" tend to be intended for business not open-source use. Certain other aspects also still betray a certain "get things done" crudeness, which we tend to view as virtue more than vice, but definitely include some infelicities. In general, if it looks like the code has been carved somewhat crudely out of some larger application ... it probably has been.

At present only the OpenAI LLM plugin explicitly supports predefined structured / JSON outputs, though implementing it for other LLMs should be fairly straightforward (and a combination of good prompting and the `get_json_from` method in `util.py` can render them unnecessary).

When the input data for an LLM task exceeds the size of the context window, at present we simply truncate that data. For many purposes, this turns out to be perfeclty acceptable; modern context windows are hundreds of pages long, and especially when running reports on data ordered reverse chronologically, more than enough germane data is maintained. However, depending on context, other approaches such as dividing single tasks into multiple tasks may be desirable. This should be relatively straightforward to implement within the YamLLMs framework.

## Out Of The Box

YamLLMs is designed to make adding new categories and features very easy. That said, out of the box it supports:

- GitHub:
    - commit history
    - issues
    - pull requests
    - pull request quality rating
    - source code analysis (including letting the LLM determine which files are worth analyzing)
- Jira issues
- Confluence documents
- Linear issues
- Notion documents
- Slack discussions
- Figma designs
- Sentry data
- Monday data
- Harvest / Forecast hours
- Bing news search
- Time series deltas for all of the above
- Recursive agental assessments across multiple data sources
- Evaluations of previous LLM outputs
- LLM questions / chatting

LLM providers supported out of the box:

- OpenAI
- Azure OpenAI
- Anthropic
- Gemini
- Mistral
- NVidia

## Credits / Contact / License

The architecture, configuration, and Python code were initially written by [@rezendi](https://github.com/rezendi), with the front end a collaboration between [@rezendi](https://github.com/rezendi) and [@chenware](https://github.com/chenware). They can be contacted at [jon@thedispatch.ai](mailto:jon@thedispatch.ai) and [robb@thedispatch.ai](mailto:robb@thedispatch.ai).

YamLLMs is [Apache licensed](./LICENSE.txt).
