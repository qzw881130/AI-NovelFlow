"""Isolated P0 tests: --noconftest, synthetic bytes/facts, no application startup."""

import asyncio
import builtins
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import sys
from types import ModuleType

import pytest
from pydantic import ValidationError


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_core():
    backend = Path(__file__).resolve().parents[1]
    with pytest.MonkeyPatch.context() as patch:
        for name in ("app", "app.schemas"):
            package = ModuleType(name)
            package.__path__ = []
            patch.setitem(sys.modules, name, package)
        schema = _load("_isolated_visual_state_types", backend / "app/schemas/visual_state.py")
        patch.setitem(sys.modules, "app.schemas.visual_state", schema)
        validator = _load("_isolated_visual_state_validator", backend / "app/services/visual_state_validator.py")
    return schema, validator


schema, gate = _load_core()


def _forbidden(*args, **kwargs):
    raise AssertionError("File, network, and database I/O are forbidden")


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(sqlite3, "connect", _forbidden)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", _forbidden)
    monkeypatch.setattr(builtins, "open", _forbidden)
    monkeypatch.setattr(Path, "open", _forbidden)
    monkeypatch.setattr(Path, "mkdir", _forbidden)


@pytest.fixture
def reference():
    return gate.VisualReference(1, 0, b"synthetic-shot-reference", "memory://reference", "START", 0)


def requirement(predicate="character_location", subject="fox", value="tree", **kwargs):
    return {"predicate": predicate, "subject": subject, "value": value, "source": "approved:shot-35", **kwargs}


def fact(predicate="character_location", subject="fox", value="tree", **kwargs):
    return {"predicate": predicate, "subject": subject, "value": value, "state": "PRESENT",
            "confidence": "HIGH", "evidence": "Dominant occupied region is visible.", **kwargs}


def plan(*requirements, invariants=(), clip_index=1, reference_index=0):
    return {"enabled": True, "anchors": [{"clip_index": clip_index, "reference_index": reference_index,
                                         "requirements": list(requirements)}], "invariants": list(invariants)}


def observation(reference, *facts, **kwargs):
    return {"image_sha256": reference.sha256, "provider": "injected-test", "facts": list(facts), **kwargs}


class Observer:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def observe(self, reference, questions):
        self.calls.append((reference, questions))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result(reference, questions) if callable(self.result) else self.result


def validate(request, references, **kwargs):
    return asyncio.run(gate.validate_references(request, references, **kwargs))


@pytest.mark.parametrize("actual,decision,reason", [
    ("rock", "BLOCK", "WRONG_START_STATE"), ("tree", "PASS", "STATE_MATCH"),
])
def test_shot35_planned_tree_uses_actual_dominant_region(reference, actual, decision, reason):
    requested = requirement()
    observed = fact(value=actual)
    observer = Observer(observation(reference, observed))
    result = validate(plan(requested), [reference], observer=observer)
    assert result["decision"] == decision
    finding = result["findings"][0]
    assert finding["reason"] == reason
    assert finding["raw_decision"] == decision
    assert finding["capability"] == "coarse_character_location"
    assert finding["may_confirm"] is True and finding["may_block"] is True
    assert finding["expected"]["value"] == "tree"
    assert finding["observed"][0]["value"] == actual
    assert finding["image_sha256"] == hashlib.sha256(reference.payload).hexdigest()
    assert finding["conflicting_fields"] == (["character_location"] if decision == "BLOCK" else [])
    assert finding["recommended_next_action"] == ("EDIT_IMAGE" if decision == "BLOCK" else None)
    assert [question.model_dump() for question in observer.calls[0][1]] == [
        {"predicate": "character_location", "subject": "fox", "value": "tree"}]
    assert result["scope"]["unknown_is_blocking"] is False
    assert result["capability_policy"] == schema.CAPABILITY_POLICY_VERSION == gate.CAPABILITY_POLICY_VERSION == "coarse_v1"
    assert "payload" not in result["references"][0]
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize("predicate,subject,value,actual,reason", [
    ("contact_relation", "fox", "shallow_water", "ABSENT", "CONTACT_STATE_CONFLICT"),
    ("environment_relation", "shallow_water", "connected_to:river_main", "ABSENT", "ENVIRONMENT_STATE_CONFLICT"),
    ("surface_state", "fox", "wet", "dry", "STATE_CONFLICT"),
])
def test_shot116_explicit_wrong_water_state_is_advisory(reference, predicate, subject, value, actual, reason):
    required = requirement(predicate, subject, value, source="approved:shot-116")
    observed = fact(predicate, subject, actual if predicate == "surface_state" else value,
                    state="PRESENT" if predicate == "surface_state" else actual)
    result = validate(plan(required), [reference], observer=Observer(observation(reference, observed)))
    assert result["decision"] == "WARN"
    finding = result["findings"][0]
    assert finding["reason"] == reason
    assert finding["raw_decision"] == "BLOCK"
    assert finding["capability"] == "advisory_only"
    assert finding["may_confirm"] is False and finding["may_block"] is False


