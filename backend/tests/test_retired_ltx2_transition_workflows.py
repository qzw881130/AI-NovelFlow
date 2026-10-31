from app.constants.workflow import EXTRA_SYSTEM_WORKFLOWS, RETIRED_LTX2_TRANSITION_WORKFLOW_FILES
from app.models.task import Task
from app.models.workflow import Workflow
from app.services.workflow_service import WorkflowService


def test_ltx2_transition_presets_are_not_seeded(db_session):
    assert not any(
        config["filename"] in RETIRED_LTX2_TRANSITION_WORKFLOW_FILES
        for config in EXTRA_SYSTEM_WORKFLOWS
    )

    WorkflowService(db_session).load_default_workflows()

    assert db_session.query(Workflow).filter_by(type="transition", is_system=True).count() == 0


def test_old_ltx2_transition_presets_are_retired_without_losing_task_history(db_session):
    old_used = Workflow(
        name="LTX2 镜头转场视频", type="transition", is_system=True, is_active=True,
        workflow_json="{}", file_path="/old-install/workflows/transition_ltx2_camera.json",
    )
    old_unused = Workflow(
        name="LTX2 光线转场视频", type="transition", is_system=True, is_active=False,
        workflow_json="{}", file_path="/old-install/workflows/transition_ltx2_lighting.json",
    )
    custom = Workflow(
        name="自定义转场", type="transition", is_system=False, is_active=False,
        workflow_json="{}", file_path="/old-install/user_workflows/custom.json",
    )
    db_session.add_all([old_used, old_unused, custom])
    db_session.flush()
    task = Task(type="transition_video", name="historical", workflow_id=old_used.id)
    db_session.add(task)
    db_session.commit()
    old_used_id, old_unused_id, custom_id = old_used.id, old_unused.id, custom.id

    service = WorkflowService(db_session)
    service.load_default_workflows()
    service.load_default_workflows()

    assert db_session.get(Workflow, old_unused_id) is None
    assert db_session.get(Workflow, old_used_id) is not None
    assert not db_session.get(Workflow, old_used_id).is_active
    assert db_session.get(Task, task.id).workflow_id == old_used_id
    assert [workflow.id for workflow in service.workflow_repo.list_by_type("transition")] == [custom_id]
    assert service.workflow_repo.get_first_system_by_type("transition") is None
    assert service.workflow_repo.get_active_by_type("transition") is None
    assert service.set_default_workflow(old_used_id)["status_code"] == 410
