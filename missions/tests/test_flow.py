from django.test import TestCase
from django.test.client import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.auth.models import AnonymousUser

from ..models import *
from ..hub import fulfil_mission
from ..util import TEST_MODEL, email_ops
from web.views import get_customer, allow_access, accessible_mission


class DependencyFlowTest(TestCase):
    def setUp(self):
        customer = Customer.objects.create(
            name="TDTest customer",
            email_suffix="example.com",
        )
        mission_info = MissionInfo.objects.create(
            name="TDTest mission info",
            base_llm=TEST_MODEL,
            base_prompt="This is a test prompt",
            flags={"run_evals": "true"},
        )
        first = TaskInfo.objects.create(
            mission_info=mission_info,
            name="TDTest fetch task 1",
            base_url="https://github.com/test/repo/readme",
            base_llm=TEST_MODEL,
            category=TaskCategory.API,
        )
        second = TaskInfo.objects.create(
            mission_info=mission_info,
            parent=first,
            name="TDTest fetch task 2",
            base_url="https://github.com/test/repo/commits",
            base_llm=TEST_MODEL,
            base_prompt="TDTest prompt",
            category=TaskCategory.API,
            reporting=Reporting.ALWAYS_REPORT,
        )
        mission = mission_info.create_mission()
        self.mission_id = mission.id
        self.customer = customer

    def test_response_aggregation(self):
        fulfil_mission(self.mission_id)
        mission = Mission.objects.get(id=self.mission_id)
        tasks = mission.task_set.all()
        f1 = tasks.filter(name="TDTest fetch task 1").first()
        f2 = tasks.filter(name="TDTest fetch task 2").first()
        r = tasks.filter(category=TaskCategory.LLM_REPORT).first()
        self.assertTrue(len(f1.response) > 0)
        self.assertTrue(len(f2.response) > 0)
        assembled = r.assemble_prerequisite_inputs()
        self.assertTrue(f1.response in assembled)
        self.assertTrue(f2.response in assembled)

    def test_login_auth(self):
        self.assertTrue(self.customer.has_access("test@example.com"))
        self.assertFalse(self.customer.has_access("test@example2.com"))
        request = RequestFactory().get("/hello/")
        request.user = User.objects.create_user("test", "test@example.com")
        self.assertTrue(get_customer(request) == self.customer)
        self.assertTrue(allow_access(request, self.customer))
        request.user = User.objects.create_user("test2", "test@example2.com")
        self.assertTrue(get_customer(request) == None)
        self.assertFalse(allow_access(request, self.customer))


class ReportAccessTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name="TDTest Customer", email_suffix="example.com"
        )
        self.mission_info = MissionInfo.objects.create(
            customer=self.customer,
            name="TDTest mission info",
            base_llm=TEST_MODEL,
            base_prompt="This is a test prompt",
        )
        self.mission = self.mission_info.create_mission()
        self.mission.status = Mission.MissionStatus.COMPLETE
        self.mission.save()
        Task.objects.create(
            mission=self.mission,
            name="TDTest task",
            category=TaskCategory.LLM_REPORT,
            status=TaskStatus.COMPLETE,
        )
        Task.objects.create(
            mission=self.mission,
            name="TDTest task",
            category=TaskCategory.LLM_REPORT,
            status=TaskStatus.COMPLETE,
            visibility=Visibility.RESTRICTED,
        )

        self.user = User.objects.create_user("TDTestUser", "test@example.com")

    def test_report_access(self):
        self.assertTrue(self.customer.privacy == Customer.CustomerPrivacy.PRIVATE)
        self.assertTrue(self.mission.visibility == Visibility.PRIVATE)
        self.assertTrue(len(self.mission.sub_reports()) == 2)
        request = RequestFactory().get("/report/%s" % self.mission.id)
        middleware = SessionMiddleware(lambda x: None)
        middleware.process_request(request)
        request.session.save()
        request.user = AnonymousUser()
        self.assertFalse(accessible_mission(request, self.mission))
        request.user = self.user
        self.assertFalse(accessible_mission(request, self.mission))
        self.customer.privacy = Customer.CustomerPrivacy.PUBLIC
        self.customer.save()
        self.assertFalse(accessible_mission(request, self.mission))
        self.mission.visibility = Visibility.PUBLIC
        self.mission.save()
        self.assertTrue(accessible_mission(request, self.mission))
        self.customer.privacy = Customer.CustomerPrivacy.PRIVATE
        self.customer.save()
        self.assertFalse(accessible_mission(request, self.mission))
        self.customer.privacy = Customer.CustomerPrivacy.PUBLIC
        self.customer.save()
        self.assertTrue(accessible_mission(request, self.mission))
        self.mission.visibility = Visibility.BLOCKED
        self.mission.save()
        self.assertFalse(accessible_mission(request, self.mission))

        # now test user and customer match, with restricted access
        self.user.customer = self.customer
        self.user.save()
        self.mission.visibility = Visibility.RESTRICTED
        self.mission.flags["restricted_access"] = ["test"]
        self.mission.save()
        self.assertFalse(accessible_mission(request, self.mission))
        self.customer.privacy = Customer.CustomerPrivacy.PRIVATE
        self.customer.save()
        self.assertTrue(accessible_mission(request, self.mission))
        self.mission.flags["restricted_access"] = ["test2"]
        self.mission.save()
        self.assertFalse(accessible_mission(request, self.mission))
        self.customer.extras["restricted_access"] = ["test"]
        self.customer.save()
        self.assertFalse(accessible_mission(request, self.mission))
        self.mission.flags.pop("restricted_access")
        self.mission.save()
        self.assertTrue(accessible_mission(request, self.mission))

        # just make sure email_ops doesn't break
        email_ops("subject", "body")
        self.assertTrue(1 == 1)
