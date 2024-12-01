from datetime import timedelta
from django.utils import timezone
from django.test import TestCase
from django.test.client import RequestFactory

from ..models import *
from ..hub import fulfil_mission, run_task
from ..util import TEST_MODEL
from web.views import create_task


class SimpleMissionTest(TestCase):
    def setUp(self):
        mission_info = MissionInfo.objects.create(
            name="TDTest mission info",
            base_llm=TEST_MODEL,
            base_prompt="This is a test prompt",
            flags={"general_eval": "true"},
        )
        first = TaskInfo.objects.create(
            mission_info=mission_info,
            name="TDTest fetch task",
            base_url=GITHUB_PREFIX + "test/repo",
            base_llm=TEST_MODEL,
            category=TaskCategory.API,
        )
        TaskInfo.objects.create(
            mission_info=mission_info,
            name="TDTest report task",
            category=TaskCategory.LLM_REPORT,
            parent=first,
            base_llm=TEST_MODEL,
            base_prompt="This is a test prompt",
        )
        mission = mission_info.create_mission()
        self.mission_id = mission.id

    def test_mission_run(self):
        fulfil_mission(self.mission_id)
        mission = Mission.objects.get(id=self.mission_id)
        tasks = mission.task_set.all()
        self.assertEqual(len(tasks), 5)  # include final task and 2 eval tasks
        done = [t.status for t in tasks if t.status == TaskStatus.COMPLETE]
        self.assertEqual(len(done), 5)  # include final task and 2 eval tasks


