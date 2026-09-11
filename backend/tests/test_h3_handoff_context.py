"""P1 prompt-only handoff tests: --noconftest, in-memory authority, no external calls."""

import asyncio
from copy import deepcopy
import json
import sys
from types import ModuleType

import pytest
from sqlalchemy.orm import Session

from test_h3_prompt_worker import CONSTRAINT, PROMPT, edit_plan, records, worker


ACTUAL_DESCRIPTION = "Ada is by the tree."


@pytest.fixture
def handoff(worker, monkeypatch, request):
    state = worker
    options = getattr(request, "param", {})
    count = options.get("frames", 3)
    state.configure("MULTI_KEYFRAME", windows=2, frames=count, prompt=PROMPT, audio=options.get("audio", True))
    state.shot.continuity_mode = options.get("continuity", "NORMAL")
    state.task.claim_token, state.task.attempt = "owned-claim", 1
    plan = json.loads(state.shot.video_director_plan)
    plan["window_plans"][1]["keyframe_indexes"] = list(range(count, count * 2))
    plan["window_plans"][1]["speaker_timeline"] = [
        {"start_time": 0, "end_time": 1, "visible_speaker": "NONE"},
        {"start_time": 1, "end_time": 3, "visible_speaker": "Ada"},
        {"start_time": 3, "end_time": 4, "visible_speaker": "NONE"},
    ]
    for frame in plan["keyframes"]:
        frame["time_seconds"] = (frame["index"] - 1) * 4 / (count - 1)
        frame["image_task_id"] = "private-image-task"
    plan["transitions"] = [{"from_keyframe_index": index, "to_keyframe_index": index + 1,
                            "transition_description": "Continue towards the gate.",
                            "reference_url": "/private/transition.png?token=secret"}
                           for index in range(1, count * 2)]
    state.shot.video_director_plan = json.dumps(plan)
    state.db.commit()
    state.original_plan = deepcopy(plan)
    state.clip = {**plan["window_plans"][1], "clip_index": 2}
    state.audio = state.module._resolve_audio_drive_for_h3(plan, state.clip, state.mapping)
    state.base_context = state.module._h3_prompt_context(state.db, state.shot, state.mode, state.clip, state.audio["enabled"])
    state.original_frames = [deepcopy(frame) for frame in plan["keyframes"] if frame["index"] in state.clip["keyframe_indexes"]]
    state.original_transitions = state.module._filter_transitions_for_keyframe_indexes(plan["transitions"], state.clip["keyframe_indexes"])
    state.bundle = {
        "version": 1, "source": "actual_state_handoff", "run_id": "same-run", "from_clip": 1, "to_clip": 2,
        "clip_attempt_id": "c2-attempt", "planned_context_hash": state.module.prompt_digest(state.base_context),
        "start_image_url": "/api/files/private/same-run/actual-c1-tail.png", "start_image_sha256": "a" * 64,
        "keyframes": deepcopy(state.original_frames), "transitions": deepcopy(state.original_transitions),
        "trusted_state": [{"predicate": "character_location", "subject": "Ada", "value": "tree",
                           "state": "PRESENT", "confidence": "HIGH", "evidence": "private-raw-observation"}],
        "canonical_state": [{"predicate": "prop_present", "subject": "bag", "value": "", "expected": "PRESENT",
                             "critical": True, "protected": True, "source": "/private/approved-intent?token=secret"}],
        "evidence_hash": "b" * 64,
    }
    state.bundle["keyframes"][0].update(image_url=state.bundle["start_image_url"], description=ACTUAL_DESCRIPTION)
    state.handle = {"task_id": state.task.id, "run_id": "same-run", "claim_token": "owned-claim", "attempt": 1,
                    "attempts": {"1": "c1-attempt", "2": "c2-attempt"}}
    metadata = json.loads(state.task.metadata_json)
    metadata.update({
        "execution": {"attempt_id": "same-run"},
        "video_run": {"version": 1, "run_id": "same-run", "phase": "running", "clips": {
            str(index): {"attempt_id": f"c{index}-attempt", "spec": {"clip_index": index}} for index in (1, 2)
        }},
        "actual_state_handoff": {
            "decision": options.get("decision", "CONTINUE"), "can_submit_c2": True,
            "effective_context": deepcopy(state.bundle), "effective_context_hash": state.module.prompt_digest(state.bundle),
            "observations": [{"state": "UNKNOWN", "evidence": "private-unknown-observation"}],
            "credentials": "private-credentials",
        },
    })
    state.task.metadata_json = json.dumps(metadata)
    state.db.commit()
    state.task._video_execution = state.shot._video_execution = state.handle
    state.shot._video_clip_attempt_id = "c2-attempt"

    # Only runtime identity/persistence is doubled; exercise the real prompt gate and AI builder.
    execution = ModuleType("app.services.shot_video_execution")

    def save_gate_record(db, task, record):
        db.refresh(task)
        data = json.loads(task.metadata_json)
        attempts = data.setdefault("h3_prompt_gate", {"version": 1, "clips": {}})["clips"].setdefault("2", [])
        attempts[:] = [item for item in attempts if item["attempt_id"] != record["attempt_id"]] + [deepcopy(record)]
        task.metadata_json = json.dumps(data)
        db.commit()

    execution.save_gate_record = save_gate_record
    monkeypatch.setitem(sys.modules, execution.__name__, execution)
    return state


