import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services.clip_execution_compiler import (
    ClipExecutionCompileError,
    compile_extend_clip,
    compile_generate_clip,
    compile_temporal_extend_clip,
    project_canonical_visual_references,
)
from app.services import video_director_ai


class Shot:
    id = "canonical-compiler-shot"
    duration = 24
    image_url = "/api/files/shot.png"
    image_path = None


def plan(states, revision=1):
    return {"canonical_visual_plan": True, "clip_plan_revision": revision, "keyframes": states}


def state(index, time, role="INTERMEDIATE", image=None, timed=False):
    item = {"index": index, "time_seconds": time, "role": role, "timed_visual_target": timed}
    if image:
        item["image_url"] = image
    return item


def clip(index=1, capability="GENERATE", owned=None, carry=None, **extra):
    return {
        "clip_index": index, "start_time": 0, "end_time": 8,
        "visual_state_indexes": owned or [], "carry_in_state_index": carry,
        "capability": capability, **extra,
    }


def test_generate_projection_orders_owned_states_and_resolves_start():
    manifest = project_canonical_visual_references(Shot(), plan([
        state(1, 0, "START"), state(2, 4, image="/api/files/a.png"), state(3, 8, image="/api/files/b.png"),
    ]), clip(owned=[1, 2, 3]))
    assert [item["source_keyframe_index"] for item in manifest["references"]] == [1, 2, 3]
    assert manifest["references"][0]["source_type"] == "SHOT_IMAGE"


