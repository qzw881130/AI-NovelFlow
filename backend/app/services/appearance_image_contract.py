"""Appearance ImageEdit contract helpers; prompt text is loaded from local JSON."""
from copy import deepcopy
from io import BytesIO
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi import HTTPException
from PIL import Image
from app.models.novel import Character
from app.models.appearance_timeline import CharacterAppearance as Appearance, AppearanceTimelineRun
from app.models.appearance_generation import AppearanceImageRevision, AppearanceGeneration
from app.services.appearance_timeline_service import timeline_response
from app.services.chapter_asset_parse_service import digest
from app.services.file_storage import file_storage
from app.utils.path_utils import url_to_local_path, local_path_to_url
from app.services.keyframe_reference_graph import validate_keyframe_graph, semantic_graph_digest, KeyframeGraphError
from app.services.comfyui.workflows import WorkflowBuilder

VERSION = "appearance-generation-v1"
WORKFLOW_TYPE = "CHARACTER_APPEARANCE"
TASK_TYPE = "character_appearance_generation"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompt_templates" / "character_appearance_edit.json"


def load_prompt():
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    definition = json.loads(raw)
    for key in ("version", "system_prompt", "user_template", "image_prompt_suffix", "prior_appearance_instruction", "preservation_instruction"):
        if not isinstance(definition.get(key), str) or not definition[key].strip():
            raise ValueError(f"invalid appearance prompt field: {key}")
    if (any(type(definition.get(key)) is not int or definition[key] <= 0 for key in ("max_source_bytes", "max_source_pixels"))
            or type(definition.get("max_aspect_error")) not in {float, int} or not 0 <= definition["max_aspect_error"] <= 0.1):
        raise ValueError("invalid appearance image limits")
    return {"file": f"prompt_templates/{PROMPT_PATH.name}", "version": definition["version"], "hash": digest(raw), "definition": definition}


def image_source_signature(url):
    path = url_to_local_path(url) if url else None
    if not path:
        return None
    try:
        source = Path(path).resolve()
        stat = source.stat()
    except OSError:
        return None
    return {
        "path": str(source), "device": stat.st_dev, "inode": stat.st_ino,
        "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns,
    }


def image_bytes(url, policy, memo=None):
    signature = image_source_signature(url)
    if memo:
        memo.observe_file(url, signature)
    cache_key = memo.fingerprint({"url": url, "policy": policy, "source": signature}) if memo else None
    if memo:
        hit, cached = memo.lookup("image_bytes", cache_key)
        if hit:
            return cached[0], deepcopy(cached[1])
    path = url_to_local_path(url) if url else None
    if not path:
        raise HTTPException(409, "SOURCE_REFERENCE_MISSING")
    source = Path(path).resolve()
    if not source.is_relative_to(file_storage.base_dir.resolve()) or not source.is_file():
        raise HTTPException(409, "SOURCE_REFERENCE_UNAVAILABLE")
    if source.stat().st_size > policy["max_source_bytes"]:
        raise HTTPException(409, "SOURCE_REFERENCE_TOO_LARGE")
    data = source.read_bytes()
    try:
        info = inspect_image(data, policy, memo=memo)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, f"REFERENCE_IMAGE_INVALID: {exc}") from exc
    result = {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), **info}
    final_signature = image_source_signature(url)
    if memo:
        memo.observe_file(url, final_signature)
        if signature is not None and signature == final_signature:
            memo.store("image_bytes", cache_key, (data, deepcopy(result)))
    return data, result


def inspect_image(data, policy, memo=None):
    cache_key = memo.fingerprint({
        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "policy": policy,
    }) if memo else None
    if memo:
        hit, cached = memo.lookup("inspect_image", cache_key)
        if hit:
            return deepcopy(cached)
    with Image.open(BytesIO(data)) as image:
        if getattr(image, "n_frames", 1) != 1 or image.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("UNSUPPORTED_REFERENCE_IMAGE")
        width, height, fmt = image.width, image.height, image.format
        if width * height > policy["max_source_pixels"]:
            raise ValueError("REFERENCE_PIXEL_LIMIT")
        image.verify()
    with Image.open(BytesIO(data)) as image:
        image.load()
    result = {"width": width, "height": height, "format": fmt}
    if memo:
        memo.store("inspect_image", cache_key, deepcopy(result))
    return result


