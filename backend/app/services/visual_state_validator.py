"""Pure P0 checks of explicit intent against injected, hash-bound observations."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Iterable, Protocol, Sequence

from pydantic import ValidationError

from app.schemas.visual_state import (
    CAPABILITY_POLICY_VERSION, ImageObservation, ObservationFact, ObservationQuestion, RecommendedNextAction,
    StateRequirement, VisualStateValidation,
)


_EXCLUSIVE = frozenset(("character_location", "character_state", "facing_direction", "prop_owner", "surface_state"))
# Exact dominant-region labels, not geometry, contact, or an action parser.
_COARSE_REGIONS = frozenset((
    "tree", "tree_support", "rock", "rock_top", "bank", "dry_bank", "river", "river_main", "forest", "farm", "gate",
))
# A bounded identifier guard, not a general actor/body-part NLP taxonomy.
_BODY_PART_ALIASES = frozenset((
    "body", "head", "face", "eye", "eyes", "ear", "ears", "nose", "mouth", "neck", "shoulder", "shoulders",
    "arm", "arms", "hand", "hands", "finger", "fingers", "leg", "legs", "foot", "feet", "toe", "toes",
    "paw", "paws", "forepaw", "forepaws", "hindpaw", "hindpaws", "foreleg", "forelegs", "hindleg", "hindlegs",
    "tail", "wing", "wings", "hoof", "hooves", "chest", "back", "belly", "fur",
))
_BODY_PART_SUFFIXES = ("\u722a", "\u722a\u5b50", "\u624b", "\u811a", "\u817f", "\u5c3e\u5df4", "\u5934\u90e8", "\u8eab\u4f53")
# These bounded negative flags only veto absence; their absence never proves visibility.
_ABSENCE_VISIBILITY_FLAGS = re.compile(
    r"\b(?:hidden|occluded|occlusion|cropped|cropping|not[\s_-]+visible|cannot[\s-]+see"
    r"|can[\s-]+not[\s-]+see|can't[\s-]+see|out[\s-]+of[\s-]+frame|off[\s-]*screen)\b"
    r"|\u906e\u6321|\u4e0d\u53ef\u89c1|\u770b\u4e0d\u89c1", re.IGNORECASE,
)
OBSERVATION_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class VisualReference:
    clip_index: int
    reference_index: int
    payload: bytes
    source_url: str
    role: str
    keyframe_index: int | None = None

    @property
    def sha256(self) -> str:
        return sha256(self.payload).hexdigest()


class VisualObservationProvider(Protocol):
    async def observe(self, reference: VisualReference, questions: tuple[ObservationQuestion, ...]) -> ImageObservation | dict:
        ...


def get_visual_state_observer() -> VisualObservationProvider | None:
    return None


def capability_for(requirement: StateRequirement) -> dict:
    """Return policy eligibility, not proof. A usable finding also needs PASS/BLOCK.

    Actor subjects must be identifiers without path/attribute punctuation or
    known body-part tokens (including snake/kebab/camel aliases). This bounded
    guard cannot certify that an arbitrary name denotes a whole actor.
    """
    tokens = re.split(r"[_-]+|(?<=[a-z])(?=[A-Z])", requirement.subject)
    coarse_actor = (re.fullmatch(r"\w+(?:-\w+)*", requirement.subject) is not None
                    and not _BODY_PART_ALIASES.intersection(token.lower() for token in tokens)
                    and not requirement.subject.endswith(_BODY_PART_SUFFIXES))
    capability = "advisory_only"
    if requirement.predicate == "character_present" and coarse_actor:
        capability = "coarse_character_presence"
    elif requirement.predicate == "prop_present" and requirement.protected:
        capability = "protected_prop_presence"
    elif requirement.predicate == "character_location" and coarse_actor and requirement.value in _COARSE_REGIONS:
        capability = "coarse_character_location"
    strong = capability != "advisory_only"
    return {"capability": capability, "may_confirm": strong and not requirement.known_unknown,
            "may_block": strong and requirement.critical and not requirement.known_unknown}


def _decision(findings):
    return next((state for state in ("BLOCK", "UNKNOWN", "WARN", "PASS")
                 if any(item["decision"] == state for item in findings)), "UNKNOWN")


def _finding(decision, reason, reference=None, requirement=None, observed=(), *, conflict=False, action=None):
    policy = capability_for(requirement) if requirement else {
        "capability": "not_evaluated", "may_confirm": False, "may_block": False,
    }
    raw_decision = decision
    if requirement is not None and requirement.known_unknown:
        decision = "UNKNOWN"
    elif decision == "PASS" and not policy["may_confirm"]:
        decision = "UNKNOWN"
    elif decision == "BLOCK" and not policy["may_block"]:
        decision = "WARN"
    return {
        "decision": decision, "raw_decision": raw_decision, "reason": reason, **policy,
        "clip_index": reference.clip_index if reference else None,
        "reference_index": reference.reference_index if reference else None,
        "image_sha256": reference.sha256 if reference else None,
        "expected": requirement.model_dump(mode="json") if requirement else None,
        "observed": [fact.model_dump(mode="json") for fact in observed],
        "conflicting_fields": [requirement.predicate] if conflict and requirement else [],
        "recommended_next_action": action.value if action else None,
    }


def _requirements_conflict(requirements):
    states, present_values = {}, {}
    for requirement in requirements:
        field = (requirement.predicate, requirement.subject)
        key = (*field, requirement.value)
        if key in states and states[key] != requirement.expected:
            return True
        states[key] = requirement.expected
        if requirement.predicate in _EXCLUSIVE and requirement.expected == "PRESENT":
            if field in present_values and present_values[field] != requirement.value:
                return True
            present_values[field] = requirement.value
    return False


def merge_requirements(requirements):
    """Duplicate declarations may strengthen restrictions, never erase them."""
    merged = {}
    for item in requirements:
        key = (item.predicate, item.subject, item.value, item.expected)
        previous = merged.get(key)
        merged[key] = item if previous is None else previous.model_copy(update={
            "critical": previous.critical or item.critical,
            "protected": previous.protected or item.protected,
            "known_unknown": previous.known_unknown or item.known_unknown,
        })
    return list(merged.values())


def evaluate_requirement(requirement: StateRequirement, facts: Sequence[ObservationFact], reference: VisualReference) -> dict:
    """Assess validated facts, then cap automatic authority without rewriting them."""
    related = [fact for fact in facts if (fact.predicate, fact.subject) == (requirement.predicate, requirement.subject)]
    relevant = [fact for fact in related if fact.value == requirement.value or requirement.predicate in _EXCLUSIVE]
    signs = {}
    for fact in relevant:
        signs.setdefault(fact.value, set()).add(fact.state)
    if (any(len(states) > 1 for states in signs.values()) or
            (requirement.predicate in _EXCLUSIVE and sum("PRESENT" in states for states in signs.values()) > 1)):
        return _finding("UNKNOWN", "CONTRADICTORY_OBSERVATIONS", reference, requirement, related, conflict=True)
    if any(fact.state == "ABSENT" and fact.confidence == "HIGH" and _ABSENCE_VISIBILITY_FLAGS.search(fact.evidence)
           for fact in relevant):
        return _finding("UNKNOWN", "INSUFFICIENT_EVIDENCE", reference, requirement, related)
    clear = [fact for fact in relevant if fact.confidence == "HIGH" and fact.evidence.strip()
             and fact.state in ("PRESENT", "ABSENT")]
    actual = next((fact.state for fact in clear if fact.value == requirement.value), None)
    if actual is None and requirement.predicate in _EXCLUSIVE:
        # Fine location labels cannot prove a different dominant region. Explicit
        # target uncertainty also cannot be converted into alternate-value absence.
        target_uncertain = any(fact.value == requirement.value for fact in relevant)
        alternatives = [fact for fact in clear if fact.state == "PRESENT"
                        and (requirement.predicate != "character_location"
                             or (requirement.value in _COARSE_REGIONS and fact.value in _COARSE_REGIONS))]
        if alternatives and not target_uncertain:
            actual = "ABSENT"
    if actual is None:
        return _finding("UNKNOWN", "INSUFFICIENT_EVIDENCE" if relevant else "MISSING_FACT", reference, requirement, related)
    if actual == requirement.expected:
        return _finding("PASS", "STATE_MATCH", reference, requirement, related)
    reason = {
        "contact_relation": "CONTACT_STATE_CONFLICT",
        "environment_relation": "ENVIRONMENT_STATE_CONFLICT",
        "facing_direction": "WRONG_ACTION_DIRECTION",
    }.get(requirement.predicate, "STATE_CONFLICT")
    if requirement.predicate == "character_location" and reference.role == "START":
        reason = "WRONG_START_STATE"
    elif actual == "ABSENT" and requirement.predicate == "prop_present" and requirement.protected:
        reason = "PROTECTED_PROP_MISSING"
    elif actual == "ABSENT" and requirement.predicate == "character_present":
        reason = "REQUIRED_CHARACTER_MISSING"
    return _finding("BLOCK" if requirement.critical else "WARN", reason, reference, requirement, related,
                    conflict=True, action=RecommendedNextAction.EDIT_IMAGE)


async def validate_references(
    request: VisualStateValidation | dict,
    references: Iterable[VisualReference],
    *,
    observer: VisualObservationProvider | None = None,
    known_observations: Iterable[ImageObservation | dict] = (),
) -> dict:
    """Known observations are trusted caller input, never extracted from a plan.

    UNKNOWN is nonblocking. PASS covers only policy-eligible supplied constraints
    and observation evidence, not independently certified pixels. Legacy requests
    without a policy use the current policy for this evaluation only; historical
    JSON and raw observations are never rewritten. This function never retries.
    """
    report = {
        "version": 1,
        "capability_policy": CAPABILITY_POLICY_VERSION,
        "enabled": (request.get("enabled") if isinstance(request, dict) else getattr(request, "enabled", False)) is True,
        "decision": "UNKNOWN", "findings": [], "references": [], "observations": [], "raw_observations": [],
        "scope": {"stage": "P0", "constraints": "explicit_approved_intent_only",
                  "coverage": "selected_references_only", "pixel_verification": "requires_trusted_observations",
                  "unknown_is_blocking": False},
    }
    try:
        request = VisualStateValidation.model_validate(request, strict=True)
    except (ValidationError, TypeError, ValueError):
        report["findings"].append(_finding("UNKNOWN", "INVALID_CONTRACT", action=RecommendedNextAction.REPLAN_CLIP))
        return report
    if not request.enabled:
        report["findings"].append(_finding("UNKNOWN", "DISABLED"))
        return report

    # Finish all deterministic checks before making even the first observer call.
    try:
        references = tuple(references)
        addresses = set()
        for reference in references:
            if (not isinstance(reference, VisualReference) or type(reference.clip_index) is not int or reference.clip_index < 1
                    or type(reference.reference_index) is not int or reference.reference_index < 0
                    or type(reference.payload) is not bytes or not reference.payload
                    or not isinstance(reference.source_url, str) or not isinstance(reference.role, str)
                    or (reference.keyframe_index is not None and type(reference.keyframe_index) is not int)):
                raise ValueError("INVALID_REFERENCE")
            address = (reference.clip_index, reference.reference_index)
            if address in addresses:
                raise ValueError("DUPLICATE_REFERENCE")
            addresses.add(address)
            report["references"].append({"clip_index": reference.clip_index, "reference_index": reference.reference_index,
                                         "image_sha256": reference.sha256, "source_url": reference.source_url,
                                         "role": reference.role, "keyframe_index": reference.keyframe_index, "decision": "UNKNOWN"})
        anchors = {}
        if _requirements_conflict(request.invariants):
            raise ValueError("CONFLICTING_REQUIREMENTS")
        for anchor in request.anchors:
            address = (anchor.clip_index, anchor.reference_index)
            if address not in addresses or address in anchors:
                raise ValueError("ANCHOR_TARGET_NOT_UNIQUE_OR_SELECTED")
            anchors[address] = anchor.requirements
            if _requirements_conflict([*request.invariants, *anchor.requirements]):
                raise ValueError("CONFLICTING_REQUIREMENTS")
    except (TypeError, ValueError) as exc:
        finding = _finding("UNKNOWN", "INVALID_CONTRACT", action=RecommendedNextAction.REPLAN_CLIP)
        finding["detail"] = str(exc)
        report["findings"].append(finding)
        return report

    requirements = {address: merge_requirements([*request.invariants, *anchors.get(address, ())]) for address in addresses}
    if not references or not any(requirements.values()):
        report["findings"].append(_finding("UNKNOWN", "NOT_EVALUATED"))
        return report
    known = {}
    try:
        for item in known_observations:
            observation = ImageObservation.model_validate(item, strict=True)
            known.setdefault(observation.image_sha256, []).append(observation)
    except (ValidationError, TypeError, ValueError):
        report["findings"].append(_finding("UNKNOWN", "INVALID_OBSERVATION"))
        return report

    cache, image_facts, errors = {}, {}, {}
    for reference in references:
        address = (reference.clip_index, reference.reference_index)
        selected = requirements[address]
        if not selected:
            errors[address] = "NOT_EVALUATED"
            continue
        question_keys = tuple(sorted({(item.predicate, item.subject, item.value) for item in selected}))
        digest = reference.sha256
        key = (digest, question_keys)
        if digest in known:
            if digest not in image_facts:
                image_facts[digest] = [fact for item in known[digest] for fact in item.facts]
                report["observations"].extend(item.model_dump(mode="json") for item in known[digest])
            continue
        if key not in cache:
            error, observation = None, None
            if observer is None:
                error = "OBSERVER_NOT_CONFIGURED"
            else:
                questions = tuple(ObservationQuestion(predicate=p, subject=s, value=v) for p, s, v in question_keys)
                try:
                    raw = await asyncio.wait_for(observer.observe(reference, questions), OBSERVATION_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    error = "OBSERVER_TIMEOUT"
                except Exception:
                    error = "OBSERVER_ERROR"
                else:
                    candidate = raw.model_dump(mode="json") if isinstance(raw, ImageObservation) else raw
                    try:
                        json.dumps(candidate, allow_nan=False)
                        recorded = deepcopy(candidate)
                    except (TypeError, ValueError):
                        recorded = {"invalid_response_type": type(raw).__name__, "json_serializable": False}
                    report["raw_observations"].append({"image_sha256": digest, "response": recorded})
                    try:
                        observation = ImageObservation.model_validate(raw, strict=True)
                    except (ValidationError, TypeError, ValueError):
                        error = "INVALID_OBSERVATION"
                    else:
                        if observation.image_sha256 != digest:
                            error = "OBSERVATION_HASH_MISMATCH"
            cache[key] = error
            if error is None:
                image_facts.setdefault(digest, []).extend(observation.facts)
                report["observations"].append(observation.model_dump(mode="json"))
        if cache[key] is not None:
            errors[address] = cache[key]

    # Merge same-image facts before evaluation so later answers cannot hide conflicts.
    for reference, summary in zip(references, report["references"]):
        address = (reference.clip_index, reference.reference_index)
        selected = requirements[address]
        if address in errors:
            findings = [_finding("UNKNOWN", errors[address], reference, item) for item in selected] or [
                _finding("UNKNOWN", errors[address], reference)]
        else:
            findings = [evaluate_requirement(item, image_facts[reference.sha256], reference) for item in selected]
        summary["decision"] = _decision(findings)
        report["findings"].extend(findings)
    report["decision"] = _decision(report["findings"])
    return report
