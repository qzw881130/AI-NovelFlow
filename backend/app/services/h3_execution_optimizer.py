"""Shared registered #14 execution optimizer; raw prompts remain reusable."""
import asyncio
import hashlib
import json
import math
import re

from app.constants.capability import VIDEO_CAPABILITY_CONTRACTS
from app.services.llm_service import LLMService
from app.services.llm.cancellation import LLMCallTerminated
from app.services.video_director_ai import resolve_prompt_template, append_video_ai_call
from app.services.vision_inputs import vision_proxy, previous_video_frames
from app.utils.json_parser import safe_parse_llm_json
from app.services.h3_native_prompt import check_native_prompt, declared_duration, speaker_bindings, MAX_PROMPT_CHARACTERS

VERSION = "h3_execution_optimizer_native_v5"
TEMPLATE_TYPE = "h3_execution_optimizer_prompt"
EPSILON = 0.000001


def workflow_duration_limits(extension=None, capability="GENERATE"):
    """Intersect the existing validated capability with the selected workflow."""
    contract = VIDEO_CAPABILITY_CONTRACTS.get(capability, VIDEO_CAPABILITY_CONTRACTS["GENERATE"])
    extension = extension or {}
    return {"minimum": max(float(contract["min_duration"]), float(extension.get("min_clip_duration") or extension.get("min_seconds") or contract["min_duration"])),
            "maximum": min(20.0, float(contract["max_duration"]), float(extension.get("max_clip_duration") or extension.get("max_seconds") or contract["max_duration"])),
            "absolute_maximum": 20.0, "frame_rule": "existing frozen workflow duration-to-frames conversion"}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _same(a, b):
    return _number(a) and _number(b) and abs(a - b) <= EPSILON


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def effective_execution_duration(original_duration, record=None, limits=None):
    """A validated #14 result wins; upstream duration is only the Raw fallback."""
    original = float(original_duration)
    limits = limits or workflow_duration_limits()
    duration = original
    source = "ORIGINAL"
    optimized = None
    if record and record.get("status") == "OPTIMIZED" and (record.get("authority_check") or {}).get("passed"):
        optimized = ((record.get("output") or {}).get("av_timeline") or {}).get("optimized_duration")
        if not _number(optimized) or not 0 < optimized <= 20 or not limits["minimum"] <= optimized <= limits["maximum"]:
            raise ValueError("#14 optimized_duration 超出当前 workflow capability")
        declared = declared_duration(record.get("optimized_prompt") or "")
        if not _same(declared, optimized):
            raise ValueError("#14 optimized_prompt duration 与 av_timeline 不一致")
        duration, source = float(optimized), "H3_PROMPT_OPTIMIZER"
    if not _number(duration) or not 0 < duration <= 20 or not limits["minimum"] <= duration <= limits["maximum"]:
        raise ValueError("H3 effective_duration 超出当前 workflow capability")
    return {"original_duration": original, "optimized_duration": optimized,
            "effective_duration": duration, "duration_source": source}


def retime_temporal_manifest(manifest, record):
    """Project validated execution arrivals through the existing frame converter."""
    if not manifest or record.get("status") != "OPTIMIZED":
        return manifest
    from app.services.clip_execution_compiler import project_temporal_anchor_positions
    timeline = record["output"]["av_timeline"]
    times = {a["id"]: a["optimized_time"] for a in timeline["anchors"]}
    dropped = {a["id"] for a in timeline["anchors"] if a.get("decision") == "DROP"}
    anchors = [{**a, "time_seconds": times[a["anchor_id"]]} for a in manifest["anchors"] if a["anchor_id"] not in dropped]
    projected = project_temporal_anchor_positions(anchors, timeline["optimized_duration"]) if anchors else []
    result = []
    for anchor, position in zip(anchors, projected):
        item = {**anchor, "frame_position": position["frame_position"],
                "original_time_seconds": next(a["time_seconds"] for a in manifest["anchors"] if a["anchor_id"] == anchor["anchor_id"]),
                "timing_source": "H3_PROMPT_OPTIMIZER"}
        if "reachability" in item:
            item["initial_reachability"] = item.pop("reachability")
        result.append(item)
    return {**manifest, "anchors": result, "excluded_anchors": [a for a in manifest["anchors"] if a["anchor_id"] in dropped],
            "effective_duration": timeline["optimized_duration"]}


def dialogue_events(prompt):
    pattern = (r"(?m)^\s*(D\d+):[ \t]*\n[ \t]*speaker:[ \t]*(<Subject \d+>)[ \t]*\n"
               r"[ \t]*start_time:[ \t]*([\d.]+)s[ \t]*\n[ \t]*end_time:[ \t]*([\d.]+)s[ \t]*\n"
               r"[ \t]*exact_dialogue:[ \t]*([^\n]+)")
    return [{"id": match[0], "speaker": match[1], "start_time": float(match[2]),
             "end_time": float(match[3]), "exact_dialogue": match[4].rstrip()}
            for match in re.findall(pattern, prompt)]


