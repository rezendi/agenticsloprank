from django.test import TestCase
from django.test.client import RequestFactory
from django.contrib.auth.models import AnonymousUser

from ..models import *
from web.oauth_views import setup_github, handle_github_webhook


class SetupGitHubTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_github_setup(self):
        print("setup test")
        request = self.factory.get(
            "/github/callback?installation_id=1234&setup_action=install&test=true"
        )
        request.user = AnonymousUser()
        request.session = {}
        setup_github(request)
        customer = Customer.objects.all().first()
        self.assertTrue(customer != None)
        integration = Integration.objects.all().first()
        self.assertTrue(integration != None)
        self.assertTrue(integration.vendor == "github")
        self.assertTrue(integration.customer_id == customer.id)
        self.assertTrue(integration.extras["install_id"] == "1234")
        secret = Secret.objects.all().first()
        self.assertTrue(secret != None)
        self.assertTrue(secret.value == "1234")
        self.assertTrue(secret.vendor == "github")
        self.assertTrue(secret.integration_id == integration.id)
        self.assertTrue(secret.customer_id == customer.id)
        self.assertTrue(customer.name == "")

        # do the webhook
        post = {
            "action": "created",
            "sender": {"login": "gittest"},
            "installation": {"id": "1234"},
        }
        handle_github_webhook(post, "installation", "test1")
        customer.refresh_from_db()
        self.assertTrue(customer.name == "gittest")
        integration.refresh_from_db()
        self.assertTrue("actions" in integration.extras)

        # now with a project
        print("test with project")
        project = Project.objects.create(name="testproject", customer=customer)
        request = self.factory.get(
            "/github/callback?installation_id=1235&setup_action=install&test=true"
        )
        request.user = User.objects.create(
            name="testuser",
            email="test@example.com",
            extras={"active_project": project.id},
        )
        request.session = {}
        setup_github(request)
        integration = Integration.objects.filter(extras__install_id="1235").first()
        self.assertTrue(integration.project_id == project.id)
        self.assertTrue(Integration.objects.count() == 2)

        # do the webhook
        post = {
            "action": "created",
            "sender": {"login": "gittest"},
            "installation": {"id": "1235"},
            "repositories": [
                {"full_name": "repo/testrepo"},
                {"full_name": "repo/testrepo2"},
            ],
        }
        handle_github_webhook(post, "installation", "test2")
        integration.refresh_from_db()
        self.assertTrue("actions" in integration.extras)
        self.assertTrue(len(integration.extras["actions"]) == 1)
        self.assertTrue("repos" in integration.extras)
        self.assertTrue(len(integration.extras["repos"]) == 2)
