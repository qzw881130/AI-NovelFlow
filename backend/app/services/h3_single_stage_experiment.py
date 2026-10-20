"""Opt-in #11/#12/#13 H3-native preview; never submits or replaces #14."""

import json
import math
import re
from copy import deepcopy
from pathlib import Path

from app.services.h3_continuation import check_continuation_timing
from app.services.h3_execution_optimizer import (
    _identity_picture_subjects, subject_bindings as parsed_subject_bindings,
    workflow_duration_limits,
)
from app.services.h3_native_prompt import (
    check_native_prompt, compile_dialogue_time_cues, declared_duration,
    dialogue_events, sections, speaker_bindings, SECTIONS,
)
from app.services.vision_inputs import previous_video_frames, vision_proxy
from app.services.video_director_ai import (
    _exact_spoken_text, audit_physical_picture_references,
)


EXPERIMENT_TEMPLATE = Path(__file__).resolve().parents[2] / "prompt_templates/H3_SingleStage_Experiment_V1.txt"
DIRECTOR_ONLY_TEMPLATE = Path(__file__).resolve().parents[2] / "prompt_templates/H3_Director_Only_Experiment_V1.txt"
STRUCTURAL_CHECKS = (
    "h3_native_six_sections", "compact_final_prompt", "native_dialogue_markup",
    "dialogue_ids_speakers_text_order", "stable_speaker_ids", "no_silent_speaker_ids",
    "chinese_dialogue_language_marker", "dialogue_time_cues",
    "chinese_marker_count", "exact_dialogue_occurrence_count",
)
NARRATOR_TOKEN = "<Narrator>"


def _speaker_subject(name, subject_for_name):
    """Narration is audio-only and must never acquire a visual Subject binding."""
    if name == "旁白":
        return NARRATOR_TOKEN
    return subject_for_name.get(name)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _verified_timing(assigned, subject_for_name, supplied, continuation, capability):
    if not isinstance(supplied, dict) or not _finite(supplied.get("optimized_duration")):
        raise ValueError("H3_SINGLE_STAGE_VERIFIED_TIMING_REQUIRED")
    duration = float(supplied["optimized_duration"])
    limits = workflow_duration_limits(capability=capability)
    if not limits["minimum"] <= duration <= min(limits["maximum"], 20):
        raise ValueError("H3_SINGLE_STAGE_DURATION_OUT_OF_BOUNDS")
    provided = supplied.get("dialogue_events")
    if not isinstance(provided, list) or len(provided) != len(assigned):
        raise ValueError("H3_SINGLE_STAGE_DIALOGUE_TIMING_MISMATCH")
    canonical, events = [], []
    previous_end = 0.0
    for source, event in zip(assigned, provided):
        subject = _speaker_subject(source["speaker"], subject_for_name)
        if not subject or not isinstance(event, dict):
            raise ValueError("H3_SINGLE_STAGE_DIALOGUE_BINDING_MISMATCH")
        start, end = event.get("optimized_start"), event.get("optimized_end")
        if (event.get("id") != source["id"] or event.get("speaker") != subject
                or not _finite(start) or not _finite(end)
                or not previous_end <= start < end <= duration + 1e-6
                or abs((end - start) - float(source["duration"])) > 0.011):
            raise ValueError("H3_SINGLE_STAGE_DIALOGUE_TIMING_MISMATCH")
        text = _exact_spoken_text(source["text"])
        canonical.append({"id": source["id"], "speaker": subject,
                          "exact_dialogue": text, "duration": float(source["duration"])})
        events.append({"id": source["id"], "speaker": subject,
                       "optimized_start": float(start), "optimized_end": float(end)})
        previous_end = end
    continuation_checks = check_continuation_timing(
        continuation,
        [{"start_time": e["optimized_start"], "end_time": e["optimized_end"]} for e in events],
        duration,
    )
    if not all(continuation_checks.values()):
        raise ValueError("H3_SINGLE_STAGE_CONTINUATION_TIMING_INVALID")
    return {"optimized_duration": duration, "dialogue_events": events}, canonical, continuation_checks


def _visual_previews(manifest, temporal_anchors, previous_video_path, continuation):
    images, visual = [], []
    for index, ref in enumerate((manifest or {}).get("references") or [], 1):
        if ref.get("slot") != index:
            raise ValueError("H3_SINGLE_STAGE_MANIFEST_NOT_DENSE")
        source = ref.get("local_path") or ref.get("image_url")
        if not source:
            raise ValueError("H3_SINGLE_STAGE_REFERENCE_IMAGE_MISSING")
        item = vision_proxy(source, logical_id=f"<Picture {index}>", name=f"<Picture {index}>",
                            reference_type=ref.get("kind"), role=ref.get("source_role"),
                            binding=ref.get("source_name"), source_asset_id=ref.get("source_id"))
        images.append(item)
        visual.append({"id": item["logical_id"], "source_sha256": item["source_sha256"],
                       "proxy_url": item["proxy_url"], "type": ref.get("kind")})
    for anchor in temporal_anchors:
        source = anchor.get("local_path") or anchor.get("image_url")
        if not source:
            raise ValueError("H3_SINGLE_STAGE_TEMPORAL_PREVIEW_MISSING")
        item = vision_proxy(source, logical_id=f"TemporalAnchor:{anchor['anchor_id']}",
                            name=f"TemporalAnchor:{anchor['anchor_id']}",
                            reference_type="TEMPORAL_ANCHOR", role="timed_visual_target",
                            binding=anchor.get("source"), time=anchor.get("time_seconds"))
        images.append(item)
        visual.append({"id": item["logical_id"], "source_sha256": item["source_sha256"],
                       "proxy_url": item["proxy_url"], "type": "TEMPORAL_ANCHOR"})
    previous = previous_video_frames(previous_video_path, continuation["context_frames"]) if continuation else []
    if continuation and (not previous or any(
            item.get("source_video_sha256") != continuation.get("source_sha256") for item in previous)):
        raise ValueError("H3_SINGLE_STAGE_PREVIOUS_AV_PREVIEW_MISMATCH")
    images.extend(previous)
    visual.extend({"id": item["logical_id"], "source_sha256": item["source_sha256"],
                   "proxy_url": item["proxy_url"], "type": "PREVIOUS_VIDEO_FRAME"} for item in previous)
    return images, visual


def _assemble(model_text, canonical, timing, subject_names, picture_mapping, continuation):
    if not sections(model_text) or "<d>" in model_text or "</d>" in model_text:
        raise ValueError("H3_SINGLE_STAGE_SIX_SECTIONS_INVALID")
    ids = [event["id"] for event in canonical]
    if re.findall(r"\[\[(D\d+)\]\]", model_text) != ids or re.search(r"\bD\d+\b", re.sub(r"\[\[D\d+\]\]", "", model_text)):
        raise ValueError("H3_SINGLE_STAGE_DIALOGUE_SLOTS_INVALID")
    if any(event["exact_dialogue"] in model_text for event in canonical):
        raise ValueError("H3_SINGLE_STAGE_DIALOGUE_TEXT_REDEFINED")
    definitions = sections(model_text)["subject_definitions"]
    for subject, name in subject_names.items():
        if not re.search(r"(?m)^" + re.escape(subject) + r"\s+is\s+" + re.escape(name) + r"(?=[,，\s.;。]|$)", definitions):
            raise ValueError("H3_SINGLE_STAGE_SUBJECT_DEFINITION_MISMATCH")
    voices = speaker_bindings(canonical)
    prompt = model_text
    for event in canonical:
        subject = event["speaker"]
        language = "[Chinese] " if re.search(r"[\u3400-\u9fff]", event["exact_dialogue"]) else ""
        verb = "narrates in voice-over" if subject == NARRATOR_TOKEN else "says"
        utterance = f"{subject} ({voices[subject]}) {verb}, <d>{language}{event['exact_dialogue']}</d>"
        prompt = prompt.replace(f"[[{event['id']}]]", utterance, 1)
    prompt = compile_dialogue_time_cues(prompt, canonical, timing)
    native, _ = check_native_prompt(
        prompt, canonical,
        {"subject_bindings": subject_names, "reference_bindings": [], "continuation": continuation},
        "", {"dialogue_events": timing["dialogue_events"], "handoffs": []},
        require_time_cues=bool(canonical),
    )
    required = {name: (True if name == "dialogue_time_cues" and not canonical else native.get(name))
                for name in STRUCTURAL_CHECKS}
    required["declared_duration"] = declared_duration(prompt) is not None and abs(
        declared_duration(prompt) - timing["optimized_duration"]) <= 1e-6
    picture = audit_physical_picture_references(prompt, picture_mapping)
    required["physical_picture_mapping"] = picture["passed"]
    required["all_manifest_pictures_present"] = all(
        f"<Picture {item['picture_index']}>" in prompt for item in picture_mapping)
    for item in picture_mapping:
        if item.get("kind") != "CHARACTER_IDENTITY":
            continue
        name = item.get("source_name")
        subject = next((key for key, value in subject_names.items() if value == name), None)
        required[f"identity_picture_{item['picture_index']}"] = (
            subject is not None and _identity_picture_subjects(
                prompt, f"<Picture {item['picture_index']}>") == {subject})
    if not all(required.values()):
        raise ValueError("H3_SINGLE_STAGE_PREFLIGHT_FAILED: " + ",".join(
            name for name, passed in required.items() if not passed))
    if [(e["speaker"], e["exact_dialogue"]) for e in dialogue_events(prompt)] != [
            (e["speaker"], e["exact_dialogue"]) for e in canonical]:
        raise ValueError("H3_SINGLE_STAGE_DIALOGUE_BINDING_MISMATCH")
    return prompt, {**required, "continuation": True}, picture


def _director_sections(model_text):
    """The experimental LLM owns only prose and speech placement, not H3 facts."""
    headings = list(re.finditer(r"(?m)^([a-z_]+):[ \t]*$", model_text))
    if ([match[1] for match in headings] != ["detailed_description", "overall_soundscape"]
            or model_text[:headings[0].start()].strip()):
        raise ValueError("H3_SINGLE_STAGE_DIRECTOR_SECTIONS_INVALID")
    result = {match[1]: model_text[match.end():headings[i + 1].start()
              if i + 1 < len(headings) else len(model_text)].strip()
              for i, match in enumerate(headings)}
    if not all(result.values()):
        raise ValueError("H3_SINGLE_STAGE_DIRECTOR_SECTIONS_INVALID")
    return result


