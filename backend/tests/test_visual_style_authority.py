"""Visual state persists WHAT; prompt builders read the current HOW."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import shots as shot_api
from app.models.novel import Chapter, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.repositories.prompt_template import PromptTemplateRepository
from app.services import video_director_ai
from app.services.novel_service import NovelService
from app.services.llm_service import LLMService
from app.services.shot_keyframe_service import ShotKeyframeService
from app.services.visual_style_authority import strip_embedded_visual_style


STYLE_A = "rendering style A with clean volumes. Preserve authored identities."
STYLE_B = "rendering style B with ink shading. Preserve authored identities."
FACTS = "Scene: 皇宫织房，午后侧光，中近景平视，门在前景。\nCharacters:\n- 骗子1: 左侧抱金丝卷，怒视对方。\nAction: 两人相互瞪视。"


def test_exact_cleanup_preserves_scene_characters_action_and_unknown_english():
    legacy = FACTS.replace("门在前景。", f"门在前景，{STYLE_A} style, high quality, detailed。")
    assert strip_embedded_visual_style(legacy, STYLE_A) == FACTS
    assert strip_embedded_visual_style(legacy, STYLE_B) == legacy
    longer_style = FACTS.replace("门在前景。", f"门在前景，{STYLE_A} Additional authored English details。")
    assert strip_embedded_visual_style(longer_style, STYLE_A) == longer_style
    placeholder = FACTS.replace("门在前景。", "门在前景。##STYLE## style, high quality, detailed。")
    assert strip_embedded_visual_style(placeholder, STYLE_B) == FACTS


def test_migration_preview_apply_and_idempotence(tmp_path):
    database = tmp_path / "novelflow.db"
    template_files = {
        ("chapter_split", "章节分镜导演解析"): "05_NovelFlow_VideoDirector_ShotDirector_V1.txt",
        ("keyframe_planner", "关键帧时间轴规划"): "08_NovelFlow_VideoDirector_KeyframePlanner_V2_3Frame4Frame.txt",
        ("keyframe_transition", "关键帧过渡规划"): "10_NovelFlow_KeyframeTransition_Planner_V1.txt",
        ("h3_single_frame_prompt", "MiniMax H3 单帧视频提示词构建"): "11_MiniMax_H3_SingleFrame_VideoPrompt_V1.txt",
        ("h3_first_last_frame_prompt", "MiniMax H3 首尾帧视频提示词构建"): "12_MiniMax_H3_FirstLastFrame_VideoPrompt_V1.txt",
        ("h3_multi_keyframe_prompt", "MiniMax H3 多关键帧视频提示词构建"): "13_MiniMax_H3_MultiKeyframe_VideoPrompt_V1.txt",
    }
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE prompt_templates (id TEXT, type TEXT, name TEXT, is_system INTEGER, template TEXT, created_at TEXT);
            CREATE TABLE novels (id TEXT, style_prompt_template_id TEXT);
            CREATE TABLE chapters (id TEXT, novel_id TEXT);
            CREATE TABLE shots (id TEXT, chapter_id TEXT, description TEXT, keyframes TEXT,
                                video_director_plan TEXT, image_url TEXT, video_url TEXT);
        """)
        db.execute("INSERT INTO prompt_templates VALUES ('style', 'style', 'A', 1, ?, '2026-01-01')", (STYLE_A,))
        for index, ((template_type, name), _) in enumerate(template_files.items()):
            db.execute("INSERT INTO prompt_templates VALUES (?, ?, ?, 1, 'stale', '2026-01-01')",
                       (str(index), template_type, name))
        db.execute("INSERT INTO novels VALUES ('novel', 'style')")
        db.execute("INSERT INTO chapters VALUES ('chapter', 'novel')")
        db.execute("INSERT INTO novels VALUES ('old-novel', NULL)")
        db.execute("INSERT INTO chapters VALUES ('old-chapter', 'old-novel')")
        legacy = FACTS.replace("门在前景。", f"门在前景，{STYLE_A} style, high quality, detailed。")
        keyframes = [{"description": "Scene: 窗边。##STYLE## style, high quality, detailed。\nCharacters:\nAction: 静止。",
                      "image_url": "keep-kf.png"}]
        plan = {"keyframes": keyframes, "transitions": [{"transition_description": "骗子从左向右，##STYLE## style, high quality, detailed。"}]}
        db.execute("INSERT INTO shots VALUES ('shot', 'chapter', ?, ?, ?, 'keep.png', 'keep.mp4')",
                   (legacy, json.dumps(keyframes, ensure_ascii=False), json.dumps(plan, ensure_ascii=False)))
        db.execute("INSERT INTO shots VALUES ('old-shot', 'old-chapter', ?, '[]', '{}', 'old.png', 'old.mp4')",
                   (FACTS.replace("门在前景。", "门在前景，former rendering style. style, high quality, detailed。"),))

    script = Path(__file__).resolve().parents[1] / "migrations" / "clean_visual_style_descriptions.py"

    def run(*extra):
        process = subprocess.run([sys.executable, str(script), "--database", str(database), *extra],
                                 check=True, capture_output=True, text=True)
        return json.loads(process.stdout.split("\nbackup:", 1)[0])

    preview = run()
    assert preview["shots_changed"] == 1
    assert preview["description_fields_cleaned"] == {
        "shot.description": 1,
        "shot.keyframes[].description": 1,
        "plan.keyframes[].description": 1,
        "plan.transitions[].transition_description": 1,
    }
    assert preview["system_templates_to_sync"] == 3
    assert preview["unmatched"] == [{
        "shot_id": "old-shot",
        "field": "shot.description",
        "reason": "style differs from current fallback visual_style",
    }]
    with sqlite3.connect(database) as db:
        assert STYLE_A in db.execute("SELECT description FROM shots WHERE id='shot'").fetchone()[0]

    applied = run("--apply")
    assert applied["shots_changed"] == 1
    assert run()["shots_changed"] == 0
    assert run()["system_templates_to_sync"] == 0
    with sqlite3.connect(database) as db:
        description, keyframes_json, plan_json, image_url, video_url = db.execute(
            "SELECT description, keyframes, video_director_plan, image_url, video_url FROM shots WHERE id='shot'"
        ).fetchone()
        assert description == FACTS
        assert "##STYLE##" not in keyframes_json + plan_json
        assert image_url == "keep.png" and video_url == "keep.mp4"


