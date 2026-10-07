"""Static reachability contracts: no model, media service or product database."""

import asyncio
import copy
import inspect
import json
from decimal import Decimal, ROUND_CEILING
from types import SimpleNamespace

import pytest

from app.services import temporal_anchor_reachability as planner
from app.services.clip_execution_compiler import (
    ClipExecutionCompileError, compile_temporal_extend_clip,
    project_temporal_anchor_positions, temporal_extend_frame_count,
)


def state(index, time, roles):
    return {"index": index, "time_seconds": time, "description": "Scene: hall\nCharacters:\n" +
            "\n".join(f"- {name}: {role}" for name, role in roles.items()) + "\nAction: canonical state."}


def edge(previous, target, text, start=0, end=4):
    return {"from_keyframe_index": previous["index"], "to_keyframe_index": target["index"],
            "start_time": start, "end_time": end, "transition_description": text}


def case(start_roles=None, target_roles=None, text="Mira enters the room.", *, semantic=1, duration=10, window=4):
    previous = state(1, 0, start_roles if start_roles is not None else {"Jun": "by the mirror"})
    target = state(2, window, target_roles if target_roles is not None else {"Jun": "by the mirror", "Mira": "at the doorway"})
    transition = edge(previous, target, text, end=window)
    plan = {"keyframes": [previous, target], "transitions": [transition], "clip_plan_revision": 1}
    clip = {"clip_index": 2, "start_time": 0, "end_time": duration, "capability": "TEMPORAL_EXTEND",
            "continuity_to_previous": "CONTINUOUS", "previous_clip_index": 1,
            "requires_temporal_control": True, "carry_in_state_index": 1, "visual_state_indexes": [2]}
    anchor = {"anchor_id": "target", "time_seconds": semantic, "image_url": "/target.png", "source": {"id": "KF2"}}
    return plan, clip, [anchor]


def place(plan, clip, anchors):
    semantic = project_temporal_anchor_positions(anchors, clip["end_time"] - clip["start_time"])
    return planner.plan_temporal_anchor_reachability(plan, clip, semantic)


def analysis(plan):
    return planner.analyze_transition_reachability(*plan["keyframes"], plan["transitions"][0])


def test_no_significant_motion_preserves_semantic_projection():
    plan, clip, anchors = case({"Jun": "at left"}, {"Jun": "at left"}, "The camera moves slowly.")
    item = place(plan, clip, anchors)[0]
    assert analysis(plan)["subjects"][0]["motion_class"] == "NO_SIGNIFICANT_MOTION"
    assert item["reachability"]["motion_budget_seconds"] == 0
    assert not item["reachability"]["placement_adjusted"]
    assert item["frame_position"] == item["reachability"]["semantic_frame_position"]


def test_existing_local_motion_is_not_shifted_to_clip_tail():
    plan, clip, anchors = case({"Jun": "at left"}, {"Jun": "at left, head turned"}, "Jun slightly turns the head.")
    item = place(plan, clip, anchors)[0]
    assert item["reachability"]["motion_budget_seconds"] == pytest.approx(0.4)
    assert not item["reachability"]["placement_adjusted"]
    assert analysis(plan)["subjects"][0]["motion_class"] == "LOCAL_MOTION"


def test_entering_translation_allocates_a_path_window():
    plan, clip, anchors = case()
    item = place(plan, clip, anchors)[0]
    subject = item["reachability"]["critical_subjects"][0]
    assert subject["lifecycle"] == "ENTERING_NEW_BODY"
    assert (subject["start_presence"], subject["target_presence"]) == ("ABSENT", "PRESENT")
    assert subject["motion_class"] == "TRANSLATIONAL_MOTION"
    assert subject["motion_budget_seconds"] == 4
    assert item["frame_position"] > item["reachability"]["semantic_frame_position"]
    assert item["reachability"]["effective_frame_local_time"] >= 4


def test_existing_body_translation_also_has_a_budget():
    plan, clip, anchors = case({"Mira": "at left"}, {"Mira": "at right"}, "Mira walks across the room.")
    item = place(plan, clip, anchors)[0]
    subject = item["reachability"]["critical_subjects"][0]
    assert subject["lifecycle"] == "EXISTING_CURRENT_BODY"
    assert subject["motion_class"] == "TRANSLATIONAL_MOTION"
    assert item["reachability"]["placement_adjusted"]


