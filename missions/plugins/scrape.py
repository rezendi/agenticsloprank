import json, requests, time

from bs4 import BeautifulSoup
from bs4.element import Comment
from ..util import *
from missions.models.base import TaskCategory
from missions import plugins

TEXTUAL = ["style", "script", "head", "title", "meta", "[document]"]


@plugins.hookimpl
def run_scrape(task):
    if task.parent:
        return scrape_task(
            task,
            task.parent.category == TaskCategory.LLM_DECISION,
            task.parent.response,
        )
    else:
        return scrape_task(task, False, "")


# Probably the messiest of all the fetch methods, thanks to the messy nature of the web
# Uses values in the task's "extras" to determine what to extract and what to delete
def scrape_task(task, is_decision, dep_response):
    urls = [task.url]
    if is_decision:
        # we get JSON but can't be entirely sure about the format at the moment
        # so we keep going down the JSON hierarchy until we find URL(s)
        try:
            response = get_json_from(dep_response)
            vals = json.loads(response)
            if isinstance(vals, list):
                urls = [get_scrape_url_from(item) for item in vals]
            elif len(vals.keys()) == 1:  # array within a dict
                key = list(vals.keys())[0]
                if key != "url":
                    vals = vals[key]
                if isinstance(vals, list):
                    urls = [get_scrape_url_from(item) for item in vals]
            else:  # dict with multiple keys, assume one is the URL
                urls = [get_scrape_url_from(vals)]
        except Exception as ex:
            log("Could not parse categorization JSON", ex)
            task.add_error(ex, "%s" % response)

    task.structured_data["urls"] = urls
    if task.is_test():
        log("Test task, not scraping")
        task.response = "Test scrape response"
        task.save()
        return task.response

    task.response = "" if not task.response else task.response
    for url in urls:
        url = url + task.flags.get("url-suffix", "")
        req = requests.get(url, SCRAPE_HEADERS)
        log("url", url, "status", req.status_code)
        raw = req.text
        if task.flags.get("custom_scrape") != "true":  # just dump the visible text
            task.response += scrape_text(task, raw)
        else:  # various complex options
            task.response += custom_scrape(task, raw)

        if not task.is_test():
            time.sleep(0.5)  # don't hammer the server too hard

    return task.response


def scrape_text(task, raw):
    soup = BeautifulSoup(raw, "html.parser")
    retval = ""
    for i in soup.stripped_strings:
        retval += repr(i) + "\n"
    return retval


def custom_scrape(task, raw):
    # strip unwanted start/end blocks if specified and found
    delim = task.flags.get("content-start")
    idx = raw.index(delim) if delim and delim in raw else -1
    raw = raw[idx:] if idx >= 0 else raw
    delim = task.flags.get("content-end")
    idx = raw.index(delim) if delim and delim in raw else -1
    raw = raw[:idx] if idx >= 0 else raw

    soup = BeautifulSoup(raw, "html.parser")
    if task.flags.get("content-only") == "meta":
        title = soup.find("meta", property="og:title")["content"]
        # override meta-title with title if available
        if soup.find("title"):
            title = soup.find("title").text
        description = soup.find("meta", property="og:description")["content"]
        return f"\n### {title}\n{description}\n\n"

    if task.flags.get("content-decompose"):
        for to_delete in task.extras.get("content-decompose"):
            log("deleting", to_delete)
            for div in soup.find_all("div", {"class": to_delete}):
                div.decompose()

    wipes = task.flags.get("content-wipes", [])
    if task.flags.get("content-only-links"):
        prefix = task.extras.get("content-only-links")
        all_links = soup.find_all("a")
        our_links = []
        for link in all_links:
            if link.get("href", "").startswith(prefix) and not link.text in wipes:
                our_links.append(link)
        for link in our_links:
            if link.text in wipes:
                our_links.remove(link)
        return "\n".join([f"[{l.text}]({l.get('href')})" for l in our_links]) + "\n\n"

    texts = soup.findAll(text=True)
    visible_texts = filter(
        lambda x: (x.parent.name not in TEXTUAL and not isinstance(x, Comment)),
        texts,
    )
    visible_text = " ".join(t.strip() for t in visible_texts if t)
    for wipe in wipes:
        visible_text = visible_text.replace(wipe, "")

    visible_text = " ".join(visible_text.split())
    retval += visible_text + "\n\n"
    if task.flags.get("task_title"):
        retval = "## %s\n%s" % (task.flags["task_title"], retval)

    return retval
