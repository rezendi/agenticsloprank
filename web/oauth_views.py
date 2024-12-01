import hashlib, hmac, json, requests, os, urllib
from requests.auth import HTTPBasicAuth
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template import loader
from missions.models import Customer, Project, Secret, Integration, User
from missions.util import BASE_PREFIX, log


def get_user(request):
    # let staff view pages as user do
    if request.user.is_staff and "user" in request.GET:
        user = User.objects.get(id=request.GET["user"])
        log("user override to", user)
        return user
    return request.user


def active_project(request):
    if request.user.is_authenticated:
        if request.user.active_project():
            return request.user.active_project()
        if "project_id" in request.GET:
            project = Project.objects.get(id=request.GET["project_id"])
            if project.customer != request.user.customer:
                raise Exception("Project does not match customer")
    return None


def create_secret(vendor, customer, project, access_token, response_data):
    integration = Integration.objects.filter(
        customer=customer, project=project, vendor=vendor
    ).last()
    if not integration:
        log(f"Creating new integration for customer {customer} project {project}")
        integration = Integration.objects.create(
            customer=customer,
            project=project,
            vendor=vendor,
        )

    # GitHub install IDs are not secrets, store on the install
    if vendor in ["github", "github2"]:
        integration.extras["install_id"] = access_token
        integration.save()

    # store refresh token separately, also encrypted
    refresh_token = None
    if "refresh_token" in response_data:
        refresh_token = response_data.pop("refresh_token")
    elif "refreshToken" in response_data:
        refresh_token = response_data.pop("refreshToken")

    return Secret.objects.create(
        customer=customer,
        project=project,
        integration=integration,
        vendor=vendor,
        value=access_token,
        refresh=refresh_token,
        extras=response_data,
    )


# GitHub


# TODO refactor this so it makes more sense and doesn't have to wait for the webhook
# this gets tricky because we need to handle both customer and project integrations
# and setup can be called before or after the webhook, it turns out
def setup_github(request):
    integration = None
    project = active_project(request)
    customer = request.user.customer if request.user.is_authenticated else None

    # metadata-only setup, with our alternate GitHub app
    vendor = "github"
    for key in ["setup2", "callback2"]:
        if key in request.path_info:
            vendor = "github2"

    if customer:
        if customer.extras.get("github_metadata_only") == "true":
            path = request.get_full_path()
            if "setup2" not in path and "callback2" not in path:
                new_path = path.replace("/setup", "/setup2")
                new_path = new_path.replace("/callback", "/callback2")
                return redirect(new_path)
        if project:
            integration = project.integration_set.filter(vendor=vendor).last()
        if not integration:
            integration = customer.integration_set.filter(vendor=vendor).last()
    install_id = request.GET.get("installation_id")
    setup_action = request.GET.get("setup_action")

    if setup_action == "install" and install_id:
        integration = Integration.objects.filter(extras__install_id=install_id).last()
        if integration:
            secret = integration.secret_set.filter(vendor=vendor).last()
            if customer and integration.customer != customer:
                log("Existing integration does not match customer")
                integration = None
            if project and integration.project != project:
                log("Existing integration does not match project")
                integration = None
            if not secret or secret.value != install_id:
                integration = None

        if integration and not customer:
            customer = integration.customer
        if not customer:
            customer = Customer.objects.create()
            if request.user.is_authenticated:
                request.user.customer = customer
                request.user.save()
        if not integration:
            secret = create_secret(vendor, customer, project, install_id, {})
            integration = secret.integration

        if vendor == "github2":
            integration.extras["metadata_only"] = "true"
            integration.save()

        # if install and customer no mission template, return to complete integrations (for now)
        if customer and not customer.missioninfo_set.all():
            return redirect("/config/integrations")

    if setup_action == "install" and request.session.get("config") == "true":
        return redirect("/config/integrations")

    template = loader.get_template("oauth/github.html")
    if "setup2" in request.path_info or "callback2" in request.path_info:
        template = loader.get_template("oauth/github_2.html")
    context = {"customer": customer, "integration": integration, "action": setup_action}
    return HttpResponse(template.render(context, request))