@pytest.mark.parametrize("text", ["Mira arrives beside Jun.", "Mira到达门口。"])
def test_validated_entering_lifecycle_is_a_signal_without_reassigning_motion_ownership(text):
    plan, clip, anchors = case(text=text)
    item = place(plan, clip, anchors)[0]
    subject = item["reachability"]["critical_subjects"][0]
    assert subject["lifecycle"] == "ENTERING_NEW_BODY"
    assert subject["motion_ownership"] == "LOCAL_MOTION / SPATIALLY_ANCHORED"
    assert subject["motion_class"] == "TRANSLATIONAL_MOTION"
    assert item["reachability"]["placement_adjusted"]


@pytest.mark.parametrize("text", ["Mira leaves the room.", "Mira exits through the doorway.", "Mira从门口离开画面。"])
def test_exiting_body_reserves_its_owned_exit(text):
    plan, clip, anchors = case({"Jun": "at left", "Mira": "near exit"}, {"Jun": "at left"}, text)
    item = place(plan, clip, anchors)[0]
    subject = item["reachability"]["critical_subjects"][0]
    assert subject["lifecycle"] == "EXITING_CURRENT_BODY"
    assert subject["target_presence"] == "ABSENT"
    assert subject["motion_class"] == "TRANSLATIONAL_MOTION"
    assert item["reachability"]["placement_adjusted"]


def test_composite_path_and_settled_target_are_not_counted_per_verb():
    plan, clip, anchors = case(target_roles={"Jun": "by the mirror", "Mira": "standing beside Jun"})
    first = place(plan, clip, anchors)[0]
    assert first["reachability"]["critical_subjects"][0]["motion_class"] == "COMPOSITE_MOTION"
    assert first["reachability"]["motion_budget_seconds"] == 6
    plan["transitions"][0]["transition_description"] = "Mira enters the room. Mira walks toward Jun. Mira approaches Jun. Mira enters the room."
    assert place(plan, clip, anchors)[0]["reachability"]["motion_budget_seconds"] == 6


@pytest.mark.parametrize("role", ["not standing beside Jun", "尚未站定"])
def test_negated_settlement_does_not_invent_composite_demand(role):
    plan, clip, anchors = case(target_roles={"Jun": "by the mirror", "Mira": role})
    subject = place(plan, clip, anchors)[0]["reachability"]["critical_subjects"][0]
    assert subject["motion_class"] == "TRANSLATIONAL_MOTION"
    assert subject["motion_budget_seconds"] == 4


def test_concurrent_subjects_take_maximum_not_sum():
    roles = {f"Actor{i}": "at the same location" for i in range(4)}
    plan, clip, anchors = case(roles, {**roles, "Mira": "standing by Actor0"},
                             " ".join(f"Actor{i} slightly turns the head." for i in range(4)) + " Mira enters the room.")
    parsed = analysis(plan)
    assert len(parsed["subjects"]) == 5
    assert parsed["motion_budget_seconds"] == 6
    assert sum(s["motion_budget_seconds"] for s in parsed["subjects"]) > parsed["motion_budget_seconds"]
    assert place(plan, clip, anchors)[0]["reachability"]["motion_budget_seconds"] == 6


def test_semantic_time_already_reachable_is_unchanged():
    plan, clip, anchors = case(semantic=7)
    item = place(plan, clip, anchors)[0]
    assert item["reachability"]["earliest_reachable_local_time"] == 4
    assert not item["reachability"]["placement_adjusted"]


def test_overflow_clamps_legally_with_a_finding():
    plan, clip, anchors = case(duration=5, window=4, semantic=4, target_roles={"Jun": "by the mirror", "Mira": "standing beside Jun"})
    item = place(plan, clip, anchors)[0]
    assert item["frame_position"] == temporal_extend_frame_count(5)
    assert item["reachability"]["clamped"]
    assert item["reachability"]["earliest_reachable_local_time"] == 6
    assert [f["code"] for f in item["reachability"]["findings"]] == ["TEMPORAL_ANCHOR_REACHABILITY_CLAMPED"]


@pytest.mark.parametrize("text", ["Jun watches Mira enter the room.", "Mira does not enter.", "Mira and Jun enter.", "Mira was mysteriously relocated."])
def test_unknown_entry_keeps_semantic_without_guessing(text):
    plan, clip, anchors = case(text=text)
    item = place(plan, clip, anchors)[0]
    assert not item["reachability"]["placement_adjusted"]
    assert any(f["code"] == "TEMPORAL_REACHABILITY_UNCERTAIN" for f in item["reachability"]["findings"])


