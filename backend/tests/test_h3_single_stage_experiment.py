"""No LLM or ComfyUI calls: isolated six-section #11/#12/#13 preview checks."""

import asyncio
import copy
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import h3_single_stage_experiment as stage
from app.services import video_director_ai as builder
from app.services.h3_anchor_policy import project_reference_manifest
from app.services.h3_native_prompt import _DIALOGUE_PATTERN, dialogue_events, sections
from app.services.shot_video_service import _project_semantic_clip_transitions


SAVED = Path(__file__).parent / "fixtures/h3_shot12_c2_saved_preflight.json"
B_PROMPT = Path("/Volumes/Data/tmp/shot12_c2_timecue_ab_20261014/B_prompt.txt")
DB = Path(__file__).resolve().parents[1] / "novelflow.db"
TASK_ID = "c47a9bf6-9410-444e-bc9d-b249390e9101"
TIMES = [(1.75, 3.75), (3.95, 5.45), (5.9, 7.4), (7.85, 9.85),
         (10.05, 13.55), (13.95, 15.2), (15.55, 16.05)]


def saved_shot12():
    if not SAVED.exists() or not B_PROMPT.exists():
        pytest.skip("Shot 12 C2 saved offline resources unavailable")
    case = json.loads(SAVED.read_text())
    canonical = case["authority"]["dialogue_events"]
    prompt = B_PROMPT.read_text()
    spoken = list(_DIALOGUE_PATTERN.finditer(prompt))
    assert len(spoken) == len(canonical) == 7
    for match, event in zip(reversed(spoken), reversed(canonical)):
        prompt = prompt[:match.start()] + f"[[{event['id']}]]" + prompt[match.end():]
    assert list(sections(prompt)) == list(sections(B_PROMPT.read_text()))
    timing = {"optimized_duration": 16.5, "dialogue_events": [
        {"id": event["id"], "speaker": event["speaker"],
         "optimized_start": start, "optimized_end": end}
        for event, (start, end) in zip(canonical, TIMES)]}
    return case, prompt, timing


class FakeLLM:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True, "content": self.content}


def previews(monkeypatch, continuation=None):
    def proxy(_source, **metadata):
        return {**metadata, "source_sha256": "picture-sha",
                "proxy_url": "/preview.jpg", "url": "data:image/jpeg;base64,Zg=="}

    def previous(_path, frames):
        assert frames == 39
        return [{"logical_id": f"PreviousFrame{i}", "source_sha256": "frame-sha",
                 "source_video_sha256": continuation["source_sha256"],
                 "proxy_url": "/previous.jpg", "url": "data:image/jpeg;base64,Zg=="}
                for i in range(1, 6)]

    monkeypatch.setattr(stage, "vision_proxy", proxy)
    monkeypatch.setattr(stage, "previous_video_frames", previous)


