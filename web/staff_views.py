from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template import loader

from missions.models import *
from missions.admin_jobs import email_mission
from missions.plugins.figma import get_figma_projects
from missions.plugins.jira import get_jira_projects


def email_report(request):
    if not request.user.is_staff:
        return redirect("index")
    if request.method == "POST":
        email = request.POST.get("email")
        mission_id = request.POST.get("mission_id")
        email_mission(mission_id, email)
    context = {"mission_id": mission_id, "email": email}
    template = loader.get_template("staff/email_report.html")
    return HttpResponse(template.render(context, request))


def missions(request):
    if not request.user.is_staff:
        return redirect("index")
    template = loader.get_template("staff/missions.html")
    n = request.GET.get("n", 40)
    missions = Mission.objects.all().order_by("-id")[:n]
    context = {"missions": missions}
    return HttpResponse(template.render(context, request))


def mission(request, mission_id):
    if not request.user.is_staff:
        return redirect("index")
    template = loader.get_template("staff/mission.html")
    context = {"mission": Mission.objects.get(id=mission_id)}
    return HttpResponse(template.render(context, request))


def task(request, task_id):
    if not request.user.is_staff and not settings.DEBUG:
        return redirect("index")
    task = Task.objects.get(id=task_id)

    prereqs = " | ".join(["%s" % t for t in task.prerequisite_tasks()])
    context = {"task": task, "prereqs": prereqs}
    template = loader.get_template("staff/task.html")
    return HttpResponse(template.render(context, request))


def raw_data(request, raw_data_id):
    if not request.user.is_staff:
        return redirect("index")
    raw_data = RawData.objects.filter(id=raw_data_id).first()
    context = {"raw_data": raw_data}
    template = loader.get_template("staff/raw_data.html")
    return HttpResponse(template.render(context, request))


def customers(request):
    if not request.user.is_staff:
        return redirect("index")
    template = loader.get_template("staff/customers.html")
    generic = MissionInfo.objects.filter(customer__isnull=True)
    base = [m for m in generic if m.name.startswith("Base")]
    generic = [m for m in generic if not m.name.startswith("Base")]
    context = {
        "customers": Customer.objects.all(),
        "generic": generic,
        "base": base,
    }
    return HttpResponse(template.render(context, request))


def customer(request, customer_id):
    if not request.user.is_staff:
        return redirect("index")
    context = {"customer": Customer.objects.get(id=customer_id)}
    template = loader.get_template("staff/customer.html")
    return HttpResponse(template.render(context, request))


def customer_integrations(request, customer_id, vendor):
    if not request.user.is_staff:
        return redirect("index")
    customer = Customer.objects.get(id=customer_id)
    integrations = list(customer.integration_set.filter(vendor=vendor))
    for integration in integrations:
        if integration.vendor == "figma":
            integration.details = get_figma_projects(integration)
        if integration.vendor == "jira":
            integration.details = get_jira_projects(integration)
    context = {"customer": customer, "vendor": vendor, "integrations": integrations}
    template = loader.get_template("staff/customer_integrations.html")
    return HttpResponse(template.render(context, request))


def mission_info(request, id):
    if not request.user.is_staff:
        return redirect("index")
    template = loader.get_template("staff/mission_info.html")
    context = {"mission_info": MissionInfo.objects.get(id=id)}
    return HttpResponse(template.render(context, request))


def cache_bust(request):
    if not request.user.is_staff:
        return redirect("index")
    cache.clear()
    return HttpResponse("Cache busted")


def handle_web_exception(request, retry, ex, error):
    template = loader.get_template("error.html")
    context = {"ex": ex, "error": error, "retry": retry}
    return HttpResponse(template.render(context, request))
