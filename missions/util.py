import datetime
import json
import logging
from types import SimpleNamespace

import stripe
import tiktoken
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from google.generativeai.generative_models import GenerativeModel  # type: ignore

logger = logging.getLogger(__name__)

SCRAPE_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "3600",
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/55.0",
}

ARXIV_PREFIX = "https://arxiv.org/"
GITHUB_PREFIX = "https://github.com/"
LINEAR_API = "https://api.linear.app/graphql"
NOTION_API = "https://api.notion.com"
SLACK_API = "https://slack.com/api"
ATLASSIAN_API = "https://api.atlassian.com/"
JIRA_API = "https://api.atlassian.com/jira"
CONFLUENCE_API = "https://api.atlassian.com/confluence"
AZURE_API = "https://dev.azure.com"
FIGMA_API = "https://api.figma.com/v1"
HARVEST_API = "https://api.harvestapp.com/v2"
FORECAST_API = "https://api.forecastapp.com"
GOOGLE_CHAT_API = "https://chat.googleapis.com"
MONDAY_API = "https://api.monday.com/v2"
SENTRY_API = "https://sentry.io/api/0"

YAML_DIVIDER = "\n\n---\n\n"
FINAL_TASK_DIVIDER = "\n\n---\n\n"

# custom URLs for individual task types
BASE_PREFIX = "https://" + settings.BASE_DOMAIN
KEY_CONTEXT_URL = BASE_PREFIX + "/context"
AGENT_PREFIX = BASE_PREFIX + "/agent"
AGENT_REPORT_URL = BASE_PREFIX + "/agent/report"
BASE_RISK_URL = BASE_PREFIX + "/risk"
ASSESS_RISK_URL = BASE_PREFIX + "/risk/assess"
RISK_RATING_URL = BASE_PREFIX + "/risk/rating"
QUANTIFY_RISK_URL = BASE_PREFIX + "/risk/quantify"
TAXONOMIZE_PROJECTS_URL = BASE_PREFIX + "/taxonomize"
GENERAL_EVAL_URL = BASE_PREFIX + "/eval/general"
DATA_CHECK_URL = BASE_PREFIX + "/eval/data_check"
REPORT_FACT_LIST_URL = BASE_PREFIX + "/eval/fact_list"
ALL_REPORTS_URL = BASE_PREFIX + "/all_reports"
EMAIL_TASK_URL = BASE_PREFIX + "/email"

TEST_MODEL = "gpt-4-test"
TEST_MODEL_MISTRAL = "mistral-test"
TEST_MODEL_CLAUDE = "claude-test"
TEST_LLMS = [TEST_MODEL, TEST_MODEL_MISTRAL, TEST_MODEL_CLAUDE]

GPT_4_BASE = "gpt-4"
GPT_4_TURBO = "gpt-4-turbo"
GPT_4O_BASE = "gpt-4o"
GPT_4O = "gpt-4o-2024-08-06"
GPT_4O_MINI = "gpt-4o-mini"
O1_PREVIEW = "o1-preview"
O1_MINI = "o1-mini"
O1 = "o1"
O3_MINI = "o3-mini"
OPENAI_MODELS = [
    GPT_4_BASE,
    GPT_4O_BASE,
    GPT_4_TURBO,
    GPT_4O,
    GPT_4O_MINI,
    O1_PREVIEW,
    O1_MINI,
    O1,
    O3_MINI,
]

GPT_4O_AZURE = "gpt-4o-azure"
GPT_4O_AZURE_MINI = "gpt-4o-mini-azure"
AZURE_MODELS = [GPT_4O_AZURE, GPT_4O_AZURE_MINI]

VISION_MODEL = GPT_4O
EVALUATION_MODEL = GPT_4O_MINI

GEMINI_1_PRO = "gemini-1.0-pro"
GEMINI_1_5_PRO = "gemini-1.5-pro"
GEMINI_1_5_FLASH = "gemini-1.5-flash"
GEMINI_1_VISION = "gemini-pro-vision"
GEMINI_MODELS = [GEMINI_1_PRO, GEMINI_1_5_PRO, GEMINI_1_VISION, GEMINI_1_5_FLASH]

