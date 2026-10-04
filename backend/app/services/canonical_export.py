"""Canonical, read-only ZIP package builders for Shot and Chapter exports."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZipFile

from sqlalchemy.orm import Session

from app.models.novel import Character, Prop, Scene
from app.models.task import Task
from app.services.file_storage import file_storage
from app.services.clip_execution_compiler import TEMPORAL_DECISION_CONTRACT
from app.services.shot_video_service import validate_semantic_clip_artifact
from app.utils.path_utils import url_to_local_path


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _safe_part(value: Any) -> str:
    text = str(value or "unknown").strip()
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in text) or "unknown"


def _story_root(novel_id: str) -> Path:
    return (file_storage.base_dir / f"story_{str(novel_id)[:8]}").resolve()


def resolve_scoped_export_path(value: Any, novel_id: str) -> tuple[Path | None, str | None]:
    """Resolve one binary without allowing local paths outside this Novel's storage root."""
    if not value:
        return None, "MISSING"
    local = url_to_local_path(str(value))
    candidate = Path(local or str(value))
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, "FILE_UNAVAILABLE"
    root = _story_root(novel_id)
    if resolved != root and root not in resolved.parents:
        return None, "OUTSIDE_STORAGE_ROOT"
    if not resolved.is_file():
        return None, "FILE_UNAVAILABLE"
    return resolved, None


def _warning(warnings: list[dict], code: str, scope: str, detail: str | None = None) -> None:
    item = {"code": code, "scope": scope}
    if detail:
        item["detail"] = detail
    if item not in warnings:
        warnings.append(item)


def _archive_name(base: str, path: Path, default_suffix: str) -> str:
    suffix = path.suffix or default_suffix
    return f"{base}{suffix}"


def _add_binary(
    archive: ZipFile,
    added: set[str],
    novel_id: str,
    value: Any,
    base_name: str,
    default_suffix: str,
) -> tuple[str | None, str | None]:
    path, reason = resolve_scoped_export_path(value, novel_id)
    if not path:
        return None, reason
    name = _archive_name(base_name, path, default_suffix).replace("\\", "/").lstrip("/")
    if ".." in Path(name).parts:
        return None, "UNSAFE_ARCHIVE_PATH"
    if name not in added:
        archive.write(path, name)
        added.add(name)
    return name, None


