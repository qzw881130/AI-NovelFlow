"""Optional #08 attention authority: data transforms only, no directing or I/O."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from uuid import UUID


CONTRACT_VERSION = 1
PROJECTION_VERSION = 1
SECTION = "visual_attention_timeline"
ATTENTION_RULE = (
    "Visual priority concerns narrative emphasis, not speech permission, visibility, "
    "body presence or motion permission. A background-moving Subject remains free "
    "to perform its authorized action; do not freeze or remove it. Primary attention "
    "may be maintained through ensemble framing, contextual reactions and brief "
    "occlusion; it does not require a portrait or continuous visibility. Preserve "
    "the supplied continuity mode. Do not redefine visual_attention_timeline; the "
    "compiler supplies this section."
)


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("INVALID_TIME")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("INVALID_TIME")
    return result


def character_catalog(names, assets):
    """Use exact, unique formal assets; never pick the first duplicate name."""
    catalog, findings = [], []
    for name in dict.fromkeys(names):
        matches = [asset for asset in assets if asset.name == name]
        if len(matches) != 1:
            findings.append(f"CHARACTER_CATALOG_UNRESOLVED:{name}")
            continue
        catalog.append({"character_id": str(matches[0].id), "character_name": name})
    return catalog, findings


def normalize_visual_attention(raw, catalog, duration=None, *, persisted=False):
    """Invalid optional attention falls back as a whole; no clamping or retries."""
    if raw is None:
        return {"authority": None, "status": "ABSENT", "findings": []}
    try:
        if not isinstance(raw, dict):
            raise ValueError("INVALID_OBJECT")
        if persisted and (type(raw.get("version")) is not int or raw["version"] != CONTRACT_VERSION
                          or raw.get("time_base") != "SHOT_SECONDS"):
            raise ValueError("INVALID_VERSION_OR_TIME_BASE")
        if "version" in raw and (type(raw["version"]) is not int or raw["version"] != CONTRACT_VERSION):
            raise ValueError("INVALID_VERSION")
        if "time_base" in raw and raw["time_base"] != "SHOT_SECONDS":
            raise ValueError("INVALID_TIME_BASE")
        if not isinstance(catalog, list):
            raise ValueError("INVALID_CATALOG")
        ids, names = [], []
        for item in catalog:
            identity, name = item["character_id"], item["character_name"]
            if not isinstance(identity, str) or str(UUID(identity)) != identity or not isinstance(name, str) or not name:
                raise ValueError("INVALID_CHARACTER_IDENTITY")
            ids.append(identity)
            names.append(name)
        if len(set(ids)) != len(ids) or len(set(names)) != len(names):
            raise ValueError("AMBIGUOUS_CATALOG")
        def members(value):
            if not isinstance(value, list) or any(not isinstance(i, str) or i not in ids for i in value):
                raise ValueError("UNKNOWN_CHARACTER_ID")
            return [identity for identity in ids if identity in value]
        if not isinstance(raw.get("windows"), list):
            raise ValueError("INVALID_WINDOWS")
        windows = []
        for item in raw["windows"]:
            start, end = _decimal(item["start_time_seconds"]), _decimal(item["end_time_seconds"])
            if start < 0 or end <= start or (duration is not None and end > _decimal(duration)):
                raise ValueError("WINDOW_OUT_OF_BOUNDS")
            primary = members(item["primary_subjects"])
            background = members(item.get("background_motion_subjects", []))
            if set(primary) & set(background):
                raise ValueError("PRIMARY_BACKGROUND_OVERLAP")
            window = {"start_time_seconds": float(start), "end_time_seconds": float(end),
                      "primary_subjects": primary, "background_motion_subjects": background}
            if "handoff" in item:
                handoff = {key: members(item["handoff"][key]) for key in ("from", "to")}
                if set(primary) != set(handoff["from"]) | set(handoff["to"]):
                    raise ValueError("HANDOFF_PRIMARY_MISMATCH")
                window["handoff"] = handoff
            windows.append(window)
        windows.sort(key=lambda w: w["start_time_seconds"])
        if any(a["end_time_seconds"] > b["start_time_seconds"] for a, b in zip(windows, windows[1:])):
            raise ValueError("WINDOW_OVERLAP")
        return {"status": "VALID" if windows else "EMPTY", "findings": [], "authority": {
            "version": CONTRACT_VERSION, "time_base": "SHOT_SECONDS",
            "character_catalog": deepcopy(catalog), "windows": windows,
        }}
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation) as exc:
        return {"authority": None, "status": "FALLBACK_INVALID",
                "findings": [f"VISUAL_ATTENTION_INVALID:{exc}"]}


def project_visual_attention(authority, start, end, *, clip_local=True, duration=None):
    normalized = normalize_visual_attention(
        authority, (authority or {}).get("character_catalog", []) if isinstance(authority, dict) else [],
        duration, persisted=True,
    )
    result = {"version": CONTRACT_VERSION, "projection_version": PROJECTION_VERSION,
              "time_base": "CLIP_SECONDS" if clip_local else "SHOT_SECONDS",
              "status": normalized["status"], "findings": normalized["findings"],
              "character_catalog": [], "windows": []}
    if normalized["authority"] is None:
        return result
    start, end = _decimal(start), _decimal(end)
    result.update({"clip_start_seconds": float(start), "clip_end_seconds": float(end),
                   "character_catalog": normalized["authority"]["character_catalog"]})
    for index, window in enumerate(normalized["authority"]["windows"]):
        a, b = _decimal(window["start_time_seconds"]), _decimal(window["end_time_seconds"])
        left, right = max(a, start), min(b, end)
        if left >= right:
            continue
        item = {**deepcopy(window), "start_time_seconds": float(left - start if clip_local else left),
                "end_time_seconds": float(right - start if clip_local else right),
                "source_window_index": index, "source_start_time_seconds": float(a),
                "source_end_time_seconds": float(b)}
        if "handoff" in item:
            item["handoff_progress"] = {"start": float((left - a) / (b - a)), "end": float((right - a) / (b - a))}
        result["windows"].append(item)
    if normalized["status"] == "VALID" and not result["windows"]:
        result["status"] = "NO_CLIP_INTERSECTION"
    return result


def resolve_subjects(projection, subjects, manifest=None):
    result = deepcopy(projection)
    result["characters"] = []
    if result["status"] != "VALID":
        return result
    referenced = {i for w in result["windows"] for key in ("primary_subjects", "background_motion_subjects") for i in w[key]}
    for entry in result["character_catalog"]:
        identity, name = entry["character_id"], entry["character_name"]
        if identity not in referenced:
            continue
        refs = [r for r in (manifest or {}).get("references", [])
                if r.get("kind") == "CHARACTER_IDENTITY" and r.get("source_name") == name]
        if name not in subjects or any(r.get("source_id") and r["source_id"] != identity for r in refs):
            result.update(status="FALLBACK_INVALID", windows=[], findings=result["findings"] + [f"CHARACTER_SUBJECT_UNRESOLVED:{identity}"])
            return result
        result["characters"].append({**entry, "subject": subjects[name]})
    return result


def consumed_transitions(plan, clip):
    """The same canonical edge selection as the existing semantic context."""
    owned = [int(i) for i in clip.get("visual_state_indexes", [])]
    pairs = set(zip(owned, owned[1:]))
    carry = clip.get("carry_in_state_index")
    if owned and carry is not None and int(carry) != owned[0]:
        pairs.add((int(carry), owned[0]))
    return [item for item in plan.get("transitions", []) if isinstance(item, dict)
            and (item.get("from_keyframe_index"), item.get("to_keyframe_index")) in pairs]


def normalize_attention_replan_response(parsed, catalog, duration):
    """An explicit update cannot silently discard output owned by other planners."""
    if not isinstance(parsed, dict) or set(parsed) != {"visual_attention"}:
        raise ValueError("ATTENTION_REPLAN_REQUIRES_ATTENTION_ONLY_RESPONSE")
    result = normalize_visual_attention(parsed["visual_attention"], catalog, duration)
    if result["status"] not in {"VALID", "EMPTY"}:
        raise ValueError("ATTENTION_REPLAN_INVALID:" + ",".join(result["findings"] or [result["status"]]))
    return result


def attention_source_sha256(payload):
    """Planning provenance / optimistic concurrency, not another H3 cache version."""
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def canonical_transition_edges(plan):
    states = plan.get("keyframes") or []
    return {(a["index"], b["index"]) for a, b in zip(states, states[1:])}


def stale_attention_edges(plan):
    validation = (plan.get("validation") or {}).get("visual_attention") or {}
    return {(item["from_keyframe_index"], item["to_keyframe_index"])
            for item in validation.get("stale_transition_edges") or []}


def effective_transition_attention(authority, start, end, duration):
    """Exactly the optional #10 input, excluding trace-only source renumbering."""
    projection = project_visual_attention(authority, start, end, clip_local=False, duration=duration)
    if projection["status"] != "VALID":
        return None
    for window in projection["windows"]:
        window.pop("source_window_index", None)
    return projection


