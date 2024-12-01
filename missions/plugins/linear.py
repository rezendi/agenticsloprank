import os
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
from ..util import *
from missions import plugins


@plugins.hookimpl
def run_api(task):
    if task.url and task.url.startswith(LINEAR_API):
        linear = get_linear_token(task)
        method = task.url.split("/")[-1]

        match method:
            case "issues":
                get_linear_issues(task, linear)
                return task
    return None


def get_linear_token(task, integration=None):
    # if you don't want to mess with integrations and secrets
    access_token = None
    if not integration:
        integration = task.get_integration("linear")
    if integration:
        secret = integration.secret_set.last()
        access_token = secret.value if secret else None
    else:
        access_token = os.environ.get("LINEAR_API_TOKEN")
    if not access_token:
        raise Exception("No Linear token found")
    return access_token


def get_linear_teams(integration):
    if integration and integration.name and integration.name.startswith("TDTest"):
        return [{"id": "tdtest", "name": "TDTest Linear Team"}]
    try:
        token = get_linear_token(None, integration)
    except Exception as ex:
        log(f"Failed to get Linear token: {ex}")
        return []
    headers = {"Authorization": "Bearer %s" % token, "Content-Type": "application/json"}
    transport = AIOHTTPTransport(url=LINEAR_API, headers=headers)
    client = Client(transport=transport, fetch_schema_from_transport=True)
    # Get teams
    query = gql(
        """
query Teams {
  teams {
    nodes {
      id
      name
    }
  }
}
    """
    )
    result = client.execute(query)
    return result["teams"]["nodes"]


def get_linear_issues(task, linear):
    if hasattr(linear, "is_test") and linear.is_test:
        return linear.get_issues()
    headers = {
        "Authorization": "Bearer %s" % linear,
        "Content-Type": "application/json",
    }
    transport = AIOHTTPTransport(url=LINEAR_API, headers=headers)
    client = Client(transport=transport, fetch_schema_from_transport=True)

    # Get teams and members
    query = gql(
        """
query Teams {
  organization {
    id
    name
    urlKey
    teams {
      nodes {
        id
        name
        description
        issueCount
        organization {
          id
          name
        }
        members {
          nodes {
            id
            name
            displayName
            active
            admin
            createdAt
            updatedAt
            description
            organization {
              id
              name
            }
          }
        }
      }
    }
  }
}
    """
    )
    result = client.execute(query)

    res = h2("Linear Organization")
    res += f"\nName: {result['organization']['name']}"
    res += f"\nSlug: {result['organization']['urlKey']}"
    res += "\n" + h3("Linear Teams")
    teams = result["organization"]["teams"]["nodes"]
    for team in teams:
        res += f"\nTeam Name: {team['name']}" if team.get("name") else ""
        res += (
            f"\nDescription: {team['description']}" if team.get("description") else ""
        )
        for member in team["members"]["nodes"]:
            if member.get("active"):
                res += f"\n{member['name']}"
                res += (
                    f" ({member['displayName']})" if member.get("displayName") else ""
                )
                res += f" - joined {get_days_ago(member, 'createdAt')}"
    task.response = res
    task.save()

    # Get projects
    query = gql(
        """
query Projects {
  projects {
    nodes {
      id
      name
      description
      content
      createdAt
      updatedAt
      startedAt
      targetDate
      completedAt
      canceledAt
    }
  }
}
    """
    )
    result = client.execute(query)
    res += h2("Linear Projects")
    for project in result["projects"]["nodes"]:
        res += h3(f"{project['name']}")
        res += f"{project['description']}" if project.get("description") else ""
        res += f"\nCreated: {get_days_ago(project, 'createdAt')}"
        edit_days_ago = get_edit_days_ago(project, "updatedAt", "createdAt")
        res += f" Updated: {edit_days_ago}\n\n" if edit_days_ago else "\n"
    task.response = res
    task.save()

    query = gql(
        """
query Issues {
  issues(orderBy: updatedAt) {
    nodes {
      identifier
      url
      id
      number
      title
      description
      identifier
      priority
      estimate
      state {
        id
        name
        type
      }
      parent {
        id
        title
      }
      assignee {
        id
        name
      }
      project {
        id
        name
      }
      comments {
        nodes {
          id
          body
          user {
            id
            name
          }
          createdAt
          updatedAt
        }
      }
      createdAt
      updatedAt
      dueDate
      completedAt
      canceledAt
      archivedAt
    }
  }
}
    """
    )
    result = client.execute(query)
    points = {}

    res += h2("Linear Issues")
    all_issues = result["issues"]["nodes"]
    recent = [i for i in all_issues if not is_obsolete(i)]
    res += f"{team['issueCount']} total issues, {len(recent)} recent"
    active = [i for i in recent if not i["state"]["type"] in ("completed", "canceled")]
    res += "\n" + h3(f"Active Issues ({len(active)} total)")
    res += render_issues(active, points)
    completed = [i for i in recent if i["state"]["type"] in ("completed", "canceled")]
    res += "\n" + h3(f"Recently Completed Issues ({len(completed)} total)")
    res += render_issues(completed, points)
    task.structured_data = {"points": points}
    task.response = res


def render_issues(all_issues, points):
    res = ""
    priorities = ["None", "Urgent", "High", "Medium", "Low"]
    for idx in [1, 2, 3, 4, 0]:
        issues = [i for i in all_issues if i["priority"] == idx]
        # filter out completed and cancelled if older than 30 days
        if len(issues) > 0:
            res += h3(f"Priority: {priorities[idx]} ({len(issues)} issues)")
        for issue in issues:
            key = issue["identifier"]
            res += h4("Issue: [%s](%s)" % (key, issue["url"]))
            res += f"\nTitle: {issue['title']}"
            if issue.get("project"):
                res += f"\nProject: {issue['project']['name']}"
            res += f"\nState: {issue['state']['name']}"
            res += f"\nCreated: {get_days_ago(issue, 'createdAt')}"
            edit_days_ago = get_edit_days_ago(issue, "updatedAt", "createdAt")
            res += f"\nUpdated: {edit_days_ago}" if edit_days_ago else ""
            if issue.get("estimate"):
                res += f"\nEstimated complexity: {issue['estimate']:.2f} points"
                d = points.get(key, {})
                d["estimate"] = issue["estimate"]
                points[key] = d
            if issue.get("assignee"):
                res += f"\nAssigned to: {issue['assignee']['name']}"
            if issue.get("description"):
                res += f"\nDescription: {issue['description']}"
            if issue.get("comments") and issue["comments"].get("nodes"):
                res += f"\n\nComments:"
                for comment in issue["comments"]["nodes"]:
                    res += f"\n{comment['user']['name']}, {get_days_ago(comment, 'createdAt')} - {comment['body']}"
            res += "\n\n"
    return res


def is_obsolete(issue):
    return (
        issue["state"]["type"] in ("completed", "canceled")
        and get_days_since(issue, "createdAt") > 30
        and get_days_since(issue, "updatedAt") > 30
    )