def _write_text(archive: ZipFile, added: set[str], name: str, value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        content = value
    else:
        content = json.dumps(value, ensure_ascii=False, indent=2)
    if name not in added:
        archive.writestr(name, content)
        added.add(name)
    return name


def _plan_classification(plan: dict) -> str:
    if plan.get("canonical_visual_plan") is True:
        return "CURRENT_CANONICAL"
    return "HISTORICAL_PLAN" if plan else "MISSING_PLAN"


def _state_required(state: dict) -> bool:
    return str(state.get("role") or "").upper() != "START" and state.get("timed_visual_target") is True


def _state_image_value(shot, state: dict) -> Any:
    value = (
        state.get("image_url")
        or state.get("imageUrl")
        or state.get("image_path")
        or state.get("imagePath")
    )
    if not value and str(state.get("role") or "").upper() == "START":
        value = shot.image_url or shot.image_path
    return value


def _state_records(
    archive: ZipFile,
    added: set[str],
    novel_id: str,
    shot,
    plan: dict,
    prefix: str,
    warnings: list[dict],
) -> list[dict]:
    records = []
    for position, state in enumerate(plan.get("keyframes") or [], 1):
        if not isinstance(state, dict):
            continue
        try:
            index = int(state.get("index"))
        except (TypeError, ValueError):
            index = position
        new_contract = (plan.get("clip_plan_validation") or {}).get("temporal_contract") == TEMPORAL_DECISION_CONTRACT
        selected = any(f"KF{index}" in (clip.get("selected_temporal_target_ids") or []) for clip in plan.get("clip_plan") or [])
        generate_start = any(clip.get("capability") == "GENERATE" and (clip.get("visual_state_indexes") or [None])[0] == index for clip in plan.get("clip_plan") or [])
        required = (selected or generate_start) if new_contract else _state_required(state)
        value = _state_image_value(shot, state)
        image_path, reason = _add_binary(
            archive,
            added,
            novel_id,
            value,
            f"{prefix}/KF{index:03d}",
            ".png",
        )
        if image_path:
            image_status = "READY"
        else:
            image_status = "REQUIRED_MISSING" if required else "OPTIONAL_MISSING"
            if value and reason:
                _warning(warnings, reason, f"visual_state:{index}")
        records.append({
            "index": index,
            "time_seconds": state.get("time_seconds"),
            "role": state.get("role"),
            "required": required,
            "timed_visual_target": state.get("timed_visual_target") is True,
            "selected_temporal_target": selected if new_contract else None,
            "temporal_contract": TEMPORAL_DECISION_CONTRACT if new_contract else None,
            "description": state.get("description"),
            "image": {
                "status": image_status,
                "path": image_path,
                "image_task_id": state.get("image_task_id") or state.get("imageTaskId"),
            },
        })
    return records


def _clip_summary(clip: dict) -> dict:
    return {
        "clip_index": clip.get("clip_index"),
        "start_time": clip.get("start_time"),
        "end_time": clip.get("end_time"),
        "duration": clip.get("duration"),
        "continuity_to_previous": clip.get("continuity_to_previous"),
        "capability": clip.get("capability"),
        "visual_state_indexes": list(clip.get("visual_state_indexes") or []),
        "carry_in_state_index": clip.get("carry_in_state_index"),
        "previous_clip_index": clip.get("previous_clip_index"),
        "requires_temporal_control": clip.get("requires_temporal_control") is True,
        "selected_temporal_target_ids": list(clip.get("selected_temporal_target_ids") or []),
        "temporal_anchor_ids": list(clip.get("temporal_anchor_ids") or []),
        "dialogue_assignment": list(clip.get("dialogue_assignment") or []),
    }


def _validate_previous_av(
    db: Session,
    novel_id: str,
    chapter_id: str,
    shot,
    plan: dict,
    clip: dict,
    contract: dict,
) -> tuple[dict | None, str | None]:
    capability = str(clip.get("capability") or "").upper()
    if capability not in {"EXTEND", "TEMPORAL_EXTEND"}:
        return None, None
    previous_contract = contract.get("previous_clip")
    if not isinstance(previous_contract, dict):
        return None, "PREVIOUS_AV_PROVENANCE_MISSING"
    try:
        previous_index = int(clip.get("previous_clip_index"))
        revision = int(plan.get("clip_plan_revision"))
    except (TypeError, ValueError):
        return None, "PREVIOUS_AV_PROVENANCE_INVALID"
    previous_clip = next((
        item for item in plan.get("clip_plan") or []
        if isinstance(item, dict) and int(item.get("clip_index") or 0) == previous_index
    ), None)
    if not previous_clip:
        return None, "PREVIOUS_AV_PROVENANCE_INVALID"
    try:
        previous_task, previous_metadata, _ = validate_semantic_clip_artifact(
            db, shot, previous_clip, revision, novel_id, chapter_id,
        )
    except ValueError:
        return None, "PREVIOUS_AV_PROVENANCE_INVALID"
    expected = {
        "clip_index": previous_index,
        "clip_plan_revision": revision,
        "generated_by_task_id": str(previous_clip.get("generated_by_task_id") or ""),
        "result_url": str(previous_clip.get("video_url") or ""),
    }
    try:
        actual = {
            "clip_index": int(previous_contract.get("clip_index") or 0),
            "clip_plan_revision": int(previous_contract.get("clip_plan_revision") or 0),
            "generated_by_task_id": str(previous_contract.get("generated_by_task_id") or ""),
            "result_url": str(previous_contract.get("result_url") or ""),
        }
    except (TypeError, ValueError):
        return None, "PREVIOUS_AV_PROVENANCE_INVALID"
    if actual != expected or previous_task.id != expected["generated_by_task_id"]:
        return None, "PREVIOUS_AV_PROVENANCE_INVALID"
    if (previous_metadata.get("execution_contract") or {}).get("artifact_kind") not in {"CLIP_ONLY", "NATIVE_CONTINUITY_OUTPUT"}:
        return None, "PREVIOUS_AV_PROVENANCE_INVALID"
    return expected, None


def _physical_references(
    archive: ZipFile,
    added: set[str],
    novel_id: str,
    clip_index: int,
    metadata: dict,
    warnings: list[dict],
) -> tuple[dict, bool]:
    manifest = metadata.get("video_reference_manifest")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("references"), list):
        _warning(warnings, "EXECUTION_EVIDENCE_INCOMPLETE", f"clip:{clip_index}:ordinary_references")
        return {"status": "EXECUTION_EVIDENCE_INCOMPLETE", "references": []}, False
    exported = []
    dense = True
    for position, reference in enumerate(manifest.get("references") or [], 1):
        if not isinstance(reference, dict):
            dense = False
            continue
        try:
            slot = int(reference.get("slot"))
        except (TypeError, ValueError):
            slot = 0
        is_dense = slot == position
        dense = dense and is_dense
        asset_path, reason = _add_binary(
            archive,
            added,
            novel_id,
            reference.get("image_url"),
            f"execution/clips/C{clip_index:03d}/ordinary_references/P{position:03d}",
            ".png",
        )
        if reason and reason != "MISSING":
            _warning(warnings, reason, f"clip:{clip_index}:picture:{position}")
        binding = reference.get("binding") if isinstance(reference.get("binding"), dict) else {}
        exported.append({
            "physical_slot": slot or None,
            "picture_label": f"<Picture {slot}>" if is_dense else None,
            "kind": reference.get("kind"),
            "source_type": reference.get("source_type"),
            "source_keyframe_index": reference.get("source_keyframe_index"),
            "source_identity": reference.get("source_identity") or reference.get("source_id"),
            "source_image_task_id": reference.get("source_image_task_id"),
            "asset_path": asset_path,
            "binding": {
                "workflow_node_id": binding.get("workflow_node_id"),
                "submitted_filename": binding.get("uploaded_filename"),
            },
        })
    if not dense:
        _warning(warnings, "PHYSICAL_PICTURE_MANIFEST_NOT_DENSE", f"clip:{clip_index}")
    return {"status": "RECORDED" if dense else "EXECUTION_EVIDENCE_INCOMPLETE", "references": exported}, dense


