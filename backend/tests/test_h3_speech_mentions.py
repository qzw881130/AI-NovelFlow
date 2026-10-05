"""Speech mentions versus events, with frozen C2/C4 outputs and no network calls."""
import json
from pathlib import Path

import pytest

from app.services import video_director_ai as h3
from test_canonical_h3_manifest_speech_authority import dialogue, invoke


ERROR = "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"


@pytest.mark.parametrize("mention", [
    "不得出现对话气泡。",
    "禁止字幕、文字和对白气泡。",
    "背景人物全程保持沉默，不得说话。",
    "除 canonical dialogue_timeline 指定角色外，其他人物不得新增对白。",
    "角色说话时保持自然中文口型。",
    "画面中不得出现字幕、标题、说明文字、对话气泡、标志或水印。",
    "No subtitles, captions or speech bubbles.",
    "不要显示字幕。禁止文字。背景人物不得说话。不要新增对白。",
    "metadata: lip-sync rules; follow canonical dialogue timing.",
])
@pytest.mark.parametrize("has_dialogue", [False, True])
def test_non_content_speech_mentions_pass_builder(monkeypatch, mention, has_dialogue):
    prompt, _, _, record = invoke(
        monkeypatch, states=[], body="summary:\n" + mention,
        dialogues=[dialogue()] if has_dialogue else [],
    )
    assert mention in prompt
    assert record["parsed_result"]["dialogue"]["passed"]
    assert prompt.count("exact_dialogue: 请看这里。") == int(has_dialogue)
    if not has_dialogue:
        assert "NO_VOICE: no human speech" in prompt


def test_exact_canonical_reference_keeps_existing_id_projection(monkeypatch):
    text = "我们是从遥远国度来的布商。"
    prompt, _, _, record = invoke(
        monkeypatch, states=[], body=f"summary:\n遵循已分配的“{text}”时间线。",
        dialogues=[dialogue("Mira", text)],
    )
    assert "遵循已分配的assigned dialogue D1时间线。" in prompt
    assert prompt.count(text) == 1
    assert record["parsed_result"]["dialogue"]["passed"]


@pytest.mark.parametrize("field", ["summary", "camera", "overall_soundscape", "action"])
@pytest.mark.parametrize("event,assigned", [
    ('Mira说：“快让我们进去。”', [dialogue()]),
    ('Mira：“我们是来自法国的布商。”', [dialogue("Mira", "我们是布商。")]),
    ('Jun说：“我们是布商。”', [dialogue("Mira", "我们是布商。")]),
    ('卫兵低声说道：“请稍等。”', []),
    ('卫兵转身并喊道“快来人”。', []),
])
def test_new_rewritten_or_reassigned_speech_fails_all_body_fields(monkeypatch, field, event, assigned):
    with pytest.raises(RuntimeError, match=ERROR):
        invoke(monkeypatch, states=[], body=f"{field}:\n{event}", dialogues=assigned)


@pytest.mark.parametrize("body", [
    "禁止字幕、对话气泡，但Mira说：“快让我们进去。”",
    "角色说话时保持自然中文口型，Jun回答。",
    "角色说话时保持自然中文口型，卫兵转身并喊道“快来人”。",
    "不新增对白。Mira：“快让我们进去。”",
    "画面中的对话气泡消失，<Subject 2> speaks invented words.",
    "Mira说assigned dialogue D1。",
    "Jun：assigned dialogue D1。",
    'lip-sync instructions: Jun说：“快让我们进去。”',
    "<Subject 1> lip-syncs to invented words.",
])
def test_safe_mention_never_masks_event_or_speaker_assignment(monkeypatch, body):
    with pytest.raises(RuntimeError, match=ERROR):
        invoke(monkeypatch, states=[], body="summary:\n" + body, dialogues=[dialogue()])


HISTORY = json.loads((Path(__file__).parent / "fixtures/h3_speech_mention_history.json").read_text())


@pytest.mark.parametrize("case", HISTORY, ids=lambda case: case["clip"])
def test_failed_historical_body_passes_exact_production_projection(case):
    body = h3._remove_canonical_h3_internal_self_check(case["body"])
    body = h3._remove_generated_dialogue_timeline(body)
    body = h3._project_canonical_soundscape(body)
    subjects = h3._subject_bindings(body, case["characters"])
    body = h3._remove_dialogue_text_from_builder_body(body, case["dialogues"])
    timeline = h3._render_dialogue_timeline_block(case["dialogues"], case["silent_characters"], subjects)
    prompt = h3._insert_canonical_dialogue_timeline(body, timeline)
    audit = h3._audit_final_h3_prompt(
        prompt, case["dialogues"], case["silent_characters"], subjects,
        canonical_visual_body=body,
    )
    assert audit["passed"], audit
    assert prompt.count("dialogue_timeline:") == 1
    for item in case["dialogues"]:
        assert prompt.count(h3._exact_spoken_text(item["text"])) == 1


@pytest.mark.parametrize("case", HISTORY, ids=lambda case: case["clip"])
def test_historical_negative_list_cannot_authorize_new_speech(case):
    assert ERROR in h3._canonical_visual_body_speech_issues(
        case["body"] + '\naction:\n卫兵转身并喊道“快来人”。',
        {name: f"<Subject {i}>" for i, name in enumerate(case["characters"], 1)},
    )