def build(state, **changes):
    kwargs = dict(
        db=state.db, task=state.task, novel=state.novel, shot=state.shot, selected_mode=state.mode,
        clip=state.clip, workflow=state.workflow, workflow_capability={}, start_image_url=state.bundle["start_image_url"],
        keyframes=deepcopy(state.bundle["keyframes"]), transitions=deepcopy(state.bundle["transitions"]),
        reference_images=[{"label": "C2 start", "url": state.bundle["start_image_url"]}],
        character_appearances={"Ada": "blue coat", "Bea": "red coat"}, audio_drive=state.audio,
        effective_context=state.bundle,
    )
    return asyncio.run(state.module._build_h3_prompt_for_worker(**{**kwargs, **changes}))


def edit_metadata(state, mutate):
    with Session(state.engine) as editor:
        task = editor.get(state.models.Task, "task")
        data = json.loads(task.metadata_json)
        mutate(data)
        task.metadata_json = json.dumps(data)
        editor.commit()


@pytest.mark.parametrize("handoff", [{"frames": 3}, {"frames": 4}], indirect=True)
def test_context_overlay_is_pure_and_hashes_original_not_effective_plan(handoff):
    state = handoff
    context = state.module._h3_prompt_context(state.db, state.shot, state.mode, state.clip, True, effective_context=state.bundle)
    assert context["planned_context_hash"] == state.bundle["planned_context_hash"]
    assert context["start_image_url"] == state.bundle["start_image_url"]
    assert context["keyframes"] == state.bundle["keyframes"]
    assert context["transitions"] == state.original_transitions
    assert context["audio"] == state.base_context["audio"]
    assert context["actual_state_handoff"]["trusted_state"] == state.bundle["trusted_state"]
    assert context["actual_state_handoff"]["effective_context_hash"] == state.module.prompt_digest(state.bundle)
    context["keyframes"][0]["description"] = "mutated copy"
    context["actual_state_handoff"]["trusted_state"].clear()
    assert state.bundle["keyframes"][0]["description"] == ACTUAL_DESCRIPTION
    assert state.bundle["trusted_state"]
    assert json.loads(state.shot.video_director_plan) == state.original_plan
    assert state.module._h3_prompt_context(state.db, state.shot, state.mode, state.clip, True, effective_context=None) == state.base_context