def test_shot12_c2_saved_16_5s_one_call_and_authority(monkeypatch):
    case, model_output, timing = saved_shot12()
    continuation = case["authority"]["continuation"]
    previews(monkeypatch, continuation)
    names = case["authority"]["subject_bindings"]
    assigned = [{"id": item["id"], "speaker": names[item["speaker"]],
                 "text": item["exact_dialogue"], "duration": item["duration"]}
                for item in case["authority"]["dialogue_events"]]
    refs = [{"slot": i, "kind": ref["type"], "source_name": ref["source_name"],
             "image_url": f"/saved/picture_{i}.png"}
            for i, ref in enumerate(case["authority"]["reference_bindings"], 1)]
    llm = FakeLLM(model_output)
    result = asyncio.run(stage.preview_single_stage_h3(
        payload={"clip": {"capability": "EXTEND"},
                 "visual_controls": [{"index": 6, "description": "皇帝重新挺直"}],
                 "transitions": [{"canonical_source_id": "transition_5", "execution_scope": "Only unfinished action"}],
                 "dialogue_timeline_source": assigned},
        route="single", template_type="h3_single_frame_prompt", novel_id="novel", chapter_id="chapter",
        assigned_dialogues=assigned, visible_characters=list(names.values()),
        picture_mapping=[{"picture_index": i} for i in range(1, 9)],
        reference_manifest={"references": refs}, temporal_anchors=[],
        experiment={"verified_timing": timing, "verified_continuation": continuation,
                    "previous_video_path": "/saved/previous.mp4"}, llm=llm))
    assert len(llm.calls) == 1 and llm.calls[0]["task_type"] == "h3_single_frame_prompt"
    assert len(llm.calls[0]["images"]) == 13
    assert result["image_input_order"] == [f"<Picture {i}>" for i in range(1, 9)] + [f"PreviousFrame{i}" for i in range(1, 6)]
    assert result["anchor_selection"] == "NOT_REQUIRED" and result["ready_for_h3_experiment"]
    assert all(result["contract_checks"].values()) and all(result["continuation_checks"].values())
    assert result["verified_timing"] == timing
    assert [(item["speaker"], item["exact_dialogue"]) for item in dialogue_events(result["prompt"])] == [
        (item["speaker"], item["exact_dialogue"]) for item in case["authority"]["dialogue_events"]]
    assert re.findall(r"\bD\d+\b", result["prompt"]) == [f"D{i}" for i in range(7, 14)]
    stripped = result["prompt"]
    for match, event in zip(reversed(list(_DIALOGUE_PATTERN.finditer(stripped))),
                            reversed(case["authority"]["dialogue_events"])):
        stripped = stripped[:match.start()] + f"[[{event['id']}]]" + stripped[match.end():]
    assert stripped == model_output  # All non-dialogue prose and Pictures are unchanged.
    assert result["llm_input"]["single_stage_experiment"]["previous_av"]["overlap_seconds"] == 1.625
    assert result["llm_input"]["single_stage_experiment"]["speaker_ids"] == {
        "<Subject 1>": "S1", "<Subject 2>": "S2"}
    assert result["reference_manifest"] == {"references": refs}
    assert result["submission_authorized"] is False


@pytest.mark.parametrize("route,states", [
    ("single", [{"index": 1, "role": "START", "time_seconds": 0}]),
    ("endpoint", [{"index": 1, "role": "START", "time_seconds": 0},
                  {"index": 2, "role": "END", "time_seconds": 4}]),
    ("multi", [{"index": 1, "role": "START", "time_seconds": 0},
               {"index": 2, "role": "INTERMEDIATE", "time_seconds": 2},
               {"index": 3, "role": "END", "time_seconds": 4}]),
])
def test_existing_builder_three_routes_explicit_preview_no_write(monkeypatch, route, states):
    body = ("subject_definitions:\n<Subject 1> is Mira, in the room.\n\n"
            "summary:\nA 4-second room scene.\n\nretention_analysis:\nKeep Mira's identity.\n\n"
            "detailed_description:\nMira waits beside the door.\n\n"
            "overall_soundscape:\nSoft room ambience.\n\nnon_diegetic_music:\nN/A")
    llm = FakeLLM(body)
    monkeypatch.setattr(builder, "LLMService", lambda: llm)
    monkeypatch.setattr(builder, "resolve_prompt_template", lambda *_args: SimpleNamespace(template="production", name="production"))
    monkeypatch.setattr(builder, "get_visual_prop_names", lambda *_args: [])
    shot = SimpleNamespace(id="shot", index=1, chapter_id="chapter", description="room",
                           video_description="", duration=4, continuity_mode="NORMAL",
                           characters=json.dumps(["Mira"]), scene="room", props="[]",
                           dialogues="[]", video_director_plan="{}")
    clip = {"clip_index": 1, "start_time": 0, "end_time": 4, "capability": "GENERATE",
            "visual_state_indexes": [s["index"] for s in states], "carry_in_state_index": None}
    commits = []
    result = asyncio.run(builder.build_h3_video_prompt(
        db=SimpleNamespace(commit=lambda: commits.append(True)), novel=SimpleNamespace(id="novel"), shot=shot,
        selected_mode=None, clip=clip, workflow_capability={}, workflow_type="multi_reference_video",
        workflow_name="H3", start_image_url=None, keyframes=states, transitions=[],
        clip_dialogues=[], reference_images=[], video_reference_manifest={"references": []},
        resolved_dialogue_timeline=[], single_stage_experiment={"enabled": True,
            "verified_timing": {"optimized_duration": 4, "dialogue_events": []}}))
    assert result["route"] == route and result["ready_for_h3_experiment"]
    assert llm.calls[0]["task_type"] == {"single": "h3_single_frame_prompt",
                                          "endpoint": "h3_first_last_frame_prompt",
                                          "multi": "h3_multi_keyframe_prompt"}[route]
    assert len(llm.calls) == 1 and not commits and not hasattr(shot, "video_ai_calls")
    assert list(sections(result["prompt"])) == list(stage.sections(body))


