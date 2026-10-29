"""Offline Phase A: real saved inputs/resources, fake director only, no network."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.services import h3_single_stage_experiment as stage
from app.services.h3_native_prompt import SECTIONS, dialogue_events, sections


FIXTURES = Path(__file__).parent / "fixtures/h3_multi_keyframe_phase_a"
NAMES = ["shot12_c1_generate", "shot3_c6_extend", "shot5_c2_temporal_extend"]


def saved(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


def refresh_proof(snapshot, field):
    proof = {"frozen_record": "frozen_record_sha256", "canonical_plan": "canonical_sha256",
             "builder_input": "builder_input_sha256"}[field]
    snapshot["source"][proof] = stage._snapshot_digest(snapshot[field])


def mock_director(prepared):
    # A formatting fixture, explicitly not a new director plan or semantic proof.
    return ("detailed_description:\nOFFLINE MOCK — director semantics not reviewed.\n"
            + "\n".join(f"[[SPEECH_{i}]]" for i in range(1, len(prepared["canonical"]) + 1))
            + "\n\noverall_soundscape:\nOFFLINE MOCK — soundscape not reviewed.")


@pytest.fixture(autouse=True)
def no_real_clients(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Real service calls are forbidden in Phase A tests")
    from app.services.llm_service import LLMService
    from app.services.comfyui.client import ComfyUIClient
    monkeypatch.setattr(LLMService, "chat_completion", forbidden)
    monkeypatch.setattr(ComfyUIClient, "queue_prompt", forbidden)


@pytest.fixture(scope="module")
def prepared_samples():
    result = {}
    for name in NAMES:
        snapshot = saved(name)
        before = deepcopy(snapshot)
        result[name] = stage.prepare_multi_keyframe_phase_a(snapshot)
        assert snapshot == before  # No historical dictionaries mutated.
        assert result[name]["status"] == "PREPARED", result[name]
    return result


@pytest.mark.parametrize("name,capability,owned,refs,previews", [
    (NAMES[0], "GENERATE", 5, 9, 9),
    (NAMES[1], "EXTEND", 4, 7, 12),
    (NAMES[2], "TEMPORAL_EXTEND", 3, 5, 11),
])
def test_real_inputs_and_previews(prepared_samples, name, capability, owned, refs, previews):
    result = prepared_samples[name]
    payload = result["llm_input"]
    assert payload["route"] == "multi" and payload["builder"] == "13"
    assert payload["clip"]["capability"] == capability
    assert len(payload["canonical"]["owned_visual_states"]) == owned
    assert len(result["reference_manifest"]["references"]) == refs
    assert len(result["images"]) == previews
    assert all(i["url"].startswith("data:image/") for i in result["images"])
    assert all(i["source_sha256"] for i in result["images"])
    assert result["saved_execution_preflight"]["passed"]
    assert result["source"]["execution_decision_owner"] == "SAVED_14_NOT_NEW_13"
    assert not result["submission_authorized"] and not result["production_preflight_passed"]
    # Director receives facts/projections, not the prior optimizer's planning DSL.
    assert "execution_phases" not in json.dumps(payload)
    assert "authority_echo" not in json.dumps(payload)
    assert "raw_h3_prompt" not in payload
    assert payload["execution_budget"]["unknown_execution_cost"].startswith("NOT_ESTIMATED")


@pytest.mark.parametrize("name", NAMES)
def test_six_sections_authority_and_no_director_repair(prepared_samples, name):
    prepared = prepared_samples[name]
    text = mock_director(prepared)
    result = stage.compile_multi_keyframe_phase_a(prepared, text)
    assert result["status"] == "CANDIDATE_FOR_REVIEW"
    parts = sections(result["prompt"])
    assert list(parts) == list(SECTIONS)
    assert parts["non_diegetic_music"] == "N/A"
    assert all(result["review"]["structure"].values())
    assert all(result["review"]["structured_authority"].values())
    assert [(e["speaker"], e["exact_dialogue"]) for e in dialogue_events(result["prompt"])] == [
        (e["speaker"], e["exact_dialogue"]) for e in prepared["canonical"]]
    assert result["director_text"] == text
    assert parts["overall_soundscape"] == "OFFLINE MOCK — soundscape not reviewed."
    assert result["director_semantics"]["status"] == "REVIEW_REQUIRED"
    assert not result["production_preflight_passed"] and not result["submission_authorized"]
    # A structure pass never turns missing handoff/director evidence into PASS.
    assert not result["review"]["native_prompt_diagnostics"]["speaker_switch_camera_evidence"]


@pytest.mark.parametrize("name", NAMES[1:])
def test_carry_in_and_previous_av_coordinates(prepared_samples, name):
    result = prepared_samples[name]
    payload = result["llm_input"]
    snapshot = saved(name)
    index = payload["clip"]["carry_in_state_index"]
    state = next(s for s in snapshot["canonical_plan"]["keyframes"] if s["index"] == index)
    assert payload["canonical"]["carry_in_visual_state"]["description"] == state["description"]
    assert len(payload["previous_av"]["preview_frames"]) == 5
    assert result["continuation"]["overlap_seconds"] == 1.625
    frames = payload["previous_av"]["preview_frames"]
    assert frames[0]["source_frame_index"] == result["continuation"]["source_start_frame"]
    assert frames[-1]["source_frame_index"] == result["continuation"]["source_end_frame_exclusive"] - 1
    assert frames[0]["time_base"] == "PREVIOUS_AV_SOURCE_SECONDS"
    expected = snapshot["frozen_record"]["output"]["av_timeline"]["dialogue_events"]
    assert result["timing"]["dialogue_events"] == [
        {k: e[k] for k in ("id", "speaker", "optimized_start", "optimized_end")} for e in expected]
    assert all(e["optimized_start"] >= 1.625 for e in expected)
    assert all(result["continuation_checks"].values())


@pytest.mark.parametrize("name", NAMES)
def test_director_canonical_projection_excludes_only_old_image_instructions(prepared_samples, name):
    from app.services.video_director_ai import _strip_keyframe_generation_prompt, strip_media_refs
    snapshot = saved(name)
    result = prepared_samples[name]
    canonical = result["llm_input"]["canonical"]
    states = {s["index"]: s for s in snapshot["canonical_plan"]["keyframes"]}
    clip = result["llm_input"]["clip"]
    expected = [states[index] for index in clip["visual_state_indexes"]]
    assert canonical["owned_visual_states"] == _strip_keyframe_generation_prompt(strip_media_refs(expected))
    carry = states.get(clip.get("carry_in_state_index"))
    assert canonical["carry_in_visual_state"] == _strip_keyframe_generation_prompt(strip_media_refs(carry))
    assert '"prompt_text"' not in json.dumps(result["llm_input"])
    assert "<image_" not in json.dumps(result["llm_input"])
    for projected in canonical["transitions"]:
        original = next(t for t in snapshot["canonical_plan"]["transitions"]
                        if t["segment_index"] == projected["segment_index"])
        for key in ("start_time", "end_time", "transition_description"):
            assert projected[key] == original[key]
    if name == NAMES[1]:
        assert all(s.get("prompt_text") for s in expected) and carry.get("prompt_text")


@pytest.mark.parametrize("name", NAMES)
def test_director_picture_namespace_is_actual_send_order(prepared_samples, name):
    result = prepared_samples[name]
    payload = result["llm_input"]
    references = payload["reference_manifest"]["references"]
    ordinary = [image for image in result["images"]
                if image["reference_type"] not in {"PREVIOUS_VIDEO_FRAME", "TEMPORAL_ANCHOR"}]
    assert [r["picture"] for r in references] == [image["logical_id"] for image in ordinary]
    assert [r["slot"] for r in references] == list(range(1, len(ordinary) + 1))
    assert [r["picture"] for r in payload["picture_mapping"]] == [r["picture"] for r in references]
    wire = json.dumps(payload)
    for key in ("source_picture", "source_slot", "picture_projection", "excluded_references", "visual_reference_description"):
        assert f'"{key}"' not in wire
    # Audit/physical manifests retain originals; only the Director presentation changes.
    assert all("source_picture" in r for r in result["reference_manifest"]["references"])
    if name == NAMES[1]:
        assert len(references) == 7 and len(result["images"]) == 12
        assert [i["logical_id"] for i in result["images"][7:]] == [f"PreviousFrame{i}" for i in range(1, 6)]
        assert "<Picture 8>" not in wire and "<Picture 9>" not in wire
        catalog = {a["anchor_id"]: a for a in payload["frozen_execution"]["anchor_catalog"]}
        assert {key: a["picture"] for key, a in catalog.items()} == {
            "KF9": "<Picture 1>", "KF10": None, "KF11": None, "KF12": "<Picture 2>"}
        assert references[3]["kind"] == "CHARACTER_IDENTITY" and references[3]["source_name"] == "皇帝"


@pytest.mark.parametrize("name", NAMES)
def test_frozen_anchor_times_domains_and_dropped_facts(prepared_samples, name):
    result = prepared_samples[name]
    payload = result["llm_input"]
    frozen = payload["frozen_execution"]
    old = saved(name)["frozen_record"]["output"]["av_timeline"]["anchors"]
    keys = ("id", "decision", "original_time", "optimized_time")
    assert [{k: a[k] for k in keys} for a in frozen["anchor_decisions"]] == [
        {k: a[k] for k in keys} for a in old]
    for choice, saved_choice in zip(frozen["anchor_decisions"], old):
        assert choice["original_time_base"] == "CLIP_STORY_SECONDS"
        assert choice["original_time_basis"] == "CANONICAL_STATE_MINUS_CLIP_START"
        assert choice["optimized_time_base"] == "GENERATION_LOCAL_SECONDS"
        relation = saved_choice.get("arrival_relation")
        assert choice["arrival_relation"] == ({k: relation[k] for k in ("dialogue_id", "position")} if relation else None)
        if choice["decision"] == "DROP":
            assert choice["arrival_constraint"] == "RELEASED" and choice["optimized_time"] is None
            index = next(a["canonical_state_index"] for a in frozen["anchor_catalog"] if a["anchor_id"] == choice["id"])
            assert index in {state["index"] for state in payload["canonical"]["owned_visual_states"]}
        else:
            assert choice["arrival_constraint"] == "FROZEN"
    if name == NAMES[1]:
        assert frozen["anchor_decisions"][0]["optimized_time"] == 1.85
        assert frozen["anchor_decisions"][-1]["optimized_time"] == 9.7
        assert 1.85 - result["continuation"]["overlap_seconds"] == pytest.approx(0.225)
        assert {s["index"] for s in payload["canonical"]["owned_visual_states"]} == {9, 10, 11, 12}


@pytest.mark.parametrize("name", NAMES[1:])
def test_previous_av_explicit_source_to_shared_prefix_coordinates(prepared_samples, name):
    result = prepared_samples[name]
    previous = result["llm_input"]["previous_av"]
    contract = result["continuation"]
    coordinates = previous["time_coordinates"]
    assert coordinates["source_time_base"] == "PREVIOUS_AV_SOURCE_SECONDS"
    assert coordinates["target_time_base"] == "GENERATION_LOCAL_SECONDS"
    assert coordinates["target_shared_prefix_interval"] == [0.0, 1.625]
    assert coordinates["source_context_interval"] == [contract["source_start_frame"] / contract["fps"],
                                                      contract["source_end_frame_exclusive"] / contract["fps"]]
    for frame in previous["preview_frames"]:
        assert frame["source_video_time_seconds"] == frame["source_frame_index"] / contract["fps"]
        assert frame["generation_local_time_seconds"] == (frame["source_frame_index"] - contract["source_start_frame"]) / contract["fps"]
        assert 0 <= frame["generation_local_time_seconds"] < 1.625


def test_untraceable_anchor_original_time_is_unknown_not_invented(prepared_samples):
    # Exercise presentation independently, not a bypass of prepare's authority checks.
    payload = deepcopy(prepared_samples[NAMES[1]]["llm_input"])
    snapshot = saved(NAMES[1])
    payload["reference_manifest"] = deepcopy(prepared_samples[NAMES[1]]["reference_manifest"])
    payload["frozen_execution"]["anchor_catalog"] = snapshot["frozen_record"]["runtime_input"]["immutable_authority"]["anchor_policy"]["catalog"]
    payload["frozen_execution"]["anchor_decisions"][0]["original_time"] = 99.0
    before = deepcopy(payload)
    projected = stage._phase_a_director_input(payload, snapshot["frozen_record"]["output"]["av_timeline"]["anchors"])
    assert payload == before
    anchor = projected["frozen_execution"]["anchor_decisions"][0]
    assert anchor["original_time"] == 99.0 and anchor["original_time_base"] == "UNKNOWN"
    assert anchor["optimized_time"] == 1.85


def test_keep_retime_drop_and_temporal_alias(prepared_samples):
    extend = prepared_samples[NAMES[1]]
    decisions = extend["llm_input"]["frozen_execution"]["anchor_decisions"]
    assert {a["decision"] for a in decisions} == {"RETIME", "DROP"}
    refs = extend["reference_manifest"]["references"]
    assert [r["slot"] for r in refs] == list(range(1, 8))
    assert [r["source_slot"] for r in refs] == sorted(r["source_slot"] for r in refs)
    assert all(r["kind"] == "DIRECTOR_VISUAL_ANCHOR" for r in extend["reference_manifest"]["excluded_references"])
    temporal = prepared_samples[NAMES[2]]
    decisions = {a["id"]: a for a in temporal["llm_input"]["frozen_execution"]["anchor_decisions"]}
    assert decisions["KF5"]["decision"] == "KEEP"
    assert decisions["KF6"]["optimized_time"] == decisions["clip-2-KF6"]["optimized_time"] == 15.45
    assert temporal["temporal_manifest"]["anchors"][0]["time_seconds"] == 15.45
    assert all(r["kind"] != "TEMPORAL_ANCHOR" for r in temporal["picture_mapping"])
    assert any(i["logical_id"] == "TemporalAnchor:clip-2-KF6" for i in temporal["images"])
    assert {r["picture"] for r in temporal["picture_mapping"]} == {f"<Picture {i}>" for i in range(1, 6)}


def test_cross_clip_long_transition_scope(prepared_samples):
    payload = prepared_samples[NAMES[1]]["llm_input"]
    cross = [t for t in payload["canonical"]["transitions"] if t.get("projection_mode") == "CROSS_CLIP_OPENING"]
    assert cross
    for transition in cross:
        assert transition["end_time"] > payload["clip"]["end_time"]
        assert not transition["target_state_owned"] and transition["execution_scope"]
        assert transition["clip_local_end_time"] <= payload["execution_budget"]["story_duration"] + 1e-6
        assert transition["transition_description"]  # Full action/camera source retained.


@pytest.mark.parametrize("case", ["missing_timing", "wrong_speaker", "changed_text", "missing_anchor",
    "alias_arrival", "unknown_overlap", "missing_previous", "missing_identity", "music",
    "missing_carry", "changed_transition", "picture_binding", "missing_reference", "changed_source"])
def test_unsupported_or_invalid_inputs_never_assume_defaults(case):
    data = saved(NAMES[2])
    record = data["frozen_record"]
    timeline = record["output"]["av_timeline"]
    if case == "missing_timing": timeline.pop("optimized_duration")
    elif case == "wrong_speaker": timeline["dialogue_events"][0]["speaker"] = "<Subject 99>"
    elif case == "changed_text":
        data["canonical_plan"]["dialogue_timeline_source"][9]["text"] = "未授权的新台词"
    elif case == "missing_anchor": timeline["anchors"].pop()
    elif case == "alias_arrival": timeline["anchors"][-1]["optimized_time"] += 1
    elif case == "unknown_overlap": record["runtime_input"]["immutable_authority"]["continuation"]["overlap_seconds"] = None
    elif case == "missing_previous": data["previous_video_path"] = None
    elif case == "missing_identity": data["builder_input"]["shot"]["official_character_appearances"] = {}
    elif case == "music":
        record["output"]["optimized_prompt"] = record["output"]["optimized_prompt"].replace("non_diegetic_music:\nN/A", "non_diegetic_music:\nOrchestral music.")
    elif case == "missing_carry":
        data["canonical_plan"]["keyframes"] = [s for s in data["canonical_plan"]["keyframes"] if s["index"] != 4]
    elif case == "changed_transition": data["canonical_plan"]["transitions"][3]["transition_description"] = "改变剧情"
    elif case == "picture_binding": data["reference_manifest"]["references"][0]["source_name"] = "错误角色"
    elif case == "missing_reference": data["reference_manifest"]["references"].pop()
    elif case == "changed_source": data["source"]["frozen_record_sha256"] = "wrong"
    if case != "changed_source":
        for field in ("frozen_record", "canonical_plan", "builder_input"):
            refresh_proof(data, field)
    result = stage.prepare_multi_keyframe_phase_a(data)
    assert result["status"] == "NOT_COVERED", (case, result.get("status"))
    assert result["reasons"] and "prompt" not in result and not result["submission_authorized"]


@pytest.mark.parametrize("kind", ["repeat", "missing", "reorder", "redefine"])
def test_director_cannot_redefine_facts(prepared_samples, kind):
    prepared = prepared_samples[NAMES[0]]
    text = mock_director(prepared)
    if kind == "repeat": text = text.replace("[[SPEECH_1]]", "[[SPEECH_1]][[SPEECH_1]]")
    elif kind == "missing": text = text.replace("[[SPEECH_1]]", "")
    elif kind == "reorder": text = text.replace("[[SPEECH_1]]", "[[SPEECH_2]]", 1)
    else: text += "\n<Subject 99> says new dialogue."
    assert stage.compile_multi_keyframe_phase_a(prepared, text)["status"] == "NOT_COVERED"


def test_explicit_one_call_route_and_no_retry(prepared_samples, monkeypatch):
    prepared = prepared_samples[NAMES[0]]
    monkeypatch.setattr(stage, "prepare_multi_keyframe_phase_a", lambda _: prepared)
    class Fake:
        def __init__(self, success): self.calls, self.success = [], success
        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            return {"success": self.success, "content": mock_director(prepared)}
    for success in (True, False):
        client = Fake(success)
        result = asyncio.run(stage.preview_multi_keyframe_phase_a({}, llm=client))
        assert len(client.calls) == 1
        assert client.calls[0]["task_type"] == "h3_multi_keyframe_prompt"
        assert "#13 Multi-Keyframe" in client.calls[0]["system_prompt"]
        assert client.calls[0]["images"] == prepared["images"]
        assert not result["submission_authorized"]
    monkeypatch.setattr(stage, "prepare_multi_keyframe_phase_a", lambda _: stage._phase_a_not_covered("missing"))
    client = Fake(True)
    asyncio.run(stage.preview_multi_keyframe_phase_a({}, llm=client))
    assert not client.calls


def test_no_production_dispatch():
    root = Path(__file__).resolve().parents[1]
    for directory in (root / "app/api", root / "app/services"):
        for path in directory.rglob("*.py"):
            if path.name == "h3_single_stage_experiment.py": continue
            assert "preview_multi_keyframe_phase_a" not in path.read_text()
    formal = (root / "tests/fixtures/retired_h3/13_MiniMax_H3_MultiKeyframe_VideoPrompt_V1.txt").read_text()
    assert "H3_MULTI_KEYFRAME_PHASE_A" not in formal
