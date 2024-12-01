import json
from datetime import timedelta
from django.utils.dateparse import parse_date
from ..util import *
from missions import plugins


@plugins.hookimpl
def quantify(task):
    # risk quantification is a slightly special case
    if task.url == BASE_RISK_URL + "/quantify":
        return quantify_project_risks(task)

    # first prereq is always the direct parent
    prereqs = task.prerequisite_tasks()
    if not prereqs or len(prereqs) == 0:
        raise Exception("No dependencies for quantified task")
    for prereq in prereqs:
        url = prereq.url
        prereq.refresh_from_db()
        if url and url.endswith("commits"):
            return quantify_dev_activity(task)
        elif url and url.endswith("actions"):
            return quantify_workflow_runs(task)
        elif url and FIGMA_API in url:
            return quantify_figma(task)
        elif url and (url.startswith(HARVEST_API) or url.startswith(FORECAST_API)):
            return quantify_hours(task)
        elif url and url.startswith(GITHUB_PREFIX) and "issues" in url:
            return quantify_github_issues(task)
        elif url and url.startswith(GITHUB_PREFIX) and "pulls" in url:
            return quantify_pr_ratings(task)
        elif url and url.startswith(JIRA_API) and "quantify" in task.url:
            return quantify_jira(task)
    return


@plugins.hookimpl
def run_aggregate(task, tasks, url_key):
    if url_key == "hours":
        log("aggregating hours across missions", tasks)
        return quantify_hours(task, tasks)


def quantify_dev_activity(task):
    md = ""
    devs = {}
    prev_devs = {}

    # always run a quantified task for a final report if there are any commit tasks
    tasks = task.prerequisite_tasks()
    devs = concatenate_dev_data(tasks)
    prev_task = task.previous()
    if prev_task:
        prev_devs = concatenate_dev_data(prev_task.prerequisite_tasks())
    if not prev_devs and task.mission.previous:
        prev_devs = concatenate_dev_data(task.mission.previous.commit_tasks())

    if devs:
        if task.mission.flags.get("combine_by_name"):
            log("Combining by names")
            devs = combine_devs_by_name(devs)
        # sort by total changes
        for name in devs:
            commits = devs[name].get("commits", [])
            commits = [c for c in commits if c["type"] == "normal"]
            devs[name]["total"] = sum([c["changes"] for c in commits])

        devs_desc = sorted(devs, key=lambda x: devs[x]["total"], reverse=True)

        days = task.parent.commit_days() if task.parent else task.commit_days()
        md += "\n## Quantified Commit Activity Over %s Days\n" % days
        md += "\n<div markdown='1' class='table-container dev-quant-table'>\n"
        md += "| Developer | Avatar | Branches | PRs | Commits | Files | Changes |\n"
        md += "| --------- | ------ | -------- | --- | ------- | ----- | ------- |\n"
        for name in devs_desc:
            dev = get_dev_summary(devs[name])
            md += f"| **{dev.link}** | {dev.avatar} | {dev.branches} | {dev.prs} | {dev.commits} | {dev.files} | {dev.changes} |\n"
            if prev_devs and name in prev_devs and task.is_time_series():
                dev_prev = get_dev_summary(prev_devs[name])
                diff = get_dev_diff(dev, dev_prev)
                if diff:
                    md += f"| vs. last report | | {diff.branches} | {diff.prs} | {diff.commits} | {diff.files} | {diff.changes} |\n"
        md += "\n</div>\n"
        md += "\n<sub>PRs: created by that dev and opened/merged/closed-unmerged during the period</sub>\n"

    if md:
        task.response = md
    return task.response


