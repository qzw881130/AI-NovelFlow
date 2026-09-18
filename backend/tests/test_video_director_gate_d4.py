import json
from pathlib import Path

import pytest

from app.models.novel import Chapter, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.services.video_director_ai import (
    _apply_audio_text_rendering_constraint,
    _extract_audio_text_rendering_constraint,
    audit_audiodrive_h3_prompt,
    build_clip_subject_manifest,
    build_h3_video_prompt,
    resolve_speaker_timeline_for_h3,
)
from test_rsa_media import db_session, chapter, fixture, base_setup, setup


AUDIO_TEXT_RENDERING_CONSTRAINT_FIXTURE = """The input drive_audio is provided only for visible lip-sync, speech timing, facial performance, and speaking rhythm.
Never transcribe drive_audio.
Never transcribe, display, visualize, quote, or render any spoken content from drive_audio or final_audio as text.
Spoken audio must remain audio only.
Do not generate subtitles, captions, dialogue text, speech bubbles, karaoke text, transcription, Chinese characters, English text, or any readable on-screen text derived from the audio.
The video must contain no subtitles, no captions, and no audio transcription."""


def _shot(characters):
    return Shot(index=1, characters=json.dumps(characters, ensure_ascii=False), duration=10)


def _clip(duration=10):
    return {"clip_index": 1, "start_time": 0, "end_time": duration}


def _resolve(characters, timeline):
    manifest = build_clip_subject_manifest(_shot(characters), timeline)
    resolved, issues = resolve_speaker_timeline_for_h3(timeline, manifest, _clip())
    return manifest, resolved, issues


def _prompt(body: str) -> str:
    return f"{body}\n\n{AUDIO_TEXT_RENDERING_CONSTRAINT_FIXTURE}"


def test_single_speaker_resolves_to_subject_1():
    _manifest, resolved, issues = _resolve(["小马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
    ])

    assert issues == []
    assert resolved[0]["visible_speaker"] == "<Subject 1>"


def test_speaker_resolution_prefers_character_id_over_name():
    shot = _shot(["小马", "母马"])
    manifest = build_clip_subject_manifest(
        shot,
        [],
        character_refs={"小马": {"id": "char-a"}, "母马": {"id": "char-b"}},
    )

    resolved, issues = resolve_speaker_timeline_for_h3([
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马", "visible_speaker_character_id": "char-b"},
    ], manifest, _clip())

    assert issues == []
    assert resolved[0]["visible_speaker"] == "<Subject 2>"


def test_a_to_b_resolves_to_subject_1_then_subject_2():
    _manifest, resolved, issues = _resolve(["小马", "母马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
        {"start_time": 2, "end_time": 4, "visible_speaker": "母马"},
    ])

    assert issues == []
    assert [item["visible_speaker"] for item in resolved] == ["<Subject 1>", "<Subject 2>"]


def test_a_to_b_to_a_resolves_back_to_same_subject():
    _manifest, resolved, issues = _resolve(["小马", "母马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
        {"start_time": 2, "end_time": 4, "visible_speaker": "母马"},
        {"start_time": 4, "end_time": 6, "visible_speaker": "小马"},
    ])

    assert issues == []
    assert [item["visible_speaker"] for item in resolved] == ["<Subject 1>", "<Subject 2>", "<Subject 1>"]


def test_unmanifested_speaker_fails_resolution():
    _manifest, _resolved, issues = _resolve(["小马", "母马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
        {"start_time": 2, "end_time": 4, "visible_speaker": "母马"},
        {"start_time": 4, "end_time": 6, "visible_speaker": "牛伯"},
    ])

    assert any(issue["code"] == "UNRESOLVED_VISIBLE_SPEAKER" for issue in issues)


@pytest.mark.parametrize("event_type", ["NARRATION", "INNER_MONOLOGUE", "OFFSCREEN_DIALOGUE"])
def test_non_visible_audio_semantics_must_be_none(event_type):
    manifest, resolved, issues = _resolve(["小马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "NONE", "event_type": event_type},
    ])

    audit = audit_audiodrive_h3_prompt(_prompt("speaker_timeline: visible_speaker=NONE"), resolved, manifest, issues)
    assert resolved[0]["visible_speaker"] == "NONE"
    assert audit["passed"] is True


