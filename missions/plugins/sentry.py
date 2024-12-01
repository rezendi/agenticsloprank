import os, requests, datetime
from ..util import *
from missions import plugins


@plugins.hookimpl
def run_api(task):
    if task.url and task.url.startswith(SENTRY_API):
        get_sentry(task)
        return task
    return None


def get_sentry(task, integration=None):
    access_token = None
    if not integration:
        integration = task.get_integration("sentry")
    if integration:
        secret = integration.secret_set.filter(vendor="sentry").last()
        access_token = secret.value if secret else None
    else:
        access_token = os.environ.get("SENTRY_API_TOKEN")
    if not access_token:
        raise Exception("No Sentry token found")

    # PAT stored as a secret
    if not secret or secret.extras.get("oauth") == "false":
        return access_token

    expires = secret.extras.get("expiresAt")
    if expires:
        expires = datetime.datetime.fromisoformat(expires)
    if datetime.datetime.now() > expires:
        # refresh the token
        if not secret.refresh:
            raise Exception("No refresh token found")
        url = (
            "https://sentry.io/api/0/sentry-app-installations/%s/authorizations/"
            % secret.extras.get("install_id")
        )
        data = {
            "grant_type": "refresh_token",
            "refresh_token": secret.refresh,
            "client_id": os.environ.get("SENTRY_CLIENT_ID"),
            "client_secret": os.environ.get("SENTRY_CLIENT_SECRET"),
        }
        response = requests.post(url, json=data)
        response_data = response.json()
        if "error" in response_data:
            raise Exception("Error refreshing Sentry token: %s" % response_data)
        elif "token" not in response_data:
            raise Exception("No token in Sentry refresh response")
        secret.value = response_data.pop("token")
        if "refreshToken" in response_data:
            secret.refresh = response_data.pop("refreshToken")
        secret.extras = response_data
        secret.save()

    return secret.value


def fetch(token, endpoint):
    base = SENTRY_API
    url = f"{base}/{endpoint}"
    headers = {"Authorization": "Bearer " + token}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise Exception(f"Failed to fetch {url}", r, r.text)
    vals = r.json()
    return vals


def get_sentry_orgs(task, integration=None):
    token = get_sentry(task, integration)
    orgs = fetch(token, "organizations/")
    return orgs


def get_sentry_projects(task, integration=None):
    token = get_sentry(task, integration)
    projects = fetch(token, "projects/")
    return projects


def get_sentry_events(task, integration=None):
    token = get_sentry(task, integration)
    orgs = fetch(token, "organizations/")
    r = ""
    for org in orgs:
        org_slug = org["slug"]
        r += h2("Sentry Issues: %s" % org["name"])
        projects = fetch(token, f"organizations/{org_slug}/projects/")
        for project in projects:
            r = "\n\n" + h3("Sentry Project: %s" % project["name"])
            events = fetch(token, f"projects/{org_slug}/{project['id']}/issues/")
            if not events:
                r += "No events found"
            for event in events:
                r += h4(f"{event['title']}")
                r += f"Last seen: {get_days_ago(event, 'lastSeen')}\n"
                r += f"First seen: {get_days_ago(event, 'firstSeen')}\n"
                r += "Level: %s\n" % event["level"]
                r += "Count: %s\n" % event["count"]
                r += "Status: %s\n" % event["status"]
        if task:
            task.response = r
        return r