def subject_bindings(prompt):
    bindings = {}
    for subject, name in re.findall(r"(?m)^[ \t]*(<Subject \d+>)\s+is\s+([^,，\n.;；。:：]+)", prompt):
        bindings.setdefault(subject, name.strip())
    return bindings


def anchor_declarations(prompt):
    result = []
    for line in prompt.splitlines():
        match = re.match(r"\s*[-*]?\s*(KF\d+)\s*[—:@-].*?\b(?:Clip-local\s+|@\s*)?([\d.]+)s\b", line)
        if match:
            picture = re.search(r"<Picture \d+>", line)
            result.append({"id": match[1], "time": float(match[2]), "picture": picture[0] if picture else None})
    return result


def anchor_facts(prompt):
    """Copy visual targets verbatim; arrival time alone is execution-owned."""
    result = []
    for line in prompt.splitlines():
        match = re.match(r"\s*[-*]?\s*(KF\d+)\s*[—:@-](.*?)\b([\d.]+)s\b(.*)$", line)
        if match:
            picture = re.search(r"<Picture \d+>", match[4])
            result.append({"id": match[1], "order": len(result) + 1,
                           "declaration_prefix": match[2].strip(), "visual_target": match[4].strip(),
                           "picture": picture[0] if picture else None})
    return result


def temporal_declarations(prompt, anchors):
    """Read existing temporal IDs or their linked canonical KF declarations."""
    result = []
    for anchor in anchors:
        source = anchor.get("source") or {}
        state = source.get("keyframe_index") or anchor.get("source_state_index")
        aliases = [str(anchor["anchor_id"])]
        if state is not None:
            aliases.append(f"KF{state}")
        elif str(source.get("id") or "").startswith("KF"):
            aliases.append(str(source["id"]))
        for alias in aliases:
            matches = re.findall(r"(?m)^\s*[-*]?\s*" + re.escape(alias) + r"\s*[—:@-].*?([\d.]+)s\b", prompt)
            if matches:
                result.extend({"anchor_id": anchor["anchor_id"], "time_seconds": float(time)} for time in matches)
                break
    return result


def _temporal_target_suffix(prompt, anchor_id):
    match = re.search(r"(?m)^\s*[-*]?\s*" + re.escape(str(anchor_id)) + r"\s*[—:@-].*?[\d.]+s\b(.*)$", prompt)
    return match[1].strip() if match else None


