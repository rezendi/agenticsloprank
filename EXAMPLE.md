# Example: Fact Checking an Online Article

This document walks through a simple YamLLMs mission: using an LLM and Bing News to fact-check an online article.

## 1. Defining and Running The Mission

As a reminder, you define _mission templates_ - "what to do" - which can then be run many times for different inputs, each time being a _mission_. Here, the YAML describing our fact-check mission template, and the prompt for its final report, is simply

```yaml
mission: "Fact Check"
description: Fact check the contents of an online URL using Bing News
flags: { "single_task_chain": "true" } #  final report is predicated only on the last task in the chain
base_llm: nvidia/llama-3.1-nemotron-70b-instruct
base_prompt: |
  # Assess Credibility

  List all of the factual claims provided. Then, for each claim, briefly assess its credibility based on the verification / support from the corresponding sources. Be concise, no yapping.
  Be sure to always cite and, crucially, link to sources. Note that you MUST assess ALL of the claims.
```

Missions always end with a final LLM output. By default they are assumed to include multiple LLM-generated reports and the final task is a report-of-reports that summarizes them. In this case, however, our mission is a very simple linear chain of tasks, so we  set `{ "single_task_chain:" "true" }`.

After a mission template is defined, there are two ways to actually launch a mission:

- the Django web admin interface, via the "Run" button on the mission template's edit page.
- the command line, via a Django _command_.  This is often simpler, and suitable for cron/scheduler jobs.

We could use the generic [run_mission command](./missions/management/commands/run_mission.py), but it's clearer to have a separate Django command for each mission type. Here, that command is [fact_check.py](./missions/management/commands/fact_check.py) — only 20 lines of code. It grabs the mission template by name (since we don't know its databse ID), creates a new mission, stores the URL from the command-line argument in `flags`, and runs it.

## 2. Task 1: Scraping The Article

LLMs are very good at dealing with unstructured text, so we rarely need to do anything fancier than just grabbing all the text and dumping it into the context window. As such defining our first task is super easy, since simple scraping is a built-in YamLLMs task. [scrape.py](./missions/plugins/scrape.py) even comes with a `custom_scrape` method in case you want to do some preprocessing of the text, but, honestly, if you're feeding it to an LLM, you probably don't. So our YAML definition for our first task is simply:

```yaml
tasks:
  - article:
      name: Article in Question
      category: Scrape
      base_url: https://www.example.com/url # special case URL: replaced at runtime with the `mission_url` in the mission's `flags`
```

## 3. Task 2: Listing The Claims

Now, given all the unstructured text within a given web page, we want a list of the key factual assertions in that text. Not long ago this would have been extremely difficult! Now it's almost trivial; all you need is any halfway decent LLM.

### 3a. Adding A New LLM

Let's illustrate how to add a whole new LLM to your YamLLMs installation. It's surprisingly easy. All you need is a new LLM plugin, where "plugin" just means "a new source file which implements a given method, which is then registered in `apps.py`." An LLM plugin is one which implements the following function

```python
@plugins.hookimpl
def chat_llm(task, input, tool_key):
```