def _temporal_anchors(
    archive: ZipFile,
    added: set[str],
    novel_id: str,
    clip_index: int,
    clip: dict,
    contract: dict,
    warnings: list[dict],
) -> tuple[dict, bool]:
    manifest = contract.get("temporal_anchor_manifest")
    requires = str(clip.get("capability") or "").upper() == "TEMPORAL_EXTEND"
    if not isinstance(manifest, dict):
        if requires:
            _warning(warnings, "EXECUTION_EVIDENCE_INCOMPLETE", f"clip:{clip_index}:temporal_anchors")
        return {"status": "EXECUTION_EVIDENCE_INCOMPLETE" if requires else "NOT_APPLICABLE", "anchors": []}, not requires
    exported = []
    for position, anchor in enumerate(manifest.get("anchors") or [], 1):
        if not isinstance(anchor, dict):
            continue
        asset_path, reason = _add_binary(
            archive,
            added,
            novel_id,
            anchor.get("image_url"),
            f"execution/clips/C{clip_index:03d}/temporal_anchors/A{position:03d}",
            ".png",
        )
        if reason and reason != "MISSING":
            _warning(warnings, reason, f"clip:{clip_index}:temporal_anchor:{position}")
        binding = anchor.get("binding") if isinstance(anchor.get("binding"), dict) else {}
        source = anchor.get("source") if isinstance(anchor.get("source"), dict) else {}
        exported.append({
            "temporal_slot": anchor.get("slot"),
            "anchor_id": anchor.get("anchor_id"),
            "time_seconds": anchor.get("time_seconds"),
            "frame_position": anchor.get("frame_position"),
            "source": {
                "id": source.get("id"),
                "keyframe_index": source.get("keyframe_index"),
                "image_task_id": source.get("image_task_id"),
            },
            "asset_path": asset_path,
            "binding": {
                "workflow_node_id": binding.get("workflow_node_id"),
                "submitted_filename": binding.get("uploaded_filename"),
            },
        })
    valid = bool(exported) if requires else True
    if requires and not valid:
        _warning(warnings, "EXECUTION_EVIDENCE_INCOMPLETE", f"clip:{clip_index}:temporal_anchors")
    return {"status": "RECORDED" if valid else "EXECUTION_EVIDENCE_INCOMPLETE", "anchors": exported}, valid


