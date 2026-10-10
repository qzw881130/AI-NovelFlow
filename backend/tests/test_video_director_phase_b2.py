"""B2 PRE context contracts: fake planning, memory persistence, no external services."""
import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api import shots as api
from app.models.novel import Chapter, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.repositories.novel_repository import NovelRepository
from app.repositories.shot_repository import ShotRepository
from app.schemas.shot import PlanClipsRequest
from app.services import clip_planner as planner, video_director_ai as ai
from app.services.prompt_template_service import PromptTemplateService
from app.services.shot_video_service import _semantic_clip_prompt_context, get_semantic_clip_prompt
from app.services.visual_attention import prompt_projection_metadata
import test_video_director_phase_a as phase_a
import test_video_director_phase_b1 as phase_b1

ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE = ROOT / "prompt_templates/10A_NovelFlow_ClipExecutionPlanner_V1.txt"
CONTEXT = "dialogue_visual_planning_context"


def fixture():
    return json.loads((FIXTURES / "video_director_phase_b2.json").read_text())


def input_context(variant="planner"):
    return planner.build_clip_planner_input(SimpleNamespace(**fixture()["variants"][variant]["shot"]), [])[CONTEXT]


def event(context, dialogue_id):
    return next(e for e in context["events"] if e["dialogue_id"] == dialogue_id)


def direct_context(args):
    return ai.build_dialogue_visual_planning_context(args[0], args[2], args[1]["end_time"])


def mock_planner(monkeypatch, response, calls):
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "content": json.dumps(response, ensure_ascii=False)}
    monkeypatch.setattr(planner, "LLMService", FakeLLM)
    monkeypatch.setattr(planner, "PromptTemplateService", lambda db: SimpleNamespace(
        get_default_system_template=lambda kind: SimpleNamespace(template=TEMPLATE.read_text(), name="fixture")))


async def planned(monkeypatch, variant="planner", response=None, shot=None):
    data = fixture()["variants"][variant]
    calls, anchors = [], []
    mock_planner(monkeypatch, response or data["response"], calls)
    clips, validation = await planner.plan_clips(None, SimpleNamespace(id="novel"),
        shot or SimpleNamespace(**data["shot"]), anchors)
    return clips, validation, anchors, calls


def frozen_function_hash(path, name):
    source = (ROOT / path.removeprefix("backend/")).read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return hashlib.sha256("\n".join(source.splitlines()[node.lineno - 1:node.end_lineno]).encode()).hexdigest()


def test_b2_01_pre_context_is_pure_deterministic_json_safe_and_shot_seconds():
    data = fixture()["variants"]["planner"]["shot"]
    plan = json.loads(data["video_director_plan"])
    args = (plan["dialogue_timeline_source"], plan, data["duration"])
    before = copy.deepcopy(args)
    first = ai.build_dialogue_visual_planning_context(*args)
    second = ai.build_dialogue_visual_planning_context(*args)
    assert first == second and args == before
    assert json.dumps(first, allow_nan=False, sort_keys=True) == json.dumps(second, allow_nan=False, sort_keys=True)
    assert (first["basis"], first["phase"], first["time_base"]) == ("PLANNED_METADATA", "PRE_PLANNING", "SHOT_SECONDS")


