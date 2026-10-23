"""Offline authority compilation; no model, media, tracking or product DB calls."""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from app.services import video_director_ai as h3
from app.services.clip_execution_compiler import compile_temporal_extend_clip


def state(index=4, time=14):
    return {"index": index, "time_seconds": time, "role": "INTERMEDIATE", "description":
            "Scene: room\nCharacters:\n- Jun: holds the box beside the window.\n- Mira: wears a purple coat at the doorway.\n- Ivo: stays behind Jun.\nAction: Jun raises a hand."}


def manifest(generate=False):
    resources = [("SCENE", "Room", "room-id"), ("CHARACTER_IDENTITY", "Mira", "mira-id"),
                 ("CHARACTER_IDENTITY", "Jun", "jun-id"), ("PROP", "Box", "box-id")]
    refs = [{"kind": kind, "source_id": asset_id, "source_name": name,
             "source_identity": {"asset_id": asset_id, "name": name}, "image_url": f"/{asset_id}.png"}
            for kind, name, asset_id in resources]
    if generate:
        refs.insert(0, {"kind": "DIRECTOR_VISUAL_ANCHOR", "source_type": "KEYFRAME_IMAGE", "source_keyframe_index": 4, "image_url": "/state.png"})
    return {"version": 1, "references": [{**ref, "slot": i} for i, ref in enumerate(refs, 1)]}


def compile_binding(capability="EXTEND", text="Mira walks from the doorway toward Jun.", current=True):
    source = manifest(capability == "GENERATE")
    visible = h3._clip_visible_characters([state()], ["unrelated"])
    return h3.compile_h3_reference_bindings(
        h3.build_physical_picture_mapping(source), h3._subject_bindings("", visible), [state()],
        [{"from_keyframe_index": 3, "to_keyframe_index": 4, "transition_description": text}],
        capability=capability, previous_av_present=capability != "GENERATE",
        current_visual_state=state(3, 10) if current else None)


@pytest.mark.parametrize("capability,picture", [("GENERATE", "<Picture 3>"), ("EXTEND", "<Picture 2>"), ("TEMPORAL_EXTEND", "<Picture 2>")])
def test_dynamic_picture_asset_subject_binding(capability, picture):
    binding = compile_binding(capability)
    mira, jun = binding["characters"]
    assert (mira["picture"], mira["asset_id"], mira["name"], mira["subject"]) == (picture, "mira-id", "Mira", "<Subject 2>")
    assert jun["subject"] == "<Subject 1>"
    assert binding == compile_binding(capability)
    assert all("subject" not in item for item in binding["resources"])


def test_identity_only_preserves_current_state_and_resource_authorities():
    prompt = h3.render_h3_reference_bindings(compile_binding())
    for item in ("clothing", "pose", "position", "portrait background", "incidental props", "prop ownership"):
        assert item in prompt
    assert "stable face, age, facial structure, hair and personal identity only" in prompt
    assert "incidental people are not additional Subjects" in prompt
    assert "current canonical state decides who owns/holds it and where it is" in prompt
    assert "only, exclusively for this Subject" in prompt


@pytest.mark.parametrize("capability", ["EXTEND", "TEMPORAL_EXTEND"])
def test_current_body_joins_carry_role_without_portrait_state_reset(capability):
    binding = compile_binding(capability)
    mira = binding["characters"][0]
    assert mira["body_state_id"] == "KF3"
    assert mira["body_role"] == "wears a purple coat at the doorway."
    assert mira["body_binding"] == "EXISTING_CURRENT_BODY"
    prompt = h3.render_h3_reference_bindings(binding)
    assert "Previous AV and canonical KF3" in prompt
    assert "Do not create a second body or transfer this identity to another visible body" in prompt
    initial = h3.render_h3_reference_bindings(compile_binding("GENERATE"))
    assert "existing_body_binding:" not in initial
    assert "initial_body_binding:" in initial
    assert "no Previous AV body is assumed" in initial


def test_missing_portrait_keeps_subject_and_no_phantom_picture():
    binding = compile_binding()
    assert binding["subjects"]["Ivo"] == "<Subject 3>"
    assert not any(x["name"] == "Ivo" for x in binding["characters"])
    prompt = h3.render_h3_reference_bindings(binding)
    assert "<Subject 3> — Ivo: LOCAL_MOTION / SPATIALLY_ANCHORED" in prompt
    assert "<Picture 5>" not in prompt


