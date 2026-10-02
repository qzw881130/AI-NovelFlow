import json

import pytest
from fastapi import HTTPException

from app.api import shots as shot_api
from app.models.novel import Chapter, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.models.task import Task
from app.repositories.chapter_repository import ChapterRepository
from app.repositories.novel_repository import NovelRepository
from app.repositories.prompt_template import PromptTemplateRepository
from app.repositories.shot_repository import ShotRepository
from app.schemas.shot import PlanClipsRequest, PlanVideoKeyframesRequest
from app.services.shot_keyframe_service import ShotKeyframeService
from app.services.shot_video_service import merge_video_director_clip_videos, resolve_extend_previous_av


class ReplacementLLM:
    def __init__(self):
        self.calls = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("task_type") != "keyframe_planner":
            raise AssertionError("#10 must fail pre-LLM for this fixture")
        return {
            "success": True,
            "content": json.dumps({"keyframes": [
                {
                    "index": 1,
                    "time_seconds": 0,
                    "role": "START",
                    "description": None,
                    "timed_visual_target": False,
                },
                {
                    "index": 2,
                    "time_seconds": 8,
                    "role": "END",
                    "description": "侍从站在镜前，皇帝皱眉看向他",
                    "timed_visual_target": True,
                },
            ]}, ensure_ascii=False),
        }


def _clip(index, capability, task_id, url, *, previous=None, states=None):
    return {
        "clip_index": index,
        "clip_plan_revision": 7,
        "start_time": (index - 1) * 4,
        "end_time": index * 4,
        "planned_duration": 4,
        "capability": capability,
        "continuity_to_previous": "CONTINUOUS" if previous else "CUT",
        "previous_clip_index": previous,
        "visual_state_indexes": states or [],
        "carry_in_state_index": 1 if previous else None,
        "execution_status": "APPROVED",
        "status": "SUCCEEDED",
        "approval_status": "APPROVED",
        "generated_by_task_id": task_id,
        "video_url": url,
    }


def _old_plan(task_ids):
    _, _, timeline_status = shot_api.build_dialogue_timeline(
        {"start_time": 0, "end_time": 8}, [], [],
    )
    clips = [
        _clip(1, "GENERATE", task_ids[0], "/api/files/c1.mp4", states=[1]),
        _clip(2, "EXTEND", task_ids[1], "/api/files/c2.mp4", previous=1, states=[2]),
    ]
    return {
        "canonical_visual_plan": True,
        "keyframes": [
            {"index": 1, "time_seconds": 0, "role": "START", "description": "", "timed_visual_target": False},
            {
                "index": 2,
                "time_seconds": 8,
                "role": "END",
                "description": "旧的结束状态",
                "timed_visual_target": True,
                "image_url": "/api/files/old-kf2.png",
                "image_task_id": "old-kf-task",
                "prompt_text": "旧 canonical KF2 prompt",
                "source": "old-source",
                "provenance": {"task_id": "old-kf-task"},
            },
        ],
        "transitions": [{"from_keyframe_index": 1, "to_keyframe_index": 2}],
        "clip_plan_revision": 7,
        "clip_plan": clips,
        "clip_plan_validation": {"passed": True},
        "clip_plan_findings": [{"code": "OLD"}],
        "clip_plan_approval_mode": "AUTO_APPROVE",
        "temporal_anchors": [{"anchor_id": "old-anchor", "image_url": "/api/files/old-kf2.png"}],
        "execution_readiness": {"ready": True},
        "assembly_status": "COMPLETED",
        "assembly_clip_plan_revision": 7,
        "assembly_task_ids": list(task_ids),
        "assembly_mode": "CONCAT",
        "assembled_result": {"url": "/api/files/final.mp4", "task_ids": list(task_ids)},
        "merged_video_url": "/api/files/final.mp4",
        "merged_at": "2026-10-02T00:00:00",
        "dialogue_timeline_source": [],
        "dialogue_timeline_status": timeline_status,
    }


def _clip_task(shot, novel, chapter, index, task_id, url, capability):
    metadata = {
        "execution_scope": "CLIP",
        "clip_id": f"{shot.id}:clip:{index}",
        "clip_index": index,
        "clip_plan_revision": 7,
        "capability": capability,
        "approval_status": "APPROVED",
        "execution_contract": {
            "artifact_kind": "CLIP_ONLY",
            "clip": {
                "clip_id": f"{shot.id}:clip:{index}",
                "clip_index": index,
                "clip_plan_revision": 7,
            },
        },
    }
    return Task(
        id=task_id,
        type="shot_video",
        status="completed",
        name=f"C{index}",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        result_url=url,
        metadata_json=json.dumps(metadata),
    )


