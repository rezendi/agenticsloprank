import datetime
from types import SimpleNamespace

from django.test import TestCase

from ..models import *
from ..util import get_sized_prompt
from ..run import run_scrape
from ..plugins.github import get_gh_issues, get_gh_commits
from ..plugins.jira import get_jira_issues
from ..plugins.notion import get_notion_pages
from ..plugins.jira import get_jira_issues
from ..plugins.figma import get_figma_files
from ..plugins.slack import get_slack_chatter
from ..plugins.linear import get_linear_issues
from ..plugins.harvest import fetch_harvest_projects
from ..plugins.text_links import process_text


class GHList(list):
    totalCount = 0
    pull_request = False

    def __init__(self, iterable):
        super().__init__(iterable)
        self.totalCount = len(iterable)


class EmptyMockRepo:
    full_name = "mock/empty"

    def get_pulls(self, state=None):
        return GHList([])

    def get_issues(self, state=None):
        return GHList([])

    def get_issues_comments(self, since=None):
        return GHList([])

    def get_pulls(self, state=None):
        return GHList([])


class MockRepo:
    full_name = "mock/mock"
    default_branch = "main"

    def get_issues(self, state=None):
        datenow = datetime.datetime.now(datetime.timezone.utc)
        dicts = [
            {
                "id": 1002,
                "number": 2,
                "title": "Just another issue",
                "body": "This is the body of the other issue",
                "pull_request": False,
                "created_at": datenow,
                "updated_at": datenow,
                "closed_at": None,
                "state": "closed",
                "user": None,
                "pull_request": None,
                "comments": 2,
                "labels": [SimpleNamespace(**{"name": "bug"})],
                "milestone": SimpleNamespace(**{"title": "v1.0"}),
            },
        ]
        if state == "open":
            dicts = [
                {
                    "id": 1001,
                    "number": 1,
                    "title": "Just an issue",
                    "body": "This is the body of the issue",
                    "pull_request": False,
                    "created_at": datenow,
                    "updated_at": datenow,
                    "closed_at": None,
                    "state": "open",
                    "user": None,
                    "pull_request": None,
                    "comments": 0,
                    "labels": [SimpleNamespace(**{"name": "bug"})],
                    "milestone": SimpleNamespace(**{"title": "v1.0"}),
                },
                {
                    "id": 2001,
                    "number": 11,
                    "title": "Just a PR",
                    "body": "This is the body of the PR",
                    "pull_request": False,
                    "created_at": datenow,
                    "updated_at": datenow,
                    "closed_at": None,
                    "state": "open",
                    "user": None,
                    "pull_request": {},
                    "comments": 0,
                    "labels": [],
                    "milestone": None,
                },
                {
                    "id": 2002,
                    "number": 12,
                    "title": "Just another PR",
                    "body": "This is the body of the other PR",
                    "pull_request": False,
                    "created_at": datenow,
                    "updated_at": datenow,
                    "closed_at": None,
                    "state": "open",
                    "user": None,
                    "pull_request": {},
                    "comments": 0,
                    "labels": [],
                    "milestone": None,
                },
            ]
        objs = [SimpleNamespace(**d) for d in dicts]
        return GHList(objs)

    def get_pulls(self, state=None):
        return GHList([])

    def get_issues_comments(self, since=None):
        datestr = datetime.datetime.now(datetime.timezone.utc).isoformat()
        test_user_dict = {"login": "testuser", "name": "Test User"}
        test_user = SimpleNamespace(**test_user_dict)
        dicts = [
            {
                "id": 1,
                "user": test_user,
                "issue_url": "https://test.com/example/11",
                "body": "Just a comment",
                "created_at": datestr,
            },
            {
                "id": 2,
                "user": test_user,
                "issue_url": "https://test.com/example/12",
                "body": "Just another comment",
                "created_at": datestr,
            },
        ]
        return GHList([SimpleNamespace(**d) for d in dicts])

    def get_branches(self, state=None):
        return GHList([])

    def get_commits(self, state=None):
        datestr = datetime.datetime.now(datetime.timezone.utc).isoformat()
        auth = {"login": "testuser", "name": "Test User", "date": datestr}
        stats = {"additions": 10, "deletions": 5, "total": 15}
        stats = SimpleNamespace(**stats)
        file = {
            "filename": "test.py",
            "additions": 10,
            "deletions": 5,
            "changes": 15,
            "status": "modified",
        }
        file = SimpleNamespace(**file)
        c1 = {
            "author": SimpleNamespace(**auth),
            "message": "Test Commit 1",
        }
        c2 = {
            "author": SimpleNamespace(**auth),
            "message": "Test Commit 2",
        }
        dicts = [
            {
                "commit": SimpleNamespace(**c1),
                "sha": "123456a",
                "stats": stats,
                "files": [file],
                "parents": [],
            },
            {
                "commit": SimpleNamespace(**c2),
                "sha": "123456b",
                "stats": stats,
                "files": [file],
                "parents": [],
            },
        ]
        objs = [SimpleNamespace(**d) for d in dicts]
        return GHList(objs)