def test_multi_anchor_keeps_manifest_and_marks_selection_uncovered(monkeypatch):
    saved = json.loads((Path(__file__).parent / "fixtures/h3_v5_approved_c1.json").read_text())
    assert len(saved["authority"]["anchor_policy"]["catalog"]) == 3
    assert [item["decision"] for item in saved["output"]["av_timeline"]["anchors"]] == [
        "KEEP", "RETIME", "RETIME"]  # #14's real selection is not copied into this preview.
    previews(monkeypatch)
    manifest = {"references": [
        {"slot": 1, "kind": "DIRECTOR_VISUAL_ANCHOR", "source_keyframe_index": 1, "image_url": "/kf1.png"},
        {"slot": 2, "kind": "DIRECTOR_VISUAL_ANCHOR", "source_keyframe_index": 2, "image_url": "/kf2.png"},
    ]}
    text = ("subject_definitions:\n<Subject 1> is Mira, in the room.\n\nsummary:\nA 4-second room scene.\n\n"
            "retention_analysis:\n<Picture 1> establishes the opening. <Picture 2> guides the later state.\n\n"
            "detailed_description:\nMira moves from the door in <Picture 1> to the table in <Picture 2>.\n\n"
            "overall_soundscape:\nQuiet footsteps.\n\nnon_diegetic_music:\nN/A")
    result = asyncio.run(stage.preview_single_stage_h3(
        payload={"clip": {"capability": "GENERATE"}, "visual_controls": [
            {"index": 1, "description": "Mira at door"}, {"index": 2, "description": "Mira at table"}],
            "transitions": [{"transition_description": "Mira moves from door to table"}]},
        route="endpoint", template_type="h3_first_last_frame_prompt", novel_id="novel", chapter_id="chapter",
        assigned_dialogues=[], visible_characters=["Mira"],
        picture_mapping=[{"picture_index": 1, "source_keyframe_index": 1},
                         {"picture_index": 2, "source_keyframe_index": 2}],
        reference_manifest=manifest, temporal_anchors=[],
        experiment={"verified_timing": {"optimized_duration": 4, "dialogue_events": []}},
        llm=FakeLLM(text)))
    assert result["anchor_selection"] == "NOT_COVERED" and not result["ready_for_h3_experiment"]
    assert result["reference_manifest"] == manifest
    assert result["image_input_order"] == ["<Picture 1>", "<Picture 2>"]
    assert result["picture_audit"]["passed"]
    assert "Mira moves from the door" in result["prompt"]


@pytest.mark.parametrize("change,reason", [
    ("slot_missing", "DIALOGUE_SLOTS_INVALID"),
    ("wrong_subject", "SUBJECT_DEFINITION_MISMATCH"),
    ("wrong_duration", "PREFLIGHT_FAILED"),
    ("extra_picture", "PREFLIGHT_FAILED"),
])
def test_structured_preview_mismatch_still_rejected(change, reason):
    case, model, timing = saved_shot12()
    canonical = case["authority"]["dialogue_events"]
    if change == "slot_missing":
        model = model.replace("[[D10]]", "", 1)
    elif change == "wrong_subject":
        model = model.replace("<Subject 1> is 皇帝", "<Subject 1> is 宫廷总管", 1)
    elif change == "wrong_duration":
        model = model.replace("16.5-second", "17-second", 1)
    else:
        model += "\n<Picture 9>"
    with pytest.raises(ValueError, match=reason):
        stage._assemble(model, canonical, timing, case["authority"]["subject_bindings"],
                        [{"picture_index": i} for i in range(1, 9)], case["authority"]["continuation"])


