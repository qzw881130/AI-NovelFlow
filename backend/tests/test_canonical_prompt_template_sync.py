from hashlib import sha256
from pathlib import Path

from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.services.prompt_template_service import PromptTemplateService
from app.services.video_director_ai import resolve_prompt_template


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompt_templates"
PLANNER_FILE = "08_NovelFlow_VideoDirector_KeyframePlanner_V2_3Frame4Frame.txt"
TRANSITION_FILE = "10_NovelFlow_KeyframeTransition_Planner_V1.txt"


def _prompt(filename: str) -> str:
    return (PROMPT_DIR / filename).read_text(encoding="utf-8")


def test_canonical_visual_planner_keeps_schema_and_mature_visual_rules():
    prompt = _prompt(PLANNER_FILE)

    for marker in (
        '"role": "START"',
        '"timed_visual_target": false',
        "至少输出一个状态",
        "time_seconds 必须严格递增",
        "END 可选",
        "Visual Beat Priority",
        "Speech-neutral Visual State",
        "WHAT IS VISIBLY TRUE AT THIS MOMENT",
        "speech-derived event 转换为 pose",
        "侍从2身体微微前倾，视线朝向皇帝",
        "皇帝眉头较前一状态舒展，神情趋于平和",
        "END = final visible state",
        "不是 final narrative event + visible state",
        "Whole-plan Speech-neutral Audit",
        "逐个重新检查全部 keyframes",
        "全部 states 必须共同通过",
        "Low Visual Delta",
        "Visible Narrative Coverage",
        "最后说话者构图",
    ):
        assert marker in prompt

    for legacy_marker in (
        "selected_mode",
        "recommended_mode",
        "window_plans",
        "execution_windows",
        "selected_frame_count",
        "workflow_key",
        "supported_frame_counts",
        "FIRST_LAST_FRAME",
        "MULTI_KEYFRAME",
    ):
        assert legacy_marker not in prompt


def test_transition_planner_keeps_adjacent_scope_and_isolates_speech_authority():
    prompt = _prompt(TRANSITION_FILE)

    for marker in (
        "根据相邻两个静态关键帧",
        "from_keyframe 是起点权威状态",
        "to_keyframe 是终点权威状态",
        "Current Segment Action Recovery",
        "from_keyframe.time_seconds 至 to_keyframe.time_seconds",
        "不得把其他 transition 的动作泄漏进当前 transition",
        "Speech Authority Isolation",
        "由后续 Clip dialogue timeline / H3 Prompt Builder 独占",
        '"from_keyframe_index": 1',
        '"to_keyframe_index": 2',
        '"start_time": 0',
        '"end_time": 8',
    ):
        assert marker in prompt

    for obsolete_speech_rule in (
        "speaking mouth state 只能由 dialogue_timeline_source",
        "允许自然说话视觉状态",
        "说话者保持面对目标",
        "持续讲话期间",
    ):
        assert obsolete_speech_rule not in prompt


def test_system_sync_updates_existing_rows_in_place_and_default_resolution(db_session):
    planner_id = "ee6d8619-1b93-4b7e-a68e-48c9a827b2d5"
    transition_id = "7f9d53a8-6ff6-4584-b2d4-703168175f25"
    db_session.add_all([
        PromptTemplate(
            id=planner_id,
            name="关键帧时间轴规划",
            description="stale",
            template="stale planner",
            type="keyframe_planner",
            is_system=True,
            is_active=True,
        ),
        PromptTemplate(
            id=transition_id,
            name="关键帧过渡规划",
            description="stale",
            template="stale transition",
            type="keyframe_transition",
            is_system=True,
            is_active=True,
        ),
    ])
    db_session.commit()

    PromptTemplateService(db_session).init_system_templates()
    novel = Novel(title="default prompt resolution")
    db_session.add(novel)
    db_session.flush()

    planner = resolve_prompt_template(
        db_session, novel, "keyframe_planner_prompt_template_id", "keyframe_planner"
    )
    transition = resolve_prompt_template(
        db_session, novel, "keyframe_transition_prompt_template_id", "keyframe_transition"
    )

    assert planner.id == planner_id
    assert planner.template == _prompt(PLANNER_FILE)
    assert transition.id == transition_id
    assert transition.template == _prompt(TRANSITION_FILE)


def test_unrelated_system_prompt_sources_remain_frozen():
    expected_hashes = {
        "06_NovelFlow_QwenEdit2511_ShotImagePrompt_V1.txt": "937f62ce9fbf9c25543abd9dca7b9d988eb770b878bfe1219f5d6095a2a296cd",
        "10A_NovelFlow_ClipExecutionPlanner_V1.txt": "a0c668afb2a881db7722ea65915ef12aa8a3a4f3c61ed65dabe03f3bad1ab908",
        "11_MiniMax_H3_SingleFrame_VideoPrompt_V1.txt": "52019d4ee11be55d703e292e099acf33e39e4bc58668c42ce74161e636ae270f",
        "12_MiniMax_H3_FirstLastFrame_VideoPrompt_V1.txt": "c2de7ce18528ecd7384859076414c96181e021a04077ed87bb494a826b8f62b6",
        "13_MiniMax_H3_MultiKeyframe_VideoPrompt_V1.txt": "93987dd6dd073b9e76a09e7798147d9f37083bcad275a2c885445489e85bfa54",
    }

    for filename, expected_hash in expected_hashes.items():
        assert sha256((PROMPT_DIR / filename).read_bytes()).hexdigest() == expected_hash
