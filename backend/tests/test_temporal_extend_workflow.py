import json

import pytest

from app.models.workflow import Workflow
from app.services.comfyui.service import ComfyUIService
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.task_service import TaskService
from app.services.workflow_service import WorkflowService


REFERENCE_IDS = ("142", "141", "143", "137", "138", "140", "135", "136", "139")
ANCHOR_IDS = ("117", "128", "129", "130", "131", "132", "133", "134")


def _workflow(db_session):
    WorkflowService(db_session).load_default_workflows()
    return db_session.query(Workflow).filter(Workflow.type == "TEMPORAL_EXTEND", Workflow.is_system == True).one()


def test_temporal_extend_system_workflow_is_registered(db_session):
    workflow = _workflow(db_session)
    mapping = json.loads(workflow.node_mapping)
    graph = json.loads(workflow.workflow_json)

    assert workflow.name == "NovelFlow H3 AV 时序续生成 V1"
    assert workflow.is_active
    assert mapping["reference_to_video_node_id"] == "55"
    assert [mapping[f"keyframe_node_{i}"] for i in range(1, 9)] == list(ANCHOR_IDS)
    assert [mapping[f"load_image_node_{i}"] for i in range(1, 10)] == list(REFERENCE_IDS)
    assert graph["116"]["class_type"] == "MiniMaxH3CustomKeyframes"
    assert graph["55"]["class_type"] == "MiniMaxH3ReferenceToVideo"
    assert sum(node.get("class_type") == "LoadImage" for node in graph.values()) == 17
    assert TaskService.validate_workflow_node_mapping(workflow, "TEMPORAL_EXTEND") == (True, "")


def test_existing_temporal_extend_mapping_is_upgraded_in_place(db_session):
    workflow = _workflow(db_session)
    workflow_id = workflow.id
    old_mapping = json.loads(workflow.node_mapping)
    workflow.node_mapping = json.dumps({
        key: value for key, value in old_mapping.items()
        if not key.startswith("load_image_node_") and key != "reference_to_video_node_id"
    })
    db_session.commit()

    WorkflowService(db_session).load_default_workflows()

    db_session.expire_all()
    workflow = db_session.query(Workflow).filter(Workflow.type == "TEMPORAL_EXTEND").one()
    mapping = json.loads(workflow.node_mapping)
    assert workflow.id == workflow_id and workflow.is_active
    assert mapping["reference_to_video_node_id"] == "55"
    assert [mapping[f"load_image_node_{i}"] for i in range(1, 10)] == list(REFERENCE_IDS)
    assert [mapping[f"keyframe_node_{i}"] for i in range(1, 9)] == list(ANCHOR_IDS)


def test_temporal_extend_builder_bypasses_custom_keyframes_for_zero_anchors(db_session):
    workflow = _workflow(db_session)
    graph = WorkflowBuilder().build_temporal_extend_workflow(
        workflow.workflow_json, json.loads(workflow.node_mapping), "previous.mp4", 12, [],
        "story_test/temporal_extend", "next scene",
    )

    assert "116" not in graph
    assert all(node_id not in graph for node_id in (*ANCHOR_IDS, *REFERENCE_IDS))
    assert not any(key.startswith("ref_images.ref_image_") for key in graph["55"]["inputs"])
    assert graph["66"]["inputs"]["video"] == "previous.mp4"
    assert graph["65"]["inputs"]["filename_prefix"] == "story_test/temporal_extend"


@pytest.mark.parametrize("anchor_count,reference_count", [(0, 0), (2, 1), (2, 4), (8, 9)])
def test_temporal_anchors_and_visual_references_vary_independently(db_session, anchor_count, reference_count):
    workflow = _workflow(db_session)
    mapping = json.loads(workflow.node_mapping)
    anchors = [{"image": f"anchor_{i}.png", "position": (i + 1) * 30} for i in range(anchor_count)]
    references = [f"reference_{i}.png" for i in range(reference_count)]

    graph = WorkflowBuilder().build_temporal_extend_workflow(
        workflow.workflow_json, mapping, "previous.mp4", 12.5, anchors,
        "story_test/temporal_extend", "next scene", reference_image_filenames=references,
    )

    assert graph["125"]["inputs"]["value"] == 12.5
    assert ("116" in graph) == bool(anchor_count)
    if anchors:
        assert json.loads(graph["116"]["inputs"]["keyframe_state"]) == {
            "count": anchor_count, "positions": [item["position"] for item in anchors],
        }
    for index, node_id in enumerate(ANCHOR_IDS):
        if index < anchor_count:
            assert graph[node_id]["inputs"]["image"] == anchors[index]["image"]
        else:
            assert node_id not in graph
    for index, node_id in enumerate(REFERENCE_IDS):
        key = f"ref_images.ref_image_{index}"
        if index < reference_count:
            assert graph[node_id]["inputs"]["image"] == references[index]
            assert graph["55"]["inputs"][key] == [node_id, 0]
        else:
            assert node_id not in graph and key not in graph["55"]["inputs"]


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 4, 9])
async def test_temporal_extend_service_submits_only_requested_references(db_session, monkeypatch, count):
    workflow = _workflow(db_session)
    service = ComfyUIService()
    queued = []

    async def upload_video(_path):
        return {"success": True, "filename": "previous.mp4"}

    async def upload_image(path):
        return {"success": True, "filename": path.rsplit("/", 1)[-1]}

    async def queue_prompt(graph):
        queued.append(graph)
        return {"success": True, "prompt_id": "test-job"}

    async def wait_for_result(*_args, **_kwargs):
        return {"success": True, "video_url": "result.mp4"}

    monkeypatch.setattr(service.client, "upload_video", upload_video)
    monkeypatch.setattr(service.client, "upload_image", upload_image)
    monkeypatch.setattr(service.client, "queue_prompt", queue_prompt)
    monkeypatch.setattr(service.client, "wait_for_result", wait_for_result)

    result = await service.generate_video_continuation_with_workflow(
        prompt="next scene", workflow_json=workflow.workflow_json,
        node_mapping=json.loads(workflow.node_mapping), previous_video_path="/videos/previous.mp4",
        duration_seconds=5, filename_prefix="test/temporal", capability="TEMPORAL_EXTEND",
        anchors=[{"image_path": "/images/anchor.png", "position": 30}],
        reference_image_paths=[f"/images/ref_{i}.png" for i in range(count)],
    )

    assert result["success"] and len(queued) == 1
    assert queued[0]["117"]["inputs"]["image"] == "anchor.png"
    assert len([key for key in queued[0]["55"]["inputs"] if key.startswith("ref_images.ref_image_")]) == count
