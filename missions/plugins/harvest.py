import datetime, os, requests, time
from types import SimpleNamespace
from ..util import *

HARVEST_ID_URL = "https://id.getharvest.com/api/v2"
# https://github.com/singer-io/tap-harvest-forecast
# https://pkg.go.dev/github.com/joefitzgerald/forecast#section-readme


DERELICT_DAYS = 365


from missions import plugins


@plugins.hookimpl
def run_api(task):
    if task.url and task.url.startswith(HARVEST_API):
        fetch_harvest_projects(task, get_harvest(task))
        return task
    if task.url and task.url.startswith(FORECAST_API):
        fetch_forecast_projects(task, get_harvest(task))
        return task
    return None


def get_harvest(task, integration=None):
    if not integration:
        integration = task.get_integration("harvest")
    if not integration:
        raise Exception("No Harvest integration found")
    secret = integration.secret_set.filter(vendor="harvest").last()
    if not secret:
        raise Exception("No Harvest token found")

    scope = secret.extras.get("scope", "").split()
    harvest_account_id = integration.extras.get("harvest_account_id")
    if not harvest_account_id:
        harvest_scope = [s for s in scope if s.startswith("harvest:")]
        if harvest_scope:
            harvest_account_id = harvest_scope[0].split(":")[1]

    forecast_account_id = integration.extras.get("forecast_account_id")
    if not forecast_account_id:
        forecast_scope = [s for s in scope if s.startswith("forecast:")]
        if forecast_scope:
            forecast_account_id = forecast_scope[0].split(":")[1]
        else:
            harvest_scope = [s for s in scope if s.startswith("harvest:")]
            if harvest_scope:
                forecast_account_id = harvest_scope[0].split(":")[1]

    refreshed = secret.extras.get("refreshed_at", secret.edited_at.timestamp())
    # oauth = false means we're just using a personal access token
    if integration.extras.get("oauth") != "false" and (
        int(time.time()) - int(refreshed) > secret.extras.get("expires_in", 3600)
    ):
        if not secret.refresh:
            raise Exception("No refresh token found")
        url = "https://id.getharvest.com/api/v2/oauth2/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": secret.refresh,
            "client_id": os.environ.get("HARVEST_CLIENT_ID"),
            "client_secret": os.environ.get("HARVEST_CLIENT_SECRET"),
        }
        response = requests.post(url, json=data)
        response_data = response.json()
        if "error" in response_data:
            raise Exception("Error refreshing Harvest token: %s" % response_data)
        elif "access_token" not in response_data:
            raise Exception("No token in Harvest refresh response")
        secret.value = response_data.pop("access_token")
        if "refresh_token" in response_data:
            secret.refresh = response_data.pop("refresh_token")
        secret.extras = response_data
        secret.extras["refreshed_at"] = int(time.time())
        secret.save()
    token = secret.value

    d = {
        "token": token,
        "harvest_account_id": harvest_account_id,
        "forecast_account_id": forecast_account_id,
    }
    return SimpleNamespace(**d)


def fetch(harvest, endpoint, forecast=False, id=False):
    if hasattr(harvest, "is_test") and harvest.is_test:
        return harvest.fetch(endpoint)
    base = FORECAST_API if forecast else HARVEST_API
    base = HARVEST_ID_URL if id else base
    url = f"{base}/{endpoint}"
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer " + harvest.token,
        "User-Agent": "YamLLMs (info@%s)" % settings.BASE_DOMAIN,
    }
    if not id and not forecast:
        headers["Harvest-Account-Id"] = "%s" % harvest.harvest_account_id
    if forecast:
        headers["Forecast-Account-Id"] = "%s" % harvest.forecast_account_id
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise Exception(f"Failed to fetch {url}: {r.text}")
    vals = r.json()
    # TODO pagination?
    # namespacing dicts may be in the "seemed like a good idea at the time" category
    if isinstance(vals, dict) and len(vals) == 1:
        vals = list(vals.values())[0]
    if isinstance(vals, list):
        return [SimpleNamespace(**val) for val in vals]
    return SimpleNamespace(**vals)


def get_accounts(harvest):
    accounts = fetch(harvest, "accounts", id=True)
    return accounts


