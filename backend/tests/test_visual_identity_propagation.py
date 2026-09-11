"""Bounded request-fact tests: --noconftest, reused isolated DB/provider fixtures."""
import asyncio
from copy import deepcopy
import importlib.util
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import test_keyframe_reference_worker as keyframes
from test_keyframe_reference_worker import worker as reference_worker
import test_h3_prompt_worker as h3
from test_h3_prompt_worker import worker as h3_worker
from test_execution_integrity_api import api


def test_06_name_bound_saved_facts_do_not_expand_references_or_visual_cast(api, monkeypatch):
    models, db = api.models.novel, api.db
    api.writes_forbidden = False
    api.shot.characters = json.dumps(["Bea", "Ada", "Voice", "Narrator", "Unknown"])
    api.shot.props = json.dumps(["sword", "lantern"])
    api.shot.description = "Ada in a torn gray coat has dropped the damaged sword. Bea watches."
    db.add_all([
        models.Character(id="ada", novel_id="novel", name="Ada", appearance="age 70, blue wool coat", image_url="/api/files/ada.png"),
        models.Character(id="bea", novel_id="novel", name="Bea", appearance="age 20, red linen coat"),
        models.Character(id="voice", novel_id="novel", name="Voice", appearance="invisible narrator", is_narrator=True, image_url="/api/files/voice.png"),
        models.Character(id="narrator", novel_id="novel", name="Narrator", appearance="not visual", image_url="/api/files/narrator.png"),
        models.Character(id="other", novel_id="other-novel", name="Ada", appearance="wrong novel"),
        models.Prop(id="sword", novel_id="novel", name="sword", appearance="bronze guard, short steel blade", image_url="/api/files/sword.png"),
        models.Prop(id="lantern", novel_id="novel", name="lantern", appearance="square brass frame"),
        models.Prop(id="unlisted", novel_id="novel", name="crown", appearance="gold"),
    ])
    db.commit()
    api.writes_forbidden = True
    monkeypatch.setattr(api.module, "get_style", lambda *args: ("ink and muted mineral colors", None))
    before = api.shot.description, api.shot.characters, api.shot.shot_image_prompt, api.shot.video_director_plan
    payload = json.loads(api.module._build_shot_image_prompt_input(db, api.novel, api.shot, "reference_image_manifest").split("\n\n", 1)[1])
    facts = payload["visual_identity"]
    assert facts["characters"] == payload["shot"]["characters"] == ["Bea", "Ada", "Unknown"]
    assert facts["character_appearances"] == {"Bea": "age 20, red linen coat", "Ada": "age 70, blue wool coat"}
    assert facts["prop_appearances"] == {"sword": "bronze guard, short steel blade", "lantern": "square brass frame"}
    assert facts["visual_style"] == payload["visual_style"] == "ink and muted mineral colors"
    assert payload["reference_image_manifest"] == [
        {"picture_index": 1, "type": "MERGED_CHARACTER", "members": ["Ada"]},
        {"picture_index": 2, "type": "MERGED_PROP", "members": ["sword"]},
    ]
    assert (api.shot.description, api.shot.characters, api.shot.shot_image_prompt, api.shot.video_director_plan) == before
    rule = facts["preservation_rule"]
    for phrase in ("exact saved name", "not extra reference pictures", "primary visible identity", "unknown stable features",
                   "never override visible age", "held/dropped/absent props", "damage", "explicit costume or age changes",
                   "Do not restore baseline clothes", "re-equip dropped props", "narrator is audio-only", "With no bound image"):
        assert phrase in rule
    legacy = json.loads(api.module._build_shot_image_prompt_input(db, api.novel, api.shot, "reference_bundle").split("\n\n", 1)[1])
    assert legacy["visual_identity"] == facts
    assert legacy["reference_bundle"]["picture_1"]["members"] == ["Ada"]