def build_runtime_input(raw_prompt, generation_mode, clip, reference_manifest=None,
                        reference_images=None, temporal_anchors=None, previous_video_path=None,
                        execution_context=None):
    """Use actual compiler manifests and builder facts; images never decide speakers."""
    clip = dict(clip or {})
    duration = float(clip.get("planned_duration") or clip.get("duration") or
                     (float(clip.get("end_time", 4)) - float(clip.get("start_time", 0))))
    subjects = subject_bindings(raw_prompt)
    references = (reference_manifest or {}).get("references") or []
    if not references:
        references = [{"slot": i, "kind": "DIRECTOR_VISUAL_ANCHOR", "image_url": item.get("url"),
                       "source_role": item.get("label")} for i, item in enumerate(reference_images or [], 1)]
    bindings, visual, images = [], [], []
    for i, ref in enumerate(references, 1):
        slot = ref.get("slot", i)
        picture = f"<Picture {slot}>"
        kind = ref.get("kind") or ref.get("source_type") or "REFERENCE"
        character = ref.get("source_name")
        subject = next((key for key, name in subjects.items() if name == character), None)
        binding = {"picture": picture, "type": kind, "subject": subject,
                   "source_name": character, "source_id": ref.get("source_id") or ref.get("source_identity"),
                   "state_index": ref.get("source_keyframe_index"),
                   "time": (float(ref["source_time_seconds"]) - float(clip.get("start_time") or 0)) if ref.get("source_time_seconds") is not None else None,
                   "source_time_seconds": ref.get("source_time_seconds"), "role": ref.get("source_role")}
        bindings.append(binding)
        source = ref.get("local_path") or ref.get("image_url")
        if not source:
            raise ValueError(f"VISION_INPUT_UNAVAILABLE: {picture} 缺少实际图片")
        proxy = vision_proxy(source, logical_id=picture, name=picture, reference_type=kind,
                             role=ref.get("source_role"), binding=subject or character,
                             source_asset_id=binding["source_id"], time=binding["time"])
        images.append(proxy)
        visual.append({**binding, "id": picture, "vision_proxy": proxy["proxy_url"],
                       "source_sha256": proxy["source_sha256"],
                       "source_dimensions": proxy["source_dimensions"], "submitted_dimensions": proxy["submitted_dimensions"]})
    anchors = []
    for anchor in temporal_anchors or []:
        item = {key: anchor.get(key) for key in ["anchor_id", "time_seconds", "source", "source_state_index", "description"]}
        anchors.append(item)
        source = anchor.get("local_path") or anchor.get("image_url")
        if source:
            proxy = vision_proxy(source, logical_id=f"TemporalAnchor:{anchor.get('anchor_id')}",
                                 name=f"TemporalAnchor:{anchor.get('anchor_id')}", reference_type="TEMPORAL_ANCHOR",
                                 role="timed_visual_target", binding=anchor.get("source"), time=anchor.get("time_seconds"))
            images.append(proxy)
            visual.append({**item, "id": proxy["logical_id"], "type": "TEMPORAL_ANCHOR", "vision_proxy": proxy["proxy_url"]})
    context = execution_context or {}
    continuation = context.get("continuation")
    if continuation and (not previous_video_path or continuation.get("binding_verified") is not True):
        raise ValueError("PREVIOUS_AV_BINDING_MISSING: verified source required")
    if context.get("capability") in {"EXTEND", "TEMPORAL_EXTEND", "VIDEO_CONTINUATION"} and not continuation:
        raise ValueError("PREVIOUS_AV_BINDING_MISSING: continuation timing contract required")
    if previous_video_path and not continuation:
        raise ValueError("PREVIOUS_AV_BINDING_MISSING: source without verified continuation contract")
    previous = previous_video_frames(previous_video_path, continuation["context_frames"]) if continuation else []
    images.extend(previous)
    initial_events = dialogue_events(raw_prompt)
    temporal_facts = []
    for item in anchors:
        source = {k: v for k, v in (item.get("source") or {}).items() if k not in {"time", "time_seconds", "source_time_seconds"}}
        temporal_facts.append({**{k: v for k, v in item.items() if k != "time_seconds"}, "source": source,
                               "declaration_suffix": _temporal_target_suffix(raw_prompt, item["anchor_id"])})
    authority = {"generation_mode": generation_mode,
                 "dialogue_events": [{"id": e["id"], "speaker": e["speaker"], "exact_dialogue": e["exact_dialogue"],
                                      "duration": round(e["end_time"] - e["start_time"], 9), "order": i}
                                     for i, e in enumerate(initial_events, 1)], "subject_bindings": subjects,
                 "reference_bindings": [{k: v for k, v in item.items() if k not in {"time", "source_time_seconds"}} for item in bindings],
                 "visual_anchor_order": anchor_facts(raw_prompt),
                 "temporal_anchor_order": temporal_facts,
                 "allowed_dialogue_overlaps": [[a["id"], b["id"]] for i, a in enumerate(initial_events)
                                               for b in initial_events[i + 1:] if b["start_time"] < a["end_time"] - EPSILON]}
    initial_timing = {"duration": duration, "dialogue_events": initial_events,
                      "visual_anchors": anchor_declarations(raw_prompt), "temporal_anchors": anchors}
    if continuation:
        authority["continuation"] = continuation
    if context.get("anchor_policy_version") == 1:
        from app.services.h3_anchor_policy import anchor_policy
        authority["anchor_policy"] = anchor_policy(authority, initial_timing, context)
    runtime = {"optimizer_version": VERSION, "generation_mode": generation_mode,
               "execution_mode": "VIDEO_CONTINUATION" if continuation else "STANDARD_GENERATION",
               "clip": {"id": clip.get("id") or clip.get("clip_id") or clip.get("clip_index"),
                        "duration": duration, "continuity_mode": (execution_context or {}).get("continuity_mode") or "UNSPECIFIED"},
               "raw_h3_prompt": raw_prompt, "immutable_authority": authority,
               "initial_execution_timing": initial_timing,
               "execution_flexibility": {
                   "inter_anchor_camera_path": "CONTINUOUS_PATH_OPTIMIZABLE; upstream transition path prose is initial execution guidance",
                   "anchor_camera_composition_and_blocking": ("SOFT_REFERENCE_KEEP_RETIME_DROP; preserve canonical actions, blocking and required outcomes independently of optional KF composition"
                       if authority.get("anchor_policy") else "IMMUTABLE_VISUAL_TARGETS; reach the prescribed states at optimized arrivals"),
                   "speaker_visual_hierarchy": "PRIMARY active speaker; SECONDARY/BACKGROUND listeners with canonical presence and spatial continuity",
                   "speaker_readiness": "Face/mouth and camera/composition support acquired BEFORE dialogue starts",
                   "blocking_preservation": "Use camera/composition for readability; preserve canonical seated/standing states and floor positions. No acquisition-driven character reblocking.",
               },
               "native_prompt_contract": {"speaker_bindings": speaker_bindings(authority["dialogue_events"]),
                   "max_characters": MAX_PROMPT_CHARACTERS,
                   "internal_timing_only": True, "visual_acquisition_method": "CAMERA_COMPOSITION_WITH_CANONICAL_BLOCKING"},
               "duration_limits": context.get("duration_limits") or workflow_duration_limits(capability=context.get("capability") or generation_mode),
               "visual_inputs": visual,
               "previous_video_context": {"present": bool(previous),
                   "role": "PREVIOUS_CLIP_CONTINUITY_REFERENCE",
                   "conditioning": "EXISTING_MASKED_AV_TAIL" if previous else None,
                   "context_frames": previous[0].get("context_frames") if previous else None,
                   "independent_of_picture_slots_and_anchor_decisions": True,
                   "frames_are_llm_previews_only": True,
                   "frames": [
                   {key: item.get(key) for key in ["logical_id", "reference_type", "time", "source_video_path", "source_video_sha256", "authority", "proxy_url", "source_frame_index", "context_start_frame", "context_end_frame", "context_frames", "source_fps", "llm_preview_only"]}
                   for item in previous]}, "execution_context": execution_context or {}}
    return runtime, images


