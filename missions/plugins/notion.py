import os
from notion_client import Client
from notion_client.helpers import is_full_page, is_full_block
from ..util import *
from missions import plugins
from types import SimpleNamespace

# if we're in a time series, ignore pages older than this, otherwise, go back a year
TIME_SERIES_CONTEXT_DAYS = 60
CONTEXT_DAYS = 365


@plugins.hookimpl
def run_api(task):
    if task.url and task.url.startswith(NOTION_API):
        notion = get_notion(task)
        method = task.url.split("/")[-1]

        match method:
            case "pages":
                get_notion_pages(task, notion)
                return task
    return None


def get_notion(task, integration=None):
    access_token = None
    if not integration:
        integration = task.get_integration("notion")
    if integration:
        secret = integration.secret_set.filter(vendor="notion").last()
        access_token = secret.value if secret else None
    else:
        # if you don't want to mess with integrations and secrets
        access_token = os.environ.get("NOTION_API_TOKEN")
    if not access_token:
        raise Exception("No Notion token found")
    return Client(auth=access_token)


def get_notion_projects(integration):
    notion = get_notion(None, integration)
    pages = notion.search(
        query="", filter={"property": "object", "value": "database"}
    ).get("results")
    vals = [
        {
            "id": p["id"],
            "title": (
                p["title"][0]["plain_text"] if "title" in p and p["title"] else "n/a"
            ),
        }
        for p in pages
    ]
    return vals


def get_user_from_list(users, id):
    matching = [u for u in users["results"] if u["id"] == id]
    return matching[0] if matching else None


def get_title(block):
    if "title" in block:
        return block["title"][0]["plain_text"]
    props = block["properties"]
    if "Page" in props:
        props = props["Page"]
    if "title" not in props or not props["title"]:
        return "n/a"
    return props["title"][0]["plain_text"]


def get_notion_page_list(task, notion):
    pages = []
    sort = {"direction": "descending", "timestamp": "last_edited_time"}
    if task.get_project_value("notion_db_query"):
        # run a Notion prefix search on databases, get all their pages
        query = task.get_project_value("notion_db_query")
        log("Running Notion DB query", query)
        stack = notion.search(
            query=query,
            filter={"property": "object", "value": "database"},
            sort=sort,
        ).get("results")
        while stack:
            current = stack.pop()
            if "type" in current and current["type"] == "child_page":
                current = notion.pages.retrieve(page_id=current["id"])
            if current["object"] == "page":
                pages.append(current)
            children = notion.blocks.children.list(block_id=current["id"])
            for child in children["results"]:
                if child["type"] == "child_page":
                    stack.append(child)

    if not pages and task.get_project_value("notion_query"):
        query = task.get_project_value("notion_query")
        log("Running Notion query", query)
        pages = notion.search(query=query, sort=sort).get("results")

    # if we got nothing, get everything
    if not pages:
        log("Fetching all Notion pages")
        pages = notion.search(query="").get("results")

    return pages


def get_notion_pages(task, notion):
    time_series = task.is_time_series()
    page_list = get_notion_page_list(task, notion)
    users = notion.users.list()
    r = h2("Relevant Notion Documents")
    for page in page_list:
        if not is_full_page(page):
            continue
        vals = SimpleNamespace()
        created_days = get_days_since(page, "created_time")
        edited_days = get_days_since(page, "last_edited_time")
        context_days = TIME_SERIES_CONTEXT_DAYS if time_series else CONTEXT_DAYS
        if created_days > context_days and edited_days > context_days:
            continue
        vals.created_days = get_days_ago(page, "created_time")
        user = get_user_from_list(users, page["created_by"]["id"])
        vals.created_by = user["name"] if user else "n/a"
        vals.edited_days = get_edit_days_ago(page, "last_edited_time", "created_time")
        user = get_user_from_list(users, page["last_edited_by"]["id"])
        vals.edited_by = user["name"] if user else "n/a"
        props = page["properties"]
        if "Title" in props or "title" in props:
            pass
        elif "Page" in props:
            props = props["Page"]
        elif "Summary" in props:
            props = props["Summary"]

        title = {}
        if "Title" in props:
            title = props["Title"]
        elif "title" in props:
            title = props["title"]
        elif "Name" in props:
            title = props["Name"]
        elif "name" in props:
            title = props["name"]
        elif "Ticket" in props:
            title = props["Ticket"]

        title = title["title"] if title and "title" in title else title
        if title:
            vals.title = title[0]["plain_text"] if title else None
        debug = vals.title if hasattr(vals, "title") else props
        log("Fetching page", debug)

        status = props.get("Status", "")
        try:
            if status and "select" in status:
                vals.status = status["select"]["name"]
            elif status and "status" in status:
                vals.status = status["status"]["name"]
            else:
                vals.status = "%s" % status
        except Exception:
            vals.status = "%s" % status

        # OK, get the actual content
        vals.content = ""
        try:
            blocks = notion.blocks.children.list(block_id=page["id"])
            stack = blocks["results"][::-1]  # reverse because stack
            while stack:
                cur = stack.pop()
                if not cur or not "object" in cur:
                    continue
                if cur["object"] != "block" or not is_full_block(cur):
                    continue
                type = cur["type"]
                if type in cur:
                    text = ""
                    content = cur[type]
                    if "text" in content:
                        text = " ".join([t.get("plain_text") for t in content["text"]])
                    elif "rich_text" in content:
                        text = " ".join(
                            [t.get("plain_text") for t in content["rich_text"]]
                        )
                    if text:
                        vals.content += "\n%s" % text
                if "has_children" in cur and cur["has_children"]:
                    children = notion.blocks.children.list(block_id=cur["id"])[
                        "results"
                    ]
                    stack += children[::-1]  # reverse because stack
            r += render_page(vals)
        except Exception as e:
            r += "Error fetching content: %s\n" % e

    task.response = r
    task.save()


def render_page(vals):
    if not vals.content or len(vals.content) < 16:
        return ""
    r = "---\n\n"
    if hasattr(vals, "title"):
        r += h4("Page title: %s" % vals.title)
    r += "created %s by %s" % (
        vals.created_days,
        vals.created_by,
    )
    r += (
        ", edited %s by %s" % (vals.edited_days, vals.edited_by)
        if vals.edited_days
        else ""
    )
    r += "\n"
    if hasattr(vals, "status") and vals.status:
        r += "Status: %s\n" % vals.status
    r += "Content: %s\n\n" % (vals.content or "").replace("%s", " ").strip()
    return r