@csrf_exempt
def github_webhook(request):
    # check against webhook secret
    secret_token = os.environ.get("GITHUB_WEBHOOK_SECRET").encode("utf-8")
    hash_object = hmac.new(secret_token, msg=request.body, digestmod=hashlib.sha256)
    expected = "sha256=" + hash_object.hexdigest()
    signature = request.headers["X-Hub-Signature-256"]
    if not hmac.compare_digest(expected, signature):
        log("Signatures didn't match!")
        raise PermissionDenied("Signatures didn't match!")
    event = request.headers["X-GitHub-Event"]
    delivery_id = request.headers["X-GitHub-Delivery"]
    post = json.loads(request.body)
    return handle_github_webhook(post, event, delivery_id)


# webhook for metadata-only GitHub app, TODO separate webhook secret here as well
@csrf_exempt
def github_webhook_2(request):
    event = request.headers["X-GitHub-Event"]
    delivery_id = request.headers["X-GitHub-Delivery"]
    post = json.loads(request.body)
    return handle_github_webhook(post, event, delivery_id)


# split into a different method to be testable
def handle_github_webhook(post, event, delivery_id):
    sender_key = "organization" if post.get("organization") else "sender"
    handle = post.get(sender_key).get("login")
    install_id = "%s" % post.get("installation").get("id")
    action = post.get("action")
    post["github_delivery_id"] = delivery_id
    post["github_event"] = event

    # get existing project/customer if any
    # we should always have an integration and a corresponding customer for an install
    # unlike other flows here, webhook means no active project, so we store install ID at setup time above
    project = None
    customer = None
    integration = Integration.objects.filter(extras__install_id=install_id).last()
    if integration:
        project = integration.project
        customer = integration.customer
    if not project:
        project = Project.objects.filter(extras__github_install=install_id).last()
    if project and not customer:
        customer = project.customer
    if not customer:
        customer = Customer.objects.filter(git_handle=handle).last()

    try:
        # webhook can be called before setup, so we need to create a customer if we don't have one
        secret = None
        if integration:
            secret = integration.secret_set.filter(
                vendor__in=["github", "github2"]
            ).last()
            customer = customer if customer else integration.customer

        if not customer:  # paranoia
            log("Creating new GitHub customer in webhook from integration")
            customer = Customer.objects.create()

        # this is the first time we get the customer's GitHub info
        customer.name = customer.name if customer.name else handle
        customer.git_handle = handle
        customer.save()

        # create secret if new
        if not secret or secret.value != install_id:
            secret = create_secret("github", customer, project, install_id, action)
            integration = secret.integration

        # save the action for potential later usage
        integration.extras["actions"] = integration.extras.get("actions", []) + [post]
        integration.save()

        if event == "installation":
            if action == "deleted":
                integration.extras["deleted"] = "true"
                integration.extras["repos"] = []
                if secret:
                    secret.delete()

            if action == "created":
                integration.extras.pop("revoked", "")
                integration.extras.pop("deleted", "")
                integration.extras["repos"] = post.get("repositories", [])

        if event == "installation_repositories":
            existing = integration.extras.get("repos", [])
            removed = post.get("repositories_removed")
            for repo in removed:
                existing.remove(repo)
            added = post.get("repositories_added")
            for repo in added:
                existing.append(repo)
            integration.extras["repos"] = existing

        if event == "github_app_authorization":
            if action == "revoked":
                integration.extras["revoked"] = "true"

        integration.save()
        return HttpResponse(status=204)
    except Exception as ex:
        log(ex)
        log("action %s" % action)
        raise


# Generic OAuth flow
# This method is ussed by other OAuth views to parse the response and create a secret
def parse_token_response(request, response_data, vendor):
    context = {}
    state = request.GET.get("state")
    id = int(state.split("-")[0])
    customer = Customer.objects.filter(id=id).first()
    if not customer:
        context = {"error": "Invalid OAuth YamLLMs %s customer" % vendor}
    r = int(state.split("-")[1])
    seed = os.environ.get("%s_CLIENT_SECRET" % vendor.upper()) + customer.name
    if r != int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 10**8:
        context = {"error": "Invalid OAuth YamLLMs %s state" % vendor}
    access_token = response_data.pop("access_token", "")
    if vendor == "sentry":
        access_token = response_data.pop("token", "")
    if not access_token:
        context = {"error": "No access token found in response"}
    if not "error" in context:
        project = active_project(request)
        create_secret(vendor, customer, project, access_token, response_data)
    return context