def changed_attention_edges(plan, authority, duration):
    states = plan.get("keyframes") or []
    return {(a["index"], b["index"]) for a, b in zip(states, states[1:])
            if effective_transition_attention(plan.get("visual_attention"), a["time_seconds"], b["time_seconds"], duration)
            != effective_transition_attention(authority, a["time_seconds"], b["time_seconds"], duration)}


def attention_edge_records(edges):
    return [{"from_keyframe_index": a, "to_keyframe_index": b} for a, b in sorted(edges)]


def merge_attention_update(plan, result, duration, catalog_findings=()):
    """Only the owner and its validation/freshness metadata are writable."""
    merged = deepcopy(plan)
    stale = stale_attention_edges(plan) | changed_attention_edges(plan, result["authority"], duration)
    validation = merged.setdefault("validation", {}).setdefault("visual_attention", {})
    validation.update(status=result["status"], findings=list(catalog_findings) + result["findings"],
                      stale_transition_edges=attention_edge_records(stale))
    merged["visual_attention"] = deepcopy(result["authority"])
    return merged


def clip_attention_transition_edges(plan, clip):
    if clip is None:
        return canonical_transition_edges(plan)
    indexes = clip.get("visual_state_indexes", clip.get("keyframe_indexes"))
    if indexes is not None:
        pairs = set(zip(indexes, indexes[1:]))
        carry = clip.get("carry_in_state_index")
        if indexes and carry is not None and carry != indexes[0]:
            pairs.add((carry, indexes[0]))
        return pairs
    # Legacy whole-shot/window callers have no semantic ownership indexes.
    start, end = clip.get("start_time", 0), clip.get("end_time")
    states = plan.get("keyframes") or []
    return {(a["index"], b["index"]) for a, b in zip(states, states[1:])
            if b["time_seconds"] > start and (end is None or a["time_seconds"] < end)}