def test_shot116_matching_fine_states_cannot_confirm_facts(reference):
    values = [("contact_relation", "fox", "shallow_water"),
              ("environment_relation", "shallow_water", "connected_to:river_main"),
              ("surface_state", "fox", "wet")]
    observer = Observer(observation(reference, *(fact(*value) for value in values)))
    result = validate(plan(*(requirement(*value) for value in values)), [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert len(result["findings"]) == 3
    assert all(item["raw_decision"] == "PASS" and not item["may_confirm"] and not item["may_block"]
               for item in result["findings"])


@pytest.mark.parametrize("predicate", ["contact_relation", "environment_relation"])
def test_relations_are_not_exclusive(reference, predicate):
    observer = Observer(observation(reference, fact(predicate, "fox", "bank")))
    result = validate(plan(requirement(predicate, "fox", "river")), [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "MISSING_FACT"
    forbidden_bank = requirement(predicate, "fox", "bank", expected="ABSENT")
    assert validate(plan(forbidden_bank), [reference], observer=observer)["decision"] == "WARN"
    both = plan(requirement(predicate, "fox", "river"), requirement(predicate, "fox", "bank"))
    observer.result = observation(reference, fact(predicate, "fox", "bank"), fact(predicate, "fox", "river"))
    assert validate(both, [reference], observer=observer)["decision"] == "UNKNOWN"


@pytest.mark.parametrize("state,decision,reason", [
    ("ABSENT", "BLOCK", "PROTECTED_PROP_MISSING"),
    ("OCCLUDED", "UNKNOWN", "INSUFFICIENT_EVIDENCE"),
    ("UNKNOWN", "UNKNOWN", "INSUFFICIENT_EVIDENCE"),
    ("PRESENT", "PASS", "STATE_MATCH"),
])
def test_shot85_protected_bag(reference, state, decision, reason):
    required = requirement("prop_present", "bag", "", protected=True, source="approved:shot-85")
    observer = Observer(observation(reference, fact("prop_present", "bag", "", state=state)))
    result = validate(plan(required), [reference], observer=observer)
    assert result["decision"] == decision
    assert result["findings"][0]["reason"] == reason
    assert result["findings"][0]["raw_decision"] == decision
    assert result["findings"][0]["capability"] == "protected_prop_presence"


def test_observer_timeout_preserves_earlier_clear_conflict(reference, monkeypatch):
    other = replace(reference, clip_index=2, payload=b"second-reference")
    calls = []

    class SlowObserver:
        async def observe(self, image, questions):
            calls.append(image.clip_index)
            if image.clip_index == 1:
                return observation(image, fact(value="rock"))
            await asyncio.Event().wait()

    monkeypatch.setattr(gate, "OBSERVATION_TIMEOUT_SECONDS", 0.01)
    result = validate({"enabled": True, "invariants": [requirement()]}, [reference, other], observer=SlowObserver())
    assert calls == [1, 2]
    assert result["decision"] == "BLOCK"
    assert [item["reason"] for item in result["findings"]] == ["WRONG_START_STATE", "OBSERVER_TIMEOUT"]


@pytest.mark.parametrize("uncertain", ["OCCLUDED", "UNKNOWN"])
def test_absence_mixed_with_uncertainty_cannot_block_protected_prop(reference, uncertain):
    required = requirement("prop_present", "grain_sack", "", protected=True, source="approved:shot-85")
    result = validate(plan(required), [reference], observer=Observer(observation(
        reference, fact("prop_present", "grain_sack", "", state="ABSENT"),
        fact("prop_present", "grain_sack", "", state=uncertain, confidence="LOW"),
    )))
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "CONTRADICTORY_OBSERVATIONS"


def test_duplicate_anchor_cannot_remove_invariant_known_unknown(reference):
    invariant = requirement("prop_present", "grain_sack", "", protected=True, known_unknown=True)
    duplicate = requirement("prop_present", "grain_sack", "", protected=True)
    result = validate(plan(duplicate, invariants=[invariant]), [reference], observer=Observer(observation(
        reference, fact("prop_present", "grain_sack", "", state="ABSENT"))))
    assert result["decision"] == "UNKNOWN"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["expected"]["known_unknown"] is True
    assert result["findings"][0]["may_block"] is False


def test_invalid_model_response_is_preserved_before_contract_validation(reference):
    raw = {"facts": [{"subject": "raw observation", "state": "unsupported"}], "decision": "PASS"}
    result = validate(plan(requirement()), [reference], observer=Observer(raw))
    assert result["decision"] == "UNKNOWN" and result["observations"] == []
    assert result["raw_observations"] == [{"image_sha256": reference.sha256, "response": raw}]
    raw["facts"].clear()
    assert result["raw_observations"][0]["response"]["facts"]


@pytest.mark.parametrize("values,decision", [
    ([("character_location", "fox", "tree")], "PASS"),
    ([("environment_relation", "shallow_water", "connected_to:river_main")], "UNKNOWN"),
])
def test_no_props_or_characters_or_speaker_are_invented(reference, values, decision):
    observer = Observer(observation(reference, *(fact(*value) for value in values)))
    request = plan(*(requirement(*value, source="approved:visible_speaker=NONE;narration") for value in values))
    result = validate(request, [reference], observer=observer)
    assert result["decision"] == decision
    assert {q.predicate for q in observer.calls[0][1]} == {value[0] for value in values}
    assert len(result["findings"]) == len(values)


@pytest.mark.parametrize("changes", [{"confidence": "LOW"}, {"confidence": "MEDIUM"},
                                      {"evidence": ""}, {"evidence": " \n "}, {"state": "OCCLUDED"}, {"state": "UNKNOWN"}])
def test_uncertain_evidence_never_blocks(reference, changes):
    observer = Observer(observation(reference, fact(value="rock", **changes)))
    result = validate(plan(requirement()), [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"


def test_missing_confidence_defaults_low_and_missing_fact_is_not_absence(reference):
    weak_fact = fact(value="rock")
    del weak_fact["confidence"]
    observer = Observer(observation(reference, weak_fact))
    assert validate(plan(requirement()), [reference], observer=observer)["decision"] == "UNKNOWN"
    observer.result = observation(reference)
    result = validate(plan(requirement(expected="ABSENT")), [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "MISSING_FACT"


@pytest.mark.parametrize("predicate,subject,value,other,reason", [
    ("character_state", "fox", "standing", "seated", "STATE_CONFLICT"),
    ("facing_direction", "fox", "left", "right", "WRONG_ACTION_DIRECTION"),
    ("prop_owner", "bag", "fox", "wolf", "STATE_CONFLICT"),
    ("surface_state", "fox", "wet", "dry", "STATE_CONFLICT"),
])
def test_advisory_exclusive_fields_retain_raw_conflicts(reference, predicate, subject, value, other, reason):
    observer = Observer(observation(reference, fact(predicate, subject, other)))
    result = validate(plan(requirement(predicate, subject, value)), [reference], observer=observer)
    assert result["decision"] == "WARN"
    finding = result["findings"][0]
    assert finding["reason"] == reason and finding["raw_decision"] == "BLOCK"
    assert finding["may_confirm"] is False and finding["may_block"] is False


def test_required_character_and_forbidden_presence(reference):
    observer = Observer(observation(reference, fact("character_present", "fox", "", state="ABSENT")))
    result = validate(plan(requirement("character_present", "fox", "")), [reference], observer=observer)
    assert result["decision"] == "BLOCK"
    assert result["findings"][0]["reason"] == "REQUIRED_CHARACTER_MISSING"
    observer.result = observation(reference, fact("character_present", "fox", ""))
    result = validate(plan(requirement("character_present", "fox", "", expected="ABSENT")), [reference], observer=observer)
    assert result["decision"] == "BLOCK"
    assert result["findings"][0]["reason"] == "STATE_CONFLICT"


def test_non_start_location_has_generic_conflict_and_noncritical_warns(reference):
    reference = replace(reference, role="END")
    observer = Observer(observation(reference, fact(value="rock")))
    result = validate(plan(requirement(critical=False)), [reference], observer=observer)
    assert result["decision"] == "WARN"
    assert result["findings"][0]["reason"] == "STATE_CONFLICT"


@pytest.mark.parametrize("facts", [
    [fact(), fact(value="rock")], [fact(), fact(state="ABSENT")],
    [fact(value="rock"), fact(confidence="LOW")],
])
def test_conflicting_observation_facts_are_unknown_even_with_clear_extra_values(reference, facts):
    result = validate(plan(requirement()), [reference], observer=Observer(observation(reference, *facts)))
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "CONTRADICTORY_OBSERVATIONS"


@pytest.mark.parametrize("critical,include_unknown,expected", [(True, True, "BLOCK"), (False, True, "UNKNOWN"),
                                                             (False, False, "WARN")])
def test_aggregate_precedence(reference, critical, include_unknown, expected):
    requirements = [requirement(critical=critical), requirement("character_present", "fox", "")]
    if include_unknown:
        requirements.append(requirement("character_present", "wolf", ""))
    observer = Observer(observation(reference, fact(value="rock"), fact("character_present", "fox", "")))
    result = validate(plan(*requirements), [reference], observer=observer)
    assert result["decision"] == expected


@pytest.mark.parametrize("changes", [
    {"enabled": "true"}, {"enabled": 1}, {"observations": []}, {"decision": "PASS"},
    {"known_observations": []}, {"anchors": ()}, {"invariants": None},
    {"capability_policy": "unrestricted"}, {"capability_policy": None}, {"capability_policy": 1},
])
def test_invalid_request_never_calls_observer(reference, changes):
    observer = Observer(_forbidden)
    result = validate({**plan(requirement()), **changes}, [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "INVALID_CONTRACT"
    assert observer.calls == []


@pytest.mark.parametrize("changes", [
    {"critical": "false"}, {"protected": 1}, {"subject": " "}, {"source": " "}, {"source": None},
    {"value": ""}, {"value": [0, 1, 2, 3]}, {"expected": "UNKNOWN"}, {"expected": "present"},
    {"state": "PRESENT"}, {"confidence": "HIGH"}, {"protected": True}, {"predicate": "speaker_present"},
    {"predicate": "character_state", "value": "blinking"},
    {"predicate": "character_state", "value": "microexpression"},
    {"predicate": "surface_state", "value": "microtexture"},
    {"predicate": "facing_direction", "value": "north"},
    {"known_unknown": "false"}, {"known_unknown": 1}, {"known_unknown": None},
    {"may_confirm": True}, {"may_block": True}, {"capability": "coarse_character_location"},
])
def test_requirement_contract_rejects_unsupported_or_coerced_fields(reference, changes):
    observer = Observer(_forbidden)
    result = validate(plan(requirement(**changes)), [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "INVALID_CONTRACT"
    assert observer.calls == []


def test_presence_source_protection_and_default_contracts():
    required = schema.StateRequirement(predicate="prop_present", subject="bag", source="approved", protected=True)
    assert required.value == "" and required.expected == "PRESENT" and required.critical is True
    assert required.known_unknown is False
    assert schema.VisualStateValidation().model_dump() == {
        "enabled": False, "capability_policy": "coarse_v1", "anchors": [], "invariants": [],
    }
    for updates in ({"critical": False}, {"expected": "ABSENT"}, {"value": "bag"}, {"source": None}):
        with pytest.raises(ValidationError):
            schema.StateRequirement.model_validate({**required.model_dump(), **updates})
    missing_source = required.model_dump()
    del missing_source["source"]
    with pytest.raises(ValidationError):
        schema.StateRequirement.model_validate(missing_source)
    assert schema.StateRequirement(**requirement("prop_owner", "bag", "fox", protected=True)).protected
    first, second = schema.VisualStateValidation(), schema.VisualStateValidation()
    first.invariants.append(required)
    assert second.invariants == []


@pytest.mark.parametrize("predicate,value", [("prop_present", ""), ("prop_owner", "fox")])
def test_protected_absence_cannot_define_canon_but_ordinary_forbidden_props_are_valid(reference, predicate, value):
    required = requirement(predicate, "bag", value, expected="ABSENT", protected=True)
    absent = observation(reference, fact(predicate, "bag", value, state="ABSENT"))
    observer = Observer(_forbidden)
    for requested in (plan(required), plan(invariants=[required])):
        result = validate(requested, [reference], observer=observer, known_observations=[absent])
        assert result["decision"] == "UNKNOWN"
        assert result["findings"][0]["reason"] == "INVALID_CONTRACT"
        assert result["scope"]["unknown_is_blocking"] is False
    assert observer.calls == []
    forbidden = plan(invariants=[{**required, "protected": False}])
    matched = validate(forbidden, [reference], known_observations=[absent])
    assert matched["decision"] == "UNKNOWN"
    assert matched["findings"][0]["raw_decision"] == "PASS"
    assert matched["findings"][0]["may_confirm"] is False
    present = observation(reference, fact(predicate, "bag", value))
    result = validate(forbidden, [reference], known_observations=[present])
    assert result["decision"] == "WARN"
    assert result["findings"][0]["reason"] == "STATE_CONFLICT"
    assert result["findings"][0]["may_block"] is False


@pytest.mark.parametrize("field,limit", [("subject", 128), ("value", 128), ("source", 512)])
def test_requirement_string_limits_accept_boundary_and_reject_excess_before_observing(reference, field, limit):
    bounded = requirement(**{field: "x" * limit})
    assert getattr(schema.StateRequirement.model_validate(bounded), field) == "x" * limit
    observer = Observer(_forbidden)
    result = validate(plan({**bounded, field: "x" * (limit + 1)}), [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "INVALID_CONTRACT"
    assert observer.calls == []


@pytest.mark.parametrize("field", ["anchors", "requirements", "invariants"])
def test_requirement_collection_limits_accept_64_and_reject_65_before_observing(reference, field):
    requested = plan()
    if field == "anchors":
        requested[field] = [{"clip_index": index + 1, "reference_index": 0,
                             "requirements": [requirement()]} for index in range(64)]
        items = requested[field]
    elif field == "requirements":
        items = requested["anchors"][0][field] = [requirement() for _ in range(64)]
    else:
        items = requested[field] = [requirement() for _ in range(64)]
    schema.VisualStateValidation.model_validate(requested)
    items.append(deepcopy(items[0]))
    with pytest.raises(ValidationError) as exc:
        schema.VisualStateValidation.model_validate(requested)
    assert exc.value.errors()[0]["type"] == "too_long"
    observer = Observer(_forbidden)
    result = validate(requested, [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "INVALID_CONTRACT"
    assert observer.calls == []


@pytest.mark.parametrize("field", ["subject", "value", "provider"])
def test_observation_string_limits_accept_128_and_reject_129(reference, field):
    raw = observation(reference, fact())
    target = raw if field == "provider" else raw["facts"][0]
    target[field] = "x" * 128
    schema.ImageObservation.model_validate(raw)
    target[field] = "x" * 129
    observer = Observer(raw)
    result = validate(plan(requirement()), [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "INVALID_OBSERVATION"
    assert len(observer.calls) == 1


@pytest.mark.parametrize("clip_index,reference_index", [(0, 0), (1, -1), (True, 0), (1, False), ("1", 0)])
def test_anchor_addresses_are_strict(reference, clip_index, reference_index):
    result = validate(plan(requirement(), clip_index=clip_index, reference_index=reference_index), [reference])
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "INVALID_CONTRACT"


def test_reference_addresses_targets_and_all_contracts_checked_before_observer(reference):
    observer = Observer(_forbidden)
    first = plan(requirement())
    cases = [(first, [reference, reference]), (plan(requirement(), reference_index=1), [reference]),
             ({**first, "anchors": first["anchors"] * 2}, [reference]),
             (first, [replace(reference, clip_index=True)]), (first, [replace(reference, payload=b"")])]
    later = replace(reference, clip_index=2, reference_index=1)
    conflict = plan(requirement())
    conflict["anchors"].append({"clip_index": 2, "reference_index": 1,
                                "requirements": [requirement(), requirement(expected="ABSENT")]})
    cases.append((conflict, [reference, later]))
    cases.append((plan(requirement(), invariants=[requirement(value="rock")]), [reference]))
    for request, references in cases:
        result = validate(request, references, observer=observer)
        assert result["decision"] == "UNKNOWN"
        assert result["findings"][0]["reason"] == "INVALID_CONTRACT"
    assert observer.calls == []


def test_actual_ordered_extra_index_not_keyframe_index(reference):
    extra = replace(reference, reference_index=1, keyframe_index=35, role="END")
    result = validate(plan(requirement(), reference_index=1), [extra],
                      observer=Observer(observation(extra, fact())))
    assert result["decision"] == "PASS"
    assert result["references"][0]["reference_index"] == 1
    assert result["references"][0]["keyframe_index"] == 35
    assert validate(plan(requirement(), reference_index=35), [extra])["decision"] == "UNKNOWN"


@pytest.mark.parametrize("mode", ["dict", "model"])
def test_validated_model_or_dict_and_snapshots_never_change(reference, mode):
    request = plan(invariants=[requirement()])
    if mode == "model":
        request = schema.VisualStateValidation.model_validate(request)
    before = deepcopy(request)
    known = schema.ImageObservation.model_validate(observation(reference, fact()))
    known_before = known.model_dump()
    first = validate(request, [reference], known_observations=[known])
    first_snapshot = deepcopy(first)
    second = validate(request, [reference], observer=Observer(observation(reference, fact(value="rock"))))
    assert first["decision"] == "PASS" and second["decision"] == "BLOCK"
    assert first["capability_policy"] == second["capability_policy"] == "coarse_v1"
    assert request == before
    assert known.model_dump() == known_before
    assert first == first_snapshot
    with pytest.raises(FrozenInstanceError):
        reference.payload = b"replacement"


def test_constructed_models_cannot_bypass_strict_validation(reference):
    bad = schema.VisualStateValidation.model_construct(enabled="true")
    observer = Observer(_forbidden)
    assert validate(bad, [reference], observer=observer)["decision"] == "UNKNOWN"
    bad_requirement = schema.StateRequirement.model_construct(**requirement(critical="false"))
    nested = schema.VisualStateValidation.model_construct(enabled=True, invariants=[bad_requirement], anchors=[])
    assert validate(nested, [reference], observer=observer)["decision"] == "UNKNOWN"
    assert observer.calls == []
    raw = schema.ImageObservation.model_construct(image_sha256=reference.sha256, facts=[{"decision": "PASS"}])
    result = validate(plan(requirement()), [reference], observer=Observer(raw))
    assert result["decision"] == "UNKNOWN"


@pytest.mark.parametrize("kind,reason", [("error", "OBSERVER_ERROR"), ("decision", "INVALID_OBSERVATION"),
                                       ("fact_decision", "INVALID_OBSERVATION"), ("hash", "OBSERVATION_HASH_MISMATCH"),
                                       ("wrong_type", "INVALID_OBSERVATION"), ("missing_facts", "MISSING_FACT"),
                                       ("microtexture", "INVALID_OBSERVATION")])
def test_provider_failures_are_unknown_without_retry(reference, kind, reason):
    raw = observation(reference, fact(value="rock"))
    if kind == "error":
        raw = RuntimeError("observer failed")
    elif kind == "decision":
        raw["decision"] = "BLOCK"
    elif kind == "fact_decision":
        raw["facts"][0]["decision"] = "PASS"
    elif kind == "hash":
        raw["image_sha256"] = "0" * 64
    elif kind == "wrong_type":
        raw = None
    elif kind == "missing_facts":
        del raw["facts"]
    elif kind == "microtexture":
        raw["facts"] = [fact("surface_state", "fox", "microtexture")]
    observer = Observer(raw)
    result = validate(plan(requirement()), [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == reason
    assert len(observer.calls) == 1
    if kind != "missing_facts":
        assert result["observations"] == []


@pytest.mark.parametrize("changes", [
    {"image_sha256": "A" * 64}, {"image_sha256": "a" * 63}, {"image_sha256": b"a" * 64},
    {"image_sha256": "a" * 64 + "\n"}, {"version": True}, {"version": 1.0}, {"version": "1"},
    {"version": 2}, {"facts": [fact()] * 257}, {"facts": (fact(),)}, {"provider": 1},
    {"facts": [fact(state="visible")]}, {"facts": [fact(confidence="high")]},
    {"facts": [fact(evidence="x" * 513)]}, {"facts": [fact(expected="PRESENT")]},
    {"facts": [fact(known_unknown=False)]}, {"facts": [fact(may_confirm=True)]},
    {"capability_policy": "coarse_v1"},
])
def test_observation_contract_is_strict_and_bounded(reference, changes):
    observer = Observer({**observation(reference, fact()), **changes})
    result = validate(plan(requirement()), [reference], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "INVALID_OBSERVATION"


@pytest.mark.parametrize("exception", [asyncio.CancelledError(), BaseException("stop")])
def test_cancellation_and_baseexception_propagate(reference, exception):
    with pytest.raises(type(exception)):
        validate(plan(requirement()), [reference], observer=Observer(exception))


def test_known_hash_bound_facts_avoid_provider_and_do_not_accept_other_images(reference):
    observer = Observer(_forbidden)
    known = observation(reference, fact())
    snapshot = deepcopy(known)
    assert validate(plan(requirement()), [reference], observer=observer, known_observations=[known])["decision"] == "PASS"
    assert observer.calls == []
    assert known == snapshot
    wrong = {**known, "image_sha256": "0" * 64}
    result = validate(plan(requirement()), [reference], known_observations=[wrong])
    assert result["decision"] == "UNKNOWN"
    assert result["observations"] == []
    assert result["findings"][0]["reason"] == "OBSERVER_NOT_CONFIGURED"
    result = validate(plan(requirement()), [reference], observer=observer, known_observations=[observation(reference)])
    assert result["decision"] == "UNKNOWN"
    assert observer.calls == []


def test_known_observation_conflicts_and_malformed_values_do_not_fall_back(reference):
    observer = Observer(_forbidden)
    known = [observation(reference, fact()), observation(reference, fact(value="rock"))]
    result = validate(plan(requirement()), [reference], observer=observer, known_observations=known)
    assert result["findings"][0]["reason"] == "CONTRADICTORY_OBSERVATIONS"
    assert result["decision"] == "UNKNOWN"
    result = validate(plan(requirement()), [reference], observer=observer, known_observations=[{"decision": "PASS"}])
    assert result["findings"][0]["reason"] == "INVALID_OBSERVATION"
    assert observer.calls == []


@pytest.mark.parametrize("error", [False, True])
def test_same_hash_questions_dedup_across_anchors_ignores_expected_flags_and_source(reference, error):
    later = replace(reference, clip_index=2, reference_index=1, role="END")
    request = plan(requirement())
    request["anchors"].append({"clip_index": 2, "reference_index": 1, "requirements": [
        requirement(expected="ABSENT", critical=False, source="approved:other-clip")]})
    observer = Observer(RuntimeError("fail") if error else observation(reference, fact()))
    result = validate(request, [reference, later], observer=observer)
    assert len(observer.calls) == 1
    assert result["decision"] == ("UNKNOWN" if error else "WARN")
    assert len(result["observations"]) == (0 if error else 1)
    assert len(result["references"]) == 2


def test_question_order_dedup_and_different_hashes_are_distinct(reference):
    later = replace(reference, clip_index=2)
    values = [("character_location", "fox", "tree"), ("character_present", "fox", "")]
    request = plan(*(requirement(*value) for value in values))
    request["anchors"].append({"clip_index": 2, "reference_index": 0,
                                "requirements": [requirement(*value) for value in reversed(values)]})
    observer = Observer(lambda ref, questions: observation(ref, *(fact(*value) for value in values)))
    assert validate(request, [reference, later], observer=observer)["decision"] == "PASS"
    assert len(observer.calls) == 1
    observer.calls.clear()
    assert validate(request, [reference, replace(later, payload=b"different-image")], observer=observer)["decision"] == "PASS"
    assert len(observer.calls) == 2


def test_different_questions_same_image_merge_conflicting_answers_before_deciding(reference):
    later = replace(reference, clip_index=2)
    request = plan(requirement())
    request["anchors"].append({"clip_index": 2, "reference_index": 0,
                                "requirements": [requirement(value="rock")]})
    observer = Observer(lambda ref, questions: observation(ref, fact(value=questions[0].value)))
    result = validate(request, [reference, later], observer=observer)
    assert len(observer.calls) == 2
    assert result["decision"] == "UNKNOWN"
    assert all(item["reason"] == "CONTRADICTORY_OBSERVATIONS" for item in result["findings"])


@pytest.mark.parametrize("requested,references,reason", [
    ({}, "selected", "DISABLED"), (plan(requirement()) | {"enabled": False}, "selected", "DISABLED"),
    ({"enabled": True}, "selected", "NOT_EVALUATED"), (plan(), "selected", "NOT_EVALUATED"),
    ({"enabled": True, "invariants": [requirement()]}, "empty", "NOT_EVALUATED"),
])
def test_disabled_or_unconstrained_never_calls_provider(reference, requested, references, reason):
    observer = Observer(_forbidden)
    result = validate(requested, [reference] if references == "selected" else [], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["enabled"] is requested.get("enabled", False)
    assert result["findings"][0]["reason"] == reason
    assert observer.calls == []


def test_configured_observer_factory_and_unconstrained_reference_not_certified(reference, monkeypatch):
    services = ModuleType("app.services")
    services.__path__ = []
    observer_module = ModuleType("app.services.visual_state_observer")
    configured = object()
    observer_module.get_configured_visual_state_observer = lambda: configured
    monkeypatch.setitem(sys.modules, "app.services", services)
    monkeypatch.setitem(sys.modules, "app.services.visual_state_observer", observer_module)
    assert gate.get_visual_state_observer() is configured
    observer_module.get_configured_visual_state_observer = lambda: None
    assert gate.get_visual_state_observer() is None
    result = validate(plan(requirement()), [reference])
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["reason"] == "OBSERVER_NOT_CONFIGURED"
    extra = replace(reference, reference_index=1)
    observer = Observer(observation(reference, fact()))
    result = validate(plan(requirement()), [reference, extra], observer=observer)
    assert result["decision"] == "UNKNOWN"
    assert result["references"][0]["decision"] == "PASS"
    assert result["references"][1]["decision"] == "UNKNOWN"
    assert len(observer.calls) == 1


@pytest.mark.parametrize("role", ["START", "END"])
@pytest.mark.parametrize("region", [
    "tree", "tree_support", "rock", "rock_top", "bank", "dry_bank", "river", "river_main", "forest", "farm", "gate",
])
def test_coarse_start_end_region_controls_can_confirm(reference, role, region):
    reference = replace(reference, role=role)
    result = validate(plan(requirement(value=region)), [reference],
                      known_observations=[observation(reference, fact(value=region))])
    assert result["decision"] == "PASS"
    assert result["findings"][0]["may_confirm"] is True


@pytest.mark.parametrize("value", [
    "tree.left_branch", "tree_support:paw_contact", "rock_top_left_paw", "dry_bank_front_paws_in_water",
    "river_main_near_left_foot", "left_paw", "tree_top", "farm/gate", "bank within 2cm of water",
])
@pytest.mark.parametrize("state,decision,raw_decision", [("PRESENT", "UNKNOWN", "PASS"), ("ABSENT", "WARN", "BLOCK")])
def test_fine_locations_remain_parseable_but_have_no_strong_authority(reference, value, state, decision, raw_decision):
    required = schema.StateRequirement(**requirement(value=value, critical=True))
    observed = schema.ObservationFact(**fact(value=value, state=state))
    finding = gate.evaluate_requirement(required, [observed], reference)
    assert finding["decision"] == decision and finding["raw_decision"] == raw_decision
    assert finding["capability"] == "advisory_only"
    assert finding["may_confirm"] is False and finding["may_block"] is False
    assert finding["observed"] == [observed.model_dump(mode="json")]


@pytest.mark.parametrize("expected", ["PRESENT", "ABSENT"])
def test_fine_alternate_location_cannot_prove_coarse_absence(reference, expected):
    result = validate(plan(requirement(expected=expected)), [reference], known_observations=[
        observation(reference, fact(value="rock_top_left_paw")),
    ])
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["raw_decision"] == "UNKNOWN"
    assert result["findings"][0]["observed"][0]["value"] == "rock_top_left_paw"


@pytest.mark.parametrize("subject", [
    "paw", "feet", "fox.paw", "fox_left_paw", "foxLeftPaw", "fox-front-paws", "fox/leg", "fox:tail",
    "fox's hand", "fox[head]", "\u72d0\u72f8\u524d\u722a", "\u722a\u5b50",
])
@pytest.mark.parametrize("predicate,value", [("character_location", "tree"), ("character_present", "")])
def test_known_body_part_and_attribute_subjects_are_advisory(reference, subject, predicate, value):
    required = schema.StateRequirement(**requirement(predicate, subject, value))
    assert gate.capability_for(required) == {
        "capability": "advisory_only", "may_confirm": False, "may_block": False,
    }
    for state, decision in (("PRESENT", "UNKNOWN"), ("ABSENT", "WARN")):
        finding = gate.evaluate_requirement(required, [schema.ObservationFact(**fact(predicate, subject, value, state=state))],
                                            reference)
        assert finding["decision"] == decision


@pytest.mark.parametrize("predicate,subject,value,protected", [
    ("contact_relation", "fox", "left_front_paw:touching:shallow_water_surface", False),
    ("environment_relation", "shallow_water", "connected_to:river_main", False),
    ("surface_state", "fox", "wet", False),
    ("facing_direction", "fox", "left", False),
    ("character_state", "fox", "standing", False),
    ("prop_present", "bag", "", False),
    ("prop_owner", "bag", "fox", False),
    ("prop_owner", "bag", "fox", True),
])
@pytest.mark.parametrize("state,decision,raw_decision", [
    ("PRESENT", "UNKNOWN", "PASS"), ("ABSENT", "WARN", "BLOCK"),
    ("OCCLUDED", "UNKNOWN", "UNKNOWN"), ("UNKNOWN", "UNKNOWN", "UNKNOWN"),
])
def test_advisory_fields_preserve_raw_states_even_when_critical_and_high(
    reference, predicate, subject, value, protected, state, decision, raw_decision,
):
    requested = plan(invariants=[requirement(predicate, subject, value, critical=True, protected=protected)])
    raw = observation(reference, fact(predicate, subject, value, state=state))
    before = deepcopy((requested, raw))
    observer = Observer(_forbidden)
    result = validate(requested, [reference], observer=observer, known_observations=[raw])
    finding = result["findings"][0]
    assert result["decision"] == finding["decision"] == decision
    assert finding["raw_decision"] == raw_decision
    assert finding["may_confirm"] is False and finding["may_block"] is False
    assert finding["observed"] == raw["facts"]
    assert result["observations"] == [{"version": 1, **raw}]
    assert (requested, raw) == before
    assert observer.calls == []


@pytest.mark.parametrize("evidence", [
    "The bag is hidden behind the actor.", "Occluded by the body.", "Absence inferred from occlusion.",
    "The bag is cropped out.", "The bag is NOT VISIBLE.", "Bag not-visible in this view.",
    "Cannot see the bag.", "Can't see it behind the tree.", "The bag is out of frame.",
    "\u80cc\u5305\u88ab\u906e\u6321\u3002", "\u80cc\u5305\u4e0d\u53ef\u89c1\u3002", "\u770b\u4e0d\u89c1\u80cc\u5305\u3002",
])
def test_high_absence_based_on_nonvisibility_stays_unknown_without_rewriting_canon(reference, evidence):
    requested = plan(invariants=[requirement("prop_present", "bag", "", protected=True, source="approved:shot-85")])
    raw = observation(reference, fact("prop_present", "bag", "", state="ABSENT", evidence=evidence))
    snapshot = deepcopy((requested, raw))
    result = validate(requested, [reference], known_observations=[raw])
    finding = result["findings"][0]
    assert result["decision"] == "UNKNOWN"
    assert finding["reason"] == "INSUFFICIENT_EVIDENCE"
    assert finding["expected"]["expected"] == "PRESENT" and finding["expected"]["protected"] is True
    assert finding["observed"] == raw["facts"]
    assert result["observations"] == [{"version": 1, **raw}]
    assert (requested, raw) == snapshot


@pytest.mark.parametrize("confidence", ["HIGH", "MEDIUM", "LOW"])
@pytest.mark.parametrize("expected", ["PRESENT", "ABSENT"])
def test_nonvisibility_cannot_confirm_absence_or_override_low_confidence(reference, confidence, expected):
    result = validate(plan(requirement("character_present", "fox", "", expected=expected)), [reference],
                      known_observations=[observation(reference, fact(
                          "character_present", "fox", "", state="ABSENT", confidence=confidence, evidence="Actor is hidden."))])
    assert result["decision"] == "UNKNOWN"


@pytest.mark.parametrize("changes", [
    {"state": "UNKNOWN"}, {"state": "OCCLUDED"}, {"state": "ABSENT", "confidence": "LOW"},
    {"state": "ABSENT", "evidence": ""}, {"state": "ABSENT", "evidence": "Region is cropped."},
])
def test_uncertain_target_is_not_converted_to_absence_by_an_alternate_location(reference, changes):
    result = validate(plan(requirement()), [reference], known_observations=[
        observation(reference, fact(**changes), fact(value="rock")),
    ])
    assert result["decision"] == "UNKNOWN"
    assert result["findings"][0]["observed"][0] == fact(**changes)


@pytest.mark.parametrize("predicate,value,protected", [
    ("surface_state", "wet", False), ("character_location", "tree", False),
    ("character_present", "", False), ("prop_present", "", True),
])
def test_typed_known_unknown_prevents_high_confirmation_without_changing_intent_or_questions(
    reference, predicate, value, protected,
):
    requested = schema.VisualStateValidation.model_validate(plan(requirement(
        predicate, "actor_or_prop", value, protected=protected, known_unknown=True, source="approved:uncertain-field")))
    before = requested.model_dump(mode="json")
    observer = Observer(observation(reference, fact(predicate, "actor_or_prop", value)))
    result = validate(requested, [reference], observer=observer)
    finding = result["findings"][0]
    assert result["decision"] == "UNKNOWN" and finding["raw_decision"] == "PASS"
    assert finding["may_confirm"] is False
    assert finding["expected"]["known_unknown"] is True
    assert finding["expected"]["expected"] == "PRESENT"
    assert [question.model_dump() for question in observer.calls[0][1]] == [
        {"predicate": predicate, "subject": "actor_or_prop", "value": value},
    ]
    assert requested.model_dump(mode="json") == before


def test_known_unknown_is_scoped_to_the_requirement_not_the_hash_or_observer(reference):
    later = replace(reference, clip_index=2)
    request = plan(requirement(known_unknown=True, source="approved:uncertain"))
    request["anchors"].append({"clip_index": 2, "reference_index": 0, "requirements": [requirement()]})
    observer = Observer(observation(reference, fact()))
    result = validate(request, [reference, later], observer=observer)
    assert len(observer.calls) == 1
    assert [item["decision"] for item in result["findings"]] == ["UNKNOWN", "PASS"]
    assert [item["may_confirm"] for item in result["findings"]] == [False, True]


def test_legacy_json_uses_current_policy_only_for_new_evaluation(reference):
    historical = {"request": plan(requirement("contact_relation", "fox", "river")),
                  "observation": observation(reference, fact("contact_relation", "fox", "river")),
                  "report": {"version": 1, "decision": "PASS", "findings": [{"decision": "PASS", "reason": "STATE_MATCH"}]}}
    encoded = json.dumps(historical, sort_keys=True)
    legacy = json.loads(encoded)
    normalized = schema.VisualStateValidation.model_validate(legacy["request"], strict=True)
    assert normalized.model_dump(mode="json")["capability_policy"] == "coarse_v1"
    assert normalized.anchors[0].requirements[0].known_unknown is False
    current = validate(legacy["request"], [reference], known_observations=[legacy["observation"]])
    assert current["capability_policy"] == "coarse_v1"
    assert current["decision"] == "UNKNOWN" and current["findings"][0]["raw_decision"] == "PASS"
    assert json.dumps(legacy, sort_keys=True) == encoded


@pytest.mark.parametrize("requested", [{}, {"enabled": True}, {"enabled": "true"}, plan(requirement())])
def test_unevaluated_reports_also_expose_current_policy_and_no_fact_confirmation(reference, requested):
    result = validate(requested, [reference])
    assert result["capability_policy"] == "coarse_v1"
    assert result["decision"] == "UNKNOWN"
    assert all(item["raw_decision"] == "UNKNOWN" and isinstance(item["may_confirm"], bool)
               and isinstance(item["may_block"], bool) and isinstance(item["capability"], str)
               for item in result["findings"])
