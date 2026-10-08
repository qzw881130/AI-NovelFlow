"""Read-only execution projection; deliberately does not import generation services."""
import json
import re

from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.services.inspector_frame_service import InspectorFrameService, build_mapping, finite, fraction
from app.services.inspector_store import InspectorError, InspectorStore, digest, utc_now

HEADERS = ("subject_definitions", "official_character_identity_lock", "keyframe_timeline", "dialogue_timeline",
           "summary", "detailed_description", "overall_soundscape", "reference_authority",
           "character_identity_binding", "existing_body_binding", "initial_body_binding", "motion_ownership",
           "visual_attention_owner", "foreground_speaker", "background_entrant", "background_motion_subject")
DEDICATED = HEADERS[-4:]


def decode(value, fallback, warnings, name):
    if not value:
        return fallback
    try:
        result = json.loads(value) if isinstance(value, str) else value
        if not isinstance(result, type(fallback)):
            raise ValueError(name)
        return result
    except (ValueError, TypeError):
        warnings.append(f"INVALID_JSON:{name}")
        return fallback


def source(kind, entity_id, path, value, revision=None, **extra):
    statuses = {"TASK_SNAPSHOT": "EXECUTION_SNAPSHOT", "SUBMITTED_WORKFLOW": "EXECUTION_SNAPSHOT",
                "FINAL_PROMPT_TEXT": "FINAL_PROMPT", "CURRENT_PLAN": "CURRENT_PLAN", "MEDIA_PROBE": "EXPLICIT"}
    return {"kind": kind, "status": statuses.get(kind, "SOURCE_NOT_AVAILABLE"), "entity_id": entity_id,
            "path": path, "content_hash": digest(value), "source_revision": revision, "observed_at": utc_now(),
            "relation_to_execution": "CURRENT_ONLY" if kind == "CURRENT_PLAN" else "EXACT", **extra}


def prompt_sections(prompt, task_id, node_id=None):
    matches = list(re.finditer(r"(?m)^(" + "|".join(HEADERS) + r"):\s*\n", prompt))
    sections = {}
    for i, match in enumerate(matches):
        start, end = match.end(), matches[i + 1].start() if i + 1 < len(matches) else len(prompt)
        sections[match[1]] = {"text": prompt[start:end], "text_start": start, "text_end": end,
                             "source": source("FINAL_PROMPT_TEXT", task_id, f"prompt/{match[1]}", prompt,
                                              text_start=start, text_end=end, submitted_node_id=node_id)}
    return sections