@pytest.mark.asyncio
async def test_chapter_split_prompt_does_not_inject_visual_style(monkeypatch):
    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return {"success": True, "content": json.dumps({"shots": [{"description": FACTS}]}, ensure_ascii=False)}

    service = LLMService()
    monkeypatch.setattr(service, "chat_completion", complete)
    await service.split_chapter_with_prompt(
        chapter_title="织房", chapter_content="两人争执。",
        prompt_template="Scene: ##STYLE## style, high quality, detailed。 {图像风格}",
        style=STYLE_A, story_world_context={},
    )
    assert STYLE_A not in captured["system_prompt"]
    assert "##STYLE##" not in captured["system_prompt"]
    assert "style, high quality, detailed" not in captured["system_prompt"]


@pytest.mark.asyncio
async def test_new_chapter_split_persists_factual_shot(db_session, monkeypatch):
    style = PromptTemplate(name="A", type="style", template=STYLE_A)
    split = PromptTemplate(name="split", type="chapter_split", template="Scene facts only", is_system=True)
    db_session.add_all([style, split])
    db_session.flush()
    novel = Novel(title="authority test", style_prompt_template_id=style.id)
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="织房", content="两名骗子争执。")
    db_session.add(chapter)
    db_session.commit()

    mock_llm = SimpleNamespace(
        api_key="test", provider="test", api_url="test",
        split_chapter_with_prompt=AsyncMock(return_value={
            "chapter": chapter.title,
            "shots": [{"description": FACTS.replace("门在前景。", f"门在前景，{STYLE_A} style, high quality, detailed。"),
                       "video_description": "两人继续争执。", "characters": ["骗子1"], "scene": "织房", "props": [], "duration": 4}],
        }),
    )
    monkeypatch.setattr("app.services.story_world_context.get_locked_story_world_context", lambda *_: SimpleNamespace(model_dump=lambda: {}))
    monkeypatch.setattr("app.services.novel_service.file_storage.delete_chapter_directory", lambda *_: None)
    service = NovelService(db_session)
    monkeypatch.setattr(service, "get_llm_service", lambda: mock_llm)

    result = await service.split_chapter(novel, chapter, ["骗子1"], ["织房"])
    persisted = db_session.query(Shot).filter(Shot.chapter_id == chapter.id).one()
    assert result["success"]
    assert persisted.description == FACTS
    assert all(section in persisted.description for section in ("Scene:", "Characters:", "Action:"))