MISTRAL_MODEL = "mistral-medium"
MISTRAL_MODELS = [MISTRAL_MODEL]

CLAUDE_OPUS = "claude-3-opus-20240229"
CLAUDE_SONNET = "claude-3-5-sonnet-20241022"
CLAUDE_SONNET_LATEST = "claude-3-5-sonnet-latest"
CLAUDE_HAIKU = "claude-3-5-haiku-20241022"
CLAUDE_HAIKU_LATEST = "claude-3-5-haiku-latest"
CLAUDE_MODELS = [
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    CLAUDE_HAIKU,
    CLAUDE_HAIKU_LATEST,
    CLAUDE_SONNET_LATEST,
]

DEEPSEEK_MODEL = "deepseek-reasoner"

NEMOTRON_70B = "nvidia/llama-3.1-nemotron-70b-instruct"
NEMOTRON_MODELS = [NEMOTRON_70B]

# note these include prompt and response, and we add some buffer
TOKEN_LIMITS = {
    TEST_MODEL: 16384,
    TEST_MODEL_MISTRAL: 16384,
    GPT_4_BASE: 16384,
    GPT_4_TURBO: 120000,
    GPT_4O_BASE: 120000,
    GPT_4O: 120000,
    GPT_4O_MINI: 120000,
    GPT_4O_AZURE: 120000,
    GPT_4O_AZURE_MINI: 120000,
    O1_PREVIEW: 100000,
    O1_MINI: 100000,
    O1: 100000,
    O3_MINI: 100000,
    MISTRAL_MODEL: 32768,
    GEMINI_1_PRO: 32768,
    GEMINI_1_VISION: 32768,
    GEMINI_1_5_FLASH: 1000000,
    GEMINI_1_5_PRO: 1000000,
    CLAUDE_SONNET: 192000,
    CLAUDE_SONNET_LATEST: 192000,
    CLAUDE_OPUS: 192000,
    CLAUDE_HAIKU: 192000,
    CLAUDE_HAIKU_LATEST: 192000,
    NEMOTRON_70B: 120000,
}
MAX_THREADED_MSG_LENGTH = 28768  # actually 32K but we want to be safe and not have one message overwhelm the context
MINIMUM_RESERVED_TOKENS = 8192

MAX_WINDOW_TASKS = 52  # maximum to create in a time window; 52 weeks in a year

MAX_CADENCE_DAYS = 14

LINK_SUFFIXES = [
    ".txt",
    ".md",
    ".html",
    ".json",
    ".yaml",
    ".toml",
    ".yml",
    ".csv",
    ".py",
    ".rs",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".java",
    ".c",
    ".cpp",
    ".rb",
    ".h",
    ".hpp",
    ".go",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".php",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".xml",
    ".swift",
    ".vb",
    ".asp",
    ".aspx",
    ".pl",
    ".m",
    ".ipynb",
    ".kt",
    ".swift",
]

EXCLUDE_FROM_TREE = [
    "node_modules/",
    "web_modules/",
    "plugins/",
    "upload/",
    "uploads/",
    "build/",
    "_build/",
    ".build/",
    "cache/",
    "_cache/",
    ".cache/",
    ".yarn/",
    ".git/",
    "dist/",
    "release/",
    "DerivedData",
    "Packages/",
    "Pods/",
    "Carthage/",
    "Dependencies/",
    "fastlane/",
    "xcuserdata/",
    "tmp/",
    "log/",
    "downloads/",
    "vendor/",
    "__pycache__/",
    ".dSYM/",
    ".tmp_versions/",
    ".DS_Store",
    ".jpg",
    ".png",
    ".svg",
    ".webp",
    ".exe",
    ".dll",
    ".jar",
    ".zip",
    ".war",
    ".tar",
    ".gz",
    ".class",
    ".log",
    ".ttf",
    ".otf",
    ".eot",
    ".woff",
    ".woff2",
]