@pytest.mark.parametrize("handoff", [
    {"frames": 3}, {"frames": 4, "continuity": "CONTINUOUS_TAKE", "decision": "WARN"}, {"audio": False},
], indirect=True)
def test_handoff_reaches_model_and_selected_image_with_stable_prequeue_hash(handoff):
    state = handoff
    prompt, callback = build(state)
    sent = state.llm.await_args.kwargs
    payload = json.loads(sent["user_content"].split("\n\n", 1)[1])
    context = payload["actual_state_handoff"]
    assert sent["task_type"] == "h3_multi_keyframe_prompt"
    assert sent["system_prompt"] == state.template.template
    assert context["picture_1_description"] == payload["frames"][0]["description"] == ACTUAL_DESCRIPTION
    assert payload["keyframes"] == state.ai.strip_media_refs(state.bundle["keyframes"])
    assert payload["transitions"] == state.ai.strip_media_refs(state.original_transitions)
    assert "validated actual C1 tail" in context["picture_1_role"]
    assert context["trusted_state"] == [{"predicate": "character_location", "subject": "Ada", "value": "tree", "state": "PRESENT"}]
    assert context["canonical_state"][0]["protected"] is True
    assert "original P0 invariant requirements" in prompt
    assert "does not certify all pixels" in prompt
    assert "Keep declared AudioDrive speakers and timing unchanged" in prompt
    for private in ("/api/files/", "/private/", "private-raw-observation", "private-unknown-observation", "private-credentials", "private-image-task"):
        assert private not in sent["user_content"]
        assert private not in prompt
    layer = state.ai.build_handoff_continuity_layer(state.bundle)
    record = callback.validation_record
    assert layer in record["continuity_lock"]
    assert prompt.count("actual_state_handoff:") == 1
    assert record["raw_candidate"] == record["core"] == PROMPT
    assert record["context"]["start_image_url"] == state.bundle["start_image_url"]
    result = asyncio.run(state.comfy.ComfyUIService().generate_shot_video_with_workflow(
        prompt=prompt, workflow_json=state.workflow.workflow_json, node_mapping=state.mapping,
        character_reference_path=state.module.url_to_local_path(record["context"]["start_image_url"]),
        keyframe_paths=[state.module.url_to_local_path(frame["image_url"]) for frame in state.bundle["keyframes"][1:]],
        drive_audio_path=state.audio.get("drive_audio_path"), final_audio_path=state.audio.get("final_audio_path"),
        on_before_submit=callback,
    ))
    assert result["success"], result
    assert state.queued[0]["image"]["inputs"]["image"] == "uploaded/actual-c1-tail.png"
    assert state.comfy.resolve_h3_consumed_prompt(state.queued[0], state.mapping) == prompt
    assert record["prequeue_validation"]["final_prompt"] == prompt
    assert record["prequeue_validation"]["final_hash"] == record["final_hash"] == state.module.prompt_digest(prompt)
    if state.audio["enabled"]:
        assert [(item["start_time"], item["end_time"], item["visible_speaker"]) for item in record["speaker_timeline"]] == [
            (0, 1, "NONE"), (1, 3, "<Subject 1>"), (3, 4, "NONE"),
        ]
        assert record["audio_audit"]["passed"]
    assert json.loads(state.shot.video_director_plan)["keyframes"] == state.original_plan["keyframes"]
    assert json.loads(state.task.metadata_json)["unrelated"] == "keep"


@pytest.mark.parametrize("reuse", [False, True])
def test_default_none_ignores_persisted_handoff_and_keeps_manual_baseline(handoff, reuse):
    state = handoff
    prompt, callback = build(state, effective_context=None, start_image_url=state.base_context["start_image_url"],
                             keyframes=state.original_frames, transitions=state.original_transitions,
                             skip_llm_when_prompt_exists=reuse)
    assert prompt == PROMPT + "\n\ntext_rendering_constraint:\n" + CONSTRAINT
    assert callback.validation_record["context"] == state.base_context
    assert "effective_context" not in state.builder.await_args.kwargs
    callback(state.graph)
    assert state.llm.await_count == int(not reuse)
    assert "actual_state_handoff" not in prompt
    if not reuse:
        assert "actual_state_handoff" not in state.llm.await_args.kwargs["user_content"]
    assert state.ai.build_handoff_continuity_layer(None) == ""


