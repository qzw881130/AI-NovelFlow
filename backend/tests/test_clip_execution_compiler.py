import json

import pytest
from unittest.mock import patch

from app.constants.workflow import DEFAULT_WORKFLOW_NODE_MAPPINGS
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.workflow import Workflow
from app.models.task import Task

from app.services.clip_execution_compiler import ClipExecutionCompileError, compile_extend_clip, compile_generate_clip


class FakeShot:
    id = "shot-compiler"
    duration = 12
    image_url = "/api/files/shot.png"
    image_path = None
    keyframes = "[]"


def make_plan(mode="SINGLE_FRAME", keyframes=None, revision=3):
    return {
        "selected_mode": mode,
        "clip_plan_revision": revision,
        "keyframes": keyframes or [],
    }


def make_clip(index=1, start=0, end=8, **extra):
    return {"clip_index": index, "start_time": start, "end_time": end, "planned_duration": end - start, **extra}


def test_single_frame_projects_shot_image():
    result = compile_generate_clip(FakeShot(), make_plan(), make_clip(), "SINGLE_FRAME", 3)
    assert [item["image_url"] for item in result["video_reference_manifest"]["references"]] == ["/api/files/shot.png"]
    assert result["execution_contract"]["capability"] == "GENERATE"
    assert result["execution_contract"]["artifact_kind"] == "CLIP_ONLY"


def test_first_last_projects_start_then_end():
    plan = make_plan("FIRST_LAST_FRAME", [
        {"index": 1, "role": "START", "time_seconds": 0},
        {"index": 2, "role": "END", "time_seconds": 8, "image_url": "/api/files/end.png"},
    ])
    refs = compile_generate_clip(FakeShot(), plan, make_clip(), "FIRST_LAST_FRAME", 3)["video_reference_manifest"]["references"]
    assert [item["source_role"] for item in refs] == ["START", "END"]
    assert [item["source_keyframe_index"] for item in refs] == [1, 2]


def test_multi_keyframe_preserves_declared_non_monotonic_order():
    plan = make_plan("MULTI_KEYFRAME", [
        {"index": 1, "role": "START", "time_seconds": 0, "image_url": "/api/files/k1.png"},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 4, "image_url": "/api/files/k2.png"},
        {"index": 3, "role": "INTERMEDIATE", "time_seconds": 6, "image_url": "/api/files/k3.png"},
        {"index": 4, "role": "END", "time_seconds": 8, "image_url": "/api/files/k4.png"},
    ])
    refs = compile_generate_clip(
        FakeShot(), plan, make_clip(keyframe_indexes=[3, 1, 4]), "MULTI_KEYFRAME", 3,
    )["video_reference_manifest"]["references"]
    assert [item["source_keyframe_index"] for item in refs] == [3, 1, 4]


def test_zero_reference_single_frame_is_legal():
    shot = FakeShot()
    shot.image_url = None
    result = compile_generate_clip(shot, make_plan(), make_clip(), "SINGLE_FRAME", 3)
    assert result["video_reference_manifest"]["references"] == []


def test_stale_revision_and_invalid_timing_fail():
    with pytest.raises(ClipExecutionCompileError):
        compile_generate_clip(FakeShot(), make_plan(revision=3), make_clip(), "SINGLE_FRAME", 2)
    with pytest.raises(ClipExecutionCompileError):
        compile_generate_clip(FakeShot(), make_plan(), make_clip(start=8, end=8), "SINGLE_FRAME", 3)


def test_extend_compiles_exact_previous_provenance_without_io():
    plan = make_plan("SINGLE_FRAME", revision=4)
    clip = make_clip(
        index=2, start=8, end=12, capability="EXTEND",
        continuity_to_previous="CONTINUOUS", requires_temporal_control=False,
        previous_clip_index=1,
    )
    provenance = {
        "clip_index": 1,
        "clip_plan_revision": 4,
        "generated_by_task_id": "c1-task",
        "result_url": "/api/files/c1.mp4",
    }
    result = compile_extend_clip(FakeShot(), plan, clip, "SINGLE_FRAME", 4, provenance)
    assert result["execution_contract"]["capability"] == "EXTEND"
    assert result["execution_contract"]["artifact_kind"] == "CLIP_ONLY"
    assert result["execution_contract"]["previous_clip"] == provenance
    assert result["video_reference_manifest"]["references"][0]["image_url"] == "/api/files/shot.png"


@pytest.mark.parametrize("patch", [
    {"continuity_to_previous": "CUT"},
    {"requires_temporal_control": True},
])
def test_extend_rejects_non_extend_semantics(patch):
    clip = make_clip(
        index=2, start=8, end=12, capability="EXTEND",
        continuity_to_previous="CONTINUOUS", requires_temporal_control=False,
    )
    clip.update(patch)
    clip["previous_clip_index"] = 1
    with pytest.raises(ClipExecutionCompileError):
        compile_extend_clip(
            FakeShot(), make_plan("SINGLE_FRAME", revision=4), clip,
            "SINGLE_FRAME", 4,
            {"clip_index": 1, "clip_plan_revision": 4, "generated_by_task_id": "c1", "result_url": "/api/files/c1.mp4"},
        )