def test_reference_identity_swap_and_unverified_dialogue_window_rejected():
    case, model, timing = saved_shot12()
    authority = case["authority"]
    mapping = [{"picture_index": i, "kind": ref["type"], "source_name": ref["source_name"]}
               for i, ref in enumerate(authority["reference_bindings"], 1)]
    swapped = model.replace("<Picture 2> supplies identity only for <Subject 1>",
                            "<Picture 2> supplies identity only for <Subject 2>", 1)
    with pytest.raises(ValueError, match="identity_picture_2"):
        stage._assemble(swapped, authority["dialogue_events"], timing,
                        authority["subject_bindings"], mapping, authority["continuation"])
    assigned = [{"id": item["id"], "speaker": authority["subject_bindings"][item["speaker"]],
                 "text": item["exact_dialogue"], "duration": item["duration"]}
                for item in authority["dialogue_events"]]
    by_name = {name: subject for subject, name in authority["subject_bindings"].items()}
    altered = json.loads(json.dumps(timing))
    altered["dialogue_events"][0]["optimized_start"] = 0.2
    altered["dialogue_events"][0]["optimized_end"] = 2.2
    with pytest.raises(ValueError, match="CONTINUATION_TIMING_INVALID"):
        stage._verified_timing(assigned, by_name, altered, authority["continuation"], "EXTEND")
    altered = json.loads(json.dumps(timing))
    altered["dialogue_events"][2]["speaker"] = "<Subject 1>"
    with pytest.raises(ValueError, match="DIALOGUE_TIMING_MISMATCH"):
        stage._verified_timing(assigned, by_name, altered, authority["continuation"], "EXTEND")


def test_saved_task_read_only_builder_replay(monkeypatch):
    if not DB.exists():
        pytest.skip("Read-only Shot 12 task snapshot unavailable")
    case, model_output, timing = saved_shot12()
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        task = connection.execute("select * from tasks where id=?", (TASK_ID,)).fetchone()
        if task is None:
            pytest.skip("Saved Shot 12 task unavailable")
        shot_row = connection.execute("select * from shots where id=?", (task["shot_id"],)).fetchone()
    metadata = json.loads(task["metadata_json"])
    plan = json.loads(shot_row["video_director_plan"])
    clip = next(item for item in plan["clip_plan"] if item["clip_index"] == 2)
    transitions = _project_semantic_clip_transitions(
        plan["transitions"], clip["visual_state_indexes"], clip["carry_in_state_index"],
        clip_start=clip["start_time"], clip_end=clip["end_time"])
    continuation = metadata["h3_prompt_optimizer"]["runtime_input"]["immutable_authority"]["continuation"]
    previews(monkeypatch, continuation)
    llm = FakeLLM(model_output)
    monkeypatch.setattr(builder, "LLMService", lambda: llm)
    monkeypatch.setattr(builder, "resolve_prompt_template", lambda *_args: SimpleNamespace(template="production", name="production"))
    monkeypatch.setattr(builder, "get_visual_prop_names", lambda *_args: [])
    shot = SimpleNamespace(**{key: shot_row[key] for key in shot_row.keys()})
    commits = []
    result = asyncio.run(builder.build_h3_video_prompt(
        db=SimpleNamespace(commit=lambda: commits.append(True)), novel=SimpleNamespace(id=task["novel_id"]),
        shot=shot, selected_mode="SINGLE_FRAME", clip=clip, workflow_capability={},
        workflow_type="VIDEO_CONTINUATION", workflow_name=task["workflow_name"],
        start_image_url=None, keyframes=plan["keyframes"], transitions=transitions,
        clip_dialogues=clip["dialogue_assignment"], reference_images=[],
        temporal_anchors=[], video_reference_manifest=metadata["video_reference_manifest"],
        previous_av_present=True,
        current_visual_state=next(item for item in plan["keyframes"] if item["index"] == 5),
        resolved_dialogue_timeline=plan["dialogue_timeline_source"],
        single_stage_experiment={"enabled": True, "verified_timing": timing,
            "verified_continuation": continuation,
            "previous_video_path": metadata["previous_approved_video_url"]}))
    assert not commits and len(llm.calls) == 1 and result["raw_llm_output"] == model_output
    assert [item["exact_dialogue"] for item in dialogue_events(result["prompt"])] == [
        item["exact_dialogue"] for item in case["authority"]["dialogue_events"]]
    entered = json.loads(llm.calls[0]["user_content"])
    assert entered["visual_control_route"] == "single" and len(entered["transitions"]) == 2
    assert entered["single_stage_experiment"]["verified_generation_duration"] == 16.5
    assert len(entered["dialogue_timeline_source"]) == 7
    assert result["anchor_selection"] == "NOT_REQUIRED"