Here, `task` is a YamLLM task, and `input` is the text to be input to the LLM (often the output of a previous task). `tool_key` is used for [structured outputs](https://platform.openai.com/docs/guides/structured-outputs) a.k.a. function calls - ignore it for now.

For this mission we'll use Nvidia's Nemotron LLM, not least because you can get a [free API key](https://build.nvidia.com/nvidia/llama-3_1-nemotron-70b-instruct) from them. The entire plugin implementation is at [nemotron.py](./missions/plugins/nemotron.py), 50 lines of code. You then have to _register_ the plugin at [apps.py](./missions/apps.py), following the brutally simple examples there. Finally `nemotron.py` requires a valid `NVIDIA_API_KEY` environment variable, likely set in your `.env`.

### 3b. Turning A Raw Scrape Into A Structured List Of Claims

Now that you have an LLM ready to use, just configure a task with the category of "LLM Report" and set its input data and prompt, per this simple and fairly self-explanatory YAML:

```yaml
  - claims:
      name: List of Claims
      parent: article
      category: LLM Report
      base_prompt: |
        # List Factual Assertions

        What follows is text scraped from an online article.
        Briefly itemize all of the most salient factual assertions made in the article. Be terse and concise: no yapping.
        Note that projections and opinions, or claims that something _would_ or _could_ happen, are not factual assertions.
        Nor are judgement calls, arguable categorizations, indications, suggestions, attempts to draw conclusions, or any other subjective assessments.
        Focus strictly on verifiable, concrete, testable facts that are either true or false.

        Output your findings as a JSON list of strings, with the first string being a one-sentence summary of the article, and every subsequent string being a factual assertion.
```

Note that it will use the LLM defined in the mission's `base_llm` field above; individual tasks can overwrite that, of course. Note also its `parent` field is set to _article_, from the previous task's YAML. This means the output of the _article_ task will be used as the input for this _claims_ task. Obviously each tasks needs to have a unique key.

## 4. Task 3: Fact-Checking The Claims

Our next task is to use Bing News to try to find support / verification for all of those claims output by the previous task.

### 4a. Adding A New API Plugin

Again, a plugin just means "a new source file which implements a given method, registered in `apps.py`." For API tasks, the method in question is simply

```python
@plugins.hookimpl
def run_api(task):
```

To determine which API plugin handles which task, we use the task's URL (and sometimes its parent's URL.) Here that means

```python
BING_ENDPOINT = "https://api.bing.microsoft.com/"

if task.url and task.url.startswith(BING_ENDPOINT):
    return bing_news_fact_check(task)
return None
```

If we used Bing APIs in different ways for different tasks, we would use the path of the `task.url`, or perhaps values in `task.flags`, to determine which method to call. Here we only have one Bing method, `bing_news_fact_check`, found in [bing.py](./missions/plugins/bing.py)

That method expects the outputs of our previous task: `a JSON list of strings, with the first string being a one-sentence summary of the article`, to quote that task's prompt. It uses the convenience method `get_json_from` in `util.py` to unwrap the LLM's response into JSON, then, for each fact, searches Bing News for corresponding articles. Note that it searches with 'textDecoration: True," which means the resulting URLs actually include relevant text from the linked aricles - this is a cheap way to get around having to scrape each individual article.

It's worth noting that we could limit Bing to particular news sources the user considers trustworthy, e.g. only Fox News or only The New York Times depending on your political slant, by setting `bing_site` to `nytimes.com` or `foxnews.com` in the task's `flags`. (One [could also](https://support.microsoft.com/en-us/topic/advanced-search-keywords-ea595928-5d63-4a0b-9c6b-0b769865e78a) OR multiple sites together but this is left as a coding exercise for the reader.)

It's also worth noting though that we _could_ scrape each article, though; indeed we could create a new Task for each individual fact. It is common, useful, and powerful for Tasks to create other Tasks mid-mission, and have all those Tasks feed into our final report. Here, though, to keep thing simple, we just stuff all those Bing News search outputs into a single blob of text, in —

### 4b. The Fact-Check API Task

Since all of the work is really done in `bing_news_fact_check`, the YAML here is just what we need to route the Task to that method:

```yaml
  - sources:
      name: Sources for Claims
      parent: claims
      category: API
      base_url: https://api.bing.microsoft.com/
```

Note that the `base_url` will become the `url` for the task, which our Bing plugin will recognize as the signal that it should run, and that because its `parent` is _claims_, the previous list of claims will be used as the inputs for the Bing News searches.

## 5. Final Report: The Fact Check

We are, in fact, now done! There is one more task - every mission has an implicit Final Report LLM task, generated when all of its previous tasks are complete - but we have already defined it, its prompt, and which LLM to use, in the mission YAML up top.

## 6. Putting It All Together

The complete YAML for this mission type can be found in [fact_check.yaml](./missions/management/fact_check.yaml). Only 36 lines to define code and prompts that will scrape any arbitrary web site, assemble a list of factual claims, run Bing News searches on each claim, and summarize the support / verification, or lack thereof, for each of those claims! Not bad.

To run this locally, with YamLLMs set up, you need merely import that YAML so as to create a Mission Template in your local database

`python manage.py import --file "missions/management/fact_check.yaml"`

and then use the `fact_check` command to fact-check any URL, e.g.

`python manage.py run_mission --name="Fact Check" --url "https://site.com/blog-post-to-fact-check/"`

Note that we could also use our generic `run_mission` command:

`python manage.py run_mission --name="Fact Check" --flag_name=mission_url --flag_val=https://techcrunch.com/2024/11/25/tesla-appears-to-be-building-a-teleoperations-team-for-its-robotaxi-service/`

## 7. Next Steps

This is obviously a very simple and crude form of fact-checking. But it should illustrate how you can use YamLLMs as a very lightweight framework to configure, run, and persist arbitrary kinds/numbers of simple LLM tasks, and also chain tasks together into a sophisticated pipelines including many different API fetches and LLM processing steps.