def test_extend_requires_complete_previous_provenance():
    clip = make_clip(index=2, start=8, end=12, capability="EXTEND", continuity_to_previous="CONTINUOUS", previous_clip_index=1)
    with pytest.raises(ClipExecutionCompileError):
        compile_extend_clip(FakeShot(), make_plan("SINGLE_FRAME", revision=4), clip, "SINGLE_FRAME", 4, {})


def test_multi_keyframe_extend_allows_zero_ordinary_refs():
    clip = make_clip(
        index=2, start=8, end=12, capability="EXTEND",
        continuity_to_previous="CONTINUOUS", requires_temporal_control=False,
        previous_clip_index=1,
    )
    result = compile_extend_clip(
        FakeShot(), make_plan("MULTI_KEYFRAME", revision=4), clip, "MULTI_KEYFRAME", 4,
        {"clip_index": 1, "clip_plan_revision": 4, "generated_by_task_id": "c1", "result_url": "/api/files/c1.mp4"},
    )
    assert result["execution_contract"]["capability"] == "EXTEND"
    assert result["video_reference_manifest"]["references"] == []


def test_multi_keyframe_extend_preserves_declared_ordinary_ref_order():
    plan = make_plan("MULTI_KEYFRAME", [
        {"index": 1, "role": "START", "time_seconds": 0, "image_url": "/api/files/k1.png"},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 4, "image_url": "/api/files/k2.png"},
        {"index": 3, "role": "END", "time_seconds": 8, "image_url": "/api/files/k3.png"},
    ], revision=4)
    clip = make_clip(
        index=2, start=8, end=12, capability="EXTEND", keyframe_indexes=[3, 1, 2],
        continuity_to_previous="CONTINUOUS", requires_temporal_control=False, previous_clip_index=1,
    )
    refs = compile_extend_clip(
        FakeShot(), plan, clip, "MULTI_KEYFRAME", 4,
        {"clip_index": 1, "clip_plan_revision": 4, "generated_by_task_id": "c1", "result_url": "/api/files/c1.mp4"},
    )["video_reference_manifest"]["references"]
    assert [item["source_keyframe_index"] for item in refs] == [3, 1, 2]


def test_missing_required_image_and_more_than_nine_refs_fail():
    plan = make_plan("FIRST_LAST_FRAME", [{"index": 2, "role": "END", "time_seconds": 8}])
    with pytest.raises(ClipExecutionCompileError):
        compile_generate_clip(FakeShot(), plan, make_clip(), "FIRST_LAST_FRAME", 3)

    keyframes = [
        {"index": index, "role": "INTERMEDIATE", "time_seconds": index, "image_url": f"/api/files/k{index}.png"}
        for index in range(1, 11)
    ]
    with pytest.raises(ClipExecutionCompileError):
        compile_generate_clip(
            FakeShot(), make_plan("MULTI_KEYFRAME", keyframes),
            make_clip(keyframe_indexes=list(range(1, 11))), "MULTI_KEYFRAME", 3,
        )


def test_semantic_endpoint_targets_exact_clip_and_preserves_shot_video(client, db_session):
    novel = Novel(id="novel-phase-b", title="Phase B")
    chapter = Chapter(id="chapter-phase-b", novel_id=novel.id, number=1, title="Chapter")
    shot = FakeShot()
    shot_model = Shot(
        id=shot.id,
        chapter_id=chapter.id,
        index=1,
        duration=12,
        image_url=None,
        video_url="/api/files/assembled.mp4",
        video_status="completed",
        video_director_plan=json.dumps({
            "selected_mode": "SINGLE_FRAME",
            "clip_plan_revision": 3,
            "clip_plan_validation": {"passed": True},
            "clip_plan": [{"clip_index": 2, "start_time": 0, "end_time": 8, "planned_duration": 8, "capability": "SINGLE_FRAME"}],
        }),
    )
    workflow = Workflow(
        id="phase-b-workflow",
        type="multi_reference_video",
        name="Minimax H3 多参考生视频 V20260928",
        workflow_json="{}",
        node_mapping=json.dumps(DEFAULT_WORKFLOW_NODE_MAPPINGS["multi_reference_video"]),
        is_active=True,
    )
    db_session.add_all([novel, chapter, shot_model, workflow])
    db_session.commit()
    captured = {}

    def enqueue(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    with patch("app.api.shots.enqueue_shot_video_task", side_effect=enqueue):
        response = client.post(
            f"/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/video-director/clips/2/generate",
            json={"clip_plan_revision": 3, "auto_merge": False},
        )

    assert response.status_code == 200
    task = db_session.query(Task).filter(Task.shot_id == shot.id).one()
    metadata = json.loads(task.metadata_json)
    assert task.workflow_id == workflow.id
    assert metadata["execution_contract"]["capability"] == "GENERATE"
    assert metadata["execution_contract"]["artifact_kind"] == "CLIP_ONLY"
    assert metadata["execution_contract"]["clip"]["clip_index"] == 2
    assert metadata["video_reference_manifest"]["references"] == []
    assert shot_model.video_url == "/api/files/assembled.mp4"
    assert captured["kwargs"]["selected_mode"] == "SINGLE_FRAME"
    assert captured["kwargs"]["clip_metadata"]["clip_index"] == 2