SAVED_SINGLE_STAGE = Path("/Volumes/Data/tmp/shot12_c2_single_stage_llm_20261014")


def test_authority_owned_saved_shot12_response_offline():
    if not (SAVED_SINGLE_STAGE / "single_stage_raw_output.txt").exists():
        pytest.skip("Saved one-call Shot 12 C2 response unavailable")
    raw = (SAVED_SINGLE_STAGE / "single_stage_raw_output.txt").read_text()
    call = json.loads((SAVED_SINGLE_STAGE / "live_llm_call.json").read_text())
    payload = json.loads(call["user_content"])
    snapshot = json.loads((SAVED_SINGLE_STAGE / "input_snapshot.json").read_text())
    by_name = payload["single_stage_experiment"]["subject_speaker_bindings"]
    timing, canonical, continuation_checks = stage._verified_timing(
        payload["dialogue_timeline_source"], by_name, snapshot["verified_timing"],
        snapshot["continuation"], "EXTEND")
    mapping = builder.build_physical_picture_mapping(snapshot["reference_manifest"])
    prompt, review, picture = stage.assemble_authority_owned_candidate(
        raw, canonical, timing, {subject: name for name, subject in by_name.items()},
        mapping, snapshot["continuation"], "N/A")
    assert all(continuation_checks.values())
    assert all(review["structure"].values())
    assert all(review["structured_authority"].values()) and picture["passed"]
    assert not all(review["native_prompt_diagnostics"].values())
    assert review["submission_authorized"] is False
    parts = sections(prompt)
    assert list(parts) == list(stage.SECTIONS)
    assert parts["subject_definitions"].splitlines() == [
        line for line in parts["subject_definitions"].splitlines() if re.match(r"^<Subject \d+> is ", line)]
    assert len(parts["subject_definitions"].splitlines()) == 4
    assert "宝蓝礼服" not in parts["subject_definitions"]
    assert "黑紫长外套" not in parts["subject_definitions"]
    assert "identity reference does not determine current costume" in parts["subject_definitions"]
    assert parts["non_diegetic_music"] == "N/A"
    assert "1.625-second" not in prompt  # The prefix is in the verified timing, not a second H3 duration.
    assert review["verified_overlap_seconds"] == 1.625
    assert snapshot["continuation"]["overlap_seconds"] == 1.625
    assert [(e["speaker"], e["exact_dialogue"]) for e in dialogue_events(prompt)] == [
        (e["speaker"], e["exact_dialogue"]) for e in canonical]
    assert re.findall(r"\bD\d+\b", prompt) == [f"D{i}" for i in range(7, 14)]
    assert all(f"<Picture {i}>" in prompt for i in range(1, 9))
    detail = parts["detailed_description"]
    for match, event in zip(reversed(list(_DIALOGUE_PATTERN.finditer(detail))), reversed(canonical)):
        detail = detail[:match.start()] + f"[[{event['id']}]]" + detail[match.end():]
    assert detail == sections(raw)["detailed_description"]  # No invented director actions/handoffs.
    assert parts["overall_soundscape"] == sections(raw)["overall_soundscape"]
    assert "REVIEW_REQUIRED" in review["canonical_action_coverage"]
    assert "REVIEW_REQUIRED" in review["speaker_visual_handoff"]