def test_no_pictures_still_preserves_canonical_subject_motion_without_phantom_binding():
    binding = h3.compile_h3_reference_bindings(
        [], h3._subject_bindings("", ["Jun", "Mira"]), [state()],
        [{"transition_description": "Mira walks toward Jun."}],
        capability="EXTEND", previous_av_present=True, current_visual_state=state(3))
    prompt = h3.render_h3_reference_bindings(binding)
    assert "<Subject 2> — Mira: TRANSLATIONAL_MOTION" in prompt
    assert "<Subject 1> — Jun: LOCAL_MOTION / SPATIALLY_ANCHORED" in prompt
    assert "<Picture" not in prompt
    assert "character_identity_binding:" not in prompt
    assert "existing_body_binding:" not in prompt


def test_unknown_current_body_does_not_invent_presence_or_position():
    binding = compile_binding(current=False)
    assert all(x["body_binding"] == "CANONICAL_BODY_PRESENCE_UNKNOWN" and x["body_role"] is None for x in binding["characters"])
    assert any(x["code"] == "CURRENT_BODY_STATE_UNAVAILABLE" for x in binding["findings"])
    assert "existing or explicitly entering" in h3.render_h3_reference_bindings(binding)


@pytest.mark.parametrize("text,owner", [
    ("Mira walks toward Jun. Jun turns his head.", "Mira"),
    ("Mira从门口进入并走向Jun。Jun保持在镜子旁。", "Mira"),
    ("<Subject 2> crosses the room. Jun raises a hand.", "Mira"),
    ("Mira不改变站位，Jun不移动站位。", None),
    ("Mira does not walk toward Jun. Ivo stays behind Jun.", None),
    ("Mira已走向Jun并站定。", None),
    ("Mira's hand moves toward Jun. Jun turns his head.", None),
    ("The camera approaches Mira and Jun. Mira breathes.", None),
    ("Miranda walks toward Jun. Mira stays beside the window.", None),
])
def test_motion_owner_is_explicit_actor_not_target_camera_or_local_body_part(text, owner):
    items = compile_binding(text=text)["motion_ownership"]
    assert [x["name"] for x in items if x["motion_class"] == "TRANSLATIONAL_MOTION"] == ([owner] if owner else [])
    assert all(x["evidence"] for x in items if x["name"] == owner)
    assert "does not freeze a person" in h3.render_h3_reference_bindings(compile_binding(text=text))


def test_canonical_state_action_can_authorize_explicit_motion():
    current = state()
    current["description"] = current["description"].replace("Action: Jun raises a hand.", "Action: Mira enters the room.")
    binding = h3.compile_h3_reference_bindings(h3.build_physical_picture_mapping(manifest()), h3._subject_bindings("", ["Jun", "Mira", "Ivo"]), [current], [], capability="GENERATE", previous_av_present=False)
    assert binding["motion_ownership"][1]["motion_class"] == "TRANSLATIONAL_MOTION"


@pytest.mark.parametrize("text", ["Jun watches Mira walk toward the doorway.", "Jun看着Mira走向门口。", "Mira and Jun enter the room."])
def test_ambiguous_actor_clause_records_finding_without_assigning_an_observers_motion(text):
    binding = compile_binding(text=text)
    assert not any(x["motion_class"] == "TRANSLATIONAL_MOTION" for x in binding["motion_ownership"])
    assert any(x["code"] == "MOTION_OWNER_AMBIGUOUS" for x in binding["findings"])


