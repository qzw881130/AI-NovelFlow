import json
from pathlib import Path

from app.models.workflow import Workflow
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.workflow_service import WorkflowService


def test_temporal_extend_system_workflow_is_registered(db_session):
    WorkflowService(db_session).load_default_workflows()

    workflow = db_session.query(Workflow).filter(
        Workflow.type == "TEMPORAL_EXTEND",
        Workflow.is_system == True,
    ).one()
    mapping = json.loads(workflow.node_mapping)
    workflow_json = json.loads(workflow.workflow_json)
    nodes = {str(node["id"]): node for node in workflow_json["nodes"]}

    assert workflow.name == "NovelFlow H3 AV 时序续生成 V1"
    assert workflow.is_active is True
    assert mapping == {
        "load_video_node_id": "66",
        "duration_seconds_node_id": "125",
        "prompt_node_id": "120",
        "keyframe_node_1": "117",
        "keyframe_node_2": "128",
        "keyframe_node_3": "129",
        "keyframe_node_4": "130",
        "keyframe_node_5": "131",
        "keyframe_node_6": "132",
        "keyframe_node_7": "133",
        "keyframe_node_8": "134",
        "custom_keyframes_node_id": "116",
        "video_save_node_id": "39",
    }
    assert nodes["66"]["type"] == "VHS_LoadVideoFFmpeg"
    assert nodes["125"]["type"] == "PrimitiveFloat"
    assert [nodes[node_id]["type"] for node_id in ["117", "128", "129", "130", "131", "132", "133", "134"]] == ["LoadImage"] * 8
    assert nodes["116"]["type"] == "MiniMaxH3CustomKeyframes"
    assert nodes["39"]["type"] == "VHS_VideoCombine"


def _temporal_workflow_and_mapping():
    path = Path(__file__).parent.parent / "workflows" / "temporal_extend_h3_v1_20260925.json"
    workflow = json.loads(path.read_text(encoding="utf-8"))
    mapping = {
        "load_video_node_id": "66",
        "duration_seconds_node_id": "125",
        "keyframe_node_1": "117",
        "keyframe_node_2": "128",
        "keyframe_node_3": "129",
        "keyframe_node_4": "130",
        "keyframe_node_5": "131",
        "keyframe_node_6": "132",
        "keyframe_node_7": "133",
        "keyframe_node_8": "134",
        "custom_keyframes_node_id": "116",
        "video_save_node_id": "39",
    }
    return workflow, mapping


def test_temporal_extend_builder_bypasses_custom_keyframes_for_zero_anchors():
    workflow, mapping = _temporal_workflow_and_mapping()

    result = WorkflowBuilder().build_temporal_extend_workflow(
        workflow, mapping, "previous.mp4", 12, [], "story_test/temporal_extend"
    )

    node_ids = {str(node["id"]) for node in result["nodes"]}
    assert "116" not in node_ids
    assert not node_ids.intersection({"117", "128", "129", "130", "131", "132", "133", "134"})
    assert any(link[1] == 55 and link[3] == 2 and link[4] == 1 for link in result["links"])
    save = next(node for node in result["nodes"] if node["id"] == 39)
    assert save["widgets_values_named"]["filename_prefix"] == "story_test/temporal_extend"
    assert save["widgets_values_named"]["save_output"] is True


def test_temporal_extend_builder_keeps_requested_anchor_nodes_and_updates_state():
    workflow, mapping = _temporal_workflow_and_mapping()
    anchors = [
        {"image": "anchor-1.png", "position": 120},
        {"image": "anchor-2.png", "position": 240},
    ]

    result = WorkflowBuilder().build_temporal_extend_workflow(
        workflow, mapping, "previous.mp4", 12.5, anchors, "story_test/temporal_extend"
    )

    nodes = {str(node["id"]): node for node in result["nodes"]}
    state = json.loads(nodes["116"]["widgets_values_named"]["keyframe_state"])
    assert state == {"count": 2, "positions": [120, 240]}
    assert nodes["117"]["widgets_values_named"]["image"] == "anchor-1.png"
    assert nodes["128"]["widgets_values_named"]["image"] == "anchor-2.png"
    assert not set(nodes).intersection({"129", "130", "131", "132", "133", "134"})
    assert nodes["125"]["widgets_values_named"]["value"] == 12.5


def test_temporal_extend_builder_keeps_all_eight_anchor_nodes():
    workflow, mapping = _temporal_workflow_and_mapping()
    anchors = [{"image": f"anchor-{index}.png", "position": index * 30} for index in range(1, 9)]

    result = WorkflowBuilder().build_temporal_extend_workflow(
        workflow, mapping, "previous.mp4", 20, anchors, "story_test/temporal_extend"
    )

    nodes = {str(node["id"]): node for node in result["nodes"]}
    state = json.loads(nodes["116"]["widgets_values_named"]["keyframe_state"])
    assert state == {"count": 8, "positions": [30, 60, 90, 120, 150, 180, 210, 240]}
    assert {"117", "128", "129", "130", "131", "132", "133", "134"}.issubset(nodes)