def test_authority_owned_preview_flag_is_isolated_and_never_ready(monkeypatch):
    if not (SAVED_SINGLE_STAGE / "single_stage_raw_output.txt").exists():
        pytest.skip("Saved one-call Shot 12 C2 response unavailable")
    case = json.loads(SAVED.read_text())
    names = case["authority"]["subject_bindings"]
    continuation = case["authority"]["continuation"]
    previews(monkeypatch, continuation)
    assigned = [{"id": item["id"], "speaker": names[item["speaker"]],
                 "text": item["exact_dialogue"], "duration": item["duration"]}
                for item in case["authority"]["dialogue_events"]]
    refs = [{"slot": i, "kind": ref["type"], "source_name": ref["source_name"],
             "image_url": f"/saved/picture_{i}.png"}
            for i, ref in enumerate(case["authority"]["reference_bindings"], 1)]
    llm = FakeLLM((SAVED_SINGLE_STAGE / "single_stage_raw_output.txt").read_text())
    result = asyncio.run(stage.preview_single_stage_h3(
        payload={"clip": {"capability": "EXTEND"}}, route="single",
        template_type="h3_single_frame_prompt", novel_id="novel", chapter_id="chapter",
        assigned_dialogues=assigned, visible_characters=list(names.values()),
        picture_mapping=[{"picture_index": i} for i in range(1, 9)],
        reference_manifest={"references": refs}, temporal_anchors=[],
        experiment={"assembly_mode": "AUTHORITY_OWNED_V1", "verified_music": "N/A",
                    "verified_timing": {"optimized_duration": 16.5, "dialogue_events": [
                        {"id": item["id"], "speaker": item["speaker"],
                         "optimized_start": start, "optimized_end": end}
                        for item, (start, end) in zip(case["authority"]["dialogue_events"], TIMES)]},
                    "verified_continuation": continuation,
                    "previous_video_path": "/saved/previous.mp4"}, llm=llm))
    assert len(llm.calls) == 1
    assert all(result["assembly_review"]["structure"].values())
    assert all(result["assembly_review"]["structured_authority"].values())
    assert result["ready_for_h3_experiment"] is False
    assert result["submission_authorized"] is False


def test_authority_owned_director_only_uses_ordered_slots_and_backend_sections(monkeypatch):
    case, _, timing = saved_shot12()
    names = case["authority"]["subject_bindings"]
    continuation = case["authority"]["continuation"]
    refs = [{"slot": i, "kind": ref["type"], "source_name": ref["source_name"],
             "image_url": f"/saved/picture_{i}.png"}
            for i, ref in enumerate(case["authority"]["reference_bindings"], 1)]
    director = ("detailed_description:\n" + "\n".join(
        f"皇帝与宫廷总管维持既定空间关系，当前发言者的面部可辨。[[SPEECH_{i}]]"
        for i in range(1, 8)) +
        "\n\noverall_soundscape:\n大厅的室内空气声。")
    previews(monkeypatch, continuation)
    llm = FakeLLM(director)
    result = asyncio.run(stage.preview_single_stage_h3(
        payload={"clip": {"capability": "EXTEND"}}, route="single",
        template_type="h3_single_frame_prompt", novel_id="novel", chapter_id="chapter",
        assigned_dialogues=[{"id": item["id"], "speaker": names[item["speaker"]],
                             "text": item["exact_dialogue"], "duration": item["duration"]}
                            for item in case["authority"]["dialogue_events"]],
        visible_characters=list(names.values()),
        picture_mapping=[{"picture_index": i} for i in range(1, 9)],
        reference_manifest={"references": refs}, temporal_anchors=[],
        experiment={"assembly_mode": "AUTHORITY_OWNED_V1", "director_only": True,
                    "verified_music": "N/A", "verified_timing": timing,
                    "verified_continuation": continuation,
                    "previous_video_path": "/saved/previous.mp4"}, llm=llm))
    assert len(llm.calls) == 1
    assert llm.calls[0]["system_prompt"] == stage.DIRECTOR_ONLY_TEMPLATE.read_text()
    assert result["assembly_review"]["llm_output_mode"] == "DIRECTOR_ONLY"
    assert all(result["assembly_review"]["structure"].values())
    assert all(result["assembly_review"]["structured_authority"].values())
    assert list(sections(result["prompt"])) == list(stage.SECTIONS)
    assert [(e["speaker"], e["exact_dialogue"]) for e in dialogue_events(result["prompt"])] == [
        (e["speaker"], e["exact_dialogue"]) for e in case["authority"]["dialogue_events"]]
    assert result["ready_for_h3_experiment"] is False
    assert result["submission_authorized"] is False