def require_current_attention_transitions(plan, clip=None):
    """Only new authoritative builds/reuse/execution require refreshed #10 prose."""
    affected = stale_attention_edges(plan) & clip_attention_transition_edges(plan, clip)
    if affected:
        edges = ",".join(f"KF{a}->KF{b}" for a, b in sorted(affected))
        raise ValueError("VISUAL_ATTENTION_TRANSITIONS_STALE: 请先显式刷新 #10：" + edges)


def attention_fingerprint(projection, transitions):
    keys = ("from_keyframe_index", "to_keyframe_index", "start_time", "end_time", "duration", "transition_description")
    payload = {key: projection.get(key) for key in (
        "version", "projection_version", "time_base", "clip_start_seconds", "clip_end_seconds", "windows", "characters",
    )}
    # Source index is trace metadata: an unrelated earlier window can renumber it.
    payload["windows"] = [{key: value for key, value in w.items() if key != "source_window_index"}
                          for w in projection.get("windows", [])]
    payload["consumed_transitions"] = [{key: t[key] for key in keys if key in t} for t in transitions or []]
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def render_visual_attention(projection):
    if projection.get("status") != "VALID":
        return ""
    subjects = {entry["character_id"]: entry["subject"] for entry in projection["characters"]}
    def labels(ids):
        return ", ".join(subjects[i] for i in ids) or "the environment / non-character composition"
    lines = [f"{SECTION}:", ATTENTION_RULE]
    for w in projection["windows"]:
        def seconds(value):
            text = format(Decimal(str(value)), "f")
            return text + (".00" if "." not in text else "0" * max(0, 2 - len(text.split(".")[1])))
        interval = f"{seconds(w['start_time_seconds'])}–{seconds(w['end_time_seconds'])}s"
        if "handoff" in w:
            handoff = w["handoff"]
            text = f"Gradually redistribute attention from {labels(handoff['from'])} toward {labels(handoff['to'])}, allowing ensemble composition. Do not cut or imply that an approach must finish within this interval."
            progress = w["handoff_progress"]
            if progress != {"start": 0.0, "end": 1.0}:
                text += f" This is progress {progress['start']:.6g}–{progress['end']:.6g} of the original handoff; do not restart it or complete it early."
        else:
            text = f"Maintain primary narrative emphasis around {labels(w['primary_subjects'])} within the established composition."
            if w["background_motion_subjects"]:
                text += f" The authorized actions of {labels(w['background_motion_subjects'])} remain background motion; accommodate them without shifting dominance solely because they move."
        lines.append(f"{interval}: {text}")
    return "\n".join(lines)