ALL_INTEGRATIONS = [
    "github",
    "linear",
    "jira",
    "confluence",
    "notion",
    "slack",
    "figma",
    "azure",
    "gchat",
    "monday",
    "harvest",
    "forecast",
    "sentry",
]

PROMPT_KEYS = [
    "README",
    "commits",
    "pulls",
    "figma",
    "jira",
    "linear",
    "monday",
    "notion",
    "slack",
    "assess-pulls",
    "assess-files",
    "harvest",
    "forecast",
    "gchat",
]

LOGIN_EMAIL = """\
Hello,

You requested that we send you a link to log into YamLLMs:

    %s

Enjoy!
"""

PR_DIFF_PROMPT = """\
# Pull Request Diff

What follows is the diff of _all_ the changes in the pull request.
This should be more than sufficient for a detailed assessment of the code quality.

---

%s

"""

GENERIC_MISSION = "GitHub Repo Analysis"
EXAMPLE_URL = "https://www.example.com/url"

MAX_PR_RATINGS = 10


def email_ops(subject, body, html=None, fail_silently=True):
    log("Sending email to ops", subject)
    email = EmailMultiAlternatives(
        from_email=settings.DEFAULT_FROM_EMAIL,
        reply_to=[settings.REPLY_TO_EMAIL],
        to=[settings.NOTIFICATION_EMAIL],
        subject=subject,
        body=body,
    )
    if html:
        email.attach_alternative(html, "text/html")
    email.send(fail_silently=fail_silently)
    log("sent")


def email_eval_failure(eval, evaluated, errors, email_to):
    log("Sending evaluation failure", eval, "to", email_to)
    body = f"Task {evaluated} in mission {eval.mission} failed evaluaion: \n {errors}"
    email = EmailMultiAlternatives(
        from_email=settings.DEFAULT_FROM_EMAIL,
        reply_to=[settings.REPLY_TO_EMAIL],
        to=[email_to],
        subject="Evaluation failure: %s" % eval.name,
        body=body,
    )
    email.send(fail_silently=settings.DEBUG)
    log("sent")


def get_provider_llm(llm, use_azure_mini=True):
    if settings.USE_AZURE_OPENAI:
        if llm == "gpt-4o-mini":
            if use_azure_mini:
                return GPT_4O_AZURE_MINI
        elif llm and llm.startswith("gpt-4o"):
            return GPT_4O_AZURE
    return llm


def get_token_limit_for(llm):
    minimum = MINIMUM_RESERVED_TOKENS
    minimum = minimum / 2 if llm == GPT_4_BASE else minimum
    if llm in TOKEN_LIMITS:
        return TOKEN_LIMITS[llm] - minimum
    elif llm.startswith("ft:gpt-4o-mini"):  # fine-tuned models
        return TOKEN_LIMITS[GPT_4O_MINI] - minimum
    raise Exception("No token limit found for %s" % llm)


# Used to not overload the contet window with massive data
# TODO flags to handle excessive inputs in ways other than truncating
def get_sized_prompt(task, prompt, truncate_to=None):
    llm = task.get_llm()
    tokens = token_count_for(prompt, llm)
    task.extras["input_length"] = len(prompt)
    task.extras["input_tokens"] = tokens
    task.extras["truncated"] = False
    max_input_tokens = get_token_limit_for(llm)
    if tokens > max_input_tokens:
        encoding = encoding_for(llm)
        fraction = max_input_tokens / tokens
        prompt = prompt[: int(fraction * len(prompt))]
        prompt = prompt.rpartition(" ")[0] + "\n\n---\n\n Input truncated."
        truncated_tokens = encoding.encode_ordinary(prompt)
        task.extras["truncated_length"] = len(prompt)
        task.extras["truncated_tokens"] = len(truncated_tokens)
        task.extras["truncated"] = True
    task.save()
    return prompt


def encoding_for(llm):
    llm_encoding = llm
    # TODO different token counters for different models
    for prefix in ["gpt-4", "o1-", "mistral", "gemini", "claude", "nvidia/llama"]:
        if llm.startswith(prefix):
            llm_encoding = "gpt-4"
    return tiktoken.encoding_for_model(llm_encoding)