def check_authority(raw_prompt, output, authority, initial_timing=None, limits=None):
    """Check immutable facts and execution consistency, without predicting AV quality."""
    from app.services.h3_evidence import resolve_authority
    resolved_authority = resolve_authority(authority, output.get("authority_echo"))
    authority = resolved_authority["authority"]
    prompt = output.get("optimized_prompt") or ""
    timeline = output.get("av_timeline") if isinstance(output.get("av_timeline"), dict) else {}
    initial_timing = initial_timing or {"duration": authority.get("duration"), "dialogue_events": dialogue_events(raw_prompt),
                                        "visual_anchors": anchor_declarations(raw_prompt), "temporal_anchors": []}
    limits = limits or workflow_duration_limits()
    warnings, checks = [], {}
    canonical = authority["dialogue_events"]
    from app.services.h3_evidence import resolve_output_evidence, excerpt
    import copy
    evidence = resolve_output_evidence(prompt, output, authority)
    # A derived audit view only. Never replace model-owned excerpts or final prose.
    resolved_timeline = copy.deepcopy(timeline)
    for i,handoff in enumerate(resolved_timeline.get("handoffs") or []):
        if isinstance(handoff, dict):
            for key in handoff.get("prompt_evidence") or {}:
                handoff["prompt_evidence"][key] = excerpt(evidence, f"handoffs.{i}.{key}")
    native_checks, spoken = check_native_prompt(prompt, canonical, authority, raw_prompt, resolved_timeline)
    checks.update(native_checks)
    original_events = initial_timing["dialogue_events"]
    duration = timeline.get("optimized_duration")
    budget_valid = (_number(duration) and 0 < duration <= 20 and limits["minimum"] <= duration <= limits["maximum"])
    checks["duration_within_workflow_and_20s"] = budget_valid
    original_duration = initial_timing.get("duration")
    checks["duration_original_delta_changed"] = (
        _same(timeline.get("original_duration"), original_duration) and _number(duration)
        and _same(timeline.get("duration_delta"), duration - original_duration)
        and timeline.get("duration_changed") is (abs(duration - original_duration) > EPSILON))
    duration_output = output.get("duration")
    checks["duration_output_matches_timeline"] = duration_output is None or (isinstance(duration_output, dict) and all(
        _same(duration_output.get(key), timeline.get(key)) for key in ("original_duration", "optimized_duration", "duration_delta"))
        and duration_output.get("duration_changed") is timeline.get("duration_changed"))
    checks["prompt_duration_matches_timeline"] = _same(declared_duration(prompt), duration)
    events = timeline.get("dialogue_events")
    events = events if isinstance(events, list) and all(isinstance(e, dict) for e in events) else []
    actual = [{"id": e.get("id"), "speaker": e.get("speaker"),
               "start_time": e.get("optimized_start"), "end_time": e.get("optimized_end")} for e in events]
    checks["dialogue_duration_unchanged"] = len(events) == len(canonical) and all(
        _number(e.get("optimized_start")) and _number(e.get("optimized_end"))
        and _same(e["optimized_end"] - e["optimized_start"], c["duration"]) for e, c in zip(events, canonical))
    checks["dialogue_timeline_matches_prompt_and_initial"] = len(events) == len(canonical) == len(spoken) and all(
        e.get("id") == c["id"] and e.get("speaker") == c["speaker"]
        and _same(e.get("duration"), c["duration"])
        and _same(e.get("original_start"), old["start_time"]) and _same(e.get("original_end"), old["end_time"])
        and a["speaker"] == c["speaker"] and a["exact_dialogue"] == c["exact_dialogue"]
        for e, c, old, a in zip(events, canonical, original_events, spoken))
    event_times_valid = all(_number(e["start_time"]) and _number(e["end_time"]) for e in actual)
    checks["dialogue_inside_budget"] = event_times_valid and budget_valid and all(0 <= e["start_time"] < e["end_time"] <= duration + EPSILON for e in actual)
    checks["dialogue_chronological_order"] = event_times_valid and all(a["start_time"] <= b["start_time"] for a, b in zip(actual, actual[1:]))
    allowed_overlaps = authority.get("allowed_dialogue_overlaps") or []
    checks["no_illegal_dialogue_overlap"] = event_times_valid and all(
        b["start_time"] >= a["end_time"] - EPSILON or [a["id"], b["id"]] in allowed_overlaps
        for i, a in enumerate(actual) for b in actual[i + 1:])
    checks["subject_binding"] = subject_bindings(prompt) == authority["subject_bindings"]
    checks["subject_set"] = set(re.findall(r"<Subject \d+>", prompt)) == set(re.findall(r"<Subject \d+>", raw_prompt))
    checks["invented_picture"] = set(re.findall(r"<Picture \d+>", prompt)) <= {r["picture"] for r in authority["reference_bindings"]}
    checks["picture_presence"] = set(re.findall(r"<Picture \d+>", prompt)) == set(re.findall(r"<Picture \d+>", raw_prompt))
    # The echo remains required audit metadata, but cannot rebind canonical IDs.
    checks["authority_echo_preserved"] = isinstance(output.get("authority_echo"), dict) and bool(output["authority_echo"])
    checks["canonical_manifest_subject_consistent"] = resolved_authority["manifest_subject_consistent"]
    from app.services.h3_continuation import check_continuation_timing
    checks.update(check_continuation_timing(authority.get("continuation"), actual, duration))

    reference_bindings = authority["reference_bindings"]
    if authority.get("anchor_policy"):
        from app.services.h3_anchor_policy import check_anchor_policy
        from app.services.h3_native_prompt import sections
        anchor_checks, reference_bindings = check_anchor_policy(
            prompt, output, authority, spoken, sections(prompt).get("detailed_description", ""), evidence)
        checks.update(anchor_checks)
    else:
        # Historical v4 records remain inspectable under their original contract.
        old_anchors = [{"id": a["id"], "time": a["time"]} for a in initial_timing["visual_anchors"]]
        old_anchors += [{"id": a["anchor_id"], "time": a["time_seconds"]} for a in initial_timing.get("temporal_anchors") or []]
        anchors = timeline.get("anchors")
        anchors = anchors if isinstance(anchors, list) and all(isinstance(a, dict) for a in anchors) else []
        checks["anchor_ids_order_initial_delta"] = len(anchors) == len(old_anchors) and all(
            a.get("id") == old["id"] and _same(a.get("original_time"), old["time"])
            and _number(a.get("optimized_time")) and _same(a.get("delta"), a["optimized_time"] - old["time"])
            and a.get("visual_state_changed") is False and _text(a.get("reason")) for a, old in zip(anchors, old_anchors))
        checks["anchors_inside_budget"] = budget_valid and all(_number(a.get("optimized_time")) and 0 <= a["optimized_time"] <= duration + EPSILON for a in anchors)
        checks["anchor_chronological_order"] = True
        visual_count = len(initial_timing["visual_anchors"])
        for group in (anchors[:visual_count], anchors[visual_count:]):
            checks["anchor_chronological_order"] &= all(_number(a.get("optimized_time")) and _number(b.get("optimized_time")) and a["optimized_time"] < b["optimized_time"] for a, b in zip(group, group[1:]))
        temporal = authority.get("temporal_anchor_order") or []
        # Trace condensed natural anchor prose without claiming Ref2VA frame binding.
        checks["anchor_prompt_rendering"] = len(anchors) == len(old_anchors) and all(
            _text(a.get("prompt_excerpt")) and a["prompt_excerpt"] in prompt for a in anchors)
        checks["visual_anchor_order_target_binding"] = checks["authority_echo_preserved"] and all(
            not fact.get("picture") or fact["picture"] in anchor.get("prompt_excerpt", "")
            for fact, anchor in zip(authority["visual_anchor_order"], anchors[:visual_count]))
        anchor_times = {a.get("id"): a.get("optimized_time") for a in anchors}
        checks["linked_temporal_visual_arrival"] = True
        checks["temporal_target_preserved"] = checks["authority_echo_preserved"]
        for anchor in temporal:
            source = anchor.get("source") or {}
            state = source.get("keyframe_index") or anchor.get("source_state_index")
            alias = f"KF{state}" if state is not None else source.get("id")
            if alias in anchor_times:
                checks["linked_temporal_visual_arrival"] &= _same(anchor_times.get(anchor["anchor_id"]), anchor_times[alias])

    handoffs = timeline.get("handoffs")
    handoffs = handoffs if isinstance(handoffs, list) and all(isinstance(h, dict) for h in handoffs) else []
    expected_handoffs = [(i, a, b) for i, (a, b) in enumerate(zip(actual, actual[1:])) if a["speaker"] != b["speaker"]]
    checks["all_speaker_handoffs_consistent"] = event_times_valid and len(actual) == len(original_events) and len(handoffs) == len(expected_handoffs) and all(
        h.get("from") == a["id"] and h.get("to") == b["id"] and h.get("from_subject") == a["speaker"] and h.get("to_subject") == b["speaker"]
        and _same(h.get("original_gap"), original_events[i + 1]["start_time"] - original_events[i]["end_time"])
        and _same(h.get("optimized_gap"), b["start_time"] - a["end_time"]) and _text(h.get("reason")) and _text(h.get("strategy"))
        for h, (i, a, b) in zip(handoffs, expected_handoffs))
    # Shape only: the LLM reasons about geometry/readiness and chooses all budgets.
    # Historical timelines without this extension remain inspectable; never infer
    # a minimum gap or evaluate camera feasibility from Subject IDs in Python.
    reasoning_fields = ("complexity_reasoning", "spatial_relation", "depth_relation",
                        "camera_strategy", "previous_speaker_release", "next_speaker_readiness")
    new_fields = ("complexity", "visual_handoff_required", "camera_handoff_required", *reasoning_fields)
    checks["handoff_reasoning_schema"] = True
    for handoff in handoffs:
        if not any(key in handoff for key in new_fields):
            warnings.append({"code": "HANDOFF_REASONING_MISSING", "from": handoff.get("from"), "to": handoff.get("to")})
            continue
        checks["handoff_reasoning_schema"] &= (
            handoff.get("complexity") in ("LOW", "MEDIUM", "HIGH")
            and isinstance(handoff.get("visual_handoff_required"), bool)
            and isinstance(handoff.get("camera_handoff_required"), bool)
            and all(_text(handoff.get(key)) for key in reasoning_fields))

    phases = timeline.get("execution_phases")
    phases = phases if isinstance(phases, list) and all(isinstance(p, dict) for p in phases) else []
    checks["execution_phases_inside_budget"] = bool(phases) and budget_valid and all(
        isinstance(p.get("id"), str) and p["id"] and isinstance(p.get("type"), str) and p["type"]
        and _number(p.get("start")) and _number(p.get("end")) and 0 <= p["start"] <= p["end"] <= duration + EPSILON
        and (p["start"] < p["end"] or p["type"] == "ANCHOR_ARRIVAL")
        and isinstance(p.get("description"), str) and bool(p["description"]) for p in phases)
    checks["execution_phase_ids_unique"] = bool(phases) and len({p.get("id") for p in phases}) == len(phases)
    if checks["execution_phases_inside_budget"]:
        covered = 0.0
        for p in sorted(phases, key=lambda p: p["start"]):
            if p["start"] == p["end"]:
                # Legal anchor points neither cover time nor interrupt coverage.
                continue
            if p["start"] > covered + EPSILON:
                break
            covered = max(covered, p["end"])
        checks["execution_budget_explained"] = _same(covered, duration)
    else:
        checks["execution_budget_explained"] = False
    for ref in reference_bindings:
        roles = re.findall(re.escape(ref["picture"]) + r"\s*(?:[—:-]|is)\s*(?:the\s+)?(?:authoritative\s+)?(DIRECTOR_VISUAL_ANCHOR|TEMPORAL_ANCHOR|CHARACTER_IDENTITY|SCENE|PROP)\b", prompt, re.I)
        if roles: checks[f"reference_role_{ref['picture']}"] = all(role.upper() == ref["type"] for role in roles)
        if ref["type"] == "CHARACTER_IDENTITY" and ref["subject"]:
            lines = [line for line in prompt.splitlines() if ref["picture"] in line and re.search(r"(?i)identity|↔|\bbind|\bapply", line)]
            pairs = {subject for line in lines for subject in re.findall(r"<Subject \d+>", line)}
            checks[f"picture_binding_{ref['picture']}"] = pairs == {ref["subject"]}
    for phase_type in ("ATTENTION", "CAMERA", "FINAL_SETTLE"):
        if not any(p.get("type") == phase_type for p in phases):
            warnings.append({"code": "EXECUTION_PHASE_MISSING", "type": phase_type})
    if not re.search(r"(?i)continuous|uninterrupted", prompt) and re.search(r"(?i)continuous", raw_prompt):
        warnings.append({"code": "CONTINUOUS_CAMERA_WORDING_WEAK"})
    blocking = [name for name, passed in checks.items() if not passed]
    if resolved_authority["echo_differences"]:
        warnings.append({"code": "AUTHORITY_ECHO_MISMATCH",
                         "paths": [d["path"] for d in resolved_authority["echo_differences"]],
                         "resolution": "Canonical input and manifest retained; see resolved_authority"})
    warnings.extend({"code": "EVIDENCE_MISMATCH", "path": path,
                     "resolution": evidence["entries"][path]["status"]} for path in evidence["mismatches"])
    if evidence["unresolved"]:
        # Explicitly distinguish unverifiable meaning from a proven story error.
        warnings.append({"code": "EVIDENCE_SEMANTIC_REVIEW_REQUIRED", "paths": evidence["unresolved"]})
    return {"status": "PASS" if not blocking else "FAIL", "passed": not blocking,
            "checks": checks, "blocking_findings": blocking, "warnings": warnings,
            "resolved_evidence": evidence, "resolved_authority": resolved_authority,
            "evidence_provenance": {"status": "EVIDENCE_MISMATCH" if evidence["mismatches"] else "EXACT",
                                    "mismatches": evidence["mismatches"], "unresolved": evidence["unresolved"]},
            "semantic_consistency": {"status": "REVIEW_REQUIRED" if evidence["unresolved"] else ("PASS" if not blocking else "FAIL"),
                                     "scope": "Existing dialogue/identity/binding/order checks and located requirement text; arbitrary action meaning requires semantic preflight."},
            "scope": "immutable textual facts, AV execution consistency and local handoff evidence provenance; acquisition meaning requires semantic preflight, actual voice/lip/camera quality requires video review"}


