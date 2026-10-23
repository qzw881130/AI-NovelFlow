"""Deterministic pacing evidence for canonical temporal targets; no I/O."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.services import video_director_ai as h3


# Fractions of one canonical transition window, not measured speeds or per-verb
# timers. Translation uses a whole path window; path + convergence gets a modest
# reserve. These initial pacing heuristics need physical validation separately.
MOTION_WINDOW_RATIOS = {
    "NO_SIGNIFICANT_MOTION": Decimal("0"),
    "LOCAL_MOTION": Decimal("0.1"),
    "TRANSLATIONAL_MOTION": Decimal("1"),
    "POSTURE_TRANSITION": Decimal("0.5"),
    "PROP_INTERACTION": Decimal("0.5"),
    "COMPOSITE_MOTION": Decimal("1.5"),
}

_POSTURE = re.compile(r"坐下|起身|跪下|站起|\b(?:sits? down|stands? up|kneels? down)\b", re.I)
_PROP = re.compile(r"拿起|放下|交给|接过|穿上|脱下|\b(?:picks? up|puts? down|hands? over|takes? off|puts? on)\b", re.I)
_LOCAL = re.compile(r"转头|目光|视线|轻微|细微|小幅|整理|保持|维持|始终位于|留在|\b(?:turns? (?:the )?head|gaze|small|slight|adjusts?|holds?|stays?|remains?)\b", re.I)
_SETTLED = re.compile(r"站定|站稳|停稳|\b(?:standing|settled|at rest|stands? still)\b", re.I)
_NEGATED_TARGET = re.compile(r"不|未|没有|不得|禁止|\b(?:not|never|without)\b", re.I)
_NEGATED_OR_COMPLETE = re.compile(r"不|未|没有|不得|禁止|已|已经|\b(?:not|never|without|already|no longer)\b", re.I)


def _decimal(value) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _seconds(value: Decimal) -> float:
    return float(value)


def _owned_actions(name: str, text: str) -> list[str]:
    """Exact actor-led clauses only; no inferred ownership across commas."""
    actor = re.compile(rf"^{re.escape(name)}(?![A-Za-z0-9_])")
    actions = []
    for clause in re.split(r"[，。；.!?;\n]", text):
        match = actor.match(clause.strip())
        if match:
            actions.append(clause.strip()[match.end():])
    return actions


def _has_owned_action(actions: list[str], marker: re.Pattern, names: set[str], owner: str) -> bool:
    for action in actions:
        match = marker.search(action)
        if match and not _NEGATED_OR_COMPLETE.search(action[:match.start()]) and not any(
            name in action[:match.start()] for name in names if name != owner
        ):
            return True
    return False


def analyze_transition_reachability(previous: dict, target: dict, transition: dict) -> dict:
    """Reuse Phase 2/2.1 authorities; compute one maximum concurrent budget."""
    start = h3._canonical_body_membership(previous)
    end = h3._canonical_body_membership(target)
    beginning = _decimal(transition.get("start_time"))
    finish = _decimal(transition.get("end_time"))
    previous_time = _decimal(previous.get("time_seconds"))
    target_time = _decimal(target.get("time_seconds"))
    if (start is None or end is None or beginning is None or finish is None or finish <= beginning
            or beginning != previous_time or finish != target_time
            or transition.get("from_keyframe_index") != previous.get("index")
            or transition.get("to_keyframe_index") != target.get("index")):
        return {"motion_budget_seconds": 0.0, "subjects": [], "findings": [
            {"code": "TEMPORAL_REACHABILITY_UNCERTAIN", "reason": "CANONICAL_PRESENCE_OR_TIMING_UNAVAILABLE"}
        ]}
    names = start | end
    # Character names serve as stable analysis IDs. This does not assign or render
    # H3 Subject/Picture numbers and does not require physical identity references.
    identities = {name: name for name in sorted(names)}
    ownership = h3.compile_h3_reference_bindings(
        [], identities, [target], [transition], capability="TEMPORAL_EXTEND",
        previous_av_present=True, current_visual_state=previous,
    )
    motion = {item["name"]: item for item in ownership["motion_ownership"]}
    old_roles = h3._canonical_character_roles(previous)
    new_roles = h3._canonical_character_roles(target)
    subjects, findings = [], []
    duration = finish - beginning
    for name in sorted(names):
        lifecycle, _ = h3._canonical_body_lifecycle(name, name, previous, [target], [transition], identities)
        actions = _owned_actions(name, str(transition.get("transition_description") or ""))
        posture = _has_owned_action(actions, _POSTURE, names, name)
        prop = _has_owned_action(actions, _PROP, names, name)
        local = _has_owned_action(actions, _LOCAL, names, name)
        translation = motion[name]["motion_class"] == "TRANSLATIONAL_MOTION" or lifecycle in {"ENTERING_NEW_BODY", "EXITING_CURRENT_BODY"}
        presence_change = lifecycle in {"ENTERING_NEW_BODY", "EXITING_CURRENT_BODY"}
        role = new_roles.get(name, "")
        settle = _SETTLED.search(role)
        settled_target = bool(settle and not _NEGATED_TARGET.search(role[:settle.start()]))
        if lifecycle == "CANONICAL_BODY_PRESENCE_UNKNOWN":
            classification = "UNKNOWN"
        elif translation:
            classification = "COMPOSITE_MOTION" if (presence_change and settled_target) or posture or prop else "TRANSLATIONAL_MOTION"
        elif posture:
            classification = "POSTURE_TRANSITION"
        elif prop:
            classification = "PROP_INTERACTION"
        elif local:
            classification = "LOCAL_MOTION"
        elif old_roles.get(name) == new_roles.get(name) and not actions:
            classification = "NO_SIGNIFICANT_MOTION"
        else:
            classification = "UNKNOWN"
        ratio = MOTION_WINDOW_RATIOS.get(classification, Decimal(0))
        reason = [lifecycle, classification]
        if presence_change and settled_target:
            reason.append("SETTLED_TARGET_AFTER_PRESENCE_CHANGE")
        if classification == "UNKNOWN":
            findings.append({"code": "TEMPORAL_REACHABILITY_UNCERTAIN", "character": name,
                             "reason": "OWNED_MOTION_NOT_RELIABLY_CLASSIFIED"})
        subjects.append({
            "character": name, "lifecycle": lifecycle,
            "start_presence": "PRESENT" if name in start else "ABSENT",
            "target_presence": "PRESENT" if name in end else "ABSENT",
            "motion_ownership": motion[name]["motion_class"], "motion_class": classification,
            "motion_budget_seconds": _seconds(duration * ratio),
            "motion_window_ratio": float(ratio),
            "blocking_delta": {"previous_role": old_roles.get(name), "target_role": new_roles.get(name)},
            "reachability_reason": "+".join(reason),
        })
    return {"motion_budget_seconds": max((s["motion_budget_seconds"] for s in subjects), default=0.0),
            "transition_duration_seconds": float(duration),
            "subjects": subjects, "findings": findings}


def _target_index(source: dict) -> int | None:
    raw = source.get("keyframe_index")
    match = re.fullmatch(r"KF([0-9]+)", str(source.get("id") or ""))
    if raw is None:
        raw = match.group(1) if match else None
    try:
        index = int(raw)
        return index if not match or index == int(match.group(1)) else None
    except (ValueError, TypeError):
        return None


def plan_temporal_anchor_reachability(plan: dict, clip: dict, semantic_anchors: list[dict]) -> list[dict]:
    """Add effective execution positions while preserving canonical local times.

    Semantic input validation and projection remain owned by the existing compiler.
    Each target uses its own incoming edge, not a summed Clip-wide motion history.
    """
    # Local import avoids a compiler/planner cycle; the old projection owns all
    # fps, frame alignment and indexing arithmetic.
    from app.services.clip_execution_compiler import (
        _temporal_anchor_frame_position, _temporal_anchor_physical_frame_position,
        _temporal_anchor_physical_frame_time, temporal_extend_frame_count,
    )

    clip_start = _decimal(clip["start_time"])
    duration = _decimal(clip["end_time"]) - clip_start
    count = temporal_extend_frame_count(float(duration))
    states = {state.get("index"): state for state in plan.get("keyframes") or [] if isinstance(state, dict)}
    transitions = [edge for edge in plan.get("transitions") or [] if isinstance(edge, dict)]
    reached = {}
    result = []
    for offset, anchor in enumerate(semantic_anchors):
        target_index = _target_index(anchor["source"])
        target = states.get(target_index)
        edges = [edge for edge in transitions if edge.get("to_keyframe_index") == target_index] if target else []
        edge = edges[0] if len(edges) == 1 else None
        previous_index = edge.get("from_keyframe_index") if edge else None
        previous = states.get(previous_index)
        analysis = {"motion_budget_seconds": 0.0, "subjects": [], "findings": [
            {"code": "TEMPORAL_REACHABILITY_UNCERTAIN", "reason": "CANONICAL_EDGE_UNAVAILABLE"}
        ]}
        local_start = Decimal(0)
        if previous and edge and _decimal(edge.get("start_time")) is not None:
            analysis = analyze_transition_reachability(previous, target, edge)
            local_start = max(Decimal(0), _decimal(edge["start_time"]) - clip_start)
        findings = [dict(finding, anchor_id=anchor["anchor_id"]) for finding in analysis["findings"]]
        semantic_time = _decimal(anchor["time_seconds"])
        budget = _decimal(analysis["motion_budget_seconds"])
        # A delayed predecessor becomes the actual start for its successor edge.
        known = any(s["motion_class"] != "UNKNOWN" for s in analysis["subjects"])
        earliest = max(local_start, reached.get(previous_index, Decimal(0))) + budget if known else Decimal(0)
        requested = max(semantic_time, earliest)
        bounded = min(duration, requested)
        projected = _temporal_anchor_frame_position(bounded, duration, count)
        # Proportional semantic projection is not a physical seconds clock.
        # Use the actual frozen fps for the lower bound; preserve HALF_UP above.
        reachable_frame = _temporal_anchor_physical_frame_position(earliest)
        candidate = max(projected, reachable_frame)
        maximum = count - (len(semantic_anchors) - offset - 1)
        minimum = result[-1]["frame_position"] + 1 if result else 1
        position = min(maximum, max(minimum, candidate))
        clamped = requested > duration or position != candidate
        if clamped:
            findings.append({"code": "TEMPORAL_ANCHOR_REACHABILITY_CLAMPED", "anchor_id": anchor["anchor_id"],
                             "requested_local_time": float(requested), "effective_frame_position": position})
        frame_time = _temporal_anchor_physical_frame_time(position)
        reached[target_index] = frame_time
        critical = [s for s in analysis["subjects"] if s["motion_budget_seconds"] == analysis["motion_budget_seconds"] and budget]
        result.append({**anchor, "frame_position": position, "reachability": {
            "policy": "CANONICAL_MOTION_WINDOW_V1",
            "previous_state_index": previous_index, "target_state_index": target_index,
            "semantic_frame_position": anchor["frame_position"], "effective_frame_position": position,
            "semantic_local_time": float(semantic_time), "earliest_reachable_local_time": float(earliest) if known else None,
            "transition_start_local_time": float(local_start),
            "canonical_transition_duration_seconds": analysis.get("transition_duration_seconds"),
            "requested_anchor_local_time": float(requested),
            "effective_anchor_local_time": float(frame_time), "motion_budget_seconds": float(budget),
            "effective_frame_local_time": float(frame_time),
            "placement_adjusted": position != anchor["frame_position"], "clamped": clamped,
            "reachability_reason": [s["reachability_reason"] for s in critical] or [
                "NO_SIGNIFICANT_MOTION" if known else "TEMPORAL_REACHABILITY_UNCERTAIN"
            ],
            "critical_subjects": critical, "findings": findings,
        }})
    return result
