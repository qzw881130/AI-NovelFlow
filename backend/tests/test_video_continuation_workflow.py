import json

from app.models.workflow import Workflow
from app.services.workflow_service import WorkflowService


def test_video_continuation_system_workflow_is_registered(db_session):
    WorkflowService(db_session).load_default_workflows()

    workflow = db_session.query(Workflow).filter(
        Workflow.type == "VIDEO_CONTINUATION",
        Workflow.is_system == True,
    ).one()
    mapping = json.loads(workflow.node_mapping)
    extension = json.loads(workflow.extension)
    workflow_json = json.loads(workflow.workflow_json)

    assert workflow.name == "NovelFlow H3 AV 视频续生成 Minimal V1"
    assert workflow.is_active is True
    assert mapping == {
        "load_video_node_id": "66",
        "duration_seconds_node_id": "105",
        "prompt_node_id": "107",
        "video_save_node_id": "39",
    }
    assert extension == {"workflow_capability": "TEMPORAL_EXTEND"}
    assert workflow_json["66"]["class_type"] == "VHS_LoadVideoFFmpeg"
    assert workflow_json["105"]["class_type"] == "PrimitiveFloat"
    assert workflow_json["107"]["class_type"] == "CR Prompt Text"
    assert workflow_json["39"]["class_type"] == "VHS_VideoCombine"
