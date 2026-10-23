import json
from types import SimpleNamespace

import pytest

from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.services.shot_keyframe_service import ShotKeyframeService
from app.services.prompt_template_service import PromptTemplateService


@pytest.mark.asyncio
async def test_reference_selector_filters_unknown_refs_and_limits_temporal_anchors(db_session):
    PromptTemplateService(db_session).init_system_templates()
    service = ShotKeyframeService()
    service.llm_service = SimpleNamespace(chat_completion=None)

    async def select(**_kwargs):
        return {
            "success": True,
            "content": json.dumps({
                "selected_references": [
                    {
                        "type": "TEMPORAL_ANCHOR",
                        "ref_ids": ["KF1", "KF2", "KF3", "UNKNOWN"],
                        "purpose": "preserve distinct historical states",
                    },
                    {
                        "type": "CHARACTER_IDENTITY",
                        "ref_ids": ["CHAR:hero", "MISSING"],
                        "purpose": "preserve identity",
                    },
                ]
            }),
        }

    service.llm_service.chat_completion = select
    shot = SimpleNamespace(
        id="shot-1",
        chapter_id="chapter-1",
        duration=20,
        continuity_mode="NORMAL",
        description="shot",
        characters='["hero"]',
        scene="",
        props="[]",
    )
    candidates = [
        {"ref_id": "KF1", "type": "TEMPORAL_ANCHOR"},
        {"ref_id": "KF2", "type": "TEMPORAL_ANCHOR"},
        {"ref_id": "KF3", "type": "TEMPORAL_ANCHOR"},
        {"ref_id": "CHAR:hero", "type": "CHARACTER_IDENTITY"},
    ]

    _payload, _raw, parsed = await service._select_references(
        db_session,
        SimpleNamespace(id="novel-1"),
        shot,
        {"plan_keyframe_index": 4, "time_seconds": 20, "description": "current"},
        candidates,
    )

    assert parsed["selected_references"][0]["ref_ids"] == ["KF1", "KF2"]
    assert parsed["selected_references"][1]["ref_ids"] == ["CHAR:hero"]


@pytest.mark.asyncio
async def test_empty_selected_manifest_stays_explicit_with_unbacked_predecessor(db_session):
    novel = Novel(title="empty manifest")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="chapter")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="current state",
        characters="[]",
        scene="",
        props="[]",
        keyframes=json.dumps([
            {
                "frame_index": 0,
                "plan_keyframe_index": 3,
                "time_seconds": 12,
                "description": "predecessor without an image",
                "image_url": None,
                "reference_mode": "auto_select",
            },
            {
                "frame_index": 1,
                "plan_keyframe_index": 4,
                "time_seconds": 18,
                "description": "current state",
                "reference_mode": "auto_select",
            },
        ]),
    )
    workflow = Workflow(
        name="任意数量参考图",
        type="multi_image_edit",
        workflow_json="{}",
        node_mapping="{}",
        is_active=True,
    )
    task = Task(
        id="task-empty-manifest",
        type="keyframe_image",
        status="pending",
        name=f"生成关键帧图片: {shot.id}-1",
        shot_id=shot.id,
        novel_id=novel.id,
        chapter_id=chapter.id,
    )
    db_session.add_all([shot, workflow, task])
    db_session.commit()

    service = ShotKeyframeService()

    async def select_no_references(*_args, **_kwargs):
        return ({"available_references": []}, '{"selected_references":[]}', {"selected_references": []})

    class PromptCaptured(Exception):
        pass

    captured = {}

    async def capture_prompt(*_args, reference_manifest=None, **_kwargs):
        captured["reference_manifest"] = reference_manifest
        raise PromptCaptured

    service._select_references = select_no_references
    service._build_qwen_keyframe_prompt = capture_prompt

    with pytest.raises(PromptCaptured):
        await service._generate_keyframe_image_task(
            db_session,
            task.id,
            shot.id,
            1,
        )

    metadata = json.loads(db_session.get(Task, task.id).metadata_json)
    assert metadata["reference_manifest"] == []
    assert captured["reference_manifest"] == []


@pytest.mark.asyncio
async def test_keyframe_prompt_declarations_follow_actual_manifest(db_session):
    PromptTemplateService(db_session).init_system_templates()
    novel = Novel(title="prompt manifest")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="chapter")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="current state",
        characters="[]",
        scene="",
        props="[]",
    )
    db_session.add(shot)
    db_session.commit()

    service = ShotKeyframeService()
    captured_payloads = []

    async def build_prompt(**kwargs):
        payload = json.loads(kwargs["user_content"].split("\n\n", 1)[1])
        captured_payloads.append(payload)
        count = len(payload["reference_image_manifest"])
        return {
            "success": True,
            "content": "text-only current state" if count == 0 else "preserve identity from <image_1>",
        }

    service.llm_service = SimpleNamespace(chat_completion=build_prompt)
    predecessor = {
        "frame_index": 0,
        "plan_keyframe_index": 3,
        "description": "predecessor without an image",
        "image_url": None,
    }
    current = {"frame_index": 1, "plan_keyframe_index": 4, "description": "current state"}
    task = SimpleNamespace(current_step="")

    empty_prompt = await service._build_qwen_keyframe_prompt(
        db_session, novel, shot, current, predecessor, task, reference_manifest=[]
    )
    actual_manifest = [{
        "picture": 1,
        "picture_index": 1,
        "kind": "TEMPORAL_ANCHOR",
        "type": "TEMPORAL_ANCHOR",
        "sources": ["KF3"],
        "purpose": "preserve predecessor state",
        "url": "/api/files/kf3.png",
        "path": "/tmp/kf3.png",
    }]
    positive_prompt = await service._build_qwen_keyframe_prompt(
        db_session, novel, shot, current, predecessor, task,
        reference_manifest=actual_manifest,
    )

    assert captured_payloads[0]["reference_image_manifest"] == []
    assert "<image_1>" not in empty_prompt
    assert "PREVIOUS_KEYFRAME" not in json.dumps(captured_payloads[0])
    assert len(captured_payloads[1]["reference_image_manifest"]) == 1
    assert captured_payloads[1]["reference_image_manifest"][0]["sources"] == ["KF3"]
    assert "<image_1>" in positive_prompt