def test_b2_02_no_historical_manifest_slots_subjects_or_future_selection_leakage():
    data = fixture()["variants"]["planner"]["shot"]
    plan = json.loads(data["video_director_plan"])
    clean = ai.build_dialogue_visual_planning_context(plan["dialogue_timeline_source"], plan, data["duration"])
    plan.update(clip_plan=[{"visual_support_evidence": phase_b1.formal_evidence(),
                           "temporal_anchor_ids": ["FUTURE-LEAK"], "reason": "H3-LEAK"}],
                temporal_anchors=[{"anchor_id": "FUTURE-LEAK"}],
                video_reference_manifest=phase_b1.fixture()["clip1_manifest"],
                execution_contract={"visual_attention_snapshot": {"characters": phase_b1.fixture()["clip1_subject_bindings"]}})
    result = ai.build_dialogue_visual_planning_context(plan["dialogue_timeline_source"], plan, data["duration"])
    assert result == clean
    text = json.dumps(result)
    for forbidden in ["slot", "reference_ids", "ordinary_visual", "temporal_anchor_ids", "Picture", "Subject", "FUTURE-LEAK", "H3-LEAK", "realization_review"]:
        assert forbidden not in text
    assert all(e["identity_reference"] == {"available": "unknown", "source_status": "unavailable_at_planning"} for e in result["events"])


def test_b2_03_d4_mismatch_is_visible_as_facts_without_post_ci():
    d4 = event(input_context(), "D4")
    assert d4["canonical_reference"] == {"speaker": "骗子1", "intended_window": {"start": 8.35, "end": 9.35}}
    assert d4["attention"]["coverage_ratio"] == 1
    assert [o["roles"] for o in d4["attention"]["overlaps"]] == [["not_listed"]]
    assert [(s["state_id"], s["planned_speaker_membership"]) for s in d4["visual_states"]["states"]] == [("KF2", "present"), ("KF3", "present")]
    assert d4["identity_reference"]["available"] == "unknown"
    assert all(s["scope"] == "shot_context" for s in d4["visual_states"]["states"])


@pytest.mark.parametrize("dialogue_id", ["D1", "D2", "D5", "D6"])
def test_b2_04_primary_support_positive_cases_have_no_deterministic_concern(dialogue_id):
    positive = event(input_context(), dialogue_id)
    assert [o["roles"] for o in positive["attention"]["overlaps"]] == [["primary"]]
    assert positive["attention"]["coverage_ratio"] == 1
    assert "concern" not in positive and "mismatch" not in positive
    if dialogue_id == "D5":
        assert positive["canonical_reference"] == {"speaker": "皇帝", "intended_window": {"start": 9.55, "end": 10.8}}


def test_b2_05_d3_preserves_primary_handoff_to_speaker_then_primary():
    d3 = event(input_context(), "D3")
    overlaps = d3["attention"]["overlaps"]
    assert [o["roles"] for o in overlaps] == [["primary", "handoff_participant"], ["primary"]]
    assert overlaps[0]["handoff_directions"] == ["to"]
    assert overlaps[0]["handoff"]["to"] == [phase_b1.EMPEROR]
    assert "concern" not in d3 and d3["attention"]["handoff_overlap"] is True


def test_b2_06_reaction_subject_primary_and_speaker_background_are_preserved():
    args = phase_b1.inputs(windows=[phase_b1.window(0, 10, [phase_b1.OTHER], [phase_b1.EMPEROR])])
    reaction = direct_context(args)["events"][0]
    overlap = reaction["attention"]["overlaps"][0]
    assert overlap["roles"] == ["background_motion"]
    assert overlap["primary_subjects"] == [phase_b1.OTHER]
    assert overlap["background_motion_subjects"] == [phase_b1.EMPEROR]
    assert "INVALID" not in json.dumps(reaction) and "failure" not in reaction
    assert reaction["speaker_visibility"] == "unknown"


def test_b2_07_absent_sources_remain_unknown_without_false_absent_or_gate():
    args = phase_b1.inputs(speaker="Unknown speaker", states=[])
    args[2]["visual_attention"] = None
    result = direct_context(args)
    e = result["events"][0]
    assert result["source_status"] == e["source_status"] == "unknown"
    assert e["resolved_character"] == {"status": "unresolved", "character_id": None}
    assert e["attention"]["coverage_ratio"] is None
    assert e["visual_states"]["states"] == []
    assert all(e[k] == "unknown" for k in ["speaker_visibility", "face_readability", "mouth_readability", "competing_face_salience"])
    assert e["identity_reference"]["available"] == "unknown"


