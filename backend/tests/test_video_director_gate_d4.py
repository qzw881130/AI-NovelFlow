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


def test_h3_prompt_builder_blocks_unknown_subject_before_submit(db_session, monkeypatch):
    novel = Novel(title="Gate D4")
    db_session.add(novel)
    db_session.commit()
    db_session.refresh(novel)
    chapter = Chapter(novel_id=novel.id, number=1, title="Chapter", content="content")
    db_session.add(chapter)
    db_session.commit()
    db_session.refresh(chapter)
    shot = Shot(
        chapter_id=chapter.id,
        index=1,
        description="Shot",
        characters=json.dumps(["小马"], ensure_ascii=False),
        props="[]",
        duration=4,
    )
    template = PromptTemplate(
        name="H3 Single",
        type="h3_single_frame_prompt",
        template="build h3",
        is_system=True,
    )
    db_session.add_all([shot, template])
    db_session.commit()

    class FakeLLM:
        async def chat_completion(self, **_kwargs):
            return {"success": True, "content": "<Subject 3> talks to camera."}

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
            start_image_url="/api/files/shot.png",
            keyframes=[],
            transitions=[],
            clip_dialogues=[],
            reference_images=[],
            character_appearances={"小马": "pony"},
            speaker_timeline=[{"start_time": 0, "end_time": 2, "visible_speaker": "小马"}],
            audio_drive_context={"audio_mode": "lock_source"},
        ))

    assert "UNKNOWN_SUBJECT_REFERENCE" in str(exc_info.value)
