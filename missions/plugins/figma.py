import os, requests, time, urllib
import FigmaPy as figmapy  # type: ignore
from ..util import *
from missions import plugins

DAYS_CUTOFF = 180
TIME_SERIES_DAYS_CUTOFF = 60

# TODO components https://www.figma.com/developers/api#library-items


@plugins.hookimpl
def run_api(task):
    if task.url and task.url.startswith(FIGMA_API):
        figma = get_figma(task)
        get_figma_files(task, figma)
        return task
    return None


def get_figma(task, integration=None):
    if not integration:
        integration = task.get_integration("figma")
    if not integration:
        token = os.environ.get("FIGMA_API_TOKEN")
        if not token:
            raise Exception("No Figma token found")
        return figmapy.FigmaPy(token=secret.value, oauth2=False)
    secret = integration.secret_set.filter(vendor="figma").last()
    if not secret:
        raise Exception("No Figma secret found")

    latest = secret.edited_at.timestamp()
    diff = int(time.time()) - int(float(latest))
    if diff > secret.extras.get("expires_in", 7776000):
        # refresh the token
        if not secret.refresh:
            raise Exception("No refresh token found")

        url = "https://www.figma.com/api/oauth/refresh"
        args = {
            "client_id": os.environ.get("FIGMA_CLIENT_ID"),
            "client_secret": os.environ.get("FIGMA_CLIENT_SECRET"),
            "refresh_token": secret.refresh,
        }
        url += "?" + urllib.parse.urlencode(args)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(url, headers=headers)
        response_data = response.json()
        if "error" in response_data:
            raise Exception("Error refreshing Figma token: %s" % response_data)
        elif "access_token" not in response_data:
            raise Exception("No access token in Figma refresh response")
        secret.value = response_data.pop("access_token")
        if "refresh_token" in response_data:
            secret.refresh = response_data.pop("refresh_token")
        secret.extras = response_data
        secret.extras["refreshed_at"] = int(time.time())
        secret.save()

    # set "oauth2"="false" in extras if it's a PAT stored there
    oauth2 = integration.extras.get("oauth2", "true") == "true"
    return figmapy.FigmaPy(token=secret.value, oauth2=oauth2)


def get_figma_projects(integration, figma_team=None):
    if integration and integration.name and integration.name.startswith("TDTest"):
        return [{"id": "tdtest", "name": "TDTest Figma Project"}]
    if not integration:
        return []
    try:
        figma = get_figma(None, integration)
    except Exception as ex:
        log("Error getting Figma", ex)
        return []
    if not figma_team:
        tier = integration.project if integration.project else integration.customer
        figma_team = tier.extras.get("figma_team")
    projects = figma.get_team_projects(figma_team)
    return (
        [{"id": p["id"], "name": p["name"]} for p in projects.projects]
        if projects
        else []
    )


def get_figma_projects_for(task, figma):
    team = task.get_project_value("figma_team")
    projects = figma.get_team_projects(team)
    return projects.projects if projects else []


def get_figma_files(task, figma):
    r = ""
    structured = {}
    projects = []
    all_projects = get_figma_projects_for(task, figma)
    config_projects = task.get_project_value("figma_projects", [])
    for project in all_projects:
        if (
            not config_projects
            or project["name"] in config_projects
            or project["id"] in config_projects
        ):
            projects.append(project)

    structured["projects"] = projects
    structured["files"] = []
    cutoff = TIME_SERIES_DAYS_CUTOFF if task.is_time_series() else DAYS_CUTOFF
    for project in projects:
        log("Considering project", project["name"])
        r += h3(f"Figma project: {project['name']}")
        files = figma.get_project_files(project["id"])
        log("Total files", len(files.files))
        for file in sorted(files.files, key=lambda x: x["last_modified"], reverse=True):
            log("Considering file", file["name"])
            last_modified = get_days_since(file["last_modified"])
            if last_modified > cutoff:
                continue
            r += "\n" + h4(f"File: {file['name']}")
            r += f"\nLast modified: {get_days_ago(file['last_modified'])}\n"
            r += f"![{file['name']}]({file['thumbnail_url']})\n"

            new_version = False
            versions = figma.get_file_versions(file["key"])
            if versions:
                r += h5(f"Versions: {len(versions.versions)}")
                for version in versions.versions:
                    if get_days_since(version["created_at"]) < task.cadence_days():
                        new_version = True
                        r += f"\nnew version by {version['user']['handle']} {get_days_ago(version['created_at'])}"
                        if version["label"]:
                            r += f" ({version['label']})"
                        if version["description"]:
                            r += f"\n{version['description']}\n"

            if not new_version and versions.versions:
                r += (
                    f"\nMost recent: {get_days_ago(versions.versions[0]['created_at'])}"
                )

            r += "\n"
            new_comments = False
            comments = figma.get_comments(file["key"])
            days = task.cadence_days() or 7
            new_comments = [
                c for c in comments.comments if get_days_since(c.created_at) < days
            ]
            old_comments = [c for c in comments.comments if c not in new_comments]
            if new_comments:
                r += h5(f"New comments: {len(new_comments)}")
                for comment in new_comments:
                    r += f"\n{comment.user['handle']} - {get_days_ago(comment.created_at)}"
                    if comment.resolved_at:
                        r += f"resolved {get_days_ago(comment.resolved_at)}"
                    r += f" - {comment.message}"
                old_comments = old_comments[:40]
                if old_comments:
                    r += "\n" + h5(f"Previous {len(old_comments)} comments:")
                    for comment in old_comments:
                        r += f"\n{comment.user['handle']} - {get_days_ago(comment.created_at)}"
                        if comment.resolved_at:
                            r += f", resolved {get_days_ago(comment.resolved_at)}"
                        r += f" - {comment.message}"

            structured["files"].append(
                {
                    "project_id": project["id"],
                    "name": file["name"],
                    "key": file["key"],
                    "versions": [
                        {
                            "created_at": v["created_at"],
                            "user": v["user"],
                            "label": v["label"],
                            "description": v["description"],
                        }
                        for v in versions.versions
                    ],
                    "comments": [
                        {
                            "from": c.user,
                            "message": c.message,
                            "created_at": c.created_at,
                            "resolved_at": c.resolved_at,
                        }
                        for c in comments.comments
                    ],
                }
            )
            task.structured_data = structured

            if new_version and task.flags.get("figma_frames") == "true":
                # this API response can be 50-100MB+ in size(!)
                details = figma.get_file(file["key"])
                children = [x for x in details.document["children"]]
                frames = []
                for child in children:
                    subchildren = [x for x in child["children"]]
                    frames = [x for x in subchildren if x["type"] == "FRAME"]
                    images = None
                    if task.flags.get("figma_images") == "true":
                        ids = [f["id"] for f in frames]
                        images = figma.get_file_images(file_key=file["key"], ids=ids)

                    if frames:
                        r += h5(f"Frames: {len(frames)}")
                        for frame in frames:
                            id = frame["id"]
                            r += f"\n{frame['name']}"
                            if images and id in images.images:
                                r += f"![{frame['name']}]({images.images[id]})\n"
                        r += "\n"

            task.response = r
            task.save()

    task.response = r