def quantify_workflow_runs(task):
    task.response = ""
    dep = task.parent
    keys = dep.structured_data.keys()
    md = f"\n### Workflow Runs Over {task.commit_days()} Days\n"
    md += "\n<div markdown='1' class='table-container workflow-quant-table'>\n"
    md += "| Workflow | Runs | Complete | Success | Failure | Success % | Runs Since Failure | \n"
    md += "| -------- | ---- | -------- | ------- | ------- | --------- | ------------------ | \n"
    for key in keys:
        if key in ["workflows", "runs"]:
            continue
        flow = dep.structured_data[key]
        runs = flow.get("runs", [])
        name = flow.get("name")
        if task.flags.get("branch_filter"):
            runs = [r for r in runs if r["branch"] == task.flags.get("branch_filter")]
        total = len(runs)
        if total == 0:
            continue
        complete = [r for r in runs if r["status"] == "completed"]
        complete = [r for r in runs if r["conclusion"] in ["success", "failure"]]
        success = len([r for r in complete if r["conclusion"] == "success"])
        failure = len([r for r in complete if r["conclusion"] == "failure"])
        perc = 100 * success / (success + failure) if success + failure > 0 else 0
        last_failure = next(
            (idx for (idx, d) in enumerate(complete) if d["conclusion"] == "failure"),
            len(complete),
        )
        md += f"| **{name}** | {total} | {len(complete)} | {success} | {failure} | {perc:.0f}% | {last_failure} |\n"
    md += "</div>\n"
    task.response = md
    return task.response


def quantify_github_issues(task):
    task.response = ""
    dep = task.parent
    counts = dep.structured_data.get("counts", {"open_issues": 0, "closed_issues": 0})
    issues = dep.structured_data.get("issues", [])
    if not issues:
        return log("No issues found for GitHub quant task")
    issues = sorted(issues, key=lambda x: x.get("created"), reverse=True)
    oldest = get_days_since(issues[-1], "created")

    md = f"\n### Recent GitHub Issues Activity\n"
    md += "\n<div markdown='1' class='table-container'>\n"
    md += "| Timespan | Opened | Closed | Comments | Labeled | Milestones | \n"
    md += "| -------- | ------ | ------ | -------- | ------- | ---------- | \n"

    rows = [7, 14, 30, 0]
    if oldest > 365:
        rows = [7, 30, 90, 365, 0]
    elif oldest > 90:
        rows = [7, 30, 90, 0]
    elif oldest < 30:
        rows = [7, 14, 0]
    for row in rows:
        if row == 0:
            md += f"| All Time | {counts['closed_issues'] + counts['open_issues']} | {counts['closed_issues']} | - | - | - |\n"
        else:
            opened = [i for i in issues if get_days_since(i, "created") <= row]
            comments = sum([i["comments"] for i in opened], 0)
            labels = sum([0 if i.get("labels", []) else 1 for i in opened], 0)
            milestones = len(set([i.get("milestone", "") for i in opened]))
            closed = [
                i
                for i in issues
                if i["state"] == "closed"
                and (get_days_since(i, "closed") or 9999) <= row
            ]
            name = f"{row} Days" if row < 365 else "1 Year"
            md += f"| {name} | {len(opened)} | {len(closed)} | {comments} | {labels} | {milestones} |\n"
    md += "</div>\n"
    md += "\n<sub>Like all software activity quantification, these numbers are imperfect but sometimes useful. Comments, Labels, and Milestones refer to those issues opened in the timespan in question.</sub>\n"
    task.response = md
    return task.response


