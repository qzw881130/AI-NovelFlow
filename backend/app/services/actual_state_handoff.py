"""Two-clip semantic handoff only. No generation, repair, canon writes, or I/O."""
from copy import deepcopy
import math

from app.schemas.visual_state import ActualStateHandoff, VisualStateValidation
from app.services.visual_state_validator import (
    CAPABILITY_POLICY_VERSION, _requirements_conflict, merge_requirements, validate_references,
)


def validate_handoff_scope(request, plan, mode):
    option = ActualStateHandoff.model_validate(request.get("actual_state_handoff") or {}, strict=True)
    if not option.enabled:
        return False
    visual = VisualStateValidation.model_validate(request.get("visual_state_validation") or {}, strict=True)
    if not visual.enabled:
        raise ValueError("HANDOFF_REQUIRES_VISUAL_STATE_VALIDATION")
    if request.get("skip_llm_when_prompt_exists"):
        raise ValueError("HANDOFF_REQUIRES_FRESH_PROMPT")
    windows = plan.get("window_plans") or []
    if mode != "MULTI_KEYFRAME" or request.get("only_window_index") is not None or len(windows) != 2:
        raise ValueError("HANDOFF_REQUIRES_WHOLE_TWO_CLIP_MULTI")
    for index, window in enumerate(windows, 1):
        frames = window.get("keyframe_indexes")
        if (type(window.get("window_index")) is not int or window["window_index"] != index
                or window.get("selected_frame_count") not in (3, 4) or not isinstance(frames, list)
                or len(frames) != window["selected_frame_count"] or any(type(f) is not int or f < 1 for f in frames)
                or frames != sorted(set(frames))):
            raise ValueError("HANDOFF_INVALID_CLIP_MEMBERSHIP")
        start, end = window.get("start_time"), window.get("end_time")
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start):
            raise ValueError("HANDOFF_INVALID_CLIP_RANGE")
    if abs(windows[0]["end_time"] - windows[1]["start_time"]) > 0.001:
        raise ValueError("HANDOFF_REQUIRES_ADJACENT_WINDOWS")
    if windows[0]["keyframe_indexes"][-1] != windows[1]["keyframe_indexes"][0]:
        raise ValueError("HANDOFF_REQUIRES_SHARED_PLANNED_BOUNDARY")
    return True


def _rule_key(item):
    return item.predicate, item.subject, item.value, item.expected


def validate_reference_slots(graph, mapping, count):
    """P1 supports the shipped direct LoadImage -> ordered H3 reference ports."""
    consumers = [node for node, value in graph.items() if value.get("class_type") in
                 ("MiniMaxH3AudioConditioningT8", "MiniMaxH3ReferenceToVideo")]
    if len(consumers) != 1:
        raise ValueError("HANDOFF_REQUIRES_ONE_H3_REFERENCE_CONSUMER")
    consumer = consumers[0]
    nodes = [mapping.get("reference_image_node_id"), *[mapping.get(f"keyframe_node_{i}") for i in range(1, count)]]
    if len(set(nodes)) != count or any(graph.get(node, {}).get("class_type") != "LoadImage" for node in nodes):
        raise ValueError("HANDOFF_REFERENCE_LOADERS_NOT_DISTINCT")
    inputs = graph[consumer]["inputs"]
    for index, node in enumerate(nodes):
        link = inputs.get(f"ref_images.ref_image_{index}")
        if not isinstance(link, list) or len(link) != 2 or link[0] != node or type(link[1]) is not int or link[1] != 0:
            raise ValueError("HANDOFF_REFERENCE_SLOT_MISMATCH")
    if any(key.startswith("ref_images.ref_image_") and key not in {f"ref_images.ref_image_{i}" for i in range(count)}
           and value not in (None, "", []) for key, value in inputs.items()):
        raise ValueError("HANDOFF_UNEXPECTED_REFERENCE_SLOT")
    # Follow the shipped visual/latent path, not arbitrary ancestry through audio.
    visual_inputs = {"SaveVideo": "video", "CreateVideo": "images", "VHS_VideoCombine": "images",
                     "RAMCleanup": "anything", "RTXVideoSuperResolution": "images",
                     "MiniMaxH3AVDecodeT8": "av_latent", "VAEDecode": "samples", "SamplerCustomAdvanced": "latent_image"}
    node, slot, seen = mapping.get("video_save_node_id"), 0, set()
    while node != consumer:
        if node in seen or node not in graph or slot not in (0, 1):
            raise ValueError("HANDOFF_REFERENCE_CONSUMER_NOT_IN_OUTPUT")
        seen.add(node)
        current = graph[node]
        kind = current.get("class_type")
        if kind not in visual_inputs or (kind != "SamplerCustomAdvanced" and slot != 0):
            raise ValueError("HANDOFF_UNSUPPORTED_VISUAL_OUTPUT_PATH")
        source = current.get("inputs", {})
        if kind == "SamplerCustomAdvanced":
            guider = source.get("guider")
            if (not isinstance(guider, list) or len(guider) != 2 or type(guider[1]) is not int or guider[1] != 0
                    or graph.get(guider[0], {}).get("class_type") != "BasicGuider"):
                raise ValueError("HANDOFF_REFERENCE_CONDITIONING_NOT_USED")
            conditioning = graph[guider[0]].get("inputs", {}).get("conditioning")
            if (not isinstance(conditioning, list) or len(conditioning) != 2 or conditioning[0] != consumer
                    or type(conditioning[1]) is not int or conditioning[1] != 0):
                raise ValueError("HANDOFF_REFERENCE_CONDITIONING_NOT_USED")
        link = source.get(visual_inputs[kind])
        if not isinstance(link, list) or len(link) != 2 or not isinstance(link[0], str) or type(link[1]) is not int:
            raise ValueError("HANDOFF_REFERENCE_CONSUMER_NOT_IN_OUTPUT")
        node, slot = link
    if slot != 1:
        raise ValueError("HANDOFF_REFERENCE_LATENT_NOT_USED")