# just check variants work
class MissionTests(TestCase):
    def setUp(self):
        self.mission_info = MissionInfo.objects.create(
            name="TDTest mission info",
            base_llm=TEST_MODEL,
            base_prompt="This is a test prompt",
        )

    def test_assemble_previous_responses(self):
        mission = self.mission_info.create_mission()
        t1 = Task.objects.create(
            mission=mission,
            category=TaskCategory.API,
            response="Test fetch response",
        )
        t2 = Task.objects.create(
            mission=mission,
            parent=t1,
            category=TaskCategory.LLM_REPORT,
            response="Test report response",
        )
        t3 = Task.objects.create(
            mission=mission,
            parent=t1,
            category=TaskCategory.SCRAPE,
            response="Test scrape response",
        )
        t4 = Task.objects.create(
            mission=mission,
            parent=t3,
            category=TaskCategory.LLM_DECISION,
            response="Test LLM decision response",
        )
        t5 = Task.objects.create(
            mission=mission,
            parent=t4,
            category=TaskCategory.SCRAPE,
            response="Test scrape response 2",
        )
        t6 = Task.objects.create(
            mission=mission,
            parent=t5,
            category=TaskCategory.LLM_REPORT,
            response="Test report 2",
        )
        t7 = Task.objects.create(
            mission=mission,
            parent=t6,
            category=TaskCategory.LLM_REPORT,
            response="Test report 3",
        )
        previous = t2.prerequisite_input_tasks()
        self.assertTrue(len(previous) == 1)
        previous = t5.prerequisite_input_tasks()
        self.assertTrue(len(previous) == 1)
        previous = t6.prerequisite_input_tasks()
        self.assertTrue(len(previous) == 2)
        previous = t7.prerequisite_input_tasks()
        self.assertTrue(len(previous) == 3)
        self.assertTrue(previous[0] == t4)
        self.assertTrue(previous[1] == t5)
        self.assertTrue(previous[2] == t6)

    def test_recurring_mission(self):
        self.mission_info.cadence = MissionInfo.Cadence.WEEKLY
        self.mission_info.save()
        m1 = self.mission_info.create_mission()
        ti1 = TaskInfo.objects.create(
            mission_info=self.mission_info,
            name="Fetch test data",
            category=TaskCategory.API,
        )
        ti2 = TaskInfo.objects.create(
            mission_info=self.mission_info,
            name="Report on test",
            category=TaskCategory.LLM_REPORT,
            base_prompt="Test prompt",
        )
        ti3 = TaskInfo.objects.create(
            mission_info=self.mission_info,
            name="Finalize test",
            category=TaskCategory.FINALIZE_MISSION,
        )
        t1 = ti1.create_task(m1)
        t1.status = TaskStatus.COMPLETE
        t2 = ti2.create_task(m1, parent=t1)
        t2.status = TaskStatus.COMPLETE
        t3 = ti3.create_task(m1, parent=t1)
        t3.status = TaskStatus.COMPLETE
        for days in [2, 3, 5, 7, 30]:
            m1.created_at = timezone.now() - timedelta(days=days)
            m1.status = Mission.MissionStatus.COMPLETE
            m1.save()
            for t in [t1, t2, t3]:
                t.created_at = timezone.now() - timedelta(days=days)
                t.save()
            m2 = self.mission_info.create_mission()
            if days > 3 and days < 28:
                self.assertTrue(m2.previous == m1)
                self.assertTrue(m2.is_time_series())
            else:
                self.assertTrue(m2.previous == None)
            m2.name = "Recurring %s" % days
            m2.save()
            t4 = ti1.create_task(m2)
            t5 = ti2.create_task(m2, parent=t4)
            t6 = ti3.create_task(m2, parent=t5)
            if days > 3 and days < 28:
                self.assertTrue(t6.commit_days() == days)
            prev = t5.previous()
            if days in [2, 3, 30]:
                self.assertTrue(prev == None)
                continue
            self.assertTrue(prev == t2)
            run_task(t5.id)
            t5.refresh_from_db()
            self.assertTrue(t5.status == TaskStatus.COMPLETE)
            self.assertTrue(t5.flags.get("time_series_days") == "%s" % days)
            t5.delete()
            t4.delete()
            m2.delete()

    def test_aggregate_tasks(self):
        customer = Customer.objects.create()
        Project.objects.create(name="TDTest", customer=customer)
        self.mission_info.customer = customer
        self.mission_info.cadence = MissionInfo.Cadence.WEEKLY
        self.mission_info.save()
        m1 = self.mission_info.create_mission()
        m1.status = Mission.MissionStatus.COMPLETE
        m1.save()
        m2 = self.mission_info.create_mission()
        m2.status = Mission.MissionStatus.COMPLETE
        m2.save()
        ti = TaskInfo.objects.create(
            mission_info=self.mission_info,
            name="TDTest commit reports",
            category=TaskCategory.LLM_REPORT,
        )
        t1 = ti.create_task(m1)
        t1.response = "Test fetch first response"
        t1.status = TaskStatus.COMPLETE
        t1.save()
        t2 = ti.create_task(m2)
        t2.response = "Test fetch second response"
        t2.status = TaskStatus.COMPLETE
        t2.save()
        self.assertTrue(len(m2.sub_reports()) == 1)
        ati = TaskInfo.objects.create(
            mission_info=self.mission_info,
            name="TDTest aggregate commit reports",
            category=TaskCategory.AGGREGATE_REPORTS,
        )
        m3 = self.mission_info.create_mission()
        at = ati.create_task(m3)
        fulfil_mission(m3.id)
        at.refresh_from_db()
        assert t1.response in at.response
        assert t2.response in at.response
        final = m3.task_set.last()
        self.assertTrue("/reports/%s" % m2.id in final.response)

    # check new fetch task(s) are created and run as appropriate
    def test_llm_decision(self):
        mission = self.mission_info.create_mission()
        t1 = Task.objects.create(
            mission=mission,
            category=TaskCategory.API,
            status=TaskStatus.COMPLETE,
            response="Test fetch response",
        )
        t2 = Task.objects.create(
            mission=mission,
            parent=t1,
            category=TaskCategory.LLM_DECISION,
            status=TaskStatus.CREATED,
            prompt="Test decision prompt",
        )
        run_task(t2.id)
        self.assertTrue(mission.task_set.count() == 2)
        t2.url = GITHUB_PREFIX + "test/files"
        t2.status = TaskStatus.CREATED
        t2.save()
        run_task(t2.id)
        self.assertTrue(mission.task_set.count() == 3)

    def test_followup(self):
        mission = self.mission_info.create_mission()
        t1 = Task.objects.create(
            mission=mission,
            name="TDTest Fetch One",
            category=TaskCategory.API,
            status=TaskStatus.COMPLETE,
            response="Test fetch one",
        )
        t2 = Task.objects.create(
            mission=mission,
            parent=t1,
            category=TaskCategory.LLM_REPORT,
            status=TaskStatus.COMPLETE,
            response="Test report one",
        )
        t3 = Task.objects.create(
            mission=mission,
            name="TDTest Fetch Two",
            category=TaskCategory.API,
            status=TaskStatus.COMPLETE,
            response="Test fetch two",
        )
        t4 = Task.objects.create(
            mission=mission,
            parent=t3,
            category=TaskCategory.LLM_REPORT,
            status=TaskStatus.COMPLETE,
            response="Test report one",
        )
        fulfil_mission(mission.id)
        mission.refresh_from_db()
        self.assertTrue(mission.status == Mission.MissionStatus.COMPLETE)
        f = Task.objects.create(
            mission=mission,
            name="TDTest Followup Question",
            category=TaskCategory.LLM_QUESTION,
            parent=mission.task_set.filter(
                category=TaskCategory.FINALIZE_MISSION
            ).last(),
            prompt="Test followup question",
            extras={"followup_question": "Test followup question"},
        )
        self.assertTrue(f.is_test())
        self.assertTrue(len(f.prerequisite_tasks()) == 3)
        run_task(f.id)
        f.refresh_from_db()
        self.assertTrue(f.extras.get("final_prompt_length", 0) > 150)
        self.assertTrue(f.response == "Test Gemini response")