@pytest.mark.parametrize("characters,props,expected", [
    ([], [], "shot_scene"), ([], ["sword"], "shot_scene_prop"),
    (["Ada"], [], "shot_character_scene"), (["Ada"], ["sword"], "shot"),
])
def test_06_workflow_selection_still_depends_on_images_not_appearance(api, characters, props, expected):
    models = api.models.novel
    api.writes_forbidden = False
    api.shot.characters, api.shot.props, api.shot.scene = json.dumps(characters), json.dumps(props), "gate"
    api.db.add_all([
        models.Character(novel_id="novel", name="Ada", appearance="blue coat", image_url="/api/files/ada.png"),
        models.Prop(novel_id="novel", name="sword", appearance="steel", image_url="/api/files/sword.png"),
        models.Scene(novel_id="novel", name="gate", image_url="/api/files/gate.png"),
    ])
    api.db.commit()
    api.writes_forbidden = True
    assert api.module._resolve_shot_image_workflow_type(api.db, api.novel, api.shot) == expected


def test_08_uses_selected_saved_style_in_template_and_payload_without_editing_template(api, monkeypatch):
    spec = importlib.util.spec_from_file_location("_identity_prompt_builder", keyframes.BACKEND / "app/services/prompt_builder.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    monkeypatch.setattr(api.module, "get_style", builder.get_style)
    api.writes_forbidden = False
    Template = api.models.prompt_template.PromptTemplate
    style = Template(id="style", type="style", name="Selected style", template="charcoal lines, warm paper")
    planner = Template(id="planner", type="keyframe_planner", name="Planner", template="Style: ##STYLE##\nKeep ##STYLE## consistent.")
    api.db.add_all([style, planner])
    api.novel.style_prompt_template_id = style.id
    api.shot.video_director_plan = '{"selected_mode":"FIRST_LAST_FRAME","workflow_capability":{"max_clip_duration":15}}'
    api.db.commit()
    monkeypatch.setattr(api.module, "_get_keyframe_planner_template", lambda *args: planner)
    monkeypatch.setattr(api.module, "_plan_keyframe_transitions", AsyncMock(return_value=[]))
    api.llm.chat_completion.return_value = {"success": True, "content": json.dumps({
        "validation": {"executable": True}, "window_plans": [], "keyframes": [
            {"index": 1, "role": "START", "time_seconds": 0, "description": "Start"},
            {"index": 2, "role": "END", "time_seconds": 4, "description": "End"},
        ],
    })}
    response = api.post("/video-director/plan-keyframes", {"force": True})
    assert response.status_code == 200, response.text
    kwargs = api.llm.chat_completion.await_args.kwargs
    assert kwargs["system_prompt"] == "Style: charcoal lines, warm paper\nKeep charcoal lines, warm paper consistent."
    assert json.loads(kwargs["user_content"].split("\n\n", 1)[1])["visual_style"] == style.template
    api.db.refresh(planner)
    assert planner.template == "Style: ##STYLE##\nKeep ##STYLE## consistent."


@pytest.mark.parametrize("mode,source", [("auto_select", "PRIMARY_STORYBOARD"), ("custom", "CUSTOM_REFERENCE"), ("none", "NONE")])
def test_09_freezes_new_source_facts_at_request_without_phantom_images(reference_worker, mode, source):
    state = reference_worker
    keyframes.configure(state, mode=mode, reference=state.urls["custom"] if mode == "custom" else None)
    with state.sessions() as db:
        db.get(state.novels.Prop, "prop").appearance = "bronze guard, short steel blade"
        db.commit()
    keyframes.create(state)
    captured = deepcopy(keyframes.saved(state).contract["context"]["visual_identity"])
    assert captured["character_appearances"] == {"Ada": "blue coat", "Bea": "red coat"}
    with state.sessions() as db:
        db.get(state.novels.Character, "ada").appearance = "newly edited text, not this request"
        db.get(state.novels.Prop, "prop").appearance = "newly edited prop"
        db.commit()
    result = keyframes.run(state)
    keyframes.assert_completed(state, result, source)
    assert result.contract["context"]["visual_identity"] == captured == state.inputs[-1]["visual_identity"]
    assert captured["prop_appearances"] == {"sword": "bronze guard, short steel blade"}
    assert len(state.inputs[-1]["reference_image_manifest"]) == (0 if mode == "none" else 1)
    assert len(state.uploads) == (0 if mode == "none" else 1)


@pytest.mark.parametrize("changed", ["character", "prop", "style"])
def test_09_new_facts_are_cache_significant_but_do_not_rewrite_prior_contract(reference_worker, changed, monkeypatch):
    state = reference_worker
    first_id = keyframes.create(state)
    first = keyframes.run(state)
    frozen = deepcopy(first.contract)
    with state.sessions() as db:
        if changed == "character":
            db.get(state.novels.Character, "ada").appearance = "age 80, patched coat"
        elif changed == "prop":
            db.get(state.novels.Prop, "prop").appearance = "short bronze sword"
        db.commit()
    if changed == "style":
        monkeypatch.setattr(state.module, "get_style", lambda *args: ("new formal style", None))
    keyframes.create(state, skip_llm_when_prompt_exists=True)
    result = keyframes.run(state)
    keyframes.assert_failed(state, result, "CACHE_BINDING_UNVERIFIED", queued=1, llm=1)
    assert result.contract["prompt"]["cache_fingerprint"] != frozen["prompt"]["cache_fingerprint"]
    assert keyframes.saved(state, first_id).contract == frozen
    assert state.contracts.validate_frozen_contract(frozen, first.task, require_submitted=True)["reference_count"] == 1
    tampered = deepcopy(frozen)
    tampered["context"]["visual_identity"]["prop_appearances"]["sword"] = "tampered"
    state.contracts.seal_contract(tampered)
    with pytest.raises(state.contracts.KeyframeReferenceError, match="CACHE_PROOF_INVALID"):
        state.contracts.validate_frozen_contract(tampered)


def test_09_preexisting_request_without_identity_fields_is_not_retrofitted(reference_worker):
    state = reference_worker
    keyframes.create(state)
    with state.sessions() as db:
        task = db.get(state.Task, state.task_id)
        metadata = json.loads(task.metadata_json)
        contract = metadata[keyframes.KEY]
        contract.pop("context")
        state.contracts.seal_contract(contract)
        task.metadata_json = json.dumps(metadata)
        db.commit()
    result = keyframes.run(state)
    keyframes.assert_completed(state, result, "PRIMARY_STORYBOARD")
    assert "visual_identity" not in result.contract["context"]
    assert "visual_identity" not in state.inputs[-1]
    frozen = deepcopy(result.contract)
    state.contracts.validate_frozen_contract(result.contract, result.task, require_submitted=True)
    assert result.contract == frozen


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"])
@pytest.mark.parametrize("fallback", [False, True])
def test_h3_new_llm_and_fallback_inputs_share_named_facts_and_style(h3_worker, mode, fallback):
    state = h3_worker
    state.configure(mode)
    state.shot.props = '["sword"]'
    state.shot.characters = '["Bea", "Ada", "Voice", "Narrator"]'
    state.db.get(state.models.Character, "ada").appearance = "age 70, blue wool coat"
    state.db.add_all([
        state.models.Prop(id="sword", novel_id="novel", name="sword", appearance="bronze guard, short steel blade"),
        state.models.Character(id="voice", novel_id="novel", name="Voice", appearance="not visual", is_narrator=True),
    ])
    state.db.commit()
    if fallback:
        state.llm.return_value = {"success": False, "failure_kind": "SERVICE_ERROR", "error": "isolated provider failure"}
    prompt, _ = h3.build(state)
    payload = json.loads(state.llm.await_args.kwargs["user_content"].split("\n\n", 1)[1])
    facts = payload["visual_identity"]
    assert facts["characters"] == ["Bea", "Ada"]
    assert facts["character_appearances"] == payload["shot"]["official_character_appearances"] == {
        "Bea": "red coat", "Ada": "age 70, blue wool coat",
    }
    assert facts["prop_appearances"] == {"sword": "bronze guard, short steel blade"}
    assert facts["visual_style"] == "isolated painterly style"
    assert [(item["subject_ref"], item["character_name"], item["appearance"]) for item in payload["subject_manifest"]["subjects"]] == [
        ("<Subject 1>", "Bea", "red coat"), ("<Subject 2>", "Ada", "age 70, blue wool coat"),
    ]
    record = h3.records(state, 1)[0]
    assert record["visual_identity"] == facts
    assert record["input_hash"] == state.ai.prompt_digest(payload)
    assert record["origin"] == ("fallback" if fallback else "llm")
    if fallback:
        assert json.dumps(facts, ensure_ascii=False) in prompt
        assert record["profile"] == "deterministic_fallback"
    else:
        assert record["raw_candidate"] == h3.PROMPT
    state.client.queue_prompt.assert_not_awaited()


@pytest.mark.parametrize("change", ["character", "prop", "style"])
@pytest.mark.parametrize("trim_calls", [False, True])
def test_h3_cached_new_fact_snapshot_requires_explicit_refresh_on_change(h3_worker, change, trim_calls, monkeypatch):
    state = h3_worker
    state.shot.props = '["sword"]'
    prop = state.models.Prop(id="sword", novel_id="novel", name="sword", appearance="short steel blade")
    state.db.add(prop)
    state.db.commit()
    prompt, _ = h3.build(state)
    first = deepcopy(h3.records(state, 1)[0])
    if trim_calls:
        plan = json.loads(state.shot.video_director_plan)
        plan["ai_calls"] = []
        state.shot.video_director_plan = json.dumps(plan)
    if change == "character":
        state.db.get(state.models.Character, "ada").appearance = "different coat"
    elif change == "prop":
        prop.appearance = "different sword"
    else:
        monkeypatch.setattr(sys.modules["app.services.prompt_builder"], "get_style", lambda *args: ("different style", None))
    state.db.commit()
    with pytest.raises(Exception, match="VISUAL_IDENTITY_CHANGED"):
        h3.build(state, reuse=True)
    assert h3.records(state, 1)[0] == first
    assert json.loads(state.shot.video_director_plan)[state.collection][0]["prompt_text"] == prompt
    assert state.llm.await_count == 1
    state.client.queue_prompt.assert_not_awaited()


def test_h3_preserves_saved_whitespace_and_unchanged_cache_through_prequeue(h3_worker):
    state = h3_worker
    state.db.get(state.models.Character, "ada").appearance = "  age 70, blue coat\n"
    state.db.commit()
    prompt, callback = h3.build(state)
    assert callback.validation_record["visual_identity"]["character_appearances"]["Ada"] == "  age 70, blue coat\n"
    assert h3.submit(state, prompt, callback)["success"]
    cached, _ = h3.build(state, reuse=True)
    assert cached == prompt
    assert state.llm.await_count == 1


def test_h3_fact_only_fallback_cannot_replace_missing_visual_direction(h3_worker):
    state = h3_worker
    state.shot.description = state.shot.video_description = ""
    prompt = state.ai._build_deterministic_h3_prompt(
        state.shot, "SINGLE_FRAME", {"start_time": 0, "end_time": 4}, [], [], [], {},
        visual_identity={"character_appearances": {"Ada": "blue coat"}, "visual_style": "ink"},
    )
    with pytest.raises(state.ai.H3PromptValidationError, match="FALLBACK_VISUAL_DIRECTION_MISSING"):
        state.ai.prepare_h3_prompt(
            prompt, constraint="", continuity_lock="", subject_manifest={"subjects": []}, speaker_timeline=[],
            audio_drive_enabled=False, fallback_context={"shot_index": 1, "selected_mode": "SINGLE_FRAME", "start_time": 0, "end_time": 4},
        )


@pytest.fixture
def shot_images(reference_worker, monkeypatch):
    state = reference_worker
    for name in ("app.utils.image_utils", "app.utils.workflow_disconnect", "app.services.shot_image_service"):
        spec = importlib.util.spec_from_file_location(name, keyframes.BACKEND / (name.replace(".", "/") + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    state.images = module
    state.mapping = {f"{role}_reference_image_node_id": role for role in ("character", "scene", "prop")}
    state.graph = {role: {"class_type": "LoadImage", "inputs": {"image": "unused.png"}} for role in ("character", "scene", "prop")}
    state.provider = SimpleNamespace(
        builder=SimpleNamespace(build_shot_workflow=Mock(side_effect=lambda **kwargs: deepcopy(state.graph))),
        client=SimpleNamespace(upload_image=AsyncMock(return_value={"success": True, "filename": "uploaded.png"})),
        generate_shot_image_with_workflow=AsyncMock(return_value={"success": False, "message": "isolated submission stop"}),
    )
    monkeypatch.setattr(state.images, "ComfyUIService", lambda: state.provider)
    state.merge_characters = Mock(return_value=state.to_path(state.urls["characters"]))
    state.merge_props = Mock(return_value=state.to_path(state.urls["prop"]))
    monkeypatch.setattr(state.images, "merge_character_images", state.merge_characters)
    monkeypatch.setattr(state.images, "merge_prop_images", state.merge_props)
    with state.sessions() as db:
        workflow = db.get(state.Workflow, "workflow")
        workflow.workflow_json, workflow.node_mapping = json.dumps(state.graph), json.dumps(state.mapping)
        shot = db.get(state.Shot, "shot")
        shot.props = '["sword", "shield"]'
        db.add(state.novels.Prop(id="shield", novel_id="novel", name="shield", appearance="round oak shield", image_url=state.urls["prop"]))
        task = state.Task(id="image-attempt", type="shot_image", name="New production image", status="pending",
                          novel_id="novel", chapter_id="chapter", shot_id="shot", workflow_id="workflow", metadata_json='{"unrelated":"keep"}')
        db.add(task)
        db.commit()
        state.task_id = task.id
    return state


def run_shot_image(state):
    asyncio.run(state.images.generate_shot_image_task(state.task_id, "novel", "chapter", 1, "Accepted literal prompt", "workflow"))
    return keyframes.saved(state)


@pytest.mark.parametrize("role", ["character", "prop"])
def test_shot_image_merge_failure_never_submits_partial_reference_set(shot_images, role):
    state = shot_images
    (state.merge_characters if role == "character" else state.merge_props).return_value = None
    before = keyframes.saved(state).shot.image_url
    result = run_shot_image(state)
    assert result.task.status == "failed"
    assert "\u5408\u5e76\u5931\u8d25" in result.task.error_message and "\u672a\u63d0\u4ea4\u751f\u6210" in result.task.error_message
    assert ("Ada, Bea" if role == "character" else "sword, shield") in result.task.error_message
    state.provider.generate_shot_image_with_workflow.assert_not_awaited()
    state.provider.client.upload_image.assert_not_awaited()
    assert result.shot.image_url == before


@pytest.mark.parametrize("receipt", [{"success": False, "message": "offline"}, {"success": True}, {"success": True, "filename": " "}, None, OSError("offline")])
def test_shot_image_upload_failure_never_disconnects_and_submits(shot_images, receipt, monkeypatch):
    state = shot_images
    upload = state.provider.client.upload_image
    if isinstance(receipt, Exception):
        upload.side_effect = receipt
    else:
        upload.return_value = receipt
    disconnect = Mock(side_effect=AssertionError("Failed references must not be silently disconnected"))
    monkeypatch.setattr(state.images, "disconnect_reference_chain", disconnect)
    result = run_shot_image(state)
    assert result.task.status == "failed" and "\u4e0a\u4f20\u5931\u8d25" in result.task.error_message
    state.provider.generate_shot_image_with_workflow.assert_not_awaited()
    disconnect.assert_not_called()
    assert not result.task.reference_images


@pytest.mark.parametrize("role", ["character", "scene", "prop"])
def test_shot_image_unavailable_member_fails_actionably(shot_images, role):
    state = shot_images
    with state.sessions() as db:
        model, id_ = {"character": (state.novels.Character, "bea"), "scene": (state.novels.Scene, "scene"), "prop": (state.novels.Prop, "shield")}[role]
        db.get(model, id_).image_url = "/api/files/missing.png"
        db.commit()
    result = run_shot_image(state)
    assert result.task.status == "failed" and "\u53c2\u8003\u56fe\u4e0d\u53ef\u7528" in result.task.error_message
    state.provider.generate_shot_image_with_workflow.assert_not_awaited()


@pytest.mark.parametrize("characters,props", [(False, False), (False, True), (True, False), (True, True)])
def test_shot_image_valid_no_character_no_prop_and_custom_prop_slot_remain_supported(shot_images, characters, props):
    state = shot_images
    with state.sessions() as db:
        if not characters:
            for character in db.query(state.novels.Character).all():
                character.image_url = None
        if not props:
            for prop in db.query(state.novels.Prop).all():
                prop.image_url = None
        mapping = {"scene_reference_image_node_id": "scene"}
        if characters:
            mapping["character_reference_image_node_id"] = "character"
        if props:
            mapping["custom_reference_image_node_1"] = "prop"
        db.get(state.Workflow, "workflow").node_mapping = json.dumps(mapping)
        db.commit()
    result = run_shot_image(state)
    state.provider.generate_shot_image_with_workflow.assert_awaited_once()
    assert state.provider.client.upload_image.await_count == 1 + characters + props
    metadata = json.loads(result.task.metadata_json)
    assert metadata["unrelated"] == "keep"
    assert metadata["visual_identity"]["prop_appearances"] == {"shield": "round oak shield"}
    assert result.task.prompt_text == "Accepted literal prompt"
    assert len(json.loads(result.task.reference_images)) == 1 + characters + props


def test_shot_image_supplied_role_without_workflow_binding_never_submits(shot_images):
    state = shot_images
    with state.sessions() as db:
        db.get(state.Workflow, "workflow").node_mapping = '{"scene_reference_image_node_id":"scene"}'
        db.commit()
    result = run_shot_image(state)
    assert result.task.status == "failed" and "\u65e0\u6cd5\u7ed1\u5b9a" in result.task.error_message
    state.provider.generate_shot_image_with_workflow.assert_not_awaited()
    state.provider.client.upload_image.assert_not_awaited()


def test_shot_image_reference_alias_does_not_duplicate_or_disconnect_bound_prop(shot_images, monkeypatch):
    state = shot_images
    with state.sessions() as db:
        mapping = {**state.mapping, "custom_reference_image_node_1": "prop"}
        db.get(state.Workflow, "workflow").node_mapping = json.dumps(mapping)
        db.commit()
    disconnect = Mock(side_effect=AssertionError("An alias must not disconnect the bound prop"))
    monkeypatch.setattr(state.images, "disconnect_reference_chain", disconnect)
    result = run_shot_image(state)
    assert state.provider.client.upload_image.await_count == 3
    state.provider.generate_shot_image_with_workflow.assert_awaited_once()
    assert len(json.loads(result.task.reference_images)) == 3
    assert json.loads(result.task.workflow_json)["prop"]["inputs"]["image"] == "uploaded.png"
    disconnect.assert_not_called()
