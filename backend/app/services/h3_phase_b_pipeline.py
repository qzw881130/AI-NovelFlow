"""Opt-in semantic Clip adapter for the existing Phase B Director/Compiler.

No queue, workflow selection or video persistence lives here. The Clip worker
continues to own those operations. Legacy #13/#14 is an explicit alternative,
never an automatic recovery call after a failed Phase B request.
"""
import hashlib
import json
from app.services.video_result_mode import is_candidate
from app.services.h3_prompt_language import task_language, LANGUAGE_CONTRACT
from copy import deepcopy
from pathlib import Path
from time import monotonic

from app.services import h3_single_stage_experiment as compiler
from app.services.director_context import effective_visual_states
from app.services.h3_continuation import continuation_contract, target_frames
from app.services.h3_execution_optimizer import workflow_duration_limits
from app.services.video_director_ai import safe_json_dict, append_video_ai_call, resolve_prompt_template
from app.utils.path_utils import url_to_local_path

PIPELINE = "phase_b"
# Invalidate compiled reuse after the Subject-reference assembly contract change.
VERSION = "H3_PHASE_B_LIMITED_V3"
TEMPLATE_TYPE = "h3_multi_keyframe_director_phase_b"


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else
                          json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime_snapshot(*, plan, builder_input, manifest, workflow, previous_path, execution_contract,
                     shot_description=None, video_prompt_language=None):
    """Adapt live, already validated upstream data to Phase B's saved-input contract."""
    capability = builder_input["clip"]["capability"]
    expected_type = {"GENERATE": "multi_reference_video", "EXTEND": "VIDEO_CONTINUATION",
                     "TEMPORAL_EXTEND": "TEMPORAL_EXTEND"}[capability]
    if workflow.type != expected_type:
        raise ValueError("PHASE_B_WORKFLOW_MODE_MISMATCH")
    # Never feed prior Prompt/optimized times, task results or #14 answers back
    # into planning. The same upstream projector used by the legacy builder is used.
    canonical = {k: deepcopy(plan.get(k)) for k in ("keyframes", "transitions", "dialogue_timeline_source", "clip_plan")}
    canonical["keyframes"], start_resolution = effective_visual_states(canonical["keyframes"] or [], shot_description)
    references = deepcopy(manifest)
    temporal = deepcopy((execution_contract.get("temporal_anchor_manifest") or {}).get("anchors", []))
    resources = [(f"<Picture {r['slot']}>", r) for r in references["references"]]
    resources += [("TemporalAnchor:" + r["anchor_id"], r) for r in temporal]
    hashes = {}
    for key, resource in resources:
        resource["local_path"] = resource.get("local_path") or url_to_local_path(resource["image_url"])
        hashes[key] = file_hash(resource["local_path"])
    workflow_data = {k: getattr(workflow, k, None) for k in ("id", "type", "workflow_json", "node_mapping")}
    data = {"canonical_plan": canonical, "builder_input": deepcopy(builder_input),
            "reference_manifest": references, "workflow": workflow_data,
            "previous_video_path": previous_path,
            "physical_evidence": {"resource_hashes": hashes, "previous_clip": execution_contract.get("previous_clip"),
                "temporal_anchors": temporal,
                "duration_limits": workflow_duration_limits(safe_json_dict(workflow.extension), capability)},
            # This limited route explicitly has no added score. It does not
            # claim to infer a music instruction from Canonical or a prior #13.
            "music_contract": {"value": "N/A", "source_stage": "PHASE_B_RUNTIME_POLICY", "interpretation": "NO_ADDED_SCORE"},
            "user_camera_requirements": deepcopy(plan.get("user_camera_requirements") or {
                "status": "UNKNOWN", "requirements": [], "source": "No explicit structured user lock recorded; preserve Canonical camera facts"})}
    if execution_contract.get("execution_projection") is not None:
        data["physical_evidence"]["execution_projection"] = deepcopy(execution_contract["execution_projection"])
        # Preserve the original anchor catalog for strict policy replay, including
        # anchors deliberately absent from the physical manifest.
        canonical["temporal_anchors"] = deepcopy(plan.get("temporal_anchors") or [])
    if video_prompt_language is not None:
        data["video_prompt_language"] = video_prompt_language
    data["source"] = {"kind": "LIVE_SEMANTIC_CLIP", "start_visual_resolution": start_resolution, "hashes": {
        k: compiler._snapshot_digest(v) for k, v in data.items() if k != "previous_video_path"}}
    return data


