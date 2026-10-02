from hashlib import sha256
from pathlib import Path

from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.services.prompt_template_service import PromptTemplateService
from app.services.video_director_ai import resolve_prompt_template


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompt_templates"
PLANNER_FILE = "08_NovelFlow_VideoDirector_KeyframePlanner_V2_3Frame4Frame.txt"
KEYFRAME_IMAGE_FILE = "09_NovelFlow_QwenEdit2511_KeyframeImagePrompt_V1.txt"
TRANSITION_FILE = "10_NovelFlow_KeyframeTransition_Planner_V1.txt"
CLIP_PLANNER_FILE = "10A_NovelFlow_ClipExecutionPlanner_V1.txt"


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
        "canonical START 可以为 null/empty",
        "不得读取或推断 raw shot.description、shot.video_description、dialogue、speaker 或 timeline",
        "只能使用当前输入明确提供的 canonical visual facts 与结构化视觉上下文",
        "不得通过 raw shot.description、shot.video_description 或 dialogue 恢复",
        "Speech Authority Isolation",
        "由后续 Clip dialogue timeline / H3 Prompt Builder 独占",
        '"from_keyframe_index": 1',
        '"to_keyframe_index": 2',
        '"start_time": 0',
        '"end_time": 8',
    ):
        assert marker in prompt

    for obsolete_speech_rule in (
        "START 若由程序引用 shot.description",
        "必须同时参考 shot.video_description",
        "当前 Segment 的 dialogue timeline 只能用于理解",
        "speaking mouth state 只能由 dialogue_timeline_source",
        "允许自然说话视觉状态",
        "说话者保持面对目标",
        "持续讲话期间",
    ):
        assert obsolete_speech_rule not in prompt


def test_keyframe_image_prompt_keeps_visual_state_authority_and_no_dialogue_mouth_rules():
    prompt = _prompt(KEYFRAME_IMAGE_FILE)

    for marker in (
        "当前 canonical Visual State 静态 description",
        "shot 不提供 raw description、video_description、dialogues、speaker 或 dialogue",
        "#09 只负责把",
        "current_keyframe.description 已明确给出的可见事实实现为画面",
        "不得从其缺失与否推断任何人物正在说话、正在倾听",
        "参考图片只负责人物身份、当前外观、场景、道具和纯视觉连续性",
        "嘴角略向下",
        "咬紧牙关",
    ):
        assert marker in prompt

    for obsolete_dialogue_rule in (
        "shot.dialogues == []",
        "当 dialogues 非空",
        "人物嘴部保持自然闭合或自然静态表情",
        "禁止明显正在讲话的夸张口型",
        "第一版不根据台词自行猜测精确嘴型",
    ):
        assert obsolete_dialogue_rule not in prompt


def test_clip_planner_separates_boundary_hints_from_visual_continuity_authority():
    prompt = _prompt(CLIP_PLANNER_FILE)

    for marker in (
        "speech_timing_intervals",
        "boundary hints, not dialogue content, speaker authority, or continuity authority",
        "Boundary selection and continuity classification are two separate decisions",
        "depends on the actual ending visual state",
        "independently establish its start",
        "Narrative continuity is not visual",
        "must not coerce a visually independent boundary from CUT to CONTINUOUS",
        "carry_in_state_index` as semantic context only",
        "Do not cite dialogue/story continuity as the reason for CONTINUOUS",
        "Do not select or number Pictures",
    ):
        assert marker in prompt

    for legacy_or_wrong_authority in (
        "Prefer natural narrative Beats",
        "every later Clip must be `CONTINUOUS`",
        "SINGLE_FRAME",
        "FIRST_LAST_FRAME",
        "MULTI_KEYFRAME",
        '"capability":',
        '"dialogue_scope":',
    ):
        assert legacy_or_wrong_authority not in prompt


def test_system_sync_updates_existing_rows_in_place_and_default_resolution(db_session):
    planner_id = "ee6d8619-1b93-4b7e-a68e-48c9a827b2d5"
    keyframe_image_id = "276f0181-64c4-4a03-b0fd-b9b9b1f04a09"
    transition_id = "7f9d53a8-6ff6-4584-b2d4-703168175f25"
    clip_planner_id = "b8553cb9-bf01-4a86-8f47-3aedbfc1c0b0"
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
            id=keyframe_image_id,
            name="视频关键帧生图提示词构建",
            description="stale",
            template="stale keyframe image prompt",
            type="keyframe_image_prompt",
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
        PromptTemplate(
            id=clip_planner_id,
            name="Clip Execution Planner",
            description="stale",
            template="stale clip planner",
            type="clip_execution_planner",
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
    keyframe_image = resolve_prompt_template(
        db_session, novel, "keyframe_image_prompt_template_id", "keyframe_image_prompt"
    )
    transition = resolve_prompt_template(
        db_session, novel, "keyframe_transition_prompt_template_id", "keyframe_transition"
    )
    clip_planner = PromptTemplateService(db_session).get_default_system_template("clip_execution_planner")

    assert planner.id == planner_id
    assert planner.template == _prompt(PLANNER_FILE)
    assert keyframe_image.id == keyframe_image_id
    assert keyframe_image.template == _prompt(KEYFRAME_IMAGE_FILE)
    assert transition.id == transition_id
    assert transition.template == _prompt(TRANSITION_FILE)
    assert clip_planner.id == clip_planner_id
    assert clip_planner.template == _prompt(CLIP_PLANNER_FILE)


def test_unrelated_system_prompt_sources_remain_frozen():
    expected_hashes = {
        "06_NovelFlow_QwenEdit2511_ShotImagePrompt_V1.txt": "937f62ce9fbf9c25543abd9dca7b9d988eb770b878bfe1219f5d6095a2a296cd",
        "11_MiniMax_H3_SingleFrame_VideoPrompt_V1.txt": "52019d4ee11be55d703e292e099acf33e39e4bc58668c42ce74161e636ae270f",
        "12_MiniMax_H3_FirstLastFrame_VideoPrompt_V1.txt": "c2de7ce18528ecd7384859076414c96181e021a04077ed87bb494a826b8f62b6",
        "13_MiniMax_H3_MultiKeyframe_VideoPrompt_V1.txt": "93987dd6dd073b9e76a09e7798147d9f37083bcad275a2c885445489e85bfa54",
    }

    for filename, expected_hash in expected_hashes.items():
        assert sha256((PROMPT_DIR / filename).read_bytes()).hexdigest() == expected_hash