def token_count_for(text, llm="gpt-4"):
    if llm.startswith("gemini"):
        model = GenerativeModel(llm)
        count = model.count_tokens(text)
        return count.total_tokens

    encoding = encoding_for(llm)
    try:
        tokens = encoding.encode_ordinary(text)
    except Exception as ex:
        # there's a tiktoken bug, fake it by having tokens be half the prompt
        log("Failed to encode prompt", ex)
        tokens = text[: len(" %s " % text) // 2]
    return len(tokens)


def is_too_long(text, llm):
    tokens = token_count_for(text, llm)
    max_input_tokens = get_token_limit_for(llm)
    return tokens > max_input_tokens


def get_year_of(vals, key=None):
    iso = vals if key == None else vals.get(key, None)
    dt = datetime.datetime.fromisoformat("%s" % iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.year


def get_days_between(later, former):
    delta = later - former
    return delta.days + round(delta.seconds / 86400)


def get_days_since(vals, key=None):
    if not vals:
        return None
    iso = (
        vals
        if key == None or isinstance(vals, str) or isinstance(vals, int)
        else vals.get(key, None)
    )
    if not iso:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    then = datetime.datetime.fromisoformat("%s" % iso)
    if then.tzinfo is None:
        then = then.replace(tzinfo=datetime.timezone.utc)
    return get_days_between(now, then)


def get_days_ago(dict, key=None):
    days_since = get_days_since(dict, key)
    if days_since is None:
        return None
    elif days_since < 0:
        r = "%s days away" % days_since
        return r[1:]  # lose the minus sign
    elif days_since == 0:
        return "0 days ago"
    elif days_since == 1:
        return "1 day ago"
    else:
        return "%s days ago" % days_since


def get_edit_days_ago(dict, edit_key, create_key):
    created_days = get_days_since(dict, create_key)
    edited_days = get_days_since(dict, edit_key)
    if edited_days == created_days:
        return ""
    return get_days_ago(dict, edit_key)


# TODO: return HTML not Markdown for Anthropic, etc., for these
# we don't use h1 within the data, those are used for framing the data


# dataset title
def h2(text):
    return f"\n\n## {text}\n"


# dataset metadata and/or sections/groups
def h3(text):
    return f"\n### {text}\n"


# individual atomic items e.g. PRs, commits, allocations, files, etc., suitable for later recombination
def h4(text):
    return f"\n<!--DAI4-->\n#### {text}\n"


# metadata or sub-groups within an item
def h5(text):
    return f"\n##### {text}\n"


def is_sqlite():
    return settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"


def rename(name):
    if not name:
        return ""
    renamed = name.replace("Fetch ", "")
    return renamed.capitalize() if renamed != name else name


def get_scrape_url_from(item):
    url = item.get("url", "").strip()
    if not url:
        url = item.get("name", "").strip()
    if url.startswith("/"):
        if "/abs/" in url or "/list/" in url:
            url = ARXIV_PREFIX + url
    elif len(url) == 5 and url[2] == ".":
        url = ARXIV_PREFIX + "/list/" + url
    return url


def get_file_intro(name, data):
    d = data or ""
    r = "What follows is the (possibly truncated) source file: %s\n" % name
    r += f"It is {len(d.splitlines())} lines long and comprised of {len(d)} characters.\n---\n\n"
    return r


def combine_devs(d1, d2):
    commits = d1.get("commits", [])
    opened = d1.get("prs_opened", 0) + d2.get("prs_opened", 0)
    merged = d1.get("prs_merged", 0) + d2.get("prs_merged", 0)
    closed = d1.get("prs_closed", 0) + d2.get("prs_closed", 0)
    d1 = d1 | d2
    new_commits = d2.get("commits", [])
    existing_ids = [c["sha"] for c in commits]
    for c in new_commits:
        if c["sha"] not in existing_ids:
            commits.append(c)
    d1["commits"] = commits
    d1["prs_opened"] = opened
    d1["prs_closed"] = closed
    d1["prs_merged"] = merged
    return d1


def concatenate_dev_data(tasks):
    log("Concatenating dev data", tasks)
    all_devs = {}
    tasks_with_devs = set()

    for t in tasks:
        for dep in [t] + t.prerequisite_tasks():
            devs = dep.structured_data.get("devs", {})
            if devs:
                tasks_with_devs.add(dep)

    for t in list(tasks_with_devs):
        devs = t.structured_data.get("devs", {})
        for key in devs:
            if key not in all_devs:
                all_devs[key] = devs[key]
            else:
                dev = all_devs[key]
                new_dev = devs[key]
                all_devs[key] = combine_devs(dev, new_dev)
    return all_devs


def combine_devs_by_name(devs):
    names = set()
    for key in devs:
        dev = devs[key]
        if "name" in dev:
            names.add(dev["name"])
        else:
            log("No name found for", key, dev)
    devs_by_name = {}
    for name in names:
        combined = {}
        for key in devs:
            dev = devs[key]
            if "name" in dev and dev["name"] == name:
                combined = combine_devs(combined, dev)
        devs_by_name[name] = combined
    return devs_by_name


def get_dev_data_totals(task, since_days):
    devs = task.structured_data.get("devs", {})
    all_files = set()
    all_commits = []
    for dev in devs:
        commits = devs[dev].get("commits", [])
        all_commits += [
            c for c in commits if c["type"] == "normal" and c["days_ago"] <= since_days
        ]
        for file in devs[dev].get("files", []):
            all_files.add(file)
    total_changes = sum([c["changes"] for c in all_commits])
    total_prs_opened = sum([c.get("prs_opened", 0) for c in all_commits])
    total_prs_merged = sum([c.get("prs_merged", 0) for c in all_commits])
    return {
        "devs": len(devs),
        "commits": len(all_commits),
        "changes": total_changes,
        "files": len(all_files),
        "opened": total_prs_opened,
        "merged": total_prs_merged,
    }


def get_jira_projects_from(jira, task=None):
    if not jira:
        jira = task.get_integration("jira")
    jira_projects = []
    root = jira.project if jira.project else jira.customer
    if root:
        project_value = root.extras.get("jira")
        if project_value:
            jira_projects = (
                json.loads(project_value)
                if project_value.startswith("[")
                else [project_value]
            )
    return jira_projects


def get_jira_url_from(jira, task=None):
    if not jira:
        jira = task.get_integration("jira")
    if jira:
        accessible = jira.extras.get("accessible", [])
        if accessible and isinstance(accessible, list):
            accessible = accessible[0]
            return accessible["url"] if "url" in accessible else None


def source_from_task(obj):
    url = ""
    if hasattr(obj, "url"):
        url = obj.url
    if hasattr(obj, "base_url"):
        url = obj.base_url
    if not url:
        return {}

    name = ""
    link = ""
    vendor = ""
    if "github.com" in url:
        name = "GitHub"
        vendor = "github"
        link = GITHUB_PREFIX
        repo = obj.get_repo()
        if repo:
            link = GITHUB_PREFIX + repo
            name = "GitHub — %s" % repo

    elif "api.atlassian" in url:
        name = "Jira"
        vendor = "jira"
        if "confluence" in url:
            name = "Confluence"
            vendor = "confluence"
        if hasattr(obj, "get_project_value"):
            name = "Jira %s" % obj.get_project_value("jira", "")
            link = get_jira_url_from(None, obj)
        if not link:
            link = ATLASSIAN_API
    elif "api.notion" in url:
        name = "Notion"
        vendor = "notion"
        link = "https://notion.so/"
    elif "api.linear" in url:
        name = "Linear"
        vendor = "linear"
        link = "https://linear.app/"
    elif "api.figma" in url:
        name = "Figma"
        vendor = "figma"
        link = "https://figma.com/"
    elif "slack.com/api" in url:
        name = "Slack"
        vendor = "slack"
        link = "https://slack.com/"
    elif "dev.azure.com" in url:
        name = "Azure DevOps"
        vendor = "azure"
        link = "https://dev.azure.com/"
    elif "chat.googleapis.com" in url:
        name = "Google Chat"
        vendor = "gchat"
        link = "https://chat.google.com/"
    elif "harvestapp.com" in url:
        name = "Harvest"
        vendor = "harvest"
        link = "https://harvestapp.com/"
    elif "forecastapp.com" in url:
        name = "Forecast"
        vendor = "harvest"
        link = "https://forecastapp.com/"
    elif "api.monday" in url:
        name = "Monday"
        vendor = "monday"
        link = "https://monday.com/"
    elif url.startswith(BASE_PREFIX):
        suffix = url.split("/")[-1]
        if suffix == "pulls":
            name = "GitHub"
            vendor = "github"
            link = GITHUB_PREFIX
        elif suffix == "issues":
            name = "Jira"
            vendor = "jira"
            if hasattr(obj, "get_project_value"):
                name = "Jira %s" % obj.get_project_value("jira", "")
                link = get_jira_url_from(None, obj)
    return {"name": name, "vendor": vendor, "link": link}


def order_sub_reports(tasks):
    # they come in ordered by "order"
    # for tasks with the same order:
    # ensure quantify tasks come after corresponding report tasks
    # ensure context tasks come early, detail tasks later
    for idx, t in enumerate(tasks):
        t.dynamic_order = t.order * 10000 + idx * 100
    for t in tasks:
        if t.is_aggregate():
            t.dynamic_order -= 9000
        else:
            dep = t.default_ordering_info()
            if dep and dep.get("url"):
                url = dep.get("url", "")
                if "confluence" in url or "notion" in url:
                    t.dynamic_order -= 8500
                if "jira" in url or "linear" in url:
                    t.dynamic_order -= 8000
                if "github" in url and "readme" in url:
                    t.dynamic_order -= 7500
                if "github" in url and "issues" in url:
                    t.dynamic_order -= 7000
                if "github" in url and "pulls" in url:
                    t.dynamic_order -= 6500
    return sorted(tasks, key=lambda x: x.dynamic_order)


def get_dev_summary(dev):
    commits = dev.get("commits", [])
    commits = [c for c in commits if c["type"] == "normal"]
    files = set()
    [files.update(c["files"]) for c in commits]
    vals = {
        "name": dev.get("name"),
        "link": dev.get("link", ""),
        "avatar": dev.get("avatar", ""),
        "commits": len(commits),
        "changes": sum([c["changes"] for c in commits]),
        "files": len(files),
        "branches": len(set([c["branch"] for c in commits])),
        "pr_branches": len(dev.get("pr_branches", [])),
        "prs_opened": dev.get("prs_opened", 0),
        "prs_merged": dev.get("prs_merged", 0),
        "prs_closed": dev.get("prs_closed", 0),
        "prs": f"{dev.get('prs_opened', 0)}/{dev.get('prs_merged', 0)}/{dev.get('prs_closed', 0)}",
    }
    return SimpleNamespace(**vals)


def get_dev_diff(dev, prev):
    vals = {
        "commits": dev.commits - prev.commits,
        "changes": dev.changes - prev.changes,
        "files": dev.files - prev.files,
        "branches": dev.branches - prev.branches,
        "prs_opened": dev.prs_opened - prev.prs_opened,
        "prs_merged": dev.prs_merged - prev.prs_merged,
        "prs_closed": dev.prs_closed - prev.prs_closed,
    }
    for key, val in vals.items():
        if isinstance(val, int):
            if val > 0:
                val = "+%s" % val
            if val == 0:
                val = "="
        vals[key] = "%s" % val
    vals["prs"] = f"{vals['prs_opened']}/{vals['prs_merged']}/{vals['prs_closed']}"
    return SimpleNamespace(**vals)


def get_repo_name_from_url(url):
    if not url.startswith(GITHUB_PREFIX):
        return None
    parts = url.replace(GITHUB_PREFIX, "").split("/")
    return None if len(parts) < 2 else "/".join(parts[:2])


def correct_name(mission):
    name = mission.name
    if mission.flags.get("repo_in_name") == "true":
        target = mission.get_repo()
        if target and target not in name:
            name = f"{name}: {target}"
    if mission.is_duplicate() and not name.endswith(" (Copy)"):
        name += " (Copy)"
    return name


def get_json_from(response_text):
    response_text = response_text or ""
    if response_text.find("<output>") > -1:
        return response_text.split("<output>")[1].split("</output>")[0].strip()
    if response_text.find("<result>") > -1:
        return response_text.split("<output>")[1].split("</result>")[0].strip()
    if response_text.find("```json") > -1:
        return response_text.split("```json")[1].split("```")[0].strip()
    if response_text.find("```") > -1:
        return response_text.split("```")[1].split("```")[0].strip()
    if response_text and response_text[0] not in "{[":
        extracted = extract_first_json(response_text)
        return extracted or response_text
    return response_text


def extract_first_json(text):
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char in "{[":
            try:
                # Attempt to decode a JSON blob starting at this index.
                obj, _ = decoder.raw_decode(text[i:])
                return obj
            except json.JSONDecodeError:
                # Not valid JSON at this position, keep scanning.
                continue
    return None  # No valid JSON blob found.


def get_json_from_raw(raw, array_expected=False):
    ends = ""
    if not raw.startswith("{") or raw.startswith("["):
        try:
            square = raw.index("[")
        except ValueError:
            square = len(raw)
        try:
            angle = raw.index("{")
        except ValueError:
            angle = len(raw)
        min_index = min(square, angle)
        raw = raw[min_index:]

        ends = "]" if square < angle else "}"
        if not raw.endswith(ends):
            raw = raw[: raw.rindex(ends) + 1]
        if ends == "}" and array_expected:
            raw = "[%s]" % raw
    return raw


def log(message, *args):
    print(message, *args)


def get_task_urls_for(post, type, repos=[]):
    vals = post.getlist(type, [])
    urls = []
    for val in vals:
        if type == "tasks":
            val = get_task_url_for(val)
            urls.append(val)
        elif type == "github":
            for repo in repos:
                urls.append(GITHUB_PREFIX + "%s/%s" % (repo, val))
        elif type == "azure":
            for repo in repos:
                urls.append(AZURE_API + "/%s/%s" % (repo, val))
    return urls


def get_task_url_for(val):
    if val == "github":
        return GITHUB_PREFIX
    if val == "azure":
        return AZURE_API
    if val == "jira":
        return JIRA_API + "/issues"
    if val == "jira/quantify":
        return JIRA_API + "/issues/epics"
    if val == "jira/epics":
        return JIRA_API + "/issues/epics"
    if val == "linear":
        return LINEAR_API + "/issues"
    if val == "monday":
        return MONDAY_API
    if val == "notion":
        return NOTION_API + "/pages"
    if val == "confluence":
        return CONFLUENCE_API + "/pages"
    if val == "figma":
        return FIGMA_API
    if val == "figma/quantify":
        return FIGMA_API + "/quantify"
    if val == "slack":
        return SLACK_API + "/channels"
    if val == "gchat":
        return GOOGLE_CHAT_API + "/spaces"
    if val == "harvest":
        return HARVEST_API
    if val == "forecast":
        return FORECAST_API
    if val == "sentry":
        return SENTRY_API


def stripe_url_for_project(project, url_type):
    if not project.stripe_subscription_id:
        logger.warning(f"Project {project.id} has no Stripe subscription ID")
        return ""

    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        url_type = "subscription_%s" % url_type
        url_info = stripe.billing_portal.Session.create(
            customer=project.customer.stripe_customer_id,
            return_url=BASE_PREFIX + "/config/account",
            flow_data={
                "type": url_type,
                url_type: {"subscription": project.stripe_subscription_id},
                "after_completion": {
                    "type": "redirect",
                    "redirect": {
                        "return_url": f"{BASE_PREFIX}/config/configure?project_id={project.id}"
                    },
                },
            },
        )
        return url_info.url
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error for project {project.id}: {str(e)}")