@pytest.mark.parametrize("speaker", ["未知皇帝", "皇帝陛下", "皇帝 "])
def test_b2_08_identity_unresolved_does_not_fuzzy_guess_uuid_or_subject(speaker):
    result = direct_context(phase_b1.inputs(speaker=speaker))["events"][0]
    assert result["resolved_character"] == {"status": "unresolved", "character_id": None}
    assert result["attention"]["overlaps"][0]["roles"] == ["unresolved"]
    assert "subject" not in result["resolved_character"]


@pytest.mark.asyncio
async def test_b2_09_no_dialogue_plan_remains_runnable(monkeypatch):
    shot_data = fixture()["variants"]["planner"]["shot"]
    plan = json.loads(shot_data["video_director_plan"])
    plan["dialogue_timeline_source"] = []
    shot = SimpleNamespace(**{**shot_data, "dialogues": "[]", "video_director_plan": json.dumps(plan)})
    assert planner.build_clip_planner_input(shot, [])[CONTEXT]["events"] == []
    clips, validation, _, _ = await planned(monkeypatch, shot=shot)
    assert validation["passed"] and clips[0]["dialogue_assignment"] == []


def test_b2_10_canonical_text_speaker_order_and_shot_times_immutable(monkeypatch):
    data = fixture()["variants"]["planner"]["shot"]
    before = copy.deepcopy(data)
    monkeypatch.setattr(ai, "build_dialogue_timeline", lambda *args: pytest.fail("persisted official must not reallocate"))
    payload = planner.build_clip_planner_input(SimpleNamespace(**data), [])
    timeline = json.loads(data["video_director_plan"])["dialogue_timeline_source"]
    assert data == before
    assert [e["dialogue_id"] for e in payload[CONTEXT]["events"]] == [e["id"] for e in timeline]
    assert all("text" not in e["canonical_reference"] for e in payload[CONTEXT]["events"])
    assert [(e["canonical_reference"]["speaker"], e["canonical_reference"]["intended_window"]) for e in payload[CONTEXT]["events"]] == [(e["speaker"], {"start": e["start_time"], "end": e["end_time"]}) for e in timeline]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["planner", "multiclip_planner"])
async def test_b2_11_boundaries_count_duration_frozen_under_identical_response(monkeypatch, variant):
    clips, _, _, _ = await planned(monkeypatch, variant)
    before = fixture()["variants"][variant]["clips_before"]
    keys = ["clip_index", "start_time", "end_time", "planned_duration"]
    assert [{k: c[k] for k in keys} for c in clips] == [{k: c[k] for k in keys} for c in before]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["planner", "multiclip_planner"])
async def test_b2_12_capabilities_and_continuity_frozen(monkeypatch, variant):
    clips, _, _, _ = await planned(monkeypatch, variant)
    before = fixture()["variants"][variant]["clips_before"]
    assert [(c["capability"], c["continuity_to_previous"]) for c in clips] == [(c["capability"], c["continuity_to_previous"]) for c in before]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["planner", "multiclip_planner"])
async def test_b2_13_temporal_selection_composition_and_anchor_types_frozen(monkeypatch, variant):
    clips, _, anchors, _ = await planned(monkeypatch, variant)
    before = fixture()["variants"][variant]
    keys = ["selected_temporal_target_ids", "temporal_anchor_ids", "early_composition_state_id", "inherited_start_composition"]
    assert [{k: c.get(k) for k in keys} for c in clips] == [{k: c.get(k) for k in keys} for c in before["clips_before"]]
    assert anchors == before["temporal_anchors_before"]
    if variant == "planner":
        assert clips[0]["temporal_anchor_ids"] == []
        assert {a["reference_type"] for a in phase_b1.formal_evidence()["events"][0]["anchors"]["ordinary_visual"]} == {"DIRECTOR_VISUAL_ANCHOR"}


