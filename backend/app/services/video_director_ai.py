"""Helpers for Video Director prompt call records and prompt builders."""
import json
import hashlib
import math
import re
from copy import deepcopy
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.novel import Novel
from app.repositories.prompt_template import PromptTemplateRepository
from app.services.llm_service import LLMService
from app.services.prop_policy import get_visual_prop_names
from app.services.visual_attention import (
    ATTENTION_RULE, attention_fingerprint, compile_visual_attention,
    consumed_transitions, execution_attention_snapshot, project_visual_attention,
    resolve_subjects, require_current_attention_transitions,
)


VIDEO_AI_STEP_LABELS = {
    "07": "视频模式推荐",
    "08": "视频关键帧规划",
    "09": "关键帧生图提示词构建",
    "10": "关键帧过渡规划",
    "11": "H3 单帧视频提示词构建",
    "12": "H3 首尾帧视频提示词构建",
    "13": "H3 多关键帧视频提示词构建",
}


def safe_json_dict(value: Any) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def safe_json_list(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


MEDIA_REF_KEYS = {"image_url", "image_path", "image_task_id", "reference_image_url", "reference_url", "url", "path"}
CLIP_LLM_EXCLUDED_KEYS = {
    "prompt_text",
    "video_url",
    "local_path",
    "source_video_url",
    "generated_at",
    "generated_by_task_id",
}

_PICTURE_TOKEN_RE = re.compile(r"(?i)(?:<\s*)?Picture\s+(\d+)(?:\s*>)?")
_PICTURE_TIMELINE_RE = re.compile(
    r"(?im)(?:<\s*)?Picture\s+(\d+)(?:\s*>)?\s*=\s*[^\n]*?\bt\s*=\s*(-?\d+(?:\.\d+)?)\s*s?"
)


def build_physical_picture_mapping(video_reference_manifest: Optional[dict]) -> list[dict]:
    """Expose the final ordinary-reference manifest as the only Picture authority."""
    manifest = video_reference_manifest if isinstance(video_reference_manifest, dict) else {}
    references = manifest.get("references") if isinstance(manifest.get("references"), list) else []
    mapping = []
    for expected_index, reference in enumerate(references, 1):
        if not isinstance(reference, dict):
            raise ValueError("PHYSICAL_PICTURE_MANIFEST_INVALID")
        try:
            picture_index = int(reference.get("slot"))
        except (TypeError, ValueError):
            raise ValueError("PHYSICAL_PICTURE_MANIFEST_INVALID")
        if picture_index != expected_index:
            raise ValueError("PHYSICAL_PICTURE_MANIFEST_NOT_DENSE")
        mapping.append({
            "picture_index": picture_index,
            "picture": f"<Picture {picture_index}>",
            "kind": reference.get("kind"),
            "source_type": reference.get("source_type"),
            "source_keyframe_index": reference.get("source_keyframe_index"),
            "source_role": reference.get("source_role"),
            "source_time_seconds": reference.get("source_time_seconds"),
            "source_image_task_id": reference.get("source_image_task_id"),
            "source_identity": reference.get("source_identity") or reference.get("source_id"),
            "source_id": reference.get("source_id"),
            "source_name": reference.get("source_name"),
        })
    return mapping


def attach_physical_picture_mapping(states: list, picture_mapping: list[dict]) -> list[dict]:
    """Attach manifest-derived Picture identity without dropping image-less semantics."""
    by_state_index = {}
    for item in picture_mapping:
        raw_index = item.get("source_keyframe_index")
        if raw_index is None:
            continue
        try:
            state_index = int(raw_index)
        except (TypeError, ValueError):
            raise ValueError("PHYSICAL_PICTURE_SOURCE_IDENTITY_INVALID")
        if state_index in by_state_index:
            raise ValueError("PHYSICAL_PICTURE_SOURCE_IDENTITY_DUPLICATE")
        by_state_index[state_index] = item

    result = []
    for state in states or []:
        if not isinstance(state, dict):
            continue
        projected = dict(state)
        raw_index = projected.get("index")
        try:
            state_index = int(raw_index) if raw_index is not None else None
        except (TypeError, ValueError):
            state_index = None
        if state_index is None:
            result.append(projected)
            continue
        physical = by_state_index.get(state_index)
        projected["semantic_state_label"] = f"KF{state_index}"
        projected["physical_picture_index"] = physical.get("picture_index") if physical else None
        projected["physical_picture"] = physical.get("picture") if physical else None
        projected["physical_reference_status"] = "IMAGE_BACKED" if physical else "TEXT_ONLY"
        result.append(projected)
    return result


def audit_physical_picture_references(final_prompt: str, picture_mapping: list[dict]) -> dict:
    """Reject phantom/missing state Pictures and manifest-time mismatches."""
    allowed = {int(item["picture_index"]) for item in picture_mapping}
    emitted = [int(match.group(1)) for match in _PICTURE_TOKEN_RE.finditer(final_prompt or "")]
    emitted_set = set(emitted)
    invalid = sorted(emitted_set - allowed)
    required_state_pictures = {
        int(item["picture_index"])
        for item in picture_mapping
        if item.get("source_keyframe_index") is not None
    }
    missing = sorted(required_state_pictures - emitted_set)
    expected_times = {
        int(item["picture_index"]): float(
            item.get("prompt_time_seconds", item["source_time_seconds"])
        )
        for item in picture_mapping
        if item.get("source_time_seconds") is not None
    }
    time_mismatches = []
    for match in _PICTURE_TIMELINE_RE.finditer(final_prompt or ""):
        picture_index = int(match.group(1))
        if picture_index not in expected_times:
            continue
        actual_time = float(match.group(2))
        if abs(actual_time - expected_times[picture_index]) > 0.01:
            time_mismatches.append({
                "picture_index": picture_index,
                "expected_time_seconds": expected_times[picture_index],
                "actual_time_seconds": actual_time,
            })
    issues = []
    if invalid:
        issues.append("PHANTOM_PICTURE_REFERENCE")
    if missing:
        issues.append("PHYSICAL_PICTURE_REFERENCE_MISSING")
    if time_mismatches:
        issues.append("PHYSICAL_PICTURE_TIME_MISMATCH")
    return {
        "passed": not issues,
        "issues": issues,
        "physical_picture_count": len(picture_mapping),
        "emitted_picture_indexes": sorted(emitted_set),
        "invalid_picture_indexes": invalid,
        "missing_state_picture_indexes": missing,
        "time_mismatches": time_mismatches,
    }


def _canonical_picture_mapping_contract() -> str:
    return """
CANONICAL PHYSICAL PICTURE MAPPING CONTRACT (highest priority for Picture labels):
- physical_picture_manifest in the user payload is the only authority for <Picture N>.
- Picture numbering is dense, 1-based, and exactly follows physical_picture_manifest order.
- Use each semantic state's physical_picture field exactly. If it is null, describe that state textually by semantic_state_label (for example KF2) and never assign it a Picture number.
- Never derive a Picture number from a canonical state index, array position, role, or time.
- Real non-state resource references also occupy their physical_picture_manifest positions.
- temporal_anchors are separate and never consume ordinary Picture numbers.
- Every Picture reference in the final answer must resolve to physical_picture_manifest; do not emit phantom or out-of-range Picture labels.
""".strip()


def _canonical_speech_contract() -> str:
    return """
CANONICAL SINGLE SPEECH AUTHORITY (highest priority, including Novel overrides):
- dialogue_timeline_source is the sole Clip-local speaker, exact text, language,
  timing and speech-related mouth/lip authority. The program injects it once.
- Output visual direction and non-human environmental/action sound only. Do not
  output dialogue_timeline, exact dialogue, speaker assignments, human vocalization
  permissions or speech-related mouth/lip rules. Describe visual behavior from
  canonical states, transitions and Clip-local time. Do not use dialogue event IDs
  as visual pacing or rhythm markers, or redefine those speech events.
- Pictures, temporal targets, Previous AV and visual prominence never assign speakers.
- With no assigned dialogue the program injects NO_VOICE: no human speech,
  vocalization or invented dialogue, NOT SILENT_AUDIO. Preserve ambience, Foley,
  movement/object sounds and appropriate non-human sound; never mute the audio track.
- Smiles, frowns, mouth-corner changes, clenched teeth, gaze, posture and gestures
  remain legitimate visual facts, not speech permission.
""".strip()


def _canonical_section_ownership_contract() -> str:
    """Give existing H3 sections distinct source ownership, including overrides."""
    return """
CANONICAL H3 SECTION OWNERSHIP (highest priority over template expansion rules):
Use the existing final section names below. Each fact has one owner; other
sections refer to its Subject/KF label instead of paraphrasing or expanding it.
The only owned-state collection is visual_controls. Legacy frames,
ordered_keyframes, keyframes and motion_directive aliases are not supplied.

subject_definitions — SUBJECT_IDENTITY:
Define Subjects in clip_visible_characters order. Use the standard character
name and stable identity features from shot.official_character_appearances once.
Those asset descriptions may contain default outfits and portrait instructions:
do not treat them as current costume, blocking, pose, action or carried objects.
No independent current Shot appearance binding is supplied; do not invent one.
Do not repeat these identity facts in any other section.

official_character_identity_lock — META / HARD CONSTRAINTS:
Only shared identity preservation, allowed Subjects/no new characters or props,
and necessary physical constraints. No repeated identity-feature list, default
costume inventory, state description, action, continuity or temporal target.
Preserve current appearance from actual visual conditioning/canonical states;
default asset appearance must not overwrite it. Express each shared rule once.

keyframe_timeline — CURRENT_VISUAL_STATE / REFERENCE_BINDING / TEMPORAL_TARGET:
Project each owned canonical description once from visual_controls, with its KF
label and Clip-local time. Empty description is not permission to invent a pose:
use its actual physical reference if present. When a state is a selected temporal
target, put its description only in the temporal target entry, not again in an
ordinary state entry. temporal_anchors.target_state_label links to that state;
an unlinked target instead owns its supplied description. Keep exact anchor ID
and Clip-local time; temporal conditioning never consumes a Picture number.
Give each physical_picture_manifest binding once, including non-state references.
State index is not Picture index. Other sections use KF/Subject labels instead
of repeating Picture bindings. No carry-in state dump or future unowned state.

summary — CONTINUITY:
When conditioning.previous_av_present=true and semantic continuity requires it,
Previous AV is the continuity conditioning. State only necessary persistence of
identity, spatial relations, current appearance, held objects and ongoing action
once, without describing the whole previous scene or claiming observed tail pixels.
carry_in_state_index is context, not a newly owned visual state or Picture.
Without Previous AV, refer to the supplied current/start state or actual reference
for grounding; do not claim inheritance. No endpoint recap or action synopsis.

detailed_description — TRANSITION_ACTION:
Use transitions as the sole action/camera-delta source. Their times are Shot-global;
project only the intersection with this Clip and express its Clip-local interval.
Refer to the start/end KF authorities; do not fully redescribe their endpoint
facts, stable identities, continuity rules or selected temporal target. Preserve
all action changes and required prop interactions. With no transitions or new
target, do not invent a multi-interval action script; continue the conditioned
state naturally. Do not pad this section with repeated holds or constraints.

dialogue_timeline — program owned:
The existing deterministic speech contract remains authoritative and unchanged.
Do not output this section or repeat its text, speakers, timing or permissions.

visual_attention_timeline — program owned:
Consume the supplied Clip-local attention windows without redefining them.
Attention constrains narrative emphasis, not speech, motion or body permission.
Background motion alone must not change visual dominance. Camera may compensate
and preserve ensemble relationships; primary does not imply portrait framing or
continuous visibility. Preserve planned smooth handoffs and their clipped progress.
Do not output this section; the compiler supplies it exactly once.

overall_soundscape — SOUNDSCAPE:
Retain grounded non-human ambience and action/object Foley. No speech authority,
dialogue recap, silent-audio instruction, visual-state recap or identity rules.
""".strip()


def _canonical_temporal_controls(anchors: list, states: list) -> list[dict]:
    """Project semantic targets, not physical slots, paths or Task provenance."""
    by_index = {int(state["index"]): state for state in states}
    result = []
    for anchor in anchors or []:
        source = anchor.get("source") or {}
        raw_index = source.get("keyframe_index")
        if raw_index is None and str(source.get("id") or "").startswith("KF"):
            raw_index = str(source["id"])[2:]
        state = by_index.get(int(raw_index)) if raw_index is not None else None
        result.append({
            "anchor_id": anchor.get("anchor_id") or anchor.get("id"),
            # The compiled temporal manifest already uses Clip-local time.
            "time_seconds": anchor.get("time_seconds"),
            "source_keyframe_index": int(raw_index) if raw_index is not None else None,
            # A linked state already owns the full target description. Keep the
            # time/identity binding here, not a second copy of the same facts.
            **({"target_state_label": f"KF{int(raw_index)}"} if state is not None
               else {"description": anchor.get("description")}),
        })
    return result


def strip_media_refs(value: Any) -> Any:
    """Remove concrete media locators before sending data to LLM prompt builders."""
    if isinstance(value, list):
        return [strip_media_refs(item) for item in value]
    if isinstance(value, dict):
        return {
            key: strip_media_refs(item)
            for key, item in value.items()
            if key not in MEDIA_REF_KEYS
        }
    return value


def _strip_keyframe_generation_prompt(value: Any) -> Any:
    """Do not feed an old #09 image prompt back into H3 planning."""
    if isinstance(value, list):
        return [_strip_keyframe_generation_prompt(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _strip_keyframe_generation_prompt(item)
            for key, item in value.items()
            if key != "prompt_text"
        }
    return value


def strip_clip_generation_data(clip: dict) -> dict:
    """Remove generated Clip artifacts before serializing an LLM request."""
    return {
        key: value
        for key, value in (clip or {}).items()
        if key not in CLIP_LLM_EXCLUDED_KEYS
    }


def append_video_ai_call(shot, call: dict) -> dict:
    """Append an AI prompt call snapshot into shot.video_director_plan."""
    plan = safe_json_dict(shot.video_director_plan)
    calls = plan.get("ai_calls") if isinstance(plan.get("ai_calls"), list) else []
    step = str(call.get("step") or "")
    calls.append({
        "step": step,
        "title": call.get("title") or VIDEO_AI_STEP_LABELS.get(step, "AI 调用"),
        "task_type": call.get("task_type"),
        "prompt_template_name": call.get("prompt_template_name"),
        "status": call.get("status") or "success",
        "error_message": call.get("error_message") or call.get("error") or "",
        "input_summary": call.get("input_summary") or "",
        "response": call.get("response") or "",
        "parsed_result": call.get("parsed_result"),
        "final_prompt": call.get("final_prompt"),
        "clip_index": call.get("clip_index"),
        "workflow_type": call.get("workflow_type"),
        "workflow_name": call.get("workflow_name"),
        "reference_images": call.get("reference_images"),
        "created_at": call.get("created_at") or datetime.utcnow().isoformat(),
    })
    plan["ai_calls"] = calls[-80:]
    shot.video_director_plan = json.dumps(plan, ensure_ascii=False)
    return plan


def resolve_prompt_template(db: Session, novel: Novel, template_attr: str, template_type: str):
    repo = PromptTemplateRepository(db)
    template = None
    template_id = getattr(novel, template_attr, None)
    if template_id:
        template = repo.get_by_id(template_id)
    if not template:
        template = repo.get_default_system_template(template_type)
    if not template:
        raise RuntimeError(f"未配置 {template_type} 提示词模板")
    return template


def _strip_voice_rules_from_text(value: Any) -> str:
    """Keep visual direction while removing dialogue authority from motion text."""
    clauses = re.split(r"[，,。！？；;\n]+", str(value or ""))
    voice_rule_patterns = (
        r"(?:所有|全部|其他|其余)?(?:可见)?人物.*保持沉默",
        r"(?:所有|全部|其他|其余)?(?:可见)?角色.*保持沉默",
        r"不说话",
        r"不低语",
        r"不发出(?:任何)?人物语音",
        r"只保留(?:必要的|同步)?环境声",
        r"(?:all|other) characters?.*remain silent",
        r"do not speak",
        r"no (?:dialogue|human voice|voices)",
        r"environmental sounds? only",
    )
    visual_clauses = [
        clause.strip()
        for clause in clauses
        if clause.strip() and not any(re.search(pattern, clause, re.IGNORECASE) for pattern in voice_rule_patterns)
    ]
    visual_text = "；".join(visual_clauses)
    return visual_text.replace("低声说话", "嘴巴微张，表现低声交谈的视觉状态")


def _sanitize_transitions_for_h3(transitions: list) -> list:
    sanitized = strip_media_refs(transitions) or []
    for transition in sanitized:
        if isinstance(transition, dict) and "transition_description" in transition:
            transition["transition_description"] = _strip_voice_rules_from_text(transition.get("transition_description"))
    return sanitized


def _build_clip_motion_directive(shot, clip: dict, transitions: list) -> str:
    clip_label = f"Clip {clip.get('clip_index') or '-'} {clip.get('start_time', '-')}-{clip.get('end_time', '-')}s"
    transition_text = "\n".join(
        f"- {transition.get('transition_description')}"
        for transition in transitions or []
        if isinstance(transition, dict) and transition.get("transition_description")
    )
    return "\n".join([
        f"当前只生成 {clip_label}，不要引入 Clip 时间窗之外的 Shot 级台词或未来状态。",
        "这里只描述视觉动作与镜头运动，以当前 Clip 的关键帧和相邻 transition 为准。",
        transition_text or "无额外 transition 描述。",
    ])


def _dialogue_text(dialogue: dict) -> str:
    return str(dialogue.get("text") or dialogue.get("dialogue") or "").strip()


def _dialogue_speaker(dialogue: dict) -> str:
    return str(dialogue.get("character_name") or dialogue.get("speaker") or dialogue.get("character") or "").strip()


def timeline_matches_shot_dialogues(timeline: list, dialogues: list) -> bool:
    """Check L1 identity with the existing ownership validator, without allocation."""
    from app.services.dialogue_ownership import assign_dialogues_to_clips

    ordered = [(index, item) for index, item in enumerate(dialogues or [])
               if isinstance(item, dict) and _dialogue_text(item)]
    ordered.sort(key=lambda pair: (pair[1].get("order") is None, pair[1].get("order", pair[0]), pair[0]))
    expected_ids = [str(item.get("dialogue_id") or item.get("id") or f"D{order}")
                    for order, (_, item) in enumerate(ordered, 1)]
    if not isinstance(timeline, list) or len(timeline) != len(expected_ids):
        return False
    if not timeline:
        return not expected_ids
    try:
        previous_end = 0.0
        for order, (event, event_id) in enumerate(zip(timeline, expected_ids), 1):
            if not isinstance(event, dict) or str(event.get("id")) != event_id:
                return False
            if "speaker" not in event or "text" not in event or event.get("source_order", order) != order:
                return False
            start, end = float(event["start_time"]), float(event["end_time"])
            if not math.isfinite(start) or not math.isfinite(end) or start < previous_end or end <= start:
                return False
            previous_end = end
        _, validation = assign_dialogues_to_clips(
            dialogues, [{"clip_index": 1, "start_time": 0, "end_time": previous_end}], timeline,
        )
        return validation["passed"]
    except (KeyError, TypeError, ValueError):
        return False


def resolve_canonical_dialogue_timeline(shot, plan: dict | None = None, *, candidate: list | None = None) -> tuple[list, dict]:
    """Resolve SHOT_SECONDS once; never replace an existing L1 authority by estimates.

    This read is pure. Planning callers persist a first candidate only when saving
    their new plan and explicitly pass it to subsequent consumers.
    """
    plan = plan if plan is not None else safe_json_dict(getattr(shot, "video_director_plan", None))
    dialogues = safe_json_list(getattr(shot, "dialogues", None))
    persisted = plan.get("dialogue_timeline_source")
    if persisted is not None and persisted != []:
        if not timeline_matches_shot_dialogues(persisted, dialogues):
            raise ValueError("CANONICAL_DIALOGUE_TIMELINE_INVALID: speaker/text/order/event identity or timing mismatch")
        status = plan.get("dialogue_timeline_status")
        if not isinstance(status, dict) or status.get("status") != "ok":
            status = {"status": "ok", "source": "persisted_official"}
        return persisted, status
    if not any(isinstance(item, dict) and _dialogue_text(item) for item in dialogues):
        return [], plan.get("dialogue_timeline_status") or {"status": "ok"}
    if candidate is not None:
        if not timeline_matches_shot_dialogues(candidate, dialogues):
            raise ValueError("CANONICAL_DIALOGUE_TIMELINE_INVALID")
        return candidate, {"status": "ok", "source": "resolved_candidate"}
    ordered = [(index, item) for index, item in enumerate(dialogues) if isinstance(item, dict) and _dialogue_text(item)]
    ordered.sort(key=lambda pair: (pair[1].get("order") is None, pair[1].get("order", pair[0]), pair[0]))
    timeline, _, status = build_dialogue_timeline(
        {"start_time": 0, "end_time": getattr(shot, "duration", None) or 4},
        [item for _, item in ordered], safe_json_list(getattr(shot, "characters", None)),
    )
    for order, (event, (_, dialogue)) in enumerate(zip(timeline, ordered), 1):
        event["id"] = str(dialogue.get("dialogue_id") or dialogue.get("id") or f"D{order}")
        event["text"] = str(dialogue.get("text") or dialogue.get("dialogue") or "")
    if status.get("status") == "ok" and not timeline_matches_shot_dialogues(timeline, dialogues):
        raise ValueError("CANONICAL_DIALOGUE_TIMELINE_INVALID")
    return timeline, status


def project_resolved_dialogue_timeline(timeline: list, clip: dict, assignments: list) -> list:
    """Derive clip-local intent from L1, retaining existing segment bookkeeping."""
    clip_start, clip_end = float(clip.get("start_time") or 0), float(clip["end_time"])
    by_id = {str(item.get("dialogue_id") or item.get("id")): item for item in assignments or [] if isinstance(item, dict)}
    projected = []
    for event in timeline:
        start, end = max(clip_start, float(event["start_time"])), min(clip_end, float(event["end_time"]))
        if end <= start:
            continue
        event_id = str(event["id"])
        projected.append({
            **by_id.get(event_id, {}),
            "dialogue_id": event_id, "id": event_id,
            "speaker": event["speaker"], "text": event["text"],
            "emotion_prompt": event.get("emotion_prompt") or "",
            "start_time": round(start, 2), "end_time": round(end, 2),
            "local_start_time": round(start - clip_start, 2), "local_end_time": round(end - clip_start, 2),
            "projection_mode": "intersection", "dialogue_timing_source": "official_projection",
            "is_continuation": start > float(event["start_time"]) + 1e-6,
            "continues_in_next_clip": end < float(event["end_time"]) - 1e-6,
        })
    return projected


def build_execution_intent_metadata(timeline: list, clip: dict) -> dict:
    """Optional L3 observability. L1 text/speaker/order/shot timing remain HARD."""
    canonical = [{key: event[key] for key in ("id", "speaker", "text", "start_time", "end_time")} for event in timeline]
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    projected = project_resolved_dialogue_timeline(timeline, clip, [])
    return {
        "execution_intent": {
            "version": 1,
            "canonical_timeline_source": "shots.video_director_plan.dialogue_timeline_source",
            "canonical_timeline_sha256": digest,
            "canonical_time_base": "SHOT_SECONDS",
            "time_base": "CLIP_LOCAL_SECONDS",
            "events": [{"dialogue_id": item["dialogue_id"], "intended_window": {
                "start": item["local_start_time"], "end": item["local_end_time"],
            }} for item in projected],
            "timing_reliability": "soft",
            "speaker_realization_reliability": "soft",
            "visual_support_status": "unknown",
        },
        # Operational APPROVED does not imply dialogue realization QA.
        "realization_review": "unreviewed",
    }


DIALOGUE_VISUAL_INTENT_SECTION = "dialogue_visual_guidance"
DIALOGUE_VISUAL_INTENT_RULE = (
    "dialogue_visual_intents are soft visual execution guidance, separate from canonical speech authority. "
    "Support the referenced canonical speaker's visual participation within the authored composition so the "
    "speaking action remains visually attributable. Preserve shared/reaction composition, the existing reaction "
    "subject, attention handoffs, continuity and camera design. Background participation, two-shots and "
    "over-the-shoulder framing remain valid. This guidance adds no primary-subject, close-up, centering, "
    "exclusive-focus or camera-cut requirement, and no new dialogue, speaker or timing authority. "
    "Visibility, face/mouth readability, lip ownership and actual realization remain unknown. "
    "Do not output or redefine dialogue_visual_guidance; the shared compiler supplies that section."
)


def validate_dialogue_visual_intent(clip: dict, timeline: list, plan: dict) -> dict | None:
    """Validate an optional #10A judgment; never infer it from coverage or roles."""
    if "dialogue_visual_intent" not in clip:
        return None
    value = clip["dialogue_visual_intent"]
    if (not isinstance(value, dict) or set(value) != {"version", "mode", "events"}
            or type(value.get("version")) is not int or value["version"] != 1
            or value.get("mode") != "soft" or not isinstance(value.get("events"), list)):
        raise ValueError("DIALOGUE_VISUAL_INTENT_SCHEMA_INVALID")
    canonical = {event["id"]: event for event in timeline}
    owned = {event["dialogue_id"] for event in project_resolved_dialogue_timeline(timeline, clip, [])}
    catalog = (plan.get("visual_attention") or {}).get("character_catalog") or []
    pairs = set()
    for entry in catalog:
        if not isinstance(entry, dict) or not isinstance(entry.get("character_name"), str):
            continue
        try:
            uid = str(UUID(entry["character_id"]))
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        pairs.add((entry["character_name"], uid))
    seen = set()
    for event in value["events"]:
        if not isinstance(event, dict) or not isinstance(event.get("intent"), str) or event["intent"] not in {
            "SUPPORT_SPEAKER_PARTICIPATION", "PRESERVE_EXISTING",
        }:
            raise ValueError("DIALOGUE_VISUAL_INTENT_ENUM_INVALID")
        support = event["intent"] == "SUPPORT_SPEAKER_PARTICIPATION"
        required = {"dialogue_id", "intent"} | ({"target_character_id"} if support else set())
        if set(event) != required:
            raise ValueError("DIALOGUE_VISUAL_INTENT_EVENT_SCHEMA_INVALID")
        dialogue_id = event["dialogue_id"]
        if not isinstance(dialogue_id, str) or dialogue_id not in canonical:
            raise ValueError("DIALOGUE_VISUAL_INTENT_DIALOGUE_UNKNOWN")
        if dialogue_id not in owned:
            raise ValueError("DIALOGUE_VISUAL_INTENT_OUTSIDE_CLIP")
        if dialogue_id in seen:
            raise ValueError("DIALOGUE_VISUAL_INTENT_DUPLICATE")
        seen.add(dialogue_id)
        if support:
            target = event["target_character_id"]
            try:
                valid_uuid = isinstance(target, str) and str(UUID(target)) == target
            except ValueError:
                valid_uuid = False
            if not valid_uuid or target not in {uid for _, uid in pairs}:
                raise ValueError("DIALOGUE_VISUAL_INTENT_TARGET_UNRESOLVED")
            speaker = canonical[dialogue_id]["speaker"]
            matches = {uid for name, uid in pairs if name == speaker or uid == speaker}
            if matches != {target}:
                raise ValueError("DIALOGUE_VISUAL_INTENT_SPEAKER_TARGET_MISMATCH")
    return deepcopy(value)


def executable_dialogue_visual_intents(clip: dict, timeline: list, plan: dict) -> list:
    """The minimal H3 whitelist: explicit no-ops have no execution projection."""
    value = validate_dialogue_visual_intent(clip, timeline, plan)
    return [event for event in (value or {}).get("events", [])
            if event["intent"] == "SUPPORT_SPEAKER_PARTICIPATION"]


def render_dialogue_visual_guidance(intents: list, projected_dialogues: list, catalog: list, subjects: dict) -> str:
    """Join canonical Clip-local windows and existing Subject bindings, without replanning."""
    if not intents:
        return ""
    events = {event["dialogue_id"]: event for event in projected_dialogues}
    lines = [f"{DIALOGUE_VISUAL_INTENT_SECTION}:", "Soft visual participation guidance; canonical speech authority remains unchanged."]
    for intent in intents:
        event = events[intent["dialogue_id"]]
        names = {entry["character_name"] for entry in catalog
                 if entry["character_id"] == intent["target_character_id"]}
        tokens = {subjects[name] for name in names if name in subjects}
        if len(tokens) != 1:
            raise ValueError("DIALOGUE_VISUAL_INTENT_SUBJECT_UNRESOLVED")
        subject = next(iter(tokens))
        start, end = event["local_start_time"], event["local_end_time"]
        lines.append(
            f"{intent['dialogue_id']} ({start:.2f}–{end:.2f}s, canonical Clip-local projection): "
            f"Support {subject}'s visual participation in the authored composition for visual attribution of "
            "the canonical speaking action. Preserve shared/reaction composition and the existing reaction "
            "subject, attention handoffs, continuity and camera design; background participation, two-shots "
            "and over-the-shoulder framing remain valid. This adds no primary-subject, close-up, centering, "
            "exclusive-focus or camera-cut requirement and no full-interval occupancy requirement. "
            "Actual visibility, face/mouth readability, lip ownership and realization remain unknown."
        )
    return "\n".join(lines)


def read_execution_semantics(metadata: dict | None) -> dict:
    """Read old Clip/Task JSON without migration, mutation, or inferred QA PASS."""
    metadata = metadata or {}
    intent = metadata.get("execution_intent")
    evidence = metadata.get("visual_support_evidence")
    return {
        "execution_intent": intent if isinstance(intent, dict) else {
            "version": "legacy", "canonical_timeline_source": "unknown",
            "canonical_timeline_sha256": None, "time_base": "unknown", "events": [],
            "timing_reliability": "unknown", "speaker_realization_reliability": "unknown",
            "visual_support_status": "unknown",
        },
        "realization_review": metadata.get("realization_review") or "unreviewed",
        "visual_support_evidence": evidence if isinstance(evidence, dict) else {
            "version": "legacy", "status": "unknown", "basis": "unknown", "events": [],
        },
    }


def _dialogue_attention_evidence(projection: dict, character_id: str | None, start: float, end: float) -> dict:
    """Interval coverage and listed UUID roles, never an alignment/quality score."""
    overlaps, uncovered = [], []
    cursor = start
    known = projection.get("status") in {"VALID", "EMPTY", "NO_CLIP_INTERSECTION"}
    for window in projection.get("windows") or []:
        left, right = max(start, window["start_time_seconds"]), min(end, window["end_time_seconds"])
        if left >= right:
            continue
        handoff = window.get("handoff") or {}
        directions = [key for key in ("from", "to") if character_id and character_id in handoff.get(key, [])]
        roles = []
        if character_id is None:
            roles = ["unresolved"]
        else:
            for key, role in (("primary_subjects", "primary"), ("background_motion_subjects", "background_motion")):
                if character_id in window.get(key, []):
                    roles.append(role)
            if directions:
                roles.append("handoff_participant")
            if not roles:
                roles = ["not_listed"]
        overlaps.append({
            "window_id": f"visual_attention.windows[{window['source_window_index']}]",
            "interval": {"start": round(left, 6), "end": round(right, 6)},
            "roles": roles, "handoff_directions": directions,
        })
        if left > cursor:
            uncovered.append({"start": round(cursor, 6), "end": round(left, 6)})
        cursor = max(cursor, right)
    if known and cursor < end:
        uncovered.append({"start": round(cursor, 6), "end": round(end, 6)})
    duration = sum(item["interval"]["end"] - item["interval"]["start"] for item in overlaps)
    return {
        "source_status": projection["status"], "overlaps": overlaps,
        "speaker_identity_status": "resolved" if character_id else "unresolved",
        "coverage_duration": round(duration, 6) if known else None,
        "coverage_ratio": round(duration / (end - start), 6) if known else None,
        "uncovered_intervals": uncovered if known else [],
        "handoff_overlap": any(item["handoff_directions"] for item in overlaps),
    }


def build_dialogue_visual_support_evidence(timeline: list, clip: dict, plan: dict, *,
                                         reference_manifest: dict | None = None,
                                         temporal_anchors: list | None = None,
                                         subject_bindings: list | None = None) -> dict:
    """Read-only PLANNED_METADATA joins. No observed pixels, scoring or decisions.

    States remain point-in-time canonical states, not invented held intervals.
    Only the selected Clip's manifests/anchors are inputs; adjacency is association,
    never proof that a speaker is visible or that H3 will realize the dialogue.
    """
    def number(value):
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        except (TypeError, ValueError):
            return None

    def identity(value):
        try:
            return str(UUID(value)) if isinstance(value, str) else None
        except ValueError:
            return None

    start, end = float(clip.get("start_time") or 0), float(clip["end_time"])
    projection = project_visual_attention(plan.get("visual_attention"), start, end)
    catalog = projection.get("character_catalog") or []
    bindings = subject_bindings if isinstance(subject_bindings, list) else []
    reference_manifest = reference_manifest if isinstance(reference_manifest, dict) else {}
    pairs = {(item.get("character_name"), identity(item.get("character_id")))
             for item in catalog + bindings if isinstance(item, dict)}
    pairs = {(name, uid) for name, uid in pairs if isinstance(name, str) and uid}

    def resolve(value):
        if value in {uid for _, uid in pairs}:
            return value
        matches = {uid for name, uid in pairs if name == value}
        return next(iter(matches)) if len(matches) == 1 else None

    states = []
    for state in plan.get("keyframes") or []:
        if not isinstance(state, dict):
            continue
        time = number(state.get("time_seconds"))
        index = state.get("index")
        if time is not None and type(index) is int:
            states.append((time, index, state))
    states.sort(key=lambda item: (item[0], item[1]))  # Existing chronological identity, not a quality ranking.
    state_times = {index: time for time, index, _ in states}
    references = (reference_manifest or {}).get("references")
    refs = [item for item in references or [] if isinstance(item, dict)] if isinstance(references, list) else []
    complete = (type((reference_manifest or {}).get("version")) is int
                and reference_manifest["version"] == 1 and isinstance(references, list)
                and len(refs) == len(references)
                and all(type(ref.get("slot")) is int and ref["slot"] == slot
                        and ref.get("kind") in {"DIRECTOR_VISUAL_ANCHOR", "CHARACTER_IDENTITY", "SCENE", "PROP"}
                        for slot, ref in enumerate(refs, 1)))

    def reference_identity(ref):
        source = ref.get("source_identity")
        return identity(ref.get("source_id") or (source.get("asset_id") if isinstance(source, dict) else source))

    if any(ref.get("kind") == "CHARACTER_IDENTITY" and not reference_identity(ref) for ref in refs):
        complete = False

    def associations(items, left, right, *, temporal=False):
        records = []
        for ref in items:
            source = ref.get("source") if isinstance(ref.get("source"), dict) else {}
            index = source.get("keyframe_index") if temporal else ref.get("source_keyframe_index")
            time = number(ref.get("time_seconds") if temporal else ref.get("source_time_seconds"))
            if not temporal:
                time = time if time is not None else state_times.get(index)
                time = time - start if time is not None else None
            relation = "unknown" if time is None else "before" if time < left else "after" if time > right else "inside"
            distance = None if time is None else round(max(left - time, time - right, 0), 6)
            records.append({
                "reference_id": str(ref["anchor_id"]) if temporal else f"ordinary:slot:{ref['slot']}" if type(ref.get("slot")) is int else None,
                "reference_type": "TEMPORAL_ANCHOR" if temporal else "DIRECTOR_VISUAL_ANCHOR",
                "source_state_id": f"KF{index}" if index is not None else source.get("id") or None,
                "slot": ref.get("slot"), "time_relationship": relation, "distance_seconds": distance,
            })
        distances = [item["distance_seconds"] for item in records if item["distance_seconds"] is not None]
        for item in records:
            item["nearest"] = item["distance_seconds"] == min(distances) if distances and item["distance_seconds"] is not None else None
        return records

    events = []
    for event in project_resolved_dialogue_timeline(timeline, clip, clip.get("dialogue_assignment") or []):
        left, right = event["local_start_time"], event["local_end_time"]
        shot_left, shot_right = left + start, right + start
        uid = resolve(event["speaker"])
        subjects = {item.get("subject") for item in bindings if isinstance(item, dict)
                    and identity(item.get("character_id")) == uid and item.get("subject")}
        before = [item for item in states if item[0] < shot_left]
        inside = [item for item in states if shot_left <= item[0] <= shot_right]
        after = [item for item in states if item[0] > shot_right]
        related = (before[-1:] + inside + after[:1])
        distances = [max(shot_left - time, time - shot_right, 0) for time, _, _ in related]
        state_records = []
        for time, index, state in related:
            members = state.get("characters", state.get("Characters"))
            basis = "structured_characters"
            if not isinstance(members, list):
                members = _canonical_body_membership(state)
                basis = "canonical_Characters_block" if members is not None else "unknown"
            resolved_members = []
            for member in members if members is not None else []:
                token = (member.get("character_id") or member.get("character_name")) if isinstance(member, dict) else member
                resolved_members.append(resolve(token) if isinstance(token, str) else None)
            membership = "unknown"
            if uid and members is not None:
                if uid in resolved_members:
                    membership = "present"
                elif None not in resolved_members:
                    membership = "absent_from_planned_membership"
            state_records.append({
                "state_id": f"KF{index}", "time_relationship": "before" if time < shot_left else "after" if time > shot_right else "inside",
                "scope": "owned" if index in (clip.get("visual_state_indexes") or []) else "carry_in" if index == clip.get("carry_in_state_index") else "shot_context",
                "planned_speaker_membership": membership, "membership_basis": basis,
            })
        matching_refs = [ref for ref in refs if uid and ref.get("kind") == "CHARACTER_IDENTITY" and reference_identity(ref) == uid]
        selected_anchors = [a for a in temporal_anchors or [] if isinstance(a, dict)
                            and a.get("anchor_id") in (clip.get("temporal_anchor_ids") or [])]
        events.append({
            "dialogue_id": event["dialogue_id"], "segment_index": event.get("segment_index"),
            "resolved_character": {"status": "resolved" if uid else "unresolved", "character_id": uid,
                                   "subject": next(iter(subjects)) if uid and len(subjects) == 1 else None},
            "attention": _dialogue_attention_evidence(projection, uid, left, right),
            "visual_states": {
                "before_state_id": f"KF{before[-1][1]}" if before else None,
                "inside_state_ids": [f"KF{index}" for _, index, _ in inside],
                "after_state_id": f"KF{after[0][1]}" if after else None,
                "nearest_state_ids": [f"KF{index}" for (time, index, _), distance in zip(related, distances) if distance == min(distances)],
                "states": state_records,
            },
            "anchors": {
                "ordinary_visual": associations([r for r in refs if r.get("kind") == "DIRECTOR_VISUAL_ANCHOR"], left, right),
                "temporal": associations(selected_anchors, left, right, temporal=True),
            },
            "identity_reference": {"available": bool(matching_refs) if complete and uid else "unknown",
                                   "reference_ids": [f"ordinary:slot:{ref.get('slot')}" for ref in matching_refs]},
            "speaker_visibility": "unknown", "face_readability": "unknown",
            "mouth_readability": "unknown", "competing_face_salience": "unknown",
        })
    return {
        "version": 1, "basis": "PLANNED_METADATA", "status": "derived", "time_base": "CLIP_LOCAL_SECONDS",
        "events": events,
        "reference_summary": {"manifest_status": "complete" if complete else "unknown",
                              "scene_prop_references": [{"reference_id": f"ordinary:slot:{ref.get('slot')}",
                                                         "reference_type": ref["kind"]} for ref in refs if ref.get("kind") in {"SCENE", "PROP"}]},
    }


def build_dialogue_visual_planning_context(timeline: list, plan: dict, duration: float) -> dict:
    """PRE_PLANNING projection of the B1 core, without future Clip/manifest facts.

    The whole-Shot extent supplies SHOT_SECONDS associations, not proposed Clips.
    Only upstream attention and states are read; historical Clip selections,
    compiled slots and Subject/Picture bindings cannot enter this projection.
    """
    upstream = {key: plan.get(key) for key in ("visual_attention", "keyframes")}
    core = build_dialogue_visual_support_evidence(
        timeline, {"start_time": 0, "end_time": duration}, upstream,
    )
    projection = project_visual_attention(upstream["visual_attention"], 0, duration)
    windows = {f"visual_attention.windows[{w['source_window_index']}]": w for w in projection["windows"]}
    canonical = {str(e.get("dialogue_id") or e.get("id")): e for e in timeline}
    events = []
    for evidence in core["events"]:
        event = canonical[evidence["dialogue_id"]]
        attention = evidence["attention"]
        for overlap in attention["overlaps"]:
            window = windows[overlap["window_id"]]
            overlap.update({key: deepcopy(window.get(key, [] if key != "handoff" else {}))
                            for key in ("primary_subjects", "background_motion_subjects", "handoff")})
        known = (attention["source_status"] in {"VALID", "EMPTY", "NO_CLIP_INTERSECTION"},
                 bool(evidence["visual_states"]["states"]),
                 evidence["resolved_character"]["status"] == "resolved")
        events.append({
            "dialogue_id": evidence["dialogue_id"],
            # Read-only reference to L1; no text copy or output authority.
            "canonical_reference": {"speaker": event["speaker"],
                                    "intended_window": {"start": event["start_time"], "end": event["end_time"]}},
            "source_status": "available" if all(known) else "partial" if any(known) else "unknown",
            "resolved_character": {key: evidence["resolved_character"][key] for key in ("status", "character_id")},
            "attention": attention, "visual_states": evidence["visual_states"],
            "identity_reference": {"available": "unknown", "source_status": "unavailable_at_planning"},
            "anchor_evidence": {"source_status": "unavailable_at_planning"},
            **{key: evidence[key] for key in ("speaker_visibility", "face_readability", "mouth_readability", "competing_face_salience")},
        })
    statuses = {e["source_status"] for e in events}
    return {
        "version": 1, "basis": "PLANNED_METADATA", "phase": "PRE_PLANNING", "time_base": "SHOT_SECONDS",
        "canonical_timeline_source": "shots.video_director_plan.dialogue_timeline_source",
        "source_status": "available" if not statuses or statuses == {"available"} else "unknown" if statuses == {"unknown"} else "partial",
        "character_catalog": projection["character_catalog"], "events": events,
    }


def align_clip_boundaries_to_dialogue_gaps(
    clips: list,
    dialogue_timeline: list,
    max_clip_duration: float | None = None,
    min_clip_duration: float | None = None,
) -> list:
    """Move generation boundaries out of active speech intervals when possible."""
    if not isinstance(clips, list) or len(clips) < 2 or not dialogue_timeline:
        return clips
    intervals = []
    for item in dialogue_timeline:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start_time"))
            end = float(item.get("end_time"))
        except (TypeError, ValueError):
            continue
        if end > start:
            intervals.append((start, end))
    if not intervals:
        return clips
    intervals.sort()
    ordered = sorted(clips, key=lambda item: float(item.get("start_time") or 0))
    for left, right in zip(ordered, ordered[1:]):
        boundary = float(left.get("end_time") or 0)
        if not any(start < boundary < end for start, end in intervals):
            continue
        previous_start = float(left.get("start_time") or 0)
        next_end = float(right.get("end_time") or boundary)
        candidates = sorted({
            endpoint
            for start, end in intervals
            for endpoint in (start, end)
            if previous_start < endpoint < next_end
        }, key=lambda endpoint: abs(endpoint - boundary))
        for candidate in candidates:
            left_duration = candidate - previous_start
            right_duration = next_end - candidate
            if max_clip_duration is not None and (left_duration > max_clip_duration + 1e-6 or right_duration > max_clip_duration + 1e-6):
                continue
            if min_clip_duration is not None and (left_duration < min_clip_duration - 1e-6 or right_duration < min_clip_duration - 1e-6):
                continue
            left["end_time"] = round(candidate, 2)
            right["start_time"] = round(candidate, 2)
            break
    return clips


def _estimate_dialogue_seconds(text: str, emotion_prompt: str = "") -> float:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    other_words = len(re.findall(r"[A-Za-z0-9]+", text or ""))
    units = chinese_chars + other_words
    if units <= 0:
        return 0
    # This is a speech-only heuristic, calibrated against Qwen3-TTS samples.
    # Reaction time and turn-taking gaps belong to timeline allocation.
    return max(0.5, units / 4.0)


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip_visible_characters(keyframes: list, shot_characters: list) -> list:
    visible = []
    for keyframe in keyframes or []:
        description = str(keyframe.get("description") or "") if isinstance(keyframe, dict) else ""
        match = re.search(r"(?:^|\n)Characters:\s*\n((?:[ \t]*-[^\n]+\n?)*)", description)
        if not match:
            continue
        for character in re.findall(r"(?m)^\s*-\s*([^:\n]+):", match.group(1)):
            name = character.strip()
            if name and name not in visible:
                visible.append(name)
    return visible or shot_characters


def build_dialogue_timeline(clip: dict, clip_dialogues: list, shot_characters: list) -> tuple[list, list, dict]:
    clip_start = float(clip.get("start_time") or 0)
    clip_end = float(clip.get("end_time") or clip_start)
    if clip_end <= clip_start:
        clip_end = clip_start + max(1, float(clip.get("duration") or 1))
    clip_duration = max(0.1, clip_end - clip_start)

    projected_dialogues = [
        item for item in clip_dialogues or []
        if isinstance(item, dict) and (item.get("projection_mode") == "intersection" or item.get("dialogue_timing_source") == "official_projection")
    ]
    if projected_dialogues:
        assigned = []
        for index, dialogue in enumerate(projected_dialogues, 1):
            try:
                shot_start = max(clip_start, float(dialogue.get("start_time")))
                shot_end = min(clip_end, float(dialogue.get("end_time")))
            except (TypeError, ValueError):
                continue
            if shot_end <= shot_start:
                continue
            start = float(dialogue.get("local_start_time")) if dialogue.get("local_start_time") is not None else shot_start - clip_start
            end = float(dialogue.get("local_end_time")) if dialogue.get("local_end_time") is not None else shot_end - clip_start
            speaker = _dialogue_speaker(dialogue)
            text = _dialogue_text(dialogue)
            if not speaker or not text:
                continue
            duration = round(end - start, 2)
            assigned.append({
                "id": str(dialogue.get("dialogue_id") or dialogue.get("id") or f"D{index}"),
                "speaker": speaker,
                "text": text,
                "start_time": round(start, 2),
                "end_time": round(end, 2),
                "shot_start_time": round(shot_start, 2),
                "shot_end_time": round(shot_end, 2),
                "duration": duration,
                "estimated_speech_duration": duration,
                "min_required_duration": duration,
                "duration_sufficient": True,
                "emotion_prompt": str(dialogue.get("emotion_prompt") or dialogue.get("emotion") or ""),
                "segment_index": int(dialogue.get("segment_index") or 1),
                "is_continuation": bool(dialogue.get("is_continuation")),
                "continues_in_next_clip": bool(dialogue.get("continues_in_next_clip")),
            })
        authorized_speakers = {item["speaker"] for item in assigned if item["speaker"] != "旁白"}
        silent_characters = [character for character in shot_characters if character not in authorized_speakers]
        return assigned, silent_characters, {
            "status": "ok",
            "source": "official_projection",
            "estimated_speech_duration": round(sum(item["duration"] for item in assigned), 2),
            "dialogue_gap_duration": 0.0,
            "lead_in_duration": 0.0,
            "overflow_seconds": 0.0,
        }

    assigned = []
    lead_in = min(1.0, clip_duration * 0.1)
    cursor = clip_start + lead_in
    overflow = False
    overflow_seconds = 0.0
    estimated_speech_total = 0.0
    dialogue_count = 0
    for index, dialogue in enumerate(clip_dialogues or [], 1):
        if not isinstance(dialogue, dict):
            continue
        text = (
            str(dialogue.get("text") or dialogue.get("dialogue") or "")
            if dialogue.get("dialogue_id")
            else _dialogue_text(dialogue)
        )
        speaker = _dialogue_speaker(dialogue)
        if not text or not speaker:
            continue
        emotion_prompt = str(dialogue.get("emotion_prompt") or dialogue.get("emotion") or "")
        min_duration = _estimate_dialogue_seconds(text, emotion_prompt)
        estimated_speech_total += min_duration
        dialogue_count += 1
        raw_start = next((
            parsed
            for key in ("start_time", "start", "time", "timestamp")
            if (parsed := _float_or_none(dialogue.get(key))) is not None
        ), None)
        raw_end = next((
            parsed
            for key in ("end_time", "end")
            if (parsed := _float_or_none(dialogue.get(key))) is not None
        ), None)
        raw_duration = _float_or_none(dialogue.get("duration"))
        # Honor explicit times only when they do not overlap the preceding
        # allocated dialogue (including its turn-taking gap).
        start = max(cursor, raw_start) if raw_start is not None else cursor
        if start < clip_start:
            start = clip_start
        if start > clip_end:
            overflow = True
            overflow_seconds = max(overflow_seconds, start + min_duration - clip_end)
            continue
        has_authoritative_end = raw_end is not None and raw_end > start
        has_authoritative_duration = raw_duration is not None and raw_duration > 0
        if has_authoritative_end:
            end = raw_end
        elif has_authoritative_duration:
            end = start + raw_duration
        else:
            end = start + min_duration
        if not has_authoritative_end and not has_authoritative_duration and end - start < min_duration:
            end = start + min_duration
        if end > clip_end:
            overflow = True
            overflow_seconds = max(overflow_seconds, end - clip_end)
            continue
        if end <= start:
            start = clip_start
            end = clip_end

        actual_duration = max(0, end - start)
        timeline_item = {
            "id": str(dialogue.get("dialogue_id") or f"D{index}"),
            "speaker": speaker,
            "text": text,
            "start_time": round(start, 2),
            "end_time": round(end, 2),
            "duration": round(actual_duration, 2),
            "estimated_speech_duration": round(min_duration, 2),
            # Backward-compatible field for existing planner consumers.
            "min_required_duration": round(min_duration, 2),
            "duration_sufficient": actual_duration + 0.05 >= min_duration,
            "emotion_prompt": emotion_prompt,
        }
        if dialogue.get("dialogue_id"):
            timeline_item["segment_index"] = int(dialogue.get("segment_index") or 1)
            timeline_item["is_continuation"] = bool(dialogue.get("is_continuation"))
            timeline_item["continues_in_next_clip"] = bool(dialogue.get("continues_in_next_clip"))
        assigned.append(timeline_item)
        cursor = end + 0.2

    # Never return a partial or clamped timeline as an official speaking-state
    # authority. Callers receive an explicit warning and an empty authority.
    timeline_status = {
        "status": "overflow" if overflow else "ok",
        "estimated_speech_duration": round(estimated_speech_total, 2),
        "dialogue_gap_duration": round(max(0, dialogue_count - 1) * 0.2, 2),
        "lead_in_duration": round(lead_in, 2),
        "overflow_seconds": round(overflow_seconds, 2),
    }
    if overflow:
        assigned = []

    authorized_speakers = {
        item["speaker"]
        for item in assigned
        if item.get("speaker") and item["speaker"] != "旁白"
    }
    silent_characters = [
        character
        for character in shot_characters
        if character not in authorized_speakers
    ]
    return assigned, silent_characters, timeline_status


def _exact_spoken_text(value: str) -> str:
    """Remove punctuation used to quote a whole utterance, not its spoken content."""
    text = str(value or "").strip()
    while len(text) >= 2 and (text[0], text[-1]) in {("“", "”"), ('"', '"')}:
        text = text[1:-1].strip()
    return text


def _subject_bindings(prompt: str, visible_characters: list) -> dict:
    """Bind the injected speech timeline to the same visible Subject order as #13."""
    bindings = {name: f"<Subject {index}>" for index, name in enumerate(visible_characters, 1)}
    for subject, name in re.findall(r"(<Subject\s+\d+>)\s+is\s+([^,\n.;—]+)", prompt):
        name = name.strip()
        if name in bindings and subject != bindings[name]:
            raise ValueError(f"#13 Subject mapping conflicts with clip_visible_characters: {name}")
    return bindings


def prepare_clip_visual_attention(plan, clip, shot_characters, *, keyframes=None,
                                  transitions=None, manifest=None, duration=None):
    """Use the existing H3 visible-character order for attention, including reuse."""
    if keyframes is None:
        owned = clip.get("visual_state_indexes", clip.get("keyframe_indexes"))
        keyframes = [state for state in plan.get("keyframes", []) if isinstance(state, dict)
                     and (owned is None or state.get("index") in owned)]
    if "visual_state_indexes" in clip:
        keyframes = [state for state in keyframes if state.get("index") in clip["visual_state_indexes"]]
    visible = _clip_visible_characters(keyframes, shot_characters)
    projection = project_visual_attention(plan.get("visual_attention"), clip.get("start_time", 0),
                                          clip.get("end_time", duration or 0), duration=duration)
    if projection["status"] == "ABSENT":
        validation = (plan.get("validation") or {}).get("visual_attention") or {}
        if validation.get("status") == "FALLBACK_INVALID":
            projection.update(status="FALLBACK_INVALID", findings=validation.get("findings") or [])
    if len(visible) != len(set(visible)):
        projection.update(status="FALLBACK_INVALID", windows=[], findings=["AMBIGUOUS_VISIBLE_CHARACTERS"])
    projection = resolve_subjects(projection, _subject_bindings("", visible), manifest)
    if transitions is None:
        transitions = (consumed_transitions(plan, clip) if "visual_state_indexes" in clip
                       else plan.get("transitions") or [])
    projection["fingerprint"] = attention_fingerprint(projection, transitions)
    return projection


def _canonical_character_roles(state: dict | None) -> dict:
    """Read the existing canonical Characters block, without body detection."""
    description = str((state or {}).get("description") or "")
    block = re.search(r"(?:^|\n)Characters:\s*\n((?:[ \t]*-[^\n]+\n?)*)", description)
    return {
        name.strip(): role.strip()
        for name, role in re.findall(r"(?m)^\s*-\s*([^:\n]+):[ \t]*([^\n]*)", block.group(1) if block else "")
    }


def _canonical_body_membership(state: dict | None) -> set | None:
    """An explicit canonical Characters block is membership, not inferred prose."""
    description = str((state or {}).get("description") or "")
    block = re.search(r"(?:^|\n)Characters:\s*\n((?:[ \t]*-[^\n]+\n?)*)", description)
    if not block:
        return None
    roles = _canonical_character_roles(state)
    if len(roles) != len(block.group(1).splitlines()):
        return None
    return set(roles)


def _canonical_body_lifecycle(name: str, subject: str, current: dict | None,
                              visual_states: list, transitions: list, subjects: dict) -> tuple:
    """Classify the carried-in body and next canonical state using exact actors."""
    start = _canonical_body_membership(current)
    targets = sorted(visual_states, key=lambda state: (state.get("time_seconds") or 0, state.get("index") or 0))
    target = targets[0] if targets else None
    end = _canonical_body_membership(target)
    unknown = ("CANONICAL_BODY_PRESENCE_UNKNOWN", None)
    if start is None or end is None:
        return unknown
    if name in start and name in end:
        return "EXISTING_CURRENT_BODY", None
    if (name in start) == (name in end):
        return unknown
    if current.get("index") is None or target.get("index") is None:
        return unknown
    entering = name not in start
    event = re.compile(
        r"进入|走入|走进|步入|入场|到达|抵达|\b(?:enters?|entering|arrives?|arriving)\b" if entering else
        r"离开|走出|退出|离场|\b(?:exits?|exiting|leaves?|leaving|left)\b", re.IGNORECASE)
    actor = re.compile(rf"^(?:{re.escape(name)}|{re.escape(subject)})(?![A-Za-z0-9_])")
    excluded = re.compile(
        r"不|未|没有|不得|禁止|已|已经|手|手臂|头|目光|视线|镜面|袍摆|"
        r"\b(?:not|never|without|already|no longer|hands?|arms?|head|gaze|eyes|mirror|hem)\b", re.IGNORECASE)
    for transition in transitions:
        if (transition.get("from_keyframe_index") != current.get("index") or
                transition.get("to_keyframe_index") != target.get("index")):
            continue
        for clause in re.split(r"[，。；.!?;\n]", str(transition.get("transition_description") or "")):
            owner = actor.match(clause.strip())
            if not owner:
                continue
            action = clause.strip()[owner.end():]
            match = event.search(action)
            if not match:
                continue
            prefix = action[:match.start()]
            if excluded.search(prefix) or any(
                    other in prefix or token in prefix for other, token in subjects.items() if other != name):
                continue
            return ("ENTERING_NEW_BODY" if entering else "EXITING_CURRENT_BODY"), {
                "from_state": current["index"], "to_state": target["index"], "clause": clause.strip()}
    return unknown


def compile_h3_reference_bindings(
    picture_mapping: list, subject_bindings: dict, visual_states: list, transitions: list,
    *, capability: str, previous_av_present: bool, current_visual_state: dict | None = None,
) -> dict:
    """Join the existing Picture and Subject authorities; never select physical inputs."""
    continuation = capability in {"EXTEND", "TEMPORAL_EXTEND"} and previous_av_present
    current = current_visual_state if continuation else (visual_states[0] if visual_states else None)
    roles = _canonical_character_roles(current)
    body_state = f"KF{current['index']}" if current and current.get("index") is not None else None
    characters, resources, findings = [], [], []
    for picture in picture_mapping:
        identity = picture.get("source_identity")
        identity = identity if isinstance(identity, dict) else {}
        name = picture.get("source_name") or identity.get("name")
        asset_id = picture.get("source_id") or identity.get("asset_id")
        item = {"picture": picture["picture"], "kind": picture.get("kind"), "asset_id": asset_id, "name": name}
        if item["kind"] == "CHARACTER_IDENTITY":
            subject = subject_bindings.get(name)
            if not subject or not asset_id:
                findings.append({"code": "CHARACTER_PICTURE_IDENTITY_UNRESOLVED", **item})
                continue
            lifecycle, lifecycle_transition = _canonical_body_lifecycle(
                name, subject, current, visual_states, transitions, subject_bindings,
            ) if continuation else ("INITIAL_DIRECTOR_BODY", None)
            characters.append({
                **item, "subject": subject, "body_state_id": body_state,
                "body_role": roles.get(name),
                "body_binding": lifecycle,
                **({"body_lifecycle_transition": lifecycle_transition} if lifecycle_transition else {}),
            })
            if lifecycle == "CANONICAL_BODY_PRESENCE_UNKNOWN":
                findings.append({"code": "CANONICAL_BODY_PRESENCE_UNKNOWN", "character": name, "subject": subject})
        elif item["kind"] in {"SCENE", "PROP", "DIRECTOR_VISUAL_ANCHOR"}:
            resources.append({**item, "source_keyframe_index": picture.get("source_keyframe_index")})

    # Explicit actor-led displacement clauses only. No camera motion, target-name
    # attribution, past arrival, inferred pose motion, or arbitrary text segmentation.
    displacement = re.compile(
        r"走向|走近|走到|走出|走入|走进|走过|走离|步入|迈向|迈步|后退|退后|跨过|穿过|进入|离开|移至|移动到|从[^，。；.!?;\n]{1,40}移到|"
        r"\b(?:walks?|walking|enters?|entering|approaches?|approaching|crosses|crossing|steps? away|moves? (?:toward|towards|from|to))\b",
        re.IGNORECASE,
    )
    negated_or_completed = re.compile(r"(?:不|未|没有|不得|禁止|已|已经)|\b(?:not|never|without|already|no longer)\b", re.IGNORECASE)
    local_part = re.compile(r"手|手臂|头|目光|视线|镜面|袍摆|\b(?:hands?|arms?|head|gaze|eyes|mirror|hem)\b", re.IGNORECASE)
    motion = {name: {"subject": subject, "name": name, "motion_class": "LOCAL_MOTION / SPATIALLY_ANCHORED", "evidence": []}
              for name, subject in subject_bindings.items()}
    actors = sorted(subject_bindings, key=len, reverse=True)
    motion_sources = list(transitions)
    for state in visual_states:
        action = re.search(r"(?m)^Action:\s*(.*)$", str(state.get("description") or ""))
        if action:
            motion_sources.append({"transition_description": action.group(1), "from_keyframe_index": state.get("index"), "to_keyframe_index": state.get("index")})
    for transition in motion_sources:
        text = str(transition.get("transition_description") or "")
        for clause in re.split(r"[，。；.!?;\n]", text):
            clause = clause.strip()
            actor = next((name for name in actors if (
                clause.startswith(name) and not (
                    name[-1:].isascii() and clause[len(name):len(name) + 1].isascii()
                    and clause[len(name):len(name) + 1].isalnum()
                )
            ) or clause.startswith(subject_bindings[name])), None)
            if not actor:
                continue
            prefix = actor if clause.startswith(actor) else subject_bindings[actor]
            action = clause[len(prefix):]
            match = displacement.search(action)
            if match and any(name in action[:match.start()] or subject in action[:match.start()]
                             for name, subject in subject_bindings.items() if name != actor):
                findings.append({"code": "MOTION_OWNER_AMBIGUOUS", "clause": clause,
                                 "action": "Do not infer translation from another Subject's action"})
                continue
            if match and not negated_or_completed.search(action[:match.start()]) and not local_part.search(action[:match.start()]):
                motion[actor]["motion_class"] = "TRANSLATIONAL_MOTION"
                motion[actor]["evidence"].append({
                    "from_state": transition.get("from_keyframe_index"),
                    "to_state": transition.get("to_keyframe_index"), "clause": clause,
                })
    if continuation and not body_state:
        findings.append({"code": "CURRENT_BODY_STATE_UNAVAILABLE", "action": "Do not infer body placement or presence"})
    return {"characters": characters, "resources": resources, "subjects": dict(subject_bindings),
            "continuation": continuation, "motion_ownership": list(motion.values()), "findings": findings}


def render_h3_reference_bindings(binding: dict) -> str:
    """Render only compiler-owned identities and motion classes, not speech rules."""
    if not binding["subjects"] and not binding["resources"]:
        return ""
    lines = [
        "reference_authority:",
        "This compiler-owned mapping is the only Picture-to-Character-to-Subject binding authority; Picture numbers never imply Subject numbers.",
        "Character Pictures provide stable face, age, facial structure, hair and personal identity only. Do not copy clothing, pose, position, action, blocking, portrait background or incidental props; they do not assign prop ownership.",
        "Current canonical temporal state (and Previous AV when present) owns current bodies, clothing, position, pose, blocking, action state and prop ownership. Director visual states own their initial/target composition and staging; temporal targets own their future state at the supplied timing.",
    ]
    for item in binding["resources"]:
        if item["kind"] == "SCENE":
            rule = "environment identity and appearance only; incidental people are not additional Subjects"
        elif item["kind"] == "PROP":
            rule = "prop identity/appearance only; current canonical state decides who owns/holds it and where it is"
        else:
            rule = "director visual state, composition and staging; preserve its canonical current/target state"
        lines.append(f"{item['picture']} — {item['kind']} / {item['name'] or 'KF' + str(item['source_keyframe_index'])}: {rule}.")
    if binding["characters"]:
        lines += ["", "character_identity_binding:"]
    for item in binding["characters"]:
        lines.append(f"{item['picture']} ↔ {item['subject']} — {item['name']} (Character asset {item['asset_id']}): identity only, exclusively for this Subject.")
    if binding["characters"]:
        lines += ["", "existing_body_binding:" if binding["continuation"] else "initial_body_binding:"]
    for item in binding["characters"]:
        if binding["continuation"]:
            source = f"Previous AV and canonical {item['body_state_id']}" if item["body_state_id"] else "Previous AV/current canonical state"
            lifecycle = item["body_binding"]
            if lifecycle in {"ENTERING_NEW_BODY", "EXITING_CURRENT_BODY"}:
                edge = item["body_lifecycle_transition"]
                transition = f"KF{edge['from_state']}→KF{edge['to_state']}"
                target = f"KF{edge['to_state']}"
                identity = f"{item['subject']} — {item['name']}"
                if lifecycle == "ENTERING_NEW_BODY":
                    lines.append(
                        f"{identity} is absent from the carried-in start state {item['body_state_id']}. "
                        f"Exactly one body enters during the assigned {transition} transition. "
                        f"{item['picture']} defines the identity of that entering body only. "
                        f"The entering body and its target-state body in {target} are the same continuous body. "
                        "The temporal target must not instantiate a separate copy. "
                        "After arrival, the same body remains the sole body of this Subject; do not perform another entry or create a second body.")
                else:
                    lines.append(
                        f"Apply {item['picture']} identity to the existing/current body of {identity}, defined by {source}. "
                        f"Exactly this same body exits during the assigned {transition} transition. "
                        f"This Subject is absent from {target}; after exit, do not reinstantiate it or create a replacement body.")
                continue
            presence = "existing/current" if item["body_binding"] == "EXISTING_CURRENT_BODY" else "single canonical (existing or explicitly entering)"
            lines.append(f"Apply {item['picture']} identity to the {presence} body of {item['subject']} — {item['name']}, defined by {source}. Do not create a second body or transfer this identity to another visible body.")
        else:
            lines.append(f"Apply {item['picture']} identity to the initial body/role of {item['subject']} — {item['name']} in the Director visual state {item['body_state_id'] or 'at Clip start'}. Preserve its clothing, pose and blocking; no Previous AV body is assumed.")
    lines += ["", "motion_ownership:",
              "Only an explicitly assigned Subject owns its translation; nearby Subjects do not inherit it. Camera motion does not assign body motion.",
              "LOCAL_MOTION / SPATIALLY_ANCHORED permits breathing, gaze/head turns, hand movements, natural posture adjustments and handling currently owned props, while preserving floor position/blocking; it does not freeze a person."]
    for item in binding["motion_ownership"]:
        sources = ", ".join(dict.fromkeys(f"KF{e['from_state']}→KF{e['to_state']}" for e in item["evidence"]))
        lines.append(f"{item['subject']} — {item['name']}: {item['motion_class']}" + (f"; owns only the displacement assigned in {sources}." if sources else "; no explicit translational assignment."))
    return "\n".join(lines)


def _render_dialogue_timeline_block(assigned_dialogues: list, silent_characters: list, subject_bindings: dict | None = None) -> str:
    subject_bindings = subject_bindings or {}
    if not assigned_dialogues:
        lines = [
            "dialogue_timeline:",
            "No assigned dialogue. No character is authorized to speak throughout this clip.",
            "NO_VOICE: no human speech, no human vocalization, no invented dialogue.",
            "No Subject may visibly perform speech-like mouth or lip articulation throughout this clip; natural breathing, blinking, facial expression, jaw relaxation and non-speech facial movement remain allowed.",
        ]
        if silent_characters:
            lines.append("silent_characters: " + ", ".join(subject_bindings.get(name, name) for name in silent_characters))
        lines.append("NO_VOICE is not SILENT_AUDIO. This human-voice restriction does not mute the audio track; environmental ambience and synchronized Foley remain audible, including movement, object interaction and appropriate non-human sounds.")
        return "\n".join(lines)
    lines = [
        "dialogue_timeline:",
        "This is the only source of exact spoken text in this prompt.",
        "Speak only the exact text spans assigned to this Clip; never repeat dialogue completed in a Previous AV.",
        "All assigned dialogue is Mandarin Chinese only. Do not translate, paraphrase, repeat, prepend or append words, invent syllables or produce other languages or extra human voices.",
        "Human vocalization and dialogue-related lip synchronization begin with the first authorized character and end with the last; no lead-in or trailing vocalization. Between assigned events no Subject has speech permission. Environmental ambience and synchronized Foley remain audible.",
        "Before the first assigned event and after the last, no Subject may visibly perform speech-like mouth or lip articulation. Natural breathing, blinking, facial expression, jaw relaxation and non-speech facial movement remain allowed.",
    ]
    for index, item in enumerate(assigned_dialogues):
        if index and item["start_time"] > assigned_dialogues[index - 1]["end_time"]:
            lines.append(f"From {assigned_dialogues[index - 1]['end_time']}s to {item['start_time']}s between dialogue events, no Subject may visibly perform speech-like mouth or lip articulation.")
        subject = subject_bindings.get(item["speaker"])
        if not subject:
            raise ValueError(f"No visible Subject mapping for dialogue speaker: {item['speaker']}")
        continuation = " This is a continuation of the same utterance; do not restart or repeat its earlier part." if item.get("is_continuation") else ""
        next_continuation = " This utterance continues into the next Clip." if item.get("continues_in_next_clip") else ""
        lines.extend([
            f"{item['id']}:",
            f"  speaker: {subject}",
            f"  start_time: {item['start_time']}s",
            f"  end_time: {item['end_time']}s",
            f"  exact_dialogue: {_exact_spoken_text(item['text'])}",
            f"  segment: {item.get('segment_index', 1)}; {continuation.strip()}{next_continuation}" if item.get("segment_index", 1) > 1 or item.get("continues_in_next_clip") else "  segment: complete assigned span.",
            f"  Only {subject} may produce human vocalization and visibly articulate speech during this event; synchronize this Subject's mouth/lip movement to the exact assigned Mandarin dialogue and event timing. All other Subjects remain non-vocal and must not visibly perform speech-like mouth or lip articulation. Do not speak metadata labels. No subtitles, captions, or on-screen text.",
        ])
    if silent_characters:
        lines.append("silent_characters: " + ", ".join(subject_bindings.get(name, name) for name in silent_characters))
    lines.append("All non-assigned characters remain silent; only refer to assigned dialogue IDs outside this block.")
    return "\n".join(lines)


def _remove_generated_dialogue_timeline(prompt: str) -> str:
    """The LLM supplies visual direction; only the assembly supplies speech."""
    return re.sub(
        r"(?ims)^dialogue_timeline:\s*\n.*?(?=^(?:subject_definitions|official_character_identity_lock|keyframe_timeline|summary|detailed_description|overall_soundscape|shot_continuity_lock):|\Z)",
        "",
        prompt or "",
    ).strip()


def _remove_canonical_h3_internal_self_check(prompt: str) -> str:
    """Exclude the explicit internal checklist tail from executable H3 text."""
    return re.split(
        r"(?m)^[ \t]*【输出前内部自检】[ \t\r]*$",
        prompt,
        maxsplit=1,
    )[0].rstrip()


def _remove_dialogue_text_from_builder_body(prompt: str, assigned_dialogues: list) -> str:
    body = prompt or ""
    for item in assigned_dialogues:
        text = _exact_spoken_text(item.get("text"))
        for variant in (item.get("text") or "", text):
            if variant:
                body = body.replace(f"“{variant}”", f"assigned dialogue {item['id']}")
                body = body.replace(f"\"{variant}\"", f"assigned dialogue {item['id']}")
                body = body.replace(variant, f"assigned dialogue {item['id']}")
    return body.strip()


def _insert_canonical_dialogue_timeline(builder_body: str, timeline_block: str) -> str:
    """Place deterministic speech before the first creative output section."""
    boundary = re.search(r"(?m)^(?:summary|detailed_description|overall_soundscape):", builder_body)
    if boundary is None:
        return f"{builder_body}\n\n{timeline_block}".strip()
    return (
        f"{builder_body[:boundary.start()].rstrip()}\n\n{timeline_block}\n\n"
        f"{builder_body[boundary.start():].lstrip()}"
    ).strip()


def _project_canonical_soundscape(prompt: str) -> str:
    """Keep model-owned non-speech audio, not references to speech authority."""
    safe_references = (
        r"(?:除|除了)(?:时间线中(?:的)?|已授权(?:的)?|上述(?:的)?)?(?:对白|人声|语音)(?:之)?外",
        r"(?:不得|禁止|不允许|没有|无)\s*(?:出现|添加|加入|产生)?\s*(?:其他|额外|背景)?(?:的)?(?:人声|说话者|对白|语音)",
        r"(?:前景|已授权(?:的)?|时间线中(?:的)?)(?:人声|对白|语音)(?:之外|以外)的(?=声响|声音|环境声)",
        r"(?:对白|已授权(?:的)?人声)(?:保持|位于|处于)(?:在)?前景(?:清晰|中央|突出)?",
        r"\b(?:no|without)\s+(?:extra|additional|background)\s+(?:human\s+)?(?:voices?|speech|speakers?)\b",
        r"\b(?:the\s+)?(?:authorized\s+)?dialogue\s+remains\s+(?:in\s+the\s+)?foreground\b",
    )

    def project(match: re.Match) -> str:
        header, soundscape = match.group(1), match.group(2)
        # An affirmative speech event must reach the final audit unchanged.
        if _canonical_visual_body_speech_issues(soundscape):
            return match.group(0)
        projected = soundscape
        for pattern in safe_references:
            projected = re.sub(pattern, "", projected, flags=re.IGNORECASE)
        if projected == soundscape:
            return match.group(0)
        projected = re.sub(r"(?m)^[，,；;]+\s*", "", projected)
        projected = re.sub(r"[，,；;]\s*(?=[，,；;。.!?]|$)", "", projected)
        projected = projected.strip(" \t\r\n，,；;。.!?")
        if not projected:
            projected = "环境声与同步动作声保持可听"
        return header + projected + "。"

    return re.sub(
        r"(?ims)(^overall_soundscape:\s*\n)(.*?)(?=^[a-z_][\w ]*:\s*(?:\n|$)|\Z)",
        project, prompt, count=1,
    )


def _canonical_visual_body_speech_issues(body: str, subject_bindings: dict | None = None) -> list[str]:
    """Narrow explicit speech assertions only; not a visual-expression/NLP filter."""
    speech = re.compile(
        r"\b(?:speaks?|speaking|talks?|talking|says?|answers?|replies?|whispers?|whispering|"
        r"shouts?|shouting|laughs?|laughing|laughter|"
        r"mumbles?|mumbling|murmuring|(?:background|crowd|off[- ]screen)\s+"
        r"(?:chatter|conversations?|speech|voices?|repl(?:y|ies))|"
        r"conversations?|chatter|reply|replies|replying|"
        r"lip[ -]?sync(?:s|ing|hronization)?|vocalizes?|vocalizing|"
        r"(?:assigned|authorized|only)\s+speaker)\b|"
        r"<Subject\s+\d+>\s+is\s+(?:the\s+|a\s+)?speaker\b|"
        r"\b(?:allow|enable|generate|produce|add|include)\s+(?:extra\s+)?human\s+(?:speech|voices?|vocalization)\b|"
        r"\bhuman\s+(?:speech|voices?|vocalization)\s+(?:(?:is|are)\s+)?(?:allowed|enabled)\b|"
        r"说话|讲话|说道|回答|交谈|对话(?!框)|低语|喊叫|笑声|口型|发声|人声|唇形|"
        r"回应(?![^，。.!?;；\n]{0,8}(?:视线|目光|手势|动作))",
        re.IGNORECASE,
    )
    muted_audio = re.compile(
        r"\b(?:silent\s+audio|complete\s+silence|(?:entire\s+clip|audio\s+track|"
        r"soundtrack|all\s+sound)\s+(?:(?:is|must\s+be|remains?|becomes?)\s+)?"
        r"(?:silent|muted)|mute\s+(?:the\s+)?(?:audio|soundtrack))\b|"
        r"音轨静音|关闭(?:整个)?音轨|所有声音消失", re.IGNORECASE,
    )
    issues = []
    human_identity = r"(?:<Subject\s+\d+>|\bhuman\b|\bperson\b|\bman\b|\bwoman\b|\bcrowd\b"
    for name in subject_bindings or {}:
        human_identity += "|" + re.escape(name)
    human_identity += ")"
    # Actual utterances/assignments remain forbidden even beside a safe mention.
    # Exact canonical quotations have already become assigned dialogue IDs here;
    # attaching an ID to a speaker outside the timeline is still an assignment.
    utterance = r'(?:[“"「『]|assigned\s+dialogue\s+D\d+\b)'
    if re.search(
        r"(?:说|说道|喊道|问道|答道|回答|低语)\s*[:：]?\s*" + utterance
        + "|" + human_identity + r"\s*[:：]\s*" + utterance,
        body, re.IGNORECASE,
    ):
        issues.append("CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE")
    # Mask only complete visual nouns and generic conditional lip instructions,
    # never a whole negative clause or a named Subject's speech/silence decision.
    mentions = re.compile(
        r"(?:对话|对白|语音)(?:框|气泡)|"
        r"\b(?:speech|dialogue)\s+bubbles?\b|"
        r"\blip[ -]?sync\s+(?:rules?|instructions?|guidelines?)\b|"
        r"(?:角色|人物)(?:说话|讲话)时(?:保持|使用)(?:自然|正确)?"
        r"(?:中文|汉语|普通话)(?:口型|唇形)",
        re.IGNORECASE,
    )
    scan_body = mentions.sub(lambda match: " " * len(match.group()), body)
    human_vocalization = re.compile(
        human_identity + r"[^.!?;,\n]{0,40}\b(?:screams?|screaming|grunts?|grunting|gasps?|gasping|sobs?|sobbing|sings?|singing|hums?|humming)\b",
        re.IGNORECASE,
    )
    human_silence = re.compile(
        r"(?:" + human_identity + r"|all\s+characters)\s+(?:is|are|remains?|stays?|must\s+remain)\s+(?:silent|non-vocal|mute)\b",
        re.IGNORECASE,
    )
    # Do not let a negation in another clause authorize affirmative speech.
    for clause in re.split(r"[\n.!?;,，。！？；]|\bbut\b|但(?:是)?|然而", scan_body, flags=re.IGNORECASE):
        for pattern, code in ((speech, "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"),
                              (human_vocalization, "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"),
                              (human_silence, "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE"),
                              (muted_audio, "NO_VOICE_AUDIO_MUTED")):
            for match in pattern.finditer(clause):
                prefix = clause[:match.start()]
                suffix = clause[match.end():]
                if code == "CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE":
                    if match.group() == "发声" and prefix.endswith("突") and suffix.startswith("源"):
                        continue
                    if match.group() == "人声" and prefix.endswith("非"):
                        continue
                    if re.search(r"无(?:额外|其他|多余)(?:的)?$", prefix) and match.group().startswith("说话"):
                        continue
                    if (match.group() in {"人声", "对白", "语音"}
                            and re.search(r"(?:前景|已授权(?:的)?|时间线中(?:的)?)$", prefix)
                            and re.match(r"(?:之外|以外)的(?:声响|声音|环境声)", suffix)):
                        continue
                # The negation must govern this speech term, not unrelated music or Foley.
                if re.search(
                    r"(?:\b(?:no|not|never|without|forbid|forbidden)\b"
                    r"(?:\s+(?:extra|additional|other|background|human|off[- ]screen|any))*\s*|"
                    r"(?:禁止|不得|没有|不允许)"
                    r"(?:(?:出现|添加|加入|产生|任何|其他|额外|背景|画外)){0,4}\s*)$",
                    prefix, re.IGNORECASE,
                ):
                    continue
                issues.append(code)
    if re.search(r"(?i)\b(?:speaker|exact_dialogue|dialogue_timeline)\s*[:=]", body):
        issues.append("CANONICAL_SPEECH_AUTHORITY_OUTSIDE_TIMELINE")
    return sorted(set(issues))


def _audit_final_h3_prompt(final_prompt: str, assigned_dialogues: list, silent_characters: list, subject_bindings: dict | None = None, *, canonical_visual_body: str | None = None) -> dict:
    issues = []
    subject_mappings = {
        name.strip(): subject
        for subject, name in re.findall(r"(<Subject\s+\d+>)\s+is\s+([^,\n.;]+)", final_prompt)
        if name.strip()
    }
    for item in assigned_dialogues:
        text = _exact_spoken_text(item.get("text"))
        speaker = item.get("speaker") or ""
        occurrence_count = final_prompt.count(text) if text else 0
        if occurrence_count > 1:
            issues.append("DIALOGUE_DUPLICATED_IN_PROMPT")
        if occurrence_count != 1:
            issues.append("DIALOGUE_EXACT_TEXT_OCCURRENCE_INVALID")
        if not speaker or not re.search(rf"(?m)^\s*speaker: <Subject \d+>\s*$", final_prompt):
            issues.append("DIALOGUE_SPEAKER_MISSING")
        if canonical_visual_body is not None:
            subject = (subject_bindings or {}).get(speaker)
            expected = f"{item['id']}:\n  speaker: {subject}\n  start_time: {item['start_time']}s\n  end_time: {item['end_time']}s\n  exact_dialogue: {text}"
            if not subject or expected not in final_prompt:
                issues.append("DIALOGUE_SPEAKER_TIMING_AUTHORITY_INVALID")
        if not item.get("duration_sufficient"):
            issues.append("DIALOGUE_DURATION_INSUFFICIENT")
    for character in silent_characters:
        subject = (subject_bindings or {}).get(character) or subject_mappings.get(character)
        subject_is_silent = bool(subject and re.search(
            rf"{re.escape(subject)}[^.!?\n]*\b(?:remain|remains|stay|stays)\s+(?:non-vocal|silent)\b",
            final_prompt,
            re.IGNORECASE,
        ))
        subject_is_silent = subject_is_silent or bool(subject and re.search(
            rf"(?m)^silent_characters: [^\n]*{re.escape(subject)}", final_prompt
        ))
        if character and character not in final_prompt and not subject_is_silent:
            issues.append("SILENT_CHARACTER_CONSTRAINT_MISSING")
    if canonical_visual_body is not None:
        issues.extend(_canonical_visual_body_speech_issues(canonical_visual_body, subject_bindings))
        if re.search(
            r"(?i)\bD\d+\b[^.!?\n]{0,160}\b(?:visual|speech)\s+"
            r"(?:pacing|rhythm)\s+markers?\b",
            canonical_visual_body,
        ):
            issues.append("CANONICAL_D_EVENT_SEMANTIC_COMPETITION")
        if not assigned_dialogues and "NO_VOICE: no human speech, no human vocalization, no invented dialogue." not in final_prompt:
            issues.append("CANONICAL_NO_VOICE_MISSING")
    blocking_issues = [issue for issue in sorted(set(issues)) if issue != "DIALOGUE_DURATION_INSUFFICIENT"]
    return {
        "source_dialogue_count": len(assigned_dialogues),
        "assigned_dialogue_count": len(assigned_dialogues),
        "issues": sorted(set(issues)),
        "blocking_issues": blocking_issues,
        "passed": not blocking_issues,
    }


def _render_continuity_lock(shot, selected_mode: str, clip: dict | None) -> str:
    if (shot.continuity_mode or "NORMAL") != "CONTINUOUS_TAKE":
        return ""
    clip = clip or {}
    clip_label = ""
    if clip.get("clip_index") is not None:
        clip_label = f" Clip {clip.get('clip_index')} ({clip.get('start_time', 0)}s-{clip.get('end_time', shot.duration or 0)}s)."
    return "\n".join([
        "shot_continuity_lock:",
        "continuity_mode = CONTINUOUS_TAKE. This is a shot-level editing constraint, not a video generation mode.",
        f"Generate this as part of one uninterrupted continuous take.{clip_label}",
        "No cuts, no hidden edits, no jump cuts, no shot/reverse-shot grammar, no abrupt camera teleport, no sudden lens/framing reset.",
        "All camera movement must be physically continuous and motivated by the previous visual state.",
        "Preserve spatial geography, screen direction, subject blocking, eyelines, action state, lighting continuity, and environment continuity.",
        "If this Shot is split into multiple generation clips, the start of this clip must visually inherit the previous clip ending state and continue the same camera path.",
        "Keyframes are chronological states along one continuous camera trajectory, not separate edited shots.",
        *([] if not selected_mode else [f"selected_video_generation_mode = {selected_mode}; do not treat CONTINUOUS_TAKE as SINGLE_FRAME."]),
    ])


async def build_h3_video_prompt(
    db: Session,
    novel: Novel,
    shot,
    selected_mode: str,
    clip: dict,
    workflow_capability: dict,
    workflow_type: str,
    workflow_name: str,
    start_image_url: Optional[str],
    keyframes: list,
    transitions: list,
    clip_dialogues: list,
    reference_images: list,
    character_appearances: Optional[dict] = None,
    temporal_anchors: Optional[list] = None,
    video_reference_manifest: Optional[dict] = None,
    previous_av_present: bool = False,
    current_visual_state: Optional[dict] = None,
    visual_attention: Optional[dict] = None,
    resolved_dialogue_timeline: Optional[list] = None,
) -> str:
    require_current_attention_transitions(safe_json_dict(shot.video_director_plan), clip)
    canonical_path = isinstance(clip, dict) and "visual_state_indexes" in clip
    semantic_controls = []
    if canonical_path:
        state_map = {
            int(item.get("index")): item
            for item in (keyframes or [])
            if isinstance(item, dict) and item.get("index") is not None
        }
        owned_indexes = [int(item) for item in clip.get("visual_state_indexes") or []]
        semantic_controls = [state_map[index] for index in owned_indexes if index in state_map]
        roles = {str(item.get("role") or "").upper() for item in semantic_controls if item.get("index") is not None}
        if len(semantic_controls) == 2 and roles == {"START", "END"}:
            route = "endpoint"
        elif len(semantic_controls) == 1:
            route = "single"
        else:
            route = "multi" if semantic_controls else "single"
        if route == "endpoint":
            step = "12"
            template_attr = "h3_first_last_frame_prompt_template_id"
            template_type = "h3_first_last_frame_prompt"
        elif route == "multi":
            step = "13"
            template_attr = "h3_multi_keyframe_prompt_template_id"
            template_type = "h3_multi_keyframe_prompt"
        else:
            step = "11"
            template_attr = "h3_single_frame_prompt_template_id"
            template_type = "h3_single_frame_prompt"
    elif selected_mode == "FIRST_LAST_FRAME":
        route = "endpoint"
        step = "12"
        template_attr = "h3_first_last_frame_prompt_template_id"
        template_type = "h3_first_last_frame_prompt"
    elif selected_mode == "MULTI_KEYFRAME":
        route = "multi"
        step = "13"
        template_attr = "h3_multi_keyframe_prompt_template_id"
        template_type = "h3_multi_keyframe_prompt"
    else:
        route = "single"
        step = "11"
        template_attr = "h3_single_frame_prompt_template_id"
        template_type = "h3_single_frame_prompt"

    template = resolve_prompt_template(db, novel, template_attr, template_type)
    sanitized_keyframes = (
        [{key: item[key] for key in (
            "index", "role", "time_seconds", "description", "required", "requirement", "timed_visual_target",
        ) if key in item} for item in semantic_controls]
        if canonical_path else _strip_keyframe_generation_prompt(strip_media_refs(keyframes))
    )
    clip_start_time = float(clip.get("start_time") or 0)
    for keyframe in sanitized_keyframes:
        if isinstance(keyframe, dict) and keyframe.get("time_seconds") is not None:
            try:
                keyframe["time_seconds"] = round(float(keyframe["time_seconds"]) - clip_start_time, 2)
            except (TypeError, ValueError):
                pass
    frames = sanitized_keyframes if canonical_path else sanitized_keyframes or [
        {
            "index": 1,
            "role": "START",
            "time_seconds": 0,
            "description": shot.description or "",
        }
    ]
    physical_picture_mapping = (
        build_physical_picture_mapping(video_reference_manifest)
        if canonical_path else []
    )
    for item in physical_picture_mapping:
        if item.get("source_time_seconds") is not None:
            item["prompt_time_seconds"] = round(
                float(item["source_time_seconds"]) - clip_start_time,
                2,
            )
    mapped_frames = (
        attach_physical_picture_mapping(frames, physical_picture_mapping)
        if canonical_path else frames
    )
    mapped_keyframes = (
        attach_physical_picture_mapping(sanitized_keyframes, physical_picture_mapping)
        if canonical_path else sanitized_keyframes
    )
    mapped_semantic_controls = (
        attach_physical_picture_mapping(
            sanitized_keyframes,
            physical_picture_mapping,
        )
        if canonical_path else []
    )
    if resolved_dialogue_timeline is None:
        plan = safe_json_dict(shot.video_director_plan)
        if plan.get("dialogue_timeline_source"):
            resolved_dialogue_timeline, _ = resolve_canonical_dialogue_timeline(shot, plan)
    if resolved_dialogue_timeline is not None:
        clip_dialogues = project_resolved_dialogue_timeline(resolved_dialogue_timeline, clip, clip_dialogues)
    is_multi_clip = route in {"endpoint", "multi"}
    is_semantic_clip = bool(clip_dialogues and any(isinstance(item, dict) and item.get("dialogue_id") for item in clip_dialogues))
    shot_characters = safe_json_list(shot.characters)
    clip_visible_characters = _clip_visible_characters(sanitized_keyframes, shot_characters)
    assigned_dialogues, silent_characters, dialogue_timeline_status = build_dialogue_timeline(clip, clip_dialogues, clip_visible_characters)
    if canonical_path and clip_dialogues and (
        not assigned_dialogues or dialogue_timeline_status.get("status") != "ok"
    ):
        raise ValueError("CANONICAL_DIALOGUE_TIMELINE_UNAVAILABLE")
    dialogue_payload = [
        {key: value for key, value in item.items() if key not in {"text", "source_order"}}
        for item in assigned_dialogues
    ]
    character_appearances = character_appearances or {}
    sanitized_transitions = (
        [{key: item[key] for key in (
            "from_keyframe_index", "to_keyframe_index", "start_time", "end_time",
            "duration", "transition_description",
        ) if key in item} for item in transitions or [] if isinstance(item, dict)]
        if canonical_path else _sanitize_transitions_for_h3(transitions)
    )
    clip_motion_directive = None if canonical_path else (
        _build_clip_motion_directive(shot, clip, sanitized_transitions)
        if is_multi_clip or is_semantic_clip
        else _strip_voice_rules_from_text(shot.video_description or shot.description or "")
    )
    reference_binding = compile_h3_reference_bindings(
        physical_picture_mapping, _subject_bindings("", clip_visible_characters),
        semantic_controls, sanitized_transitions,
        capability=str(clip.get("capability") or ""), previous_av_present=previous_av_present,
        current_visual_state=current_visual_state,
    ) if canonical_path else None
    attention = visual_attention if visual_attention is not None else prepare_clip_visual_attention(
        safe_json_dict(shot.video_director_plan), clip, shot_characters,
        keyframes=sanitized_keyframes, transitions=sanitized_transitions,
        manifest=video_reference_manifest, duration=shot.duration or 4,
    )
    dialogue_visual_intents = executable_dialogue_visual_intents(
        clip, resolved_dialogue_timeline or [], safe_json_dict(shot.video_director_plan),
    )
    visual_guidance = render_dialogue_visual_guidance(
        dialogue_visual_intents, clip_dialogues,
        (safe_json_dict(shot.video_director_plan).get("visual_attention") or {}).get("character_catalog") or [],
        _subject_bindings("", clip_visible_characters),
    )
    payload = {
        "shot": {
            "id": shot.id,
            "index": shot.index,
            **({} if canonical_path else {
                "description": shot.description or "",
                "video_description": "" if is_multi_clip or is_semantic_clip else _strip_voice_rules_from_text(shot.video_description or ""),
            }),
            "duration": shot.duration or 4,
            "continuity_mode": shot.continuity_mode or "NORMAL",
            "characters": shot_characters,
            "official_character_appearances": character_appearances,
            "scene": shot.scene or "",
            "props": get_visual_prop_names(db, novel.id, safe_json_list(shot.props)),
            **({} if canonical_path else {
                "dialogues": dialogue_payload if is_multi_clip or is_semantic_clip else safe_json_list(shot.dialogues),
            }),
        },
        **({} if canonical_path else {"selected_mode": selected_mode}),
        "visual_control_route": route if canonical_path else None,
        "visual_controls": mapped_semantic_controls if canonical_path else None,
        "physical_picture_manifest": physical_picture_mapping if canonical_path else None,
        **({"reference_binding_contract": reference_binding} if canonical_path else {}),
        "picture_mapping_contract": {
            "authority": "physical_picture_manifest",
            "numbering": "dense_1_based_manifest_order",
            "image_less_visual_states": "text_only_no_picture_number",
            "temporal_anchor_domain": "separate_from_ordinary_pictures",
        } if canonical_path else None,
        "clip": {key: clip[key] for key in (
            "clip_index", "start_time", "end_time", "duration", "planned_duration",
            "capability", "continuity_to_previous", "visual_state_indexes", "carry_in_state_index",
        ) if key in clip} if canonical_path else strip_clip_generation_data(clip),
        **({} if canonical_path else {
            "motion_directive": clip_motion_directive,
            "clip_dialogues": dialogue_payload if is_multi_clip or is_semantic_clip else clip_dialogues,
        }),
        "clip_visible_characters": clip_visible_characters,
        "dialogue_timeline_source": assigned_dialogues,
        "dialogue_timeline_status": dialogue_timeline_status,
        "silent_characters": silent_characters,
        **({} if canonical_path else {
            "frames": mapped_frames,
            "ordered_keyframes": None,
            "keyframes": mapped_keyframes,
        }),
        "temporal_anchors": _canonical_temporal_controls(temporal_anchors or [], sanitized_keyframes) if canonical_path else strip_media_refs(temporal_anchors or []),
        **({
            "conditioning": {
                "previous_av_present": bool(previous_av_present),
                "previous_av": "Continue from the ending visual state of the provided previous video; it has no Picture number." if previous_av_present else None,
                "temporal_domain": "separate_timed_conditioning_no_ordinary_picture",
            },
            "control_counts": {
                "semantic_control_count": len(semantic_controls),
                "owned_state_count": len(owned_indexes),
                "ordinary_reference_count": len(physical_picture_mapping),
                "temporal_anchor_count": len(temporal_anchors or []),
                "previous_av_present": bool(previous_av_present),
            },
        } if canonical_path else {}),
        "transitions": sanitized_transitions,
        **({"visual_attention_timeline": {key: attention[key] for key in (
            "version", "time_base", "windows", "characters",
        )}} if attention["status"] == "VALID" else {}),
        **({"dialogue_visual_intents": dialogue_visual_intents} if dialogue_visual_intents else {}),
        "workflow_capability": strip_media_refs(workflow_capability),
        "workflow_type": workflow_type,
        "workflow_name": workflow_name,
        **({} if canonical_path else {"continuity_requirements": {
            "mode": shot.continuity_mode or "NORMAL",
            "is_continuous_take": (shot.continuity_mode or "NORMAL") == "CONTINUOUS_TAKE",
            "rule": "CONTINUOUS_TAKE forbids cuts and hidden edits; visual controls remain chronological states along one continuous trajectory.",
        }}),
    }
    user_content = "请基于以下 Video Director 规划数据，生成可直接用于 MiniMax H3 的最终视频提示词。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    result = await LLMService().chat_completion(
        system_prompt=(
            f"{template.template}\n\n{_canonical_picture_mapping_contract()}\n\n{_canonical_speech_contract()}\n\n{_canonical_section_ownership_contract()}\n\n"
            "reference_binding_contract is deterministic compiler authority. Keep Subject definitions and visual actions consistent with it. Do not output or redefine reference_authority, character_identity_binding, existing_body_binding, initial_body_binding or motion_ownership sections; the compiler supplies them."
            if canonical_path else (f"{template.template}\n\n{ATTENTION_RULE}" if attention["status"] == "VALID" else template.template)
        ) + (f"\n\n{DIALOGUE_VISUAL_INTENT_RULE}" if dialogue_visual_intents else ""),
        user_content=user_content,
        temperature=0.3,
        max_tokens=1800,
        task_type=template_type,
        prompt_template_name=template.name,
        novel_id=novel.id,
        chapter_id=shot.chapter_id,
    )
    if not result.get("success"):
        append_video_ai_call(shot, {
            "step": step,
            "task_type": template_type,
            "prompt_template_name": template.name,
            "status": "error",
            "error_message": result.get("error") or "H3 视频提示词生成失败",
            "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
            "response": result.get("error") or "",
            "clip_index": clip.get("clip_index"),
            "workflow_type": workflow_type,
            "workflow_name": workflow_name,
            "reference_images": reference_images,
        })
        db.commit()
        raise RuntimeError(result.get("error") or "H3 视频提示词生成失败")

    final_prompt = (result.get("content") or "").strip()
    if dialogue_visual_intents:
        final_prompt = re.sub(
            r"(?ms)^dialogue_visual_guidance:[ \t]*\n.*?(?=^[a-z][a-z_]*:[ \t]*(?:\n|$)|\Z)",
            "", final_prompt,
        ).rstrip()
    # Remove only a model-redefined attention block before the existing audits;
    # preserve the raw response in the AI call and compile the owner block last.
    final_prompt = compile_visual_attention(final_prompt, {"status": "ABSENT"})
    if canonical_path:
        final_prompt = _remove_canonical_h3_internal_self_check(final_prompt)
    if canonical_path or route == "multi":
        final_prompt = _remove_generated_dialogue_timeline(final_prompt)
    if canonical_path:
        final_prompt = _project_canonical_soundscape(final_prompt)
    continuity_lock = "" if canonical_path else _render_continuity_lock(shot, selected_mode, clip)
    if continuity_lock:
        final_prompt = f"{continuity_lock}\n\n{final_prompt}"
    physical_picture_audit = None
    if canonical_path:
        physical_picture_audit = audit_physical_picture_references(final_prompt, physical_picture_mapping)
        if not physical_picture_audit.get("passed"):
            append_video_ai_call(shot, {
                "step": step,
                "task_type": template_type,
                "prompt_template_name": template.name,
                "status": "error",
                "error_message": ",".join(physical_picture_audit.get("issues") or ["PICTURE_MAPPING_AUDIT_FAILED"]),
                "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
                "response": result.get("content") or "",
                "parsed_result": physical_picture_audit,
                "final_prompt": final_prompt,
                "clip_index": clip.get("clip_index"),
                "workflow_type": workflow_type,
                "workflow_name": workflow_name,
                "reference_images": reference_images,
            })
            db.commit()
            raise RuntimeError(",".join(physical_picture_audit.get("issues") or ["PICTURE_MAPPING_AUDIT_FAILED"]))
    dialogue_audit = None
    if canonical_path or is_multi_clip or is_semantic_clip:
        subject_bindings = _subject_bindings(final_prompt, clip_visible_characters)
        timeline_block = _render_dialogue_timeline_block(assigned_dialogues, silent_characters, subject_bindings)
        builder_body = _remove_dialogue_text_from_builder_body(final_prompt, assigned_dialogues)
        final_prompt = (
            _insert_canonical_dialogue_timeline(builder_body, timeline_block)
            if canonical_path else f"{timeline_block}\n\n{builder_body}".strip()
        )
        dialogue_audit = _audit_final_h3_prompt(
            final_prompt, assigned_dialogues, silent_characters, subject_bindings,
            canonical_visual_body=builder_body if canonical_path else None,
        )
        if not dialogue_audit.get("passed"):
            append_video_ai_call(shot, {
                "step": step,
                "task_type": template_type,
                "prompt_template_name": template.name,
                "status": "error",
                "error_message": ",".join(dialogue_audit.get("issues") or ["DIALOGUE_PROMPT_AUDIT_FAILED"]),
                "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
                "response": result.get("content") or "",
                "parsed_result": dialogue_audit,
                "final_prompt": final_prompt,
                "clip_index": clip.get("clip_index"),
                "workflow_type": workflow_type,
                "workflow_name": workflow_name,
                "reference_images": reference_images,
            })
            db.commit()
            raise RuntimeError(",".join(dialogue_audit.get("issues") or ["DIALOGUE_PROMPT_AUDIT_FAILED"]))
    if canonical_path:
        binding_section = render_h3_reference_bindings(reference_binding)
        if binding_section:
            if re.search(r"(?m)^(?:reference_authority|character_identity_binding|existing_body_binding|initial_body_binding|motion_ownership):\s*$", final_prompt):
                raise ValueError("H3_REFERENCE_BINDING_SECTION_REDEFINED")
            final_prompt = f"{final_prompt}\n\n{binding_section}"
    if visual_guidance:
        final_prompt = f"{final_prompt}\n\n{visual_guidance}"
    final_prompt = compile_visual_attention(final_prompt, attention)
    append_video_ai_call(shot, {
        "step": step,
        "task_type": template_type,
        "prompt_template_name": template.name,
        "status": "success",
        "input_summary": f"Shot {shot.index} Clip {clip.get('clip_index')} {selected_mode}",
        "response": result.get("content") or "",
        "parsed_result": {
            "dialogue": dialogue_audit,
            "physical_picture": physical_picture_audit,
            "reference_binding": reference_binding,
            "visual_attention": execution_attention_snapshot(attention, final_prompt),
        } if canonical_path else ({**dialogue_audit, "visual_attention": execution_attention_snapshot(attention, final_prompt)}
                                 if attention["status"] == "VALID" else dialogue_audit),
        "final_prompt": final_prompt,
        "clip_index": clip.get("clip_index"),
        "workflow_type": workflow_type,
        "workflow_name": workflow_name,
        "reference_images": reference_images,
    })
    db.commit()
    return final_prompt