def _director_input_without_preview_urls(llm_input):
    """Ignore derived preview URLs while comparing Director inputs."""
    payload = deepcopy(llm_input)
    for item in payload.get("visual_previews") or []:
        if isinstance(item, dict):
            item.pop("proxy_url", None)
    for item in (payload.get("previous_av") or {}).get("preview_frames") or []:
        if isinstance(item, dict):
            item.pop("proxy_url", None)
    return payload


def input_fingerprint(prepared, template):
    # Preview filenames are derived caches, not authority; resource byte hashes,
    # source times, Canonical, route and the selected template are authority.
    # Frozen video_prompt_language stays in the input and separates language caches.
    payload = _director_input_without_preview_urls(prepared["llm_input"])
    policy = prepared.get("execution_projection") or {}
    if policy.get("continuation_mode", "AUTO") != "AUTO":
        payload["execution_policy"] = policy
    return digest({"version": VERSION, "input": payload, "resources": prepared["resource_hashes"],
                   "workflow": prepared["source"]["hashes"]["workflow"],
                   "template_id": template.id, "template": template.template})


def reuse_plan_workflow_blocker(plan, clip_index, workflow_id):
    """Catch an impossible Phase B reuse before creating a Clip task.

    The full fingerprint is still checked by the worker; this only handles the
    common case where the selected physical workflow changed after planning.
    """
    compiled = [record for call in plan.get("ai_calls") or []
                if call.get("task_type") == TEMPLATE_TYPE
                and int(call.get("clip_index") or 0) == int(clip_index)
                for record in [call.get("parsed_result") or {}]
                if record.get("version") == VERSION and record.get("status") == "COMPILED"]
    if not compiled:
        return "当前 Clip 没有可复用的 Phase B 导演计划，请选择“重新生成片段”重新规划。"
    if not any(str(record.get("workflow_id")) == str(workflow_id) for record in compiled):
        return "视频工作流已更换，旧提示词的 Phase B 导演计划不能用于当前工作流。请选择“重新生成片段”重新规划。"
    return None


def reusable_phase_b_clip_prompt(plan, clip, workflow_id):
    """Read the compiled Phase B prompt without applying legacy prompt projection rules."""
    prompt = clip.get("prompt_text") or ""
    if not isinstance(prompt, str) or not prompt.strip():
        return ""
    clip_index = int(clip.get("clip_index") or 0)
    for call in reversed(plan.get("ai_calls") or []):
        record = call.get("parsed_result") or {}
        if (call.get("task_type") == TEMPLATE_TYPE
                and int(call.get("clip_index") or 0) == clip_index
                and record.get("version") == VERSION
                and record.get("status") == "COMPILED"
                and str(record.get("workflow_id")) == str(workflow_id)
                and record.get("final_prompt_sha256") == digest(prompt)):
            return prompt
    return ""


def preflight(prepared, result):
    """Phase B fact/format contract; #14 prose heuristics remain diagnostics only."""
    review = result.get("review") or {}
    checks = {**review.get("structure", {}), **review.get("structured_authority", {}),
              **result.get("continuation_checks", {})}
    checks["compiler_completed"] = result.get("status") == "CANDIDATE_FOR_REVIEW"
    checks["contract_checks_present"] = (set(compiler.STRUCTURAL_CHECKS) <= set(review.get("structure", {}))
                                           and len(review.get("structured_authority", {})) == 8)
    checks["picture_audit"] = result.get("picture_audit", {}).get("passed") is True
    # Scope and all Canonical states/actions are retained independently from
    # optional reference choices. Natural-language coverage is not certified.
    checks["canonical_scope_available"] = compiler.has_phase_b_canonical_scope(
        prepared["llm_input"]["clip"], prepared["llm_input"]["canonical"])
    return {"contract": VERSION, "passed": all(v is True for v in checks.values()), "checks": checks,
            "native_diagnostics": review.get("native_prompt_diagnostics", {}),
            "director_semantics": "REVIEW_REQUIRED; no automatic natural-language quality certification"}


