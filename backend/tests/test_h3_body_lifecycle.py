"""Deterministic body lifecycle; no model, database, media or tracking calls."""
import copy

import pytest

from app.services import video_director_ai as h3
from app.services.clip_execution_compiler import compile_temporal_extend_clip
from types import SimpleNamespace


def state(index, names):
    return {"index": index, "time_seconds": index * 5.4, "role": "INTERMEDIATE",
            "description": "Scene: room\nCharacters:\n" +
            "\n".join(f"- {name}: canonical body role." for name in names) + "\nAction: keep the canonical arrangement."}


def compile_case(start, target, text="Mira enters through the doorway.", **kwargs):
    mapping = [{"picture": "<Picture 2>", "kind": "CHARACTER_IDENTITY",
                "source_id": "mira-id", "source_name": "Mira"}]
    return h3.compile_h3_reference_bindings(
        mapping, {"Jun": "<Subject 1>", "Mira": "<Subject 2>"}, [target],
        [{"from_keyframe_index": 2, "to_keyframe_index": 3, "transition_description": text}],
        capability="TEMPORAL_EXTEND", previous_av_present=True, current_visual_state=start, **kwargs)


def test_present_to_present_keeps_existing_body_semantics():
    binding = compile_case(state(2, ["Jun", "Mira"]), state(3, ["Jun", "Mira"]))
    item = binding["characters"][0]
    assert item["body_binding"] == "EXISTING_CURRENT_BODY"
    assert "body_lifecycle_transition" not in item
    assert "Apply <Picture 2> identity to the existing/current body" in h3.render_h3_reference_bindings(binding)


@pytest.mark.parametrize("text", ["Mira enters through the doorway.", "Mira arrives beside Jun.",
                                 "Mira从门口进入画面。", "<Subject 2> enters the room."])
def test_absent_to_present_requires_exact_owned_entry(text):
    binding = compile_case(state(2, ["Jun"]), state(3, ["Jun", "Mira"]), text)
    assert binding["characters"][0]["body_binding"] == "ENTERING_NEW_BODY"
    assert not any(x["code"] == "CANONICAL_BODY_PRESENCE_UNKNOWN" for x in binding["findings"])
    prompt = h3.render_h3_reference_bindings(binding)
    for rule in ["absent from the carried-in start state KF2", "Exactly one body enters",
                 "<Picture 2> defines the identity of that entering body only",
                 "same continuous body", "temporal target must not instantiate a separate copy",
                 "After arrival, the same body remains the sole body", "do not perform another entry"]:
        assert rule in prompt
    assert "existing or explicitly entering" not in prompt
    assert h3._canonical_visual_body_speech_issues(prompt) == []


@pytest.mark.parametrize("text", ["Mira exits through the doorway.", "Mira leaves the room.", "Mira从门口离开画面。"])
def test_present_to_absent_requires_exact_owned_exit(text):
    binding = compile_case(state(2, ["Jun", "Mira"]), state(3, ["Jun"]), text)
    assert binding["characters"][0]["body_binding"] == "EXITING_CURRENT_BODY"
    prompt = h3.render_h3_reference_bindings(binding)
    assert "Exactly this same body exits" in prompt
    assert "absent from KF3; after exit, do not reinstantiate" in prompt
    assert h3._canonical_visual_body_speech_issues(prompt) == []


@pytest.mark.parametrize("text", ["Jun watches Mira enter the room.", "Mira and Jun enter the room.",
                                 "Miranda enters the room.", "The camera enters the room beside Mira.",
                                 "Mira does not enter the room.", "Mira已进入房间。", "Mira的手进入画面。",
                                 "Mira walks toward Jun.", "Mira stays beside the doorway."])
def test_unresolved_or_ambiguous_entry_preserves_unknown_fallback(text):
    binding = compile_case(state(2, ["Jun"]), state(3, ["Jun", "Mira"]), text)
    assert binding["characters"][0]["body_binding"] == "CANONICAL_BODY_PRESENCE_UNKNOWN"
    assert "existing or explicitly entering" in h3.render_h3_reference_bindings(binding)


@pytest.mark.parametrize("start,target", [
    (None, state(3, ["Jun", "Mira"])),
    (state(2, ["Jun"]), {"index": 3, "description": "Mira is somewhere in the room."}),
    ({"index": 2, "description": "Characters:\n- Jun: here.\n- Mira unknown\nAction: stay."}, state(3, ["Jun", "Mira"])),
])
def test_unknown_membership_is_not_inferred_from_prose(start, target):
    assert compile_case(start, target)["characters"][0]["body_binding"] == "CANONICAL_BODY_PRESENCE_UNKNOWN"


def test_entry_from_unrelated_transition_does_not_authorize_spawn():
    binding = h3.compile_h3_reference_bindings(
        [{"picture": "<Picture 1>", "kind": "CHARACTER_IDENTITY", "source_id": "mira-id", "source_name": "Mira"}],
        {"Mira": "<Subject 1>"}, [state(3, ["Jun", "Mira"])],
        [{"from_keyframe_index": 1, "to_keyframe_index": 3, "transition_description": "Mira enters."}],
        capability="EXTEND", previous_av_present=True, current_visual_state=state(2, ["Jun"]))
    assert binding["characters"][0]["body_binding"] == "CANONICAL_BODY_PRESENCE_UNKNOWN"