def _resolve_current_clip(
    db: Session,
    novel_id: str,
    chapter_id: str,
    shot,
    plan: dict,
    clip: dict,
) -> tuple[Task | None, dict, str | None, str | None, dict | None]:
    task_id = str(clip.get("generated_by_task_id") or "")
    if not task_id:
        return None, {}, None, "MISSING_GENERATED_BY_TASK_ID", None
    try:
        revision = int(plan.get("clip_plan_revision") or 0)
        task, metadata, local_path = validate_semantic_clip_artifact(
            db, shot, clip, revision, novel_id, chapter_id,
        )
    except ValueError as exc:
        reason = "CURRENT_ARTIFACT_UNREADABLE" if "不可读取" in str(exc) else "CURRENT_ARTIFACT_CONTRACT_INVALID"
        return None, {}, None, reason, None
    contract = metadata.get("execution_contract") if isinstance(metadata.get("execution_contract"), dict) else {}
    previous, previous_error = _validate_previous_av(db, novel_id, chapter_id, shot, plan, clip, contract)
    if previous_error:
        return task, metadata, local_path, previous_error, None
    return task, metadata, local_path, None, previous


def _final_assembly(
    archive: ZipFile,
    added: set[str],
    novel_id: str,
    shot,
    plan: dict,
    clip_records: list[dict],
    output_base: str,
    warnings: list[dict],
) -> dict:
    revision = int(plan.get("clip_plan_revision") or 0)
    task_ids = [
        str(item.get("generated_by_task_id") or "")
        for item in plan.get("clip_plan") or []
        if isinstance(item, dict)
    ]
    assembly_ids = [str(value) for value in plan.get("assembly_task_ids") or []]
    assembled = plan.get("assembled_result") if isinstance(plan.get("assembled_result"), dict) else {}
    merged_url = plan.get("merged_video_url")
    all_clips_current = bool(clip_records) and all(
        (item.get("artifact") or {}).get("status") == "CURRENT" for item in clip_records
    )
    current = (
        all_clips_current
        and all(task_ids)
        and plan.get("assembly_status") == "COMPLETED"
        and int(plan.get("assembly_clip_plan_revision") or 0) == revision
        and assembly_ids == task_ids
        and assembled.get("status") == "COMPLETED"
        and int(assembled.get("clip_plan_revision") or 0) == revision
        and [str(value) for value in assembled.get("task_ids") or []] == task_ids
        and assembled.get("url") == merged_url
        and shot.video_url == merged_url
        and bool(merged_url)
    )
    has_stale_candidate = bool(shot.video_url or merged_url or plan.get("assembly_status"))
    if not current:
        status = "STALE_NOT_EXPORTED" if has_stale_candidate else "CURRENT_FINAL_UNAVAILABLE"
        if has_stale_candidate:
            _warning(warnings, status, f"shot:{shot.id}:final")
        return {
            "status": status,
            "clip_plan_revision": revision,
            "source_clip_task_ids": task_ids,
            "path": None,
        }
    final_path, reason = _add_binary(archive, added, novel_id, merged_url, output_base, ".mp4")
    if not final_path:
        _warning(warnings, reason or "CURRENT_FINAL_UNAVAILABLE", f"shot:{shot.id}:final")
        return {
            "status": "CURRENT_FINAL_UNAVAILABLE",
            "clip_plan_revision": revision,
            "source_clip_task_ids": task_ids,
            "path": None,
        }
    return {
        "status": "CURRENT",
        "clip_plan_revision": revision,
        "source_clip_task_ids": task_ids,
        "path": final_path,
    }


def _resource_names(value: Any) -> list[str]:
    result = []
    for item in _json_list(value) if not isinstance(value, list) else value:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("character_name") or item.get("scene_name") or item.get("prop_name")
        else:
            name = None
        if name and str(name) not in result:
            result.append(str(name))
    return result