def test_three_new_keyframes_strip_style_but_keep_visual_states():
    raw = {
        "keyframes": [
            {"index": 1, "role": "START", "time_seconds": 0, "timed_visual_target": False, "description": None},
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 4,
             "timed_visual_target": False,
             "description": FACTS.replace("门在前景。", "门在前景。##STYLE## style, high quality, detailed。")},
            {"index": 3, "role": "END", "time_seconds": 8,
             "timed_visual_target": True,
             "description": FACTS.replace("门在前景。", f"门在前景，{STYLE_A} style, high quality, detailed。")},
        ],
        "window_plans": [{"window_index": 1, "selected_frame_count": 3, "keyframe_indexes": [1, 2, 3]}],
    }
    keyframes, _, _ = shot_api._normalize_keyframe_planner_result(
        raw, [{"window_index": 1, "start_time": 0, "end_time": 8}], 8, STYLE_A,
    )
    assert keyframes[0]["description"] == ""
    assert keyframes[1]["description"] == FACTS
    assert keyframes[2]["description"] == FACTS
    assert [item["timed_visual_target"] for item in keyframes] == [False, False, True]


def test_keyframe_planner_prompt_defines_timed_target_and_explicit_field():
    from pathlib import Path

    prompt = (Path(__file__).parents[1] / "prompt_templates" / "08_NovelFlow_VideoDirector_KeyframePlanner_V2_3Frame4Frame.txt").read_text()
    assert "timed_visual_target" in prompt
    assert "`timed_visual_target` 必须为 false；输出 true 会导致整份 #08 结果被拒绝" in prompt
    assert "不能仅因状态重要、是 END" in prompt


def test_keyframe_planner_prompt_defines_selective_timed_target_decision():
    from pathlib import Path

    prompt = (Path(__file__).parents[1] / "prompt_templates" / "08_NovelFlow_VideoDirector_KeyframePlanner_V2_3Frame4Frame.txt").read_text()
    assert "以下四项全部满足时" in prompt
    assert "true 仅表示 eligible，不表示 selected、必需图片或最终 temporal anchor" in prompt
    assert "不得判断未来 Previous AV 是否足够" in prompt
    assert "到达窗边并明确手持红色文件夹" in prompt
    assert "没有必须在该时间实现的精确构图" in prompt
    assert "不要把每个中间帧、每次位置变化、每次道具交互或每个 Clip 自动标记为 true" in prompt


@pytest.mark.parametrize("value", [None, "false", 0, 1])
def test_new_keyframe_plan_requires_boolean_timed_visual_target(value):
    raw = {
        "keyframes": [{"index": 1, "role": "START", "time_seconds": 0, "timed_visual_target": value}],
        "window_plans": [],
    }
    with pytest.raises(ValueError, match="timed_visual_target 必须是 boolean"):
        shot_api._normalize_keyframe_planner_result(raw, [], 8)


def test_new_keyframe_plan_rejects_timed_start_without_repair():
    raw = {
        "keyframes": [{"index": 1, "role": "START", "time_seconds": 0, "timed_visual_target": True}],
        "window_plans": [],
    }
    with pytest.raises(ValueError, match="START keyframe timed_visual_target 必须为 false"):
        shot_api._normalize_keyframe_planner_result(raw, [], 8)


@pytest.mark.parametrize("time_seconds", [float("nan"), float("inf"), -0.1, 9])
def test_new_timed_target_requires_finite_in_shot_time(time_seconds):
    raw = {
        "keyframes": [{"index": 2, "role": "INTERMEDIATE", "time_seconds": time_seconds, "timed_visual_target": True}],
        "window_plans": [],
    }
    with pytest.raises(ValueError, match="time_seconds 无效"):
        shot_api._normalize_keyframe_planner_result(raw, [], 8)