def _stable_identity_marks(appearance):
    """Quote the existing explicit identity clause, excluding portrait outfits."""
    if not isinstance(appearance, str):
        return None
    # Character records use both "稳定身份标记包括/为" and "稳定识别特征是".
    # Stop at the clause boundary so the portrait's outfit is never quoted
    # as a permanent identity feature.
    match = re.search(r"(?:稳定身份标记(?:包括|为)|稳定识别特征是)\s*([^；。\n]+)[；。]", appearance)
    return match.group(1).strip(" ，,") if match and match.group(1).strip(" ，,") else None


def _identity_features(name, appearances, structured):
    """Prefer frozen structured facts; parse prose only for old snapshots."""
    if isinstance(structured, dict) and name in structured:
        return structured[name] or None
    return _stable_identity_marks(appearances.get(name))


def _frozen_anchor_execution_notes(frozen, timing, picture_mapping, continuation, *, prompt_language=None):
    """Serialize validated experiment decisions; never retime or direct actions."""
    if frozen is None:
        return []
    if frozen["timing"] != timing:
        raise ValueError("H3_PHASE_A_FROZEN_TIMING_MISMATCH")
    choices = frozen["anchor_decisions"]
    if not choices and not continuation:
        return []  # The existing GENERATE candidate remains byte-identical.
    catalog = {item["anchor_id"]: item for item in frozen["anchor_catalog"]}
    pictures = {f"KF{item['source_keyframe_index']}": f"<Picture {item['picture_index']}>"
                for item in picture_mapping if item.get("kind") == "DIRECTOR_VISUAL_ANCHOR"
                and item.get("source_keyframe_index") is not None}
    dialogues = {event["id"]: event for event in timing["dialogue_events"]}
    owner = "Director-selected" if frozen.get("decision_owner") == "NEW_13_PHASE_B" else "Frozen"
    notes = [f"{owner} Anchor arrivals use GENERATION_LOCAL_SECONDS: generated-fragment time starts at 0s, including any verified Previous AV shared prefix."]
    if prompt_language == "zh":
        notes = ["Anchor 到达时间使用 GENERATION_LOCAL_SECONDS：生成片段从 0s 开始，包含经验证的 Previous AV 共享前缀。"]
    if continuation:
        notes.append(
            f"Previous AV shared prefix: 0–{continuation['overlap_seconds']}s in GENERATION_LOCAL_SECONDS, "
            f"already included in the {timing['optimized_duration']}s generation duration. "
            "Do not add overlap again or replay actions completed in Previous AV.")
        if prompt_language == "zh":
            notes[-1] = (f"Previous AV 共享前缀：GENERATION_LOCAL_SECONDS 的 0–{continuation['overlap_seconds']}s，"
                         f"已包含在 {timing['optimized_duration']}s 生成时长内。不得重复叠加共享时长或重演已完成的动作。")
    dropped = []
    for choice in choices:
        anchor = choice["id"]
        item = catalog[anchor]
        if choice["decision"] == "DROP":
            dropped.append(anchor)
            continue
        arrival = choice["optimized_time"]
        if (choice["decision"] not in {"KEEP", "RETIME"}
                or choice.get("optimized_time_base") != "GENERATION_LOCAL_SECONDS"
                or not _finite(arrival) or isinstance(arrival, bool)
                or not 0 <= arrival <= timing["optimized_duration"]):
            raise ValueError("H3_PHASE_A_FROZEN_ARRIVAL_UNVERIFIED: " + anchor)
        picture = pictures.get(item.get("linked_anchor_id") or anchor)
        label = anchor + (f" ({picture})" if picture else "")
        line = f"{label}: reach its Canonical visual target at {arrival}s in GENERATION_LOCAL_SECONDS"
        if prompt_language == "zh":
            line = f"{label}：在 GENERATION_LOCAL_SECONDS 的 {arrival}s 达到对应 Canonical 视觉目标"
        relation = choice.get("arrival_relation")
        if relation:
            event = dialogues[relation["dialogue_id"]]
            position = relation["position"]
            start, end = event["optimized_start"], event["optimized_end"]
            if position == "BEFORE" and arrival <= start:
                boundary = f"starts at {start}s"
            elif position == "AFTER" and arrival >= end:
                boundary = f"ends at {end}s"
            elif position == "DURING" and start <= arrival <= end:
                boundary = f"{start}–{end}s"
            else:
                raise ValueError("H3_PHASE_A_FROZEN_ARRIVAL_RELATION_INVALID: " + anchor)
            line += f"; {position} {event['id']} ({boundary})"
            if prompt_language == "zh":
                line = (f"{label}：在 GENERATION_LOCAL_SECONDS 的 {arrival}s 达到对应 Canonical 视觉目标；"
                        f"{position} {event['id']}（对白窗口 {start}–{end}s）")
        notes.append(line + ".")
    if dropped:
        notes.append(
            f"{', '.join(dropped)}: no reference-image arrival constraint; "
            "their Canonical actions and state outcomes remain required.")
        if prompt_language == "zh":
            notes[-1] = f"{', '.join(dropped)}：不设置参考图到达约束，仍须完成对应 Canonical 动作与状态结果。"
    return notes