def submitted_evidence(graph, physical):
    """Index only a directly connected, known H3 text input. Never use current node_mapping."""
    def links(node):
        for v in (node.get("inputs") or {}).values():
            if isinstance(v, list) and len(v) == 2 and str(v[0]) in graph and isinstance(v[1], int):
                yield str(v[0])
    roots = [str(physical["output_node_id"])] if str(physical.get("output_node_id")) in graph else [
        k for k, n in graph.items() if isinstance(n, dict) and n.get("inputs", {}).get("save_output") is True]
    reachable = set()
    stack = list(roots)
    while stack:
        key = stack.pop()
        if key not in reachable:
            reachable.add(key)
            stack.extend(links(graph[key]))
    nodes = [(k, n) for k, n in graph.items() if isinstance(n, dict)
             and n.get("class_type", "").startswith("MiniMaxH3") and "prompt" in n.get("inputs", {})
             and roots and k in reachable]
    candidates = []
    for key, node in nodes:
        value = node["inputs"]["prompt"]
        if isinstance(value, str):
            candidates.append({"text": value, "node_id": key, "input": "prompt", "h3_node_id": key})
        elif isinstance(value, list) and len(value) == 2 and value[1] == 0:
            provider = graph.get(str(value[0]), {})
            known = {"CR Prompt Text": "prompt", "PrimitiveString": "value", "PrimitiveStringMultiline": "value"}
            input_name = known.get(provider.get("class_type"))
            text = provider.get("inputs", {}).get(input_name) if input_name else None
            if isinstance(text, str):
                candidates.append({"text": text, "node_id": str(value[0]), "input": input_name, "h3_node_id": key})
    selected = candidates[0] if len(candidates) == 1 else None
    anchor_nodes, previous_nodes = [], []
    for key, node in graph.items():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") == "MiniMaxH3CustomKeyframes":
            try:
                state = json.loads(node.get("inputs", {}).get("keyframe_state", "{}"))
            except (ValueError, TypeError):
                state = {}
            anchor_nodes.append({"node_id": key, "positions": state.get("positions", []), "inputs": node.get("inputs", {})})
        if node.get("class_type") == "VHS_LoadVideoFFmpeg":
            previous_nodes.append({"node_id": key, "inputs": node.get("inputs", {})})
    latent = None
    # The one audited expression is indexed explicitly; no eval of arbitrary graph text.
    expression = "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17"
    for _, node in nodes:
        length = node["inputs"].get("length")
        if isinstance(length, int):
            latent = length
        elif isinstance(length, list) and len(length) == 2:
            expr = graph.get(str(length[0]), {}).get("inputs", {})
            av = expr.get("values.a")
            if expr.get("expression") == expression and isinstance(av, list) and len(av) == 2:
                value = finite(graph.get(str(av[0]), {}).get("inputs", {}).get("value"))
                if value is not None:
                    count = max(5, round(value * 24))
                    latent = count + (5 - count % 17) % 17
    return {"prompt": selected, "prompt_status": "EXECUTION_SNAPSHOT" if selected else "SOURCE_NOT_AVAILABLE",
            "prompt_candidates": [{k: v for k, v in c.items() if k != "text"} for c in candidates],
            "anchor_nodes": anchor_nodes, "previous_av_nodes": previous_nodes,
            "requested_latent_frame_count": latent, "output_roots": roots}


def expected_at_time(projection, time):
    if projection["time_mapping"]["time_domain"] != "CLIP_LOCAL":
        return {"status": "DEGRADED", "dialogues": [], "transitions": [], "semantic_states": [],
                "message": "Clip 映射未确认，仅提供 Native 画面和未定时规则"}
    active = lambda e: e.get("start") is not None and e["start"] <= time and e.get("end") is not None and time < e["end"]
    states = sorted([e for e in projection["events"] if e["type"] == "SEMANTIC_KF" and e.get("start") is not None], key=lambda e: e["start"])
    anchors = [e for e in projection["events"] if e["type"] == "PHYSICAL_ANCHOR"]
    return {"status": "EXPLICIT", "time_seconds": time,
            "dialogues": [e for e in projection["events"] if e["type"] == "DIALOGUE" and active(e)],
            "transitions": [e for e in projection["events"] if e["type"] == "TRANSITION" and active(e)],
            "previous_state": next((e for e in reversed(states) if e["start"] <= time), None),
            "next_state": next((e for e in states if e["start"] > time), None),
            "semantic_distances": [{"id": e["id"], "distance": e["start"] - time} for e in states if e["start"] >= 0],
            "anchor_distances": [{"id": e["id"], "distance": e["start"] - time} for e in anchors if e.get("start") is not None],
            "rules": [e for e in projection["events"] if e["type"] in ("LIFECYCLE", "MOTION", "CAMERA") and (active(e) or e.get("start") is None)]}