def _fixture(db_session):
    novel = Novel(title="replacement")
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="chapter")
    db_session.add(chapter)
    db_session.flush()
    task_ids = ["old-c1", "old-c2"]
    plan = _old_plan(task_ids)
    shot = Shot(
        id="replacement-shot",
        chapter_id=chapter.id,
        index=11,
        description="皇帝提出问题，侍从回答",
        duration=8,
        characters=json.dumps(["皇帝", "侍从"], ensure_ascii=False),
        props="[]",
        dialogues="[]",
        image_url="/api/files/shot.png",
        keyframes=json.dumps([{
            "frame_index": 0,
            "plan_keyframe_index": 2,
            "time_seconds": 8,
            "description": "旧的结束状态",
            "image_url": "/api/files/old-kf2.png",
            "image_task_id": "old-kf-task",
            "prompt_text": "旧 canonical KF2 prompt",
            "source": "old-source",
            "provenance": {"task_id": "old-kf-task"},
            "reference_mode": "auto_select",
        }], ensure_ascii=False),
        video_director_plan=json.dumps(plan, ensure_ascii=False),
        video_url="/api/files/final.mp4",
        video_task_id="old-assembly",
        video_status="completed",
    )
    db_session.add(shot)
    db_session.flush()
    tasks = [
        _clip_task(shot, novel, chapter, 1, task_ids[0], "/api/files/c1.mp4", "GENERATE"),
        _clip_task(shot, novel, chapter, 2, task_ids[1], "/api/files/c2.mp4", "EXTEND"),
        Task(
            id="old-assembly",
            type="shot_video_batch_child",
            status="completed",
            name="Old assembly",
            novel_id=novel.id,
            chapter_id=chapter.id,
            shot_id=shot.id,
            result_url="/api/files/final.mp4",
        ),
    ]
    db_session.add_all(tasks + [
        PromptTemplate(name="#08", type="keyframe_planner", template="system #08", is_system=True),
        PromptTemplate(name="#10", type="keyframe_transition", template="system #10", is_system=True),
    ])
    db_session.commit()
    return novel, chapter, shot, tasks, plan


async def _replace_plan(db_session, monkeypatch, novel, chapter, shot, llm):
    monkeypatch.setattr(shot_api, "get_style", lambda *_args, **_kwargs: ("", None))
    return await shot_api.plan_video_keyframes(
        novel.id,
        chapter.id,
        shot.id,
        PlanVideoKeyframesRequest(force=True),
        db_session,
        NovelRepository(db_session),
        ChapterRepository(db_session),
        ShotRepository(db_session),
        PromptTemplateRepository(db_session),
        llm,
    )