# get, diff Harvest/Forecast hours
def quantify_hours(task, taskset=None):
    if not taskset:
        taskset = task.mission.task_set
    forecast_tasks = taskset.filter(url__startswith=FORECAST_API)
    if not forecast_tasks:
        raise Exception("No Forecast fetch tasks/data found")
    harvest_tasks = taskset.filter(url__startswith=HARVEST_API)
    if not harvest_tasks:
        raise Exception("No Forecast fetch tasks/data found")

    people = []
    for forecast_task in forecast_tasks:
        forecast_data = forecast_task.structured_data
        for id in forecast_data.keys():
            vals = forecast_data[id]
            person = {"name": vals["name"], "forecast": id, "allocs": {}, "entries": {}}
            existing = [p for p in people if p["forecast"] == id]
            if existing:
                person = existing[0]
            elif [p for p in people if p["name"] == vals["name"]]:
                raise Exception("Duplicate Forecast names, further refinement required")
            for alloc in vals.get("allocations", []):
                now = parse_date(alloc["start"])
                end = parse_date(alloc["end"])
                while now <= end:
                    key = now.strftime("%Y-%m-%d")
                    hours = round(person["allocs"].get(key, 0.0) + alloc["hours"], 2)
                    person["allocs"][key] = hours
                    now = now + timedelta(days=1)
            people.append(person)

    for harvest_task in harvest_tasks:
        harvest_data = harvest_task.structured_data
        for id in harvest_data.keys():
            vals = harvest_data[id]
            person = {"name": vals["name"], "harvest": id, "allocs": {}, "entries": {}}
            existing = [p for p in people if p["name"] == vals["name"]]
            if existing:
                person = existing[0]
                person["harvest"] = id
            for entry in vals["entries"]:
                key = entry["date"]
                hours = round(person["entries"].get(key, 0.0) + entry["hours"], 2)
                person["entries"][key] = hours
            if not existing:
                people.append(person)
    today = datetime.datetime.today().date()

    html = ""
    for week in range(0, 2):
        start_day = today - timedelta(days=today.weekday() + 7 + ((1 - week) * 7))
        html += f"<h3>Hours Allocated / Logged For Week Of {start_day}</h3>"
        html += "<div class='harvest-forecast-table table-container'>"
        html += "<table>"
        html += "<thead><tr><th>Person</th><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th><th>Sun</th><th>Total</th><th>Diff</th></tr></thead>"
        html += "<tbody>"
        for person in people:
            any_hours = False
            row = f"<tr><td><strong>{person['name']}</strong></td>"
            tot_all = 0
            tot_ent = 0
            for diff in range(0, 7):
                day = start_day + timedelta(days=diff)
                key = day.strftime("%Y-%m-%d")
                all = person["allocs"].get(key, 0)
                # assume weekend allocations 0
                if diff in [5, 6] and task.flags.get("weekend_allocations") != "true":
                    all = 0
                ent = person["entries"].get(key, 0)
                entry = f"{all}/{ent}"
                row += f"<td>{entry.replace('0/0', '--')}</td>"
                tot_all += all
                tot_ent += ent
                tot_diff = round(tot_all - tot_ent, 2)
                any_hours = any_hours or all > 0 or ent > 0
            row += f"<td><strong>{round(tot_all, 2)}/{round(tot_ent, 2)}</strong></td>"
            row += f"<td><strong>{round(tot_diff, 2)}</strong></td></tr>"
            html += row if any_hours else ""
        html += "</tbody>"
        html += "</table>"
        html += "</div>"
        html += "<p>Numbers shown are Forecast/Harvest hours for project(s) relevant to this mission only.</p>"
        if task.flags.get("weekend_allocations") != "true":
            html += "<p>Weekend allocations currently zero by default.</p>"

    if html:
        task.response = html
    return task.response