def test_new_keyframe_plan_rejects_duplicate_canonical_index():
    raw = {
        "keyframes": [
            {"index": 2, "role": "INTERMEDIATE", "time_seconds": 2, "timed_visual_target": False},
            {"index": 2, "role": "END", "time_seconds": 8, "timed_visual_target": False},
        ],
        "window_plans": [],
    }
    with pytest.raises(ValueError, match="重复 index"):
        shot_api._normalize_keyframe_planner_result(raw, [], 8)


@pytest.mark.asyncio
async def test_a_to_b_authority_in_storyboard_and_temporal_anchor(db_session, monkeypatch):
    style = PromptTemplate(name="style", type="style", template=STYLE_A)
    storyboard_template = PromptTemplate(name="shot image", type="shot_image_prompt", template="use visual_style", is_system=True)
    keyframe_template = PromptTemplate(name="KF image", type="keyframe_image_prompt", template="use visual_style", is_system=True)
    db_session.add_all([style, storyboard_template, keyframe_template])
    db_session.flush()
    novel = Novel(title="authority", style_prompt_template_id=style.id)
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="织房")
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description=FACTS, characters='["骗子1"]', props="[]", dialogues="[]")
    db_session.add(shot)
    db_session.commit()

    style.template = STYLE_B
    db_session.commit()
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return {"success": True, "content": f"最终图像提示词：{STYLE_B}"}

    fake_llm = SimpleNamespace(chat_completion=complete)
    storyboard_prompt, _ = await shot_api._resolve_shot_image_prompt_text(
        db_session, novel, shot, PromptTemplateRepository(db_session), fake_llm, None,
    )
    kf_service = ShotKeyframeService()
    kf_service.llm_service = fake_llm
    temporal_prompt = await kf_service._build_qwen_keyframe_prompt(
        db_session, novel, shot,
        {"index": 2, "description": FACTS, "prompt_text": STYLE_A},
        {"index": 1, "description": FACTS, "prompt_text": STYLE_A},
        SimpleNamespace(current_step=""), reference_manifest=[],
    )
    assert STYLE_B in storyboard_prompt and STYLE_B in temporal_prompt
    assert STYLE_A not in storyboard_prompt + temporal_prompt
    assert all(json.loads(call["user_content"].split("\n\n", 1)[1])["visual_style"] == STYLE_B for call in calls)
    assert all(STYLE_A not in call["user_content"] for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"])
async def test_h3_ignores_old_keyframe_prompt_after_style_change(db_session, monkeypatch, mode):
    style = PromptTemplate(name="style", type="style", template=STYLE_A)
    db_session.add(style)
    db_session.flush()
    novel = Novel(title="authority", style_prompt_template_id=style.id)
    db_session.add(novel)
    db_session.commit()
    style.template = STYLE_B
    db_session.commit()
    shot = SimpleNamespace(
        id="shot", index=1, chapter_id="chapter", description=FACTS,
        video_description="两人争执。", characters='["骗子1"]', scene="织房", props="[]", dialogues="[]",
        duration=4, continuity_mode="NORMAL", video_director_plan=None,
    )
    captured = {}

    class FakeLLM:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": "视频运动描述"}

    monkeypatch.setattr(video_director_ai, "LLMService", FakeLLM)
    monkeypatch.setattr(video_director_ai, "resolve_prompt_template", lambda *_: SimpleNamespace(template="system", name="H3"))
    output = await video_director_ai.build_h3_video_prompt(
        db=db_session, novel=novel, shot=shot, selected_mode=mode,
        clip={"clip_index": 1, "start_time": 0, "end_time": 4}, workflow_capability={},
        workflow_type="video", workflow_name="H3", start_image_url=None,
        keyframes=[{"index": 1, "description": FACTS, "prompt_text": STYLE_A}],
        transitions=[], clip_dialogues=[], reference_images=[],
    )
    payload = json.loads(captured["user_content"].split("\n\n", 1)[1])
    assert "visual_style" not in payload
    assert "prompt_text" not in payload["keyframes"][0]
    assert STYLE_A not in captured["user_content"]
    assert STYLE_A not in output
