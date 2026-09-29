import json
import pytest

from app.models.workflow import Workflow
from app.services.comfyui.service import ComfyUIService
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.task_service import TaskService
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
        "video_save_node_id": "65",
        "reference_to_video_node_id": "55",
        **{f"load_image_node_{index}": node for index, node in enumerate(
            ("69", "68", "109", "110", "111", "112", "113", "114", "115"), 1
        )},
    }
    assert extension == {"workflow_capability": "TEMPORAL_EXTEND"}
    assert workflow_json["66"]["class_type"] == "VHS_LoadVideoFFmpeg"
    assert workflow_json["105"]["class_type"] == "PrimitiveFloat"
    assert workflow_json["107"]["class_type"] == "CR Prompt Text"
    assert workflow_json["39"]["class_type"] == "VHS_VideoCombine"
    assert workflow_json["65"]["class_type"] == "MiniMaxH3StreamLiveExtensionAVToVHS"
    assert workflow_json[mapping["reference_to_video_node_id"]]["class_type"] == "MiniMaxH3ReferenceToVideo"
    assert [workflow_json[mapping[f"load_image_node_{index}"]]["class_type"] for index in range(1, 10)] == ["LoadImage"] * 9
    assert TaskService.validate_workflow_node_mapping(workflow, "VIDEO_CONTINUATION") == (True, "")


def test_existing_video_continuation_is_upgraded_without_replacing_its_record(db_session):
    service = WorkflowService(db_session)
    service.load_default_workflows()
    workflow = db_session.query(Workflow).filter(Workflow.type == "VIDEO_CONTINUATION").one()
    original_id = workflow.id
    workflow.node_mapping = json.dumps({
        "load_video_node_id": "66", "duration_seconds_node_id": "105",
        "prompt_node_id": "107", "video_save_node_id": "65",
    })
    db_session.commit()

    service.load_default_workflows()

    db_session.expire_all()
    workflow = db_session.query(Workflow).filter(Workflow.type == "VIDEO_CONTINUATION").one()
    assert workflow.id == original_id and workflow.is_active
    assert [json.loads(workflow.node_mapping)[f"load_image_node_{index}"] for index in range(1, 10)] == [
        "69", "68", "109", "110", "111", "112", "113", "114", "115",
    ]
    assert json.loads(workflow.node_mapping)["reference_to_video_node_id"] == "55"


@pytest.mark.parametrize("count", [0, 1, 4, 9])
def test_video_continuation_optional_reference_slots(db_session, count):
    WorkflowService(db_session).load_default_workflows()
    workflow = db_session.query(Workflow).filter(Workflow.type == "VIDEO_CONTINUATION").one()
    mapping = json.loads(workflow.node_mapping)
    graph = WorkflowBuilder().build_video_continuation_workflow(
        workflow.workflow_json, mapping, "previous.mp4", 5, "next scene", "test/continuation",
        reference_image_filenames=[f"actual_{index}.png" for index in range(count)],
    )

    assert graph["66"]["inputs"]["video"] == "previous.mp4"
    assert graph["105"]["inputs"]["value"] == 5
    assert graph["107"]["inputs"]["prompt"] == "next scene"
    for index in range(9):
        node_id = mapping[f"load_image_node_{index + 1}"]
        link = f"ref_images.ref_image_{index}"
        if index < count:
            assert graph[node_id]["inputs"]["image"] == f"actual_{index}.png"
            assert graph["55"]["inputs"][link] == [node_id, 0]
        else:
            assert node_id not in graph
            assert link not in graph["55"]["inputs"]


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 4, 9])
async def test_video_continuation_uploads_only_supplied_references(db_session, monkeypatch, count):
    WorkflowService(db_session).load_default_workflows()
    workflow = db_session.query(Workflow).filter(Workflow.type == "VIDEO_CONTINUATION").one()
    service = ComfyUIService()
    submitted = []

    async def upload_video(_path):
        return {"success": True, "filename": "previous.mp4"}

    async def upload_image(path):
        return {"success": True, "filename": path.rsplit("/", 1)[-1]}

    async def queue_prompt(graph):
        submitted.append(graph)
        return {"success": True, "prompt_id": "test-job"}

    async def wait_for_result(*_args, **_kwargs):
        return {"success": True, "video_url": "video.mp4"}

    monkeypatch.setattr(service.client, "upload_video", upload_video)
    monkeypatch.setattr(service.client, "upload_image", upload_image)
    monkeypatch.setattr(service.client, "queue_prompt", queue_prompt)
    monkeypatch.setattr(service.client, "wait_for_result", wait_for_result)

    result = await service.generate_video_continuation_with_workflow(
        prompt="next scene", workflow_json=workflow.workflow_json,
        node_mapping=json.loads(workflow.node_mapping), previous_video_path="/videos/previous.mp4",
        duration_seconds=5, filename_prefix="test/continuation",
        reference_image_paths=[f"/images/actual_{i}.png" for i in range(count)],
    )

    assert result["success"] and len(submitted) == 1
    assert len([key for key in submitted[0]["55"]["inputs"] if key.startswith("ref_images.ref_image_")]) == count