def test_saved_director_response_quotes_only_recorded_stable_identity_marks():
    saved_dir = Path("/Volumes/Data/tmp/shot12_c2_director_only_20261014")
    if not (saved_dir / "live_raw_director_output.txt").exists():
        pytest.skip("Saved Shot 12 C2 director response unavailable")
    raw = (saved_dir / "live_raw_director_output.txt").read_text()
    payload = json.loads(json.loads((saved_dir / "llm_call.json").read_text())["user_content"])
    snapshot = json.loads((SAVED_SINGLE_STAGE / "input_snapshot.json").read_text())
    by_name = payload["single_stage_experiment"]["subject_speaker_bindings"]
    timing, canonical, _ = stage._verified_timing(
        payload["dialogue_timeline_source"], by_name, snapshot["verified_timing"],
        snapshot["continuation"], "EXTEND")
    mapping = builder.build_physical_picture_mapping(snapshot["reference_manifest"])
    appearances = payload["shot"]["official_character_appearances"]
    prompt, review, _ = stage.assemble_authority_owned_candidate(
        raw, canonical, timing, {subject: name for name, subject in by_name.items()},
        mapping, snapshot["continuation"], "N/A", director_only=True,
        character_appearances=appearances)
    subject_lines = sections(prompt)["subject_definitions"].splitlines()
    assert len(subject_lines) == 4
    for subject, name in ((subject, name) for name, subject in by_name.items()):
        exact_marks = stage._stable_identity_marks(appearances[name])
        assert exact_marks and any(line.startswith(f"{subject} is {name},") and exact_marks in line
                                   for line in subject_lines)
        assert review["stable_identity_sources"][subject] == (
            "Character.appearance explicit stable-identity clause")
    assert "基础服装" not in sections(prompt)["subject_definitions"]
    assert "基础造型" not in sections(prompt)["subject_definitions"]
    assert "the identity reference does not determine current costume" in subject_lines[0]
    assert all(review["structure"].values()) and all(review["structured_authority"].values())


def test_stable_identity_clause_missing_is_not_invented():
    assert stage._stable_identity_marks("一名成年人；基础服装为深色外套。") is None
    assert stage._stable_identity_marks("稳定身份标记包括棕色眼睛；基础服装为红衣。") == "棕色眼睛"
    assert stage._stable_identity_marks("稳定身份标记为宽额方脸、浓黑剑眉和深褐色眼睛。基础服装为王服。") == (
        "宽额方脸、浓黑剑眉和深褐色眼睛"
    )
    assert stage._stable_identity_marks("稳定身份标记为；基础服装为深色外套。") is None
    assert "background prop's presence alone" in stage.DIRECTOR_ONLY_TEMPLATE.read_text()


@pytest.mark.parametrize("invalid", [
    "detailed_description:\n[[SPEECH_1]]\n\noverall_soundscape:\nRoom tone.",
    "detailed_description:\n[[SPEECH_1]]\n\nsummary:\nExtra.\n\noverall_soundscape:\nRoom tone.",
    "detailed_description:\n<Picture 1> [[SPEECH_1]]\n\noverall_soundscape:\nRoom tone.",
])
def test_authority_owned_director_only_rejects_redefined_facts(invalid):
    case, _, timing = saved_shot12()
    authority = case["authority"]
    mapping = [{"picture_index": i, "kind": ref["type"], "source_name": ref["source_name"]}
               for i, ref in enumerate(authority["reference_bindings"], 1)]
    with pytest.raises(ValueError):
        stage.assemble_authority_owned_candidate(
            invalid, authority["dialogue_events"], timing,
            authority["subject_bindings"], mapping, authority["continuation"],
            "N/A", director_only=True)