async def build_phase_b_prompt(*, db, task, novel, shot, builder_input, manifest, workflow,
                               previous_path, execution_contract, llm=None):
    """Persist one #13 attempt (or a matching compiled reuse); never call #14/A."""
    from app.services.llm_service import LLMService
    from app.services.llm.http_retry import single_attempt_llm_request
    template = resolve_prompt_template(db, novel, None, TEMPLATE_TYPE)
    plan = safe_json_dict(shot.video_director_plan)
    metadata = safe_json_dict(task.metadata_json)
    language = task_language(metadata)
    # Language rules belong to the selected template; the choice is input data.
    system_prompt = template.template
    record = {"pipeline": PIPELINE, "version": VERSION, "status": "PREPARING", "clip_index": builder_input["clip"]["clip_index"],
              "template": {"id": template.id, "name": template.name, "sha256": digest(template.template)},
              "workflow_id": workflow.id, "workflow_type": workflow.type, "llm_call_count": 0}
    if language is not None:
        record.update(video_prompt_language=language, language_contract=LANGUAGE_CONTRACT,
                      effective_system_prompt=system_prompt, effective_system_prompt_sha256=digest(system_prompt))

    def persist():
        current = safe_json_dict(task.metadata_json)
        current["h3_phase_b"] = record
        task.metadata_json = json.dumps(current, ensure_ascii=False)
        db.commit()

    started = monotonic()
    try:
        snapshot = runtime_snapshot(plan=plan, builder_input=builder_input, manifest=manifest, workflow=workflow,
                                    previous_path=previous_path, execution_contract=execution_contract,
                                    shot_description=getattr(shot, "description", None), video_prompt_language=language)
        prepared = compiler.prepare_multi_keyframe_phase_b(snapshot, runtime=True)
        if prepared["status"] != "PREPARED":
            raise ValueError("PHASE_B_INPUT_NOT_COVERED: " + "; ".join(prepared.get("reasons") or ["Unknown input error"]))
        fingerprint = input_fingerprint(prepared, template)
        record.update(input_fingerprint=fingerprint, director_input=prepared["llm_input"],
                      resource_hashes=prepared["resource_hashes"], continuation=prepared["continuation"])
        cached = None
        if metadata.get("skip_llm_when_prompt_exists"):
            calls = (plan.get("ai_calls") or []) + ([{"parsed_result": metadata.get("h3_phase_b") or {}}] if is_candidate(metadata) else [])
            cached = next((c.get("parsed_result") for c in reversed(calls)
                           if (c.get("parsed_result") or {}).get("version") == VERSION
                           and (c.get("parsed_result") or {}).get("input_fingerprint") == fingerprint
                           and (c.get("parsed_result") or {}).get("status") == "COMPILED"), None)
            if cached:
                record["reuse_scope"] = "EXACT_FINGERPRINT"
            else:
                # Output/step node mappings can change after a Clip was planned.
                # Reuse its Director response only when the semantic input,
                # physical resources, continuation contract, selected template,
                # workflow identity, and requested current prompt still match.
                clip = next((item for item in plan.get("clip_plan") or []
                             if int(item.get("clip_index") or 0) == int(record["clip_index"])), {})
                requested_prompt = metadata.get("phase_b_requested_prompt") or clip.get("prompt_text") or ""
                current_input = _director_input_without_preview_urls(prepared["llm_input"])
                cached = next((candidate for call in reversed(calls)
                               for candidate in [call.get("parsed_result") or {}]
                               if requested_prompt.strip()
                               and candidate.get("version") == VERSION
                               and candidate.get("status") == "COMPILED"
                               and candidate.get("clip_index") == record["clip_index"]
                               and candidate.get("workflow_id") == workflow.id
                               and candidate.get("workflow_type") == workflow.type
                               and candidate.get("template") == record["template"]
                               and candidate.get("final_prompt_sha256") == digest(requested_prompt)
                               and _director_input_without_preview_urls(candidate.get("director_input") or {}) == current_input
                               and candidate.get("resource_hashes") == prepared["resource_hashes"]
                               and candidate.get("continuation") == prepared["continuation"]
                               and candidate.get("raw_response")), None)
                if cached:
                    record["reuse_scope"] = "SAME_SEMANTIC_INPUT"
            if not cached:
                raise ValueError("PHASE_B_REUSABLE_PLAN_MISSING: re-run Director for this input/template")
        if cached:
            raw = cached["raw_response"]
            record["reuse"] = True
        else:
            task.current_step = "#13 Phase B 单阶段导演规划..."
            record.update(status="DIRECTING", llm_call_count=1)
            persist()
            with single_attempt_llm_request():
                response = await (llm or LLMService()).chat_completion(
                    system_prompt=system_prompt, user_content=json.dumps(prepared["llm_input"], ensure_ascii=False),
                    images=prepared["images"], response_format="json_object", temperature=0.3, max_tokens=4500,
                    task_type=TEMPLATE_TYPE, prompt_template_name=template.name,
                    novel_id=novel.id, chapter_id=shot.chapter_id, shot_id=shot.id)
            record["llm_response"] = response
            if not response.get("success"):
                raise ValueError("PHASE_B_DIRECTOR_FAILED: " + str(response.get("error") or response.get("message") or "LLM failed"))
            raw = response.get("content") or ""
        record["raw_response"] = raw
        result = compiler.compile_multi_keyframe_phase_b(prepared, raw)
        requested_prompt = metadata.get("phase_b_requested_prompt") or ""
        if metadata.get("skip_llm_when_prompt_exists") and requested_prompt.strip() and result.get("prompt") != requested_prompt:
            raise ValueError("PHASE_B_CURRENT_PROMPT_CHANGED: re-run Director for this input/template")
        record["compiler_result"] = result
        record["preflight"] = preflight(prepared, result)
        if not record["preflight"]["passed"]:
            raise ValueError("PHASE_B_PREFLIGHT_FAILED: " + str(result.get("reasons") or record["preflight"]["checks"]))
        record.update(status="COMPILED", elapsed_seconds=round(monotonic() - started, 3),
                      final_prompt_sha256=digest(result["prompt"]))
        task.prompt_text = result["prompt"]
        persist()
        if not is_candidate(metadata):
            append_video_ai_call(shot, {"step": "13", "title": "#13 单阶段导演规划（Phase B）", "task_type": TEMPLATE_TYPE,
                "prompt_template_name": template.name, "clip_index": record["clip_index"], "parsed_result": record,
                "response": raw, "final_prompt": result["prompt"], "workflow_type": workflow.type})
        db.commit()
        return result["prompt"]
    except Exception as exc:
        record.update(status="FAILED", error=str(exc), elapsed_seconds=round(monotonic() - started, 3))
        persist()
        raise


