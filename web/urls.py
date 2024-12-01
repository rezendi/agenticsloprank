from django.urls import include, path

from . import views, staff_views, oauth_views

staff_patterns = [
    # Staff URLs
    path("missions/", staff_views.missions, name="missions"),
    path("mission/<int:mission_id>/", staff_views.mission, name="mission"),
    path("task/<int:task_id>/", staff_views.task, name="task"),
    path("raw_data/<int:raw_data_id>/", staff_views.raw_data, name="raw_data"),
    path("mission_info/<int:id>/", staff_views.mission_info, name="mission_info"),
    path("cache_bust", staff_views.cache_bust, name="cache_bust"),
]

urlpatterns = [
    # public URLs
    path("", views.index, name="index"),
    path("reports/", views.reports, name="reports"),
    path("running/", views.running_latest, name="running"),
    path("reports/<int:mission_id>/", views.report, name="report"),
    path("running/<int:mission_id>/", views.running, name="running"),
    path("followup/<int:mission_id>/", views.followup, name="followup"),
    path("ask_followup/", views.ask_followup, name="ask_followup"),
    path("accounts/login/", views.login, name="login"),
    path("login/", views.login, name="login"),
    path("logout/", views.logout_view, name="logout_view"),
    # OAuth URLs
    path("github/setup/", oauth_views.setup_github, name="setup_github"),
    path("github/setup2/", oauth_views.setup_github, name="setup_github"),
    path("github/webhook", oauth_views.github_webhook, name="github_webhook"),
    path("github/webhook2", oauth_views.github_webhook_2, name="github_webhook"),
    path("github/callback", oauth_views.setup_github, name="setup_github"),
    path("github/callback2", oauth_views.setup_github, name="setup_github"),
    path("linear/setup/", oauth_views.linear_oauth, name="linear_oauth"),
    path("linear/callback", oauth_views.linear_callback, name="linear_callback"),
    path("notion/setup/", oauth_views.notion_oauth, name="notion_oauth"),
    path("notion/callback", oauth_views.notion_callback, name="notion_callback"),
    path("jira/setup/", oauth_views.jira_oauth, name="jira_oauth"),
    path("jira/callback", oauth_views.jira_callback, name="jira_callback"),
    path("slack/setup/", oauth_views.slack_oauth, name="slack_oauth"),
    path("slack/callback", oauth_views.slack_callback, name="slack_callback"),
    path("figma/setup/", oauth_views.figma_oauth, name="figma_oauth"),
    path("figma/callback", oauth_views.figma_callback, name="figma_callback"),
    path("monday/setup/", oauth_views.monday_oauth, name="monday_oauth"),
    path("monday/callback", oauth_views.monday_callback, name="monday_callback"),
    path("sentry/setup/", oauth_views.sentry_oauth, name="sentry_oauth"),
    path("sentry/callback", oauth_views.sentry_callback, name="sentry_callback"),
    path("harvest/callback", oauth_views.harvest_callback, name="harvest_callback"),
    # API URLs
    path("missions/create_task", views.create_task, name="create_task"),
    path("missions/<int:mission_id>.json", views.mission_json, name="mission_json"),
    path("missions/lucky.json", views.lucky_json, name="lucky_json"),
    path("mission_tasks/<int:mission_id>.json", views.tasks_json, name="tasks_json"),
    path(
        "mission_status/<int:mission_id>.json",
        views.mission_status_json,
        name="mission_status_json",
    ),
    # staff
    path("staff", staff_views.customers, name="customers"),
    path("staff/", include(staff_patterns)),
]
