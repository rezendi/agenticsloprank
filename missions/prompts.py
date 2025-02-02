from .plugins.github import *
from .util import *


# 'key' is often an URL
def get_prompt_from_github(key):
    log(f"Getting prompt for %s" % key)
    if not key:
        log("Warning: no prompt key, returning empty prompt")
        return ""
    if key.lower().endswith("readme"):
        key = "README-prompt"
    if key.startswith(LINEAR_API):
        key = "linear"
    if key.startswith(MONDAY_API):
        key = "monday"
    if key.startswith(NOTION_API):
        key = "notion"
    if key.startswith(SLACK_API):
        key = "slack"
    if key.startswith(JIRA_API):
        key = "jira"
    if key.startswith(CONFLUENCE_API):
        key = "confluence"
    if key.startswith(FIGMA_API):
        key = "figma"
    if key.startswith(FORECAST_API):
        key = "forecast"
    if key.startswith(HARVEST_API):
        key = "harvest"
    if key.startswith(GOOGLE_CHAT_API):
        key = "gchat"
    filename = key.split("/")[-1] + ".md"  # convert url to its suffix
    if cache.get("prompt_%s" % filename):
        return cache.get("prompt_%s" % filename)
    token = os.environ.get("GITHUB_TOKEN")
    auth = github.Auth.Token(token)
    gh = github.Github(
        auth=auth,
        user_agent="PyGitHub/Python|YamLLMs|info@" + settings.BASE_DOMAIN,
    )
    repo = gh.get_repo(settings.GITHUB_PROMPTS_REPO)
    prompt = get_gh_file(repo, {"name": filename})
    cache_minutes = 1 if settings.DEBUG or settings.TESTING else 60
    try:
        cache.set("prompt_%s" % filename, prompt, cache_minutes * 60)
    except Exception as e:
        log("Error caching prompt", e)
    return prompt