def test_b2_14_keyframe_attention_inputs_replan_code_and_templates_frozen():
    data = fixture()
    path = "backend/app/api/shots.py"
    for name, expected in data["frozen_functions"][path].items():
        assert frozen_function_hash(path, name) == expected
    for path, expected in phase_a.frozen()["frozen_files"].items():
        if "/08_" in path:
            assert hashlib.sha256((ROOT / path.removeprefix("backend/")).read_bytes()).hexdigest() == expected


@pytest.mark.asyncio
async def test_b2_15_b1_post_evidence_core_and_output_preserved(monkeypatch):
    path = "backend/app/services/video_director_ai.py"
    for name, expected in fixture()["frozen_functions"][path].items():
        if name == "build_h3_video_prompt":
            # B4 explicitly extends this consumer; its OFF golden remains below.
            continue
        assert frozen_function_hash(path, name) == expected
    clips, _, _, _ = await planned(monkeypatch)
    assert clips[0]["visual_support_evidence"] == fixture()["variants"]["planner"]["clips_before"][0]["visual_support_evidence"]
    assert phase_b1.formal_evidence()["events"][3]["identity_reference"]["available"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["planner", "multiclip_planner"])
async def test_b2_16_full_frozen_response_equivalence_except_authorized_input(monkeypatch, variant):
    clips, validation, anchors, calls = await planned(monkeypatch, variant)
    before = fixture()["variants"][variant]
    assert clips == before["clips_before"] and validation == before["validation_before"] and anchors == before["temporal_anchors_before"]
    for call, old in zip(calls, before["calls_before"]):
        payload = json.loads(call["user_content"])
        assert payload.pop(CONTEXT)["phase"] == "PRE_PLANNING"
        assert payload == json.loads(old["user_content"])
        assert {k: v for k, v in call.items() if k not in {"user_content", "system_prompt"}} == {k: v for k, v in old.items() if k not in {"user_content", "system_prompt"}}
    assert len(calls) == len(before["calls_before"])


@pytest.mark.asyncio
async def test_b2_17_aware_reason_is_accepted_and_persisted_without_authority_changes(db_session, monkeypatch):
    data = fixture(); shot_data = data["variants"]["planner"]["shot"]
    novel = Novel(title="B2 temporary novel"); db_session.add(novel); db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="temporary"); db_session.add(chapter); db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=3, duration=shot_data["duration"],
                continuity_mode=shot_data["continuity_mode"], characters=shot_data["characters"],
                dialogues=shot_data["dialogues"], video_director_plan=shot_data["video_director_plan"])
    db_session.add(shot); db_session.commit()
    calls=[]; mock_planner(monkeypatch, data["aware_response"], calls)
    monkeypatch.setattr(api, "get_canonical_execution_readiness", lambda *args: {"status": "NOT_EXECUTED"})
    result = await api.plan_shot_clips(novel.id, chapter.id, shot.id, PlanClipsRequest(force=True), db_session,
                                     NovelRepository(db_session), ShotRepository(db_session))
    assert result["data"]["validation"]["passed"]
    db_session.expire_all()
    persisted = json.loads(db_session.get(Shot, shot.id).video_director_plan)
    clips = persisted["clip_plan"]
    old = data["variants"]["planner"]["clips_before"]
    changed = {k for k in clips[0] if clips[0].get(k) != old[0].get(k)}
    assert changed == {"reason"}
    assert clips[0]["reason"] == data["aware_response"]["clips"][0]["reason"]
    assert persisted["dialogue_timeline_source"] == json.loads(shot_data["video_director_plan"])["dialogue_timeline_source"]
    assert event(json.loads(calls[0]["user_content"])[CONTEXT], "D4")["attention"]["overlaps"][0]["roles"] == ["not_listed"]