@pytest.mark.parametrize("event_type", ["NARRATION", "INNER_MONOLOGUE", "OFFSCREEN_DIALOGUE"])
def test_non_visible_audio_semantics_cannot_map_to_subject(event_type):
    _manifest, _resolved, issues = _resolve(["小马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马", "event_type": event_type},
    ])

    assert any(issue["code"] == "INVALID_AUDIO_SPEAKER_SEMANTICS" for issue in issues)


def test_invalid_timeline_fails_audit():
    manifest, resolved, issues = _resolve(["小马"], [
        {"start_time": 3, "end_time": 2, "visible_speaker": "小马"},
    ])

    audit = audit_audiodrive_h3_prompt(_prompt(""), resolved, manifest, issues)
    assert audit["passed"] is False
    assert any(issue["code"] == "INVALID_SPEAKER_TIMELINE" for issue in audit["issues"])


def test_none_segment_prompt_contradiction_fails_audit():
    manifest, resolved, issues = _resolve(["小马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "NONE"},
    ])

    audit = audit_audiodrive_h3_prompt(_prompt("During NONE, <Subject 1> lip-syncs clearly."), resolved, manifest, issues)
    assert audit["passed"] is False
    assert any(issue["code"] == "NONE_SEGMENT_LIPSYNC_CONTRADICTION" for issue in audit["issues"])


def test_none_segment_no_lipsync_rule_passes_audit():
    manifest, resolved, issues = _resolve(["小马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "NONE"},
    ])

    audit = audit_audiodrive_h3_prompt(
        _prompt("visible_speaker=NONE: All visible characters remain silent with no lip-sync."),
        resolved,
        manifest,
        issues,
    )

    assert audit["passed"] is True
    assert not any(issue["code"] == "NONE_SEGMENT_LIPSYNC_CONTRADICTION" for issue in audit["issues"])


def test_shot119_clip2_exact_none_output_passes_audit():
    # LLM log 105035bb-ddf0-4097-b042-2746e38c8f35, 2026-09-06 01:42:54.
    body = """dialogue_timeline:

All visible characters remain silent and do not perform speech lip-sync throughout the entire clip.

详细可见说话者时间轴：0.000s–14.977s，visible_speaker = NONE，整段无任何人产生说话口型。
"""
    manifest = build_clip_subject_manifest(_shot(["小马"]), [])
    timeline = [{"start_time": 0.0, "end_time": 14.977, "visible_speaker": "NONE"}]

    audit = audit_audiodrive_h3_prompt(_prompt(body), timeline, manifest)

    assert audit["passed"] is True, audit["issues"]


@pytest.mark.parametrize("body", [
    "visible_speaker=NONE，画面无可说话人物。",
    "visible_speaker=NONE，小马不说话，不张嘴，不产生口型。",
    "NONE: <Subject 1> is completely silent and does not speak.",
    "NONE. <Subject2> closes her mouth.",
    "NONE: <Subject 1> must remain silent, with no lip-sync; 2s-4s: <Subject 1> speaks.",
    "0.0s-2.0s visible_speaker=NONE，嘴巴闭合。2.0s-4.0s <Subject 1> 张嘴说话。",
    "0s-2s NONE: <Subject 1> is silent, 2s-4s <Subject 1> lip-syncs.",
    "NONE: no lip-sync, visible_speaker=<Subject 1>: speaks.",
    "NONE: <Subject 1> does not speak and never lip-syncs.",
    "NONE期间，小马不张嘴说话，禁止任何人物产生口型。",
    "NONE，整段无任何人产生说话口型。",
    "NONE，没有任何人物产生讲话口型。",
    "NONE，禁止任何角色做发声口型。",
    "NONE，无人说话。",
    "NONE，不允许任何人张嘴说话。",
    "NONE，小马不产生说话口型，不做讲话口型。",
    "NONE，无任何可见人物产生说话口型。",
    "NONE，无可见角色做说话口型。",
    "visible_speaker = NONE. All characters remain silent; none of the visible characters produces any lip-sync or talking mouth shape at any moment, including when narration audio is heard.",
    "NONE: none of the visible characters produces any lip-sync or talking mouth shape at any moment.",
    "NONE. No visible character performs lip-sync at any time.",
    "NONE. No visible characters produce any speech or lip-sync.",
    "NONE. Any voiced audio present in the final audio is off-screen non-lip-sync content and must not move any visible character's mouth.",
])
def test_none_segment_negated_and_scoped_speech_passes(body):
    manifest, resolved, issues = _resolve(["小马", "老牛"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "NONE"},
        {"start_time": 2, "end_time": 4, "visible_speaker": "小马"},
    ])

    audit = audit_audiodrive_h3_prompt(_prompt(body + "\nSubject manifest: <Subject 1>"), resolved, manifest, issues)

    assert audit["passed"] is True, audit["issues"]