def current_appearance(db, appearance_id):
    asset = db.get(Appearance, appearance_id)
    if not asset or digest(asset.definition) != asset.definition_hash:
        raise HTTPException(409, "APPEARANCE_DEFINITION_UNAVAILABLE")
    actor = db.get(Character, asset.character_id)
    if not actor or actor.novel_id != asset.novel_id or not actor.entity_type or actor.is_narrator:
        raise HTTPException(409, "CHARACTER_IDENTITY_UNAVAILABLE")
    run = db.query(AppearanceTimelineRun).filter_by(novel_id=asset.novel_id, chapter_id=asset.source_chapter_id).order_by(
        AppearanceTimelineRun.created_at.desc(), AppearanceTimelineRun.id.desc()).first()
    if not run:
        raise HTTPException(409, "APPEARANCE_TIMELINE_REQUIRED")
    timeline = timeline_response(db, run)
    if timeline["effectiveStatus"] not in {"SUCCEEDED", "NEEDS_REVIEW"} or not timeline["sourceCurrent"]:
        raise HTTPException(409, "APPEARANCE_TIMELINE_NOT_CURRENT")
    chapter = next(row for row in run.result["chapters"] if row["chapterId"] == asset.source_chapter_id)
    member = next((row for row in chapter["characters"] if row["characterId"] == actor.id), None)
    if not member or not any(s["selection"]["kind"] == "APPEARANCE" and s["selection"]["appearanceId"] == asset.id for s in member["segments"]):
        raise HTTPException(409, "APPEARANCE_NOT_ACTIVE_IN_TIMELINE")
    proof = {"run_id": run.id, "input_hash": run.input_hash, "result_hash": digest(run.result), "version": run.resolver_version}
    return asset, actor, proof


def ready_revision(db, asset, policy, memo=None):
    revision = db.get(AppearanceImageRevision, asset.reference_image_revision_id) if asset.reference_image_revision_id else None
    generation = db.get(AppearanceGeneration, revision.generation_id) if revision else None
    if (asset.status != "READY" or not revision or revision.appearance_id != asset.id or asset.reference_image_url != revision.image_url
            or not generation or generation.status != "SUCCEEDED" or generation.appearance_id != asset.id
            or digest(generation.inputs) != generation.input_hash or generation.inputs["asset"]["definition_hash"] != asset.definition_hash
            or generation.execution.get("result", {}).get("sha256") != revision.sha256
            or revision.receipt.get("remote_sha256") != revision.sha256
            or generation.execution.get("output_receipt") != revision.receipt):
        raise HTTPException(409, "APPEARANCE_IMAGE_NOT_READY")
    data, info = image_bytes(revision.image_url, policy, memo=memo)
    if info["sha256"] != revision.sha256:
        raise HTTPException(409, "APPEARANCE_IMAGE_BYTES_CHANGED")
    return data, {**info, "image_revision_id": revision.id, "generation_id": revision.generation_id}


def source_reference(db, asset, actor, policy):
    # Spec §14: the only visual input is the Book's formal Character image.
    # Prior logical changes are context, independent of their image generation status.
    cursor, seen, prior = asset, {asset.id}, []
    while cursor.previous_appearance_id:
        previous = cursor.definition.get("previous") or {}
        if previous.get("kind") != "APPEARANCE" or previous.get("appearanceId") != cursor.previous_appearance_id:
            raise HTTPException(409, "PARENT_APPEARANCE_DEFINITION_CHANGED")
        if cursor.previous_appearance_id in seen:
            raise HTTPException(409, "APPEARANCE_LOGICAL_CYCLE")
        cursor, parent_actor, _ = current_appearance(db, cursor.previous_appearance_id)
        if parent_actor.id != actor.id:
            raise HTTPException(409, "PARENT_CHARACTER_MISMATCH")
        seen.add(cursor.id)
        prior.append({"appearance_id": cursor.id, "description": cursor.description, "definition_hash": cursor.definition_hash})
    previous = cursor.definition.get("previous") or {}
    if previous.get("kind") != "BASE" or previous.get("appearanceId") is not None:
        raise HTTPException(409, "BASE_REFERENCE_NOT_RESOLVED")
    if actor.generating_status in {"pending", "running", "generating"}:
        raise HTTPException(409, "BASE_REFERENCE_GENERATING")
    data, info = image_bytes(actor.image_url, policy)
    result = {**info, "kind": "CHARACTER_BASE", "character_id": actor.id, "appearance_id": None}
    if prior:
        result["prior_appearances"] = list(reversed(prior))
    return data, result