def assemble_authority_owned_candidate(model_text, canonical, timing, subject_names,
                                       picture_mapping, continuation, verified_music,
                                       *, director_only=False, character_appearances=None,
                                       character_stable_features=None,
                                       frozen_execution=None, execution_decisions=None,
                                       prompt_language=None, localized_descriptions=None,
                                       canonical_source_names=()):
    """Offline-only six-section candidate; the model's director prose is not repaired.

    The caller supplies already verified Dialogue timing and the selected physical
    Picture manifest. This function neither selects anchors nor approves generation.
    """
    model_parts = _director_sections(model_text) if director_only else sections(model_text)
    if not model_parts or "<d>" in model_text or "</d>" in model_text:
        raise ValueError("H3_SINGLE_STAGE_SIX_SECTIONS_INVALID")
    ids = [event["id"] for event in canonical]
    detail = model_parts["detailed_description"]
    phase_b = (execution_decisions is not None
               and execution_decisions.get("decision_owner") == "NEW_13_PHASE_B")
    reference_text = model_text
    if director_only and phase_b:
        # Phase B may refer to the upstream identity map, but never owns it.
        # Remove only validated tags from the numbering guard, not from prose.
        subjects = re.findall(r"<Subject\s+[^>]+>", model_text)
        if any(subject not in subject_names for subject in subjects):
            raise ValueError("H3_PHASE_B_UNDEFINED_SUBJECT_REFERENCE")
        reference_text = re.sub(r"<Subject \d+>", "", model_text)
    expected_slots = [f"SPEECH_{i}" for i in range(1, len(canonical) + 1)] if director_only else ids
    slots = re.findall(r"\[\[([A-Z]+(?:_\d+|\d+))\]\]", detail)
    if (slots != expected_slots or model_text.count("[[") != len(expected_slots)
            or re.search(r"\bD\d+\b", re.sub(r"\[\[D\d+\]\]", "", model_text))
            or any(event["exact_dialogue"] in model_text for event in canonical)
            or (director_only and re.search(
                r"<?(?:Subject|Picture)\s+\d+>?|\bS\d+\b", reference_text))):
        raise ValueError("H3_SINGLE_STAGE_DIALOGUE_SLOTS_INVALID")
    if not isinstance(picture_mapping, list) or [item.get("picture_index") for item in picture_mapping] != list(range(1, len(picture_mapping) + 1)):
        raise ValueError("H3_SINGLE_STAGE_MANIFEST_NOT_DENSE")
    if not _finite(timing.get("optimized_duration")) or timing["optimized_duration"] <= 0:
        raise ValueError("H3_SINGLE_STAGE_VERIFIED_TIMING_REQUIRED")
    if verified_music != "N/A":
        raise ValueError("H3_SINGLE_STAGE_MUSIC_AUTHORITY_UNVERIFIED")
    if continuation and (continuation.get("binding_verified") is not True
                         or continuation.get("mode") != "VIDEO_CONTINUATION"
                         or not _finite(continuation.get("overlap_seconds"))
                         or not 0 < continuation["overlap_seconds"] < timing["optimized_duration"]):
        raise ValueError("H3_SINGLE_STAGE_CONTINUATION_UNVERIFIED")

    pictures_by_name = {}
    for item in picture_mapping:
        if item.get("kind") == "CHARACTER_IDENTITY":
            pictures_by_name.setdefault(item.get("source_name"), []).append(item["picture_index"])
    if any((len(pictures_by_name.get(name, [])) > 1 if phase_b
            else len(pictures_by_name.get(name, [])) != 1)
           for name in subject_names.values()):
        raise ValueError("H3_SINGLE_STAGE_IDENTITY_PICTURE_BINDING_UNRESOLVED")

    from app.services import h3_prompt_rendering as render
    appearances = character_appearances if isinstance(character_appearances, dict) else {}
    structured_features = character_stable_features if isinstance(character_stable_features, dict) else {}
    localized = localized_descriptions or {}
    definitions = []
    identity_sources = {}
    for subject, name in subject_names.items():
        number = (pictures_by_name.get(name) or [None])[0]
        marks = _identity_features(name, appearances, structured_features)
        identity_sources[subject] = (
            ("Character.stable_identity_features" if name in structured_features else
             "Character.appearance explicit stable-identity clause" if number is not None else
             "Character.appearance text-only stable-identity clause")
            if marks else "IMAGE_ONLY_IDENTITY" if number is not None else
            "MISSING_IDENTITY_SOURCE")
        marks = localized.get("identity:" + subject, marks)
        definitions.append(render.identity_definition(subject, name, number, marks, prompt_language))
    if not definitions:
        definitions.append(render.no_bound_subjects(prompt_language))
    retention = [render.retention_intro(continuation, prompt_language)]
    subjects_for_name = {name: subject for subject, name in subject_names.items()}
    for item in picture_mapping:
        picture = f"<Picture {item['picture_index']}>"
        kind, name = item.get("kind"), item.get("source_name")
        if kind == "CHARACTER_IDENTITY":
            label = subjects_for_name[name] if phase_b else f"{subjects_for_name[name]} ({name})"
        elif kind in {"SCENE", "PROP"}:
            label = localized.get(f"{kind}:{name}", name)
        elif kind == "DIRECTOR_VISUAL_ANCHOR":
            label = (f"KF{item['source_keyframe_index']}" if item.get("source_keyframe_index") is not None
                     else "选定视觉状态" if prompt_language == "zh" else "selected visual state")
        else:
            raise ValueError("H3_SINGLE_STAGE_PICTURE_KIND_UNSUPPORTED")
        retention.append(render.reference_note(picture, kind, label, prompt_language))

    if frozen_execution is not None and execution_decisions is not None:
        raise ValueError("H3_EXPERIMENT_EXECUTION_OWNER_AMBIGUOUS")
    silent_phase_b = not canonical and phase_b
    if silent_phase_b:
        # Absence of Canonical speech is a fact, not a new director action.
        # Retain source audio in a physical shared prefix; never mute/rewrite it.
        retention.append(render.silent_note(continuation, prompt_language))
    execution_notes = _frozen_anchor_execution_notes(
        frozen_execution if frozen_execution is not None else execution_decisions,
        timing, picture_mapping, continuation, prompt_language=prompt_language)
    duration = float(timing["optimized_duration"])
    parts = {
        "subject_definitions": "\n".join(definitions),
        "summary": render.summary(duration, continuation, prompt_language),
        "retention_analysis": "\n".join(retention),
        "detailed_description": detail,
        "overall_soundscape": model_parts["overall_soundscape"],
        "non_diegetic_music": verified_music,
    }
    prompt = "\n\n".join(f"{heading}:\n{parts[heading]}" for heading in SECTIONS)
    if prompt_language == "en":
        from app.services.h3_prompt_language import validate_english_prose
        validate_english_prose(prompt, (*subject_names.values(), *canonical_source_names))
    voices = speaker_bindings(canonical)
    for index, event in enumerate(canonical, 1):
        subject = event["speaker"]
        language = "[Chinese] " if re.search(r"[\u3400-\u9fff]", event["exact_dialogue"]) else ""
        verb = "narrates in voice-over" if subject == NARRATOR_TOKEN else "says"
        utterance = f"{subject} ({voices[subject]}) {verb}, <d>{language}{event['exact_dialogue']}</d>"
        slot = f"[[SPEECH_{index}]]" if director_only else f"[[{event['id']}]]"
        prompt = prompt.replace(slot, utterance, 1)
    prompt = compile_dialogue_time_cues(prompt, canonical, timing)
    cue_prompt = prompt
    if execution_notes:
        # Dialogue injection operates only on speech IDs; add their Anchor
        # cross-references afterwards, still before all final-prompt checks.
        compiled_parts = sections(prompt)
        compiled_parts["retention_analysis"] += "\n" + "\n".join(execution_notes)
        prompt = "\n\n".join(f"{heading}:\n{compiled_parts[heading]}" for heading in SECTIONS)
    native, _ = check_native_prompt(
        prompt, canonical, {"subject_bindings": subject_names, "reference_bindings": [],
                            "continuation": continuation}, "",
        {"dialogue_events": timing["dialogue_events"], "handoffs": []},
        require_time_cues=bool(canonical) or silent_phase_b,
    )
    structure = {name: bool(native.get(name)) for name in STRUCTURAL_CHECKS}
    if execution_notes:
        # The legacy cue check counts every D-ID in all six sections. Frozen
        # BEFORE/AFTER references are not additional utterances. Scope only this
        # check to the original sections without our exact compiler-owned notes;
        # keep full-prompt diagnostics and all other final checks unchanged.
        cue_checks, _ = check_native_prompt(
            cue_prompt, canonical, {"subject_bindings": subject_names, "reference_bindings": [],
                                    "continuation": continuation}, "",
            {"dialogue_events": timing["dialogue_events"], "handoffs": []},
            require_time_cues=bool(canonical) or silent_phase_b)
        structure["dialogue_time_cues"] = cue_checks["dialogue_time_cues"]
    structure["declared_duration"] = declared_duration(prompt) == duration
    picture = audit_physical_picture_references(prompt, picture_mapping)
    facts = {
        "canonical_dialogue_exact": [(e["speaker"], e["exact_dialogue"]) for e in dialogue_events(prompt)]
            == [(e["speaker"], e["exact_dialogue"]) for e in canonical],
        "subject_names_exact": parsed_subject_bindings(prompt) == subject_names,
        "no_unauthorized_subject": set(re.findall(r"<Subject \d+>", prompt)) == set(subject_names),
        "dialogue_windows_exact": len(timing["dialogue_events"]) == len(canonical) and all(
            event.get("id") == source["id"] and event.get("speaker") == source["speaker"]
            and _finite(event.get("optimized_start")) and _finite(event.get("optimized_end"))
            and 0 <= event["optimized_start"] < event["optimized_end"] <= duration
            and abs(event["optimized_end"] - event["optimized_start"] - source["duration"]) <= 0.011
            for event, source in zip(timing["dialogue_events"], canonical)),
        "physical_picture_mapping": picture["passed"],
        "all_manifest_pictures_present": all(
            f"<Picture {item['picture_index']}>" in prompt for item in picture_mapping),
        "identity_picture_binding": all(_identity_picture_subjects(
            prompt, f"<Picture {pictures_by_name[name][0]}>") == {subject}
            for subject, name in subject_names.items() if pictures_by_name.get(name)),
        "continuation_timing": not continuation or all(check_continuation_timing(
            continuation,
            [{"start_time": e["optimized_start"], "end_time": e["optimized_end"]}
             for e in timing["dialogue_events"]], duration).values()),
    }
    review = {
        "llm_output_mode": "DIRECTOR_ONLY" if director_only else "SIX_SECTION",
        "structure": structure,
        "structured_authority": facts,
        "native_prompt_diagnostics": native,
        "compiler_owned_execution_notes": execution_notes,
        "verified_overlap_seconds": continuation["overlap_seconds"] if continuation else None,
        "stable_identity_sources": identity_sources,
        "stable_identity_features": "REVIEW_REQUIRED: explicit recorded identity clauses are quoted where available; visual match is not certified",
        "current_costume_match": "REVIEW_REQUIRED: Previous AV is the source, visual match is not certified",
        "canonical_action_coverage": "REVIEW_REQUIRED: original director prose was not completed or repaired",
        "speaker_visual_handoff": "REVIEW_REQUIRED: no camera or listener action was inserted",
        "soundscape_authority": "REVIEW_REQUIRED: original model Foley prose was preserved",
        "submission_authorized": False,
    }
    return prompt, review, picture


async def preview_single_stage_h3(*, payload, route, template_type, novel_id, chapter_id,
                                  assigned_dialogues, visible_characters, picture_mapping,
                                  reference_manifest, temporal_anchors, experiment, llm, shot_id=None):
    """One #11/#12/#13 call and deterministic assembly; returns an isolated preview."""
    if route not in {"single", "endpoint", "multi"}:
        raise ValueError("H3_SINGLE_STAGE_ROUTE_INVALID")
    capability = str(payload["clip"].get("capability") or "GENERATE")
    continuation = experiment.get("verified_continuation")
    previous_path = experiment.get("previous_video_path")
    is_extend = capability in {"EXTEND", "TEMPORAL_EXTEND", "VIDEO_CONTINUATION"}
    if is_extend != bool(continuation) or is_extend != bool(previous_path):
        raise ValueError("H3_SINGLE_STAGE_CONTINUATION_REQUIRED")
    if continuation and (continuation.get("binding_verified") is not True
                         or continuation.get("mode") != "VIDEO_CONTINUATION"):
        raise ValueError("H3_SINGLE_STAGE_CONTINUATION_UNVERIFIED")
    subject_for_name = {name: f"<Subject {i}>" for i, name in enumerate(visible_characters, 1)}
    timing, canonical, continuation_checks = _verified_timing(
        assigned_dialogues, subject_for_name, experiment.get("verified_timing"), continuation, capability)
    images, visual = _visual_previews(reference_manifest, temporal_anchors, previous_path, continuation)
    manifest = deepcopy(reference_manifest or {"references": []})
    if len(picture_mapping) != len(manifest.get("references") or []):
        raise ValueError("H3_SINGLE_STAGE_MANIFEST_MAPPING_MISMATCH")
    anchored = bool(temporal_anchors or any(
        ref.get("kind") == "DIRECTOR_VISUAL_ANCHOR" for ref in manifest.get("references") or []))
    prior_selection = bool(manifest.get("excluded_references"))
    input_payload = {**payload,
        "single_stage_experiment": {
            "route": route, "execution_timing_source": "VERIFIED_EXTERNAL_BUDGET_NOT_PLANNED_BY_11_12_13",
            "verified_generation_duration": timing["optimized_duration"],
            "verified_dialogue_events": timing["dialogue_events"],
            "subject_speaker_bindings": subject_for_name,
            "speaker_ids": speaker_bindings(canonical),
            "picture_manifest": [{key: ref.get(key) for key in (
                "slot", "kind", "source_id", "source_name", "source_keyframe_index", "source_role")}
                for ref in manifest.get("references") or []],
            "visual_previews": visual,
            "previous_av": {"present": bool(continuation),
                            "overlap_seconds": continuation.get("overlap_seconds") if continuation else None,
                            "context_frames": continuation.get("context_frames") if continuation else None,
                            "time_origin": continuation.get("clip_local_time_origin") if continuation else None},
            "anchor_selection": ("NOT_COVERED_INPUT_ALREADY_PROJECTED" if prior_selection else
                                 "NOT_COVERED_KEEP_SUPPLIED_REFERENCES" if anchored else "NO_ANCHORS"),
        },
    }
    authority_owned = experiment.get("assembly_mode") == "AUTHORITY_OWNED_V1"
    director_only = authority_owned and experiment.get("director_only") is True
    result = await llm.chat_completion(
        system_prompt=(DIRECTOR_ONLY_TEMPLATE if director_only else EXPERIMENT_TEMPLATE).read_text(encoding="utf-8"),
        user_content=json.dumps(input_payload, ensure_ascii=False),
        images=images,
        temperature=0.3, max_tokens=4500,
        task_type=template_type,
        prompt_template_name="H3 Director Only Experiment V1" if director_only else "H3 Single Stage Experiment V1",
        novel_id=novel_id, chapter_id=chapter_id, shot_id=shot_id,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "H3_SINGLE_STAGE_LLM_FAILED")
    raw_output = (result.get("content") or "").strip()
    subject_names = {subject: name for name, subject in subject_for_name.items()}
    manifest_mapping = [{**item, **{key: ref.get(key) for key in (
        "kind", "source_name", "source_keyframe_index")}}
        for item, ref in zip(picture_mapping, manifest.get("references") or [])]
    if authority_owned:
        prompt, review, picture = assemble_authority_owned_candidate(
            raw_output, canonical, timing, subject_names, manifest_mapping, continuation,
            experiment.get("verified_music"), director_only=director_only,
            character_appearances=(payload.get("shot") or {}).get("official_character_appearances"),
            character_stable_features=(payload.get("shot") or {}).get("official_character_stable_features"))
        checks = review["structure"]
    else:
        prompt, checks, picture = _assemble(
            raw_output, canonical, timing, subject_names, manifest_mapping, continuation)
    return {
        "mode": "SINGLE_STAGE_H3_PREVIEW", "route": route, "prompt": prompt,
        "raw_llm_output": raw_output, "llm_input": input_payload,
        "verified_timing": timing, "continuation_checks": continuation_checks,
        "picture_audit": picture, "contract_checks": checks,
        **({"assembly_review": review} if authority_owned else {}),
        "reference_manifest": manifest, "image_input_order": [item["logical_id"] for item in images],
        "anchor_selection": "NOT_COVERED" if anchored or prior_selection else "NOT_REQUIRED",
        "ready_for_h3_experiment": not authority_owned and not anchored and not prior_selection,
        "submission_authorized": False,
        "preflight_scope": "Six sections, structured dialogue, duration, continuation and Picture mapping; Canonical prose semantics and #14-only anchor selection require separate review.",
    }