@pytest.mark.parametrize("broken", ["presence", "edge", "timing", "ambiguous_edge", "mismatched_timing", "source_identity"])
def test_missing_canonical_authority_is_observable_and_nonblocking(broken):
    plan, clip, anchors = case()
    if broken == "presence": plan["keyframes"][0]["description"] = "Jun is here."
    if broken == "edge": plan["transitions"] = []
    if broken == "timing": plan["transitions"][0]["end_time"] = float("nan")
    if broken == "ambiguous_edge": plan["transitions"] *= 2
    if broken == "mismatched_timing": plan["transitions"][0]["end_time"] += 1
    if broken == "source_identity": anchors[0]["source"]["keyframe_index"] = 1
    item = place(plan, clip, anchors)[0]
    assert not item["reachability"]["placement_adjusted"]
    assert item["reachability"]["findings"][0]["code"] == "TEMPORAL_REACHABILITY_UNCERTAIN"


@pytest.mark.parametrize("text,expected", [("Mira sits down.", "POSTURE_TRANSITION"), ("Mira picks up the box.", "PROP_INTERACTION")])
def test_bounded_owned_posture_and_prop_actions(text, expected):
    plan, clip, anchors = case({"Mira": "at left"}, {"Mira": "at left, changed state"}, text)
    item = place(plan, clip, anchors)[0]
    assert item["reachability"]["critical_subjects"][0]["motion_class"] == expected
    assert item["reachability"]["motion_budget_seconds"] == 2


def test_negated_or_other_subject_posture_is_not_owned():
    plan, clip, anchors = case({"Jun": "at left", "Mira": "at right"}, {"Jun": "at left", "Mira": "unknown pose"}, "Mira watches Jun sit down. Mira does not sit down.")
    assert all(s["motion_class"] != "POSTURE_TRANSITION" for s in analysis(plan)["subjects"])


def test_deterministic_and_inputs_not_mutated():
    plan, clip, anchors = case()
    before = copy.deepcopy((plan, clip, anchors))
    expected = place(plan, clip, anchors)
    for _ in range(5): assert place(plan, clip, anchors) == expected
    assert (plan, clip, anchors) == before


def test_multiple_anchors_use_own_predecessor_and_inherit_delay():
    plan, clip, anchors = case(window=2, target_roles={"Jun": "by the mirror", "Mira": "standing beside Jun"})
    third = state(3, 4, {"Jun": "by the mirror", "Mira": "at the far side"})
    plan["keyframes"].append(third)
    plan["transitions"].append(edge(plan["keyframes"][1], third, "Mira walks across the room.", start=2, end=4))
    anchors.append({"anchor_id": "last", "time_seconds": 2, "image_url": "/last.png", "source": {"id": "KF3"}})
    first, second = place(plan, clip, anchors)
    assert first["reachability"]["motion_budget_seconds"] == 3
    assert second["reachability"]["previous_state_index"] == 2
    assert second["reachability"]["motion_budget_seconds"] == 2
    assert second["reachability"]["earliest_reachable_local_time"] == pytest.approx(first["reachability"]["effective_anchor_local_time"] + 2)
    assert first["frame_position"] < second["frame_position"]


def test_multiple_clamped_anchors_keep_unique_legal_slots():
    plan, clip, anchors = case(window=4, duration=5, semantic=4, target_roles={"Jun": "by the mirror", "Mira": "standing beside Jun"})
    third = state(3, 5, {"Jun": "by mirror", "Mira": "far right"})
    plan["keyframes"].append(third)
    plan["transitions"].append(edge(plan["keyframes"][1], third, "Mira walks across the room.", start=4, end=5))
    anchors.append({"anchor_id": "last", "time_seconds": 5, "image_url": "/last.png", "source": {"id": "KF3"}})
    first, second = place(plan, clip, anchors)
    assert [first["frame_position"], second["frame_position"]] == [temporal_extend_frame_count(5)-1, temporal_extend_frame_count(5)]
    assert all(a["reachability"]["clamped"] for a in [first, second])