async def h3_for_clips(monkeypatch, clips):
    data = phase_a.frozen(); data["plan"]["clip_plan"] = clips
    context = _semantic_clip_prompt_context(data["plan"], data["metadata"])
    shot = SimpleNamespace(**data["shot"], video_director_plan=json.dumps(data["plan"]))
    captured={}
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs); return {"success": True, "content": data["llm_response"]}
    monkeypatch.setattr(ai, "LLMService", FakeLLM)
    monkeypatch.setattr(ai, "get_visual_prop_names", lambda db, nid, props: props)
    text=(ROOT / "prompt_templates/13_MiniMax_H3_MultiKeyframe_VideoPrompt_V1.txt").read_text()
    monkeypatch.setattr(ai, "resolve_prompt_template", lambda *args: SimpleNamespace(template=text, name="frozen #13"))
    prompt=await ai.build_h3_video_prompt(db=SimpleNamespace(commit=lambda: None), novel=SimpleNamespace(id=data["shot"]["novel_id"] if "novel_id" in data["shot"] else "bfc54b7d-04da-43e8-9e11-ff9a6032de5e"),
        shot=shot, selected_mode="MULTI_KEYFRAME", clip=context["clip"], workflow_capability={}, workflow_type="multi_reference_video",
        workflow_name="frozen workflow", start_image_url=None, keyframes=context["keyframes"], transitions=context["transitions"],
        clip_dialogues=context["clip_dialogues"], reference_images=[], video_reference_manifest=data["metadata"]["video_reference_manifest"])
    return prompt, captured


@pytest.mark.asyncio
async def test_b2_18_same_fake_planner_response_h3_prompt_and_llm_inputs_byte_identical(monkeypatch):
    clips, _, _, _ = await planned(monkeypatch)
    before, old_input = await h3_for_clips(monkeypatch, fixture()["variants"]["planner"]["clips_before"])
    after, new_input = await h3_for_clips(monkeypatch, clips)
    assert before.encode() == after.encode()
    assert json.dumps(old_input, ensure_ascii=False, sort_keys=True) == json.dumps(new_input, ensure_ascii=False, sort_keys=True)
    assert CONTEXT not in json.dumps(new_input)


def test_b2_19_h3_templates_remain_frozen():
    for path, expected in phase_a.frozen()["frozen_files"].items():
        if any("/" + n + "_" in path for n in ["11", "12", "13"]):
            assert hashlib.sha256((ROOT / path.removeprefix("backend/")).read_bytes()).hexdigest() == expected


@pytest.mark.asyncio
async def test_b2_20_new_planning_input_is_sent_each_time_without_old_response_cache(monkeypatch):
    data=fixture()["variants"]["planner"]; calls=[]; mock_planner(monkeypatch,data["response"],calls)
    shot=SimpleNamespace(**data["shot"])
    await planner.plan_clips(None,SimpleNamespace(id="novel"),shot,[])
    plan=json.loads(shot.video_director_plan); plan["visual_attention"]["windows"][2]["primary_subjects"]=[phase_b1.OTHER]
    shot.video_director_plan=json.dumps(plan)
    await planner.plan_clips(None,SimpleNamespace(id="novel"),shot,[])
    assert len(calls)==2 and calls[0]["user_content"] != calls[1]["user_content"]
    assert event(json.loads(calls[0]["user_content"])[CONTEXT],"D4")["attention"]["overlaps"][0]["roles"]==["not_listed"]
    assert event(json.loads(calls[1]["user_content"])[CONTEXT],"D4")["attention"]["overlaps"][0]["roles"]==["primary"]