def _bound_resource_names(chapter, shots: Iterable[Any]) -> dict[str, list[str]]:
    parsed = _json_dict(chapter.parsed_data)
    result = {
        "characters": _resource_names(parsed.get("characters") or []),
        "scenes": _resource_names(parsed.get("scenes") or []),
        "props": _resource_names(parsed.get("props") or []),
    }
    for shot in shots:
        for name in _resource_names(shot.characters):
            if name not in result["characters"]:
                result["characters"].append(name)
        if shot.scene and shot.scene not in result["scenes"]:
            result["scenes"].append(shot.scene)
        for name in _resource_names(shot.props):
            if name not in result["props"]:
                result["props"].append(name)
    return result


def _write_resources(
    archive: ZipFile,
    added: set[str],
    db: Session,
    novel_id: str,
    names: dict[str, list[str]],
    warnings: list[dict],
) -> dict:
    result = {"characters": [], "scenes": [], "props": []}
    specs = (
        ("characters", Character, None),
        ("scenes", Scene, None),
        ("props", Prop, "REAL"),
    )
    for category, model, required_existence in specs:
        requested = names.get(category) or []
        rows = db.query(model).filter(model.novel_id == novel_id, model.name.in_(requested)).all() if requested else []
        by_name = {row.name: row for row in rows}
        for position, name in enumerate(requested, 1):
            row = by_name.get(name)
            if not row or (required_existence and getattr(row, "existence", None) != required_existence):
                result[category].append({"name": name, "status": "RESOURCE_UNAVAILABLE", "path": None})
                _warning(warnings, "RESOURCE_UNAVAILABLE", f"{category}:{name}")
                continue
            path, reason = _add_binary(
                archive,
                added,
                novel_id,
                row.image_url,
                f"resources/{category}/{position:03d}_{_safe_part(name)}",
                ".png",
            )
            status = "READY" if path else "IMAGE_UNAVAILABLE"
            result[category].append({"id": row.id, "name": name, "status": status, "path": path})
            if reason and reason != "MISSING":
                _warning(warnings, reason, f"{category}:{name}")
    return result