class GitHubTest(TestCase):
    def setUp(self):
        mission_info = MissionInfo.objects.create(name="TDTest mission info")
        self.task_info = TaskInfo.objects.create(
            mission_info=mission_info,
            name="TDTest task info",
            category=TaskCategory.API,
            base_prompt="This is a test prompt",
        )
        self.mission = mission_info.create_mission()

    def test_empty_repo(self):
        mock = EmptyMockRepo()
        task = self.task_info.create_task(self.mission)
        get_gh_issues(task, mock)
        self.assertTrue("### Open issues: 0" in task.response)
        self.assertTrue("### Closed issues: 0" in task.response)

    def test_repo(self):
        mock = MockRepo()
        task = self.task_info.create_task(self.mission)
        get_gh_issues(task, mock)
        self.assertTrue("### Open issues: 3" in task.response)
        self.assertTrue("### Closed issues: 1" in task.response)

    def test_commits(self):
        mock = MockRepo()
        task = self.task_info.create_task(self.mission)
        get_gh_commits(task, mock)
        self.assertTrue(
            "0 days ago - Test Commit 2 by Test User (testuser)" in task.response
        )
        self.assertTrue("test.py (+10, -5)" in task.response)


class PromptSizingTest(TestCase):
    def setUp(self):
        self.mission_info = MissionInfo.objects.create(name="TTDest mission info")
        self.task_info = TaskInfo.objects.create(
            mission_info=self.mission_info,
            name="TDTest task info",
            category=TaskCategory.LLM_REPORT,
            base_prompt="This is a test prompt",
        )

    def test_sizing(self):
        mission = self.mission_info.create_mission()
        task = self.task_info.create_task(mission)
        task.llm = GPT_4_BASE
        self.assertEqual(task.get_llm(), GPT_4_BASE)
        full = get_sized_prompt(task, task.prompt)
        self.assertEqual(full, task.prompt)
        self.assertFalse(task.extras["truncated"])
        too_big = ["It's important to report on all of this information."] * (1024 * 4)
        too_big = "\n".join(too_big)
        prompt = get_sized_prompt(task, too_big)
        self.assertNotEqual(prompt, too_big)
        self.assertTrue(task.extras["truncated"])
        self.assertTrue("truncated_tokens" in task.extras)
        log("truncated", task.extras["truncated_tokens"])
        self.assertTrue(task.extras["truncated_tokens"] == 12290)