def test_b2_21_pre_context_metadata_does_not_stale_valid_h3_cache():
    data=phase_a.frozen();plan=data["plan"];clip=plan["clip_plan"][0];manifest=data["metadata"]["video_reference_manifest"]
    attention=ai.prepare_clip_visual_attention(plan,clip,json.loads(data["shot"]["characters"]),manifest=manifest)
    prompt=(FIXTURES/"video_director_phase_a_prompt.txt").read_text()
    clip.update(prompt_text=prompt,prompt_projection=prompt_projection_metadata(attention,prompt))
    assert get_semantic_clip_prompt(plan,clip,manifest)==prompt
    clip[CONTEXT]=input_context()
    assert get_semantic_clip_prompt(plan,clip,manifest)==prompt
    assert ai.prepare_clip_visual_attention(plan,clip,json.loads(data["shot"]["characters"]),manifest=manifest)==attention


@pytest.mark.asyncio
async def test_b2_22_old_clip_task_approved_and_existing_plan_reads_compatible(db_session, monkeypatch):
    await phase_a.test_06_existing_clip_and_visual_plan_reads_do_not_write(monkeypatch)
    phase_b1.test_b1_10_old_phase_a_clip_task_read_without_backfill_or_approval_changes(db_session)


def test_b2_23_formal_canonical_fixture_is_immutable_and_no_truth_inflation():
    data=phase_a.frozen();before=copy.deepcopy(data)
    context=ai.build_dialogue_visual_planning_context(data["plan"]["dialogue_timeline_source"],data["plan"],data["shot"]["duration"])
    assert data==before and len(context["events"])==31
    assert all(e[k]=="unknown" for e in context["events"] for k in ["speaker_visibility","face_readability","mouth_readability","competing_face_salience"])


def test_b2_24_all_workflows_frozen():
    for path, expected in phase_a.frozen()["frozen_files"].items():
        if "/workflows/" in path:
            assert hashlib.sha256((ROOT/path.removeprefix("backend/")).read_bytes()).hexdigest()==expected


def test_prompt_contract_preserves_hard_soft_unknown_and_old_schema_with_optional_b4_carrier():
    prompt=" ".join(TEMPLATE.read_text().split())
    rules=["PRE_PLANNING / PLANNED_METADATA", "timeline source remain HARD", "Do not rewrite speaker/text/order/timing",
           "handoff are SOFT", "Coverage measures time only", "Unknown is not false", "not a hard failure or validation rule",
           "H3 timing and speaker realization remain soft, not guaranteed", "do not invent them", "speaker-primary is not a hard rule",
           "must not change Clip count/start/end/duration, capability or temporal selection", "do not output scores"]
    for rule in rules: assert rule in prompt
    old=fixture()["template_before"]
    suffix = TEMPLATE.read_text().split("Return JSON only:",1)[1]
    assert suffix.replace(',\n      "dialogue_visual_intent": {"version": 1, "mode": "soft", "events": []}', '') == old.split("Return JSON only:",1)[1]
    assert "D4" not in prompt and "骗子1" not in prompt


def test_template_sync_updates_same_key_in_memory_without_changing_production(db_session):
    row=PromptTemplate(id="b2-test-template",name="Clip Execution Planner",type="clip_execution_planner",
                       template=fixture()["template_before"],is_system=True,is_active=True)
    db_session.add(row);db_session.commit()
    service=PromptTemplateService(db_session);service.init_system_templates()
    runtime=service.get_default_system_template("clip_execution_planner")
    assert runtime.id==row.id and runtime.template==TEMPLATE.read_text()
    assert hashlib.sha256(runtime.template.encode()).hexdigest()==fixture()["template_after_sha256"]
    service.init_system_templates()
    assert db_session.query(PromptTemplate).filter_by(type="clip_execution_planner").count()==1


@pytest.mark.asyncio
async def test_phase_a_h3_golden_ignores_optional_pre_context_metadata(monkeypatch):
    data=phase_a.frozen();data["plan"]["clip_plan"][0][CONTEXT]=input_context()
    monkeypatch.setattr(phase_a,"frozen",lambda:copy.deepcopy(data))
    await phase_a.test_09_frozen_h3_prompt_and_context_are_byte_identical(monkeypatch)
