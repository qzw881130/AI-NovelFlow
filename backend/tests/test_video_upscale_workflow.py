import json
from pathlib import Path

from app.models.task import Task
from app.models.workflow import Workflow
from app.services.workflow_service import WorkflowService


def test_topaz_video_upscale_system_workflow_is_registered(db_session):
    WorkflowService(db_session).load_default_workflows()

    workflow = db_session.query(Workflow).filter(
        Workflow.type == "video_upscale",
        Workflow.is_system == True,
    ).one()
    mapping = json.loads(workflow.node_mapping)
    workflow_json = json.loads(workflow.workflow_json)

    assert workflow.name == "Topaz Video 星光放大 V1"
    assert workflow.is_active is True
    assert mapping == {
        "load_video_node_id": "2",
        "scale_node_id": "15",
        "scale_value": "2x",
        "video_save_node_id": "3",
    }
    assert workflow_json["2"]["class_type"] == "LoadVideo"
    assert workflow_json["15"]["inputs"]["text"] == "2x"
    assert workflow_json["3"]["class_type"] == "SaveVideo"


def test_old_deployment_copy_is_removed_without_losing_selection_or_task_links(db_session, tmp_path):
    service = WorkflowService(db_session)
    service.load_default_workflows()
    current = db_session.query(Workflow).filter(Workflow.type == "video_upscale").one()
    old_path = str(tmp_path / "old-release" / "backend" / "workflows" / Path(current.file_path).name)
    duplicate = Workflow(
        name=current.name,
        description=current.description,
        type=current.type,
        workflow_json=current.workflow_json,
        node_mapping='{"video_save_node_id": "obsolete"}',
        is_system=True,
        is_active=True,
        file_path=old_path,
    )
    current.is_active = False
    db_session.add(duplicate)
    db_session.flush()
    task = Task(type="video_upscale", name="Historical task", workflow_id=duplicate.id)
    db_session.add(task)
    db_session.commit()

    service.load_default_workflows()

    remaining = db_session.query(Workflow).filter(Workflow.type == "video_upscale").one()
    assert remaining.id == current.id
    assert remaining.is_active is True
    assert json.loads(remaining.node_mapping)["video_save_node_id"] == "3"
    assert db_session.query(Task).filter(Task.id == task.id).one().workflow_id == current.id