def build_shot_production_package(
    archive: ZipFile,
    db: Session,
    novel,
    chapter,
    shot,
) -> dict:
    """Write a canonical Shot production package and return its manifest."""
    added: set[str] = set()
    warnings: list[dict] = []
    plan = _json_dict(shot.video_director_plan)
    classification = _plan_classification(plan)
    primary_path, primary_reason = _add_binary(
        archive, added, novel.id, shot.image_url or shot.image_path, "shot/primary", ".png",
    )
    if primary_reason and primary_reason != "MISSING":
        _warning(warnings, primary_reason, "shot:primary")

    bound_names = {
        "characters": _resource_names(shot.characters),
        "scenes": [shot.scene] if shot.scene else [],
        "props": _resource_names(shot.props),
    }
    resources = _write_resources(archive, added, db, novel.id, bound_names, warnings)
    states = _state_records(
        archive, added, novel.id, shot, plan, "visual_states", warnings,
    ) if classification == "CURRENT_CANONICAL" else []
    clips = [item for item in plan.get("clip_plan") or [] if isinstance(item, dict)] if classification == "CURRENT_CANONICAL" else []
    clips.sort(key=lambda item: int(item.get("clip_index") or 0))
    execution_records = []
    artifact_paths: dict[int, str] = {}
    revision = int(plan.get("clip_plan_revision") or 0)
    for position, clip in enumerate(clips, 1):
        clip_index = int(clip.get("clip_index") or position)
        task, metadata, _, error, previous = _resolve_current_clip(db, novel.id, chapter.id, shot, plan, clip)
        record = _clip_summary(clip)
        record["generated_by_task_id"] = clip.get("generated_by_task_id")
        record["artifact"] = {
            "status": "CURRENT_ARTIFACT_UNAVAILABLE",
            "reason": error or "CURRENT_ARTIFACT_UNAVAILABLE",
            "artifact_kind": None,
            "path": None,
        }
        record["prompt_path"] = None
        record["workflow_path"] = None
        record["ordinary_references"] = {"status": "NOT_AVAILABLE", "references": []}
        record["temporal_anchors"] = {"status": "NOT_APPLICABLE", "anchors": []}
        record["previous_av"] = None
        if task and not error:
            artifact_path, path_error = _add_binary(
                archive, added, novel.id, task.result_url,
                f"execution/clips/C{clip_index:03d}/artifact", ".mp4",
            )
            if artifact_path:
                contract = metadata.get("execution_contract") or {}
                record["artifact"] = {
                    "status": "CURRENT",
                    "reason": None,
                    "generated_by_task_id": task.id,
                    "artifact_kind": contract.get("artifact_kind"),
                    "path": artifact_path,
                }
                artifact_paths[clip_index] = artifact_path
                record["prompt_path"] = _write_text(
                    archive, added, f"execution/clips/C{clip_index:03d}/submitted_prompt.txt", task.prompt_text,
                )
                record["workflow_path"] = _write_text(
                    archive, added, f"execution/clips/C{clip_index:03d}/submitted_workflow.json", _json_dict(task.workflow_json) or task.workflow_json,
                )
                record["ordinary_references"], _ = _physical_references(
                    archive, added, novel.id, clip_index, metadata, warnings,
                )
                record["temporal_anchors"], _ = _temporal_anchors(
                    archive, added, novel.id, clip_index, clip, contract, warnings,
                )
                if previous:
                    record["previous_av"] = {
                        **previous,
                        "package_artifact_path": artifact_paths.get(int(previous["clip_index"])),
                    }
            else:
                record["artifact"]["reason"] = path_error or "CURRENT_ARTIFACT_UNAVAILABLE"
                _warning(warnings, record["artifact"]["reason"], f"clip:{clip_index}")
        else:
            _warning(warnings, record["artifact"]["reason"], f"clip:{clip_index}")
        execution_records.append(record)

    final_assembly = _final_assembly(
        archive, added, novel.id, shot, plan, execution_records,
        f"final/shot_{int(shot.index):03d}", warnings,
    ) if classification == "CURRENT_CANONICAL" else {
        "status": "HISTORICAL_PLAN_NOT_EXPORTED" if classification == "HISTORICAL_PLAN" else "CURRENT_FINAL_UNAVAILABLE",
        "clip_plan_revision": None,
        "source_clip_task_ids": [],
        "path": None,
    }
    manifest = {
        "manifest_version": 1,
        "package_type": "SHOT_PRODUCTION",
        "generated_at": datetime.utcnow().isoformat(),
        "novel": {"id": novel.id, "title": novel.title},
        "chapter": {"id": chapter.id, "number": chapter.number, "title": chapter.title},
        "shot": {
            "id": shot.id,
            "index": shot.index,
            "duration": shot.duration,
            "description": shot.description,
            "video_description": shot.video_description,
            "primary_image": {"status": "READY" if primary_path else "UNAVAILABLE", "path": primary_path},
        },
        "resources": resources,
        "canonical_plan": {
            "classification": classification,
            "visual_states": states,
            "transitions": list(plan.get("transitions") or []) if classification == "CURRENT_CANONICAL" else [],
            "clip_plan_revision": revision if classification == "CURRENT_CANONICAL" else None,
            "clip_plan_validation": plan.get("clip_plan_validation") if classification == "CURRENT_CANONICAL" else None,
            "semantic_clips": [_clip_summary(clip) for clip in clips],
        },
        "execution": {"clips": execution_records},
        "final_assembly": final_assembly,
        "warnings": warnings,
    }
    archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def build_chapter_archive_package(
    archive: ZipFile,
    db: Session,
    novel,
    chapter,
    shots: list[Any],
) -> dict:
    """Write a current-state Chapter archive without raw directory scanning."""
    added: set[str] = set()
    warnings: list[dict] = []
    bound_names = _bound_resource_names(chapter, shots)
    resources = _write_resources(archive, added, db, novel.id, bound_names, warnings)
    shot_records = []
    for shot in sorted(shots, key=lambda item: int(item.index or 0)):
        shot_dir = f"shots/shot_{int(shot.index):03d}"
        plan = _json_dict(shot.video_director_plan)
        classification = _plan_classification(plan)
        primary_path, primary_reason = _add_binary(
            archive, added, novel.id, shot.image_url or shot.image_path,
            f"{shot_dir}/primary", ".png",
        )
        if primary_reason and primary_reason != "MISSING":
            _warning(warnings, primary_reason, f"shot:{shot.id}:primary")
        record = {
            "id": shot.id,
            "index": shot.index,
            "duration": shot.duration,
            "description": shot.description,
            "plan_classification": classification,
            "primary_image": {"status": "READY" if primary_path else "UNAVAILABLE", "path": primary_path},
            "visual_state_count": 0,
            "visual_states": [],
            "transitions": [],
            "clip_plan_revision": None,
            "semantic_clips": [],
            "execution_status": "NOT_AVAILABLE",
            "final_assembly": {"status": "CURRENT_FINAL_UNAVAILABLE", "path": None},
        }
        if classification == "HISTORICAL_PLAN":
            record["execution_status"] = "HISTORICAL_PLAN_NOT_EXPORTED"
            record["final_assembly"] = {"status": "HISTORICAL_PLAN_NOT_EXPORTED", "path": None}
            shot_records.append(record)
            continue
        if classification == "MISSING_PLAN":
            record["execution_status"] = "MISSING_PLAN"
            shot_records.append(record)
            continue

        states = _state_records(
            archive, added, novel.id, shot, plan, f"{shot_dir}/visual_states", warnings,
        )
        clips = [item for item in plan.get("clip_plan") or [] if isinstance(item, dict)]
        clips.sort(key=lambda item: int(item.get("clip_index") or 0))
        clip_records = []
        for position, clip in enumerate(clips, 1):
            clip_index = int(clip.get("clip_index") or position)
            task, metadata, _, error, _ = _resolve_current_clip(db, novel.id, chapter.id, shot, plan, clip)
            artifact_path = None
            status = "CURRENT_ARTIFACT_UNAVAILABLE"
            reason = error or "CURRENT_ARTIFACT_UNAVAILABLE"
            if task and not error:
                artifact_path, path_error = _add_binary(
                    archive, added, novel.id, task.result_url,
                    f"{shot_dir}/clips/C{clip_index:03d}", ".mp4",
                )
                if artifact_path:
                    status = "CURRENT"
                    reason = None
                else:
                    reason = path_error or reason
            if status != "CURRENT":
                _warning(warnings, reason, f"shot:{shot.id}:clip:{clip_index}")
            clip_records.append({
                **_clip_summary(clip),
                "generated_by_task_id": clip.get("generated_by_task_id"),
                "artifact": {
                    "status": status,
                    "reason": reason,
                    "artifact_kind": ((metadata.get("execution_contract") or {}).get("artifact_kind") if metadata else None),
                    "path": artifact_path,
                },
            })
        final = _final_assembly(
            archive, added, novel.id, shot, plan, clip_records,
            f"final/shots/shot_{int(shot.index):03d}", warnings,
        )
        current_count = sum((item.get("artifact") or {}).get("status") == "CURRENT" for item in clip_records)
        if clips and current_count == len(clips):
            execution_status = "COMPLETE" if final.get("status") == "CURRENT" else "CLIPS_COMPLETE"
        elif current_count:
            execution_status = "PARTIAL"
        else:
            execution_status = "INCOMPLETE"
        record.update({
            "visual_state_count": len(states),
            "visual_states": states,
            "transitions": list(plan.get("transitions") or []),
            "clip_plan_revision": int(plan.get("clip_plan_revision") or 0),
            "semantic_clips": clip_records,
            "execution_status": execution_status,
            "final_assembly": final,
        })
        shot_records.append(record)

    manifest = {
        "manifest_version": 1,
        "package_type": "CHAPTER_ARCHIVE",
        "generated_at": datetime.utcnow().isoformat(),
        "novel": {"id": novel.id, "title": novel.title},
        "chapter": {
            "id": chapter.id,
            "number": chapter.number,
            "title": chapter.title,
            "status": chapter.status,
            "content": chapter.content,
        },
        "resources": resources,
        "shots": shot_records,
        "chapter_final": {
            "status": "NOT_EXPORTED",
            "reason": "CURRENT_CHAPTER_FINAL_AUTHORITY_NOT_AVAILABLE",
            "path": None,
        },
        "warnings": warnings,
    }
    archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest
