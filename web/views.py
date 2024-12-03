import json, logging

from django.conf import settings
from django_ratelimit.decorators import ratelimit as django_ratelimit
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core import serializers
from django.db.models import CharField, TextField
from django.db.models.functions import Length, Lower
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template import loader
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse

import sesame.utils

from missions.hub import fulfil_mission, run_task
from missions.admin_jobs import get_random_repo
from missions.prompts import get_prompt_from_github
from missions.models import *
from missions.util import *

logger = logging.getLogger(__name__)
TextField.register_lookup(Length, "length")
CharField.register_lookup(Lower, "lower")


def conditional_ratelimit(key, rate):
    def decorator(view_func):
        if settings.DEBUG:
            return view_func
        return django_ratelimit(key=key, rate=rate)(view_func)

    return decorator


def get_user(request):
    # let staff view pages as user do
    if request.user.is_staff and "user" in request.GET:
        return User.objects.get(id=request.GET["user"])
    return request.user


def get_customer(request):
    # let staff view pages as customers do
    user = get_user(request)
    if user.is_staff and "customer" in request.GET:
        return Customer.objects.get(id=request.GET["customer"])
    if request.user.is_authenticated:
        email = user.email
        customer = user.customer
        if not customer and "@" in email:
            suffix = email.split("@")[-1]
            customer = Customer.objects.filter(email_suffix=suffix).first()
            if customer and customer.has_access(email):
                user.customer = customer
                user.save()
            else:
                customer = None
        return customer
    return None


def allow_access(request, customer):
    user = get_user(request)
    if user.is_staff or not customer:
        return True
    if user.is_authenticated and user.customer == customer:
        return customer.has_access(user.email)
    return False


def accessible_mission(request, mission):
    logger.debug(
        f"Checking accessibility for mission {mission.id}, visibility: {mission.visibility}"
    )

    if request.user.is_staff:
        logger.debug(
            f"User {request.user.id} is staff, granting access to mission {mission.id}"
        )
        return True

    if mission.visibility == Visibility.BLOCKED:
        logger.debug(
            f"Mission {mission.id} is BLOCKED, user {request.user.id} is not staff"
        )
        return False

    customer = mission.get_customer()
    logger.debug(f"Mission {mission.id} customer: {customer}")

    if request.user.is_authenticated:
        # For demo missions
        if mission.flags.get("user_created_by") == request.user.id:
            logger.debug(
                f"Mission {mission.id} created by user {request.user.id}, granting access"
            )
            return True

    if customer and customer.privacy == Customer.CustomerPrivacy.PRIVATE:
        # note that customer privacy trumps mission privacy, at least for now
        if mission.visibility == Visibility.RESTRICTED:
            # note "authorized" if any, lists emails who can access any non-public mission
            # whereas "restricted" limits access only to missions marked as restricted
            # we'll make this more sophisticated in the future
            allowlist = mission.flags.get("restricted_access", [])
            if not allowlist:
                allowlist = customer.extras.get("restricted_access", [])
            allowlist = [a + "@" + customer.email_suffix for a in allowlist]
            access_granted = request.user.email in allowlist and allow_access(
                request, customer
            )
            logger.debug(
                f"Mission {mission.id} is RESTRICTED, user {request.user.id} access granted: {access_granted}"
            )
            return access_granted
        access_granted = allow_access(request, customer)
        logger.debug(
            f"Mission {mission.id} has PRIVATE customer, user {request.user.id} access granted: {access_granted}"
        )
        return access_granted

    result = mission.visibility in [Visibility.PUBLIC, Visibility.ACCESSIBLE]
    logger.debug(
        f"Mission {mission.id} accessibility for user {request.user.id}: {result}"
    )
    return result


def index(request):
    template = loader.get_template("index.html")
    return HttpResponse(template.render())


@conditional_ratelimit(key="ip", rate="60/h")
def reports(request, page_length=40):
    mission_list = Mission.objects.filter(
        status__gte=Mission.MissionStatus.COMPLETE,
        mission_info__customer__isnull=True,
        visibility=Visibility.PUBLIC,
    ).order_by("-created_at")

    # uncomment the following to test large page counts locally
    # mission_list = list(mission_list) * 10

    paginator = Paginator(mission_list, page_length)  # Show 40 reports per page
    page = request.GET.get("page")

    try:
        missions = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        missions = paginator.page(1)
    except EmptyPage:
        # If page is out of range, deliver last page of results.
        missions = paginator.page(paginator.num_pages)

    for mission in missions:
        mission.week = mission.created_at.isocalendar()[1]
        mission.year = mission.created_at.year
        mission.month = mission.created_at.strftime("%B")
        mission.day = mission.created_at.day
        mission.name = (mission.name or "").replace(
            "GitHub Repo Analysis", "OSS Report"
        )

    # Limit the number of page links displayed
    max_displayed_pages = 10
    total_pages = paginator.num_pages

    # Ensure the current page is always included
    start_page = max(1, missions.number - (max_displayed_pages // 2))
    end_page = min(total_pages, start_page + max_displayed_pages - 1)

    # Adjust start_page if there are not enough pages before the current page
    if end_page - start_page < max_displayed_pages - 1:
        start_page = max(1, end_page - max_displayed_pages + 1)

    # Ensure that start_page is at least 1
    start_page = max(start_page, 1)

    # Ensure that end_page does not exceed total_pages
    end_page = min(end_page, total_pages)

    # Create a list of page numbers to pass to the template
    page_numbers = list(range(start_page, end_page + 1))

    context = {
        "mission_list": missions,
        "start_page": start_page,
        "end_page": end_page,
        "total_pages": total_pages,
        "page_numbers": page_numbers,
    }
    template = loader.get_template("reports.html")
    return HttpResponse(template.render(context, request))


@conditional_ratelimit(key="ip", rate="60/h")
def report(request, mission_id):
    user = get_user(request)
    if mission_id > 2147483648:
        return HttpResponse("Invalid mission ID", status=400)

    mission = (
        Mission.objects.filter(id=mission_id)
        .select_related("mission_info")
        .prefetch_related("task_set")
        .first()
    )

    if not mission:
        template = loader.get_template("no_report.html")
        return HttpResponse(template.render({id: mission_id}, request))

    if not accessible_mission(request, mission):
        request.session["requested_id"] = mission_id
        return redirect("/login")

    if mission.status != Mission.MissionStatus.COMPLETE and not user.is_staff:
        return redirect("/running/%s" % mission_id)

    customer = mission.get_customer()
    project = mission.mission_info.project if mission.mission_info else None

    sub_reports = mission.sub_reports()

    # gotta show the mission on a per-user basis if there are restricted subreports
    if mission.restricted_tasks().exists() and not user.is_staff:
        restricted_task_ids = [m.id for m in mission.restricted_tasks().only("id")]
        allowlist = mission.flags.get("restricted_access", [])
        if customer and not allowlist:
            allowlist = customer.extras.get("restricted_access", [])
            allowlist = [a + "@" + customer.email_suffix for a in allowlist]

        # OK, filter 'em out
        email = user.email if user.is_authenticated else None
        if not email or email not in allowlist:
            sub_reports = [s for s in sub_reports if s.id not in restricted_task_ids]

    followup = user.is_staff or (user.is_authenticated and user.customer == customer)
    followup = followup and not mission.is_report_on_reports()
    context = {
        "mission": mission,
        "sub_reports": sub_reports,
        "followup_ok": followup,
        "project": project,
        "skip_sources": mission.is_report_on_reports(),
    }
    template = loader.get_template("report.html")
    return HttpResponse(template.render(context, request))


def running_latest(request):
    mission = Mission.objects.all().order_by("-id").first()
    if not mission:
        return HttpResponse("No missions found", status=404)
    return running(request, mission.id)


def running(request, mission_id):
    template = loader.get_template("running.html")
    mission = Mission.objects.get(id=mission_id)
    customer = mission.get_customer()
    if not allow_access(request, customer):
        return redirect("index")
    context = {
        "mission": Mission.objects.get(id=mission_id),
    }
    return HttpResponse(template.render(context, request))


def login(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    sent = False
    error = None
    if request.method == "POST":
        try:
            email = request.POST.get("email")
            send_login_email(email, request)
            sent = True
        except Exception as ex:
            log("Login exception", ex)
            sent = False
            error = ex
    template = loader.get_template("login.html")
    return HttpResponse(template.render({"sent": sent, "error": error}, request))


def logout_view(request):
    logout(request)
    return redirect("index")


def send_login_email(email, request):
    if not "@" in email:  # TODO better validation
        raise Exception("Invalid email")
    user = User.objects.filter(email=email).first()
    if not user:
        user = User.objects.create(email=email, username=email)
    link = reverse("sesame-login")
    link = request.build_absolute_uri(link)
    link += sesame.utils.get_query_string(user)
    if settings.DEBUG:
        log("Login link", link)
    email = EmailMultiAlternatives(
        from_email=settings.DEFAULT_FROM_EMAIL,
        reply_to=[settings.REPLY_TO_EMAIL],
        to=[user.email],
        subject="Log into YamLLMs",
        body=LOGIN_EMAIL % link,
    )
    email.send(fail_silently=settings.DEBUG)
    log("Sent login email to", user.email)


@login_required
def followup(request, mission_id):
    mission = Mission.objects.get(id=mission_id)
    task = None
    task_id = request.GET.get("task_id")
    if task_id:
        task = Task.objects.filter(id=task_id).first()
        if task and task.mission != mission:
            raise Exception("Task does not belong to mission")
    if not allow_access(request, mission.get_customer()):
        return redirect("index")
    context = {
        "mission": mission,
        "task": task,
        "active": False,
        "thisPage": "followUp",
    }
    template = loader.get_template("followup.html")
    return HttpResponse(template.render(context, request))


@login_required
def ask_followup(request):
    mission = Mission.objects.get(id=request.POST.get("mission_id"))
    if not allow_access(request, mission.get_customer()):
        return redirect("index")
    if request.method == "POST":
        task = Task.objects.create(
            mission=mission,
            name="Followup Question",
            category=TaskCategory.LLM_QUESTION,
            parent=mission.task_set.filter(
                category=TaskCategory.FINALIZE_MISSION
            ).last(),
            prompt=request.POST.get("question"),
            extras={"followup_question": request.POST.get("question")},
        )
        run_task.delay(task.id)
        # temporary while beta-ing followup tasks
        email_ops(
            subject="[YamLLMs] Followup question: %s" % mission,
            body=f"(Temporary email while beta-ing followup questions.) \n\n {BASE_PREFIX}/staff/task/{task.id}",
        )
        return redirect("/followup/%s?task_id=%s" % (mission.id, task.id))


def handle_web_exception(request, retry, ex, error):
    template = loader.get_template("error.html")
    context = {"ex": ex, "error": error, "retry": retry}
    return HttpResponse(template.render(context, request))


# API pages


def run_report(request):
    if not request.user.is_staff:
        return redirect("index")
    customer = request.user.customer
    mission_info = customer.missioninfo_set.first()
    mission = mission_info.create_mission()
    mission.flags["email_to"] = [request.user.email]
    mission.save()
    fulfil_mission.delay(mission.id)
    redirect("/running/%s" % mission.id)


# TODO replace with real API eg Django REST Framework
def mission_json(request, mission_id):
    mission = Mission.objects.get(id=mission_id)
    if not accessible_mission(request, mission):
        return HttpResponse("Unauthorized", status=401)
    data = serializers.serialize("json", [mission])
    return HttpResponse(data, content_type="application/json")


def mission_status_json(request, mission_id):
    mission = Mission.objects.get(id=mission_id)
    if not accessible_mission(request, mission):
        return JsonResponse({"error": "Unauthorized"}, status=401)
    status = mission.status
    return JsonResponse(
        {
            "id": mission.id,
            "status": status,
            "status_display": Mission.MissionStatus(status).label,
        }
    )


def tasks_json(request, mission_id):
    mission = Mission.objects.get(id=mission_id)
    if not accessible_mission(request, mission):
        # Add this check for demo missions
        if mission.flags.get("user_created_by") != request.user.id:
            return HttpResponse("Unauthorized", status=401)

    tasks = mission.task_set.all().values(
        "id",
        "name",
        "status",
        "category",
        "parent_id",
        "mission_id",
        "task_info_id",
        "response",
    )
    tasks = list(tasks)
    post = [t for t in tasks if t["category"] > TaskCategory.FINALIZE_MISSION]
    pre = [t for t in tasks if t["category"] <= TaskCategory.FINALIZE_MISSION]
    tasks = pre + post
    for task in tasks:
        task["response"] = (task["response"] or "")[:8192]
    data = json.dumps(tasks)
    return HttpResponse(data, content_type="application/json")


def lucky_json(request):
    selected = get_random_repo().split("/")
    data = json.dumps({"org": selected[0], "repo": selected[1]})
    return HttpResponse(data, content_type="application/json")


def create_task(request):
    if not request.method == "POST":
        raise Exception("Invalid request")
    post = request.POST
    api_key = post.get("api_key")
    if not api_key in settings.API_KEYS:
        return HttpResponse("Unauthorized", status=401)
    mission_id = post.get("mission_id")
    mission = Mission.objects.filter(id=mission_id).first()
    if not mission:
        return HttpResponse("Mission not found", status=404)
    task = Task.objects.create(
        mission_id=mission.id,
        name=post.get("name"),
        parent_id=post.get("parent_id"),
        url=post.get("url"),
        category=post.get("category"),
        reporting=post.get("reporting"),
        prompt=post.get("prompt"),
        response=post.get("data"),
        llm=post.get("llm"),
        structured_data=post.get("structured_data") or {},
        depends_on_urls=post.get("depends_on_urls") or [],
        visibility=post.get("visibility") or 0,
        order=post.get("order") or 0,
        flags=post.get("flags") or {},
    )
    prompt = post.get("prompt")
    if prompt and prompt.strip() and len(prompt.strip().split(" ")) == 0:
        task.prompt = get_prompt_from_github(prompt)
        task.save()
    if task.flags.get("prompt_template"):
        task.prompt = get_prompt_from_github(task.flags["prompt_template"])
        task.save()
    if post.get("run"):
        run_task(task.id) if task.is_test() else run_task.delay(task.id)
    response = {"status": "success", "task_id": task.id}
    return JsonResponse(response)
