import json

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