def test_extend_ignores_carry_in_and_allows_zero_refs():
    compiled = compile_extend_clip(
        Shot(), plan([state(3, 8, image="/api/files/k3.png")]),
        clip(2, "EXTEND", owned=[], carry=3, continuity_to_previous="CONTINUOUS", previous_clip_index=1), 1,
        {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": "t1", "result_url": "/api/files/c1.mp4"},
    )
    assert compiled["video_reference_manifest"]["references"] == []


def test_temporal_excludes_anchor_identity_from_ordinary_manifest():
    temporal = {"anchor_id": "clip-2-KF4", "time_seconds": 2, "image_url": "/api/files/k4.png", "source": {"type": "KEYFRAME", "id": "KF4", "keyframe_index": 4}}
    compiled = compile_temporal_extend_clip(
        Shot(), plan([state(4, 10, image="/api/files/k4.png", timed=True), state(5, 12, image="/api/files/k5.png")]),
        clip(2, "TEMPORAL_EXTEND", owned=[4, 5], carry=3, continuity_to_previous="CONTINUOUS", previous_clip_index=1, requires_temporal_control=True), 1,
        {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": "t1", "result_url": "/api/files/c1.mp4"}, [temporal],
    )
    assert [item["source_keyframe_index"] for item in compiled["video_reference_manifest"]["references"]] == [5]
    assert compiled["execution_contract"]["temporal_anchor_manifest"]["anchors"][0]["anchor_id"] == "clip-2-KF4"


def test_missing_ordinary_image_soft_skips_and_end_does_not_fallback():
    manifest = project_canonical_visual_references(Shot(), plan([
        state(2, 4), state(3, 8, "END"),
    ]), clip(owned=[2, 3]))
    assert manifest["references"] == []


def test_budget_is_checked_after_projection_and_identity_not_url():
    states = [state(i, i, image=f"/api/files/same.png") for i in range(1, 12)]
    with pytest.raises(ClipExecutionCompileError, match="ORDINARY_REFERENCE_BUDGET_EXCEEDED"):
        project_canonical_visual_references(Shot(), plan(states), clip(owned=list(range(1, 12))))
    nine = project_canonical_visual_references(Shot(), plan(states[:10]), clip(owned=list(range(1, 10))))
    assert len(nine["references"]) == 9
    assert len({item["source_keyframe_index"] for item in nine["references"]}) == 9


def test_generate_without_first_owned_grounding_is_rejected():
    with pytest.raises(ClipExecutionCompileError, match="缺少片段起始视觉图"):
        compile_generate_clip(Shot(), plan([]), clip(owned=[]), 1)


def _prompt_route(monkeypatch, states, owned, temporal=None, carry=None):
    captured = {}

    class FakeLLM:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": "subject_definitions:\n<Subject 1> is Mira.\nsummary:\nvisual."}

    monkeypatch.setattr(video_director_ai, "LLMService", FakeLLM)
    monkeypatch.setattr(video_director_ai, "resolve_prompt_template", lambda _db, _novel, _attr, template_type: SimpleNamespace(template="system", name=template_type))
    shot = SimpleNamespace(
        id="prompt-route", index=1, chapter_id="chapter", description="visual", video_description="",
        duration=10, continuity_mode="NORMAL", characters=json.dumps(["Mira"]), scene="room", props="[]",
        dialogues="[]", video_director_plan="{}",
    )
    clip = {"clip_index": 1, "start_time": 0, "end_time": 10, "visual_state_indexes": owned, "carry_in_state_index": carry}
    asyncio.run(video_director_ai.build_h3_video_prompt(
        db=SimpleNamespace(commit=lambda: None), novel=SimpleNamespace(id="novel"), shot=shot,
        selected_mode=None, clip=clip, workflow_capability={}, workflow_type="multi_reference_video",
        workflow_name="H3", start_image_url=None, keyframes=states, transitions=[], clip_dialogues=[],
        reference_images=[], temporal_anchors=temporal or [],
    ))
    return captured["task_type"]


def _canonical_prompt(monkeypatch, states, owned, manifest, generated_prompt):
    captured = {}

    class FakeLLM:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": generated_prompt}

    monkeypatch.setattr(video_director_ai, "LLMService", FakeLLM)
    monkeypatch.setattr(
        video_director_ai,
        "resolve_prompt_template",
        lambda _db, _novel, _attr, template_type: SimpleNamespace(
            template="system", name=template_type,
        ),
    )
    shot = SimpleNamespace(
        id="picture-map", index=1, chapter_id="chapter", description="visual",
        video_description="", duration=10, continuity_mode="NORMAL",
        characters="[]", scene="room", props="[]", dialogues="[]",
        video_director_plan="{}",
    )
    result = asyncio.run(video_director_ai.build_h3_video_prompt(
        db=SimpleNamespace(commit=lambda: None), novel=SimpleNamespace(id="novel"), shot=shot,
        selected_mode=None,
        clip={
            "clip_index": 1, "start_time": 0, "end_time": 10,
            "visual_state_indexes": owned, "carry_in_state_index": None,
        },
        workflow_capability={}, workflow_type="multi_reference_video", workflow_name="H3",
        start_image_url=None, keyframes=states, transitions=[], clip_dialogues=[],
        reference_images=[], temporal_anchors=[], video_reference_manifest=manifest,
    ))
    payload = json.loads(captured["user_content"].split("\n\n", 1)[1])
    return result, payload, captured["system_prompt"]


def _manifest_reference(slot, state_index=None, *, source_type="KEYFRAME_IMAGE", time=None):
    return {
        "slot": slot,
        "kind": "DIRECTOR_VISUAL_ANCHOR" if state_index is not None else "CHARACTER_IDENTITY",
        "source_type": source_type,
        "source_keyframe_index": state_index,
        "source_role": "START" if state_index == 1 else "END" if state_index in {3, 4} else None,
        "source_time_seconds": time,
        "image_url": f"/api/files/ref-{slot}.png",
    }


def test_prompt_route_single_control_uses_11(monkeypatch):
    assert _prompt_route(monkeypatch, [state(2, 4, image="/k2.png")], [2]) == "h3_single_frame_prompt"


def test_prompt_route_start_end_pair_uses_12(monkeypatch):
    assert _prompt_route(monkeypatch, [state(1, 0, "START"), state(2, 10, "END", image="/end.png")], [1, 2]) == "h3_first_last_frame_prompt"


def test_prompt_route_two_non_endpoint_controls_uses_13(monkeypatch):
    assert _prompt_route(monkeypatch, [state(2, 3, image="/a.png"), state(3, 7, image="/b.png")], [2, 3]) == "h3_multi_keyframe_prompt"


def test_prompt_route_three_controls_uses_13(monkeypatch):
    assert _prompt_route(monkeypatch, [state(1, 0, "START"), state(2, 4, image="/a.png"), state(3, 10, "END", image="/b.png")], [1, 2, 3]) == "h3_multi_keyframe_prompt"


def test_prompt_route_ordinary_plus_timed_uses_13(monkeypatch):
    assert _prompt_route(monkeypatch, [state(2, 3, image="/a.png"), state(3, 7, timed=True)], [2, 3], [{"anchor_id": "clip-1-KF3", "source": {"type": "KEYFRAME", "id": "KF3"}}]) == "h3_multi_keyframe_prompt"


def test_prompt_route_timed_control_counts_when_excluded_from_ordinary(monkeypatch):
    assert _prompt_route(monkeypatch, [state(3, 7, timed=True)], [], [{"anchor_id": "clip-1-KF3", "source": {"type": "KEYFRAME", "id": "KF3"}}]) == "h3_single_frame_prompt"


def test_prompt_route_carry_in_does_not_count(monkeypatch):
    assert _prompt_route(monkeypatch, [], [], carry=2) == "h3_single_frame_prompt"


def test_prompt_route_zero_controls_uses_11(monkeypatch):
    assert _prompt_route(monkeypatch, [], []) == "h3_single_frame_prompt"


def test_prompt_mapping_minimal_hole_keeps_middle_state_text_only(monkeypatch):
    states = [state(1, 0, "START"), state(2, 4), state(3, 10, "END", image="/end.png")]
    manifest = {"version": 1, "references": [
        _manifest_reference(1, 1, source_type="SHOT_IMAGE", time=0),
        _manifest_reference(2, 3, time=10),
    ]}
    prompt, payload, _ = _canonical_prompt(
        monkeypatch, states, [1, 2, 3], manifest,
        "<Picture 1> = START at t=0s. KF2 is a textual intermediate state. <Picture 2> = END at t=10s.",
    )
    controls = {item["index"]: item for item in payload["visual_controls"]}
    assert controls[1]["physical_picture"] == "<Picture 1>"
    assert controls[2]["physical_picture"] is None
    assert controls[2]["physical_reference_status"] == "TEXT_ONLY"
    assert controls[3]["physical_picture"] == "<Picture 2>"
    assert "Picture 3" not in prompt


def test_single_state_11_uses_manifest_picture_identity(monkeypatch):
    states = [state(2, 4, image="/middle.png")]
    manifest = {"version": 1, "references": [
        _manifest_reference(1, 2, time=4),
    ]}
    prompt, payload, _ = _canonical_prompt(
        monkeypatch, states, [2], manifest,
        "<Picture 1> = KF2 at t=4s.",
    )
    assert payload["visual_control_route"] == "single"
    assert payload["visual_controls"][0]["physical_picture_index"] == 1
    assert "Picture 2" not in prompt


def test_start_end_12_uses_manifest_picture_identity(monkeypatch):
    states = [state(1, 0, "START"), state(2, 10, "END", image="/end.png")]
    manifest = {"version": 1, "references": [
        _manifest_reference(1, 1, source_type="SHOT_IMAGE", time=0),
        _manifest_reference(2, 2, time=10),
    ]}
    prompt, payload, _ = _canonical_prompt(
        monkeypatch, states, [1, 2], manifest,
        "<Picture 1> = START at t=0s. <Picture 2> = END at t=10s.",
    )
    assert payload["visual_control_route"] == "endpoint"
    assert [item["physical_picture_index"] for item in payload["visual_controls"]] == [1, 2]
    assert "Picture 3" not in prompt


def test_prompt_mapping_multiple_holes_stays_dense(monkeypatch):
    states = [state(1, 0, "START"), state(2, 3), state(3, 6), state(4, 10, "END", image="/end.png")]
    manifest = {"version": 1, "references": [
        _manifest_reference(1, 1, source_type="SHOT_IMAGE", time=0),
        _manifest_reference(2, 4, time=10),
    ]}
    prompt, payload, _ = _canonical_prompt(
        monkeypatch, states, [1, 2, 3, 4], manifest,
        "<Picture 1> = START at t=0s. KF2 then KF3 are textual states. <Picture 2> = END at t=10s.",
    )
    assert [item["physical_picture_index"] for item in payload["visual_controls"]] == [1, None, None, 2]
    assert "Picture 3" not in prompt and "Picture 4" not in prompt


def test_prompt_mapping_uses_complete_manifest_with_resource_slots(monkeypatch):
    states = [state(1, 0, "START"), state(2, 5), state(3, 10, "END", image="/end.png")]
    manifest = {"version": 1, "references": [
        _manifest_reference(1, source_type="CHARACTER_IDENTITY"),
        _manifest_reference(2, 1, source_type="SHOT_IMAGE", time=0),
        {**_manifest_reference(3, source_type="SCENE_REFERENCE"), "kind": "SCENE"},
        _manifest_reference(4, 3, time=10),
    ]}
    prompt, payload, _ = _canonical_prompt(
        monkeypatch, states, [1, 2, 3], manifest,
        "<Picture 1> character; <Picture 2> = START at t=0s; KF2 textual; "
        "<Picture 3> scene; <Picture 4> = END at t=10s.",
    )
    controls = {item["index"]: item for item in payload["visual_controls"]}
    assert controls[1]["physical_picture_index"] == 2
    assert controls[2]["physical_picture_index"] is None
    assert controls[3]["physical_picture_index"] == 4
    assert {int(value) for value in __import__("re").findall(r"Picture (\d+)", prompt)} == {1, 2, 3, 4}


def test_start_primary_fallback_and_end_exact_image_keep_manifest_identity(monkeypatch):
    states = [state(1, 0, "START"), state(2, 5), state(3, 10, "END", image="/end.png")]
    manifest = project_canonical_visual_references(Shot(), plan(states), clip(owned=[1, 2, 3]))
    prompt, payload, system_prompt = _canonical_prompt(
        monkeypatch, states, [1, 2, 3], manifest,
        "<Picture 1> = START at t=0s. KF2 remains textual. <Picture 2> = END at t=10s.",
    )
    assert manifest["references"][0]["source_type"] == "SHOT_IMAGE"
    assert manifest["references"][1]["source_type"] == "KEYFRAME_IMAGE"
    assert [item["source_keyframe_index"] for item in payload["physical_picture_manifest"]] == [1, 3]
    assert "physical_picture_manifest" in system_prompt
    assert "Picture 3" not in prompt


def test_all_image_backed_prompt_mapping_remains_one_to_one(monkeypatch):
    states = [
        state(1, 0, "START", image="/one.png"),
        state(2, 5, image="/two.png"),
        state(3, 10, "END", image="/three.png"),
    ]
    manifest = project_canonical_visual_references(Shot(), plan(states), clip(owned=[1, 2, 3]))
    prompt, payload, _ = _canonical_prompt(
        monkeypatch, states, [1, 2, 3], manifest,
        "<Picture 1> = START at t=0s; <Picture 2> = middle at t=5s; <Picture 3> = END at t=10s.",
    )
    assert [item["physical_picture_index"] for item in payload["visual_controls"]] == [1, 2, 3]
    assert all(f"Picture {index}" in prompt for index in (1, 2, 3))


def test_optional_missing_state_remains_text_only_and_does_not_enter_manifest(monkeypatch):
    states = [
        state(1, 0, "START"),
        {**state(2, 5), "timed_visual_target": False, "requirement": "OPTIONAL_MISSING"},
        state(3, 10, "END", image="/end.png"),
    ]
    manifest = project_canonical_visual_references(Shot(), plan(states), clip(owned=[1, 2, 3]))
    _, payload, _ = _canonical_prompt(
        monkeypatch, states, [1, 2, 3], manifest,
        "<Picture 1> = START at t=0s. KF2 remains optional text. <Picture 2> = END at t=10s.",
    )
    optional = payload["visual_controls"][1]
    assert optional["timed_visual_target"] is False
    assert optional["requirement"] == "OPTIONAL_MISSING"
    assert optional["physical_picture_index"] is None


def test_phantom_picture_reference_is_rejected(monkeypatch):
    states = [state(1, 0, "START"), state(2, 5), state(3, 10, "END", image="/end.png")]
    manifest = {"version": 1, "references": [
        _manifest_reference(1, 1, source_type="SHOT_IMAGE", time=0),
        _manifest_reference(2, 3, time=10),
    ]}
    with pytest.raises(RuntimeError, match="PHANTOM_PICTURE_REFERENCE"):
        _canonical_prompt(
            monkeypatch, states, [1, 2, 3], manifest,
            "<Picture 1> = START at t=0s. <Picture 2> = END at t=10s. <Picture 3> phantom.",
        )