@pytest.mark.parametrize("phase,change,code", [(phase, change, code)
    for phase in ("build", "llm", "prequeue") for change, code in [
    ("bundle", "HANDOFF_CONTEXT_NOT_AUTHORIZED"), ("reauthorized_bundle", "HANDOFF_CONTEXT_NOT_AUTHORIZED"),
    ("saved_bundle", "HANDOFF_CONTEXT_NOT_AUTHORIZED"), ("root_hash", "HANDOFF_CONTEXT_NOT_AUTHORIZED"),
    ("decision", "HANDOFF_CONTEXT_NOT_AUTHORIZED"), ("can_submit", "HANDOFF_CONTEXT_NOT_AUTHORIZED"),
    ("run", "HANDOFF_EXECUTION_CHANGED"), ("attempt", "HANDOFF_EXECUTION_CHANGED"), ("handle", "HANDOFF_EXECUTION_CHANGED"),
    ("source_image", "HANDOFF_PLANNED_CONTEXT_CHANGED"), ("source_description", "HANDOFF_PLANNED_CONTEXT_CHANGED"),
    ("source_transition", "HANDOFF_PLANNED_CONTEXT_CHANGED"),
] if (phase, change) != ("build", "reauthorized_bundle")])
def test_changed_authority_or_original_source_is_rejected(handoff, phase, change, code):
    state = handoff

    def mutate():
        if change in {"bundle", "reauthorized_bundle"}:
            state.bundle["trusted_state"][0]["value"] = "rock"
            if change == "reauthorized_bundle":
                edit_metadata(state, lambda data: data["actual_state_handoff"].update(
                    effective_context=deepcopy(state.bundle), effective_context_hash=state.module.prompt_digest(state.bundle)))
        elif change.startswith("source_"):
            def edit(plan):
                if change == "source_transition":
                    plan["transitions"][state.clip["keyframe_indexes"][0] - 1]["transition_description"] = "New movement"
                else:
                    plan["keyframes"][state.clip["keyframe_indexes"][0] - 1][change.removeprefix("source_").replace("image", "image_url")] = "New source"
            edit_plan(state, edit)
        elif change == "handle":
            state.shot._video_execution = {**state.handle, "run_id": "replacement"}
        else:
            def edit(data):
                root = data["actual_state_handoff"]
                if change == "saved_bundle":
                    root["effective_context"]["evidence_hash"] = "c" * 64
                    root["effective_context_hash"] = state.module.prompt_digest(root["effective_context"])
                elif change == "root_hash":
                    root["effective_context_hash"] = "c" * 64
                elif change == "decision":
                    root["decision"] = "BLOCK"
                elif change == "can_submit":
                    root["can_submit_c2"] = False
                elif change == "run":
                    data["video_run"]["run_id"] = "replacement"
                else:
                    data["video_run"]["clips"]["2"]["attempt_id"] = "replacement"
            edit_metadata(state, edit)

    if phase == "build":
        mutate()
    elif phase == "llm":
        async def complete(**kwargs):
            mutate()
            return {"success": True, "content": PROMPT}
        state.llm.side_effect = complete
    with pytest.raises(state.ai.H3PromptValidationError, match=code):
        prompt, callback = build(state)
        assert phase == "prequeue"
        mutate()
        callback(state.graph)
    state.client.queue_prompt.assert_not_awaited()
    assert records(state, 2)[0]["passed"] is False
    if phase == "build":
        state.llm.assert_not_awaited()


@pytest.mark.parametrize("field", ["keyframes", "transitions"])
def test_supplied_effective_inputs_must_match_whole_authorized_bundle(handoff, field):
    state = handoff
    changed = deepcopy(state.bundle[field])
    changed[0]["unapproved_field"] = True
    with pytest.raises(state.ai.H3PromptValidationError, match="VISUAL_INPUTS_CHANGED"):
        build(state, **{field: changed})
    state.llm.assert_not_awaited()


def test_handoff_cannot_reuse_existing_manual_prompt(handoff):
    state = handoff
    with pytest.raises(state.ai.H3PromptValidationError, match="HANDOFF_REQUIRES_FRESH_PROMPT"):
        build(state, skip_llm_when_prompt_exists=True)
    assert json.loads(state.shot.video_director_plan) == state.original_plan
    state.builder.assert_not_awaited()
    state.llm.assert_not_awaited()


@pytest.mark.parametrize("failure_kind", ["TIMEOUT", "SERVICE_ERROR"])
def test_fallback_uses_effective_first_state_and_same_managed_layer(handoff, failure_kind):
    state = handoff
    state.llm.return_value = {"success": False, "failure_kind": failure_kind, "error": "unavailable"}
    prompt, callback = build(state)
    record = callback.validation_record
    assert record["origin"] == "fallback"
    assert record["profile"] == "deterministic_fallback"
    assert f"description={ACTUAL_DESCRIPTION}" in record["raw_candidate"]
    assert state.original_frames[0]["description"] not in record["raw_candidate"]
    assert state.ai.build_handoff_continuity_layer(state.bundle) in prompt
    callback(state.graph)
    assert record["prequeue_validation"]["final_prompt"] == prompt
    assert record["prequeue_validation"]["final_hash"] == record["final_hash"]
    assert json.loads(state.shot.video_director_plan)["keyframes"] == state.original_plan["keyframes"]


def test_handoff_does_not_rescue_invalid_model_core(handoff):
    handoff.llm.return_value = {"success": True, "content": "not a director document"}
    with pytest.raises(handoff.ai.H3PromptValidationError, match="UNSUPPORTED_DIRECTOR_FORMAT"):
        build(handoff)
    handoff.client.queue_prompt.assert_not_awaited()