# Phase A is an explicit, independent entry point. No production caller or
# existing preview route dispatches here; no default LLM client is constructed.
MULTI_DIRECTOR_TEMPLATE = Path(__file__).resolve().parents[2] / "prompt_templates/H3_MultiKeyframe_Director_PhaseA.txt"


def _snapshot_digest(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _phase_a_not_covered(reason):
    return {"mode": "H3_MULTI_KEYFRAME_PHASE_A", "status": "NOT_COVERED",
            "reasons": [reason], "submission_authorized": False,
            "production_preflight_passed": False}


def _phase_a_director_input(payload, saved_anchors):
    """Present verified facts in current namespaces; retain originals for audit.

    This is input formatting only. It neither selects references nor retimes
    anything, and never changes the manifests used by the existing compiler.
    """
    from app.services.video_director_ai import _strip_keyframe_generation_prompt, strip_media_refs

    result = _strip_keyframe_generation_prompt(strip_media_refs(deepcopy(payload)))
    manifest = result["reference_manifest"]
    current_pictures = {ref["source_picture"]: ref["picture"] for ref in manifest["references"]}
    # Source slots and excluded images belong to the offline audit, not the
    # current LLM image namespace. The actual preview list is already projected.
    result["reference_manifest"] = {
        **{k: v for k, v in manifest.items() if k not in {
            "references", "excluded_references", "picture_projection"}},
        "references": [{k: v for k, v in ref.items() if k not in {
            "source_slot", "source_picture", "logical_id"}} for ref in manifest["references"]],
        "picture_numbering": "CURRENT_SELECTED_REFERENCES_IN_SEND_ORDER; Previous AV previews are not Pictures",
    }
    frozen = result["frozen_execution"]
    states = {f"KF{s['index']}": s for s in result["canonical"]["owned_visual_states"]}
    catalog = {item["anchor_id"]: item for item in frozen["anchor_catalog"]}
    saved = {item["id"]: item for item in saved_anchors}
    for choice in frozen["anchor_decisions"]:
        item = catalog[choice["id"]]
        state = states.get(item.get("linked_anchor_id") or item["anchor_id"])
        # Ordinary and linked temporal anchors are traceable to the same
        # Canonical state, not to a guessed scale factor or matching prose.
        original_local = (state["time_seconds"] - result["clip"]["start_time"]) if state else None
        known = (_finite(original_local) and _finite(choice["original_time"])
                 and abs(original_local - choice["original_time"]) <= 1e-6)
        relation = saved[choice["id"]].get("arrival_relation")
        choice.update(
            original_time_base="CLIP_STORY_SECONDS" if known else "UNKNOWN",
            original_time_basis="CANONICAL_STATE_MINUS_CLIP_START" if known else "UNVERIFIED_SOURCE",
            optimized_time_base="GENERATION_LOCAL_SECONDS",
            arrival_constraint="RELEASED" if choice["decision"] == "DROP" else "FROZEN",
            arrival_relation=({k: relation[k] for k in ("dialogue_id", "position")}
                              if relation else None),
        )
    # Old #13/#14 prose embeds original Picture labels. Canonical state IDs
    # provide the full visual facts without importing or rewriting that prose.
    frozen["anchor_catalog"] = [{
        "anchor_id": item["anchor_id"], "source_kind": item["source_kind"],
        "linked_anchor_id": item.get("linked_anchor_id"),
        "canonical_state_index": (states.get(item.get("linked_anchor_id") or item["anchor_id"]) or {}).get("index"),
        "picture": current_pictures.get(item.get("source_picture")),
    } for item in catalog.values()]
    frozen.pop("time_base", None)  # original and optimized times are different domains.
    frozen["time_bases"] = {
        "timing": "GENERATION_LOCAL_SECONDS",
        "anchor_original_time": "PER_ANCHOR_ORIGINAL_TIME_BASE",
        "anchor_optimized_time": "GENERATION_LOCAL_SECONDS",
        "generation_origin": "Generated fragment zero includes shared Previous AV context; never add overlap again",
        "story_to_generation_mapping": "NOT_PROVIDED; anchor arrivals do not define a full timeline map",
    }
    frozen["anchor_semantics"] = (
        "KEEP/RETIME retain the saved optimized arrival, including its relation to dialogue. "
        "DROP releases the optional reference image and its anchor-arrival/image-matching constraint only; "
        "it never releases Canonical story, action, spatial facts or scoped state outcomes. "
        "A dropped anchor has no required arrival time or current Picture. "
        "Visual facts are in canonical.owned_visual_states, subject to transition execution_scope."
    )
    contract = result["previous_av"]["continuation_contract"]
    if contract:
        fps, first = contract["fps"], contract["source_start_frame"]
        result["previous_av"]["time_coordinates"] = {
            "source_time_base": "PREVIOUS_AV_SOURCE_SECONDS",
            "source_context_interval": [first / fps, contract["source_end_frame_exclusive"] / fps],
            "target_time_base": "GENERATION_LOCAL_SECONDS",
            "target_shared_prefix_interval": [0.0, contract["overlap_seconds"]],
            "mapping_scope": "SHARED_PREFIX_ONLY; (source_frame_index - source_start_frame) / fps",
        }
        # Both lists describe the same previews, outside the ordinary manifest.
        for frame in result["visual_previews"] + result["previous_av"]["preview_frames"]:
            if frame["type"] == "PREVIOUS_VIDEO_FRAME":
                frame["time_base"] = "PREVIOUS_AV_SOURCE_SECONDS"
                frame["generation_local_time_seconds"] = (frame["source_frame_index"] - first) / fps
    return result


def prepare_multi_keyframe_phase_a(snapshot):
    """Validate saved execution decisions and prepare real previews, without LLM.

    snapshot is an isolated export of existing records, not a database session.
    Reuses production projections/checks; unknown timing/selection is never filled.
    Returns NOT_COVERED before any LLM for missing, changed or unsupported inputs.
    """
    from types import SimpleNamespace
    from app.services.h3_execution_optimizer import check_authority, retime_temporal_manifest
    from app.services.h3_anchor_policy import project_reference_manifest
    from app.services.h3_continuation import continuation_contract
    from app.services.shot_video_service import _semantic_clip_prompt_context
    from app.services.video_director_ai import build_physical_picture_mapping

    try:
        data = deepcopy(snapshot)
        source, record = data["source"], data["frozen_record"]
        for field, proof in (("canonical_plan", "canonical_sha256"),
                             ("builder_input", "builder_input_sha256"),
                             ("frozen_record", "frozen_record_sha256")):
            if source.get(proof) != _snapshot_digest(data[field]):
                raise ValueError("SAVED_SOURCE_CHANGED: " + field)
        if (source.get("task_status") != "completed" or not source.get("task_id")
                or not source.get("builder_log_id") or source.get("optimizer_log_id") != record.get("llm_log_id")
                or record.get("status") != "OPTIMIZED" or not record.get("authority_check", {}).get("passed")):
            raise ValueError("VERIFIED_SAVED_EXECUTION_REQUIRED")
        runtime, output = record["runtime_input"], record["output"]
        authority, initial = runtime["immutable_authority"], runtime["initial_execution_timing"]
        saved_check = check_authority(record["raw_prompt"], output, authority, initial, runtime["duration_limits"])
        if not saved_check["passed"]:
            raise ValueError("SAVED_EXECUTION_INVALID: " + ",".join(saved_check["blocking_findings"]))
        old_input, plan = data["builder_input"], data["canonical_plan"]
        context = _semantic_clip_prompt_context(
            plan, {"clip_index": old_input["clip"]["clip_index"]},
            resolved_dialogue_timeline=plan["dialogue_timeline_source"])
        clip = context["clip"]
        capability = clip["capability"]
        if capability not in {"GENERATE", "EXTEND", "TEMPORAL_EXTEND"}:
            raise ValueError("PHASE_A_CAPABILITY_UNSUPPORTED")
        for key in ("start_time", "end_time", "visual_state_indexes", "carry_in_state_index", "capability"):
            if clip.get(key) != old_input["clip"].get(key):
                raise ValueError("SAVED_CLIP_MISMATCH: " + key)
        states = {state["index"]: state for state in plan["keyframes"]}
        for state in old_input["visual_controls"]:
            canonical_state = states[state["index"]]
            if (canonical_state["description"] != state["description"]
                    or abs(canonical_state["time_seconds"] - clip["start_time"] - state["time_seconds"]) > 1e-6):
                raise ValueError("SAVED_VISUAL_STATE_MISMATCH")
        owned = [states[index] for index in clip["visual_state_indexes"]]
        if len(owned) < 2:
            raise ValueError("PHASE_A_MULTI_STATE_SAMPLE_REQUIRED")
        carry_index = clip.get("carry_in_state_index")
        carry = states[carry_index] if carry_index is not None else None
        saved_transitions = runtime["execution_context"]["canonical_transitions"]
        for transition in context["transitions"]:
            keys = ("from_keyframe_index", "to_keyframe_index", "start_time", "end_time", "transition_description")
            if not any(all(transition.get(k) == old.get(k) for k in keys) for old in saved_transitions):
                raise ValueError("SAVED_TRANSITION_MISMATCH")
        names = authority["subject_bindings"]
        subject_for_name = {name: subject for subject, name in names.items()}
        if len(subject_for_name) != len(names):
            raise ValueError("SUBJECT_NAMES_AMBIGUOUS")
        assigned = [{**event, "duration": round(event["end_time"] - event["start_time"], 9)}
                    for event in context["clip_dialogues"]]
        if not assigned:
            raise ValueError("SILENT_CLIP_COMPILER_NOT_COVERED")
        continuation = continuation_contract(
            SimpleNamespace(**data["workflow"]), capability, data.get("previous_video_path"),
            runtime["execution_context"])
        if continuation != authority.get("continuation"):
            raise ValueError("SAVED_CONTINUATION_CHANGED")
        timing, canonical, continuation_checks = _verified_timing(
            assigned, subject_for_name, output["av_timeline"], continuation, capability)
        old_facts = authority["dialogue_events"]
        if ([(e["id"], e["speaker"], e["exact_dialogue"], e["duration"]) for e in canonical]
                != [(e["id"], e["speaker"], e["exact_dialogue"], e["duration"]) for e in old_facts]):
            raise ValueError("SAVED_CANONICAL_DIALOGUE_MISMATCH")
        music = sections(output["optimized_prompt"]).get("non_diegetic_music")
        if music != "N/A":
            raise ValueError("MUSIC_NOT_COVERED")
        appearances = old_input["shot"].get("official_character_appearances") or {}
        # A frozen Phase A response can reuse only the identity source it was
        # verified against. The new Phase B route has no such saved dependency.
        if any(not _stable_identity_marks(appearances.get(name)) for name in names.values()):
            raise ValueError("STABLE_IDENTITY_SOURCE_NOT_COVERED")
        if not isinstance(authority.get("anchor_policy"), dict):
            raise ValueError("VERIFIED_ANCHOR_POLICY_REQUIRED")
        manifest = project_reference_manifest(data["reference_manifest"], authority, output)
        mapping = build_physical_picture_mapping(manifest)
        for name in names.values():
            if sum(ref.get("kind") == "CHARACTER_IDENTITY" and ref.get("source_name") == name
                   for ref in mapping) != 1:
                raise ValueError("IDENTITY_PICTURE_NOT_COVERED")
        # Verify original resources before applying frozen KEEP/RETIME/DROP.
        # Hashes are from the saved #14 visual request, not inferred from names.
        expected = {v["picture"]: v for v in runtime["visual_inputs"] if v.get("picture")}
        from hashlib import sha256
        from app.utils.path_utils import url_to_local_path
        refs = data["reference_manifest"]["references"]
        if len(refs) != len(expected):
            raise ValueError("REFERENCE_MANIFEST_INCOMPLETE")
        resource_hashes = {}
        for ref in refs:
            key = f"<Picture {ref['slot']}>"
            saved = expected[key]
            path = Path(ref.get("local_path") or url_to_local_path(ref["image_url"]))
            digest = sha256(path.read_bytes()).hexdigest()
            if (digest != saved["source_sha256"] or ref["kind"] != saved["type"]
                    or ref.get("source_id") != saved.get("source_id")
                    or ref.get("source_name") != saved.get("source_name")
                    or ref.get("source_keyframe_index") != saved.get("state_index")):
                raise ValueError("REFERENCE_RESOURCE_CHANGED: " + key)
            resource_hashes[key] = digest
        temporal = runtime["execution_context"].get("temporal_anchor_manifest")
        if capability == "TEMPORAL_EXTEND" and not temporal:
            raise ValueError("TEMPORAL_MANIFEST_REQUIRED")
        temporal = retime_temporal_manifest(deepcopy(temporal), record) if temporal else None
        temporal_refs = (temporal or {}).get("anchors") or []
        for ref in temporal_refs:
            saved = next(v for v in runtime["visual_inputs"] if v["id"] == "TemporalAnchor:" + ref["anchor_id"])
            path = Path(ref.get("local_path") or url_to_local_path(ref["image_url"]))
            digest = sha256(path.read_bytes()).hexdigest()
            # Existing vision_proxy filenames are source SHA256, including older
            # temporal request entries that did not duplicate source_sha256.
            if digest != (saved.get("source_sha256") or Path(saved["vision_proxy"]).stem):
                raise ValueError("TEMPORAL_RESOURCE_CHANGED")
            resource_hashes["TemporalAnchor:" + ref["anchor_id"]] = digest
        images, visual = _visual_previews(manifest, temporal_refs, data.get("previous_video_path"), continuation)
        for item, preview in zip(images, visual):
            if preview["type"] == "PREVIOUS_VIDEO_FRAME":
                preview.update({key: item[key] for key in (
                    "source_frame_index", "context_start_frame", "context_end_frame", "source_fps") if key in item})
                preview["source_video_time_seconds"] = item.get("time")
                preview["time_base"] = "PREVIOUS_VIDEO_SOURCE; not a new dialogue window"
        if continuation:
            if sum(v["type"] == "PREVIOUS_VIDEO_FRAME" for v in visual) != 5:
                raise ValueError("PREVIOUS_AV_FIVE_PREVIEWS_REQUIRED")
            resource_hashes["PreviousAV"] = continuation["source_sha256"]
        choices = [{key: a.get(key) for key in ("id", "decision", "original_time", "optimized_time")}
                   for a in output["av_timeline"]["anchors"]]
        provenance = {**source, "execution_decision_owner": "SAVED_14_NOT_NEW_13",
                      "timing_sha256": _snapshot_digest(timing), "anchor_decisions_sha256": _snapshot_digest(choices)}
        payload = {
            "experiment": "H3_MULTI_KEYFRAME_PHASE_A", "builder": "13", "route": "multi",
            "shot": old_input["shot"], "clip": clip,
            "canonical": {
                "state_time_base": "SHOT_SECONDS", "owned_visual_states": owned,
                "carry_in_visual_state": carry,
                "transitions": context["transitions"],
                "action_authority": "Full state/transition descriptions within execution_scope; not the historical optimized prose",
                "dialogue_timeline": assigned,
                "dialogue_time_base": "start/end=SHOT_SECONDS; local_start/end=CLIP_STORY_SECONDS",
            },
            "subject_bindings": names, "speaker_bindings": speaker_bindings(canonical),
            "speech_slots": [{"slot": f"SPEECH_{i}", **e} for i, e in enumerate(timing["dialogue_events"], 1)],
            "camera_planning": {
                "sources": "Canonical state and transition descriptions; preserve spatial facts",
                "shot_continuity_mode": old_input["shot"].get("continuity_mode"),
                "historical_mode_origin": "UNKNOWN_UNLESS_EXPLICITLY_DOCUMENTED",
                "user_requirements": data["user_camera_requirements"],
                "visual_attention": runtime["execution_context"].get("visual_attention_snapshot"),
            },
            "reference_manifest": manifest, "picture_mapping": mapping,
            "temporal_anchor_manifest": temporal,
            "temporal_time_base": "GENERATION_LOCAL_INCLUDES_SHARED_PREFIX; frame positions use existing compiler",
            "previous_av": {"continuation_contract": continuation, "preview_frames": [v for v in visual if v["type"] == "PREVIOUS_VIDEO_FRAME"]},
            "visual_previews": visual,
            "execution_budget": {"story_duration": clip["end_time"] - clip["start_time"],
                "generation_duration": timing["optimized_duration"], "duration_limits": runtime["duration_limits"],
                "overlap_seconds": continuation["overlap_seconds"] if continuation else 0.0,
                "unknown_execution_cost": "NOT_ESTIMATED; frozen historical budget, not zero cost"},
            "frozen_execution": {"provenance": provenance, "timing": timing, "anchor_decisions": choices,
                "anchor_catalog": authority["anchor_policy"]["catalog"],
                "time_base": "GENERATION_LOCAL_INCLUDES_SHARED_PREFIX; never add overlap again"},
        }
        return {"mode": "H3_MULTI_KEYFRAME_PHASE_A", "status": "PREPARED", "route": "multi",
                "llm_input": _phase_a_director_input(payload, output["av_timeline"]["anchors"]), "images": images,
                "canonical": canonical, "timing": timing, "subject_names": names,
                "picture_mapping": mapping, "reference_manifest": manifest, "temporal_manifest": temporal,
                "continuation": continuation, "character_appearances": appearances, "verified_music": music,
                "source": provenance, "resource_hashes": resource_hashes,
                "saved_execution_preflight": saved_check, "continuation_checks": continuation_checks,
                "submission_authorized": False, "production_preflight_passed": False}
    except (KeyError, ValueError, TypeError, OSError, StopIteration) as exc:
        return _phase_a_not_covered(f"{type(exc).__name__}: {exc}")


def compile_multi_keyframe_phase_a(prepared, director_text):
    """Compile only authoritative facts; never invent director prose or repairs."""
    if prepared.get("status") != "PREPARED":
        return _phase_a_not_covered("PREPARED_VERIFIED_INPUT_REQUIRED")
    try:
        prompt, review, picture = assemble_authority_owned_candidate(
            director_text, prepared["canonical"], prepared["timing"], prepared["subject_names"],
            prepared["picture_mapping"], prepared["continuation"], prepared["verified_music"],
            director_only=True, character_appearances=prepared["character_appearances"],
            frozen_execution=prepared["llm_input"]["frozen_execution"])
    except (KeyError, ValueError, TypeError) as exc:
        return _phase_a_not_covered(f"DIRECTOR_OUTPUT_UNSUPPORTED: {exc}")
    passed = all(review["structure"].values()) and all(review["structured_authority"].values())
    return {"mode": "H3_MULTI_KEYFRAME_PHASE_A", "route": "multi",
            "status": "CANDIDATE_FOR_REVIEW" if passed else "VALIDATION_FAILED", "prompt": prompt,
            "director_text": director_text, "review": review, "picture_audit": picture,
            "execution_decisions": prepared["llm_input"]["frozen_execution"],
            "reference_manifest": prepared["reference_manifest"], "temporal_manifest": prepared["temporal_manifest"],
            "director_semantics": {"status": "REVIEW_REQUIRED", "items": [
                "Canonical action coverage and cross-Clip scope", "Frozen anchor outcomes and arrival relations",
                "Spatial/costume continuity and explicit camera requirements", "Speaker visibility and advance preparation",
                "Scene/action-supported Foley"]},
            "submission_authorized": False, "production_preflight_passed": False}


async def preview_multi_keyframe_phase_a(snapshot, *, llm):
    """Explicit future experiment: exactly one injected #13 client call, no #14.

    This entry is never called by production. Phase A offline tests inject a fake
    client; real invocation requires separate user authorization.
    """
    prepared = prepare_multi_keyframe_phase_a(snapshot)
    if prepared["status"] != "PREPARED":
        return prepared
    request = {"system_prompt": MULTI_DIRECTOR_TEMPLATE.read_text(encoding="utf-8"),
               "user_content": json.dumps(prepared["llm_input"], ensure_ascii=False),
               "images": prepared["images"], "temperature": 0.3, "max_tokens": 4500,
               "task_type": "h3_multi_keyframe_prompt", "prompt_template_name": "H3 Multi-Keyframe Director Phase A (isolated)"}
    response = await llm.chat_completion(**request)
    if not response.get("success"):
        return {**_phase_a_not_covered("DIRECTOR_CALL_FAILED"), "llm_response": response}
    result = compile_multi_keyframe_phase_a(prepared, response.get("content") or "")
    return {**result, "llm_request": request, "llm_response": response, "llm_call_count": 1}


# Phase B accepts an upstream-only snapshot, never a Phase A frozen_record.
# No API/worker imports or dispatches this opt-in experiment entry point.
PHASE_B_TEMPLATE = Path(__file__).resolve().parents[2] / "prompt_templates/H3_MultiKeyframe_Director_PhaseB.txt"


def _phase_b_not_covered(reason):
    return {"mode": "H3_MULTI_KEYFRAME_PHASE_B", "status": "NOT_COVERED",
            "reasons": [reason], "submission_authorized": False,
            "production_preflight_passed": False}


def has_phase_b_canonical_scope(clip, canonical):
    """Owned targets or the planner's scoped continuation supply action authority."""
    if canonical.get("owned_visual_states"):
        return True
    carry = canonical.get("carry_in_visual_state") or {}
    transitions = canonical.get("transitions") or []
    return (clip.get("capability") == "EXTEND"
            and clip.get("continuity_to_previous") == "CONTINUOUS"
            and carry.get("index") is not None
            and carry["index"] == clip.get("carry_in_state_index")
            and bool(transitions)
            and all(t.get("from_keyframe_index") == carry["index"]
                    and t.get("target_state_owned") is False
                    and t.get("projection_mode") == "CROSS_CLIP_CONTINUATION"
                    and bool(t.get("execution_scope"))
                    and _finite(t.get("clip_local_start_time"))
                    and _finite(t.get("clip_local_end_time"))
                    and t["clip_local_end_time"] > t["clip_local_start_time"]
                    for t in transitions))


def prepare_multi_keyframe_phase_b(snapshot, *, runtime=False):
    """Prepare upstream facts and actual previews; never read #14 decisions.

    physical_evidence contains source hashes, the actual Previous AV provenance,
    initial temporal resources and capability limits, NOT optimizer output.
    Music requires an explicit, reviewed upstream evidence record. No inference
    from sound keywords or fallback to a historical optimized prompt is used.
    """
    from hashlib import sha256
    from types import SimpleNamespace
    from app.services.h3_continuation import continuation_contract
    from app.services.h3_anchor_policy import reference_drop_capability
    from app.services.shot_video_service import _semantic_clip_prompt_context
    from app.services.video_director_ai import (
        build_physical_picture_mapping, _strip_keyframe_generation_prompt, strip_media_refs,
    )
    from app.utils.path_utils import url_to_local_path

    try:
        if set(snapshot) - {"video_prompt_language"} != {"source", "canonical_plan", "builder_input", "reference_manifest",
                             "workflow", "previous_video_path", "physical_evidence",
                             "music_contract", "user_camera_requirements"}:
            raise ValueError("UPSTREAM_ONLY_SNAPSHOT_REQUIRED")
        data = deepcopy(snapshot)
        source = data["source"]
        if "video_prompt_language" in data and source["hashes"].get("video_prompt_language") != _snapshot_digest(data["video_prompt_language"]):
            raise ValueError("SOURCE_CHANGED: video_prompt_language")
        for key in ("canonical_plan", "builder_input", "reference_manifest", "workflow",
                    "physical_evidence", "music_contract", "user_camera_requirements"):
            if source["hashes"].get(key) != _snapshot_digest(data[key]):
                raise ValueError("SOURCE_CHANGED: " + key)
        plan, old, evidence = data["canonical_plan"], data["builder_input"], data["physical_evidence"]
        from app.services.effective_execution import task_execution_projection
        policy = evidence.get("execution_projection")
        policy_metadata = ({"continuation_mode": policy["continuation_mode"], "execution_projection": policy,
                            "capability": old["clip"]["capability"]} if policy else {})
        original_clip = next(c for c in plan["clip_plan"] if c["clip_index"] == old["clip"]["clip_index"])
        projection = task_execution_projection(plan, original_clip, policy_metadata)
        context = _semantic_clip_prompt_context(plan, {"clip_index": old["clip"]["clip_index"], **policy_metadata},
                                                resolved_dialogue_timeline=plan["dialogue_timeline_source"])
        # Whitelist request data; saved Clip runtime artifacts are not planning input.
        clip = {k: context["clip"].get(k) for k in (
            "clip_index", "start_time", "end_time", "planned_duration", "capability",
            "visual_state_indexes", "carry_in_state_index", "continuity_to_previous")}
        for key in ("start_time", "end_time", "capability", "visual_state_indexes", "carry_in_state_index"):
            if clip[key] != old["clip"].get(key):
                raise ValueError("SAVED_CLIP_MISMATCH: " + key)
        capability = clip["capability"]
        if capability not in {"GENERATE", "EXTEND", "TEMPORAL_EXTEND"}:
            raise ValueError("CAPABILITY_NOT_COVERED")
        states = {s["index"]: s for s in plan["keyframes"]}
        owned = [states[i] for i in clip["visual_state_indexes"]]
        carry = states[clip["carry_in_state_index"]] if clip["carry_in_state_index"] is not None else None
        # A Clip wholly inside a Canonical transition can have no owned target.
        # Keep carry-in as context and use the existing scoped action projection;
        # it never becomes a target or a physical anchor.
        if not has_phase_b_canonical_scope(clip, {"owned_visual_states": owned,
                "carry_in_visual_state": carry, "transitions": context["transitions"]}):
            raise ValueError("OWNED_VISUAL_STATE_REQUIRED")
        if not owned:
            # Reuse the planner's ownership rule to reject an omitted target or
            # a wrong carry-in instead of manufacturing a state for the Clip.
            from app.services.clip_planner import _project_clip_visual_states
            expected = deepcopy(clip)
            _project_clip_visual_states([expected], [
                {**state, "keyframe_index": state["index"]} for state in states.values()])
            if (expected["visual_state_indexes"]
                    or expected["carry_in_state_index"] != clip["carry_in_state_index"]):
                raise ValueError("CANONICAL_STATE_SCOPE_MISMATCH")
        if len(old["visual_controls"]) != len(owned):
            raise ValueError("SAVED_STATES_MISMATCH")
        for state, saved in zip(owned, old["visual_controls"]):
            if (state["index"] != saved["index"] or state["description"] != saved["description"]
                    or abs(state["time_seconds"] - clip["start_time"] - saved["time_seconds"]) > 1e-6):
                raise ValueError("SAVED_STATES_MISMATCH")
        if not _finite(old["shot"].get("duration")) or clip["end_time"] > old["shot"]["duration"]:
            raise ValueError("STORY_BOUNDARY_INVALID")

        bindings = old["reference_binding_contract"]["characters"]
        pictured = {b["subject"]: b["name"] for b in bindings}
        # Binding records follow Picture order, which need not be Subject order.
        # Validate the builder's explicit numbering, never renumber by image slot.
        subject_order = {f"<Subject {i}>": name for i, name in enumerate(old["clip_visible_characters"], 1)}
        if (len(subject_order) != len(old["clip_visible_characters"])
                or len(set(subject_order.values())) != len(subject_order)
                or len(pictured) != len(bindings) or len(set(pictured.values())) != len(pictured)
                or any(subject_order.get(subject) != name for subject, name in pictured.items())):
            raise ValueError("UPSTREAM_SUBJECT_BINDING_AMBIGUOUS")
        names = subject_order
        subject_for_name = {name: subject for subject, name in names.items()}
        appearances = old["shot"].get("official_character_appearances") or {}
        structured_features = old["shot"].get("official_character_stable_features") or {}
        assigned = context["clip_dialogues"]
        if any(a["end_time"] > b["start_time"] + 1e-6 for a, b in zip(assigned, assigned[1:])):
            raise ValueError("OVERLAPPING_DIALOGUE_NOT_COVERED")
        canonical = [{"id": e["id"], "speaker": _speaker_subject(e["speaker"], subject_for_name),
                      "exact_dialogue": e["text"], "duration": round(e["end_time"] - e["start_time"], 9)}
                     for e in assigned]
        if any(e["speaker"] is None for e in canonical):
            raise ValueError("DIALOGUE_SPEAKER_BINDING_MISSING")
        if len({e["id"] for e in canonical}) != len(canonical):
            raise ValueError("DUPLICATE_DIALOGUE")

        workflow = SimpleNamespace(**data["workflow"])
        limits = evidence["duration_limits"]
        contract_limits = workflow_duration_limits(capability=capability)
        if not (all(_finite(limits.get(k)) for k in ("minimum", "maximum"))
                and contract_limits["minimum"] <= limits["minimum"] <= limits["maximum"] <= contract_limits["maximum"]):
            raise ValueError("DURATION_LIMITS_UNVERIFIED")
        continuation = continuation_contract(workflow, capability, data.get("previous_video_path"),
                                             {"previous_clip": evidence.get("previous_clip")})
        overlap = continuation["overlap_seconds"] if continuation else 0.0
        if sum(e["duration"] for e in canonical) + overlap > limits["maximum"] + 1e-6:
            raise ValueError("FIXED_SPEECH_EXCEEDS_BUDGET")
        manifest = data["reference_manifest"]
        mapping = build_physical_picture_mapping(manifest)
        suppressed_states = set(projection["suppressed_state_indexes"])
        suppressed_urls = set(projection["suppressed_image_urls"])
        if any(r.get("source_keyframe_index") in suppressed_states
               or r.get("image_url") in suppressed_urls for r in manifest["references"]):
            raise ValueError("SUPPRESSED_TEMPORAL_REFERENCE_RETURNED")
        if not 0 <= len(mapping) <= 9:
            raise ValueError("REFERENCE_COUNT_UNSUPPORTED")
        # Saved executed graphs may already have optional image nodes removed.
        # Verify the existing unbound binder separately, without rebuilding or
        # editing the saved workflow. This is not a submission-ready graph.
        drop_capability = reference_drop_capability(workflow)
        binder = evidence.get("reference_binder")
        if binder:
            binder_text = Path(binder["template_path"]).read_text(encoding="utf-8")
            if sha256(binder_text.encode()).hexdigest() != binder["sha256"]:
                raise ValueError("REFERENCE_BINDER_SOURCE_CHANGED")
            drop_capability = reference_drop_capability(SimpleNamespace(
                **{**data["workflow"], "workflow_json": binder_text}))
            drop_capability["evidence_scope"] = "EXISTING_UNBOUND_BINDER; NOT_A_SUBMISSION_GRAPH"
        owned_indexes = {s["index"] for s in owned}
        anchor_refs = [r for r in manifest["references"] if r["kind"] == "DIRECTOR_VISUAL_ANCHOR"]
        if (len({r["source_keyframe_index"] for r in anchor_refs}) != len(anchor_refs)
                or any(r["source_keyframe_index"] not in owned_indexes
                       or r["source_time_seconds"] != states[r["source_keyframe_index"]]["time_seconds"]
                       for r in anchor_refs)):
            raise ValueError("ANCHOR_REFERENCE_SOURCE_MISMATCH")
        if [r["slot"] for r in manifest["references"]] != list(range(1, len(mapping) + 1)):
            raise ValueError("ORIGINAL_PICTURE_ORDER_INVALID")
        if (anchor_refs or capability == "TEMPORAL_EXTEND") and not drop_capability["supported"]:
            raise ValueError("REFERENCE_SELECTION_BINDER_NOT_COVERED")
        if sum(r["kind"] == "CHARACTER_IDENTITY" for r in mapping) != len(bindings):
            raise ValueError("IDENTITY_PICTURE_BINDING_MISMATCH")
        for subject, name in pictured.items():
            identity = [r for r in mapping if r["kind"] == "CHARACTER_IDENTITY" and r["source_name"] == name]
            bound = next(b for b in bindings if b["subject"] == subject)
            if len(identity) != 1 or identity[0]["picture"] != bound["picture"]:
                raise ValueError("IDENTITY_PICTURE_BINDING_MISMATCH")
        temporal = evidence.get("temporal_anchors") or []
        upstream_temporal = old.get("temporal_anchors") or []
        if ([a["anchor_id"] for a in temporal] != [a["anchor_id"] for a in upstream_temporal]
                or (capability == "TEMPORAL_EXTEND") != bool(temporal)):
            raise ValueError("TEMPORAL_MANIFEST_UNVERIFIED")
        resources = [(f"<Picture {r['slot']}>", r) for r in manifest["references"]]
        resources += [("TemporalAnchor:" + a["anchor_id"], a) for a in temporal]
        hashes = {}
        if set(evidence["resource_hashes"]) != {key for key, _ in resources}:
            raise ValueError("RESOURCE_HASH_CATALOG_MISMATCH")
        for key, resource in resources:
            path = Path(resource.get("local_path") or url_to_local_path(resource["image_url"]))
            hashes[key] = sha256(path.read_bytes()).hexdigest()
            if hashes[key] != evidence["resource_hashes"][key]:
                raise ValueError("RESOURCE_CHANGED: " + key)

        # Canonical states, rather than old Raw-language parsing or #14 selection,
        # own the full candidate catalog, including text-only states.
        catalog = []
        for state in owned:
            picture = next((r["picture"] for r in mapping
                            if r["kind"] == "DIRECTOR_VISUAL_ANCHOR"
                            and r["source_keyframe_index"] == state["index"]), None)
            catalog.append({"anchor_id": f"KF{state['index']}", "canonical_state_index": state["index"],
                            "original_time": round(state["time_seconds"] - clip["start_time"], 6),
                            "original_time_base": "CLIP_STORY_SECONDS", "source_time_base": "SHOT_SECONDS",
                            "source_time": state["time_seconds"], "source_picture": picture,
                            "source_kind": "DIRECTOR_VISUAL_ANCHOR" if picture else "CANONICAL_VISUAL_STATE",
                            "linked_anchor_id": None})
        for anchor, saved in zip(temporal, upstream_temporal):
            index = anchor["source"].get("keyframe_index")
            target = next(a for a in catalog if a["canonical_state_index"] == index)
            if (abs(anchor["time_seconds"] - target["original_time"]) > 1e-6
                    or anchor["time_seconds"] != saved["time_seconds"]
                    or anchor["source"].get("id", target["anchor_id"]) != target["anchor_id"]):
                raise ValueError("TEMPORAL_ORIGINAL_TIME_MISMATCH")
            catalog.append({**target, "anchor_id": anchor["anchor_id"], "source_kind": "TEMPORAL_ANCHOR",
                            "linked_anchor_id": target["anchor_id"]})
        if len({a["anchor_id"] for a in catalog}) != len(catalog):
            raise ValueError("ANCHOR_ID_COLLISION")
        music = data["music_contract"]
        reviewed_music = (music.get("source_stage") == "13_RAW"
                          and music.get("source_log_id") and music.get("source_excerpt")
                          and music.get("interpretation") == "REVIEWED_NO_ADDED_MUSIC")
        runtime_music = (runtime and music == {"value": "N/A", "source_stage": "PHASE_B_RUNTIME_POLICY",
                                              "interpretation": "NO_ADDED_SCORE"})
        if music.get("value") != "N/A" or not (reviewed_music or runtime_music):
            raise ValueError("MUSIC_AUTHORITY_NOT_COVERED")
        images, visual = _visual_previews(manifest, temporal, data.get("previous_video_path"), continuation)
        previous = []
        for image, item in zip(images, visual):
            if item["type"] == "PREVIOUS_VIDEO_FRAME":
                item.update(time_base="PREVIOUS_AV_SOURCE_SECONDS", source_video_time_seconds=image["time"],
                            source_frame_index=image["source_frame_index"],
                            generation_local_time_seconds=(image["source_frame_index"] - continuation["source_start_frame"]) / continuation["fps"])
                previous.append(item)
        if continuation and len(previous) != 5:
            raise ValueError("FIVE_PREVIOUS_PREVIEWS_REQUIRED")
        if continuation:
            hashes["PreviousAV"] = continuation["source_sha256"]
        clean = lambda value: _strip_keyframe_generation_prompt(strip_media_refs(deepcopy(value)))
        payload = {
            "experiment": "H3_MULTI_KEYFRAME_PHASE_B", "builder": "13", "route": "multi",
            "shot": clean(old["shot"]), "clip": clip,
            "time_domains": {"canonical": "SHOT_SECONDS", "clip_projection": "CLIP_STORY_SECONDS",
                "new_execution_decisions": "GENERATION_LOCAL_SECONDS", "previous_previews": "PREVIOUS_AV_SOURCE_SECONDS",
                "story_to_generation_mapping": "NOT_PROVIDED; do not infer a linear map or add overlap to selected generation times"},
            "canonical": {"owned_visual_states": clean(owned), "carry_in_visual_state": clean(carry),
                          "transitions": clean(context["transitions"]), "dialogue_timeline": assigned},
            "subject_bindings": names, "speaker_bindings": speaker_bindings(canonical),
            "speech_slots": [{"slot": f"SPEECH_{i}", "id": e["id"], "speaker": e["speaker"],
                              "fixed_duration": e["duration"],
                              "original_start": assigned[i-1]["local_start_time"],
                              "original_end": assigned[i-1]["local_end_time"], "original_time_base": "CLIP_STORY_SECONDS"}
                             for i, e in enumerate(canonical, 1)],
            "anchor_catalog": catalog,
            "reference_selection_capability": drop_capability,
            "reference_manifest": clean(manifest), "picture_mapping": mapping,
            "temporal_anchor_manifest": {"anchors": clean(temporal), "time_base": "CLIP_STORY_SECONDS"},
            "visual_previews": visual,
            "previous_av": {"continuation_contract": continuation, "preview_frames": previous,
                "source_context_interval": ([continuation["source_start_frame"] / continuation["fps"],
                                              continuation["source_end_frame_exclusive"] / continuation["fps"]] if continuation else None),
                "generation_shared_prefix_interval": [0, overlap] if continuation else None},
            "camera_planning": {"user_requirements": data["user_camera_requirements"],
                "historical_mode_origin": "UNKNOWN_UNLESS_EXPLICITLY_DOCUMENTED",
                "visual_attention": clean(old.get("visual_attention_timeline")),
                "sources": "Canonical owned/carry states and scoped Transitions; never move people for composition"},
            "execution_budget": {"story_duration": clip["end_time"] - clip["start_time"],
                "duration_limits": limits, "overlap_seconds": overlap,
                "fixed_speech_lower_bound": round(sum(e["duration"] for e in canonical) + overlap, 6),
                "unknown_execution_cost": "NOT_ESTIMATED; camera/action costs require director judgment"},
            "music_policy": {"value": music["value"], "source": music["source_stage"] if runtime_music else "REVIEWED_UPSTREAM_13_RAW_NO_ADDED_MUSIC"},
        }
        from app.services.effective_execution import projection_record
        from app.services.h3_prompt_language import validate_language, description_sources, LANGUAGE_CONTRACT
        language = data.get("video_prompt_language")
        if language is not None:
            payload.update(video_prompt_language=validate_language(language), language_contract=LANGUAGE_CONTRACT,
                           compiler_description_sources=description_sources(
                               names, appearances, mapping,
                               lambda appearance: _stable_identity_marks(appearance), structured_features))
        projection_record_for_prepare = projection_record(projection)
        authority = {"reference_bindings": [{"picture": r["picture"], "type": r["kind"]} for r in mapping],
                     "anchor_policy": {"catalog": catalog}}
        return {"mode": "H3_MULTI_KEYFRAME_PHASE_B", "status": "PREPARED", "llm_input": payload,
                "images": images, "canonical": canonical, "assigned": assigned, "subject_names": names,
                "character_appearances": appearances, "character_stable_features": structured_features,
                "continuation": continuation, "limits": limits,
                "reference_manifest": manifest, "picture_mapping": mapping, "temporal_anchors": temporal,
                "authority": authority, "drop_capability": drop_capability,
                "resource_hashes": hashes, "source": source, "music_contract": music,
                "execution_projection": projection_record_for_prepare,
                "submission_authorized": False, "production_preflight_passed": False}
    except (KeyError, ValueError, TypeError, OSError, StopIteration, AttributeError) as exc:
        return _phase_b_not_covered(f"{type(exc).__name__}: {exc}")


def compile_multi_keyframe_phase_b(prepared, response):
    """Validate one new Director response, derive numbers and compile, without LLM."""
    from app.services.h3_anchor_policy import project_reference_manifest
    from app.services.video_director_ai import build_physical_picture_mapping
    from app.services.clip_execution_compiler import project_temporal_anchor_positions

    if prepared.get("status") != "PREPARED":
        return _phase_b_not_covered("PREPARED_INPUT_REQUIRED")
    try:
        output = json.loads(response) if isinstance(response, str) else deepcopy(response)
        language = prepared["llm_input"].get("video_prompt_language")
        fields = {"optimized_duration", "dialogue_events", "anchors", "detailed_description", "overall_soundscape"}
        localized = None
        if language is not None:
            fields.add("localized_descriptions")
        if not isinstance(output, dict) or set(output) != fields:
            raise ValueError("DIRECTOR_RESPONSE_FIELDS_INVALID")
        if language is not None:
            from app.services.h3_prompt_language import validate_localized_descriptions
            localized = validate_localized_descriptions(output["localized_descriptions"],
                                                       prepared["llm_input"]["compiler_description_sources"])
        duration = output["optimized_duration"]
        if not _finite(duration) or not prepared["limits"]["minimum"] <= duration <= prepared["limits"]["maximum"]:
            raise ValueError("GENERATION_DURATION_INVALID")
        canonical = prepared["canonical"]
        events = output["dialogue_events"]
        if not isinstance(events, list) or len(events) != len(canonical):
            raise ValueError("DIALOGUE_IDS_INVALID")
        derived = []
        for event, fact in zip(events, canonical):
            if not isinstance(event, dict) or set(event) != {"id", "start"} or event["id"] != fact["id"] or not _finite(event["start"]):
                raise ValueError("DIALOGUE_IDS_OR_START_INVALID")
            derived.append({"id": fact["id"], "speaker": fact["speaker"],
                            "optimized_start": event["start"], "optimized_end": round(event["start"] + fact["duration"], 9)})
        timing, verified, continuation_checks = _verified_timing(
            [{**e, "duration": c["duration"]} for e, c in zip(prepared["assigned"], canonical)],
            {name: subject for subject, name in prepared["subject_names"].items()},
            {"optimized_duration": duration, "dialogue_events": derived}, prepared["continuation"],
            prepared["llm_input"]["clip"]["capability"])
        if verified != canonical:
            raise ValueError("CANONICAL_TEXT_CHANGED")
        for event, original in zip(timing["dialogue_events"], prepared["assigned"]):
            event.update(original_start=original["local_start_time"], original_end=original["local_end_time"],
                         original_time_base="CLIP_STORY_SECONDS", optimized_time_base="GENERATION_LOCAL_SECONDS",
                         delta=round(event["optimized_start"] - original["local_start_time"], 9))
        catalog = prepared["llm_input"]["anchor_catalog"]
        choices = output["anchors"]
        if (not isinstance(choices, list) or any(not isinstance(a, dict) for a in choices)
                or [a.get("id") for a in choices] != [a["anchor_id"] for a in catalog]):
            raise ValueError("ANCHOR_IDS_INVALID")
        normalized = []
        events_by_id = {e["id"]: e for e in timing["dialogue_events"]}
        for choice, source in zip(choices, catalog):
            if set(choice) != {"id", "decision", "optimized_time", "arrival_relation", "reason"}:
                raise ValueError("ANCHOR_FIELDS_INVALID")
            decision, arrival, relation = choice["decision"], choice["optimized_time"], choice["arrival_relation"]
            if decision not in {"KEEP", "RETIME", "DROP"} or not isinstance(choice["reason"], str) or not choice["reason"].strip():
                raise ValueError("ANCHOR_DECISION_INVALID")
            if decision == "DROP":
                if arrival is not None or relation is not None:
                    raise ValueError("DROP_CANNOT_HAVE_ARRIVAL")
                if (source["source_picture"] or source["source_kind"] == "TEMPORAL_ANCHOR") and not prepared["drop_capability"]["supported"]:
                    raise ValueError("DROP_BINDING_NOT_COVERED")
            else:
                if (source["original_time_base"] != "CLIP_STORY_SECONDS" or not _finite(arrival)
                        or not 0 <= arrival <= duration or
                        (decision == "KEEP" and abs(arrival - source["original_time"]) > 1e-6)):
                    raise ValueError("ANCHOR_TIME_INVALID")
                if prepared["continuation"] and arrival < prepared["continuation"]["overlap_seconds"]:
                    raise ValueError("NEW_ANCHOR_INSIDE_PROTECTED_CONTEXT")
                if not canonical:
                    if relation is not None:
                        raise ValueError("SILENT_ANCHOR_RELATION_MUST_BE_NULL")
                else:
                    if not isinstance(relation, dict) or set(relation) != {"dialogue_id", "position"} or relation["dialogue_id"] not in events_by_id:
                        raise ValueError("ANCHOR_RELATION_INVALID")
                    event = events_by_id[relation["dialogue_id"]]
                    start, end = event["optimized_start"], event["optimized_end"]
                    valid = {"BEFORE": arrival <= start, "DURING": start <= arrival <= end, "AFTER": arrival >= end}
                    if not valid.get(relation["position"], False):
                        raise ValueError("ANCHOR_RELATION_INVALID")
            normalized.append({**choice, "original_time": source["original_time"],
                               "original_time_base": source["original_time_base"],
                               "optimized_time_base": "GENERATION_LOCAL_SECONDS",
                               "delta": round(arrival - source["original_time"], 9) if decision != "DROP" else None})
        by_id = {a["id"]: a for a in normalized}
        for item in catalog:
            if item["linked_anchor_id"]:
                a, b = by_id[item["anchor_id"]], by_id[item["linked_anchor_id"]]
                if any(a[k] != b[k] for k in ("decision", "optimized_time", "arrival_relation")):
                    raise ValueError("TEMPORAL_ALIAS_MISMATCH")
        retained_times = [by_id[a["anchor_id"]]["optimized_time"] for a in catalog
                          if not a["linked_anchor_id"] and by_id[a["anchor_id"]]["decision"] != "DROP"]
        if any(a >= b for a, b in zip(retained_times, retained_times[1:])):
            raise ValueError("CANONICAL_ANCHOR_ORDER_CHANGED")
        manifest = project_reference_manifest(prepared["reference_manifest"], prepared["authority"],
                                              {"av_timeline": {"anchors": normalized}})
        manifest["selection_source"] = "NEW_13_PHASE_B"
        mapping = build_physical_picture_mapping(manifest)
        retained_temporal = [{**a, "time_seconds": by_id[a["anchor_id"]]["optimized_time"]}
                             for a in prepared["temporal_anchors"] if by_id[a["anchor_id"]]["decision"] != "DROP"]
        projected = project_temporal_anchor_positions(retained_temporal, duration) if retained_temporal else []
        temporal_manifest = {"anchors": projected, "time_base": "GENERATION_LOCAL_SECONDS",
                             "excluded_anchors": [a for a in prepared["temporal_anchors"] if by_id[a["anchor_id"]]["decision"] == "DROP"]}
        decisions = {"decision_owner": "NEW_13_PHASE_B", "timing": timing,
                     "anchor_decisions": normalized, "anchor_catalog": catalog,
                     "duration_delta": round(duration - prepared["llm_input"]["execution_budget"]["story_duration"], 9),
                     "gaps": [{"from": a["id"], "to": b["id"], "seconds": round(b["optimized_start"] - a["optimized_end"], 9)}
                              for a, b in zip(timing["dialogue_events"], timing["dialogue_events"][1:])]}
        if any(not isinstance(output[k], str) or not output[k].strip() for k in ("detailed_description", "overall_soundscape")):
            raise ValueError("DIRECTOR_PROSE_REQUIRED")
        director = f"detailed_description:\n{output['detailed_description']}\n\noverall_soundscape:\n{output['overall_soundscape']}"
        shot_sources = prepared["llm_input"]["shot"]
        prop_names = shot_sources.get("props")
        if not isinstance(prop_names, (list, tuple)):
            prop_names = []
        prompt, review, picture = assemble_authority_owned_candidate(
            director, canonical, timing, prepared["subject_names"], mapping, prepared["continuation"],
            prepared["music_contract"]["value"], director_only=True,
            character_appearances=prepared["character_appearances"],
            character_stable_features=prepared.get("character_stable_features"), execution_decisions=decisions,
            prompt_language=language, localized_descriptions=localized,
            canonical_source_names=(shot_sources.get("scene"), *prop_names))
        passed = all(review["structure"].values()) and all(review["structured_authority"].values())
        return {"mode": "H3_MULTI_KEYFRAME_PHASE_B", "status": "CANDIDATE_FOR_REVIEW" if passed else "VALIDATION_FAILED",
                "prompt": prompt, "director_response": output, "director_text": director,
                "execution_decisions": decisions, "reference_manifest": manifest, "picture_mapping": mapping,
                "temporal_manifest": temporal_manifest, "review": review, "picture_audit": picture,
                "continuation_checks": continuation_checks,
                "director_semantics": {"status": "REVIEW_REQUIRED", "items": [
                    "Canonical actions/outcomes retained after DROP", "Action order and cross-Clip scope",
                    "Readiness/arrival feasibility and prose consistency", "Speaker visibility, space and soundscape"]},
                "submission_authorized": False, "production_preflight_passed": False}
    except (KeyError, ValueError, TypeError, StopIteration) as exc:
        return {**_phase_b_not_covered(f"{type(exc).__name__}: {exc}"), "status": "VALIDATION_FAILED"}


async def preview_multi_keyframe_phase_b(snapshot, *, llm):
    """Explicit one-call preview; caller must provide a transport with retries disabled."""
    prepared = prepare_multi_keyframe_phase_b(snapshot)
    if prepared["status"] != "PREPARED":
        return prepared
    if getattr(llm, "max_retries", None) != 0:
        return _phase_b_not_covered("ZERO_RETRY_CLIENT_REQUIRED")
    request = {"system_prompt": PHASE_B_TEMPLATE.read_text(encoding="utf-8"),
               "user_content": json.dumps(prepared["llm_input"], ensure_ascii=False),
               "images": prepared["images"], "response_format": "json_object", "temperature": 0.3,
               "max_tokens": 4500, "task_type": "h3_multi_keyframe_prompt",
               "prompt_template_name": "H3 Multi-Keyframe Director Phase B (isolated)"}
    try:
        response = await llm.chat_completion(**request)
    except Exception as exc:
        return {**_phase_b_not_covered(type(exc).__name__), "llm_call_count": 1}
    if not response.get("success"):
        return {**_phase_b_not_covered("DIRECTOR_CALL_FAILED"), "llm_call_count": 1}
    return {**compile_multi_keyframe_phase_b(prepared, response.get("content") or ""),
            "llm_request": request, "llm_response": response, "llm_call_count": 1}