def test_phase1_manifest_and_temporal_frame293_remain_unchanged():
    shot = SimpleNamespace(id="preserved", duration=68)
    clip = {"clip_index": 3, "start_time": 23.1, "end_time": 34.95, "capability": "TEMPORAL_EXTEND",
            "requires_temporal_control": True, "continuity_to_previous": "CONTINUOUS", "previous_clip_index": 2, "visual_state_indexes": [4, 5]}
    plan = {"clip_plan_revision": 1, "keyframes": [state(4, 28.5), state(5, 34.9)]}
    anchors = [{"anchor_id": "clip-3-KF5", "time_seconds": 11.8, "image_url": "/kf5.png", "source": {"keyframe_index": 5, "id": "KF5"}}]
    previous = {"clip_index": 2, "clip_plan_revision": 1, "generated_by_task_id": "c2", "result_url": "/c2.mp4"}
    resources = {"references": manifest()["references"]}
    compiled = compile_temporal_extend_clip(shot, plan, clip, 1, previous, anchors, resource_references=resources)
    before = copy.deepcopy((compiled, resources, anchors))
    h3.compile_h3_reference_bindings(h3.build_physical_picture_mapping(compiled["video_reference_manifest"]), h3._subject_bindings("", ["Jun", "Mira", "Ivo"]), plan["keyframes"], [], capability="TEMPORAL_EXTEND", previous_av_present=True, current_visual_state=state(3, 17.4))
    assert (compiled, resources, anchors) == before
    assert compiled["execution_contract"]["temporal_anchor_manifest"]["anchors"][0]["frame_position"] == 293


def invoke(monkeypatch, response=None):
    captured = []
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            captured.append(kwargs)
            return {"success": True, "content": response or "subject_definitions:\n<Subject 1> is Jun.\n<Subject 2> is Mira.\n<Subject 3> is Ivo.\nsummary:\nThe subjects keep their canonical actions.\noverall_soundscape:\nRoom tone."}
    monkeypatch.setattr(h3, "LLMService", FakeLLM)
    monkeypatch.setattr(h3, "resolve_prompt_template", lambda *_: SimpleNamespace(template="frozen template", name="fake template"))
    shot = SimpleNamespace(id="offline", index=2, chapter_id="chapter", duration=24, characters=json.dumps(["Jun", "Mira", "Ivo"]), props="[]", scene="Room", dialogues="[]", video_director_plan="{}", continuity_mode="CONTINUOUS_TAKE", description="", video_description="")
    result = asyncio.run(h3.build_h3_video_prompt(
        db=SimpleNamespace(commit=lambda: None), novel=SimpleNamespace(id="n"), shot=shot,
        selected_mode=None, clip={"clip_index": 2, "start_time": 10, "end_time": 18, "capability": "EXTEND", "visual_state_indexes": [4]},
        workflow_capability={}, workflow_type="VIDEO_CONTINUATION", workflow_name="frozen", start_image_url=None,
        keyframes=[state()], transitions=[{"from_keyframe_index": 3, "to_keyframe_index": 4, "transition_description": "Mira walks toward Jun."}],
        clip_dialogues=[], reference_images=[], video_reference_manifest=manifest(), previous_av_present=True, current_visual_state=state(3, 10)))
    return result, captured, json.loads(shot.video_director_plan)["ai_calls"][-1]


def test_builder_uses_one_compiler_owned_section_and_existing_speech_contract(monkeypatch):
    prompt, calls, record = invoke(monkeypatch)
    payload = json.loads(calls[0]["user_content"].split("\n\n", 1)[1])
    assert len(calls) == 1
    expected = h3.render_h3_reference_bindings(payload["reference_binding_contract"])
    assert prompt.endswith(expected)
    assert prompt.count("character_identity_binding:") == 1
    assert "<Picture 2> ↔ <Subject 2> — Mira" in prompt
    assert record["parsed_result"]["reference_binding"] == payload["reference_binding_contract"]
    assert record["parsed_result"]["dialogue"]["passed"]
    assert prompt.count("dialogue_timeline:") == 1
    assert h3._canonical_visual_body_speech_issues(expected) == []
    assert h3.audit_physical_picture_references(prompt, payload["physical_picture_manifest"])["passed"]


def test_llm_cannot_redefine_compiler_owned_mapping_section(monkeypatch):
    with pytest.raises(ValueError, match="H3_REFERENCE_BINDING_SECTION_REDEFINED"):
        invoke(monkeypatch, "subject_definitions:\n<Subject 1> is Jun.\n<Subject 2> is Mira.\n<Subject 3> is Ivo.\ncharacter_identity_binding:\n<Picture 2> belongs to <Subject 1>.\nsummary:\nThey stay in place.")