_SECTION_RE = re.compile(r"(?m)^visual_attention_timeline:[ \t]*\n.*?(?=^[a-z][a-z_]*:[ \t]*(?:\n|$)|\Z)", re.S)


def compile_visual_attention(prompt, projection):
    """Remove a model-owned duplicate block, then inject the sole compiler block."""
    body = _SECTION_RE.sub("", prompt).rstrip()
    section = render_visual_attention(projection)
    return f"{body}\n\n{section}" if section else body


def prompt_projection_metadata(projection, prompt):
    section = render_visual_attention(projection)
    return {"version": CONTRACT_VERSION, "projection_version": PROJECTION_VERSION,
            "status": projection["status"], "fingerprint": projection.get("fingerprint"),
            "section_sha256": sha256(section.encode()).hexdigest() if section and prompt.endswith(section) else None}


def reusable_attention_prompt(prompt, projection, metadata=None):
    if projection.get("status") != "VALID":
        return not re.search(r"(?m)^visual_attention_timeline:", prompt or "")
    expected = prompt_projection_metadata(projection, prompt)
    return (bool(expected["section_sha256"]) and metadata == expected
            and len(re.findall(r"(?m)^visual_attention_timeline:", prompt or "")) == 1)


def execution_attention_snapshot(projection, prompt=None, temporal_manifest=None):
    snapshot = deepcopy(projection)
    snapshot["source"] = "shots.video_director_plan.visual_attention"
    snapshot["stage"] = "PROJECTED"
    snapshot["program_owned_section_sha256"] = None
    if prompt is not None:
        metadata = prompt_projection_metadata(snapshot, prompt)
        snapshot["program_owned_section_sha256"] = metadata["section_sha256"]
        snapshot["stage"] = "PROMPTED" if metadata["section_sha256"] else "NOT_APPLIED"
    if temporal_manifest:
        snapshot["temporal_times"] = [{key: deepcopy(a[key]) for key in ("anchor_id", "time_seconds", "frame_position", "reachability") if key in a}
                                      for a in temporal_manifest.get("anchors", [])]
    return snapshot
