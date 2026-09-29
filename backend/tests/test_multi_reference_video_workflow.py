import json

import pytest

from app.models.workflow import Workflow
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.comfyui.service import ComfyUIService
from app.services.task_service import TaskService
from app.services.workflow_service import WorkflowService


def test_multi_reference_video_is_first_active_system_workflow(db_session):
    WorkflowService(db_session).load_default_workflows()
    workflow = db_session.query(Workflow).filter(Workflow.type == "multi_reference_video").one()
    mapping = json.loads(workflow.node_mapping)
    graph = json.loads(workflow.workflow_json)

    assert workflow.is_system and workflow.is_active
    assert workflow.name == "Minimax H3 多参考生视频 V20260928"
    assert mapping["prompt_node_id"] == "138"
    assert mapping["video_save_node_id"] == "169"
    assert mapping["reference_to_video_node_id"] == "136"
    assert mapping["megapixels_node_id"] == "171"
    assert mapping["duration_seconds_node_id"] == "132"
    assert "reference_audio_node_id" not in mapping
    assert [mapping[f"load_image_node_{i}"] for i in range(1, 10)] == [
        "137", "139", "172", "173", "175", "174", "176", "177", "178",
    ]
    assert [graph[mapping[f"load_image_node_{i}"]]["class_type"] for i in range(1, 10)] == ["LoadImage"] * 9
    assert graph["136"]["class_type"] == "MiniMaxH3ReferenceToVideo"
    assert TaskService.validate_workflow_node_mapping(workflow, "multi_reference_video") == (True, "")


@pytest.mark.parametrize("count", [0, 1, 4, 9])
def test_optional_reference_images_never_use_workflow_sample_filenames(db_session, count):
    WorkflowService(db_session).load_default_workflows()
    workflow = db_session.query(Workflow).filter(Workflow.type == "multi_reference_video").one()
    original = json.loads(workflow.workflow_json)
    graph = json.loads(workflow.workflow_json)
    mapping = json.loads(workflow.node_mapping)
    filenames = [f"actual_ref_{i}.png" for i in range(count)]

    WorkflowBuilder.bind_multi_reference_video_images(graph, mapping, filenames)

    for i in range(9):
        node_id = mapping[f"load_image_node_{i + 1}"]
        link = f"ref_images.ref_image_{i}"
        if i < count:
            assert graph[node_id]["inputs"]["image"] == filenames[i]
            assert graph["136"]["inputs"][link] == [node_id, 0]
        else:
            assert node_id not in graph
            assert link not in graph["136"]["inputs"]

    assert len([node for node in graph.values() if node.get("class_type") == "LoadImage"]) == count
    assert len([key for key in graph["136"]["inputs"] if key.startswith("ref_images.ref_image_")]) == count
    assert len([node for node in original.values() if node.get("class_type") == "LoadImage"]) == 9


def test_misbound_reference_to_video_node_is_rejected(db_session):
    WorkflowService(db_session).load_default_workflows()
    workflow = db_session.query(Workflow).filter(Workflow.type == "multi_reference_video").one()
    mapping = json.loads(workflow.node_mapping)
    mapping["reference_to_video_node_id"] = "138"
    with pytest.raises(ValueError, match="MiniMax H3 Reference to Video"):
        WorkflowBuilder.bind_multi_reference_video_images(json.loads(workflow.workflow_json), mapping, ["ref.png"])


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 4, 9])
async def test_multi_reference_video_uploads_only_supplied_images(db_session, monkeypatch, count):
    WorkflowService(db_session).load_default_workflows()
    workflow = db_session.query(Workflow).filter(Workflow.type == "multi_reference_video").one()
    service = ComfyUIService()
    queued = []

    async def upload_image(path):
        return {"success": True, "filename": path.rsplit("/", 1)[-1]}

    async def queue_prompt(graph):
        queued.append(graph)
        return {"success": True, "prompt_id": "test-job"}

    async def wait_for_result(*_args, **_kwargs):
        return {"success": True, "video_url": "video.mp4"}

    monkeypatch.setattr(service.client, "upload_image", upload_image)
    monkeypatch.setattr(service.client, "queue_prompt", queue_prompt)
    monkeypatch.setattr(service.client, "wait_for_result", wait_for_result)

    result = await service.generate_shot_video_with_workflow(
        prompt="test prompt",
        workflow_json=workflow.workflow_json,
        node_mapping=json.loads(workflow.node_mapping),
        reference_image_paths=[f"/images/ref_{i}.png" for i in range(count)],
        duration_seconds=5,
    )

    assert result["success"] and len(queued) == 1
    graph = queued[0]
    assert graph["138"]["inputs"]["value"] == "test prompt"
    assert [graph[json.loads(workflow.node_mapping)[f"load_image_node_{i + 1}"]]["inputs"]["image"] for i in range(count)] == [
        f"ref_{i}.png" for i in range(count)
    ]
    assert len([key for key in graph["136"]["inputs"] if key.startswith("ref_images.ref_image_")]) == count
