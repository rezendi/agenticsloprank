import datetime, os
from slack_sdk import WebClient
from ..util import *
from missions import plugins


@plugins.hookimpl
def run_api(task):
    if task.url and task.url.startswith(SLACK_API):
        slack = get_slack(task)
        method = task.url.split("/")[-1]

        match method:
            case "channels":
                get_slack_chatter(task, slack)
                return task
    return None


def get_slack(task, integration=None):
    access_token = None
    if not integration:
        integration = task.get_integration("slack")
    if integration:
        secret = integration.secret_set.last()
        access_token = secret.value if secret else None
    else:
        access_token = os.environ.get("SLACK_API_TOKEN")
    if not access_token:
        raise Exception("No Slack token found")
    return WebClient(token=secret.value)


def get_slack_channels(integration):
    if integration and integration.name and integration.name.startswith("TDTest"):
        return [
            {"id": "tdtest", "name": "TDTest Slack Channel"},
            {"id": "tdtest2", "name": "TDTest Slack Channel 2"},
            {"id": "tdtest3", "name": "TDTest Slack Channel 3"},
        ]
    slack = get_slack(None, integration)
    channels = slack.conversations_list()
    return [
        {"id": channel["id"], "name": channel["name"]}
        for channel in channels["channels"]
    ]


def get_slack_chatter(task, slack):
    task.response = "Today is %s\n\n" % datetime.datetime.now().strftime("%Y-%m-%d")
    (users, user_string) = get_slack_users(slack)
    task.response += h2("Slack Channels")
    channels = slack.conversations_list()
    exclude = task.get_project_value("slack_exclude", [])
    include = task.get_project_value("slack_include", [])
    for channel in channels["channels"]:
        if include and not channel["name"] in include and not channel["id"] in include:
            continue
        task.response += h3(f"Channel: {channel['name']}")
        task.response += f"Created: {channel['created']} updated {channel['updated']}\n"
        task.response += f"Archived: {channel['is_archived']}\n"
        task.response += f"Topic: {channel['topic']['value']}\n"
        task.response += f"Purpose: {channel['purpose']['value']}\n"
        if channel["name"] in exclude or channel["id"] in exclude:
            continue
        task.response += h4(f"Recent Conversation: {channel['name']}")
        task.response += render_recent_conversation(task, slack, users, channel["id"])
    task.response += user_string


def render_recent_conversation(task, slack, users, channel_id):
    response = ""
    cutoff_days = task.cadence_days() * 2 if task.is_time_series() else 30
    cutoff = datetime.datetime.now() - datetime.timedelta(days=cutoff_days)
    history = slack.conversations_history(
        channel=channel_id, oldest=cutoff.timestamp(), limit=999
    )
    current = 0
    for message in history["messages"][::-1]:
        ts = int(float(message["ts"]))
        if ts - current > 3000:
            response += "\n" + h5(f"{datetime.datetime.fromtimestamp(ts)}")
            current = ts
        user_id = message.get("user", "n/a")
        user = users[user_id] if user_id in users else user_id
        if "text" in message:
            response += f"{user}: {message['text']}\n"
    return response


def get_slack_users(slack):
    slack_users = {}
    users = slack.users_list()
    r = h2("Slack Users")
    for user in users["members"]:
        r += h3(f"User: {user['name']}")
        r += f"ID: {user['id']}\n"
        slack_users[user["id"]] = user["name"]
        r += add_line("Real Name", user)
        profile = user["profile"]
        r += add_line("Email", profile)
        r += add_line("Title", profile)
        r += add_line("Phone", profile)
        r += add_line("Status", profile, "status_text")
        r += add_line("Status Emoji", profile)
        r += add_line("Time Zone", user, "tz")
        r += add_line("Is Admin", user)
        r += add_line("Is Owner", user)
        r += add_line("Is Primary Owner", user)
        r += add_line("Is Restricted", user)
        r += add_line("Is Ultra Restricted", user)
        r += add_line("Is Bot", user)
        r += add_line("Is Deleted", user)
    return (slack_users, r)


def add_line(title, vals, key=None):
    key = title.lower().replace(" ", "_") if key is None else key
    return f"{title}: {vals[key]}\n" if key in vals and vals[key] else ""