class TextLinking(TestCase):
    def test_no_double_links(self):
        mission_info = MissionInfo.objects.create(
            name="TDTest mission info", flags={"github": "link/text"}
        )
        mission = mission_info.create_mission()
        text = "Pulls such as [#256](https://github.com/microsoft/AI-For-Beginners/pull/256)"
        processed = process_text(mission, text)
        self.assertEqual(2, len(processed.split("[")))
        text = "Pulls such as [PR #256](https://github.com/microsoft/AI-For-Beginners/pull/256)"
        processed = process_text(mission, text)
        self.assertEqual(2, len(processed.split("[")))
        text = "Papers such as [#1234.56789](https://arxiv.org/abs/1234.56789)"
        processed = process_text(mission, text)
        self.assertEqual(2, len(processed.split("[")))

    def test_linking(self):
        cust = Customer.objects.create(name="Test Customer")
        Integration.objects.create(
            customer=cust,
            vendor="jira",
            extras={
                "jira": "TEST",
                "accessible": [{"url": "https://test.atlassian.net"}],
            },
        )
        mission_info = MissionInfo.objects.create(
            name="TDTest mission info", flags={"github": "link/text"}, customer=cust
        )
        mission = mission_info.create_mission()
        text = """
PR #25
Issue #27
ArXiv #1234.56789
Just some text
ArXiv #1234.56790
enhancements. [#62](https://github.com/link/text/pulls/62) presents
TEST-123
`TEST-123`
PR #26.2
PR #27."""
        processed = process_text(mission, text)
        log("Processed text:", processed)
        lines = processed.splitlines()
        self.assertTrue("https://github.com/link/text/issues/25" in lines[1])
        self.assertTrue("https://github.com/link/text/issues/27" in lines[2])
        self.assertTrue("https://arxiv.org/abs/1234.56789" in lines[3])
        self.assertTrue("https" not in lines[4])
        self.assertTrue("https://arxiv.org/abs/1234.56790" in lines[5])
        self.assertTrue("https://github.com/link/text/issues/62" in lines[6])
        self.assertTrue(
            "[TEST-123](https://test.atlassian.net/browse/TEST-123)" in lines[7]
        )
        self.assertTrue(
            "[TEST-123](https://test.atlassian.net/browse/TEST-123)" not in lines[8]
        )
        self.assertTrue("https://github.com/link/text/issues/26." not in lines[9])
        self.assertTrue("https://github.com/link/text/issues/27)." in lines[10])

    def test_file_linking(self):
        mission_info = MissionInfo.objects.create(name="TDTest mission info")
        task_info = TaskInfo.objects.create(
            mission_info=mission_info,
            name="TDTest task info",
            category=TaskCategory.API,
            flags={"default_branch": "main", "github": "link/text"},
        )
        mission = mission_info.create_mission()
        t = task_info.create_task(mission)
        t.structured_data = {"default_branch": "main", "repo": "link/text"}
        t.save()
        text = """
Preamble
The `tests` directory has tests.
The `run/do_it.py` file is the main file.
Just some text
Can't forget the [`explode.py`] file.
Already linking to the [`other.py`](https://other.com/)
Just checking for ['final.py']"""
        processed = process_text(mission, text)
        lines = processed.splitlines()
        self.assertTrue("https://github.com/link/text/tree/main/tests" in lines[2])
        self.assertTrue(
            "https://github.com/link/text/blob/main/run/do_it.py" in lines[3]
        )
        self.assertTrue("https" not in lines[4])
        self.assertTrue("https://github.com/link/text/blob/main/explode.py" in lines[5])
        self.assertTrue("https://github.com" not in lines[6])

        project = Project.objects.create(name="Test Project")
        project.extras = {"jira": "TEST"}
        project.save()
        integration = Integration.objects.create(name="Test Integration", vendor="jira")
        integration.extras["accessible"] = [{"url": "https://test.atlassian.net"}]
        integration.project = project
        integration.save()
        mission_info.project = project
        mission_info.save()
        text = " Ticket TEST-123 "
        processed = process_text(mission, text)
        self.assertTrue("https://test.atlassian.net/browse/TEST-123" in processed)


class ScrapeTests(TestCase):
    def test_arxiv_list_prefixing(self):
        mi = MissionInfo.objects.create(name="TDTest mission info")
        mission = Mission.objects.create(mission_info=mi, name="TDTest mission")
        t1 = Task.objects.create(
            mission=mission,
            name="TDTest decision",
            category=TaskCategory.LLM_DECISION,
            response="""
{
  "category": "Computational Finance",
  "url": "/list/q-fin.CP/recent",
  "reason": "The project is related to sending cryptocurrencies, which falls under financial technology and computational finance."
}
""",
        )
        t2 = Task.objects.create(
            mission=mission,
            name="TDTest scrape",
            parent=t1,
            category=TaskCategory.SCRAPE,
            flags={"custom_scrape": "true"},
        )
        run_scrape(t2)
        t2.refresh_from_db()
        self.assertTrue(
            ARXIV_PREFIX + "/list/q-fin.CP/recent" in t2.structured_data["urls"]
        )


class JiraTests(TestCase):
    def setUp(self):
        mission_info = MissionInfo.objects.create(name="TDTest mission info")
        self.task_info = TaskInfo.objects.create(
            mission_info=mission_info,
            name="TDTest task info",
            category=TaskCategory.API,
            base_url=JIRA_API,
        )
        self.mission = mission_info.create_mission()
        self.task = self.task_info.create_task(self.mission)

    def get_mock_jira(self):
        class MockJira:
            def get_all_fields(self):
                return []

            def jql(self, jql, start=0):
                if start > 0:
                    return {"issues": []}
                return {
                    "issues": [
                        {
                            "key": "TEST-1",
                            "fields": {
                                "project": {"key": "TEST", "name": "Test Project"},
                                "creator": {"displayName": "Test User"},
                                "priority": {"name": "Medium"},
                                "issuetype": {"name": "Task"},
                                "summary": "Test issue 1",
                                "created": "2020-01-01T00:00:00.000Z",
                                "updated": "2021-01-01T00:00:00.000Z",
                                "status": {
                                    "name": "To Do",
                                    "statusCategory": {"name": "To Do"},
                                },
                                "comment": {"comments": []},
                            },
                        },
                        {
                            "key": "TEST-2",
                            "fields": {
                                "project": {"key": "TEST", "name": "Test Project"},
                                "creator": {"displayName": "Test User"},
                                "priority": {"name": "High"},
                                "issuetype": {"name": "Bug"},
                                "summary": "Test issue 2",
                                "created": "2020-01-01T00:00:00.000Z",
                                "updated": "2021-01-01T00:00:00.000Z",
                                "status": {
                                    "name": "Done",
                                    "statusCategory": {"name": "Done"},
                                },
                                "comment": {"comments": []},
                            },
                        },
                    ],
                }

        return MockJira()

    def test_fetch_jira(self):
        get_jira_issues(self.task, self.get_mock_jira())
        self.assertTrue("#### TEST-2" in self.task.response)