def get_harvest_projects(integration):
    if integration and integration.name and integration.name.startswith("TDTest"):
        return [
            {"id": "tdt1", "name": "TDTest Harvest Project 1"},
            {"id": "tdt2", "name": "TDTest Harvest Project 2"},
        ]
    harvest = get_harvest(None, integration)
    try:
        projects = fetch(harvest, "projects")
        return projects if isinstance(projects, list) else projects.projects
    except Exception as ex:
        log(f"Failed to get Harvest projects: {ex}")
        return []


def fetch_forecast_projects(task, harvest):
    log("Fetching Forecast data")
    quants = {}

    # first, get the people to populate the project data with
    # roles = fetch(harvest, "roles", forecast=True)
    people = fetch(harvest, "people", forecast=True)
    people = {p.id: p for p in people}
    placeholders = fetch(harvest, "placeholders", forecast=True)
    placeholders = {p.id: p for p in placeholders}

    # next, get the client(s)
    unknown = SimpleNamespace(id=-1, name="Unknown", latest_start=-9999)
    clients = fetch(harvest, "clients", forecast=True)
    clients.append(unknown)
    for client in clients:
        client.projects = []
    target_client = task.get_project_value("forecast_client")
    if target_client:
        log("Client:", target_client)
        clients = [c for c in clients if c.name == target_client]
    clients_by_id = {c.id: c for c in clients}

    projects = fetch(harvest, "projects", forecast=True)
    projects = [p for p in projects if not p.archived]
    target_projects = task.get_project_value("forecast_projects")
    if target_projects:
        log("Projects:", target_projects)
        projects = [p for p in projects if p.name in target_projects]
    for project in projects:
        project.milestones = []
    projects_by_id = {project.id: project for project in projects}

    milestones = fetch(harvest, "milestones", forecast=True)
    for milestone in milestones:
        if milestone.project_id in projects_by_id:
            project = projects_by_id[milestone.project_id]
            project.milestones.append(milestone)

    for project in projects:
        if not project.start_date:
            continue
        if project.end_date and get_days_since(project.end_date) > DERELICT_DAYS:
            continue
        client_id = project.client_id
        client = clients_by_id[client_id] if client_id in clients_by_id else unknown
        client.projects.append(project)

    r = h2("Harvest Forecast allocations")
    r += "Today is %s\n\n" % datetime.datetime.now().strftime("%Y-%m-%d")
    r += h3("Recent Projects")
    for client in clients:
        projects = [p for p in client.projects if is_project_active(p)]
        if projects:
            r += f"\n\n### Client: {client.name}\n"
            for project in projects:
                r += render_forecast_project(
                    harvest, project, people, placeholders, quants=quants
                )

    r += "\n" + h3("Previous Projects")
    for client in clients:
        projects = [p for p in client.projects if not is_project_active(p)]
        if projects:
            r += "\n" + h3(f"Client: {client.name}")
            for project in projects:
                r += render_forecast_project(harvest, project, quants=quants)

    task.response = r
    task.structured_data = quants
    return r


def is_project_active(project):
    now = datetime.datetime.now()
    if project.start_date:
        start = datetime.datetime.fromisoformat(project.start_date)
        if (now - start).days < 0:
            return True
    if project.end_date:
        end = datetime.datetime.fromisoformat(project.end_date)
        if (now - end).days < 7:
            return True
    return False


def render_forecast_project(harvest, project, people=None, holders=None, quants={}):
    log("Rendering", project.name)
    r = "\n" + h4(f"Project: {project.name}")
    r += f"\nStart date: %s" % get_days_ago(project.start_date)
    r += f"\nEnd date: %s" % get_days_ago(project.end_date)
    r += f"\nLast update: %s" % get_days_ago(project.updated_at)
    if project.notes:
        r += h5("Notes")
        r += f"{project.notes}"
    if project.tags:
        r += h5("Tags")
        r += f"{', '.join(project.tags)}"
    if hasattr(project, "milestones"):
        r += h5("Milestones")
        for milestone in project.milestones:
            r += f"\n- {milestone.name} ({get_days_ago(milestone.date)})"
    if people and holders:
        args = f"project_id={project.id}"
        start = datetime.datetime.now() - datetime.timedelta(days=30)
        args += "&start_date=%s" % start.strftime("%Y-%m-%d")
        end = datetime.datetime.now() + datetime.timedelta(days=60)
        args += "&end_date=%s" % end.strftime("%Y-%m-%d")
        assignments = fetch(harvest, "assignments?%s" % args, forecast=True)
        r += h5("Assignments")
        for a in assignments:
            r += f"\n- {a.start_date} to {a.end_date}"
            person = None
            if a.person_id and a.person_id in people:
                person = people[a.person_id]
            if person:
                r += f" {person.first_name} {person.last_name} ({', '.join(person.roles)})"
            elif a.placeholder_id and a.placeholder_id in holders:
                ph = holders[a.placeholder_id]
                r += f" Placeholder: {ph.name} ({', '.join(ph.roles)})"
            if a.allocation:
                hours = a.allocation / 3600
                r += f" allocation {hours} hours"
                if person:
                    quant = quants.get(person.id, {})
                    quant["name"] = f"{person.first_name} {person.last_name}"
                    allocations = quant.get("allocations", [])
                    allocations.append(
                        {
                            "project": project.name,
                            "start": a.start_date,
                            "end": a.end_date,
                            "hours": hours,
                        }
                    )
                    quant["allocations"] = allocations
                    quants[person.id] = quant
            if a.notes:
                r += f" ({a.notes})"
    return r