def test_authority_owned_rejects_missing_identity_and_unverified_time():
    case, model, timing = saved_shot12()
    names = case["authority"]["subject_bindings"]
    mapping = [{"picture_index": i, "kind": ref["type"], "source_name": ref["source_name"]}
               for i, ref in enumerate(case["authority"]["reference_bindings"], 1)]
    with pytest.raises(ValueError, match="IDENTITY_PICTURE_BINDING_UNRESOLVED"):
        stage.assemble_authority_owned_candidate(
            model, case["authority"]["dialogue_events"], timing, names,
            [mapping[0], {**mapping[1], "kind": "PROP"}, *mapping[2:]],
            case["authority"]["continuation"], "N/A")
    with pytest.raises(ValueError, match="DIALOGUE_TIME_CUE_SOURCE_INVALID"):
        altered = copy.deepcopy(timing)
        altered["dialogue_events"][0]["optimized_start"] = -1
        stage.assemble_authority_owned_candidate(
            model, case["authority"]["dialogue_events"], altered, names,
            mapping, case["authority"]["continuation"], "N/A")
    with pytest.raises(ValueError, match="MUSIC_AUTHORITY_UNVERIFIED"):
        stage.assemble_authority_owned_candidate(
            model, case["authority"]["dialogue_events"], timing, names,
            mapping, case["authority"]["continuation"], None)


@pytest.mark.parametrize("task_id,decisions", [
    ("b28d0eea-2748-405c-bea3-723ca78804ae", {"RETIME", "DROP"}),
    ("45bc29fa-8f3b-4d55-8a49-fa68fde4d880", {"KEEP", "RETIME"}),
])
def test_saved_multi_anchor_projection_and_real_path_binding_read_only(task_id, decisions):
    if not DB.exists():
        pytest.skip("Saved multi-anchor task database unavailable")
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "select metadata_json,reference_images from tasks where id=?", (task_id,)).fetchone()
    if row is None:
        pytest.skip("Saved multi-anchor task unavailable")
    metadata = json.loads(row[0])
    record = metadata["h3_prompt_optimizer"]
    assert record["status"] == "OPTIMIZED" and record["authority_check"]["passed"]
    anchors = record["output"]["av_timeline"]["anchors"]
    assert len(anchors) >= 2 and {a["decision"] for a in anchors} == decisions
    saved = record["execution_reference_manifest"]
    original = []
    for item in sorted(saved["references"] + saved["excluded_references"],
                       key=lambda value: value["source_slot"]):
        source = copy.deepcopy(item)
        for field in ("source_slot", "source_picture", "logical_id", "picture",
                      "anchor_id", "decision", "reason", "included_in_execution"):
            source.pop(field, None)
        source["slot"] = item["source_slot"]
        original.append(source)
    projected = project_reference_manifest(
        {"references": original}, record["runtime_input"]["immutable_authority"],
        record["output"])
    assert projected["references"] == saved["references"]
    assert projected["excluded_references"] == saved["excluded_references"]
    assert projected["picture_projection"] == saved["picture_projection"]
    assert [r["source_slot"] for r in projected["references"]] == sorted(
        r["source_slot"] for r in projected["references"])
    assert [r["slot"] for r in projected["references"]] == list(range(1, len(projected["references"]) + 1))
    assert all(r["kind"] != "CHARACTER_IDENTITY" and r["kind"] != "SCENE" and r["kind"] != "PROP"
               for r in projected["excluded_references"])
    assert [r["url"] for r in json.loads(row[1])] == [r["image_url"] for r in saved["references"]]
    by_picture = {r["picture"]: r["source_sha256"] for r in record["runtime_input"]["visual_inputs"]
                  if r.get("picture")}
    for item in projected["references"] + projected["excluded_references"]:
        path = Path(item["local_path"])
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == by_picture[item["source_picture"]]
    checks = record["authority_check"]["checks"]
    assert all(checks[key] for key in (
        "anchor_decisions_complete", "anchor_arrival_relation",
        "anchor_required_outcomes_retained", "reference_projection_consistent"))