def quantify_figma(task):
    dep = task.parent
    projects = dep.structured_data.get("projects", [])
    all_files = dep.structured_data.get("files", [])
    md = ""
    for project in projects:
        files = [f for f in all_files if f["project_id"] == project["id"]]
        if not files:
            continue
        md += f"\n### Figma Activity for {project['name']} Over {task.cadence_days()} Days\n"
        md += "\n<div markdown='1' class='table-container figma-table'>\n"
        md += "| User | Avatar | Files Modified | Versions | Comments | \n"
        md += "| ---- | ------ | -------------- | -------- | -------- | \n"
        users = {}
        for file in files:
            user = None
            for version in file.get("versions", []):
                if get_days_since(version["created_at"]) > task.cadence_days():
                    continue
                id = version["user"]["id"]
                user = users.get(id, {})
                if not user:
                    user = {
                        "id": id,
                        "name": version["user"]["handle"],
                        "avatar": version["user"]["img_url"],
                        "versions": 1,
                        "comments": 0,
                        "files": [file["name"]],
                    }
                else:
                    user["versions"] += 1
                    if not file["name"] in user["files"]:
                        user["files"].append(file["name"])
                users[id] = user

            for comment in file.get("comments", []):
                if get_days_since(comment["created_at"]) > task.cadence_days():
                    continue
                id = comment["from"]["id"]
                user = users.get(id, {})
                if not user:
                    user = {
                        "id": id,
                        "name": comment["from"]["handle"],
                        "avatar": comment["from"]["img_url"],
                        "files": [],
                        "versions": 0,
                        "comments": 1,
                    }
                else:
                    user["comments"] += 1
                users[id] = user

        for user in sorted(users, key=lambda x: users[x]["versions"], reverse=True):
            u = users[user]
            md += f"| **{u['name']}** | ![avatar]({u['avatar']}) | {len(u['files'])} | {u['versions']} | {u['comments']} |\n"
        md += "</div>\n"

    if md:
        task.response = md
    return task.response


def is_active_epic(epic):
    since = get_days_since(epic, "created")
    if not since:
        return False
    if since < 180:
        return True
    return get_year_of(epic, "created") == datetime.datetime.now().year


def group_epics(task, epics):
    groups = []
    group_keys = task.flags.get("group_by", [])
    for epic in epics:
        links = epic.get("issueLinks", [])
        grouped = [epic["key"]] + [l["key"] for l in links if l["rel"] in group_keys]
        found = False
        for g in groups:
            if any(k for k in grouped if k in g):
                g += [k for k in grouped if k not in g]
                found = True
                break
        if not found:
            groups.append(grouped)

    return sorted(groups, key=lambda x: "%s" % x, reverse=True)


def collate_for_rendering(task, group, issues):
    priority = ["Highest", "Critical", "Blocker"]
    priority = task.flags.get("highest_issue_priority", priority)

    tracking = False
    for key in ["timeoriginalestimate", "timeestimate", "timespent"]:
        tracking = tracking or any(i.get(key) for i in issues)

    open_issues = [i for i in issues if i.get("statusCategory") != "Done"]
    bugs = [i for i in issues if i.get("issueType") == "Bug"]
    vals = {
        "type": "epic",
        "key": group.get("id", group.get("key")),
        "name": group.get("name", group.get("summary")),
        "total": len(issues),
        "open": len(open_issues),
        "total_bugs": len(bugs),
        "open_bugs": len([i for i in bugs if i.get("statusCategory") != "Done"]),
    }
    priority = len([i for i in open_issues if i.get("priority") in priority])
    if priority:
        vals["priority"] = priority
    vals["name"] = vals["key"] + " : " + vals["name"].replace("|", "—")
    vals["name"] = vals["name"].replace("non_grouped : ", "")
    if len(vals["name"]) > 60:
        vals["name"] = vals["name"][:60] + "..."
    if tracking:
        vals["total_time"] = 0
        vals["done_time"] = 0
        for issue in issues:
            issue_time = max(
                issue.get("timeoriginalestimate", 0),
                issue.get("timeestimate", 0),
            )
            issue_time = max(issue_time, issue.get("timespent", 0))
            vals["total_time"] += issue_time / 3600
            if issue.get("statusCategory") == "Done":
                vals["done_time"] += issue_time / 3600
        vals["done_time"] = round(vals["done_time"], 2)
        vals["total_time"] = round(vals["total_time"], 2)
    return vals


