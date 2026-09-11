"""Bounded P1 handoff contracts: --noconftest, synthetic pixels and mock providers.

Runtime tests reuse isolated, ephemeral SQLite fixtures, never application assets.
Neither the mock tail extractor nor the mock observer measures video quality.
"""

import asyncio
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import socket
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
from pydantic import ValidationError
import pytest
from sqlalchemy.orm import Session

from test_h3_prompt_worker import PROMPT
from test_shot_video_execution import change_task, execution, run, worker
from test_visual_state_video_integration import answer, enable, unchanged_shot, visual


def requirement(predicate, subject, value="", **changes):
    return {"predicate": predicate, "subject": subject, "value": value,
            "source": "approved:isolated-handoff", **changes}


def p0_contract():
    return {"enabled": True, "invariants": [
        requirement("character_present", "Ada"), requirement("character_present", "Bea"),
        requirement("character_location", "Ada", "farm"),
    ]}


def load_module(monkeypatch, name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / relative)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    package, attribute = name.rsplit(".", 1)
    monkeypatch.setattr(sys.modules[package], attribute, module, raising=False)
    return module


@pytest.fixture
def pure(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Pure handoff contracts must not use network, DB, or media processes")

    for name in ("app", "app.schemas", "app.services"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    modules = [load_module(monkeypatch, name, relative) for name, relative in (
        ("app.schemas.visual_state", "app/schemas/visual_state.py"),
        ("app.services.visual_state_validator", "app/services/visual_state_validator.py"),
        ("app.services.actual_state_handoff", "app/services/actual_state_handoff.py"),
        ("app.services.actual_state_frames", "app/services/actual_state_frames.py"),
    )]
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(side_effect=forbidden))
    state = SimpleNamespace(schema=modules[0], validator=modules[1], handoff=modules[2], frames=modules[3])
    state.request = {"actual_state_handoff": {"enabled": True}, "visual_state_validation": p0_contract(),
                     "skip_llm_when_prompt_exists": False, "only_window_index": None}
    state.plan = {"window_plans": [
        {"window_index": 1, "selected_frame_count": 3, "keyframe_indexes": [1, 2, 3], "start_time": 0, "end_time": 4},
        {"window_index": 2, "selected_frame_count": 3, "keyframe_indexes": [3, 4, 5], "start_time": 4, "end_time": 8},
    ]}
    state.references = [state.validator.VisualReference(2, index, f"synthetic-tail-{index}".encode(),
                                                       f"/private/handoff-tail/frame-{index}.png", "START")
                        for index in range(3)]
    candidates = [{"frame_index": 93 + index, "pts": (93 + index) / 24,
                   "sha256": ref.sha256, "path": ref.source_url, "usable": True, "reference_usable": True}
                  for index, ref in enumerate(state.references)]
    state.tail = {"can_use": True, "technical_tail_compatible": True, "candidates": candidates,
                  "selected": candidates[0], "observation_candidates": candidates,
                  "last_frame_index": 95, "last_frame_pts": 95 / 24, "video_end_seconds": 4,
                  "source_path": "/private/same-run/processed-c1.mp4", "source_sha256": "c" * 64,
                  "recipe": deepcopy(state.frames._RECIPE)}
    state.observer = SimpleNamespace(observe=AsyncMock(side_effect=answer))
    state.arguments = {"visual_request": state.request["visual_state_validation"],
                       "snapshot": {"characters": ["Ada", "Bea"], "props": []},
                       "expected_clips": [{**window, "clip_index": window["window_index"]}
                                          for window in state.plan["window_plans"]],
                       "original_validation": {"findings": []}, "tail_evidence": state.tail,
                        "references": state.references, "observer": state.observer}
    original_refs = [state.validator.VisualReference(2, index, f"planned-{index}".encode(), f"/planned/{index}.png", "KF")
                     for index in (1, 2)]
    state.arguments["original_validation"] = asyncio.run(state.validator.validate_references(
        state.request["visual_state_validation"], original_refs, observer=state.observer))
    state.observer.observe.reset_mock()
    return state


@pytest.fixture
def runtime_modules(visual, monkeypatch):
    state = visual
    # visual explicitly loads the schema and validator into worker's isolated packages.
    state.schema = sys.modules["app.schemas.visual_state"]
    state.handoff = load_module(monkeypatch, "app.services.actual_state_handoff", "app/services/actual_state_handoff.py")
    state.frames = load_module(monkeypatch, "app.services.actual_state_frames", "app/services/actual_state_frames.py")
    state.extract = AsyncMock(side_effect=AssertionError("Disabled/unsupported runs must not extract a tail"))
    monkeypatch.setattr(state.frames, "extract_tail_window", state.extract)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(side_effect=AssertionError("Real media processes forbidden")))
    return state


@pytest.fixture
def handoff_runtime(runtime_modules, request):
    state = runtime_modules
    state.graph["h3"]["inputs"].update({f"ref_images.ref_image_{index}": [node, 0]
                                      for index, node in enumerate(("image", "kf1", "kf2"))})
    state.workflow.workflow_json = json.dumps(state.graph)
    plan = json.loads(state.shot.video_director_plan)
    assert state.mode == "MULTI_KEYFRAME" and len(plan["window_plans"]) == 2
    plan["window_plans"][1]["keyframe_indexes"] = [3, 4, 5]
    plan["keyframes"] = plan["keyframes"][:5]
    for index, window in enumerate(plan["window_plans"]):
        window.update(start_time=index * 4, end_time=(index + 1) * 4)
        if getattr(request, "param", {}).get("pre_routed"):
            window["workflow_type"] = state.workflow.type
    plan["transitions"] = [{"from_keyframe_index": index, "to_keyframe_index": index + 1,
                            "transition_description": f"Approved motion {index} to {index + 1}."}
                           for index in range(1, 5)]
    state.shot.video_director_plan = json.dumps(plan)
    state.db.commit()
    state.original_plan = deepcopy(plan)
    state.before_shot = {column.key: getattr(state.shot, column.key) for column in state.models.Shot.__table__.columns}
    state.shot_updates.clear()
    state.run_request.update(skip_llm_when_prompt_exists=False, actual_state_handoff={"enabled": True})
    enable(state, p0_contract())
    state.timeline_events, state.before_queue = [], []
    state.tail_hook = None
    state.tail = None

    async def extract(video_path, directory, *, expected_sha256):
        with Session(state.engine) as reader:
            data = json.loads(reader.get(state.models.Task, "task").metadata_json)
        receipt = state.execution.verified_clip_receipt(data["video_run"], 1)
        assert receipt["prompt_id"] == "queued-1"
        assert (video_path, expected_sha256) == (receipt["path"], receipt["sha256"])
        assert Path(video_path).suffix == ".mp4" and Path(video_path).read_bytes()
        assert state.execution.file_digest(video_path) == expected_sha256
        assert data["video_run"]["clips"]["2"]["submission"] == {"state": "not_submitted"}
        state.predecessor = deepcopy(receipt)
        state.timeline_events.extend(["c1-receipt", "tail-extraction"])
        directory = Path(directory)
        assert directory.parent == Path(data["video_run"]["directory"]) and not directory.exists()
        directory.mkdir(mode=0o700)
        candidates = []
        for index in range(3):
            frame_index = 93 + index
            path = directory / f"frame_{frame_index:08d}.png"
            Image.new("RGB", (8, 6), (240, 20 + index * 30, 130)).save(path, "PNG")
            candidates.append({"path": str(path), "sha256": state.execution.file_digest(path),
                               "frame_index": frame_index, "pts": frame_index / 24,
                               "offset_from_last_frame_seconds": (95 - frame_index) / 24,
                               "offset_from_video_end_seconds": 4 - frame_index / 24,
                               "usable": True, "reference_usable": True, "sharpness": 0.1, "reason": "mock"})
        state.tail = {
            "can_use": True, "technical_tail_compatible": True, "reason": "ok", "error": None,
            "source_path": video_path, "source_sha256": expected_sha256, "expected_sha256": expected_sha256,
            "source_size_bytes": receipt["bytes"], "source_sha256_after": expected_sha256,
            "source_size_bytes_after": receipt["bytes"], "candidates": candidates, "selected": candidates[-1],
            "observation_candidates": [candidates[-1], candidates[-2]],
            "last_frame_index": 95, "last_frame_pts": 95 / 24, "video_end_seconds": 4, "window_start_pts": 3.5,
            "recipe": deepcopy(state.frames._RECIPE),
            "tail_difference": {"scores": [{"frame_index": 95, "difference": 0}], "maximum": 0,
                                "limit": 0.12, "semantic_proof": False},
        }
        if state.tail_hook:
            state.tail_hook(state.tail)
        return state.tail

    def stage(stage_name):
        if stage_name == "queue":
            with Session(state.engine) as reader:
                state.before_queue.append(json.loads(reader.get(state.models.Task, "task").metadata_json))
            state.timeline_events.append(f"queue-c{len(state.before_queue)}")

    state.extract.side_effect = extract
    state.stage_hook = stage
    return state


