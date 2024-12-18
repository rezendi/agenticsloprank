import datetime, os, requests, time
from django.utils import timezone
from atlassian import Jira  # type: ignore
from atlassian import Confluence  # type: ignore
from markdownify import markdownify as md  # type: ignore
from ..util import *
from missions import plugins


MAX_DONE_DAYS = 60
JIRA_QUANT_FIELDS = [
    "timespent",
    "timeoriginalestimate",
    "timeestimate",
    "progress",
    "aggregateprogress",
    "aggregatetimespent",
    "aggregatetimeestimate",
    "aggregatetimeoriginalestimate",
]
MAX_DESCRIPTION_LENGTH = 16000
OBSOLETE_CLOSED_ISSUE_DAYS = 180


@plugins.hookimpl
def run_api(task):
    if task.url and task.url.startswith(ATLASSIAN_API):
        method = task.url.split("/")[-1]

        match method:
            case "issues":
                jira = get_jira(task)
                get_jira_issues(task, jira)
                return task
            case "pages":
                get_confluence_pages(task)
                return task
    return None


def get_jira(task, integration=None, confluence=False):
    if not integration:
        integration = task.get_integration("jira")
    access_token = None
    if integration:
        secret = integration.secret_set.last()
        if secret:
            access_token = secret.value
    else:  # if you don't want to mess with integrations and secrets
        access_token = os.environ.get("JIRA_API_TOKEN")
    if not access_token:
        raise Exception("No Jira integration found")

    # Atlassian PAT
    if integration.extras.get("oauth") == "false":
        integration.extras["accessible"] = [{"url": integration.extras.get("url")}]
        integration.save()
        return Jira(
            url=integration.extras.get("url", os.environ.get("JIRA_URL")),
            username=integration.extras.get("username", os.environ.get("JIRA_USER")),
            cloud=integration.extras.get("cloud") == "true",
            password=access_token,
        )

    # OK, we have an OAuth access token
    refreshed = secret.extras.get("refreshed_at", None)
    if not refreshed:
        refreshed = secret.edited_at.timestamp()
    diff = int(time.time()) - int(float(refreshed))
    if diff > secret.extras.get("expires_in", 3600):
        # gotta refresh the token
        if not secret.refresh:
            raise Exception("No refresh token found")
        url = "https://auth.atlassian.com/oauth/token"
        data = {
            "grant_type": "refresh_token",
            "client_id": os.environ.get("JIRA_CLIENT_ID"),
            "client_secret": os.environ.get("JIRA_CLIENT_SECRET"),
            "refresh_token": secret.refresh,
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(url, json=data, headers=headers)
        response_data = response.json()
        if "error" in response_data:
            raise Exception("Error refreshing JIRA token: %s" % response_data)
        elif "access_token" not in response_data:
            raise Exception("No access token in JIRA refresh response")
        secret.value = response_data.pop("access_token")
        secret.refresh = response_data.pop("refresh_token")
        secret.extras = response_data
        secret.extras["refreshed_at"] = int(time.time())
        secret.save()
        access_token = secret.value

    # OK, let's get the accessible resources if we don't have them
    # note that this includes the Jira URL, for future linking
    accessible = integration.extras.get("accessible", [])
    if not accessible:
        s = requests.Session()
        s.headers["Authorization"] = "Bearer %s" % access_token
        response = requests.get(
            "https://api.atlassian.com/oauth/token/accessible-resources",
            headers=s.headers,
        )
        accessible = response.json()
        integration.extras["accessible"] = accessible
        integration.save()

    if not accessible:
        raise Exception("No Jira resources found")

    # OK, let's finally return the Jira client
    id = accessible[0]["id"]
    oauth2_dict = {
        "client_id": os.environ["JIRA_CLIENT_ID"],
        "token": {"token_type": "Bearer", "access_token": access_token},
    }
    if confluence:
        url = "https://api.atlassian.com/ex/confluence/%s" % id
        return Confluence(oauth2=oauth2_dict, url=url)
    url = "https://api.atlassian.com/ex/jira/%s" % id
    return Jira(oauth2=oauth2_dict, url=url)


def get_confluence_pages(task):
    confluence = get_jira(task, confluence=True)
    space = task.get_project_value("confluence")
    cql = 'type = page AND space IN ("%s") ORDER BY lastModified DESC' % space
    log("Fetching Confluence pages with cql", cql)

    page = 0
    cutoff_date = timezone.now() - datetime.timedelta(days=60)
    latest_date = timezone.now()
    concatenated = {}
    while latest_date > cutoff_date and page < 10:
        start = 25 * page
        response = confluence.cql(cql, start=start)
        if concatenated and "results" in concatenated:
            concatenated["results"] += response["results"]
        else:
            concatenated = response
        if not response["results"]:
            break
        latest = response["results"][-1]
        latest_date = datetime.datetime.fromisoformat(latest["lastModified"])
        page += 1

    # filter the result per some hack-y criteria in the task extras
    raw = concatenated["results"]
    raw = [r for r in raw if r["content"].get("id")]
    crit = task.extras.get("confluence_criteria", {})
    if crit:
        results = []
        if "titles" in crit:
            for prefix in crit["titles"]:
                value = prefix[0]
                instruction = prefix[1] if len(prefix) > 1 else None
                matching = [r for r in raw if r["content"]["title"].startswith(value)]
                if instruction is None:
                    results += matching
                elif instruction == "first" and matching:
                    results.append(matching[0])
    else:
        results = raw

    r = h2("Confluence Pages")
    for meta in results:
        id = meta["content"]["id"]
        r += h4(meta["content"].get("title"))
        page = confluence.get_page_by_id(id, expand="body.storage")
        body_html = page["body"]["storage"]["value"]
        body_markdown = "\n\n" + md(body_html)
        r += body_markdown
        r += "\n\n---\n\n"
    task.response = r


def get_jira_projects(integration):
    if integration and integration.name and integration.name.startswith("TDTest"):
        return [{"key": "tdtest", "name": "TDTest Jira Project"}]
    try:
        jira = get_jira(None, integration)
        projects = jira.projects() if jira else []
        return [{"key": p["key"], "name": p["name"]} for p in projects]
    except Exception as ex:
        log("Error getting Jira projects", ex)
        return []


def get_jira_custom_fields(jira):
    all_fields = jira.get_all_fields()
    custom_fields = [f for f in all_fields if f["custom"]]
    return custom_fields


def get_confluence_spaces(integration):
    if integration and integration.name and integration.name.startswith("TDTest"):
        return [{"key": "tdtest", "name": "TDTest Confluence Space"}]
    try:
        confluence = get_jira(None, integration, confluence=True)
        spaces = confluence.get_all_spaces()
        return [{"key": p["key"], "name": p["name"]} for p in spaces["results"]]
    except Exception as ex:
        log("Error getting Confluence spaces", ex)
        return []


def cache_jira_issue(issue, structured, custom_fields):
    all_issues = structured.get("issues", [])
    existing = [i for i in all_issues if i["key"] == issue["key"]]
    if existing:  # we already have this issue
        return

    fields = issue["fields"]
    cacheissue = {"key": issue["key"]}
    statusCategory = fields["status"]["statusCategory"]["name"]
    cacheissue["statusCategory"] = statusCategory
    cacheissue["summary"] = fields["summary"]
    cacheissue["created"] = fields["created"]
    if fields.get("updated"):
        cacheissue["updated"] = fields["updated"]
    cacheissue["issueType"] = fields["issuetype"]["name"]
    cacheissue["status"] = fields["status"]["name"]
    if fields.get("statuscategorychangeddate"):
        cacheissue["statusCategoryChanged"] = fields["statuscategorychangeddate"]

    if fields.get("priority"):
        cacheissue["priority"] = fields["priority"]["name"]
    if fields.get("assignee"):
        cacheissue["assignee"] = fields["assignee"]["displayName"]

    if fields.get("parent"):
        parent = fields["parent"]
        cacheissue["parent"] = parent["key"]
        cacheissue["parent_type"] = parent["fields"].get("issuetype", {}).get("name")

    if fields.get("issuelinks"):
        for link in fields["issuelinks"]:
            issue = link.get("outwardIssue", {}).get("key")
            if issue:
                rel = link.get("type", {}).get("outward")
                cacheissue["issueLinks"] = cacheissue.get("issueLinks", [])
                cacheissue["issueLinks"].append({"key": issue, "rel": rel})
            issue = link.get("inwardIssue", {}).get("key")
            if issue:
                rel = link.get("type", {}).get("inward")
                cacheissue["issueLinks"] = cacheissue.get("issueLinks", [])
                cacheissue["issueLinks"].append({"key": issue, "rel": rel})
    if fields.get("versions"):
        cacheissue["versions"] = [
            v.get("name", v.get("id")) for v in fields["versions"]
        ]
    if fields.get("fixVersions"):
        cacheissue["fixVersions"] = [
            v.get("name", v.get("id")) for v in fields["fixVersions"]
        ]
    if fields.get("resolution"):
        cacheissue["resolution"] = fields["resolution"]["name"]
        if fields.get("resolutiondate"):
            cacheissue["resolutionDate"] = fields["resolutiondate"]

    for name in JIRA_QUANT_FIELDS:
        if name in fields:
            cacheissue[name] = fields[name]
    for field in custom_fields:
        id = field["id"]
        name = field["name"]
        if name == "Sprint" and id in fields and fields[id] is not None:
            cacheissue["sprints"] = [f["name"] for f in fields[id]]
            all_sprints = structured.get("all_sprints", [])
            for sprint in fields[id]:
                if not sprint in all_sprints:
                    all_sprints.append(sprint)
            structured["all_sprints"] = all_sprints
        else:
            if id in fields and fields[id] and fields[id] not in ["0", "0.0", "0 of 0"]:
                cacheissue[name] = fields[id]

    all_issues.append(cacheissue)
    structured["issues"] = all_issues


def render_jira_issue(issue, custom_fields, max_description=MAX_DESCRIPTION_LENGTH):
    log("rendering jira issue", issue["key"])

    fields = issue["fields"]
    statusCategory = fields["status"]["statusCategory"]["name"]
    res = h4(issue["key"])
    res += "\nSummary: %s" % fields["summary"]
    res += "\nProject: %s" % fields["project"]["name"]
    res += "\nCreated by: %s" % fields["creator"]["displayName"]
    res += "\nCreated: %s" % get_days_ago(fields, "created")
    if fields.get("updated"):
        res += "\nUpdated: %s" % get_edit_days_ago(fields, "updated", "created")
    res += "\nPriority: %s" % fields["priority"]["name"]
    res += "\nIssue Type: %s" % fields["issuetype"]["name"]
    res += "\nStatus: %s" % fields["status"]["name"]
    res += "\nStatus category: %s" % statusCategory
    if fields.get("statuscategorychangeddate"):
        res += " changed: %s" % get_days_ago(fields, "statuscategorychangeddate")

    if fields.get("priority"):
        res += "\nPriority: %s" % fields["priority"]["name"]
    if fields.get("assignee"):
        res += "\nAssignee: %s" % fields["assignee"]["displayName"]

    if fields.get("parent"):
        parent = fields["parent"]
        res += "\nParent: %s" % parent["key"]
        parent = parent["fields"]
        res += "\nParent type: %s" % parent.get("issuetype", {}).get("name")
        res += "\nParent priority: %s" % parent.get("priority", {}).get("name")
        res += "\nParent status: %s" % parent.get("statusCategory", {}).get("name")
    if fields.get("issuelinks"):
        res += "\nIssue links:"
        for link in fields["issuelinks"]:
            issue = link.get("outwardIssue", {}).get("key")
            if issue:
                rel = link.get("type", {}).get("outward")
                res += "\n- %s: %s" % (issue, rel)
    if fields.get("versions"):
        res += "\nVersions: %s" % ", ".join(
            [v.get("name", v.get("id")) for v in fields["versions"]]
        )
    if fields.get("fixVersions"):
        res += "\nFix versions: %s" % ", ".join(
            [v.get("name", v.get("id")) for v in fields["fixVersions"]]
        )

    if fields.get("closed"):
        res += "\nClosed: %s" % get_days_ago(fields, "closed")
    if fields.get("resolution"):
        res += "\nResolution: %s" % fields["resolution"]["name"]
        if fields.get("resolutiondate"):
            res += " resolved: %s" % get_days_ago(fields, "resolutiondate")

    for fid in JIRA_QUANT_FIELDS:
        if fid in fields and fields[fid] and fields[fid] not in ["0", "0.0", "0 of 0"]:
            display = fid.replace("time", "Time ").replace("estimate", " estimate")
            display = display.replace("aggregate", "Aggregate ").replace("  ", " ")
            if "progress" in fid:
                progress = fields[fid]
                if progress["progress"] or progress["total"]:
                    res += f"\n{display}: {progress['progress']} of {progress['total']}"
            else:
                field = fields[fid]
                if isinstance(field, dict):
                    field = field["name"] if "name" in field else field
                if isinstance(field, list):
                    field = "%s total" % len(field)
                res += "\n%s: %s" % (display, field)

    for field in custom_fields:
        id = field["id"]
        name = field["name"]
        if name == "Sprint" and id in fields and fields[id] is not None:
            # Sprint information
            res += "\nSlog(s):"
            for sprint in fields[id]:
                res += f"\n- {sprint.get('name')}"
                res += f", {sprint.get('state')}"
                # sprints can be created but not yet scheduled
                if "startDate" in sprint:
                    res += f", start {get_days_ago(sprint, 'startDate')}"
                if "endDate" in sprint:
                    res += f", end {get_days_ago(sprint, 'endDate')}"
                # sprints can be started but not ended, and not always within the start and end date
                if "completeDate" in sprint:
                    res += f", complete {get_days_ago(sprint, 'completeDate')}"
        else:
            if id in fields and fields[id] and fields[id] not in ["0", "0.0", "0 of 0"]:
                val = fields[id]
                res += "\n%s: %s" % (name, val)

    if fields.get("closed"):
        if get_days_since(fields["closed"]) > OBSOLETE_CLOSED_ISSUE_DAYS:
            return res + "\n\n"

    # description, comments
    description = fields.get("description", "") or ""
    res += "\n\nDescription: \n%s" % description[:max_description]
    comments = fields["comment"]["comments"]
    if comments:
        res += "\nComments:"
        for c in comments:
            res += "\n- %s: %s" % (c["author"]["displayName"], c["body"])
    res += "\n\n"
    return res


def get_project_custom_fields(task, jira, all_fields):
    custom_fields = get_jira_custom_fields(jira)
    more_custom_fields = task.get_project_value("jira_custom_fields", [])
    for field in more_custom_fields:
        if not any(f["id"] == field["id"] for f in custom_fields):
            custom_fields.append(field)
    # Get the sprint field ID if any
    for field in all_fields:
        if field["name"].lower() == "sprint":
            custom_fields.append({"id": field["id"], "name": "Sprint"})
            break
    return custom_fields


def fetch_issues_with_jql(jira, jql, cutoff_date=None, max_pages=20):
    concatenated = {}
    latest_date = timezone.now()
    page = 0
    # sanity limit to 1000 of each type of issue at least for now
    while page < max_pages:
        log("Getting jql page", page)
        start = 50 * page
        response = jira.jql(jql, start=start)
        if concatenated and "issues" in concatenated:
            concatenated["issues"] += response["issues"]
        else:
            concatenated = response
        if not response["issues"]:
            break
        latest = response["issues"][-1]
        latest_date = datetime.datetime.fromisoformat(latest["fields"]["updated"])
        log("latest", latest_date, "cutoff", cutoff_date, len(concatenated["issues"]))
        if cutoff_date and latest_date < cutoff_date:
            break
        page += 1
    return concatenated


def get_jira_issues(task, jira):
    raw_data = {}
    all_fields = jira.get_all_fields()
    raw_data["fields"] = all_fields
    custom_fields = get_project_custom_fields(task, jira, all_fields)
    structured = {
        "custom_fields": [{"id": cf["id"], "name": cf["name"]} for cf in custom_fields]
    }

    base_jql = ""
    jira_projects = task.get_project_value("jira")
    if jira_projects:
        if isinstance(jira_projects, str):
            jira_projects = [jira_projects]
        base_jql = "project IN (%s)" % ",".join(jira_projects) + " AND "

    # Get issues
    res = ""
    epics = []
    keys = []
    max_done_days = task.flags.get("max_done_days", MAX_DONE_DAYS)
    done_cutoff = timezone.now() - datetime.timedelta(days=max_done_days)
    max_description = task.flags.get("max_description", MAX_DESCRIPTION_LENGTH)
    for category in ["In Progress", "To Do", "Done"]:
        jql = base_jql + 'statusCategory = "%s" ORDER BY updatedDate DESC' % category
        log("Getting", category, "issues, jql", jql)
        res += h3("Jira Issues: %s" % category)
        cutoff = done_cutoff if category == "Done" else None
        results = fetch_issues_with_jql(jira, jql, cutoff_date=cutoff)
        raw_data[category] = results
        for issue in results["issues"]:
            res += render_jira_issue(issue, custom_fields, max_description)
            cache_jira_issue(issue, structured, custom_fields)
            keys.append(issue["key"])
            if issue["fields"]["issuetype"]["name"] == "Epic":
                epics.append(issue["key"])

    # for each epic, ensure we've fetched all of its individual issues
    for epic in epics:
        got = [i["key"] for i in structured["issues"] if i.get("parent") == epic]
        jql = base_jql + f"parent = {epic} "
        if len(got) > 0:
            jql += f"AND key NOT IN ({','.join(got)})"
        log("Getting epic issues, epic", epic, "jql", jql)
        response = fetch_issues_with_jql(jira, jql)
        log("Got", len(response["issues"]), "issues")
        for issue in response["issues"]:
            if not issue["key"] in keys:
                cache_jira_issue(issue, structured, custom_fields)

    task.response = res
    task.structured_data = structured
    task.save()
    task.store_data(raw_data)


def issue_in_slog(issue, sprints):
    sprint_names = [s["name"] for s in sprints]
    issue_sprints = issue.get("sprints", [])
    for sprint in issue_sprints:
        if sprint in sprint_names:
            return True
    return False


def get_jira_issues_by_sprint_and_epic(task):
    structured = task.structured_data
    all_spints = structured.get("all_sprints", [])
    active_sprints = [s for s in all_spints if s["state"] == "active"]
    structured["active_sprints"] = active_sprints

    jira = get_jira(task)
    all_fields = jira.get_all_fields()
    custom_fields = get_project_custom_fields(task, jira, all_fields)
    issue_data = structured.get("issues", [])

    base_jql = ""
    jira_projects = task.get_project_value("jira")
    if jira_projects:
        if isinstance(jira_projects, str):
            jira_projects = [jira_projects]
        base_jql = "project IN (%s)" % ",".join(jira_projects) + " AND "

    r = ""
    active_issues = [i for i in issue_data if issue_in_slog(i, active_sprints)]
    epic_keys = [i["key"] for i in active_issues if i.get("issueType") == "Epic"]
    epic_keys += [i["parent"] for i in active_issues if i.get("parent_type") == "Epic"]
    epic_keys.sort(reverse=True)
    if epic_keys:
        r += h3("Active Epics")
        jql = base_jql + "key IN (%s)" % ",".join(epic_keys)
        log("Getting epics, jql", jql)
        response = fetch_issues_with_jql(jira, jql)
        for epic in response["issues"]:
            r += h4(f"Epic: {epic['key']}")
            r += render_jira_issue(epic, custom_fields)
            cache_jira_issue(epic, structured, custom_fields)
            sprint_epic_issues = [
                i for i in active_issues if i.get("parent") == epic["key"]
            ]
            issue_keys = [i["key"] for i in sprint_epic_issues]
            jql = base_jql + "key IN (%s)" % ",".join(issue_keys)
            log("Getting epic issues, epic", epic["key"], "jql", jql)
            response = fetch_issues_with_jql(jira, jql)
            for issue in response["issues"]:
                r += render_jira_issue(issue, custom_fields)
                cache_jira_issue(issue, structured, custom_fields)

    r += h3("Issues Without Epics")
    non_epic = [i for i in active_issues if i["key"] not in epic_keys]
    non_epic = [i for i in non_epic if i.get("parent") not in epic_keys]
    if non_epic:
        issue_keys = [i["key"] for i in non_epic]
        jql = base_jql + "key IN (%s)" % ",".join(issue_keys)
        log("Getting non epic issues", "jql", jql)
        response = fetch_issues_with_jql(jira, jql)
        for issue in response["issues"]:
            r += render_jira_issue(issue, custom_fields)
            cache_jira_issue(issue, structured, custom_fields)

    task.response = r
    if structured:
        task.structured_data = structured
    task.save()


def get_jira_project_avatar(jira, project_key):
    try:
        project = jira.project(project_key)
        avatars = jira.project_avatars(project)
        if avatars and "system" in avatars:
            # Get the largest avatar
            largest_avatar = max(avatars["system"], key=lambda x: x["height"])
            return largest_avatar["url"]
    except Exception as e:
        log(f"Error fetching project avatar for {project_key}: {e}")
    return None