def quantify_jira(task):
    log("Quantifying Jira")
    dep = task.parent
    if not dep:
        return log("No dependency found for Jira quant task")

    issues = dep.structured_data.get("issues", [])
    if not issues:
        return log("No issues found for Jira quant task")
    issues = sorted(issues, key=lambda x: x.get("updated", ""), reverse=True)
    open_issues = [i for i in issues if i.get("statusCategory") != "Done"]
    active_epics = [i for i in open_issues if i["issueType"] == "Epic"]
    active_sprints = [
        s for s in dep.structured_data.get("all_sprints", []) if s["state"] == "active"
    ]

    # group by epics if epics, otherwise by sprints if sprints, otherwise just issues
    rows = []
    non_grouped = []

    # group by epic, with a total line for un-epiced issues
    if len(active_epics) > 1:
        title = "Active Epics"
        epic_keys = [e["key"] for e in active_epics]
        non_grouped = [i for i in open_issues if not i.get("parent") in epic_keys]
        non_grouped_name = "No Epic"
        for epic in active_epics:
            epic_issues = [i for i in issues if i.get("parent") == epic["key"]]
            epic_issue_keys = [i["key"] for i in epic_issues]
            epic_subissues = [i for i in issues if i.get("parent") in epic_issue_keys]
            if epic_subissues:
                epic_issues += epic_subissues
                non_grouped = [i for i in non_grouped if i not in epic_subissues]
            vals = collate_for_rendering(task, epic, epic_issues)
            if epic.get("sprints", []):
                vals["sprints"] = len(epic["sprints"])
                vals["first_sprint"] = epic["sprints"][0]
            if epic.get("fixVersions", []):
                vals["fix_versions"] = len(epic["fixVersions"])
                vals["first_fix"] = epic["fixVersions"][0]

            rows.append(vals)

    # group by sprint, with a total line for un-sprinted issues
    elif len(active_sprints) > 1:
        title = "Active Sprints"
        non_grouped = [i for i in issues if not i.get("sprints")]
        non_grouped_name = "No Sprint"
        for sprint in active_sprints:
            sprint_issues = [i for i in issues if sprint["name"] in i.get("sprints")]
            vals = collate_for_rendering(task, sprint, sprint_issues)
            rows.append(vals)

    # just list a total line
    else:
        title = "Active Issues"
        non_grouped = open_issues
        non_grouped_name = "Issues"

    if non_grouped:
        ng = {"id": "non_grouped", "name": non_grouped_name}
        vals = collate_for_rendering(task, ng, non_grouped)
        rows.append(vals)

    populated = set()
    for row in rows:
        populated.update(row.keys())
    potential_columns = [
        ("name", "Name"),
        ("total", "Total issues"),
        ("open", "Open"),
        ("priority", "Critical"),
        ("total_bugs", "Bugs"),
        ("open_bugs", "Open bugs"),
        ("done_time", "Done time"),
        ("total_time", "Total time"),
        ("sprints", "Sprints"),
        ("first_sprint", "First sprint"),
        ("fix_versions", "Versions"),
        ("first_fix", "First version"),
    ]
    columns = [c for c in potential_columns if c[0] in populated]

    md = ""
    md += "\n## %s\n" % title
    md += "\n<div markdown='1' class='table-container jira-quant-table'>\n"
    md += "| %s |\n" % " | ".join([c[1] for c in columns])
    md += "| %s |\n" % " | ".join(["---" for c in columns])
    for row in rows:
        md += "| %s |\n" % " | ".join([str(row.get(c[0], "")) for c in columns])
    md += "</div>\n"
    task.response = md
    return task.response