async def resolve_handoff(*, visual_request, snapshot, expected_clips, original_validation,
                          tail_evidence, references, observer=None):
    """References are fixed tail candidates, including the selected and true last.

    The caller verifies receipt/file ownership. UNKNOWN critical fields hold C2;
    filtering JSON is never represented as filtering the whole reference image.
    """
    visual = VisualStateValidation.model_validate(visual_request, strict=True)
    last_slot = expected_clips[0]["selected_frame_count"] - 1
    boundary = merge_requirements([*visual.invariants, *[
        rule for anchor in visual.anchors if (anchor.clip_index, anchor.reference_index) in ((1, last_slot), (2, 0))
        for rule in anchor.requirements]])
    future = [rule for anchor in visual.anchors if anchor.clip_index == 2 and anchor.reference_index > 0
              for rule in anchor.requirements if rule.critical]
    report = {
        "version": 1, "capability_policy": CAPABILITY_POLICY_VERSION, "decision": "HUMAN_REVIEW", "can_submit_c2": False,
        "planned_state": {"boundary": [r.model_dump(mode="json") for r in boundary],
                          "remaining_c2_anchors": [a.model_dump(mode="json") for a in visual.anchors if a.clip_index == 2 and a.reference_index > 0]},
        "canonical_state": {"requirements": [r.model_dump(mode="json") for r in visual.invariants],
                            "characters": deepcopy(snapshot.get("characters")), "props": deepcopy(snapshot.get("props"))},
        "actual_observed_state": {"tail_window": deepcopy(tail_evidence), "validation": None},
        "trusted_handoff_state": {"confirmed_actual_fields": [], "canonical_constraints": [r.model_dump(mode="json") for r in visual.invariants],
                                  "excluded_fields": [], "reference_eligible": False},
        "issues": [], "recommended_next_action": None,
    }

    def issue(code, fields=(), *, action=None):
        report["issues"].append({"reason": code, "conflicting_fields": list(fields), "reference_frame": tail_evidence.get("selected"),
                                 "recommended_next_action": action})
        if action:
            report["recommended_next_action"] = action

    if not tail_evidence.get("can_use") or not tail_evidence.get("technical_tail_compatible"):
        issue("TAIL_FRAME_UNUSABLE_OR_INCOMPATIBLE", action="REGENERATE_C1")
        return report
    if not boundary or not any(rule.critical for rule in boundary):
        issue("EXPLICIT_BOUNDARY_STATE_REQUIRED")
        return report
    if _requirements_conflict(boundary):
        issue("PLANNED_CANONICAL_BOUNDARY_CONFLICT", [r.model_dump(mode="json") for r in boundary])
        return report
    if len(boundary) > 64:
        issue("HANDOFF_RULE_LIMIT_EXCEEDED")
        return report

    observed = await validate_references({"enabled": True, "invariants": [r.model_dump(mode="json") for r in boundary]},
                                        references, observer=observer)
    report["actual_observed_state"]["validation"] = observed
    selected_hash = tail_evidence["selected"]["sha256"]
    for finding in observed["findings"]:
        expected = finding.get("expected") or {}
        if finding["decision"] == "BLOCK":
            report["decision"] = "BLOCK"
            issue("ACTUAL_VIOLATES_PLANNED_OR_CANONICAL", [finding], action="REGENERATE_C1")
        elif expected.get("critical") and not (finding["decision"] == "PASS" and finding["may_confirm"]):
            issue("CRITICAL_ACTUAL_STATE_NOT_TRUSTED", [finding])
        if finding["decision"] == "PASS" and finding["may_confirm"] and finding["image_sha256"] == selected_hash:
            peers = [other for other in observed["findings"] if other.get("expected") == expected]
            if all(other["decision"] == "PASS" and other["may_confirm"] for other in peers):
                report["trusted_handoff_state"]["confirmed_actual_fields"].append({
                    **{key: expected[key] for key in ("predicate", "subject", "value")},
                    "state": expected["expected"], "confidence": "HIGH", "image_sha256": selected_hash})
            else:
                issue("TAIL_STATE_NOT_STABLE_FOR_INHERITANCE", peers)
        elif finding["decision"] != "PASS" or not finding["may_confirm"]:
            report["trusted_handoff_state"]["excluded_fields"].append(deepcopy(finding))

    # Reuse the original future-anchor evidence; do not silently rewrite targets
    # or discard an unproven fine contact condition to make an actual PNG usable.
    for finding in original_validation.get("findings", []):
        required = finding.get("expected") or {}
        if finding.get("clip_index") == 2 and required.get("critical") and not (
                finding["decision"] == "PASS" and finding.get("may_confirm")):
            issue("PLANNED_C2_ANCHOR_NOT_TRUSTED", [finding])
    if _requirements_conflict([*boundary, *future]):
        issue("PLANNED_ANCHOR_TRANSITION_REQUIRES_REVIEW", [r.model_dump(mode="json") for r in future])
    boundary_keys = {_rule_key(rule) for rule in boundary}
    if any(_rule_key(rule) not in boundary_keys for rule in future):
        issue("FUTURE_ANCHOR_REQUIRES_UNPROVEN_STATE_CHANGE", [r.model_dump(mode="json") for r in future
                                                               if _rule_key(r) not in boundary_keys])
    trusted_keys = {(fact["predicate"], fact["subject"], fact["value"], fact["state"])
                    for fact in report["trusted_handoff_state"]["confirmed_actual_fields"]}
    if any(_rule_key(rule) not in trusted_keys for rule in future):
        issue("FUTURE_CRITICAL_STATE_NOT_TRUSTED", [rule.model_dump(mode="json") for rule in future
                                                   if _rule_key(rule) not in trusted_keys])
    for index in range(1, expected_clips[1]["selected_frame_count"]):
        findings = [item for item in original_validation.get("findings", [])
                    if item.get("clip_index") == 2 and item.get("reference_index") == index and item.get("expected")]
        for rule in boundary:
            if not rule.critical:
                continue
            if not any(all(item["expected"].get(field) == getattr(rule, field) for field in ("predicate", "subject", "value", "expected"))
                       and item["decision"] == "PASS" and item.get("may_confirm") for item in findings):
                issue("C2_ANCHOR_COMPATIBILITY_COVERAGE_MISSING", [{"reference_index": index, "requirement": rule.model_dump(mode="json")}])

    canonical_characters = snapshot.get("characters") or []
    declared = {r.subject for r in boundary if r.predicate == "character_present" and r.expected == "PRESENT" and r.critical}
    if any(character not in declared for character in canonical_characters):
        issue("EXPLICIT_CANONICAL_IDENTITY_COVERAGE_REQUIRED", canonical_characters)
    if not report["trusted_handoff_state"]["confirmed_actual_fields"]:
        issue("NO_TRUSTED_HANDOFF_FIELDS")
    if report["issues"]:
        return report
    report["trusted_handoff_state"]["reference_eligible"] = True
    report["decision"] = "WARN" if report["trusted_handoff_state"]["excluded_fields"] else "CONTINUE"
    report["can_submit_c2"] = True
    return report