@pytest.mark.parametrize("body", [
    "visible_speaker=NONE，小马不说话，但老牛张嘴说话。",
    "NONE: <Subject 1> does not speak, but <Subject 2> speaks.",
    "NONE: <Subject 1> stays silent while <Subject 2> lip-syncs.",
    "NONE. <Subject2> closes her mouth, but <Subject 1> lip-syncs.",
    "NONE，小马不得张嘴，老牛产生口型。",
    "NONE: no lip-sync, but <Subject 1> talks.",
    "0s-2s NONE: <Subject 1> speaks; 2s-4s <Subject 1> stays silent.",
    "NONE期间，小马不张嘴说话，但老牛张嘴说话。",
    "NONE，整段无任何人产生说话口型，但小马张嘴说话。",
    "NONE，小马说话，但其他人不产生说话口型。",
    "NONE，无任何人产生说话口型，<Subject 1> lip-syncs.",
    "NONE，无任何人产生说话口型，老牛做讲话口型。",
    "NONE，无任何人产生说话口型，老牛产生口型。",
    "NONE，没有字幕，小马产生说话口型。",
    "NONE，小马不走动而是说话。",
    "NONE，无任何人阻止小马说话。",
    "NONE，小马不仅说话，还张嘴。",
    "NONE，小马产生说话口型。",
    "NONE，小马做发声口型。",
    "NONE: none of the visible characters produces any lip-sync or talking mouth shape, but <Subject 1> lip-syncs.",
    "none: none of the visible characters produces any lip-sync or talking mouth shape, but <Subject 1> speaks.",
    "none of the visible characters produces any lip-sync or talking mouth shape; visible_speaker=NONE: <Subject 1> speaks.",
    "NONE. No visible character performs lip-sync, but <Subject 1> speaks.",
    "NONE. No visible characters produce speech or lip-sync, but <Subject 1> lip-syncs.",
    "NONE. The narration is non-lip-sync content, but <Subject 1> lip-syncs.",
])
def test_none_segment_mixed_negation_still_blocks_speech(body):
    manifest, resolved, issues = _resolve(["小马", "老牛"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "NONE"},
    ])

    audit = audit_audiodrive_h3_prompt(_prompt(body), resolved, manifest, issues)

    assert audit["passed"] is False
    assert [issue["code"] for issue in audit["blocking_issues"]] == ["NONE_SEGMENT_LIPSYNC_CONTRADICTION"]


def test_dialogue_text_leakage_fails_audit():
    manifest, resolved, issues = _resolve(["小马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
    ])

    audit = audit_audiodrive_h3_prompt(_prompt("<Subject 1> says 你好妈妈"), resolved, manifest, issues, dialogue_texts=["你好妈妈"])
    assert audit["passed"] is False
    assert any(issue["code"] == "DIALOGUE_TEXT_LEAKAGE" for issue in audit["issues"])


def test_unknown_subject_reference_fails_audit():
    manifest, resolved, issues = _resolve(["小马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
    ])

    audit = audit_audiodrive_h3_prompt(_prompt("<Subject 1> watches. <Subject 3> enters and talks."), resolved, manifest, issues)
    assert audit["passed"] is False
    assert any(issue["code"] == "UNKNOWN_SUBJECT_REFERENCE" for issue in audit["issues"])


def test_missing_audio_text_rendering_constraint_fails_audit():
    manifest, resolved, issues = _resolve(["小马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
    ])

    audit = audit_audiodrive_h3_prompt("speaker_timeline: <Subject 1> lip-syncs", resolved, manifest, issues)

    assert audit["passed"] is False
    assert any(issue["code"] == "MISSING_AUDIO_TEXT_RENDERING_CONSTRAINT" for issue in audit["issues"])


