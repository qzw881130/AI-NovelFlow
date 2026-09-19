"""Run with --noconftest: exact historical cores, no app startup or external I/O."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from types import ModuleType, SimpleNamespace

import pytest


BACKEND = Path(__file__).resolve().parents[1]
HISTORY = json.loads(Path(__file__).with_name("h3_prompt_gate_fixtures.json").read_text(encoding="utf-8"))
CONSTRAINT = HISTORY["constraint"]
REQUIRED_FIELDS = ("subject_definitions", "summary", "detailed_description", "overall_soundscape")
ANCHORS = ("initial_state_anchor", "frame_definitions", "keyframe_timeline")
FALLBACK_CONTEXT = {"shot_index": 7, "selected_mode": "SINGLE_FRAME", "start_time": 0.0, "end_time": 4.0}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load("_isolated_h3_prompt_core", BACKEND / "app/services/h3_prompt_validation.py")
speech_scope = _load("_isolated_h3_speech_scope", BACKEND / "app/services/h3_speech_scope.py")


def _forbidden(*args, **kwargs):
    raise AssertionError("Application startup, database, network, and directory writes are forbidden")


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)
    monkeypatch.setattr(sqlite3, "connect", _forbidden)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", _forbidden)
    monkeypatch.setattr(Path, "mkdir", _forbidden)


@pytest.fixture
def director_ai(monkeypatch):
    # Execute the actual preparation/audit functions, never app package initializers.
    def stub(name, **attributes):
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)

    for name in ("app", "app.core", "app.models", "app.repositories", "app.services",
                 "app.services.llm", "sqlalchemy"):
        stub(name, __path__=[])
    stub("sqlalchemy.orm", Session=_forbidden)
    stub("app.core.database", SessionLocal=_forbidden)
    stub("app.core.config", get_settings=_forbidden)
    stub("app.models.novel", Novel=_forbidden)
    stub("app.repositories.prompt_template", PromptTemplateRepository=_forbidden)
    stub("app.services.llm.base", mark_matching_pending_llm_logs_error=_forbidden)
    stub("app.services.llm_service", LLMService=_forbidden)
    monkeypatch.setitem(sys.modules, "app.services.h3_prompt_validation", gate)
    monkeypatch.setitem(sys.modules, "app.services.h3_speech_scope", speech_scope)
    return _load("_isolated_h3_director_audit", BACKEND / "app/services/video_director_ai.py")


def _document(anchor="initial_state_anchor"):
    return {
        "subject_definitions": "<Subject 1> is a fox; keep its red coat and identity.",
        "summary": "The fox sits.",
        "detailed_description": "Pan gently towards the seated fox, then hold.",
        "overall_soundscape": "Wind. No visible character speech.",
        anchor: "<Picture 1> shows the fox beside a tree.",
    }


def _prose(document):
    return "\n\n".join(f"{name}:\n{body}" for name, body in document.items())


def _decorate(core):
    return f"{core}\n\ntext_rendering_constraint:\n{CONSTRAINT}"


def _fallback(context=None, description="The fox sits beside a tree.", keyframes=""):
    context = FALLBACK_CONTEXT if context is None else context
    return (
        f"Generate Shot {context['shot_index']} as {context['selected_mode']}.\n"
        f"Clip range: {context['start_time']:.3f}s to {context['end_time']:.3f}s in shot time.\n"
        "Use the provided reference pictures as chronological visual anchors in exact order.\n"
        "Preserve character identity, scene geography, lighting continuity, and camera continuity.\n"
        "Do not add subtitles, captions, new dialogue, new characters, or unplanned actions.\n\n"
        f"shot_description:\n{description}\n\n"
        f"keyframe_timeline:\n{keyframes}\n\n"
        "speaker_timeline:\n0.0s-4.0s: visible_speaker=NONE\n\n"
        "audio_drive:\naudio_mode=lock_source\ndrive_audio=provided drive audio\n"
        "final_audio=provided final audio\n"
        "drive_audio controls visible lip-sync only; final_audio is the complete audience-facing audio."
    )


@pytest.mark.parametrize("case_id,characters", [("53C1", 7425), ("115C1", 363), ("119C3", 1)])
def test_historical_core_and_final_match_original_submission_hashes(case_id, characters):
    case = HISTORY["cases"][case_id]
    assert len(case["core"]) == case["core_characters"] == characters
    assert hashlib.sha256(case["core"].encode("utf-8")).hexdigest() == case["core_sha256"]
    assert hashlib.sha256(_decorate(case["core"]).encode("utf-8")).hexdigest() == case["final_sha256"]
    assert gate.prompt_digest(case["core"]) == case["core_sha256"]
    assert gate.strip_h3_managed_layers(_decorate(case["core"]), CONSTRAINT) == case["core"]


@pytest.mark.parametrize("decorated", [False, True], ids=["core", "submitted-final"])
def test_actual_53_director_json_is_accepted_without_losing_nested_fields(decorated):
    case = HISTORY["cases"]["53C1"]
    value = _decorate(case["core"]) if decorated else case["core"]
    result = gate.validate_h3_prompt_core(gate.strip_h3_managed_layers(value, CONSTRAINT))
    assert result["profile"] == "director_json"
    assert result["core"] == case["core"]
    assert result["core_hash"] == case["core_sha256"]
    document = json.loads(result["core"])
    assert set(document) == {*REQUIRED_FIELDS, "official_character_identity_lock", "keyframe_timeline", "dialogue_timeline"}
    assert set(document["subject_definitions"]) == {"<Subject 1>", "<Subject 2>"}
    assert all(isinstance(value, str) for value in document["subject_definitions"].values())
    assert all(isinstance(value, str) for key, value in document.items() if key != "subject_definitions")


@pytest.mark.parametrize("case_id,code", [("115C1", "DIRECTOR_SECTIONS_MISSING"), ("119C3", "EMPTY_CORE")])
@pytest.mark.parametrize("decorated", [False, True], ids=["core", "submitted-final"])
def test_actual_invalid_core_stays_rejected_after_stripping_managed_suffix(case_id, code, decorated):
    core = HISTORY["cases"][case_id]["core"]
    value = _decorate(core) if decorated else core
    stripped = gate.strip_h3_managed_layers(value, CONSTRAINT)
    assert stripped == core
    with pytest.raises(gate.H3PromptValidationError) as exc:
        gate.validate_h3_prompt_core(stripped)
    assert exc.value.code == code


@pytest.mark.parametrize("anchor", ANCHORS)
@pytest.mark.parametrize("format_name", ["prose", "json"])
def test_all_director_anchor_formats_are_accepted(anchor, format_name):
    document = _document(anchor)
    if anchor == "keyframe_timeline":
        document["dialogue_timeline"] = "All visible characters remain silent; no speech lip-sync."
    value = _prose(document) if format_name == "prose" else json.dumps(document)
    result = gate.validate_h3_prompt_core(value)
    assert result["profile"] == f"director_{format_name}"
    assert result["core"] == value


@pytest.mark.parametrize("subjects", ["", " \n\t", "No visible subjects.", {}])
def test_explicit_empty_subject_permission_accepts_unpopulated_scenes(subjects):
    document = _document()
    document["subject_definitions"] = subjects
    assert gate.validate_h3_prompt_core(json.dumps(document), allow_empty_subjects=True)["profile"] == "director_json"
    if isinstance(subjects, str):
        assert gate.validate_h3_prompt_core(_prose(document), allow_empty_subjects=True)["profile"] == "director_prose"


@pytest.mark.parametrize("subjects", ["", " \n\t", {}])
def test_empty_subjects_need_explicit_permission(subjects):
    document = _document()
    document["subject_definitions"] = subjects
    with pytest.raises(gate.H3PromptValidationError, match="INVALID_DIRECTOR_SECTION"):
        gate.validate_h3_prompt_core(json.dumps(document))


@pytest.mark.parametrize("value", [None, True, 17, [], {}, b"summary: fox"])
def test_non_string_api_content_is_rejected(value):
    with pytest.raises(gate.H3PromptValidationError, match="UNSUPPORTED_CONTENT_TYPE"):
        gate.validate_h3_prompt_core(value)
    with pytest.raises(gate.H3PromptValidationError, match="UNSUPPORTED_CONTENT_TYPE"):
        gate.strip_h3_managed_layers(value, CONSTRAINT)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_json_numeric_constants_are_rejected_even_in_optional_fields(constant):
    value = json.dumps(_document())[:-1] + ', "extra": ' + constant + '}'
    with pytest.raises(gate.H3PromptValidationError, match="MALFORMED_DIRECTOR_JSON"):
        gate.validate_h3_prompt_core(value)


@pytest.mark.parametrize("field", (*REQUIRED_FIELDS[1:], *ANCHORS, "dialogue_timeline", "official_character_identity_lock"))
@pytest.mark.parametrize("value", [None, False, 17, [], {}])
def test_json_director_text_fields_do_not_coerce_other_types(field, value):
    document = _document()
    document[field] = value
    with pytest.raises(gate.H3PromptValidationError):
        gate.validate_h3_prompt_core(json.dumps(document))


@pytest.mark.parametrize("subjects", [None, [], False, 17, {"<Subject 1>": None}, {"<Subject 1>": []},
                                      {"<Subject 1>": {"description": "fox"}}, {"<Subject 1>": ""}, {"": "fox"}])
def test_invalid_subject_types_and_nested_fields_are_rejected_even_with_empty_permission(subjects):
    document = _document()
    document["subject_definitions"] = subjects
    with pytest.raises(gate.H3PromptValidationError, match="INVALID_DIRECTOR_SECTION"):
        gate.validate_h3_prompt_core(json.dumps(document), allow_empty_subjects=True)


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
@pytest.mark.parametrize("format_name", ["prose", "json"])
def test_missing_director_sections_are_rejected(field, format_name):
    document = _document()
    del document[field]
    value = _prose(document) if format_name == "prose" else json.dumps(document)
    with pytest.raises(gate.H3PromptValidationError, match="DIRECTOR_SECTIONS_MISSING"):
        gate.validate_h3_prompt_core(value)


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
@pytest.mark.parametrize("body", ["", " \n\t", "`", "!!!"])
def test_empty_or_punctuation_only_required_bodies_are_rejected(field, body):
    document = _document()
    document[field] = body
    for value in (_prose(document), json.dumps(document)):
        with pytest.raises(gate.H3PromptValidationError, match="INVALID_DIRECTOR_SECTION"):
            gate.validate_h3_prompt_core(value)


@pytest.mark.parametrize("anchor_body", [None, "", " \n", "`"])
def test_missing_or_empty_visual_anchor_is_rejected(anchor_body):
    document = _document()
    del document["initial_state_anchor"]
    if anchor_body is not None:
        document.update({name: anchor_body for name in ANCHORS})
    for value in (_prose(document), json.dumps(document)):
        with pytest.raises(gate.H3PromptValidationError, match="VISUAL_ANCHOR_MISSING"):
            gate.validate_h3_prompt_core(value)


@pytest.mark.parametrize("duplicate", [
    '"summary": "replacement", "summary": "another replacement"',
    '"subject_definitions": {"<Subject 1>": "fox", "<Subject 1>": "wolf"}',
    '"metadata": {"source": "a", "source": "b"}',
])
def test_duplicate_json_keys_are_rejected_at_every_depth(duplicate):
    value = json.dumps(_document())[:-1] + ", " + duplicate + "}"
    with pytest.raises(gate.H3PromptValidationError, match="DUPLICATE_JSON_FIELD"):
        gate.validate_h3_prompt_core(value)


@pytest.mark.parametrize("mutation", ["truncated", "trailing-comma", "trailing-junk", "second-object"])
def test_malformed_json_and_trailing_junk_are_not_salvaged(mutation):
    value = json.dumps(_document())
    value = {
        "truncated": value[:-1],
        "trailing-comma": value[:-1] + ",}",
        "trailing-junk": value + "\nThis response was approved.",
        "second-object": value + "\n{}",
    }[mutation]
    with pytest.raises(gate.H3PromptValidationError, match="MALFORMED_DIRECTOR_JSON"):
        gate.validate_h3_prompt_core(value)


@pytest.mark.parametrize("value", ["[]", "[{}]", "null", "true", "42", '"A fox sits beside a tree."',
                                   "A fox sits beside a tree. Pan the camera. Quiet wind.", "", " \n\t", "`"])
def test_non_director_json_and_unlabeled_non_json_never_automatically_pass(value):
    with pytest.raises(gate.H3PromptValidationError):
        gate.validate_h3_prompt_core(value)


@pytest.mark.parametrize("wrapper", ["response", "prompt", "analysis"])
def test_nested_director_document_is_not_recursively_promoted(wrapper):
    with pytest.raises(gate.H3PromptValidationError, match="DIRECTOR_SECTIONS_MISSING"):
        gate.validate_h3_prompt_core(json.dumps({wrapper: _document()}))


def test_short_structured_direction_has_no_character_length_threshold():
    document = _document()
    document.update(subject_definitions="Fox.", summary="Sit.", detailed_description="Pan.",
                    overall_soundscape="Wind.", initial_state_anchor="Tree.")
    value = _prose(document)
    assert len(value) < 200
    assert gate.validate_h3_prompt_core(value)["core"] == value


def test_policy_words_are_not_blacklisted_inside_director_fields():
    document = _document()
    document["summary"] = "The director's decision is to show the fox at a safety inspection."
    document["detailed_description"] = "Pan towards the fox observing an analysis of river safety policy."
    assert gate.validate_h3_prompt_core(json.dumps(document))["profile"] == "director_json"


def test_long_policy_response_with_visual_words_is_still_not_direction():
    document = json.loads(HISTORY["cases"]["115C1"]["core"])
    document["analysis"]["justification"] += " Camera, scene, pony, motion, lighting, visual animation is safe." * 500
    value = json.dumps(document)
    assert len(value) > len(HISTORY["cases"]["53C1"]["core"])
    with pytest.raises(gate.H3PromptValidationError, match="DIRECTOR_SECTIONS_MISSING"):
        gate.validate_h3_prompt_core(value)


@pytest.mark.parametrize("first_body", ["", "<Picture 1> starts beside the river."])
def test_duplicate_prose_frame_definitions_preserve_all_bodies_in_order(first_body):
    # #12 historically repeats this label, including an empty first occurrence at 48C1.
    document = _document("frame_definitions")
    value = (
        f"frame_definitions:\n{first_body}\n\n"
        "official_character_identity_lock:\nKeep the same fox throughout.\n\n"
        + _prose(document)
    )
    result = gate.validate_h3_prompt_core(value)
    assert result["core"] == value
    assert result["core"].count("frame_definitions:") == 2
    assert result["core_hash"] == hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("tag", ["", "text", "json"])
@pytest.mark.parametrize("format_name", ["prose", "json"])
def test_complete_outer_fences_unwrap_without_changing_direction(tag, format_name):
    # Like 3C2, identity information can live in subject_definitions without a separate lock section.
    document = _document("keyframe_timeline")
    document["keyframe_timeline"] = "<Picture 1 (frame index 3)> starts beside the tree; <Picture 2> ends there."
    body = _prose(document) if format_name == "prose" else json.dumps(document)
    result = gate.validate_h3_prompt_core(f"```{tag}\n{body}\n```")
    assert result["profile"] == f"director_{format_name}"
    assert result["core"] == body


@pytest.mark.parametrize("prefix,suffix", [("```\n", ""), ("```text\n", "\n``"),
                                          ("```json\n", "```"), ("```python\n", "\n```"),
                                          ("```\n", "\n```\nextra text"), ("", "\n```")],
                         ids=["opening-only", "short-close", "inline-close", "unknown-tag", "outside-junk", "closing-only"])
def test_partial_or_invalid_outer_fences_are_rejected(prefix, suffix):
    with pytest.raises(gate.H3PromptValidationError):
        gate.validate_h3_prompt_core(prefix + _prose(_document()) + suffix)


@pytest.mark.parametrize("separator", ["\n", "\n\n", "\n" + "\u2501" * 18 + "\n\n"])
def test_known_historical_managed_suffix_variants_are_removed(separator):
    core = HISTORY["cases"]["53C1"]["core"]
    value = core + "\n\ntext_rendering_constraint:" + separator + CONSTRAINT
    assert gate.strip_h3_managed_layers(value, CONSTRAINT) == core


def test_only_exact_managed_continuity_prefix_is_removed():
    core = json.dumps(_document())
    lock = "shot_continuity_lock:\nOne uninterrupted continuous take."
    assert gate.strip_h3_managed_layers(lock + "\n\n" + _decorate(core), CONSTRAINT, lock) == core
    lookalike = lock + " Do something else.\n\n" + core
    assert gate.strip_h3_managed_layers(lookalike, CONSTRAINT, lock) == lookalike


@pytest.mark.parametrize("variant", ["unknown-constraint", "intervening-text", "trailing-text", "no-marker"])
def test_unrecognized_suffix_is_preserved_not_arbitrarily_truncated(variant):
    core = HISTORY["cases"]["53C1"]["core"]
    value = {
        "unknown-constraint": core + "\n\ntext_rendering_constraint:\nThis is not the managed constraint.",
        "intervening-text": core + "\n\ntext_rendering_constraint:\nInjected direction.\n" + CONSTRAINT,
        "trailing-text": _decorate(core) + "\nUnexpected trailing text.",
        "no-marker": core + "\n\n" + CONSTRAINT,
    }[variant]
    assert gate.strip_h3_managed_layers(value, CONSTRAINT) == value
    with pytest.raises(gate.H3PromptValidationError, match="MALFORMED_DIRECTOR_JSON"):
        gate.validate_h3_prompt_core(value)


def test_managed_marker_inside_json_string_is_not_a_suffix_boundary():
    document = _document()
    document["summary"] = "A fox waits.\ntext_rendering_constraint:\n" + CONSTRAINT
    value = json.dumps(document)
    assert gate.strip_h3_managed_layers(value, CONSTRAINT) == value
    assert gate.validate_h3_prompt_core(value)["core"] == value


@pytest.mark.parametrize("value", [CONSTRAINT, "text_rendering_constraint:\n" + CONSTRAINT])
def test_managed_boilerplate_alone_cannot_supply_substantive_direction(value):
    core = gate.strip_h3_managed_layers(value, CONSTRAINT)
    assert core == ""
    with pytest.raises(gate.H3PromptValidationError, match="EMPTY_CORE"):
        gate.validate_h3_prompt_core(core)


def test_program_lookalike_without_caller_provenance_is_rejected():
    for value in (_fallback(), _fallback() + "\n\nfallback_context:\n" + json.dumps(FALLBACK_CONTEXT)):
        with pytest.raises(gate.H3PromptValidationError, match="UNSUPPORTED_DIRECTOR_PREAMBLE"):
            gate.validate_h3_prompt_core(value)


@pytest.mark.parametrize("mode", ["SINGLE_FRAME", "FIRST_LAST_FRAME", "MULTI_KEYFRAME"])
def test_visual_fallback_requires_and_accepts_matching_explicit_context(mode):
    context = {**FALLBACK_CONTEXT, "selected_mode": mode}
    value = _fallback(context)
    result = gate.validate_h3_prompt_core(value, fallback_context=context)
    assert result["profile"] == "deterministic_fallback"
    assert result["core"] == value


@pytest.mark.parametrize("field,value", [("shot_index", 8), ("selected_mode", "MULTI_KEYFRAME"),
                                        ("start_time", 1.0), ("end_time", 5.0)])
def test_fallback_wrong_shot_mode_or_range_is_rejected(field, value):
    with pytest.raises(gate.H3PromptValidationError, match="FALLBACK_CONTEXT_MISMATCH"):
        gate.validate_h3_prompt_core(_fallback(), fallback_context={**FALLBACK_CONTEXT, field: value})


@pytest.mark.parametrize("section", ["shot_description", "audio_drive"])
def test_fallback_missing_required_section_is_rejected(section):
    value = _fallback().replace(section + ":", "unrecognized_section:")
    with pytest.raises(gate.H3PromptValidationError, match="FALLBACK_SECTIONS_MISSING"):
        gate.validate_h3_prompt_core(value, fallback_context=FALLBACK_CONTEXT)


@pytest.mark.parametrize("keyframes", ["", "Picture 1: t=0.000s clip time, role=START",
                                      "Picture 1: t=0.000s clip time, role=START, description="])
def test_fixed_fallback_headers_and_audio_routing_are_not_visual_direction(keyframes):
    with pytest.raises(gate.H3PromptValidationError, match="FALLBACK_VISUAL_DIRECTION_MISSING"):
        gate.validate_h3_prompt_core(_fallback(description="", keyframes=keyframes), fallback_context=FALLBACK_CONTEXT)


def test_trusted_fallback_can_take_visual_direction_from_keyframe_description():
    value = _fallback(description="", keyframes="Picture 1: t=0.000s clip time, role=START, description=A fox sits beside a tree.")
    assert gate.validate_h3_prompt_core(value, fallback_context=FALLBACK_CONTEXT)["profile"] == "deterministic_fallback"


def test_actual_53_none_interval_is_not_a_speech_contradiction(director_ai):
    case = HISTORY["cases"]["53C1"]
    audit = director_ai.audit_audiodrive_h3_prompt(
        _decorate(case["core"]), case["speaker_timeline"], case["subject_manifest"],
    )
    assert audit["passed"], audit["issues"]


@pytest.mark.parametrize("audio_drive_enabled", [False, True], ids=["structural-only", "with-real-audio-audit"])
def test_actual_53_preparation_remains_accepted(director_ai, audio_drive_enabled):
    case = HISTORY["cases"]["53C1"]
    result = director_ai.prepare_h3_prompt(
        _decorate(case["core"]), constraint=CONSTRAINT, continuity_lock="",
        subject_manifest=case["subject_manifest"], speaker_timeline=case["speaker_timeline"],
        audio_drive_enabled=audio_drive_enabled,
    )
    assert result["passed"] is True
    assert result["core_hash"] == case["core_sha256"]
    assert result["final_hash"] == case["final_sha256"]
    assert result["final_prompt"] == _decorate(case["core"])


@pytest.mark.parametrize("clause", [
    "NONE: no speech mouthing or lip-sync.",
    "NONE: no speaking or lip-sync.",
    "NONE: no speech mouthing nor lip-sync.",
    "NONE: without any speech mouthing or any lip-sync.",
    "NONE: <Subject 1> does not speak or lip-sync.",
    "NONE: no lip-sync or speech mouthing, only natural breathing.",
])
def test_coordinated_negated_speech_actions_remain_silent(director_ai, clause):
    audit = director_ai.audit_audiodrive_h3_prompt(
        _decorate(clause), [{"start_time": 0.0, "end_time": 4.0, "visible_speaker": "NONE"}],
        HISTORY["cases"]["53C1"]["subject_manifest"],
    )
    assert audit["passed"] is True, audit["issues"]
    assert audit["issues"] == []


@pytest.mark.parametrize("clause", [
    "NONE: no speech mouthing or lip-sync, but <Subject 1> speaks.",
    "NONE: no speech mouthing or the pony speaks.",
    "NONE: <Subject 1> performs speech mouthing.",
    "NONE: no speech mouthing or lip-sync, and <Subject 2> talks.",
    "NONE: <Subject 1> does not speak, but <Subject 2> performs speech mouthing.",
    "NONE: no speech mouthing or lip-sync while <Subject 2> mouth moves.",
    "NONE: no lip-sync or speech mouthing, but the pony speaks.",
    "NONE: <Subject 1> never lip-syncs, and <Subject 2> mouth opens.",
])
def test_negation_does_not_hide_other_affirmative_speech_actions(director_ai, clause):
    audit = director_ai.audit_audiodrive_h3_prompt(
        _decorate(clause), [{"start_time": 0.0, "end_time": 4.0, "visible_speaker": "NONE"}],
        HISTORY["cases"]["53C1"]["subject_manifest"],
    )
    assert audit["passed"] is False
    assert [issue["code"] for issue in audit["blocking_issues"]] == ["NONE_SEGMENT_LIPSYNC_CONTRADICTION"]


@pytest.mark.parametrize("clause", [
    "不说话", "没有说话", "不开口", "没有开口", "保持沉默", "不进行口型", "无台词",
    "不做任何说话口型", "不产生任何讲话口型", "不进行任何发声口型",
    "no visible character speaks", "no character speaks",
    "no visiblecharacter speaks", "nocharacter speaks", "No Visible Characters Speak",
    "no visible character speech or lip-sync",
    "台词：无", "对白：无台词", "exact_dialogue: NONE", 'dialogue: ""', '<Subject 1>: ""',
    # Exact offending clauses from before/S024, S048 and S059, respectively.
    "NONE for the entire clip. Therefore no visible character speaks, no lip-sync occurs, and all visible mouths remain naturally closed.",
    "NONE，两匹马都保持沉默、嘴唇闭合，不做任何说话口型",
    "NONE → no character speaks at any point.",
])
def test_local_speech_negations_do_not_activate(director_ai, clause):
    audit = director_ai.audit_audiodrive_h3_prompt(
        _decorate("NONE: " + clause),
        [{"start_time": 0, "end_time": 4, "visible_speaker": "NONE"}],
        HISTORY["cases"]["53C1"]["subject_manifest"],
    )
    assert audit["issues"] == []
    assert audit["passed"] is True


@pytest.mark.parametrize("negative", [
    "不说话", "没有说话", "不开口", "没有开口", "保持沉默", "不进行口型", "无台词",
    "no visible character speaks", "no character speaks",
])
@pytest.mark.parametrize("positive", [
    "他说道", "他开口说道", "他正在说话", "台词：“你好”", "台词：你好",
    'exact_dialogue: "Hello"', 'dialogue: "Hello"', 'dialogue: Hello', '<Subject 2>: "Hello"',
    "<Subject 2> says hello",
])
def test_negative_predicate_never_consumes_separate_speech(director_ai, negative, positive):
    for clause in (
        f"{negative}，但{positive}",
        f"{positive}，其他人{negative}",
        f"{negative} {positive}" if negative.isascii() else f"小马{negative}{positive}",
    ):
        audit = director_ai.audit_audiodrive_h3_prompt(
            _decorate("NONE: " + clause),
            [{"start_time": 0, "end_time": 4, "visible_speaker": "NONE"}],
            HISTORY["cases"]["53C1"]["subject_manifest"],
        )
        assert [issue["code"] for issue in audit["blocking_issues"]] == ["NONE_SEGMENT_LIPSYNC_CONTRADICTION"], clause


@pytest.mark.parametrize("clause", [
    "不走动而是说道", "无任何人阻止他说道", "不仅说道，还在说话",
    "no character stops <Subject 1> speaking",
    '不说话，但台词：“保持沉默，不说话”',
    'no character speaks, but exact_dialogue: "Do not speak"',
])
def test_unrelated_negators_and_spoken_negative_words_do_not_exempt_dialogue(director_ai, clause):
    audit = director_ai.audit_audiodrive_h3_prompt(
        _decorate("NONE: " + clause),
        [{"start_time": 0, "end_time": 4, "visible_speaker": "NONE"}],
        HISTORY["cases"]["53C1"]["subject_manifest"],
    )
    assert [issue["code"] for issue in audit["blocking_issues"]] == ["NONE_SEGMENT_LIPSYNC_CONTRADICTION"]


@pytest.mark.parametrize("format_name", ["prose", "json", "escaped-json"])
@pytest.mark.parametrize("contradiction", [False, True])
@pytest.mark.parametrize("continuity_lock", ["", "shot_continuity_lock:\nOne uninterrupted continuous take."])
def test_json_speech_audit_view_preserves_fields_and_prompt_bytes(director_ai, format_name, contradiction, continuity_lock):
    document = _document()
    document["dialogue_timeline"] = (
        "0s-2s visible_speaker=NONE: 不说话" + ("，但他说道" if contradiction else "")
        + "\n2s-4s visible_speaker=<Subject 1>: 正在说话。"
        + "\n4s-5s visible_speaker=NONE: no character speaks."
    )
    # A separate field must not be mistaken for continuation of a NONE clause.
    del document["overall_soundscape"]
    document["overall_soundscape"] = "Only <Subject 1> speaks during 2s-4s."
    core = _prose(document) if format_name == "prose" else json.dumps(document, ensure_ascii=format_name == "escaped-json")
    kwargs = dict(
        constraint=CONSTRAINT, continuity_lock=continuity_lock,
        subject_manifest=HISTORY["cases"]["53C1"]["subject_manifest"],
        speaker_timeline=[
            {"start_time": 0, "end_time": 2, "visible_speaker": "NONE"},
            {"start_time": 2, "end_time": 4, "visible_speaker": "<Subject 1>"},
            {"start_time": 4, "end_time": 5, "visible_speaker": "NONE"},
        ],
    )
    if contradiction:
        with pytest.raises(gate.H3PromptValidationError, match="AUDIODRIVE_AUDIT_FAILED"):
            director_ai.prepare_h3_prompt(core, **kwargs)
    else:
        result = director_ai.prepare_h3_prompt(core, **kwargs)
        final = (continuity_lock + "\n\n" if continuity_lock else "") + _decorate(core)
        assert result["core"] == core
        assert result["final_prompt"] == final
        assert result["core_hash"] == gate.prompt_digest(core)
        assert result["final_hash"] == gate.prompt_digest(final)
        assert result["audio_audit"]["passed"] is True


@pytest.mark.parametrize("field", ["summary", "detailed_description", "dialogue_timeline", "overall_soundscape"])
def test_json_speech_audit_keeps_affirmatives_in_every_director_text_field(director_ai, field):
    document = _document()
    document[field] = "NONE: 不说话，但他说道"
    with pytest.raises(gate.H3PromptValidationError, match="NONE_SEGMENT_LIPSYNC_CONTRADICTION"):
        director_ai.prepare_h3_prompt(
            json.dumps(document), constraint=CONSTRAINT, continuity_lock="",
            subject_manifest=HISTORY["cases"]["53C1"]["subject_manifest"],
            speaker_timeline=[{"start_time": 0, "end_time": 4, "visible_speaker": "NONE"}],
        )


def test_negation_does_not_bypass_subject_checks_or_exact_dialogue_leakage(director_ai):
    audit = director_ai.audit_audiodrive_h3_prompt(
        _decorate('NONE: no character speaks. <Subject 9> says "Hello".'),
        [{"start_time": 0, "end_time": 4, "visible_speaker": "<Subject 2>"}],
        HISTORY["cases"]["53C1"]["subject_manifest"], dialogue_texts=["Hello"],
    )
    assert {issue["code"] for issue in audit["blocking_issues"]} == {
        "UNKNOWN_SUBJECT_REFERENCE", "MISSING_SUBJECT_REFERENCE_IN_PROMPT",
        "NONE_SEGMENT_LIPSYNC_CONTRADICTION", "DIALOGUE_TEXT_LEAKAGE",
    }


@pytest.mark.parametrize("body", [None, False, 17, [], {}])
def test_json_audit_view_does_not_bypass_dialogue_field_types(director_ai, body):
    document = _document()
    document["dialogue_timeline"] = body
    with pytest.raises(gate.H3PromptValidationError, match="INVALID_DIRECTOR_SECTION"):
        director_ai.prepare_h3_prompt(
            json.dumps(document), constraint=CONSTRAINT, continuity_lock="",
            subject_manifest=HISTORY["cases"]["53C1"]["subject_manifest"],
            speaker_timeline=[{"start_time": 0, "end_time": 4, "visible_speaker": "NONE"}],
        )


@pytest.mark.parametrize("shot_number", [24, 48, 59])
def test_frozen_speaker_negation_snapshot_keeps_exact_prompt(director_ai, shot_number):
    directory = os.environ.get("H3_NEGATION_SNAPSHOT_DIR")
    if not directory:
        pytest.skip("Set H3_NEGATION_SNAPSHOT_DIR for read-only frozen benchmark replay")
    shot = json.loads((Path(directory) / f"S{shot_number:03d}-shot.json").read_text(encoding="utf-8"))
    plan = shot["video_director_plan"]
    clip = plan["clips"][0]
    manifest = director_ai.build_clip_subject_manifest(SimpleNamespace(characters=shot["characters"]), [])
    timeline, issues = director_ai.resolve_speaker_timeline_for_h3(plan["window_plans"][0]["speaker_timeline"], manifest, clip)
    assert issues == []
    if shot_number == 48:
        assert [(item["start_time"], item["end_time"], item["visible_speaker"]) for item in timeline] == [
            (0.0, 10.271, "NONE"), (10.271, 12.888, "<Subject 2>"), (12.888, 13.488, "NONE"),
        ]
    result = director_ai.prepare_h3_prompt(
        clip["prompt_text"], constraint=CONSTRAINT, continuity_lock="",
        subject_manifest=manifest, speaker_timeline=timeline,
    )
    assert result["audio_audit"]["passed"] is True
    assert result["final_prompt"] == clip["prompt_text"]
    assert result["final_hash"] == gate.prompt_digest(clip["prompt_text"])
