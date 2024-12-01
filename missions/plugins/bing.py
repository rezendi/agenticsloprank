import time, os, requests
from ..util import *
from missions import plugins

BING_ENDPOINT = "https://api.bing.microsoft.com/"
BING_NEWS_SEARCH_ENDPOINT = "https://api.bing.microsoft.com/v7.0/news/search"


@plugins.hookimpl
def run_api(task):
    if task.url and task.url.startswith(BING_ENDPOINT):
        return bing_news_fact_check(task)


def get_bing(task, integration=None):
    if not integration:
        integration = task.get_integration("bing")
    if integration:
        access_token = integration.secret_set.last()
    else:
        access_token = os.environ.get("BING_NEWS_API_TOKEN")
    if not access_token:
        raise Exception("No Bing token found")
    return access_token


def bing_news_fact_check(task):
    fact_task = task.parent
    if not fact_task or not fact_task.response:
        raise Exception("No fact list found")

    json_facts = get_json_from(fact_task.response or "[]")
    fact_list = json.loads(json_facts)
    if not fact_list or len(fact_list) < 2:
        raise Exception("Empty fact list")

    headline = fact_list[0]
    facts = fact_list[1:]

    retval = []
    for fact in facts:
        check = bing_news_search(task, headline, fact)
        retval.append({"fact": fact, "sources": check})
        time.sleep(1)

    # OK, we have the facts and sources in structured data
    # and thanks to "hit highlighting" we shouldn't need to scrape any more
    # https://learn.microsoft.com/en-us/bing/search-apis/bing-web-search/hit-highlighting
    # we could format what we have as Markdown here, but the LLM should interpret the JSON fine
    task.response = retval
    return task.response


# see https://learn.microsoft.com/en-us/bing/search-apis/bing-news-search/how-to/search-for-news
def bing_news_search(task, headline, fact):
    access_token = get_bing(task)
    headers = {"Ocp-Apim-Subscription-Key": access_token}

    # see https://support.microsoft.com/en-us/topic/advanced-search-keywords-ea595928-5d63-4a0b-9c6b-0b769865e78a
    # e.g. to search nytimes only, set {"bing_site":"nytimes.com"} in task.flags
    query = ": ".join([headline, fact])
    for operator in ["site", "contains", "ext", "filetype", "ip", "loc", "prefer"]:
        if task.flags.get("bing_%s" % operator):
            query += f" {operator}:{task.flags['bing_%s' % operator]}"

    params = {
        "q": query,
        "count": 3,
        "textDecorations": True,
        "textFormat": "HTML",
    }
    response = requests.get(BING_NEWS_SEARCH_ENDPOINT, headers=headers, params=params)
    response.raise_for_status()
    structured_data = task.structured_data or {"facts": []}
    structured_data["facts"].append(response.json())
    task.structured_data = structured_data
    return task.structured_data