def graph_mapping(mapping):
    keys = ("load_image_node_id", "prompt_node_id", "save_image_node_id", "seed_node_id")
    if not isinstance(mapping, dict) or any(not isinstance(mapping.get(key), (str, int)) or isinstance(mapping[key], bool) or not str(mapping[key]).strip() for key in keys):
        raise ValueError("APPEARANCE_WORKFLOW_MAPPING_REQUIRED")
    if len({str(mapping[key]) for key in keys}) != len(keys):
        raise ValueError("APPEARANCE_WORKFLOW_MAPPING_COLLISION")
    return {"reference_image_node_id": str(mapping["load_image_node_id"]), "prompt_node_id": str(mapping["prompt_node_id"]),
            "save_image_node_id": str(mapping["save_image_node_id"])}


def build_graph(workflow, mapping, *, seed, prompt="", filename=None):
    graph = deepcopy(workflow)
    canonical = graph_mapping(mapping)
    node = graph.get(str(mapping["seed_node_id"]), {})
    field = {"RandomNoise": "noise_seed", "KSampler": "seed"}.get(node.get("class_type"))
    if not field or field not in node.get("inputs", {}):
        raise ValueError("UNSUPPORTED_APPEARANCE_SEED_NODE")
    node["inputs"][field] = seed
    WorkflowBuilder()._set_prompt(graph, canonical["prompt_node_id"], prompt)
    if filename is not None:
        graph[canonical["reference_image_node_id"]]["inputs"]["image"] = filename
    try:
        proof = validate_keyframe_graph(graph, canonical, reference_count=1,
                                       expected_filename=filename, expected_prompt=prompt or None)
    except KeyframeGraphError as exc:
        raise ValueError(f"APPEARANCE_GRAPH_INVALID: {exc}") from exc
    return graph, proof


def output_receipt(history, prompt_id, graph, output_node_id):
    prompt = history.get("prompt") if isinstance(history, dict) else None
    if not isinstance(prompt, list) or len(prompt) < 3 or prompt[1] != prompt_id or semantic_graph_digest(prompt[2]) != semantic_graph_digest(graph):
        raise ValueError("APPEARANCE_HISTORY_GRAPH_MISMATCH")
    status = history.get("status") or {}
    if status.get("status_str") == "error" or not (status.get("completed") is True or status.get("status_str") in {"success", "completed"}):
        raise ValueError("APPEARANCE_RESULT_NOT_COMPLETED")
    images = (history.get("outputs") or {}).get(str(output_node_id), {}).get("images")
    if not isinstance(images, list) or len(images) != 1:
        raise ValueError("APPEARANCE_OUTPUT_COUNT_INVALID")
    image = images[0]
    name, folder = image.get("filename"), image.get("subfolder", "")
    if (not isinstance(name, str) or not name or "/" in name or "\\" in name or name in {".", ".."}
            or not isinstance(folder, str) or folder.startswith("/") or "\\" in folder or ".." in folder.split("/") or image.get("type") != "output"):
        raise ValueError("APPEARANCE_OUTPUT_LOCATOR_INVALID")
    return {"prompt_id": prompt_id, "actual_graph_hash": digest(prompt[2]), "submitted_graph_hash": digest(graph),
            "semantic_graph_hash": semantic_graph_digest(prompt[2]), "actual_graph": prompt[2],
            "graph_identity_version": "reviewed-numeric-ports-v1", "output_node_id": str(output_node_id),
            "image": image, "status": status}


def receipt_url(endpoint, image):
    return endpoint.rstrip("/") + "/view?" + urlencode({key: image.get(key, "") for key in ("filename", "subfolder", "type")})


def artifact_path(novel_id, appearance_id, task_id, name):
    return file_storage.base_dir / f"story_{novel_id[:8]}" / "appearances" / appearance_id / task_id / name


def capture_source(novel_id, appearance_id, task_id, data, info):
    extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[info["format"]]
    destination = artifact_path(novel_id, appearance_id, task_id, "source" + extension)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as out:
        out.write(data)
    return local_path_to_url(str(destination))