def test_alignment_indexing_and_fractional_lower_bound():
    assert temporal_extend_frame_count(8) == 192
    anchors = [{"anchor_id": "zero", "time_seconds": 0, "image_url": "/a.png", "source": {"type": "TEST"}},
               {"anchor_id": "half", "time_seconds": Decimal(4)/191, "image_url": "/b.png", "source": {"type": "TEST"}},
               {"anchor_id": "end", "time_seconds": 8, "image_url": "/c.png", "source": {"type": "TEST"}}]
    old = project_temporal_anchor_positions(anchors, 8)
    assert [a["frame_position"] for a in old] == [1, 2, 192]
    plan, clip, anchors = case(window=Decimal("4.01"), duration=8)
    item = place(plan, clip, anchors)[0]
    expected = 1 + int((Decimal("4.01")*24).quantize(Decimal(1), rounding=ROUND_CEILING))
    assert item["frame_position"] == expected
    assert item["reachability"]["effective_frame_local_time"] >= 4.01
    assert (item["frame_position"]-1)/24 >= 4.01


@pytest.mark.parametrize("duration,window", [(4, 2.01), (8, 4.01), (10, 4.01), (11.1, 5.5), (20, 7.333)])
def test_physical_seconds_bound_survives_proportional_alignment(duration, window):
    plan, clip, anchors = case(window=window, duration=duration)
    item = place(plan, clip, anchors)[0]
    assert not item["reachability"]["clamped"]
    assert (item["frame_position"]-1)/24 >= window


def test_clip_local_conversion_does_not_add_shot_or_previous_av_offset_twice():
    plan, clip, anchors = case(target_roles={"Jun": "by the mirror", "Mira": "standing beside Jun"})
    clip["start_time"], clip["end_time"] = 100, 110
    for s in plan["keyframes"]: s["time_seconds"] += 99
    plan["transitions"][0]["start_time"] += 99
    plan["transitions"][0]["end_time"] += 99
    item = place(plan, clip, anchors)[0]
    assert item["reachability"]["transition_start_local_time"] == 0
    assert item["reachability"]["earliest_reachable_local_time"] == 6
    assert not item["reachability"]["clamped"]


@pytest.mark.parametrize("anchors", [[], [
    {"anchor_id": "a", "time_seconds": 1, "image_url": "/a.png", "source": {"type": "TEST"}},
    {"anchor_id": "b", "time_seconds": 1, "image_url": "/b.png", "source": {"type": "TEST"}},
]])
def test_existing_invalid_semantic_contract_still_raises(anchors):
    with pytest.raises(ClipExecutionCompileError): project_temporal_anchor_positions(anchors, 8)


def test_production_planner_has_no_evidence_value_or_clip_branch():
    source = inspect.getsource(planner)
    for forbidden in ["207", "135", "72", "C2", "宫廷总管", "random", "LLMClient", "httpx", "sqlalchemy"]:
        assert forbidden not in source


