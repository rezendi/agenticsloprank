import pytest
from ..models import *
from ..admin_jobs import evaluate_mission


@pytest.fixture
def setup_mission():
    mission_info = MissionInfo.objects.create(
        name="TDTest mission info",
        base_llm=TEST_MODEL,
        base_prompt="This is a test prompt",
    )
    mission = mission_info.create_mission()
    Task.objects.create(
        mission=mission,
        name="TDTest fetch task",
        llm=TEST_MODEL,
        category=TaskCategory.API,
    )
    Task.objects.create(
        mission=mission,
        name="TDTest report task",
        llm=TEST_MODEL,
        category=TaskCategory.LLM_REPORT,
    )
    return mission


@pytest.mark.django_db
def test_task_evaluations(setup_mission):
    mission = setup_mission
    mission.flags["evaluate"] = "true"

    assert mission.extras.get("evaluated") is None

    t1 = mission.task_set.first()
    t1.extras["errors"] = ["This is a test task error"]
    t1.save()

    evaluation = evaluate_mission(mission)
    problems = evaluation.errors.get("problems", [])
    evals = MissionEvaluation.objects.filter(mission=mission)

    assert len(evals) == 1
    assert problems == evals[0].get_problems()
    assert len(problems) == 3
    assert "This is a test task error" in str(problems)
    assert "Mission not started" in str(problems)

    mission.refresh_from_db()
    assert mission.extras.get("evaluated") == "true"