async def optimize_h3_execution_prompt(db, novel, shot, raw_prompt, generation_mode, clip,
                                      reference_manifest=None, reference_images=None, temporal_anchors=None,
                                      previous_video_path=None, execution_context=None, reuse_record=None):
    record = {"version": VERSION, "clip_index": clip.get("clip_index"), "status": "FALLBACK", "raw_prompt": raw_prompt,
              "optimized_prompt": None, "selected_prompt_source": "RAW", "duration_applied": False,
              "timing_applied": False, "raw_prompt_sha256": hashlib.sha256(raw_prompt.encode()).hexdigest()}
    template = None
    result = {}
    try:
        template = resolve_prompt_template(db, novel, "h3_execution_optimizer_prompt_template_id", TEMPLATE_TYPE)
        if template.type != TEMPLATE_TYPE:
            raise ValueError("#14 所选模板类型不匹配")
        runtime, images = await asyncio.to_thread(build_runtime_input, raw_prompt, generation_mode, clip,
                                                  reference_manifest, reference_images, temporal_anchors,
                                                  previous_video_path, execution_context)
        record.update(runtime_input=runtime, prompt_template_id=template.id, prompt_template_name=template.name,
                      system_prompt_sha256=hashlib.sha256(template.template.encode()).hexdigest(), image_count=len(images))
        record["original_duration"] = runtime["clip"]["duration"]
        if not images and runtime["visual_inputs"]:
            raise ValueError("VISION_INPUT_UNAVAILABLE: 不允许静默丢弃图片")
        previous_runtime = (reuse_record or {}).get("runtime_input") or {}
        can_reuse = (reuse_record and reuse_record.get("version") == VERSION and reuse_record.get("status") == "OPTIMIZED"
                     and reuse_record.get("raw_prompt_sha256") == record["raw_prompt_sha256"]
                     and reuse_record.get("system_prompt_sha256") == record["system_prompt_sha256"]
                     and all(previous_runtime.get(key) == runtime.get(key) for key in (
                         "immutable_authority", "initial_execution_timing", "visual_inputs", "previous_video_context", "duration_limits",
                         "execution_flexibility", "execution_context", "native_prompt_contract")))
        if can_reuse:
            record["reused_result"] = True
            result = {"success": True, "content": json.dumps(reuse_record["output"], ensure_ascii=False),
                      "log_id": reuse_record.get("llm_log_id"), "raw_response": reuse_record.get("raw_llm_response")}
        else:
            result = await LLMService().chat_completion(
                system_prompt=template.template, user_content=json.dumps(runtime, ensure_ascii=False, indent=2),
                images=images, response_format="json_object", task_type=TEMPLATE_TYPE,
                prompt_template_name=template.name, novel_id=novel.id, chapter_id=shot.chapter_id,
            )
        record.update(llm_log_id=result.get("log_id"), raw_llm_response=result.get("raw_response"),
                      raw_response_content=result.get("content") or "")
        if not result.get("success"):
            if re.search(r"(?i)vision.*unsupported|unsupported.*(?:image|vision)|(?:image|vision).*not support|does not support.*image", str(result.get("error"))):
                record["capability_error"] = "VISION_CAPABILITY_UNAVAILABLE"
            raise RuntimeError("#14 含图片请求失败；请检查模型 vision 能力与调用日志：" + str(result.get("error")))
        parsed = safe_parse_llm_json(result.get("content") or "", default=None)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("optimized_prompt"), str) or not parsed["optimized_prompt"].strip():
            raise ValueError("#14 structured response 缺少 optimized_prompt")
        audit = check_authority(raw_prompt, parsed, runtime["immutable_authority"], runtime["initial_execution_timing"], runtime["duration_limits"])
        record.update(output=parsed, optimized_prompt=parsed["optimized_prompt"], authority_check=audit,
                      resolved_evidence=audit["resolved_evidence"], resolved_authority=audit["resolved_authority"])
        if not audit["passed"]:
            raise ValueError("#14 canonical authority 不通过：" + ", ".join(audit["blocking_findings"]))
        if runtime["immutable_authority"].get("anchor_policy"):
            from app.services.h3_anchor_policy import project_reference_manifest
            source_manifest = reference_manifest or {"references": [
                {"slot": i, "kind": "DIRECTOR_VISUAL_ANCHOR", "image_url": r.get("url")}
                for i, r in enumerate(reference_images or [], 1)]}
            record["execution_reference_manifest"] = project_reference_manifest(source_manifest, runtime["immutable_authority"], parsed)
        timeline = parsed["av_timeline"]
        reason = (parsed.get("duration") or {}).get("reason") or timeline.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("#14 structured response 缺少执行时长理由")
        parsed["duration"] = {key: timeline[key] for key in ("original_duration", "optimized_duration", "duration_delta", "duration_changed")}
        parsed["duration"].update(reason=reason, original=timeline["original_duration"], recommended=timeline["optimized_duration"])
        for key in ("risks", "changes", "timing_recommendations"):
            parsed.setdefault(key, [])
            if not isinstance(parsed[key], list):
                raise ValueError(f"#14 structured response {key} 必须是数组")
        events = runtime["immutable_authority"]["dialogue_events"]
        parsed["complexity"] = {"level": "unknown", **(parsed.get("complexity") or {}),
            "subjects": len(runtime["immutable_authority"]["subject_bindings"]),
            "active_speakers": len({e["speaker"] for e in events}), "dialogue_events": len(events),
            "speaker_switches": sum(a["speaker"] != b["speaker"] for a, b in zip(events, events[1:])),
            "visual_anchors": len(runtime["immutable_authority"]["visual_anchor_order"]) + len(runtime["immutable_authority"]["temporal_anchor_order"])}
        record.update(status="OPTIMIZED", selected_prompt_source="OPTIMIZED",
                      duration_applied=True, timing_applied=True)
        record.update(effective_execution_duration(runtime["clip"]["duration"], record, runtime["duration_limits"]))
        if temporal_anchors:
            retime_temporal_manifest({"anchors": temporal_anchors}, record)
    except LLMCallTerminated:
        raise
    except Exception as error:
        record.update(status="FALLBACK", selected_prompt_source="RAW", duration_applied=False, timing_applied=False,
                      optimized_duration=None, effective_duration=record.get("original_duration") or clip.get("planned_duration") or clip.get("duration"), duration_source="ORIGINAL")
        record["error"] = str(error)
    append_video_ai_call(shot, {"step": "14", "title": "MiniMax H3 执行提示词优化", "task_type": TEMPLATE_TYPE,
                               "prompt_template_name": template.name if template else None,
                               "status": "success" if record["status"] == "OPTIMIZED" else "error",
                               "error_message": record.get("error"), "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} #14",
                               "response": result.get("content") or result.get("error"), "parsed_result": record,
                               "final_prompt": record["optimized_prompt"] if record["status"] == "OPTIMIZED" else raw_prompt,
                               "clip_index": clip.get("clip_index")})
    db.commit()
    return (record["optimized_prompt"] if record["status"] == "OPTIMIZED" else raw_prompt), record