@pytest.mark.parametrize("field,value,code", [
    ("version", 2, "INVALID_HANDOFF_CONTEXT"), ("source", "planned_keyframe", "INVALID_HANDOFF_CONTEXT"),
    ("from_clip", 2, "INVALID_HANDOFF_CONTEXT"), ("to_clip", 3, "INVALID_HANDOFF_CONTEXT"),
    ("run_id", "other-run", "HANDOFF_EXECUTION_CHANGED"),
    ("clip_attempt_id", "c1-attempt", "HANDOFF_EXECUTION_CHANGED"),
])
def test_saved_bundle_still_requires_c1_to_c2_same_run_identity(handoff, field, value, code):
    state = handoff
    state.bundle[field] = value
    edit_metadata(state, lambda data: data["actual_state_handoff"].update(
        effective_context=deepcopy(state.bundle), effective_context_hash=state.module.prompt_digest(state.bundle)))
    with pytest.raises(state.ai.H3PromptValidationError, match=code):
        build(state)
    state.llm.assert_not_awaited()


@pytest.mark.parametrize("change", ["clip", "mode", "graph", "missing_authority", "missing_handle", "start_image"])
def test_handoff_is_not_a_generic_prompt_override(handoff, change):
    state = handoff
    kwargs = {}
    code = "HANDOFF_REQUIRES_C2_H3"
    if change == "clip":
        kwargs["clip"] = {**state.clip, "clip_index": 1}
    elif change == "mode":
        kwargs["selected_mode"] = "SINGLE_FRAME"
    elif change == "graph":
        state.graph["h3"]["class_type"] = "LTXVConditioning"
        state.workflow.workflow_json = json.dumps(state.graph)
        state.db.commit()
    elif change == "missing_authority":
        edit_metadata(state, lambda data: data.pop("actual_state_handoff"))
        code = "HANDOFF_CONTEXT_NOT_AUTHORIZED"
    elif change == "missing_handle":
        del state.shot._video_execution
        del state.task._video_execution
        code = "HANDOFF_EXECUTION_CHANGED"
    else:
        kwargs["start_image_url"] = state.base_context["start_image_url"]
        code = "START_IMAGE_CHANGED"
    with pytest.raises(state.ai.H3PromptValidationError, match=code):
        build(state, **kwargs)
    state.llm.assert_not_awaited()


@pytest.mark.parametrize("handoff", [{}, {"continuity": "CONTINUOUS_TAKE"}], indirect=True)
def test_handoff_managed_prefix_preserves_json_audio_speech_scoping(handoff):
    state = handoff
    candidate = json.dumps({
        "subject_definitions": "<Subject 1>: Ada. <Subject 2>: Bea.", "summary": "Ada waits by the tree.",
        "detailed_description": "The camera moves slowly towards Ada.", "initial_state_anchor": ACTUAL_DESCRIPTION,
        "dialogue_timeline": "0s-1s visible_speaker=NONE: no speaking or lip-sync.\n"
        "1s-3s visible_speaker=<Subject 1>: speaking.\n3s-4s visible_speaker=NONE: no speaking or lip-sync.",
        "overall_soundscape": "Only <Subject 1> speaks during 1s-3s.",
    })
    state.llm.return_value = {"success": True, "content": candidate}
    prompt, callback = build(state)
    callback(state.graph)
    record = callback.validation_record
    assert record["core"] == record["raw_candidate"] == candidate
    assert record["audio_audit"]["passed"] is True
    assert record["prequeue_validation"]["final_prompt"] == prompt
    assert record["prequeue_validation"]["final_hash"] == record["final_hash"]


def test_prompt_projection_never_promotes_unknown_observations(handoff):
    state = handoff
    bundle = deepcopy(state.bundle)
    bundle["trusted_state"].extend([
        {"predicate": "prop_present", "subject": "unknown-prop", "state": "UNKNOWN", "evidence": "private-unknown"},
        {"predicate": "prop_present", "subject": "uncertain-prop", "state": "PRESENT", "confidence": "LOW"},
    ])
    layer = state.ai.build_handoff_continuity_layer(bundle)
    assert "unknown-prop" not in layer
    assert "uncertain-prop" not in layer
    assert "private-unknown" not in layer
    assert '"value":"tree"' in layer
    assert '"subject":"bag"' in layer