# Linear


def get_linear_query(customer):
    seed = os.environ.get("LINEAR_CLIENT_SECRET") + customer.name
    rando = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 10**8
    state = "%s-%s" % (customer.id, rando)
    args = {
        "client_id": os.environ.get("LINEAR_CLIENT_ID"),
        "scope": "read",
        "redirect_uri": BASE_PREFIX + "/linear/callback",
        "response_type": "code",
        "prompt": "consent",
        "actor": "user",
        "state": state,
    }
    return urllib.parse.urlencode(args)


@login_required
def linear_oauth(request):
    template = loader.get_template("oauth/linear.html")
    customer = request.user.customer
    if not customer:
        context = {"error": "Not a customer - contact support%s" % settings.BASE_DOMAIN}
        return HttpResponse(template.render(context, request))
    linear_query = get_linear_query(customer)
    return HttpResponse(template.render({"linear_query": linear_query}, request))


def linear_callback(request):
    context = {}
    try:
        # exchange code for access token
        code = request.GET.get("code")
        url = "https://api.linear.app/oauth/token"
        data = {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": BASE_PREFIX + "/linear/callback",
            "client_id": os.environ.get("LINEAR_CLIENT_ID"),
            "client_secret": os.environ.get("LINEAR_CLIENT_SECRET"),
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(url, data=data, headers=headers)
        response_data = response.json()
        if "error" in response_data:
            context["error"] = response_data.get("error_description", "Token error")
        elif "access_token" not in response_data:
            context["error"] = "No access token in response"
        else:
            context = parse_token_response(request, response_data, "linear")

    except Exception as ex:
        log("Exception in Linear callback", ex)
        context = {"error": ex}
    if request.session.get("config") == "true":
        return redirect("/config/integrations")
    template = loader.get_template("oauth/linear_callback.html")
    return HttpResponse(template.render(context, request))


def get_notion_query(customer):
    seed = os.environ.get("NOTION_CLIENT_SECRET") + customer.name
    rando = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 10**8
    state = "%s-%s" % (customer.id, rando)
    args = {
        "client_id": os.environ.get("NOTION_CLIENT_ID"),
        "redirect_uri": BASE_PREFIX + "/notion/callback",
        "response_type": "code",
        "owner": "user",
        "state": state,
    }
    return urllib.parse.urlencode(args)


# Notion


@login_required
def notion_oauth(request):
    template = loader.get_template("oauth/notion.html")
    customer = request.user.customer
    if not customer:
        context = {"error": "Not a customer - contact support%s" % settings.BASE_DOMAIN}
        return HttpResponse(template.render(context, request))
    notion_query = get_notion_query(customer)
    return HttpResponse(template.render({"notion_query": notion_query}, request))


def notion_callback(request):
    context = {}
    try:
        # exchange code for access token
        code = request.GET.get("code")
        url = "https://api.notion.com/v1/oauth/token"
        data = {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": BASE_PREFIX + "/notion/callback",
        }
        headers = {"Content-Type": "application/json"}
        basic = HTTPBasicAuth(
            os.environ.get("NOTION_CLIENT_ID"), os.environ.get("NOTION_CLIENT_SECRET")
        )
        response = requests.post(url, json=data, headers=headers, auth=basic)
        response_data = response.json()
        if "error" in response_data:
            context["error"] = response_data.get("error_description", "Token error")
        elif "access_token" not in response_data:
            context["error"] = "No access token in response"
        else:
            context = parse_token_response(request, response_data, "notion")

    except Exception as ex:
        log("Exception in Notion callback", ex)
        context = {"error": ex}
    if request.session.get("config") == "true":
        return redirect("/config/integrations")
    template = loader.get_template("oauth/notion_callback.html")
    return HttpResponse(template.render(context, request))


# Jira / Confluence


def get_jira_query(customer):
    seed = os.environ.get("JIRA_CLIENT_SECRET") + customer.name
    rando = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 10**8
    state = "%s-%s" % (customer.id, rando)
    args = {
        "audience": "api.atlassian.com",
        "client_id": os.environ.get("JIRA_CLIENT_ID"),
        "scope": "read:jira-work read:jira-user read:confluence-space.summary read:confluence-content.all read:confluence-content.summary search:confluence read:confluence-user read:board-scope:jira-software read:epic:jira-software read:issue:jira-software read:sprint:jira-software read:dashboard:jira offline_access",
        "redirect_uri": BASE_PREFIX + "/jira/callback",
        "response_type": "code",
        "prompt": "consent",
        "state": state,
    }
    return urllib.parse.urlencode(args)


@login_required
def jira_oauth(request):
    template = loader.get_template("oauth/jira.html")
    customer = request.user.customer
    if not customer:
        context = {"error": "Not a customer - contact support%s" % settings.BASE_DOMAIN}
        return HttpResponse(template.render(context, request))
    jira_query = get_jira_query(customer)
    return HttpResponse(template.render({"jira_query": jira_query}, request))


def jira_callback(request):
    context = {}
    try:
        # exchange code for access token
        code = request.GET.get("code")
        url = "https://auth.atlassian.com/oauth/token"
        data = {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": BASE_PREFIX + "/jira/callback",
            "client_id": os.environ.get("JIRA_CLIENT_ID"),
            "client_secret": os.environ.get("JIRA_CLIENT_SECRET"),
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(url, json=data, headers=headers)
        response_data = response.json()
        if "error" in response_data:
            context["error"] = response_data.get("error_description", "Token error")
        elif "access_token" not in response_data:
            context["error"] = "No access token in response"
        else:
            context = parse_token_response(request, response_data, "jira")

    except Exception as ex:
        log("Exception in Jira callback", ex)
        context = {"error": ex}
    if request.session.get("config") == "true":
        return redirect("/config/integrations")
    template = loader.get_template("oauth/jira_callback.html")
    return HttpResponse(template.render(context, request))


# Slack


def get_slack_query(customer):
    seed = os.environ.get("SLACK_CLIENT_SECRET") + customer.name
    rando = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 10**8
    state = "%s-%s" % (customer.id, rando)
    args = {
        "client_id": os.environ.get("SLACK_CLIENT_ID"),
        "scope": "",
        "user_scope": "channels:history,channels:read,links:read,pins:read,users:read,search:read",
        "redirect_uri": BASE_PREFIX + "/slack/callback",
        "state": state,
    }
    return urllib.parse.urlencode(args)


@login_required
def slack_oauth(request):
    template = loader.get_template("oauth/slack.html")
    customer = request.user.customer
    if not customer:
        context = {"error": "Not a customer - contact support%s" % settings.BASE_DOMAIN}
        return HttpResponse(template.render(context, request))
    slack_query = get_slack_query(customer)
    return HttpResponse(template.render({"slack_query": slack_query}, request))


def slack_callback(request):
    context = {}
    try:
        # exchange code for access token
        code = request.GET.get("code")
        url = "https://slack.com/api/oauth.v2.access"
        data = {
            "code": code,
            "client_id": os.environ.get("SLACK_CLIENT_ID"),
            "client_secret": os.environ.get("SLACK_CLIENT_SECRET"),
            "redirect_uri": BASE_PREFIX + "/slack/callback",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(url, data=data, headers=headers)
        response_data = response.json()
        if "error" in response_data:
            context = {"error": response_data.get("error")}
        if not response_data.get("ok", False):
            error_message = response_data.get("error", "Unknown error occurred")
            context = {"error": f"Slack API error: {error_message}"}
        elif "access_token" not in response_data and "authed_user" not in response_data:
            context = {"error": "No access token in response"}
        else:
            if "authed_user" in response_data:
                response_data["access_token"] = response_data["authed_user"].pop(
                    "access_token"
                )
            context = parse_token_response(request, response_data, "slack")

    except Exception as ex:
        log("Exception in Slack callback:", ex)
        context = {"error": ex}
    if request.session.get("config") == "true":
        return redirect("/config/integrations")
    template = loader.get_template("oauth/slack_callback.html")
    return HttpResponse(template.render(context, request))


# Figma


def get_figma_query(customer):
    seed = os.environ.get("FIGMA_CLIENT_SECRET") + customer.name
    rando = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 10**8
    state = "%s-%s" % (customer.id, rando)
    args = {
        "client_id": os.environ.get("FIGMA_CLIENT_ID"),
        "scope": "files:read,file_variables:read,file_dev_resources:read",
        "redirect_uri": BASE_PREFIX + "/figma/callback",
        "response_type": "code",
        "state": state,
    }
    return urllib.parse.urlencode(args)


@login_required
def figma_oauth(request):
    template = loader.get_template("oauth/figma.html")
    customer = request.user.customer
    if not customer:
        context = {"error": "Not a customer - contact support%s" % settings.BASE_DOMAIN}
        return HttpResponse(template.render(context, request))
    figma_query = get_figma_query(customer)
    return HttpResponse(template.render({"figma_query": figma_query}, request))


def figma_callback(request):
    context = {}
    try:
        # exchange code for access token
        code = request.GET.get("code")
        url = "https://www.figma.com/api/oauth/token"
        data = {
            "code": code,
            "grant_type": "authorization_code",
            "client_id": os.environ.get("FIGMA_CLIENT_ID"),
            "client_secret": os.environ.get("FIGMA_CLIENT_SECRET"),
            "redirect_uri": BASE_PREFIX + "/figma/callback",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(url, data=data, headers=headers)
        response_data = response.json()
        if "error" in response_data:
            context = {"error": response_data.get("error")}
        elif "access_token" not in response_data:
            context = {"error": "No access token in response"}
        else:
            context = parse_token_response(request, response_data, "figma")

    except Exception as ex:
        log("Exception in Figma callback", ex)
        context = {"error": ex}
    if request.session.get("config") == "true":
        return redirect("/config/integrations")
    template = loader.get_template("oauth/figma_callback.html")
    return HttpResponse(template.render(context, request))


# Monday


def get_monday_query(customer):
    seed = os.environ.get("MONDAY_CLIENT_SECRET") + customer.name
    rando = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 10**8
    state = "%s-%s" % (customer.id, rando)
    scopes = "account:read assets:read boards:read docs:read tags:read teams:read users:read workspaces:read"
    args = {
        "client_id": os.environ.get("MONDAY_CLIENT_ID"),
        "redirect_uri": BASE_PREFIX + "/monday/callback",
        "scope": scopes,
        "state": state,
    }
    return urllib.parse.urlencode(args)


@login_required
def monday_oauth(request):
    # https://developer.monday.com/api-reference/docs/authentication
    template = loader.get_template("oauth/monday.html")
    customer = request.user.customer
    if not customer:
        context = {"error": "Not a customer - contact support%s" % settings.BASE_DOMAIN}
        return HttpResponse(template.render(context, request))
    monday_query = get_monday_query(customer)
    return HttpResponse(template.render({"monday_query": monday_query}, request))


def monday_callback(request):
    context = {}
    template = loader.get_template("oauth/monday_callback.html")
    if request.GET.get("error"):
        context = {"error": request.GET.get("error")}
        return HttpResponse(template.render(context, request))

    try:
        # exchange code for access token
        code = request.GET.get("code")
        url = "https://auth.monday.com/oauth2/token"
        data = {
            "client_id": os.environ.get("MONDAY_CLIENT_ID"),
            "client_secret": os.environ.get("MONDAY_CLIENT_SECRET"),
            "redirect_uri": BASE_PREFIX + "/monday/callback",
            "code": code,
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(url, json=data, headers=headers)
        response_data = response.json()
        if "error" in response_data:
            context = {"error": response_data.get("error")}
        elif "access_token" not in response_data:
            context = {"error": "No access token in response"}
        else:
            context = parse_token_response(request, response_data, "monday")

    except Exception as ex:
        log("Exception in Monday callback", ex)
        context = {"error": ex}
    if request.session.get("config") == "true":
        return redirect("/config/integrations")
    return HttpResponse(template.render(context, request))


# Harvest


def get_harvest_query(customer):
    seed = os.environ.get("HARVEST_CLIENT_SECRET") + customer.name
    rando = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 10**8
    state = "%s-%s" % (customer.id, rando)
    args = {
        "client_id": os.environ.get("HARVEST_CLIENT_ID"),
        "redirect_uri": BASE_PREFIX + "/harvest/callback",
        "response_type": "code",
        "state": state,
    }
    return urllib.parse.urlencode(args)


def harvest_callback(request):
    context = {"vendor": "harvest"}

    if "error" in request.GET:
        context["error"] = request.GET.get("error")
    else:
        try:
            # exchange code for access token
            code = request.GET.get("code")
            url = "https://id.getharvest.com/api/v2/oauth2/token"
            data = {
                "code": code,
                "client_id": os.environ.get("HARVEST_CLIENT_ID"),
                "client_secret": os.environ.get("HARVEST_CLIENT_SECRET"),
                "grant_type": "authorization_code",
            }
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=data, headers=headers)
            response_data = response.json()
            if "error" in response_data:
                context = {"error": response_data.get("error")}
            elif "access_token" not in response_data:
                context = {"error": "No access token in response"}
            else:
                response_data["scope"] = request.GET.get("scope")
                context = parse_token_response(request, response_data, "harvest")

        except Exception as ex:
            log("Exception in Harvest callback", ex)
            context = {"error": ex}

    if "error" in context:
        template = loader.get_template("oauth/error.html")
        return HttpResponse(template.render(context, request))
    else:
        return redirect("/config/integrations")


# Sentry


def get_sentry_query(customer):
    return "https://sentry.io/sentry-apps/[yamllms]/external-install/"


@login_required
def sentry_oauth(request):
    template = loader.get_template("oauth/sentry.html")
    customer = request.user.customer
    if not customer:
        context = {"error": "Not a customer - contact support%s" % settings.BASE_DOMAIN}
        return HttpResponse(template.render(context, request))
    sentry_query = get_sentry_query(customer)
    return HttpResponse(template.render({"sentry_query": sentry_query}, request))


def sentry_callback(request):
    context = {}
    template = loader.get_template("oauth/sentry_callback.html")
    if request.GET.get("error"):
        context = {"error": request.GET.get("error")}
        return HttpResponse(template.render(context, request))

    try:
        # exchange code for access token
        code = request.GET.get("code")
        install_id = request.GET.get("installationId")
        url = (
            "https://sentry.io/api/0/sentry-app-installations/%s/authorizations/"
            % install_id
        )
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": os.environ.get("SENTRY_CLIENT_ID"),
            "client_secret": os.environ.get("SENTRY_CLIENT_SECRET"),
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(url, json=data, headers=headers)
        response_data = response.json()
        response_data["install_id"] = install_id
        if "error" in response_data:
            context = {"error": response_data.get("error")}
        elif "access_token" not in response_data:
            context = {"error": "No access token in response"}
        else:
            context = parse_token_response(request, response_data, "sentry")

    except Exception as ex:
        log("Exception in Sentry callback", ex)
        context = {"error": ex}
    if request.session.get("config") == "true":
        return redirect("/config/integrations")
    return HttpResponse(template.render(context, request))


def sentry_webhook(request):
    expected = request.headers.get("sentry-hook-signature")
    if not expected:
        raise Exception("Unauthorized: missing signature")

    body = json.dumps(request.body)
    client_secret = os.environ.get("SENTRY_CLIENT_SECRET")

    digest = hmac.new(
        key=client_secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(digest, expected):
        raise Exception("Unauthorized: hmac mismatch")

    post = json.loads(request.body)
    install_id = post.get("installation")
    integration = Integration.objects.get(extras__install_id=install_id)
    webhooks = integration.extras.get("webhooks", [])
    webhooks.append(post)
    integration.extras["webhooks"] = webhooks
    integration.save()
    org = post.get("data", {}).get("installation", {}).get("organization")
    if org:
        integration.extras["organization"] = org
    if isinstance(org, dict) and "slug" in org:
        integration.extras["org_slug"] = org["slug"]
    return HttpResponse(status=204)