def fetch_harvest_projects(task, harvest):
    log("Fetching Harvest data")
    quants = {}

    r = h2("Harvest People")
    users = fetch(harvest, "users?is_active=true")
    for user in users.users:
        user = SimpleNamespace(**user)
        r += f"\n- {user.first_name} {user.last_name} ({', '.join(user.roles)})"
        if user.is_contractor:
            r += " (contractor)"

    r += "\n" + h2("Harvest Projects")
    r += "\nToday is %s\n\n" % datetime.datetime.now().strftime("%Y-%m-%d")

    target_client = task.get_project_value("harvest_client", "")
    log("Target client:", target_client)
    target_projects = task.get_project_value("harvest_projects", [])
    if target_projects:
        log("Target projects:", target_projects)

    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)
    cutoff = cutoff.strftime("%Y-%m-%d")
    # TODO be smarter about what to and not to include?
    projects = fetch(harvest, "projects?is_active=true")
    clients = {}
    for project in projects.projects:
        if (
            target_projects
            and project["name"] not in target_projects
            and "%s" % project["id"] not in target_projects
        ):
            continue
        if target_client and project["client"]["name"] != target_client:
            continue
        id = project["client"]["id"]
        if not id in clients:
            clients[id] = {"name": project["client"]["name"], "projects": []}
        client = clients[id]
        client["projects"].append(project)
    for cid, client in clients.items():
        r += h3(f"Client: {client['name']}")
        for project in client["projects"]:
            id = project["id"]
            entries = fetch(harvest, f"time_entries?project_id={id}&from={cutoff}")
            people = fetch(harvest, f"projects/{id}/user_assignments?is_active=true")
            tasks = fetch(harvest, f"projects/{id}/task_assignments?is_active=true")
            r += render_harvest_project(project, people, tasks, entries, quants)
        r += "\n\n"
    task.response = r
    task.structured_data = quants


def render_harvest_project(project, people, tasks, entries, quants={}):
    project = SimpleNamespace(**project)
    log("Rendering", project.name)
    r = "\n" + h4(f"Project: {project.name}")
    r += f"\nStart date: %s" % get_days_ago(project.starts_on)
    r += f"\nEnd date: %s" % get_days_ago(project.ends_on) if project.ends_on else ""
    r += "\n"
    # r += f"\nLast update: %s" % get_days_ago(project.updated_at)
    if project.notes:
        r += f"\nNotes:\n{project.notes}"
    if entries.time_entries:
        r += h5("Time entries")
    for entry in entries.time_entries:
        entry = SimpleNamespace(**entry)
        r += f"\nUser: {entry.user['name']if entry.user else ''} Task: {entry.task['name'] if entry.task else ''}"
        r += f"\n- {entry.spent_date} {entry.hours} hours"
        if entry.notes:
            r += f" ({entry.notes})"
        quant = quants.get(entry.user["id"], {})
        quant["name"] = entry.user["name"]
        entries = quant.get("entries", [])
        entries.append(
            {
                "project": project.name,
                "date": entry.spent_date,
                "hours": entry.hours,
            }
        )
        quant["entries"] = entries
        quants[entry.user["id"]] = quant

    if people.user_assignments:
        r += "\n" + h5("Assignments")
    for assign in people.user_assignments:
        assign = SimpleNamespace(**assign)
        r += f"\n- {assign.user['name']}"
    if tasks.task_assignments:
        r += "\n" + h5("Tasks")
    for task in tasks.task_assignments:
        task = SimpleNamespace(**task)
        r += f"\n- {task.task['name']}"
    return r