def apply_execution(task, original_duration, manifest, paths):
    """Project the compiled selection into the worker's existing physical route."""
    metadata = safe_json_dict(task.metadata_json)
    record = metadata.get("h3_phase_b") or {}
    if record.get("status") != "COMPILED" or not record.get("preflight", {}).get("passed"):
        raise ValueError("PHASE_B_EXECUTION_NOT_APPROVED")
    result = record["compiler_result"]
    if digest(task.prompt_text) != record["final_prompt_sha256"]:
        raise ValueError("PHASE_B_FINAL_PROMPT_CHANGED")
    selected = deepcopy(result["reference_manifest"])
    original = (manifest or {}).get("references", [])
    if len(original) != len(paths or []):
        raise ValueError("PHASE_B_REFERENCE_PATH_MISMATCH")
    selected_paths = []
    for ref in selected["references"]:
        slot = ref["source_slot"]
        source = original[slot - 1]
        path = paths[slot - 1]
        if (source["image_url"] != ref["image_url"] or file_hash(path) != record["resource_hashes"][f"<Picture {slot}>"]):
            raise ValueError("PHASE_B_REFERENCE_SOURCE_CHANGED")
        selected_paths.append(path)
    duration = result["execution_decisions"]["timing"]["optimized_duration"]
    # Compiler projects timing/alias only. Physical paths come from the frozen
    # live asset catalog, never from Director prose or a guessed filename.
    temporal = deepcopy(result["temporal_manifest"])
    original_temporal = {a["anchor_id"]: a for a in
                         (metadata.get("execution_contract", {}).get("temporal_anchor_manifest") or {}).get("anchors", [])}
    for anchor in temporal["anchors"]:
        source = original_temporal[anchor["anchor_id"]]
        path = source.get("local_path") or url_to_local_path(source["image_url"])
        if source["image_url"] != anchor["image_url"] or file_hash(path) != record["resource_hashes"]["TemporalAnchor:" + anchor["anchor_id"]]:
            raise ValueError("PHASE_B_TEMPORAL_SOURCE_CHANGED")
        anchor["local_path"] = path
    durations = {"original_duration": original_duration, "optimized_duration": duration, "effective_duration": duration,
                 "duration_delta": duration - original_duration, "duration_source": VERSION,
                 "target_frame_count": target_frames(duration)}
    metadata.update(durations, video_reference_manifest=selected)
    metadata.setdefault("execution_contract", {}).update(h3_execution=durations,
        temporal_anchor_manifest=temporal)
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    task.reference_images = json.dumps([{"label": f"Picture {r['slot']} / {r['kind']}", "url": r["image_url"]}
                                        for r in selected["references"]], ensure_ascii=False)
    return duration, temporal, selected, selected_paths


