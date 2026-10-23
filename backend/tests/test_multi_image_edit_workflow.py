import json

from app.models.workflow import Workflow
from app.services.workflow_service import WorkflowService


def test_multi_image_edit_system_workflow_is_registered(db_session):
    WorkflowService(db_session).load_default_workflows()

    workflow = db_session.query(Workflow).filter(
        Workflow.type == "multi_image_edit",
        Workflow.is_system == True,
    ).one()
    mapping = json.loads(workflow.node_mapping)
    workflow_json = json.loads(workflow.workflow_json)

    assert workflow.name == "Qwen image 2.1图片编辑 (任意数量参考图) API V20260926.json"
    assert workflow.description == "任意数目参考图编辑"
    assert workflow.is_active is True
    assert mapping == {
        "prompt_node_id": "516",
        "save_image_node_id": "515",
        "width_node_id": "517",
        "height_node_id": "518",
        "load_image_node_1": "470",
        "load_image_node_2": "510",
        "load_image_node_3": "503",
        "load_image_node_4": "520",
        "load_image_node_5": "521",
        "load_image_node_6": "522",
        "load_image_node_7": "523",
        "load_image_node_8": "524",
        "load_image_node_9": "525",
    }
    assert workflow_json["516"]["class_type"] == "CR Prompt Text"
    assert workflow_json["515"]["class_type"] == "SaveImage"
    assert workflow_json["517"]["class_type"] == "easy int"
    assert workflow_json["518"]["class_type"] == "easy int"
    assert [
        workflow_json[mapping[f"load_image_node_{index}"]]["class_type"]
        for index in range(1, 10)
    ] == ["LoadImage"] * 9