class ClipExecutionInspectorService:
    def __init__(self, db=None, store=None, frames=None):
        self.db = db
        self.store = store or InspectorStore()
        self.frames = frames or InspectorFrameService(self.store)

    def get(self, task_id, artifact_id=None):
        with self.db.no_autoflush:
            task = self.db.get(Task, task_id)
            if task is None:
                raise InspectorError("TASK_NOT_FOUND", "执行任务不存在，可从保存的分析重新打开", 404)
            if task.type != "shot_video":
                raise InspectorError("NOT_VIDEO_EXECUTION", "此任务没有视频执行证据", 422)
            shot = self.db.get(Shot, task.shot_id) if task.shot_id else None
            if shot and shot.chapter_id != task.chapter_id:
                raise InspectorError("SOURCE_IDENTITY_MISMATCH", "任务与片段归属不一致", 409)
            chapter = self.db.get(Chapter, task.chapter_id) if task.chapter_id else None
            if chapter and chapter.novel_id != task.novel_id:
                raise InspectorError("SOURCE_IDENTITY_MISMATCH", "任务与章节归属不一致", 409)
            projection, evidence = self.project(task, shot)
        if artifact_id and projection["artifact"]["artifact_id"] != artifact_id:
            raise InspectorError("SOURCE_CHANGED", "此任务的执行内容已改变，请重新选择执行结果或打开保存的分析", 409)
        return projection, evidence

    def project(self, task, shot=None):
        warnings = []
        metadata = decode(task.metadata_json, {}, warnings, "Task.metadata_json")
        graph = decode(task.workflow_json, {}, warnings, "Task.workflow_json")
        plan = decode(shot.video_director_plan if shot else None, {}, warnings, "Shot.video_director_plan")
        contract = metadata.get("execution_contract") or {}
        physical = metadata.get("physical_output") or {}
        clip = contract.get("clip") or {}
        index = clip.get("clip_index", metadata.get("clip_index"))
        revision = clip.get("clip_plan_revision", metadata.get("clip_plan_revision"))
        current_clip = next((c for c in plan.get("clip_plan", []) if c.get("clip_index") == index), {})
        start = finite(clip.get("start_seconds"))
        end = finite(clip.get("end_seconds"))
        duration = finite(clip.get("duration_seconds", metadata.get("planned_duration", metadata.get("requested_duration"))))
        timing_source = "EXECUTION_SNAPSHOT"
        if start is None and current_clip:
            start, end = finite(current_clip.get("start_time")), finite(current_clip.get("end_time"))
            duration = finite(current_clip.get("planned_duration")) or (end - start if start is not None and end is not None else None)
            timing_source = "CURRENT_PLAN"
        capability = contract.get("capability", metadata.get("capability", "UNKNOWN"))
        ref = {"novel_id": task.novel_id, "chapter_id": task.chapter_id, "shot_id": task.shot_id,
               "shot_index": shot.index if shot else None, "clip_index": index, "clip_plan_revision": revision,
               "legacy": not bool(contract)}
        submitted = submitted_evidence(graph, physical)
        task_prompt = task.prompt_text or ""
        final_prompt = submitted["prompt"]["text"] if submitted["prompt"] else task_prompt
        conflicts = []
        if submitted["prompt"] and final_prompt != task_prompt:
            conflicts.append({"code": "TASK_PROMPT_DIFFERS_FROM_SUBMITTED", "task_prompt_hash": digest(task_prompt),
                              "submitted_prompt_hash": digest(final_prompt)})
        if current_clip and (plan.get("clip_plan_revision") != revision or (current_clip.get("prompt_text") and current_clip["prompt_text"] != final_prompt)):
            conflicts.append({"code": "CURRENT_PLAN_DIFFERS_FROM_EXECUTION", "current_revision": plan.get("clip_plan_revision"), "execution_revision": revision})
        try:
            if physical.get("physical_output_role") == "RAW_CONTEXT_OUTPUT":
                raise InspectorError("RAW_CONTEXT_NOT_FINAL", "选中结果是原始上下文输出，未作为最终 Native 画面", 422)
            media = self.frames.probe(task.result_url, task.novel_id, task.id)
        except InspectorError as exc:
            media = {"status": "SOURCE_NOT_AVAILABLE", "reason": exc.code, "warnings": [exc.message]}
        if media.get("status") == "EXPLICIT":
            for key in ("frame_count", "sha256", "fps"):
                measured = media.get("video_sha256") if key == "sha256" else media.get(key)
                mismatch = fraction(physical[key]) != fraction(measured) if key == "fps" and key in physical else key in physical and physical[key] != measured
                if mismatch:
                    conflicts.append({"code": "PHYSICAL_OUTPUT_DIFFERS_FROM_MEDIA", "field": key, "snapshot": physical[key], "measured": measured})
        mapping = build_mapping(media, contract, physical, duration)
        # Historical timing absent: Native browsing is retained instead of inventing a Clip grid.
        if not contract:
            warnings.append("EXECUTION_SNAPSHOT_MISSING")
        node_id = submitted["prompt"]["node_id"] if submitted["prompt"] else None
        sections = prompt_sections(final_prompt, task.id, node_id)
        subjects = {}
        for token, name in re.findall(r"(<Subject\s+\d+>)\s+is\s+([^,，\n]+)", sections.get("subject_definitions", {}).get("text", "")):
            subjects[name.strip()] = token
        authority = []
        for title, names in [("Dialogue ownership / Speech authority", ["dialogue_timeline"]),
                             ("Motion ownership", ["motion_ownership"]), ("Body lifecycle", ["existing_body_binding", "initial_body_binding"]),
                             ("Camera / transition text", ["detailed_description"]), ("Reference authority", ["reference_authority", "character_identity_binding"]),
                             ("Subject definitions", ["subject_definitions"])]:
            found = [sections[name] for name in names if name in sections]
            authority.append({"title": title, "status": "FINAL_PROMPT" if found else "SOURCE_NOT_AVAILABLE",
                              "presence": "PRESENT_TEXT" if found else "UNKNOWN", "sections": found,
                              "submitted_verified": bool(submitted["prompt"])})
        for name in DEDICATED:
            section = sections.get(name)
            # Dedicated schema/header absence is distinct from absence of relevant prose.
            authority.append({"title": name.replace("_", " ").title(),
                              "status": "FINAL_PROMPT" if section else ("ABSENT" if sections else "SOURCE_NOT_AVAILABLE"),
                              "presence": "PRESENT_TEXT" if section else ("ABSENT_EXPLICIT_FIELD" if sections else "UNKNOWN"),
                              "sections": [section] if section else [], "submitted_verified": bool(submitted["prompt"]),
                              "message": None if section else "显式独立字段缺失；相关入场、运动要求请查看已有原文"})
        events = []
        def event(identity, kind, label, t=None, finish=None, payload=None, src=None, timing=None, **extra):
            item = {"id": identity, "type": kind, "label": label, "start": t, "end": finish,
                    "timing_kind": timing or ("POINT" if t is not None and finish is None else "INTERVAL" if t is not None else "UNTIMED"),
                    "time_domain": "CLIP_LOCAL", "payload": payload or {}, "source_refs": src or [], **extra}
            events.append(item)
            return item
        assignment = metadata.get("dialogue_assignment")
        assignment_kind = "TASK_SNAPSHOT"
        if not isinstance(assignment, list):
            assignment, assignment_kind = current_clip.get("dialogue_assignment", []), "CURRENT_PLAN"
        prompt_dialogues = {}
        text = sections.get("dialogue_timeline", {}).get("text", "")
        blocks = list(re.finditer(r"(?m)^(D\d+(?:\.part\d+)?):\s*\n", text))
        for i, match in enumerate(blocks):
            block = text[match.end():blocks[i + 1].start() if i + 1 < len(blocks) else len(text)]
            def field(name):
                m = re.search(r"(?m)^\s*" + name + r":\s*([^\n]+)", block)
                return m[1].strip() if m else None
            prompt_dialogues[match[1]] = {"subject": field("speaker"), "text": field("exact_dialogue"),
                                        "start": finite((field("start_time") or "").rstrip("s")),
                                        "end": finite((field("end_time") or "").rstrip("s"))}
        for i, span in enumerate(assignment):
            identity = span.get("dialogue_id", f"D?{i}")
            parsed = prompt_dialogues.get(identity, {})
            t = finite(span.get("clip_start_time"))
            finish = finite(span.get("clip_end_time"))
            if t is None and start is not None and finite(span.get("start_time")) is not None:
                t = round(float(span["start_time"]) - start, 9)
            if finish is None and start is not None and finite(span.get("end_time")) is not None:
                finish = round(float(span["end_time"]) - start, 9)
            src = [source(assignment_kind, task.id if assignment_kind == "TASK_SNAPSHOT" else task.shot_id,
                          f"dialogue_assignment/{i}", span, revision)]
            if parsed:
                src.append(sections["dialogue_timeline"]["source"])
                if parsed.get("start") != t or parsed.get("end") != finish or parsed.get("text") != span.get("text"):
                    conflicts.append({"code": "DIALOGUE_ASSIGNMENT_DIFFERS_FROM_PROMPT", "dialogue_id": identity,
                                      "assignment": {"start": t, "end": finish, "text": span.get("text")}, "prompt": parsed})
            event(f"dialogue:{identity}:{i}", "DIALOGUE", f"{identity} · {parsed.get('subject') or subjects.get(span.get('speaker'), '')} / {span.get('speaker', '')}",
                  t, finish, {**span, "subject_token": parsed.get("subject") or subjects.get(span.get("speaker")), "prompt_event": parsed}, src)
        if not assignment:
            for identity, parsed in prompt_dialogues.items():
                event(f"dialogue:prompt:{identity}", "DIALOGUE", f"{identity} · {parsed.get('subject', '')}", parsed["start"], parsed["end"],
                      {"dialogue_id": identity, "text": parsed["text"], "subject_token": parsed["subject"]}, [sections["dialogue_timeline"]["source"]])
        anchors = (contract.get("temporal_anchor_manifest") or {}).get("anchors", [])
        semantic_by_kf = {}
        grid_rate = fraction(physical.get("fps"))
        if grid_rate <= 0 and submitted["previous_av_nodes"]:
            grid_rate = fraction(submitted["previous_av_nodes"][0]["inputs"].get("force_rate"))
        if grid_rate <= 0 and mapping["mode"] == "FRAME_INDEX_CFR":
            grid_rate = fraction(media.get("fps"))
        positions = [p for n in submitted["anchor_nodes"] for p in n["positions"]]
        for i, anchor in enumerate(anchors):
            sem = finite(anchor.get("time_seconds"))
            p = anchor.get("frame_position")
            effective = float((int(p) - 1) / grid_rate) if isinstance(p, int) and p > 0 and grid_rate > 0 else finite((anchor.get("reachability") or {}).get("effective_frame_local_time"))
            kf = (anchor.get("source") or {}).get("keyframe_index")
            src = [source("TASK_SNAPSHOT", task.id, f"execution_contract/temporal_anchor_manifest/anchors/{i}", anchor, revision)]
            if sem is not None:
                semantic_by_kf[kf] = event(f"semantic:anchor:{anchor.get('anchor_id', i)}", "SEMANTIC_KF", f"Semantic KF{kf}", sem,
                                             payload={"keyframe_index": kf, "owned": True, "anchor_semantic": True}, src=src)
            native = mapping["origin_frame_index0"] + p - 1 if mapping["time_domain"] == "CLIP_LOCAL" and isinstance(p, int) else None
            payload = {**anchor, "effective_time": effective, "semantic_time": sem, "local_frame_index0": p - 1 if isinstance(p, int) else None,
                       "submitted_position_verified": p in positions, "native_frame_index0": native,
                       "native_pts": media["pts"][native] if native is not None and 0 <= native < media.get("frame_count", 0) else None}
            if positions and p not in positions:
                conflicts.append({"code": "ANCHOR_POSITION_DIFFERS_FROM_SUBMITTED", "anchor": p, "submitted_positions": positions})
            event(f"physical:{anchor.get('anchor_id', i)}", "PHYSICAL_ANCHOR", f"Physical Anchor · position1 {p}", effective,
                  payload=payload, src=src, native_frame_index0=native)
        owned = current_clip.get("visual_state_indexes", [])
        carry = current_clip.get("carry_in_state_index")
        for i, kf in enumerate(plan.get("keyframes", [])):
            t = finite(kf.get("time_seconds"))
            local = round(t - start, 9) if t is not None and start is not None else None
            if kf.get("index") != carry and (local is None or local < 0 or duration is None or local > duration):
                continue
            src = source("CURRENT_PLAN", task.shot_id, f"video_director_plan/keyframes/{i}", kf, plan.get("clip_plan_revision"))
            existing = semantic_by_kf.get(kf.get("index"))
            if existing and local == existing["start"]:
                existing["source_refs"].append(src)
                existing["payload"]["current_state"] = kf
                continue
            if existing:
                conflicts.append({"code": "SEMANTIC_KF_DIFFERS_FROM_CURRENT_PLAN", "kf": kf.get("index"), "snapshot": existing["start"], "current": local})
            event(f"semantic:current:{kf.get('index', i)}", "SEMANTIC_KF", f"KF{kf.get('index')}" + (" · carry-in" if kf.get("index") == carry else " · CURRENT_PLAN"),
                  local, payload={**kf, "owned": kf.get("index") in owned, "carry_in": kf.get("index") == carry}, src=[src])
        for i, transition in enumerate(plan.get("transitions", [])):
            a, b = finite(transition.get("start_time")), finite(transition.get("end_time"))
            if a is None or b is None or start is None or end is None or b <= start or a >= end:
                continue
            event(f"transition:{i}", "TRANSITION", f"KF{transition.get('from_keyframe_index')}→KF{transition.get('to_keyframe_index')}",
                  max(0, a - start), min(end, b) - start,
                  {**transition, "original_shot_range": [a, b], "clip_intersection": [max(start, a), min(end, b)]},
                  [source("CURRENT_PLAN", task.shot_id, f"video_director_plan/transitions/{i}", transition, plan.get("clip_plan_revision"))])
        for name, kind in [("existing_body_binding", "LIFECYCLE"), ("initial_body_binding", "LIFECYCLE"), ("motion_ownership", "MOTION")]:
            if name in sections:
                event(f"rule:{name}", kind, name, 0 if duration is not None else None, duration,
                      {"text": sections[name]["text"], "message": "范围内的原文要求；精确入场/退场或运动时刻未知"},
                      [sections[name]["source"]], timing="CLIP_SCOPE")
        detailed = sections.get("detailed_description")
        if detailed:
            ranges = list(re.finditer(r"Clip-local\s+(\d+(?:\.\d+)?)\s*[–−-]\s*(\d+(?:\.\d+)?)\s+seconds", detailed["text"]))
            if ranges:
                for i, match in enumerate(ranges):
                    finish = ranges[i + 1].start() if i + 1 < len(ranges) else len(detailed["text"])
                    event(f"camera:prompt:{i}", "CAMERA", "Camera / visual direction · 范围原文", float(match[1]), float(match[2]),
                          {"text": detailed["text"][match.start():finish], "message": "显式文本范围，不推断微事件时间"}, [detailed["source"]])
            else:
                event("camera:prompt:untimed", "CAMERA", "Camera / visual direction · 时间未知", payload={"text": detailed["text"]}, src=[detailed["source"]])
        artifact_identity = {"task_id": task.id, "comfyui_prompt_id": task.comfyui_prompt_id, "workflow_sha256": digest(graph),
                             "prompt_sha256": digest(final_prompt), "task_prompt_sha256": digest(task_prompt),
                             "execution_snapshot_sha256": digest({"contract": contract, "physical_output": physical,
                                                                   "dialogue_assignment": metadata.get("dialogue_assignment"),
                                                                   "video_reference_manifest": metadata.get("video_reference_manifest")}),
                             "video_sha256": media.get("video_sha256"), "result_url": task.result_url}
        artifact = {**artifact_identity, "artifact_id": digest(artifact_identity), "identity_status": "STABLE" if media.get("video_sha256") else "PENDING",
                    "artifact_kind": contract.get("artifact_kind", physical.get("physical_output_role", "UNKNOWN")), "capability": capability}
        availability = [{"name": "Execution contract", "status": "EXECUTION_SNAPSHOT" if contract else "SOURCE_NOT_AVAILABLE"},
                        {"name": "Historical full Director snapshot", "status": "EXECUTION_SNAPSHOT" if metadata.get("director_plan_snapshot") else "SOURCE_NOT_AVAILABLE"},
                        {"name": "Current Director plan", "status": "CURRENT_PLAN" if plan else "SOURCE_NOT_AVAILABLE"},
                        {"name": "Final Prompt", "status": "FINAL_PROMPT" if final_prompt else "SOURCE_NOT_AVAILABLE"},
                        {"name": "Submitted prompt connection", "status": submitted["prompt_status"]},
                        {"name": "Physical output snapshot", "status": "EXECUTION_SNAPSHOT" if physical else "SOURCE_NOT_AVAILABLE"},
                        {"name": "Native media", "status": media["status"]}, {"name": "Time mapping", "status": mapping["status"]}]
        if warnings:
            availability.append({"name": "Source parsing", "status": "DEGRADED", "reasons": warnings})
        historical = [{"step": c.get("step"), "created_at": c.get("created_at"),
                       "final_prompt_matches": bool(final_prompt) and c.get("final_prompt") == final_prompt,
                       "relation_to_execution": "PARTIAL" if final_prompt and c.get("final_prompt") == final_prompt else "UNLINKED"}
                      for c in plan.get("ai_calls", []) if isinstance(c, dict)]
        projection = {"projection_version": 1, "clip_ref": ref, "artifact": artifact,
                      "execution": {"task_id": task.id, "status": task.status, "seed": task.seed,
                                    "comfyui_prompt_id": task.comfyui_prompt_id, "shot_start": start, "shot_end": end,
                                    "planned_duration": duration, "timing_source_status": timing_source,
                                    "requested_duration": metadata.get("requested_duration", duration),
                                    "requested_latent_frame_count": submitted["requested_latent_frame_count"],
                                    "previous_av": contract.get("previous_clip"),
                                    "created_at": str(task.created_at) if task.created_at else None,
                                    "completed_at": str(task.completed_at) if task.completed_at else None},
                      "plan_context": {"status": "CURRENT_PLAN" if plan else "SOURCE_NOT_AVAILABLE", "revision": plan.get("clip_plan_revision"),
                                       "plan_hash": digest(plan), "carry_in_state_index": carry, "owned_visual_state_indexes": owned,
                                       "source": source("CURRENT_PLAN", task.shot_id, "video_director_plan", plan, plan.get("clip_plan_revision"))},
                      "media": media, "time_mapping": mapping, "events": events, "authority_items": authority,
                      "availability": availability, "conflicts": conflicts, "warnings": warnings,
                      "references": {"ordinary": (metadata.get("video_reference_manifest") or {}).get("references", []),
                                     "temporal_anchors": anchors, "previous_av": contract.get("previous_clip"),
                                     "source": source("TASK_SNAPSHOT", task.id, "metadata/video_reference_manifest", metadata.get("video_reference_manifest"), revision)},
                      "submitted": {k: v for k, v in submitted.items() if k != "prompt"},
                      "historical_auxiliary": historical}
        evidence = {"task_prompt": task_prompt, "submitted_prompt": submitted["prompt"], "final_prompt": final_prompt,
                    "workflow": graph, "metadata": metadata, "current_plan": plan,
                    "source_refs": [source("TASK_SNAPSHOT", task.id, "metadata_json", metadata, revision),
                                    source("SUBMITTED_WORKFLOW", task.id, "workflow_json", graph, revision),
                                    source("FINAL_PROMPT_TEXT", task.id, "final_prompt", final_prompt)]}
        return projection, evidence

    def artifacts(self, shot_id, clip_index, revision=None):
        with self.db.no_autoflush:
            shot = self.db.get(Shot, shot_id)
            if shot is None:
                raise InspectorError("SHOT_NOT_FOUND", "片段所在镜头不存在", 404)
            tasks = self.db.query(Task).filter(Task.shot_id == shot_id, Task.type == "shot_video").order_by(Task.created_at.desc()).all()
            items = []
            for task in tasks:
                warnings = []
                meta = decode(task.metadata_json, {}, warnings, "metadata_json")
                clip = (meta.get("execution_contract") or {}).get("clip") or meta
                if clip.get("clip_index") != clip_index or (revision is not None and clip.get("clip_plan_revision") != revision):
                    continue
                if task.result_url:
                    # Content/probe resolution is lazy when the user selects a task.
                    items.append({"task_id": task.id, "status": task.status, "result_url": task.result_url,
                                  "clip_plan_revision": clip.get("clip_plan_revision"), "created_at": str(task.created_at),
                                  "artifact_id": None, "identity_status": "PENDING"})
        return {"artifacts": items, "analyses": self.store.list_analyses(shot_id, clip_index, revision)}