@pytest.mark.asyncio
async def test_new_canonical_plan_invalidates_downstream_before_pre_llm_transition_failure(
    db_session, tmp_path, monkeypatch,
):
    novel, chapter, shot, tasks, old_plan = _fixture(db_session)
    history_files = [tmp_path / name for name in ("c1.mp4", "c2.mp4", "final.mp4")]
    for path in history_files:
        path.write_bytes(b"history")
    llm = ReplacementLLM()

    with pytest.raises(HTTPException, match="VISUAL_STATE_SPEECH_AUTHORITY_VIOLATION"):
        await _replace_plan(db_session, monkeypatch, novel, chapter, shot, llm)

    db_session.refresh(shot)
    current = json.loads(shot.video_director_plan)
    assert len(llm.calls) == 1
    assert current["canonical_visual_plan"] is True
    assert [state["description"] for state in current["keyframes"]] == ["", "侍从站在镜前，皇帝皱眉看向他"]
    assert current["transitions"] == []
    assert current["clip_plan_revision"] == 7
    for field in (
        "clip_plan", "clip_plan_validation", "clip_plan_findings",
        "clip_plan_approval_mode", "temporal_anchors", "execution_readiness",
        "assembly_status", "assembly_clip_plan_revision", "assembly_task_ids",
        "assembly_mode", "assembled_result", "merged_video_url", "merged_at",
    ):
        assert field not in current
    assert shot.video_url is None
    assert shot.video_task_id is None
    assert shot.video_status == "pending"
    assert db_session.query(Task).filter(Task.id.in_([task.id for task in tasks])).count() == 3
    assert all(path.is_file() for path in history_files)

    legacy = json.loads(shot.keyframes)[0]
    assert legacy["image_url"] is None
    assert legacy["image_task_id"] is None
    assert legacy["prompt_text"] is None
    assert legacy["source"] is None
    assert legacy["provenance"] is None

    with pytest.raises(RuntimeError, match="Semantic Clip Plan"):
        shot_api._semantic_batch_clips(shot, 7)
    with pytest.raises(ValueError, match="PREVIOUS_AV_UNAVAILABLE"):
        resolve_extend_previous_av(
            db_session,
            novel.id,
            chapter.id,
            shot,
            old_plan["clip_plan"][1],
            {
                "clip_index": 1,
                "clip_plan_revision": 7,
                "generated_by_task_id": "old-c1",
                "result_url": "/api/files/c1.mp4",
            },
        )
    assembly = await merge_video_director_clip_videos(
        db_session, shot, ShotRepository(db_session), novel.id, chapter.id, shot.index,
    )
    assert assembly["success"] is False

    async def next_plan(*_args, **_kwargs):
        return ([{
            "clip_index": 1,
            "clip_plan_revision": 8,
            "start_time": 0,
            "end_time": 8,
            "planned_duration": 8,
            "capability": "GENERATE",
            "continuity_to_previous": "NONE",
            "visual_state_indexes": [1, 2],
            "carry_in_state_index": None,
        }], {"passed": True, "findings": []})

    monkeypatch.setattr(shot_api, "plan_clips", next_plan)
    await shot_api.plan_shot_clips(
        novel.id,
        chapter.id,
        shot.id,
        PlanClipsRequest(),
        db_session,
        NovelRepository(db_session),
        ShotRepository(db_session),
    )
    db_session.refresh(shot)
    replanned = json.loads(shot.video_director_plan)
    assert replanned["clip_plan_revision"] == 8
    assert all(clip.get("generated_by_task_id") is None for clip in replanned["clip_plan"])


@pytest.mark.asyncio
async def test_active_current_revision_task_blocks_replacement_without_partial_invalidation(
    db_session, monkeypatch,
):
    novel, chapter, shot, _, old_plan = _fixture(db_session)
    active = Task(
        id="active-c1",
        type="shot_video",
        status="running",
        name="Active C1",
        novel_id=novel.id,
        chapter_id=chapter.id,
        shot_id=shot.id,
        metadata_json=json.dumps({
            "execution_scope": "CLIP",
            "clip_index": 1,
            "clip_plan_revision": 7,
        }),
    )
    db_session.add(active)
    db_session.commit()
    llm = ReplacementLLM()

    with pytest.raises(HTTPException) as exc_info:
        await _replace_plan(db_session, monkeypatch, novel, chapter, shot, llm)

    assert exc_info.value.status_code == 409
    db_session.refresh(shot)
    assert json.loads(shot.video_director_plan) == old_plan
    assert shot.video_url == "/api/files/final.mp4"
    assert shot.video_task_id == "old-assembly"
    assert shot.video_status == "completed"


def test_canonical_prompt_reuse_does_not_fall_back_when_current_authority_is_explicitly_empty(db_session):
    historical = Task(
        id="historical-keyframe",
        type="keyframe_image",
        status="completed",
        name="生成关键帧图片: shot-prompt-0",
        shot_id="shot-prompt",
        prompt_text="historical prompt",
    )
    db_session.add(historical)
    db_session.commit()
    service = ShotKeyframeService()

    assert service._get_reusable_keyframe_prompt(
        db_session, "shot-prompt", 0, {"plan_keyframe_index": 2, "prompt_text": None},
    ) == ""
    assert service._get_reusable_keyframe_prompt(
        db_session, "shot-prompt", 0, {"plan_keyframe_index": 2, "prompt_text": "current prompt"},
    ) == "current prompt"
    assert service._get_reusable_keyframe_prompt(
        db_session, "shot-prompt", 0, {"frame_index": 0},
    ) == "historical prompt"


def test_unchanged_canonical_state_preserves_current_prompt_authority():
    state = {
        "index": 2,
        "time_seconds": 8,
        "role": "END",
        "description": "unchanged",
        "timed_visual_target": True,
    }
    preserved = shot_api._preserve_matching_keyframe_assets(
        [dict(state)],
        {"keyframes": [{**state, "prompt_text": "current prompt", "image_url": "/current.png"}]},
        [],
    )

    assert preserved[0]["prompt_text"] == "current prompt"
    assert preserved[0]["image_url"] == "/current.png"