class MissionConfigTests(TestCase):
    def test_data_mission(self):
        mi1 = MissionInfo.objects.create(
            name="TDTest data mission",
            base_llm=TEST_MODEL,
            cadence=MissionInfo.Cadence.WEEKLY,
        )
        ti = TaskInfo.objects.create(
            mission_info=mi1,
            name="TDTest data task",
            category=TaskCategory.API,
        )
        mi2 = MissionInfo.objects.create(
            name="TDTest dependent mission",
            base_llm=TEST_MODEL,
            cadence=MissionInfo.Cadence.WEEKLY,
            depends_on=mi1,
        )
        ti2 = TaskInfo.objects.create(
            mission_info=mi2,
            name="TDTest dependent task",
            category=TaskCategory.API,
        )
        try:
            m2 = mi2.create_mission()

        except Exception as e:
            self.assertTrue("No valid data mission" in str(e))

        m1 = mi1.create_mission()
        self.assertTrue(mi1.latest_mission() == None)
        fulfil_mission(m1.id)
        m1.refresh_from_db()
        self.assertTrue(mi1.latest_mission() == m1)
        fulfil_mission(m2.id)
        m2.refresh_from_db()
        self.assertTrue(m2.depends_on == m1)


class TaskAPITests(TestCase):
    # for now, just test empty case
    def test_api_task_creations(self):
        mi = MissionInfo.objects.create(
            name="TDTest API task creationmission info",
            base_llm=TEST_MODEL,
            base_prompt="This is a test prompt",
        )
        mission = mi.create_mission()
        task_data = {
            "api_key": settings.API_KEYS[0],
            "mission_id": mission.id,
            "name": "TDTest API task",
            "data": "This is some test data",
            "category": TaskCategory.OTHER,
            "reporting": Reporting.ALWAYS_REPORT,
        }
        factory = RequestFactory()
        path = "/missions/create_task"
        request = factory.post(path, task_data)
        create_task(request)
        tasks = mission.task_set.all()
        self.assertTrue(len(tasks) == 1)
        task_data["run"] = "true"
        request = factory.post(path, task_data)
        create_task(request)
        tasks = mission.task_set.all()
        log("tasks", tasks)
        self.assertTrue(len(tasks) == 3)