def verify_submission(task, workflow, graph, uploads, previous_path=None):
    """Check configured inputs and saved sources before POST /prompt.

    ComfyUI owns the graph behind those mapped inputs; its topology can change.
    """
    metadata = safe_json_dict(task.metadata_json)
    record = metadata["h3_phase_b"]
    result = record["compiler_result"]
    mapping = safe_json_dict(workflow.node_mapping)
    prompt_inputs = graph.get(str(mapping.get("prompt_node_id")), {}).get("inputs", {})
    checks = {"prompt": result["prompt"] == task.prompt_text and any(
                  prompt_inputs.get(key) == result["prompt"] for key in ("prompt", "text", "value")),
              "duration": graph.get(str(mapping.get("duration_seconds_node_id")), {}).get("inputs", {}).get("value") == metadata["effective_duration"],
              "workflow": workflow.id == record["workflow_id"] and workflow.type == record["workflow_type"]}
    filenames = uploads["reference_filenames"]
    expected = result["reference_manifest"]["references"]
    checks["picture_count"] = len(filenames) == len(expected)
    checks["picture_order"] = all(
        graph.get(str(mapping.get(f"load_image_node_{i+1}")), {}).get("inputs", {}).get("image") == filename
        for i, filename in enumerate(filenames))
    checks["picture_bytes"] = all(file_hash(r.get("local_path") or url_to_local_path(r["image_url"])) ==
                                  record["resource_hashes"][f"<Picture {r['source_slot']}>"] for r in expected)
    if record.get("continuation"):
        from types import SimpleNamespace
        bound = SimpleNamespace(id=workflow.id, type=workflow.type, node_mapping=workflow.node_mapping,
                                workflow_json=json.dumps(graph))
        current = continuation_contract(bound, metadata["capability"], previous_path, metadata["execution_contract"])
        checks["previous_av"] = current == record["continuation"]
        checks["previous_upload"] = graph.get(str(mapping.get("load_video_node_id")), {}).get("inputs", {}).get("video") == uploads.get("previous_filename")
    else:
        checks["no_previous_av"] = not previous_path
    anchors = result["temporal_manifest"]["anchors"]
    checks["temporal_bytes"] = all(file_hash(url_to_local_path(a["image_url"])) ==
                                   record["resource_hashes"]["TemporalAnchor:" + a["anchor_id"]] for a in anchors)
    checks["temporal_images"] = len(uploads.get("temporal_filenames", [])) == len(anchors) and all(
        graph.get(str(mapping.get(f"keyframe_node_{i+1}")), {}).get("inputs", {}).get("image") == name
        for i, name in enumerate(uploads.get("temporal_filenames", [])))
    record["submission_preflight"] = {"passed": all(checks.values()), "checks": checks, "graph_sha256": digest(graph)}
    metadata["h3_phase_b"] = record
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    if not all(checks.values()):
        raise ValueError("PHASE_B_SUBMISSION_BINDING_FAILED: " + ", ".join(k for k, v in checks.items() if not v))