def test_public_compiler_attaches_evidence_without_changing_references_or_canonical_times():
    plan, clip, anchors = case()
    previous = {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": "previous", "result_url": "/previous.mp4"}
    original = copy.deepcopy((plan, clip, anchors, previous))
    compiled = compile_temporal_extend_clip(SimpleNamespace(id="shot"), plan, clip, 1, previous, anchors)
    item = compiled["execution_contract"]["temporal_anchor_manifest"]["anchors"][0]
    assert item["time_seconds"] == anchors[0]["time_seconds"]
    assert item["reachability"]["placement_adjusted"]
    assert compiled["video_reference_manifest"]["references"] == []
    assert (plan, clip, anchors, previous) == original


def test_api_and_worker_use_same_compiler_and_effective_evidence():
    from app.api import shots as api
    from app.services import shot_video_service as worker
    assert api.compile_temporal_extend_clip is worker.compile_temporal_extend_clip is compile_temporal_extend_clip
    plan, clip, anchors = case()
    previous = {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": "previous", "result_url": "/previous.mp4"}
    args = (SimpleNamespace(id="shot"), plan, clip, 1, previous, anchors)
    assert api.compile_temporal_extend_clip(*args) == worker.compile_temporal_extend_clip(*copy.deepcopy(args))


@pytest.fixture
def reference_assets(db_session, tmp_path):
    from app.models.novel import Novel, Chapter, Character, Scene
    def asset(name):
        path = tmp_path / (name + ".png")
        path.write_bytes(b"static input fixture")
        return str(path)
    db_session.add_all([Novel(id="n", title="Static"), Chapter(id="ch", novel_id="n", number=1, title="Chapter"),
                        Scene(id="room", novel_id="n", name="Hall", image_url=asset("room")),
                        Character(id="jun", novel_id="n", name="Jun", image_url=asset("jun")),
                        Character(id="mira", novel_id="n", name="Mira", image_url=asset("mira"))])
    db_session.commit()
    return asset


def test_formal_api_worker_recompile_and_final_binding_parity(db_session, reference_assets, monkeypatch):
    from app.api import shots as api
    from app.services import shot_video_service as worker
    from app.models.shot import Shot
    from app.models.task import Task
    from app.models.workflow import Workflow
    from app.repositories import NovelRepository, ChapterRepository, TaskRepository, ShotRepository, WorkflowRepository
    from app.services.clip_execution_compiler import TEMPORAL_DECISION_CONTRACT, EARLY_COMPOSITION_CONTRACT

    plan, clip, anchors = case(window=4, semantic=4, duration=8,
                              target_roles={"Jun": "by the mirror", "Mira": "standing beside Jun"})
    anchors[0]["anchor_id"] = "clip-2-KF2"
    anchors[0]["image_url"] = reference_assets("anchor")
    clip["temporal_anchor_ids"] = [anchors[0]["anchor_id"]]
    clip["selected_temporal_target_ids"] = ["KF2"]
    plan.update(canonical_visual_plan=True, clip_plan=[clip], temporal_anchors=anchors,
                clip_plan_validation={"temporal_contract": TEMPORAL_DECISION_CONTRACT, "composition_contract": EARLY_COMPOSITION_CONTRACT})
    shot = Shot(id="shot", chapter_id="ch", index=1, duration=8, scene="Hall", characters='["Jun", "Mira"]', props="[]", dialogues="[]", video_director_plan=json.dumps(plan))
    workflow = Workflow(id=api.TEMPORAL_EXTEND_WORKFLOW_ID, name="Static stub", type="TEMPORAL_EXTEND", workflow_json="{}", node_mapping="{}", is_active=True)
    db_session.add_all([shot, workflow]); db_session.commit()
    captured = {}
    previous = {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": "approved",
                "result_url": reference_assets("previous"), "local_path": reference_assets("previous")}
    monkeypatch.setattr(api.TaskService, "validate_workflow_node_mapping", lambda *_: (True, ""))
    monkeypatch.setattr(api, "enqueue_shot_video_task", lambda *args, **kw: captured.update(enqueued=(args, kw)))
    monkeypatch.setattr(api, "resolve_extend_previous_av", lambda *_: previous)
    monkeypatch.setattr(worker, "resolve_extend_previous_av", lambda *_: previous)
    response = asyncio.run(api.generate_video_director_clip("n", "ch", "shot", 2,
        api.GenerateVideoDirectorClipRequest(clip_plan_revision=1, auto_merge=False),
        NovelRepository(db_session), ChapterRepository(db_session), TaskRepository(db_session), WorkflowRepository(db_session), ShotRepository(db_session)))
    assert response["success"]
    args, kwargs = captured["enqueued"]
    task = db_session.query(Task).filter_by(id=args[0]).one()
    api_manifest = json.loads(task.metadata_json)["execution_contract"]["temporal_anchor_manifest"]
    assert api_manifest["anchors"][0]["reachability"]["placement_adjusted"]
    async def mocked_h3(**kwargs):
        return "mock prompt; no model request"
    class MockComfy:
        async def generate_video_continuation_with_workflow(self, **kwargs):
            captured["physical"] = kwargs
            return {"success": False, "error": "static test stop before upload or /prompt"}
    monkeypatch.setattr(worker, "build_h3_video_prompt", mocked_h3)
    monkeypatch.setattr(worker, "ComfyUIService", MockComfy)
    monkeypatch.setattr(worker, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    asyncio.run(worker.generate_shot_video_task(*args, **kwargs))
    assert "physical" in captured, task.error_message
    worker_manifest = json.loads(task.metadata_json)["execution_contract"]["temporal_anchor_manifest"]
    clean = copy.deepcopy(worker_manifest)
    for anchor in clean["anchors"]: anchor.pop("local_path", None)
    assert clean == api_manifest
    assert captured["physical"]["anchors"][0]["position"] == api_manifest["anchors"][0]["frame_position"]