def test_template_constraint_is_applied_when_successful_llm_output_omits_it():
    template = f"""H3 template
━━━━━━━━━━━━━━━━━━
【Audio Drive 文本渲染禁令】
━━━━━━━━━━━━━━━━━━
{AUDIO_TEXT_RENDERING_CONSTRAINT_FIXTURE}
━━━━━━━━━━━━━━━━━━
【输出】
"""

    constraint = _extract_audio_text_rendering_constraint(template)
    final_prompt = _apply_audio_text_rendering_constraint("speaker_timeline: <Subject 1> lip-syncs", constraint)
    manifest, resolved, issues = _resolve(["小马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
    ])
    audit = audit_audiodrive_h3_prompt(final_prompt, resolved, manifest, issues)

    assert constraint == AUDIO_TEXT_RENDERING_CONSTRAINT_FIXTURE
    assert final_prompt.count(AUDIO_TEXT_RENDERING_CONSTRAINT_FIXTURE) == 1
    assert audit["passed"] is True


@pytest.mark.parametrize("template_filename", [
    "11_MiniMax_H3_SingleFrame_VideoPrompt_V1.txt",
    "12_MiniMax_H3_FirstLastFrame_VideoPrompt_V1.txt",
    "13_MiniMax_H3_MultiKeyframe_VideoPrompt_V1.txt",
])
def test_system_h3_templates_include_audio_text_rendering_constraint(template_filename):
    manifest, resolved, issues = _resolve(["小马", "母马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
    ])
    template_path = Path(__file__).resolve().parents[1] / "prompt_templates" / template_filename
    template_text = template_path.read_text(encoding="utf-8")

    audit = audit_audiodrive_h3_prompt(f"speaker_timeline: <Subject 1> lip-syncs\n\n{template_text}", resolved, manifest, issues)

    assert audit["passed"] is True


def test_subject_slot_is_resolved_from_current_manifest_each_time():
    _old_manifest, old_resolved, old_issues = _resolve(["小马", "母马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
    ])
    _new_manifest, new_resolved, new_issues = _resolve(["母马", "小马"], [
        {"start_time": 0, "end_time": 2, "visible_speaker": "小马"},
    ])

    assert old_issues == []
    assert new_issues == []
    assert old_resolved[0]["visible_speaker"] == "<Subject 1>"
    assert new_resolved[0]["visible_speaker"] == "<Subject 2>"


def test_h3_prompt_builder_blocks_unknown_subject_before_submit(db_session, setup, monkeypatch):
    # Exercise the H3 gate after real ChapterScope/Source/Treatment/RSA admission.
    # A bare legacy Shot fails earlier and cannot prove unknown-subject validation.
    actor, _scene, _appearance, shots, _root, _rsa = setup
    shot = shots[0]
    chapter = db_session.get(Chapter, shot.chapter_id)
    novel = db_session.get(Novel, chapter.novel_id)
    template = PromptTemplate(
        name="H3 Single",
        type="h3_single_frame_prompt",
        template="build h3",
        is_system=True,
    )
    db_session.add(template)
    db_session.commit()

    calls = []
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "content": "\n\n".join([
                "subject_definitions:\n<Subject 3> is 刘备.",
                "initial_state_anchor:\n刘备 stands in the peach garden.",
                "summary:\n<Subject 3> talks to camera.",
                "detailed_description:\nHold the camera steady while <Subject 3> speaks.",
                "overall_soundscape:\nThe pony's voice and quiet river ambience.",
            ])}

    monkeypatch.setattr("app.services.video_director_ai.LLMService", FakeLLM)

    with pytest.raises(RuntimeError) as exc_info:
        import asyncio
        asyncio.run(build_h3_video_prompt(
            db=db_session,
            novel=novel,
            shot=shot,
            selected_mode="SINGLE_FRAME",
            clip={"clip_index": 1, "start_time": 0, "end_time": 4},
            workflow_capability={"max_clip_duration": 15},
            workflow_type="video",
            workflow_name="video",
            start_image_url=actor.image_url,
            keyframes=[],
            transitions=[],
            clip_dialogues=[],
            reference_images=[],
            character_appearances={actor.name: actor.appearance},
            speaker_timeline=[{"start_time": 0, "end_time": 2, "visible_speaker": actor.name}],
            audio_drive_context={"audio_mode": "lock_source"},
        ))

    assert "UNKNOWN_SUBJECT_REFERENCE" in str(exc_info.value)
    assert len(calls) == 1
    user_content = calls[0]["user_content"]
    assert "subject_manifest.subjects 是合法 <Subject N> 标记的穷尽清单" in user_content
    assert "场景和道具必须按名称引用，绝不能为其创建或分配 <Subject N>" in user_content