class OtherTests(TestCase):
    def setUp(self):
        self.mission_info = MissionInfo.objects.create(name="TDTest mission info")
        self.mission = self.mission_info.create_mission()

    def get_task(self, url):
        task_info = TaskInfo.objects.create(
            mission_info=self.mission_info,
            name="TDTest task info",
            category=TaskCategory.API,
            base_url=url,
        )
        return task_info.create_task(self.mission)

    # Notion

    def get_mock_notion(self):
        class MockNotion:
            class users:
                def list():
                    return {"results": [{"id": "TEST", "name": "TDTest User"}]}

            class blocks:
                class children:
                    def list(block_id):
                        return {
                            "results": [
                                {
                                    "object": "block",
                                    "type": "paragraph",
                                    "paragraph": {
                                        "text": [
                                            {
                                                "plain_text": "Hello, test! Test test test."
                                            }
                                        ]
                                    },
                                }
                            ]
                        }

            def search(self, query, sort=None, filter=None):
                return {
                    "results": [
                        {
                            "id": "TEST",
                            "object": "page",
                            "url": "https://notion.so/TEST",
                            "title": [{"plain_text": "TDTest"}],
                            "created_time": datetime.datetime.now().isoformat(),
                            "last_edited_time": datetime.datetime.now().isoformat(),
                            "created_by": {"id": "TEST", "name": "TDTest User"},
                            "last_edited_by": {"id": "TEST", "name": "TDTest User"},
                            "properties": {
                                "Page": {"title": [{"plain_text": "TDTest"}]}
                            },
                        }
                    ]
                }

        return MockNotion()

    def test_render_notion(self):
        task = self.get_task(NOTION_API)
        get_notion_pages(task, self.get_mock_notion())
        self.assertTrue("#### Page title: TDTest" in task.response)

    # Figma

    def get_mock_figma(self):
        class MockFigma:
            def get_team_projects(self, team):
                projects = {
                    "projects": [
                        {"id": "tdtest1", "name": "TDTest project 1"},
                        {"id": "tdtest2", "name": "TDTest project 2"},
                    ]
                }
                return SimpleNamespace(**projects)

            def get_project_files(self, project_id):
                files = {
                    "files": [
                        {
                            "key": "tdtest1",
                            "name": "TDTest file 1",
                            "last_modified": datetime.datetime.now().isoformat(),
                            "thumbnail_url": "https://figma.com/tdtest1",
                        },
                        {
                            "key": "tdtest2",
                            "name": "TDTest file 2",
                            "last_modified": datetime.datetime.now().isoformat(),
                            "thumbnail_url": "https://figma.com/tdtest2",
                        },
                    ]
                }
                return SimpleNamespace(**files)

            def get_file_versions(self, file_key):
                versions = {
                    "versions": [
                        {
                            "label": "V1",
                            "description": "Test version 1",
                            "created_at": datetime.datetime.now().isoformat(),
                            "user": {"handle": "TDTest User"},
                        },
                        {
                            "label": "V2",
                            "description": "Test version 2",
                            "created_at": datetime.datetime.now().isoformat(),
                            "user": {"handle": "TDTest User"},
                        },
                    ]
                }
                return SimpleNamespace(**versions)

            def get_comments(self, file_key):
                c1 = {
                    "user": {"handle": "TDTest User"},
                    "created_at": datetime.datetime.now().isoformat(),
                    "resolved_at": None,
                    "message": "Test comment 1",
                }
                c2 = {
                    "user": {"handle": "TDTest User"},
                    "created_at": datetime.datetime.now().isoformat(),
                    "resolved_at": None,
                    "message": "Test comment 2",
                }
                comments = {
                    "comments": [
                        SimpleNamespace(**c1),
                        SimpleNamespace(**c2),
                    ]
                }
                return SimpleNamespace(**comments)

        return MockFigma()

    def test_render_figma(self):
        task = self.get_task(FIGMA_API)
        get_figma_files(task, self.get_mock_figma())
        self.assertTrue("### Figma project: TDTest project 2" in task.response)
        self.assertTrue("TDTest User - 0 days ago - Test comment 2" in task.response)

    # Slack

    def get_mock_slack(self):
        class MockSlack:
            def users_list(self):
                return {
                    "members": [
                        {
                            "id": "tdtest1",
                            "name": "Test User 1",
                            "title": "CTO",
                            "profile": "Just this guy, you know?",
                        },
                        {
                            "id": "tdtest2",
                            "name": "Test User 2",
                            "title": "CPO",
                            "profile": "She is, she is",
                        },
                    ]
                }

            def conversations_list(self):
                return {
                    "channels": [
                        {
                            "id": "tdtest1",
                            "name": "Channel Zero",
                            "created": datetime.datetime.now().isoformat(),
                            "updated": datetime.datetime.now().isoformat(),
                            "is_archived": False,
                            "topic": {"value": "We watch Channel Zero"},
                            "purpose": {"value": "We watch Channel Zero"},
                        },
                        {
                            "id": "tdtest2",
                            "name": "General",
                            "created": datetime.datetime.now().isoformat(),
                            "updated": datetime.datetime.now().isoformat(),
                            "is_archived": False,
                            "topic": {"value": "Slack talk"},
                            "purpose": {"value": "Slack talk"},
                        },
                    ]
                }

            def conversations_history(self, channel, oldest, limit):
                return {
                    "messages": [
                        {
                            "id": "tdtest1",
                            "user": "tdtest1",
                            "text": "Test message 1",
                            "ts": "123438788",
                        },
                        {
                            "id": "tdtest1",
                            "user": "tdtest2",
                            "text": "Test message 2",
                            "ts": "123438788",
                        },
                    ]
                }

        return MockSlack()

    def test_render_slack(self):
        task = self.get_task(SLACK_API)
        get_slack_chatter(task, self.get_mock_slack())
        self.assertTrue("#### Recent Conversation: Channel Zero" in task.response)
        self.assertTrue("Test User 2: Test message 2" in task.response)

    # Linear

    def get_mock_linear(self):
        class MockLinear:
            is_test = True

            def get_issues(self):
                return []

        return MockLinear()

    def test_render_linear(self):
        task = self.get_task(HARVEST_API)
        get_linear_issues(task, self.get_mock_linear())
        # TODO actually test this by mocking GraphQL

    # Harvest

    def get_mock_harvest(self):
        class MockHarvest:
            is_test = True

            def fetch(self, endpoint):
                key = endpoint.split("?")[0].split("/")[-1]
                vals = []
                if key == "users":
                    vals = [
                        {
                            "first_name": "Test",
                            "last_name": "User 1",
                            "roles": ["Developer", "Designer"],
                            "is_contractor": True,
                        },
                        {
                            "first_name": "Test",
                            "last_name": "User 2",
                            "roles": ["Designer", "PM"],
                            "is_contractor": False,
                        },
                    ]

                if key == "projects":
                    vals = [
                        {
                            "id": "tdtest1",
                            "name": "Test Project 1",
                            "client": {"id": "client1", "name": "Client 1"},
                            "starts_on": datetime.datetime.now().isoformat(),
                            "ends_on": datetime.datetime.now().isoformat(),
                            "notes": "Already over",
                        },
                        {
                            "id": "tdtest2",
                            "name": "Test Project 2",
                            "client": {"id": "client2", "name": "Client 2"},
                            "starts_on": datetime.datetime.now().isoformat(),
                            "ends_on": datetime.datetime.now().isoformat(),
                            "notes": "Just a project",
                        },
                    ]

                if key == "user_assignments":
                    vals = [
                        {"user": {"name": "Test User 1"}},
                        {"user": {"name": "Test User 2"}},
                    ]

                if key == "task_assignments":
                    vals = [
                        {"task": {"name": "Test Task 1"}},
                        {"task": {"name": "Test Task 2"}},
                    ]

                dict = {key: vals}
                return SimpleNamespace(**dict)

        return MockHarvest()

    def test_render_harvest(self):
        task = self.get_task(HARVEST_API)
        fetch_harvest_projects(task, self.get_mock_harvest())
        self.assertTrue("#### Project: Test Project 2" in task.response)
        self.assertTrue("- Test Task 2" in task.response)