@pytest.fixture
def routed_handoff(handoff_runtime):
    """A previously routed plan, independently of the unrouted golden controls."""
    state = handoff_runtime
    plan = deepcopy(state.original_plan)
    for window in plan["window_plans"]:
        window["workflow_type"] = state.workflow.type
    state.shot.video_director_plan = json.dumps(plan)
    state.db.commit()
    state.original_plan = deepcopy(plan)
    state.before_shot = {key: getattr(state.shot, key) for key in state.before_shot}
    state.shot_updates.clear()
    enable(state, p0_contract())
    return state


def edit_metadata(state, mutate):
    with Session(state.engine) as editor:
        task = editor.get(state.models.Task, "task")
        data = json.loads(task.metadata_json)
        mutate(data)
        task.metadata_json = json.dumps(data)
        editor.commit()


def assert_no_c2(state, task, *, c1=True, failed=True):
    if failed:
        assert task.status == "failed", task.error_message
        assert task.completed_at is not None and task.result_url is None
    data = json.loads(task.metadata_json)
    assert "result" not in data["execution"]
    if "video_run" in data:
        assert "result" not in data["video_run"]
        clips = data["video_run"]["clips"]
        if "2" in clips:
            assert clips["2"]["submission"] == {"state": "not_submitted"}
            assert clips["2"]["receipt"] is None
        if c1:
            assert clips["1"]["state"] == "SUCCEEDED"
            assert clips["1"]["receipt"]["prompt_id"] == "queued-1"
    assert state.client.queue_prompt.await_count == int(c1)
    assert state.client.wait_for_result.await_count == int(c1)
    assert state.client.get_prompt_state.await_count == int(c1)
    assert state.storage.download_video.await_count == int(c1)
    state.storage.merge_videos.assert_not_awaited()
    unchanged_shot(state)
    return data


def assert_semantic_report(state, task, decision):
    data = json.loads(task.metadata_json)
    result = data["actual_state_handoff"]
    assert (result["status"], result["decision"], result["post_handoff_status"]) == ("resolved", decision, "NOT_MEASURED")
    assert result["source"]["predecessor_receipt"] == state.predecessor
    assert result["source"]["original_p0_evidence"] == data["visual_state_validation"]["evidence"]
    assert result["source"]["request_hash"] == state.execution.digest(state.frozen_request)
    assert result["source"]["snapshot_hash"] == state.execution.digest(data["execution"]["shot_snapshot"])
    assert result["canonical_state"]["characters"] == ["Ada", "Bea"]
    path = Path(result["evidence"]["path"])
    assert path.is_relative_to(Path(data["video_run"]["directory"]))
    assert sha256(path.read_bytes()).hexdigest() == result["evidence"]["sha256"]
    assert json.loads(path.read_text()) == {key: value for key, value in result.items()
                                          if key not in {"evidence", "uploads", "effective_context", "effective_context_hash"}}
    assert data["oldsource"] == state.oldsource
    assert data["execution"]["request"] == data["video_run"]["request"] == state.frozen_request
    return result


@pytest.mark.parametrize("option", [{}, {"enabled": False}, {"enabled": True}])
def test_schema_is_only_a_strict_default_off_switch(pure, option):
    model = pure.schema.ActualStateHandoff.model_validate(option)
    assert model.model_dump() == {"enabled": option.get("enabled", False)}
    with pytest.raises(ValidationError):
        model.enabled = True


@pytest.mark.parametrize("option", [{"enabled": 1}, {"enabled": "true"}, {"enabled": None},
                                    {"enabled": True, "trusted_state": []}, {"repair": True}])
def test_schema_cannot_coerce_opt_in_or_accept_state_overrides(pure, option):
    with pytest.raises(ValidationError):
        pure.schema.ActualStateHandoff.model_validate(option)


@pytest.mark.parametrize("option", [None, {}, {"enabled": False}])
def test_disabled_scope_never_imposes_new_plan_requirements(pure, option):
    assert pure.handoff.validate_handoff_scope({"actual_state_handoff": option}, None, "legacy-mode") is False


def test_supported_scope_is_read_only(pure):
    before = deepcopy((pure.request, pure.plan))
    assert pure.handoff.validate_handoff_scope(pure.request, pure.plan, "MULTI_KEYFRAME") is True
    assert (pure.request, pure.plan) == before


