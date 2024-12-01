import json
from django.db import models
from django.core import serializers
from django.contrib.auth.models import AbstractUser
from encrypted_model_fields.fields import EncryptedCharField
from ..util import *


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(auto_now=True)
    extras = models.JSONField(default=dict, blank=True)
    name = models.CharField(max_length=256)

    def __str__(self):
        return f"({self.id}) {self.name}"

    def pretty_extras(self):
        return json.dumps(self.extras, indent=2)

    class Meta:
        abstract = True
        ordering = [
            "id",
        ]

    def to_yaml(self):
        queryset = self._meta.model.objects.filter(pk=self.pk)
        return serializers.serialize("yaml", queryset)


class Visibility(models.IntegerChoices):
    BLOCKED = -1, "Blocked"  # only visible to staff
    PUBLIC = 0, "Public"  # anyone can see
    PRIVATE = 1, "Private"  # only users associated with that customer
    ACCESSIBLE = 2, "Accessible"  # viewable, but not shown on dashboard
    RESTRICTED = 3, "Restricted"  # only some users at that customer


class Reporting(models.IntegerChoices):
    NO_REPORT = 0, "No Report Needed"
    KEY_CONTEXT = 1, "Key Context For All Reports"
    ALWAYS_REPORT = 2, "Generate Report"


class TaskCategory(models.IntegerChoices):
    OTHER = 0, "Other"
    SCRAPE = 1, "Scrape"
    API = 2, "API"
    FILTER = 3, "Filter Previous Fetch Tasks"
    FETCH_FOR_LLM = 10, "Fetch For LLM"
    LLM_DECISION = 11, "LLM Decision"
    LLM_REPORT = 12, "LLM Report"
    LLM_QUESTION = 13, "LLM Question"
    LLM_EVALUATION = 14, "LLM Evaluation"
    LLM_RATING = 15, "LLM Rating"
    AGGREGATE_TASKS = 20, "Aggregate Previous Tasks"
    AGGREGATE_REPORTS = 21, "Aggregate Reports"
    AGENT_TASK = 30, "Agent Task"
    QUANTIFIED_REPORT = 40, "Quantified Report"
    FINALIZE_MISSION = 100, "Finalize Mission"
    POST_MISSION = 1000, "Post Report"


class TaskStatus(models.IntegerChoices):
    CREATED = 0, "Created"
    FAILED = -1, "Fetch Failed"
    EMPTY = -2, "No Data"
    REJECTED = -3, "Rejected"
    HIDDEN = -4, "Hidden"
    IN_PROCESS = 1, "In Process"
    COMPLETE = 2, "Complete"


class Customer(BaseModel):
    class CustomerStatus(models.IntegerChoices):
        ACTIVE = 0, "Active"
        INACTIVE = -1, "Inactive"

    class CustomerPrivacy(models.IntegerChoices):
        PUBLIC = 0, "Public Reports"
        PRIVATE = 1, "Private Reports"

    status = models.IntegerField(
        choices=CustomerStatus.choices, default=CustomerStatus.ACTIVE
    )
    privacy = models.IntegerField(
        choices=CustomerPrivacy.choices, default=CustomerPrivacy.PRIVATE
    )
    git_handle = models.CharField(max_length=256, null=True, blank=True)
    email_suffix = models.CharField(max_length=256, null=True, blank=True)
    authorized = models.JSONField(default=dict, blank=True, null=True)
    stripe_info = models.JSONField(default=dict, blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=256, null=True, blank=True)
    # currently just stores the most recently created subscription
    stripe_subscription_id = models.CharField(max_length=256, null=True, blank=True)

    def full_name(self):
        return self.name if self.name else self.git_handle

    def has_access(self, email):
        if self.authorized and email not in self.authorized.get("emails", []):
            log("Access denied to", email)
            return False
        if self.email_suffix and not email.endswith(self.email_suffix):
            log("Access denied to", email)
            return False
        log("Allowing access to", email)
        return True

    def active_projects(self):
        return self.project_set.filter(status=Customer.CustomerStatus.ACTIVE).order_by(
            "name"
        )

    def default_project(self):
        default = self.project_set.filter(name__startswith="Default").first()
        if not default:
            default = self.project_set.first()
        if not default:
            name = "Default: %s" % self.name
            default = Project.objects.create(name=name, customer=self)
        return default

    def get_integration(self, vendor):
        return (
            self.integration_set.filter(vendor=vendor)
            .filter(project__isnull=True)
            .last()
        )

    # Integrations only for this customer, not for a specific project
    def generic_integrations(self):
        return self.integration_set.filter(project__isnull=True)

    def subscription_status(self):
        if self.stripe_customer_id == "custom":
            return "custom"

        if any(project.has_active_subscription() for project in self.active_projects()):
            return "stripe"

        return None


class Project(BaseModel):
    status = models.IntegerField(
        choices=Customer.CustomerStatus.choices, default=Customer.CustomerStatus.ACTIVE
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, null=True, blank=True
    )
    stripe_subscription_id = models.CharField(max_length=256, null=True, blank=True)

    def is_default(self):
        return self.name == "Default Project" or self.customer.project_set.count() == 1

    def has_active_subscription(self):
        # TODO check that it's active
        return self.stripe_subscription_id is not None

    def get_integration(self, vendor):
        return self.integration_set.filter(vendor=vendor).last()

    def latest_mission_info(self):
        return self.missioninfo_set.order_by("-created_at").first()


class User(BaseModel, AbstractUser):
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return self.email if self.email else self.name

    def active_project_id(self):
        return self.extras.get("active_project")

    def active_project(self):
        if self.active_project_id():
            return Project.objects.filter(id=self.active_project_id()).first()
        return None

    def set_active_project(self, project_id):
        if self.extras.get("active_project") != project_id:
            self.extras["active_project"] = project_id
            self.save()

    def clear_active_project(self):
        if "active_project" in self.extras:
            self.extras.pop("active_project", "")
            self.save()

    def dashboard_link(self):
        project_id = self.active_project_id()
        return f"/project/{project_id}" if project_id else "/dashboard"


class Integration(BaseModel):
    vendor = models.CharField(max_length=64, null=True, blank=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, null=True, blank=True
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, blank=True
    )

    def __str__(self):
        return f"({self.id}) {self.vendor}"

    def metadata_only(self):
        return self.extras.get("metadata_only") == "true"


# Values encrypted at rest and not available in admin.
# Can belong to only a customer, or to a customer and a project
class Secret(BaseModel):
    class Meta:
        verbose_name = "Integration Key"

    vendor = models.CharField(max_length=64, null=True, blank=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, null=True, blank=True
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, blank=True
    )
    integration = models.ForeignKey(
        Integration, on_delete=models.CASCADE, null=True, blank=True
    )
    value = EncryptedCharField(max_length=128)
    refresh = EncryptedCharField(max_length=128, null=True, blank=True)