def production_case(clip_index):
    names = ["皇帝", "侍从1", "侍从2", "侍从3", "宫廷总管"]
    start = state(2 if clip_index == 2 else 3, names[:-1] if clip_index == 2 else names)
    target = state(3 if clip_index == 2 else 4, names)
    ordered = [("SCENE", "王宫更衣室"), ("CHARACTER_IDENTITY", "皇帝"), ("CHARACTER_IDENTITY", "侍从2"),
               ("CHARACTER_IDENTITY", "宫廷总管"), ("CHARACTER_IDENTITY", "侍从1"), ("CHARACTER_IDENTITY", "侍从3"),
               ("PROP", "巨大镜子"), ("PROP", "紫色长袍"), ("PROP", "宫廷腰带")]
    manifest = {"references": [{"slot": i, "kind": kind, "source_id": f"asset-{name}", "source_name": name,
                               "image_url": f"/{name}.png"} for i, (kind, name) in enumerate(ordered, 1)]}
    mapping = h3.build_physical_picture_mapping(manifest)
    transitions = [{"from_keyframe_index": start["index"], "to_keyframe_index": target["index"],
                    "transition_description": "宫廷总管从入口进入画面，沿入口至皇帝侧前方的路径快步接近皇帝。" if clip_index == 2 else "宫廷总管保持站位。"}]
    binding = h3.compile_h3_reference_bindings(mapping, h3._subject_bindings("", names), [target], transitions,
                capability="TEMPORAL_EXTEND", previous_av_present=True, current_visual_state=start)
    return binding, manifest, start, target, transitions


def test_c2_manager_is_single_entering_body_and_motion_owner_is_unchanged():
    binding, manifest, *_ = production_case(2)
    assert {x["name"]: x["body_binding"] for x in binding["characters"]} == {
        "皇帝": "EXISTING_CURRENT_BODY", "侍从1": "EXISTING_CURRENT_BODY", "侍从2": "EXISTING_CURRENT_BODY",
        "侍从3": "EXISTING_CURRENT_BODY", "宫廷总管": "ENTERING_NEW_BODY"}
    manager = next(x for x in binding["characters"] if x["name"] == "宫廷总管")
    assert (manager["picture"], manager["subject"]) == ("<Picture 4>", "<Subject 5>")
    assert [x["name"] for x in binding["motion_ownership"] if x["motion_class"] == "TRANSLATIONAL_MOTION"] == ["宫廷总管"]
    assert binding["motion_ownership"][-1]["evidence"] == [{"from_state": 2, "to_state": 3, "clause": "宫廷总管从入口进入画面"}]
    prompt = h3.render_h3_reference_bindings(binding)
    assert "<Subject 5> — 宫廷总管 is absent" in prompt
    assert h3.audit_physical_picture_references(prompt, h3.build_physical_picture_mapping(manifest))["passed"]


def test_c3_manager_is_existing_and_has_no_entering_body_rule():
    binding, *_ = production_case(3)
    assert all(x["body_binding"] == "EXISTING_CURRENT_BODY" for x in binding["characters"])
    assert all(x["motion_class"] == "LOCAL_MOTION / SPATIALLY_ANCHORED" for x in binding["motion_ownership"])
    assert "Exactly one body enters" not in h3.render_h3_reference_bindings(binding)


def test_body_lifecycle_cannot_mutate_packing_previous_or_temporal_frame135():
    binding, resources, start, target, transitions = production_case(2)
    clip = {"clip_index": 2, "start_time": 12.0, "end_time": 23.1, "capability": "TEMPORAL_EXTEND",
            "continuity_to_previous": "CONTINUOUS", "previous_clip_index": 1, "requires_temporal_control": True,
            "visual_state_indexes": [3]}
    plan = {"clip_plan_revision": 1, "keyframes": [start, target]}
    previous = {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": "current-c1", "result_url": "/c1.mp4"}
    anchors = [{"anchor_id": "clip-2-KF3", "time_seconds": 5.4, "image_url": "/kf3.png", "source": {"keyframe_index": 3, "id": "KF3"}}]
    compiled = compile_temporal_extend_clip(SimpleNamespace(id="shot", duration=72), plan, clip, 1, previous, anchors, resource_references=resources)
    frozen = copy.deepcopy((compiled, resources, previous, anchors, plan, transitions))
    mapped = h3.build_physical_picture_mapping(compiled["video_reference_manifest"])
    again = h3.compile_h3_reference_bindings(mapped, binding["subjects"], [target], transitions,
        capability="TEMPORAL_EXTEND", previous_av_present=True, current_visual_state=start)
    h3.render_h3_reference_bindings(again)
    assert (compiled, resources, previous, anchors, plan, transitions) == frozen
    assert len(mapped) == 9
    assert [m["source_name"] for m in mapped] == [r["source_name"] for r in resources["references"]]
    assert compiled["execution_contract"]["temporal_anchor_manifest"]["anchors"][0]["frame_position"] == 135
    assert again["motion_ownership"] == binding["motion_ownership"]
