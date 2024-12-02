from django.contrib import admin, auth
from django.http import HttpResponseRedirect
from .models import *
from .hub import fulfil_mission, run_task


class YamLLMsAdminSite(admin.AdminSite):
    site_header = "YamLLMs administration"
    site_title = "YamLLMs site admin"


admin_site = YamLLMsAdminSite(name="yamllms_admin")


class UserAdmin(auth.admin.UserAdmin):
    readonly_fields = ["last_login", "date_joined"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Profile info", {"fields": ("extras", "customer")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )

    list_display = (
        "email",
        "customer",
        "is_staff",
    )
    search_fields = ("email", "first_name", "last_name", "customer__name")
    ordering = ("-created_at",)


class TaskInfoAdmin(admin.ModelAdmin):
    fg1 = ["name", "mission_info", "category", "base_url", "parent"]
    fg2 = ["reporting", "visibility", "order", "base_llm", "flags", "depends_on_urls"]
    fg3 = ["base_prompt", "extras", "description", "created_at", "edited_at"]
    fields = fg1 + fg2 + fg3
    list_display = ["id", "name", "created_at", "visibility", "mission_info"]
    search_fields = ("name", "category", "mission_info__name")
    readonly_fields = ["created_at", "edited_at"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent":
            parent_id = request.resolver_match.kwargs.get("object_id")
            ti = TaskInfo.objects.filter(id=parent_id).first()
            if ti and ti.mission_info:
                if ti.mission_info.depends_on:
                    ids = [ti.mission_info.id, ti.mission_info.depends_on.id]
                    kwargs["queryset"] = TaskInfo.objects.filter(
                        mission_info_id__in=ids
                    )
                else:
                    kwargs["queryset"] = ti.mission_info.taskinfo_set.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_ordering(self, request):
        return ["-id"]


class TaskInfoInline(admin.TabularInline):
    model = TaskInfo
    fields = ["name", "category", "parent", "base_url", "order", "reporting"]
    readonly_fields = ["name", "category", "parent", "base_url", "order", "reporting"]
    show_change_link = True
    extra = 0

    def has_add_permission(self, request, obj) -> bool:
        return False

    def has_delete_permission(self, request, obj) -> bool:
        return False


class TaskAdmin(admin.ModelAdmin):
    fg1 = ["name", "status", "mission", "category", "url", "parent", "task_info"]
    fg2 = ["flags", "depends_on_urls", "reporting", "visibility", "order", "llm"]
    fg3 = ["extras", "structured_data", "prompt", "response", "rendered"]
    fg4 = ["created_at", "completed_at", "edited_at"]
    fields = fg1 + fg2 + fg3 + fg4
    change_form_template = "admin/rerun_task_form.html"
    list_per_page = 50
    list_select_related = True
    list_display = ["id", "name", "status", "created_at", "mission", "task_info"]
    search_fields = ["name", "status", "llm", "url", "mission__name", "task_info__name"]
    raw_id_fields = ["mission", "parent"]
    readonly_fields = ["completed_at", "created_at", "edited_at"]

    def get_ordering(self, request):
        return ["-id"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent":
            parent_id = request.resolver_match.kwargs.get("object_id")
            task = Task.objects.filter(id=parent_id).first()
            if task and task.mission:
                if task.mission.depends_on:
                    mission_ids = [task.mission.id, task.mission.depends_on.id]
                    kwargs["queryset"] = Task.objects.filter(mission_id__in=mission_ids)
                else:
                    kwargs["queryset"] = task.mission.task_set.all()
        if db_field.name == "task_info":
            parent_id = request.resolver_match.kwargs.get("object_id")
            task = Task.objects.filter(id=parent_id).first()
            if task and task.mission and task.mission.mission_info:
                kwargs["queryset"] = task.mission.mission_info.taskinfo_set.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def response_change(self, request, obj):
        if "_rerun_task" in request.POST:
            task = Task.objects.get(id=obj.id)
            task.prep_for_rerun()
            run_task.delay(task.id)
            return HttpResponseRedirect("/running/%s" % obj.mission_id)

        if "_rerender_task" in request.POST:
            task = Task.objects.get(id=obj.id)
            task.rendered = ""
            task.render()
            return HttpResponseRedirect("/staff/task/%s" % obj.id)

        if "_view_task" in request.POST:
            return HttpResponseRedirect("/staff/task/%s" % obj.id)

        return super().response_change(request, obj)


class TaskInline(admin.TabularInline):
    model = Task
    fields = ["name", "category", "parent", "url", "order", "reporting"]
    readonly_fields = ["name", "category", "parent", "url", "order", "reporting"]
    show_change_link = True
    extra = 0

    def has_add_permission(self, request, obj) -> bool:
        return False

    def has_delete_permission(self, request, obj) -> bool:
        return False


class MissionAdmin(admin.ModelAdmin):
    fg1 = ["name", "status", "mission_info", "visibility", "depends_on", "previous"]
    fg2 = ["llm", "flags", "prompt", "response", "rendered"]
    fg3 = ["extras", "created_at", "edited_at"]
    fields = fg1 + fg2 + fg3
    change_form_template = "admin/rerun_mission_form.html"
    inlines = [TaskInline]
    list_per_page = 50
    list_select_related = True
    list_display = ["id", "name", "status", "visibility", "created_at", "mission_info"]
    search_fields = ("name", "status", "llm", "mission_info__name")
    raw_id_fields = ["depends_on", "previous"]
    readonly_fields = ["created_at", "edited_at"]

    def get_ordering(self, request):
        return ["-id"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "previous":
            parent_id = request.resolver_match.kwargs.get("object_id")
            mission = Mission.objects.filter(id=parent_id).first()
            if mission and mission.mission_info:
                kwargs["queryset"] = mission.mission_info.mission_set.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def response_change(self, request, obj):
        if "_rerun_mission" in request.POST:
            fulfil_mission.delay(obj.id)
            return HttpResponseRedirect("/running/%s" % obj.id)

        if "_rerun_mission" in request.POST:
            mission = Mission.objects.get(id=obj.id)
            mission.rendered = ""
            mission.render()
            return HttpResponseRedirect("/reports/%s" % obj.id)

        if "_view_status" in request.POST:
            return HttpResponseRedirect("/running/%s" % obj.id)

        if "_view_report" in request.POST:
            return HttpResponseRedirect("/reports/%s" % obj.id)

        if "_view_mission" in request.POST:
            return HttpResponseRedirect("/staff/mission/%s" % obj.id)

        if "_copy_mission" in request.POST:
            return HttpResponseRedirect("/staff/duplicate/%s" % obj.id)

        return super().response_change(request, obj)


class MissionInline(admin.TabularInline):
    model = Mission
    fields = ["name", "created_at", "status", "visibility", "previous"]
    readonly_fields = ["name", "created_at", "status", "visibility", "previous"]
    ordering = ["-id"]
    show_change_link = True
    verbose_name = "(Last 30 Days) Mission"
    extra = 0

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(created_at__gte=timezone.now() - timedelta(days=30))

    def has_add_permission(self, request, obj) -> bool:
        return False

    def has_delete_permission(self, request, obj) -> bool:
        return False


class MissionInfoAdmin(admin.ModelAdmin):
    fg1 = ["name", "customer", "project", "visibility", "depends_on", "cadence"]
    fg2 = ["run_at", "base_llm", "flags", "base_prompt"]
    fg3 = ["extras", "description", "created_at", "edited_at"]
    fields = fg1 + fg2 + fg3
    change_form_template = "admin/run_mission_form.html"
    inlines = [TaskInfoInline, MissionInline]
    list_display = ["id", "name", "customer", "project", "visibility", "run_at"]
    search_fields = ("name", "customer__name", "project__name")
    readonly_fields = ["created_at", "edited_at"]

    def get_ordering(self, request):
        return ["-id"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "project":
            parent_id = request.resolver_match.kwargs.get("object_id")
            mi = MissionInfo.objects.filter(id=parent_id).first()
            if mi and mi.customer:
                kwargs["queryset"] = mi.customer.project_set.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def run_mission(self, mission_info):
        mission = mission_info.create_mission()
        mission.save()

        fulfil_mission.delay(mission.id)
        return mission.id

    def response_change(self, request, obj):
        if "_run_mission" in request.POST:
            mission_id = self.run_mission(obj)
            return HttpResponseRedirect("/running/%s" % mission_id)

        if "_view_mission_info" in request.POST:
            return HttpResponseRedirect("/staff/mission_info/%s" % obj.id)

        return super().response_change(request, obj)


class MissionInfoInline(admin.TabularInline):
    model = MissionInfo
    fields = ["name", "created_at", "project", "visibility"]
    readonly_fields = ["name", "created_at", "project", "visibility"]
    show_change_link = True
    extra = 0

    def has_add_permission(self, request, obj) -> bool:
        return False

    def has_delete_permission(self, request, obj) -> bool:
        return False


class IntegrationKeysInline(admin.TabularInline):
    model = Secret
    fields = ["name", "vendor", "created_at"]
    readonly_fields = ["name", "vendor", "created_at"]

    def has_add_permission(self, request, obj) -> bool:
        return False

    def has_delete_permission(self, request, obj) -> bool:
        return False


class IntegrationAdmin(admin.ModelAdmin):
    list_display = ["id", "vendor", "created_at", "customer", "project"]
    search_fields = ("name", "vendor", "customer__name", "project__name")
    inlines = [IntegrationKeysInline]


class IntegrationsInline(admin.TabularInline):
    model = Integration
    fields = ["name", "vendor", "created_at"]
    readonly_fields = ["name", "vendor", "created_at"]
    show_change_link = True

    def has_add_permission(self, request, obj) -> bool:
        return False

    def has_delete_permission(self, request, obj) -> bool:
        return False


class CustomerAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "created_at", "status", "privacy"]
    inlines = [MissionInfoInline, IntegrationsInline]


class ProjectAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "created_at", "customer", "status"]
    search_fields = ("name", "customer__name")
    inlines = [IntegrationsInline, MissionInfoInline]


class MissionEvaluationAdmin(admin.ModelAdmin):
    pass


class RawDataAdmin(admin.ModelAdmin):
    change_form_template = "admin/raw_data_form.html"

    def response_change(self, request, obj):
        if "_view_data" in request.POST:
            return HttpResponseRedirect("/staff/raw_data/%s" % obj.id)
        return super().response_change(request, obj)


admin_site.register(MissionInfo, MissionInfoAdmin)
admin_site.register(TaskInfo, TaskInfoAdmin)
admin_site.register(Mission, MissionAdmin)
admin_site.register(Task, TaskAdmin)
admin_site.register(Customer, CustomerAdmin)
admin_site.register(Project, ProjectAdmin)
admin_site.register(User, UserAdmin)
admin_site.register(Integration, IntegrationAdmin)
admin_site.register(MissionEvaluation, MissionEvaluationAdmin)
admin_site.register(RawData, RawDataAdmin)