def quantify_project_risks(task):
    rating_task = task.mission.task_set.filter(url=RISK_RATING_URL).first()
    if not rating_task:
        log("No rating task found for risk quantification")
        return
    task.parent = rating_task
    md = f"\n### Project Risk Ratings"
    md += "\n<div markdown='1' class='table-container risk-table'>"
    md += "| Risk | Level (1-5) | Rationale |\n"
    md += "| ---- | ------ | --------- |\n"
    ratings = json.loads(rating_task.response or rating_task.structured_data)
    log("ratings", ratings)
    # TODO make these keys more generic / configurable, both in the function and here
    keys = [
        "delivery",
        "velocity",
        "dependency",
        "team",
        "code_quality",
        "technical_debt",
        "test_coverage",
        "error_handling",
    ]
    for key in keys:
        name = key.replace("_", " ").title()
        md += (
            f"| {name} | {ratings[key+'_risk_rating']} |{ratings[key+'_rationale']} |\n"
        )
    md += "\n</div>\n"
    task.response = md
    return task.response


def quantify_pr_ratings(task):
    html = "<div class='pr-table'>"

    dep = task.parent
    ratings = dep.structured_data.get("llm_ratings", [])
    log("parent is", dep, "ratings populated", True if ratings else False)

    # Extract repo information from the dependent task's URL
    repo = get_repo_name_from_url(dep.url)
    if not repo:
        log("Unable to extract repo information from URL:", dep.url)
        return

    for rating in ratings:
        pr = rating.get("pr", {})
        state = pr.get("state", "unknown")
        date = pr.get("created_at", "")
        if pr.get("merged_at"):
            state = "merged"
            date = pr.get("merged_at", date)
        elif state == "closed":
            state = "closed"
            date = pr.get("closed_at", date)
        date = date.split("T")[0] if date else ""
        rating["date"] = date
        rating["state"] = state

        # display relevant issue, if any
        rating["issue"] = "n/a"
        issue = rating.get("issue_info", {})
        if issue.get("confidence", 0) > 8:
            issue_id = issue.get("issue_id", "")
            if issue_id.isnumeric():
                issue_id = "#" + issue_id
            rating["issue"] = issue_id

    ratings = sorted(ratings, key=lambda x: (x["rating"], x["date"]))
    default_repo = task.get_repo() or ""
    for rating in ratings:
        pr = rating.get("pr", {})
        rationale = rating["rationale"].replace("\n", " ").replace("\r\n", " ")

        issue = rating.get("issue", "n/a")
        if issue.startswith("#"):
            issue_number = issue[1:]
            issue_link = f"<a href='{GITHUB_PREFIX}{default_repo}/issues/{issue_number}'>{issue}</a>"
            rating["issue"] = issue_link
        else:
            # Get Jira integration details
            jira = task.get_integration("jira")
            jira_url = get_jira_url_from(jira) if jira else None
            rating["issue"] = f"<a href='{jira_url}/browse/{issue}'>{issue}</a>"

        pr_number = pr.get("number", "")
        pr_link = f"<a href='{GITHUB_PREFIX}{repo}/pull/{pr_number}'>PR#{pr_number}</a>"

        html += f"<div class='pr-row'>"
        html += f"<div class='pr-rating-header'>"
        html += f"<label>{pr_link} - {pr.get('title', '')}</label><label class='pr-rating-state capitalize'>{rating['state']}</label> <div class='pr-rating' data-rating='{rating['rating']}'><div class='pr-rating-score'><strong>{rating['rating']}</strong><sub>/5</sub></div></div>"
        html += "</div>"
        html += "<div class='pr-created'>"
        if pr.get("user"):
            html += f"<img src='https://github.com/{pr['user']}.png?size=50'/><label>{pr['user']}</label>"
        if rating["date"]:
            html += f"<label class='pr-date'>"
            if pr.get("state") == "open":
                html += f"Created: {rating['date']}</label>"
            else:
                html += f"Merged/Closed: {rating['date']}</label>"
        if issue and issue != "n/a":
            html += f"<label class='ml-auto pr-issue' >Related Issue: {rating['issue']}</label>"
        html += "</div>"
        html += f"<div class='pr-rating-rationale'>{rationale}</div><div class='read-more'>[+] Read More</div>"
        html += "</div>"
    html += "</div>"
    task.response = html
    task.flags["no_post_process"] = "true"
    task.save()
    return task.response