@pytest.mark.parametrize("fault,code", [
    ("missing-p0", "HANDOFF_REQUIRES_VISUAL_STATE_VALIDATION"),
    ("disabled-p0", "HANDOFF_REQUIRES_VISUAL_STATE_VALIDATION"),
    ("reuse", "HANDOFF_REQUIRES_FRESH_PROMPT"),
    ("one", "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"), ("three", "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ("SINGLE_FRAME", "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ("FIRST_LAST_FRAME", "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ("only", "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ("nonshared", "HANDOFF_REQUIRES_SHARED_PLANNED_BOUNDARY"),
    ("gap", "HANDOFF_REQUIRES_ADJACENT_WINDOWS"),
    ("boolean-index", "HANDOFF_INVALID_CLIP_MEMBERSHIP"), ("duplicate", "HANDOFF_INVALID_CLIP_MEMBERSHIP"),
    ("unsorted", "HANDOFF_INVALID_CLIP_MEMBERSHIP"), ("range", "HANDOFF_INVALID_CLIP_RANGE"),
    ("nonfinite", "HANDOFF_INVALID_CLIP_RANGE"),
])
def test_scope_rejects_unsupported_or_unproven_membership(pure, fault, code):
    request, plan, mode = pure.request, pure.plan, "MULTI_KEYFRAME"
    if fault == "missing-p0":
        request.pop("visual_state_validation")
    elif fault == "disabled-p0":
        request["visual_state_validation"]["enabled"] = False
    elif fault == "reuse":
        request["skip_llm_when_prompt_exists"] = True
    elif fault == "one":
        plan["window_plans"].pop()
    elif fault == "three":
        plan["window_plans"].append(deepcopy(plan["window_plans"][-1]))
    elif fault in {"SINGLE_FRAME", "FIRST_LAST_FRAME"}:
        mode = fault
    elif fault == "only":
        request["only_window_index"] = 2
    elif fault == "nonshared":
        plan["window_plans"][1]["keyframe_indexes"] = [4, 5, 6]
    elif fault == "gap":
        plan["window_plans"][1]["start_time"] = 4.5
    elif fault == "boolean-index":
        plan["window_plans"][0]["keyframe_indexes"][0] = True
    elif fault in {"duplicate", "unsorted"}:
        plan["window_plans"][0]["keyframe_indexes"] = [1, 1, 3] if fault == "duplicate" else [2, 1, 3]
    else:
        plan["window_plans"][0]["end_time"] = 0 if fault == "range" else float("inf")
    with pytest.raises(ValueError, match=code):
        pure.handoff.validate_handoff_scope(request, plan, mode)


def test_resolver_separates_planned_actual_canonical_and_trusted_state(pure):
    before = deepcopy({key: value for key, value in pure.arguments.items() if key != "observer"})
    result = asyncio.run(pure.handoff.resolve_handoff(**pure.arguments))
    assert (result["decision"], result["can_submit_c2"]) == ("CONTINUE", True)
    assert result["canonical_state"]["characters"] == ["Ada", "Bea"]
    assert result["canonical_state"]["requirements"] == result["planned_state"]["boundary"]
    trusted = result["trusted_handoff_state"]
    assert trusted["reference_eligible"] is True and trusted["excluded_fields"] == []
    assert len(trusted["confirmed_actual_fields"]) == 3
    assert {fact["image_sha256"] for fact in trusted["confirmed_actual_fields"]} == {pure.references[0].sha256}
    assert len(result["actual_observed_state"]["validation"]["observations"]) == 3
    assert {key: value for key, value in pure.arguments.items() if key != "observer"} == before
    assert pure.observer.observe.await_count == 3


def test_missing_later_anchor_coverage_is_not_compatibility_permission(pure):
    original = pure.arguments["original_validation"]
    original["findings"] = [item for item in original["findings"] if not (
        item["reference_index"] == 2 and item["expected"]["predicate"] == "character_location")]
    result = asyncio.run(pure.handoff.resolve_handoff(**pure.arguments))
    assert result["decision"] == "HUMAN_REVIEW" and result["can_submit_c2"] is False
    assert any(issue["reason"] == "C2_ANCHOR_COMPATIBILITY_COVERAGE_MISSING" for issue in result["issues"])


def test_future_critical_rule_needs_trusted_not_merely_declared_boundary_state(pure):
    pure.arguments["visual_request"]["invariants"].pop()
    pure.arguments["visual_request"]["anchors"] = [
        {"clip_index": 2, "reference_index": 0, "requirements": [requirement("character_location", "Ada", "farm", critical=False, known_unknown=True)]},
        {"clip_index": 2, "reference_index": 2, "requirements": [requirement("character_location", "Ada", "farm")]},
    ]
    result = asyncio.run(pure.handoff.resolve_handoff(**pure.arguments))
    assert result["decision"] == "HUMAN_REVIEW" and result["can_submit_c2"] is False
    assert any(issue["reason"] == "FUTURE_CRITICAL_STATE_NOT_TRUSTED" for issue in result["issues"])


def test_noncritical_fact_cannot_inherit_an_earlier_state_contradicted_at_true_end(pure):
    pure.arguments["visual_request"]["invariants"][-1].update(value="tree", critical=False)

    def moving(reference, questions):
        result = answer(reference, questions)
        if reference.payload == pure.references[-1].payload:
            for fact in result["facts"]:
                if fact["predicate"] == "character_location":
                    fact["value"] = "rock"
        return result

    pure.observer.observe.side_effect = moving
    result = asyncio.run(pure.handoff.resolve_handoff(**pure.arguments))
    assert result["decision"] == "HUMAN_REVIEW" and result["can_submit_c2"] is False
    assert any(issue["reason"] == "TAIL_STATE_NOT_STABLE_FOR_INHERITANCE" for issue in result["issues"])
    assert not any(fact["predicate"] == "character_location" for fact in result["trusted_handoff_state"]["confirmed_actual_fields"])


@pytest.mark.parametrize("fault", [None, "swapped", "missing", "disconnected", "boolean-slot", "extra-reference", "audio-only"])
def test_reference_slot_topology_must_connect_actual_picture_one_to_output(pure, fault):
    graph = {node: {"class_type": "LoadImage", "inputs": {"image": "input.png"}} for node in ("a", "b", "c")}
    graph.update(h3={"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
        f"ref_images.ref_image_{index}": [node, 0] for index, node in enumerate(("a", "b", "c"))}},
        out={"class_type": "SaveVideo", "inputs": {"video": ["h3", 1]}})
    mapping = {"reference_image_node_id": "a", "keyframe_node_1": "b", "keyframe_node_2": "c", "video_save_node_id": "out"}
    if fault == "swapped":
        graph["h3"]["inputs"]["ref_images.ref_image_0"] = ["b", 0]
    elif fault == "missing":
        del graph["h3"]["inputs"]["ref_images.ref_image_0"]
    elif fault == "disconnected":
        graph["out"]["inputs"] = {}
    elif fault == "boolean-slot":
        graph["h3"]["inputs"]["ref_images.ref_image_0"] = ["a", False]
    elif fault == "extra-reference":
        graph["h3"]["inputs"]["ref_images.ref_image_3"] = ["a", 0]
    elif fault == "audio-only":
        graph["video"] = {"class_type": "CreateVideo", "inputs": {"images": ["b", 0], "audio": ["h3", 2]}}
        graph["out"]["inputs"]["video"] = ["video", 0]
    if fault is None:
        pure.handoff.validate_reference_slots(graph, mapping, 3)
    else:
        with pytest.raises(ValueError, match="HANDOFF_"):
            pure.handoff.validate_reference_slots(graph, mapping, 3)


@pytest.mark.parametrize("count,flavor", [(3, "audiodrive"), (4, "audiodrive"), (3, "ref2va"), (4, "ref2va")])
def test_shipped_h3_visual_paths_support_ordered_handoff(pure, count, flavor):
    name = ("three" if count == 3 else "four") + "_frame_video_minimax_h3_" + flavor + ".json"
    graph = json.loads((Path(__file__).parents[1] / "workflows" / name).read_text())
    consumer = next(node for node in graph.values() if node["class_type"] in ("MiniMaxH3AudioConditioningT8", "MiniMaxH3ReferenceToVideo"))
    nodes = [consumer["inputs"][f"ref_images.ref_image_{index}"][0] for index in range(count)]
    mapping = {"reference_image_node_id": nodes[0], "video_save_node_id": "95" if flavor == "audiodrive" else "150",
               **{f"keyframe_node_{index}": node for index, node in enumerate(nodes[1:], 1)}}
    pure.handoff.validate_reference_slots(graph, mapping, count)


@pytest.mark.parametrize("known_unknown,decision", [(False, "BLOCK"), (True, "HUMAN_REVIEW")])
def test_local_anchor_cannot_weaken_a_protected_invariant(pure, known_unknown, decision):
    canonical = requirement("prop_present", "grain_sack", protected=True)
    pure.arguments["visual_request"]["invariants"].append(canonical)
    pure.arguments["visual_request"]["anchors"] = [{"clip_index": 2, "reference_index": 0,
        "requirements": [requirement("prop_present", "grain_sack", critical=False, known_unknown=known_unknown)]}]

    def absent(reference, questions):
        result = answer(reference, questions)
        for fact in result["facts"]:
            if fact["predicate"] == "prop_present":
                fact.update(state="ABSENT", evidence="The exposed back has no grain sack.")
        return result

    pure.observer.observe.side_effect = absent
    result = asyncio.run(pure.handoff.resolve_handoff(**pure.arguments))
    assert result["decision"] == decision and result["can_submit_c2"] is False
    merged = next(rule for rule in result["planned_state"]["boundary"] if rule["subject"] == "grain_sack")
    assert merged["critical"] is True and merged["protected"] is True
    assert merged["known_unknown"] == known_unknown
    assert result["canonical_state"]["requirements"][-1]["expected"] == "PRESENT"


@pytest.mark.parametrize("missing", ["Ada", "Bea"])
def test_every_declared_canonical_identity_needs_explicit_boundary_coverage(pure, missing):
    rules = pure.arguments["visual_request"]["invariants"]
    rules[:] = [rule for rule in rules if (rule["predicate"], rule["subject"]) != ("character_present", missing)]
    result = asyncio.run(pure.handoff.resolve_handoff(**pure.arguments))
    assert (result["decision"], result["can_submit_c2"]) == ("HUMAN_REVIEW", False)
    assert "EXPLICIT_CANONICAL_IDENTITY_COVERAGE_REQUIRED" in {issue["reason"] for issue in result["issues"]}


@pytest.mark.parametrize("failure", ["no-tail", "incompatible", "no-boundary", "known-unknown"])
def test_unproven_semantics_are_holds_not_reference_authorization(pure, failure):
    if failure == "no-tail":
        pure.tail.update(can_use=False, selected=None, observation_candidates=[])
    elif failure == "incompatible":
        pure.tail["technical_tail_compatible"] = False
    elif failure == "no-boundary":
        pure.arguments["visual_request"]["invariants"] = []
    else:
        pure.arguments["visual_request"]["invariants"][0]["known_unknown"] = True
    result = asyncio.run(pure.handoff.resolve_handoff(**pure.arguments))
    assert (result["decision"], result["can_submit_c2"]) == ("HUMAN_REVIEW", False)
    assert result["trusted_handoff_state"]["reference_eligible"] is False
    if failure != "known-unknown":
        pure.observer.observe.assert_not_awaited()


@pytest.mark.parametrize("execution", [{"reuse": False}], indirect=True)
@pytest.mark.parametrize("handoff_runtime", [{}, {"pre_routed": True}], indirect=True, ids=["new-plan", "routed-plan"])
def test_shot17_control_same_run_whole_barrier_uses_actual_c2_payload(handoff_runtime):
    state = handoff_runtime
    task = run(state)
    assert task.status == "completed", task.error_message
    data = json.loads(task.metadata_json)
    result = assert_semantic_report(state, task, "CONTINUE")
    assert state.timeline_events == ["queue-c1", "c1-receipt", "tail-extraction", "queue-c2"]
    state.extract.assert_awaited_once()
    assert state.db.query(state.models.Task).count() == 1
    video_run = data["video_run"]
    assert video_run["scope"] == "whole_shot" and video_run["phase"] == "completed"
    assert {slot["receipt"]["run_id"] for slot in video_run["clips"].values()} == {video_run["run_id"]}
    assert {slot["receipt"]["prompt_id"] for slot in video_run["clips"].values()} == {"queued-1", "queued-2"}
    assert len({slot["receipt"]["attempt_id"] for slot in video_run["clips"].values()}) == 2
    manifest = state.execution.completion_manifest(data)
    assert video_run["merge"]["manifest"] == manifest
    assert video_run["result"]["manifest_hash"] == state.execution.digest(manifest)
    assert video_run["result"] == data["execution"]["result"]
    assert video_run["result"]["attachment"] == "archived" and video_run["result"]["url"] == task.result_url
    assert state.storage.merge_videos.await_args.args[0] == [item["path"] for item in manifest]
    for key, slot in video_run["clips"].items():
        receipt = slot["receipt"]
        assert state.execution.verified_clip_receipt(video_run, int(key)) == receipt
        assert receipt["raw"]["path"] != receipt["path"]
        for artifact in (receipt, receipt["raw"]):
            assert state.execution.file_digest(artifact["path"]) == artifact["sha256"]
            assert Path(artifact["path"]).stat().st_size == artifact["bytes"]
        assert slot["submission"]["graph"] == state.queued[int(key) - 1]

    original = data["visual_state_validation"]
    assert original["decision"] == "PASS" and len(original["references"]) == 6
    assert set(original["uploads"]) == {"1"} and set(result["uploads"]) == {"2"}
    assert [ref["keyframe_index"] for ref in original["references"]] == [1, 2, 3, 3, 4, 5]
    assert state.before_queue[0]["visual_state_validation"] == original
    assert state.before_queue[0]["video_run"]["clips"]["1"]["receipt"] is None
    assert state.before_queue[1]["video_run"]["clips"]["1"]["receipt"] == state.predecessor
    assert state.before_queue[1]["video_run"]["clips"]["2"]["receipt"] is None
    artifacts = {item["sha256"]: item for item in original["artifacts"]}
    assert len(artifacts) == 5
    for reference in original["references"]:
        payload = state.original_images[state.module.url_to_local_path(reference["source_url"])]
        artifact = artifacts[reference["image_sha256"]]
        assert Path(artifact["path"]).read_bytes() == payload
        assert sha256(payload).hexdigest() == artifact["sha256"]
    observed = state.observer.observe.await_args_list
    prior = [call.args[0] for call in observed if "handoff-tail" not in call.args[0].source_url]
    actual = [call.args[0] for call in observed if "handoff-tail" in call.args[0].source_url]
    assert len(prior) == 5 and len(actual) == 2
    assert {ref.sha256 for ref in prior}.isdisjoint(ref.sha256 for ref in actual)
    selected = state.tail["selected"]
    uploaded = state.image_uploads[3]
    assert uploaded["payload"] == Path(selected["path"]).read_bytes()
    with Image.open(BytesIO(uploaded["payload"])) as image:
        image.verify()
    assert uploaded["payload"] != state.original_images[str(state.directory / "kf3.png")]
    assert uploaded["receipt"]["payload_sha256"] == selected["sha256"]
    for key, bindings in (("1", original["uploads"]["1"]), ("2", result["uploads"]["2"])):
        graph = state.queued[int(key) - 1]
        for binding in bindings:
            assert graph[binding["node_id"]]["inputs"][binding["field"]] == binding["upload"]["filename"]
            assert binding["sha256"] == binding["upload"]["payload_sha256"]
    assert [Path(item["source_path"]).name for item in result["uploads"]["2"]] == [
        Path(selected["path"]).name, "kf4.png", "kf5.png"]

    context = result["effective_context"]
    gate = data["h3_prompt_gate"]["clips"]["2"][0]
    assert context["start_image_sha256"] == selected["sha256"]
    assert context["evidence_hash"] == result["evidence"]["sha256"]
    assert context["run_id"] == video_run["run_id"]
    assert context["clip_attempt_id"] == video_run["clips"]["2"]["attempt_id"]
    assert context["keyframes"][0]["index"] == 3
    assert gate["context"]["keyframes"] == context["keyframes"]
    assert gate["context"]["start_image_url"] == context["start_image_url"]
    assert gate["context"]["actual_state_handoff"]["effective_context_hash"] == result["effective_context_hash"]
    assert result["effective_context_hash"] == state.ai.prompt_digest(context)
    assert gate["context_hash"] == state.ai.prompt_digest(gate["context"])
    assert context["canonical_state"] == result["canonical_state"]["requirements"]
    assert context["trusted_state"] == result["trusted_handoff_state"]["confirmed_actual_fields"]
    layer = state.ai.build_handoff_continuity_layer(context)
    assert layer in gate["continuity_lock"] and layer in gate["final_prompt"]
    assert "does not certify all pixels" in layer
    assert gate["raw_candidate"] == PROMPT
    assert gate["prequeue_validation"]["passed"] is True
    assert gate["final_hash"] == state.ai.prompt_digest(gate["final_prompt"])
    assert state.comfy.resolve_h3_consumed_prompt(state.queued[1], state.mapping) == gate["final_prompt"]
    assert gate["final_prompt"].count("actual_state_handoff:") == 1
    assert "effective_context" not in state.builder.await_args_list[0].kwargs
    assert state.builder.await_args_list[1].kwargs["effective_context"] == context
    sent = json.loads(state.llm.await_args_list[1].kwargs["user_content"].split("\n\n", 1)[1])
    assert sent["actual_state_handoff"]["picture_1_description"] == context["keyframes"][0]["description"]
    assert sent["frames"][0]["description"] != state.original_plan["keyframes"][2]["description"]
    assert sent["actual_state_handoff"]["trusted_state"]
    assert "/api/files/" not in state.llm.await_args_list[1].kwargs["user_content"]
    private_plan = json.loads(data["execution"]["working_shot"]["video_director_plan"])
    assert private_plan["keyframes"] == state.original_plan["keyframes"]
    assert private_plan["transitions"] == state.original_plan["transitions"]
    assert state.builder.await_count == state.llm.await_count == state.client.queue_prompt.await_count == 2
    unchanged_shot(state)


@pytest.mark.parametrize("execution", [{"reuse": False, "audio": True}], indirect=True)
@pytest.mark.parametrize("handoff_runtime", [{}, {"pre_routed": True}], indirect=True, ids=["new-plan", "routed-plan"])
def test_shot53_long_dialogue_context_does_not_change_audiodrive_or_routing(handoff_runtime):
    state = handoff_runtime
    # Existing speech-core tests cover audible speakers; this case preserves the NONE authority.
    state.shot.description = "Two people wait through a long off-screen conversation. " * 24
    state.db.commit()
    state.before_shot = {key: getattr(state.shot, key) for key in state.before_shot}
    state.shot_updates.clear()
    enable(state, p0_contract())
    task = run(state)
    assert task.status == "completed", task.error_message
    result = assert_semantic_report(state, task, "CONTINUE")
    assert state.timeline_events == ["queue-c1", "c1-receipt", "tail-extraction", "queue-c2"]
    data = json.loads(task.metadata_json)
    for index, call in enumerate(state.builder.await_args_list, 1):
        window = state.original_plan["window_plans"][index - 1]
        gate = data["h3_prompt_gate"]["clips"][str(index)][0]
        assert call.kwargs["clip_dialogues"] == []
        assert call.kwargs["speaker_timeline"] == window["speaker_timeline"]
        assert {item["visible_speaker"] for item in gate["speaker_timeline"]} == {"NONE"}
        assert gate["context"]["characters"] == ["Ada", "Bea"]
        assert gate["audio_audit"]["passed"] is True
        for field in ("drive_audio", "final_audio"):
            assert gate["context"]["audio"][field]["path"] == window[f"{field}_path"]
        graph = state.queued[index - 1]
        assert graph["h3"] == state.graph["h3"]
        assert graph["out"] == state.graph["out"]
        assert graph["drive"]["inputs"]["audio"] == f"uploaded/drive-{index}.wav"
        assert graph["final"]["inputs"]["audio"] == f"uploaded/final-{index}.wav"
    assert state.client.upload_audio.await_count == 4
    assert all(not call.kwargs for call in state.client.upload_audio.await_args_list)
    assert result["effective_context"]["canonical_state"] == result["canonical_state"]["requirements"]
    unchanged_shot(state)


@pytest.mark.parametrize("execution", [{"reuse": False, "audio": True}], indirect=True)
def test_three_turn_same_speaker_authority_survives_c2_handoff(handoff_runtime):
    state = handoff_runtime
    plan = deepcopy(state.original_plan)
    timelines = [
        [{"start_time": 0, "end_time": 2, "visible_speaker": "NONE"},
         {"start_time": 2, "end_time": 4, "visible_speaker": "Ada"}],
        [{"start_time": 0, "end_time": 0.3, "visible_speaker": "NONE"},
         {"start_time": 0.3, "end_time": 1.7, "visible_speaker": "Ada"},
         {"start_time": 1.7, "end_time": 2, "visible_speaker": "NONE"},
         {"start_time": 2, "end_time": 3.4, "visible_speaker": "Ada"},
         {"start_time": 3.4, "end_time": 4, "visible_speaker": "NONE"}],
    ]
    for window, timeline in zip(plan["window_plans"], timelines):
        window["speaker_timeline"] = timeline
    state.shot.video_director_plan = json.dumps(plan)
    state.db.commit()
    state.original_plan = deepcopy(plan)
    state.before_shot = {key: getattr(state.shot, key) for key in state.before_shot}
    state.shot_updates.clear()
    enable(state, p0_contract())
    task = run(state)
    assert task.status == "completed", task.error_message
    data = json.loads(task.metadata_json)
    assert data["actual_state_handoff"]["can_submit_c2"] is True
    for index, timeline in enumerate(timelines, 1):
        gate = data["h3_prompt_gate"]["clips"][str(index)][0]
        assert gate["context"]["audio"]["speaker_timeline"] == timeline
        assert gate["audio_audit"]["passed"] is True
        assert state.builder.await_args_list[index - 1].kwargs["speaker_timeline"] == timeline
    assert state.client.queue_prompt.await_count == 2
    unchanged_shot(state)


def test_shot35_wrong_coarse_start_blocks_before_c1_and_extraction(handoff_runtime):
    state = handoff_runtime

    def wrong_start(reference, questions):
        observed = answer(reference, questions)
        if (reference.clip_index, reference.reference_index) == (1, 0):
            for fact in observed["facts"]:
                if fact["predicate"] == "character_location":
                    fact["value"] = "rock"
        return observed

    state.observer.observe.side_effect = wrong_start
    task = run(state)
    data = assert_no_c2(state, task, c1=False)
    assert data["visual_state_validation"]["decision"] == "BLOCK"
    assert "WRONG_START_STATE" in task.error_message
    assert len(data["visual_state_validation"]["references"]) == 6
    assert data["visual_state_validation"]["uploads"] == {}
    state.extract.assert_not_awaited()
    state.builder.assert_not_awaited()
    state.llm.assert_not_awaited()
    state.client.upload_image.assert_not_awaited()


def test_disconnected_actual_reference_workflow_is_rejected_before_c1(handoff_runtime):
    state = handoff_runtime
    state.graph["h3"]["inputs"].pop("ref_images.ref_image_0")
    state.workflow.workflow_json = json.dumps(state.graph)
    state.db.commit()
    task = run(state)
    assert_no_c2(state, task, c1=False)
    assert "HANDOFF_REFERENCE_SLOT_MISMATCH" in task.error_message
    state.extract.assert_not_awaited()
    state.observer.observe.assert_not_awaited()


def test_c2_prepared_graph_cannot_swap_actual_and_planned_reference_slots(handoff_runtime, monkeypatch):
    state = handoff_runtime
    original = state.comfy.WorkflowBuilder.build_video_workflow
    calls = []

    def swapped(builder, *args, **kwargs):
        graph = original(builder, *args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            graph["h3"]["inputs"]["ref_images.ref_image_0"] = ["kf1", 0]
        return graph

    monkeypatch.setattr(state.comfy.WorkflowBuilder, "build_video_workflow", swapped)
    task = run(state)
    assert_no_c2(state, task)
    assert "HANDOFF_REFERENCE_SLOT_MISMATCH" in task.error_message
    assert len(calls) == 2


@pytest.mark.parametrize("actual,decision,reason", [("ABSENT", "BLOCK", "PROTECTED_PROP_MISSING"),
                                                    ("OCCLUDED", "HUMAN_REVIEW", "INSUFFICIENT_EVIDENCE")])
def test_shot85_actual_bag_state_cannot_rewrite_protected_canon(handoff_runtime, actual, decision, reason):
    state = handoff_runtime
    contract = p0_contract()
    contract["invariants"].append(requirement("prop_present", "bag", protected=True))
    enable(state, contract)

    def bag(reference, questions):
        observed = answer(reference, questions)
        if "handoff-tail" in reference.source_url:
            for fact in observed["facts"]:
                if fact["predicate"] == "prop_present":
                    fact.update(state=actual, evidence="The entire bag region is clear and empty." if actual == "ABSENT"
                                else "The bag region is occluded by the actor.")
        return observed

    state.observer.observe.side_effect = bag
    task = run(state)
    data = assert_no_c2(state, task)
    result = assert_semantic_report(state, task, decision)
    assert data["visual_state_validation"]["decision"] == "PASS"
    assert set(data["visual_state_validation"]["uploads"]) == {"1"} and result["uploads"] == {}
    findings = [item for item in result["actual_observed_state"]["validation"]["findings"]
                if item["expected"]["predicate"] == "prop_present"]
    assert findings and {item["reason"] for item in findings} == {reason}
    assert {fact["state"] for item in findings for fact in item["observed"]} == {actual}
    bag_rule = result["canonical_state"]["requirements"][-1]
    assert (bag_rule["subject"], bag_rule["expected"], bag_rule["protected"]) == ("bag", "PRESENT", True)
    assert not any(fact["subject"] == "bag" for fact in result["trusted_handoff_state"]["confirmed_actual_fields"])
    assert state.builder.await_count == state.llm.await_count == 1
    assert len(state.image_uploads) == 3


@pytest.mark.parametrize("actual", ["PRESENT", "ABSENT"])
def test_shot116_critical_fine_contact_is_review_even_for_high_confidence_match(handoff_runtime, actual):
    state = handoff_runtime
    contract = p0_contract()
    contract["invariants"].extend([
        requirement("contact_relation", "Ada", "shallow_water"),
        requirement("character_location", "Ada.left_paw", "river"),
    ])
    enable(state, contract)

    def contact(reference, questions):
        observed = answer(reference, questions)
        if "handoff-tail" in reference.source_url:
            for fact in observed["facts"]:
                if fact["predicate"] == "contact_relation" or ".left_paw" in fact["subject"]:
                    fact["state"] = actual
        return observed

    state.observer.observe.side_effect = contact
    task = run(state)
    data = assert_no_c2(state, task)
    result = assert_semantic_report(state, task, "HUMAN_REVIEW")
    assert data["visual_state_validation"]["decision"] == "UNKNOWN"
    fine = [finding for finding in result["actual_observed_state"]["validation"]["findings"]
            if finding["capability"] == "advisory_only"]
    assert fine and all(finding["may_confirm"] is False and finding["may_block"] is False for finding in fine)
    assert {finding["decision"] for finding in fine} == ({"UNKNOWN"} if actual == "PRESENT" else {"WARN"})
    assert all(fact["subject"] != "Ada.left_paw" and fact["predicate"] != "contact_relation"
               for fact in result["trusted_handoff_state"]["confirmed_actual_fields"])
    assert result["can_submit_c2"] is False and result["uploads"] == {}


@pytest.mark.parametrize("missing", ["Ada", "Bea"])
def test_explicitly_missing_actual_identity_blocks_without_rewriting_cast(handoff_runtime, missing):
    state = handoff_runtime

    def missing_actor(reference, questions):
        observed = answer(reference, questions)
        if "handoff-tail" in reference.source_url:
            for fact in observed["facts"]:
                if (fact["predicate"], fact["subject"]) == ("character_present", missing):
                    fact.update(state="ABSENT", evidence="The complete visible scene contains no such actor.")
        return observed

    state.observer.observe.side_effect = missing_actor
    task = run(state)
    assert_no_c2(state, task)
    result = assert_semantic_report(state, task, "BLOCK")
    assert any(item["reason"] == "REQUIRED_CHARACTER_MISSING"
               for item in result["actual_observed_state"]["validation"]["findings"])
    assert result["canonical_state"]["characters"] == ["Ada", "Bea"]


@pytest.mark.parametrize("future", ["different-location", "new-critical-field"])
def test_original_planned_end_must_remain_compatible_without_target_rewrite(routed_handoff, future):
    state = routed_handoff
    contract = p0_contract()
    location = contract["invariants"].pop()
    end = (requirement("character_location", "Ada", "forest") if future == "different-location"
           else requirement("prop_present", "bag", protected=True))
    contract["anchors"] = [
        {"clip_index": 1, "reference_index": 2, "requirements": [location]},
        {"clip_index": 2, "reference_index": 0, "requirements": [location]},
        {"clip_index": 2, "reference_index": 2, "requirements": [end]},
    ]
    enable(state, contract)
    task = run(state)
    data = assert_no_c2(state, task)
    result = assert_semantic_report(state, task, "HUMAN_REVIEW")
    assert data["visual_state_validation"]["decision"] == "PASS"
    assert result["planned_state"]["remaining_c2_anchors"][0]["requirements"][0]["subject"] == end["subject"]
    assert result["planned_state"]["remaining_c2_anchors"][0]["requirements"][0]["value"] == end["value"]
    original_end = state.original_plan["keyframes"][-1]
    assert json.loads(data["execution"]["working_shot"]["video_director_plan"])["keyframes"][-1] == original_end
    assert result["uploads"] == {} and result["can_submit_c2"] is False


@pytest.mark.parametrize("last_state,decision", [("farm", "CONTINUE"), ("forest", "BLOCK")])
def test_earlier_representative_cannot_roll_back_a_semantically_different_true_end(routed_handoff, last_state, decision):
    state = routed_handoff

    def choose_earlier(tail):
        tail["selected"] = tail["candidates"][0]
        tail["observation_candidates"] = [tail["selected"], tail["candidates"][-1], tail["candidates"][1]]

    def last_frame(reference, questions):
        observed = answer(reference, questions)
        if "handoff-tail" in reference.source_url and reference.source_url.endswith("00000095.png"):
            for fact in observed["facts"]:
                if fact["predicate"] == "character_location":
                    fact["value"] = last_state
        return observed

    state.tail_hook = choose_earlier
    state.observer.observe.side_effect = last_frame
    task = run(state)
    if decision == "BLOCK":
        assert_no_c2(state, task)
    else:
        assert task.status == "completed", task.error_message
        assert state.image_uploads[3]["payload"] == Path(state.tail["selected"]["path"]).read_bytes()
        unchanged_shot(state)
    result = assert_semantic_report(state, task, decision)
    assert state.tail["selected"]["frame_index"] < state.tail["last_frame_index"]
    actual = result["actual_observed_state"]["validation"]
    assert len(actual["observations"]) == 3
    last_hash = state.tail["candidates"][-1]["sha256"]
    assert any(observation["image_sha256"] == last_hash for observation in actual["observations"])
    if decision == "BLOCK":
        assert any(finding["image_sha256"] == last_hash and finding["decision"] == "BLOCK" for finding in actual["findings"])
        assert result["can_submit_c2"] is False


@pytest.mark.parametrize("fault,reason", [
    ("unknown", "INSUFFICIENT_EVIDENCE"), ("low", "INSUFFICIENT_EVIDENCE"),
    ("malformed", "INVALID_OBSERVATION"), ("hash", "OBSERVATION_HASH_MISMATCH"),
    ("timeout", "OBSERVER_TIMEOUT"), ("error", "OBSERVER_ERROR"),
])
def test_untrusted_actual_vision_holds_c2_without_reusing_original_p0_answers(handoff_runtime, fault, reason):
    state = handoff_runtime

    def observe(reference, questions):
        observed = answer(reference, questions)
        if "handoff-tail" not in reference.source_url:
            return observed
        if fault == "timeout":
            raise TimeoutError("Isolated observer timeout")
        if fault == "error":
            raise RuntimeError("Isolated observer failure")
        if fault == "malformed":
            return {"image_sha256": reference.sha256, "facts": "not-a-list"}
        if fault == "hash":
            observed["image_sha256"] = "0" * 64
        for fact in observed["facts"]:
            if fault == "unknown":
                fact["state"] = "UNKNOWN"
            if fault == "low":
                fact["confidence"] = "LOW"
        return observed

    state.observer.observe.side_effect = observe
    task = run(state)
    data = assert_no_c2(state, task)
    result = assert_semantic_report(state, task, "HUMAN_REVIEW")
    assert data["visual_state_validation"]["decision"] == "PASS"
    assert {item["reason"] for item in result["actual_observed_state"]["validation"]["findings"]} == {reason}
    assert result["trusted_handoff_state"]["confirmed_actual_fields"] == []
    assert result["trusted_handoff_state"]["reference_eligible"] is False
    assert state.observer.observe.await_count == 7
    assert state.builder.await_count == state.llm.await_count == 1


def test_unconfigured_observer_holds_enabled_handoff_before_any_generation(handoff_runtime, monkeypatch):
    state = handoff_runtime
    monkeypatch.setattr(state.validator, "get_visual_state_observer", lambda: None)
    task = run(state)
    data = assert_no_c2(state, task, c1=False)
    result = data["actual_state_handoff"]
    assert (result["decision"], result["can_submit_c2"]) == ("HUMAN_REVIEW", False)
    assert result["issues"] == [{"reason": "OBSERVER_NOT_CONFIGURED"}]
    assert result["post_handoff_status"] == "NOT_MEASURED"
    state.observer.observe.assert_not_awaited()
    state.extract.assert_not_awaited()
    state.llm.assert_not_awaited()


@pytest.mark.parametrize("fault", ["no-valid-tail", "incompatible", "extraction-timeout"])
def test_unusable_or_failed_extraction_never_authorizes_c2(handoff_runtime, fault):
    state = handoff_runtime

    def unusable(tail):
        if fault == "extraction-timeout":
            raise TimeoutError("Mock decoder deadline exceeded")
        tail.update(can_use=False, technical_tail_compatible=False, reason=fault)
        if fault == "no-valid-tail":
            tail.update(selected=None, observation_candidates=[])

    state.tail_hook = unusable
    task = run(state)
    assert_no_c2(state, task)
    if fault == "extraction-timeout":
        assert "Mock decoder deadline exceeded" in task.error_message
    else:
        result = assert_semantic_report(state, task, "HUMAN_REVIEW")
        assert result["issues"][0]["reason"] == "TAIL_FRAME_UNUSABLE_OR_INCOMPATIBLE"
        assert result["actual_observed_state"]["validation"] is None
    assert state.observer.observe.await_count == 5
    state.extract.assert_awaited_once()


@pytest.mark.parametrize("fault", ["corrupt-hash", "cross-run-candidate", "cross-run-selected", "missing-true-last", "missing-selected"])
def test_tail_paths_hashes_and_true_end_must_belong_to_the_new_private_directory(routed_handoff, fault):
    state = routed_handoff

    def tamper(tail):
        if fault == "corrupt-hash":
            Path(tail["selected"]["path"]).write_bytes(b"not the observed PNG")
        elif fault.startswith("cross-run"):
            alien = state.directory / "another-run-tail.png"
            alien.write_bytes(Path(tail["selected"]["path"]).read_bytes())
            if fault == "cross-run-candidate":
                tail["observation_candidates"][0] = {**tail["observation_candidates"][0], "path": str(alien)}
            else:
                tail["selected"] = {**tail["selected"], "path": str(alien)}
        elif fault == "missing-true-last":
            tail["selected"] = tail["candidates"][0]
            tail["observation_candidates"] = tail["candidates"][:2]
        else:
            tail["selected"] = tail["candidates"][0]

    state.tail_hook = tamper
    task = run(state)
    assert_no_c2(state, task)
    assert "HANDOFF_" in task.error_message
    assert len(state.image_uploads) == 3
    assert state.builder.await_count == 1


@pytest.mark.parametrize("stage", ["tail", "observer", "model"])
@pytest.mark.parametrize("race", ["cancel", "lost-claim"])
def test_cancel_or_claim_loss_during_handoff_never_revives_or_publishes(routed_handoff, stage, race):
    state = routed_handoff
    stamp = datetime(2025, 1, 1)
    stopped = []

    def stop():
        if stopped:
            return
        if race == "cancel":
            change_task(state, status="cancelled", completed_at=stamp, result_url="/original-result.mp4",
                        error_message="Original cancellation")
        else:
            change_task(state, claim_token="replacement", attempt=8, current_step="Replacement worker owns task")
        with Session(state.engine) as reader:
            stopped.append(json.loads(reader.get(state.models.Task, "task").metadata_json))

    if stage == "tail":
        state.tail_hook = lambda tail: stop()
    elif stage == "observer":
        def observe(reference, questions):
            if "handoff-tail" in reference.source_url:
                stop()
            return answer(reference, questions)
        state.observer.observe.side_effect = observe
    else:
        async def model(**kwargs):
            if "actual_state_handoff" in kwargs["user_content"]:
                stop()
            return {"success": True, "content": PROMPT}
        state.llm.side_effect = model
    task = run(state)
    data = assert_no_c2(state, task, failed=False)
    assert len(stopped) == 1
    assert {key: value for key, value in data.items() if key != "video_observations"} == {
        key: value for key, value in stopped[0].items() if key != "video_observations"}
    if race == "cancel":
        assert (task.status, task.completed_at, task.result_url, task.error_message) == (
            "cancelled", stamp, "/original-result.mp4", "Original cancellation")
    else:
        assert (task.status, task.claim_token, task.attempt, task.current_step) == (
            "running", "replacement", 8, "Replacement worker owns task")
        assert task.completed_at is None and task.result_url is None
    assert any(event["kind"] == "late-failure" for event in data["video_observations"])
    for event in data["video_observations"]:
        assert state.execution.file_digest(event["evidence"]["path"]) == event["evidence"]["sha256"]
    assert len(state.image_uploads) == 3


@pytest.mark.parametrize("failure_kind", ["TIMEOUT", "SERVICE_ERROR"])
def test_c2_fallback_uses_actual_first_state_and_original_later_anchors(routed_handoff, failure_kind):
    state = routed_handoff
    state.llm.side_effect = [{"success": True, "content": PROMPT},
                             {"success": False, "failure_kind": failure_kind, "error": "Mock model unavailable"}]
    task = run(state)
    assert task.status == "completed", task.error_message
    result = assert_semantic_report(state, task, "CONTINUE")
    data = json.loads(task.metadata_json)
    context = result["effective_context"]
    gate = data["h3_prompt_gate"]["clips"]["2"][0]
    assert gate["origin"] == "fallback" and gate["profile"] == "deterministic_fallback"
    assert f"description={context['keyframes'][0]['description']}" in gate["raw_candidate"]
    assert state.original_plan["keyframes"][2]["description"] not in gate["raw_candidate"]
    assert context["keyframes"][1:] == state.original_plan["keyframes"][3:]
    assert gate["context"]["start_image_url"] == context["start_image_url"]
    assert data["actual_state_handoff"]["uploads"]["2"][0]["source_path"] == state.tail["selected"]["path"]
    assert state.ai.build_handoff_continuity_layer(context) in gate["final_prompt"]
    assert state.comfy.resolve_h3_consumed_prompt(state.queued[1], state.mapping) == gate["final_prompt"]
    assert gate["prequeue_validation"]["passed"] is True
    assert state.llm.await_count == 2
    unchanged_shot(state)


def test_bad_c2_model_core_is_not_rescued_by_handoff(routed_handoff):
    state = routed_handoff
    state.llm.side_effect = [{"success": True, "content": PROMPT}, {"success": True, "content": "not an H3 core"}]
    task = run(state)
    data = assert_no_c2(state, task)
    assert_semantic_report(state, task, "CONTINUE")
    assert data["h3_prompt_gate"]["clips"]["2"][0]["passed"] is False
    assert state.llm.await_count == 2
    assert len(state.image_uploads) == 3


@pytest.mark.parametrize("execution,reason", [
    ({"windows": 1, "reuse": False}, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ({"windows": 3, "reuse": False}, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ({"mode": "SINGLE_FRAME", "reuse": False}, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ({"mode": "FIRST_LAST_FRAME", "reuse": False}, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ({"only": 2, "reuse": False}, "HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI"),
    ({"reuse": True}, "HANDOFF_REQUIRES_FRESH_PROMPT"),
    ({"reuse": False}, "HANDOFF_REQUIRES_SHARED_PLANNED_BOUNDARY"),
], indirect=["execution"])
def test_unsupported_runtime_scope_is_rejected_before_queue(runtime_modules, reason):
    state = runtime_modules
    state.run_request["actual_state_handoff"] = {"enabled": True}
    enable(state, p0_contract())
    task = run(state)
    data = assert_no_c2(state, task, c1=False)
    assert reason in task.error_message
    assert "video_run" not in data and "h3_prompt_gate" not in data
    state.extract.assert_not_awaited()
    state.observer.observe.assert_not_awaited()
    state.client.upload_image.assert_not_awaited()
    state.llm.assert_not_awaited()


@pytest.mark.parametrize("p0", [None, {"enabled": False}])
def test_enabled_runtime_scope_requires_p0_before_claim(handoff_runtime, p0):
    state = handoff_runtime
    def remove_p0(data):
        data["execution"]["request"].pop("visual_state_validation")
        if p0 is not None:
            data["execution"]["request"]["visual_state_validation"] = p0
    edit_metadata(state, remove_p0)
    task = run(state)
    data = assert_no_c2(state, task, c1=False)
    assert "HANDOFF_REQUIRES_VISUAL_STATE_VALIDATION" in task.error_message
    assert "video_run" not in data
    state.extract.assert_not_awaited()


@pytest.mark.parametrize("execution", [{"windows": 1}, {"windows": 2}, {"windows": 3},
                                         {"mode": "SINGLE_FRAME"}, {"mode": "FIRST_LAST_FRAME"}], indirect=True)
@pytest.mark.parametrize("option", ["omitted", None, {"enabled": False}])
def test_disabled_and_default_handoff_leave_legacy_modes_and_recording_unchanged(runtime_modules, option):
    state = runtime_modules
    if option != "omitted":
        state.run_request["actual_state_handoff"] = option
    enable(state, {"enabled": False})
    task = run(state)
    assert task.status == "completed", task.error_message
    data = json.loads(task.metadata_json)
    assert "actual_state_handoff" not in data and "visual_state_validation" not in data
    assert all("actual-state" not in event["kind"] for event in data["video_observations"])
    for calls in data["h3_prompt_gate"]["clips"].values():
        record = calls[0]
        assert "actual_state_handoff" not in record["context"] and "planned_context_hash" not in record["context"]
        assert "actual_state_handoff" not in record["final_prompt"]
        assert record["raw_candidate"] == PROMPT and record["prequeue_validation"]["passed"] is True
    assert all("effective_context" not in call.kwargs for call in state.builder.await_args_list)
    assert all(not call.kwargs for call in state.client.upload_image.await_args_list)
    assert (state.directory / "start.png").read_bytes() == b"start.png"
    state.extract.assert_not_awaited()
    state.observer.observe.assert_not_awaited()
    state.llm.assert_not_awaited()
    unchanged_shot(state)


@pytest.mark.parametrize("camel", [False, True])
def test_request_schema_defaults_and_aliases_do_not_enable_handoff(pure, monkeypatch, camel):
    schema = load_module(monkeypatch, "app.schemas.shot", "app/schemas/shot.py")
    baseline = schema.GenerateVideoRequest()
    assert baseline.actual_state_handoff is baseline.visual_state_validation is None
    assert baseline.skip_llm_when_prompt_exists is False
    assert baseline.selected_mode is None
    keys = ("actualStateHandoff", "visualStateValidation", "skipLlmWhenPromptExists") if camel else (
        "actual_state_handoff", "visual_state_validation", "skip_llm_when_prompt_exists")
    request = schema.GenerateVideoRequest.model_validate({keys[0]: {"enabled": True}, keys[1]: p0_contract(), keys[2]: False})
    assert request.actual_state_handoff.enabled is True and request.visual_state_validation.enabled is True
    assert request.model_dump()["actual_state_handoff"] == {"enabled": True}
    assert request.model_dump(by_alias=True)["actualStateHandoff"] == {"enabled": True}


def test_noncritical_fine_fields_remain_excluded_without_becoming_canonical_facts(routed_handoff):
    state = routed_handoff
    contract = p0_contract()
    contract["invariants"].append(requirement("facing_direction", "Ada", "left", critical=False))
    enable(state, contract)
    task = run(state)
    assert task.status == "completed", task.error_message
    result = assert_semantic_report(state, task, "WARN")
    trusted = result["trusted_handoff_state"]
    assert trusted["reference_eligible"] is True
    assert trusted["excluded_fields"] and all(not item["may_confirm"] for item in trusted["excluded_fields"])
    assert {fact["predicate"] for fact in trusted["confirmed_actual_fields"]} == {"character_present", "character_location"}
    projected = state.ai._handoff_prompt_payload(result["effective_context"])
    assert all(fact["predicate"] != "facing_direction" for fact in projected["trusted_state"])
    assert projected["canonical_state"][-1]["predicate"] == "facing_direction"
    assert projected["canonical_state"][-1]["expected"] == "PRESENT"
    unchanged_shot(state)


@pytest.mark.parametrize("fault", ["bundle", "bundle-new-field", "saved-bundle", "saved-hash", "can-submit",
                                    "frozen-request", "source-receipt", "c1-receipt"])
def test_mutated_authority_before_c2_queue_rejects_without_extra_submission(routed_handoff, fault):
    state = routed_handoff
    upload = state.client.upload_image.side_effect
    mutated = []

    async def mutate_after_upload(path, *, payload=None, upload_name=None):
        receipt = await upload(path, payload=payload, upload_name=upload_name)
        if len(state.image_uploads) == 6:
            if fault in {"bundle", "bundle-new-field"}:
                context = state.builder.await_args_list[1].kwargs["effective_context"]
                if fault == "bundle":
                    context["trusted_state"][0]["value"] = "unapproved"
                else:
                    context["keyframes"][0]["new_unapproved_field"] = {"claim": "not observed"}
            else:
                def tamper(data):
                    root = data["actual_state_handoff"]
                    if fault == "saved-bundle":
                        root["effective_context"]["trusted_state"][0]["value"] = "unapproved"
                        root["effective_context_hash"] = state.ai.prompt_digest(root["effective_context"])
                    elif fault == "saved-hash":
                        root["effective_context_hash"] = "0" * 64
                    elif fault == "can-submit":
                        root["can_submit_c2"] = False
                    elif fault == "frozen-request":
                        for record in (data["execution"], data["video_run"]):
                            record["request"]["actual_state_handoff"]["enabled"] = False
                    elif fault == "source-receipt":
                        root["source"]["predecessor_receipt"]["sha256"] = "0" * 64
                    else:
                        data["video_run"]["clips"]["1"]["receipt"]["sha256"] = "0" * 64
                edit_metadata(state, tamper)
            mutated.append(True)
        return receipt

    state.client.upload_image.side_effect = mutate_after_upload
    task = run(state)
    assert_no_c2(state, task, failed=fault != "frozen-request")
    assert mutated == [True]
    if fault == "frozen-request":
        assert task.status == "running" and task.completed_at is None and task.result_url is None
    else:
        assert any(code in task.error_message for code in (
            "HANDOFF_CONTEXT_NOT_AUTHORIZED", "HANDOFF_PREDECESSOR_CHANGED", "CLIP_RECEIPT_CHANGED"))
    assert state.llm.await_count == 2


@pytest.mark.parametrize("stage", ["before-extraction", "during-extraction"])
def test_c1_receipt_must_still_verify_before_and_after_tail_extraction(handoff_runtime, monkeypatch, stage):
    state = handoff_runtime

    def mutate():
        edit_metadata(state, lambda data: data["video_run"]["clips"]["1"]["receipt"].update(sha256="0" * 64))

    if stage == "before-extraction":
        prepare = state.execution._prepare_actual_handoff
        async def before(*args, **kwargs):
            mutate()
            return await prepare(*args, **kwargs)
        monkeypatch.setattr(state.execution, "_prepare_actual_handoff", before)
    else:
        state.tail_hook = lambda tail: mutate()
    task = run(state)
    assert_no_c2(state, task)
    assert "CLIP_RECEIPT_CHANGED" in task.error_message
    assert state.extract.await_count == int(stage == "during-extraction")
    assert state.observer.observe.await_count == 5
    assert state.llm.await_count == 1 and len(state.image_uploads) == 3


@pytest.mark.parametrize("stage", ["analysis", "model", "upload"])
def test_tampered_c2_png_is_rejected_or_uploads_only_frozen_observed_bytes(routed_handoff, monkeypatch, stage):
    state = routed_handoff
    changed = []

    def replace():
        selected = state.tail["selected"]
        path = Path(selected["path"])
        changed.append(path.read_bytes())
        Image.new("RGB", (8, 6), (20, 250, 30)).save(path, "PNG")
        assert state.execution.file_digest(path) != selected["sha256"]

    if stage == "analysis":
        resolve = state.handoff.resolve_handoff
        async def after_analysis(**kwargs):
            result = await resolve(**kwargs)
            assert result["can_submit_c2"] is True
            replace()
            return result
        monkeypatch.setattr(state.handoff, "resolve_handoff", after_analysis)
    elif stage == "model":
        async def model(**kwargs):
            if "actual_state_handoff" in kwargs["user_content"]:
                replace()
            return {"success": True, "content": PROMPT}
        state.llm.side_effect = model
    else:
        upload = state.client.upload_image.side_effect
        async def during_upload(path, *, payload=None, upload_name=None):
            if "handoff-tail" in str(path):
                replace()
            return await upload(path, payload=payload, upload_name=upload_name)
        state.client.upload_image.side_effect = during_upload
    task = run(state)
    assert len(changed) == 1
    selected_hash = state.tail["selected"]["sha256"]
    observed = next(call.args[0] for call in state.observer.observe.await_args_list if call.args[0].sha256 == selected_hash)
    assert observed.payload == changed[0]
    if task.status == "failed":
        assert_no_c2(state, task)
        assert "HANDOFF_SELECTED_FRAME_CHANGED" in task.error_message
        assert len(state.image_uploads) == 3
    else:
        assert task.status == "completed", task.error_message
        assert state.image_uploads[3]["payload"] == observed.payload
        assert state.image_uploads[3]["receipt"]["payload_sha256"] == observed.sha256
        assert state.client.queue_prompt.await_count == 2
        unchanged_shot(state)


def test_caller_mutation_and_bogus_enqueue_arguments_do_not_replace_frozen_sources(routed_handoff):
    state = routed_handoff
    contract = enable(state, p0_contract())
    contract["invariants"][0]["subject"] = "Replacement"
    contract["enabled"] = False
    state.run_request.update(actual_state_handoff={"enabled": False}, selected_mode="SINGLE_FRAME", only_window_index=1,
                             skip_llm_when_prompt_exists=True, workflow_id="wrong-workflow")
    task = run(state)
    assert task.status == "completed", task.error_message
    result = assert_semantic_report(state, task, "CONTINUE")
    assert result["effective_context"]["canonical_state"][0]["subject"] == "Ada"
    assert state.client.queue_prompt.await_count == 2 and state.llm.await_count == 2
    assert json.loads(task.metadata_json)["video_run"]["mode"] == "MULTI_KEYFRAME"
    unchanged_shot(state)
