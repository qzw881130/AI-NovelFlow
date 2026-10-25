"""Isolated real-data H3 experiment. Never imports product services or writes its DB.

Run with backend/venv/bin/python -B; all artifacts live next to this script.
"""
import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
BACKEND = PROJECT / "backend"
SHOT_ID = "58fa07ca-9cbf-44ba-9aca-57beb79a395c"
TASK_ID = "9ccf4264-be19-4489-8c4c-8e8a470c6ad5"


def write_json(path, value):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def config():
    with sqlite3.connect(f"file:{BACKEND / 'novelflow.db'}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        cfg = dict(db.execute("select * from system_configs limit 1").fetchone())
    # Product initialization decrypts the stored key before passing it to a provider.
    # Load only this pure utility; importing services would write production logs.
    spec = importlib.util.spec_from_file_location("experiment_security", BACKEND / "app/core/security.py")
    security = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(security)
    plaintext = security.decrypt_value(cfg["llm_api_key"] or "")
    keys = [key.strip() for key in plaintext.split(",") if key.strip()]
    cfg["llm_api_key"] = keys[0] if keys else ""
    return cfg


def probe_video(path):
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)
    ]))


def source_file(url):
    assert url.startswith("/api/files/"), url
    return BACKEND / "user_story" / url.removeprefix("/api/files/")


def prepare():
    assert not (ROOT / "baseline/task_snapshot.json").exists(), "Snapshot already exists"
    for directory in ["baseline", "inputs", "vision_proxy", "optimizer", "comfyui", "output", "logs", "review"]:
        (ROOT / directory).mkdir(exist_ok=True)
    with sqlite3.connect(f"file:{BACKEND / 'novelflow.db'}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        task = dict(db.execute("select * from tasks where id=?", (TASK_ID,)).fetchone())
        shot = dict(db.execute("select * from shots where id=?", (SHOT_ID,)).fetchone())
    meta = json.loads(task["metadata_json"])
    plan = json.loads(shot["video_director_plan"])
    workflow = json.loads(task["workflow_json"])
    raw = task["prompt_text"]
    assert shot["index"] == 3 and meta["clip_index"] == 1
    assert workflow["138"]["inputs"]["value"] == raw == meta["prompt_text"]
    assert TASK_ID == plan["assembly_task_ids"][0]
    manifest = meta["video_reference_manifest"]
    subjects = [{"subject": int(n), "name": name} for n, name in re.findall(r"<Subject (\d+)> is ([^,]+),", raw)]
    name_to_subject = {s["name"]: s["subject"] for s in subjects}
    dialogue = copy.deepcopy(meta["dialogue_assignment"])
    for event in dialogue:
        event["subject"] = f"<Subject {name_to_subject[event['speaker']]}>"
    assets = []
    for ref in manifest["references"]:
        slot = ref["slot"]
        original = Path(ref["local_path"])
        assert original.is_file()
        node = ref["binding"]["workflow_node_id"]
        assert workflow[node]["inputs"]["image"] == ref["binding"]["uploaded_filename"]
        assert workflow["136"]["inputs"][f"ref_images.ref_image_{slot-1}"] == [node, 0]
        replica = ROOT / "inputs" / f"picture_{slot:02d}{original.suffix}"
        shutil.copy2(original, replica)
        proxy = ROOT / "vision_proxy" / f"picture_{slot:02d}.jpg"
        with Image.open(original) as im:
            original_size = list(im.size)
            im = im.convert("RGB")
            im.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            im.save(proxy, "JPEG", quality=85)
            proxy_size = list(im.size)
        assets.append({
            "picture": f"<Picture {slot}>", "slot": slot, "kind": ref["kind"],
            "source_name": ref.get("source_name"), "source_keyframe_index": ref.get("source_keyframe_index"),
            "source_time_seconds": ref.get("source_time_seconds"),
            "subject_binding": f"<Subject {name_to_subject[ref['source_name']]}>" if ref["kind"] == "CHARACTER_IDENTITY" else None,
            "original_path": str(original), "original_sha256": digest(original),
            "input_copy_path": str(replica), "input_copy_sha256": digest(replica),
            "original_size": original_size, "vision_proxy_path": str(proxy),
            "vision_proxy_sha256": digest(proxy), "vision_proxy_size": proxy_size,
            "workflow_node_id": node, "uploaded_filename": ref["binding"]["uploaded_filename"],
        })
    baseline_source = source_file(task["result_url"])
    baseline_copy = ROOT / "output/baseline.mp4"
    shutil.copy2(baseline_source, baseline_copy)
    probe = probe_video(baseline_copy)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    params = {"original_duration": meta["requested_duration"], "seed": task["seed"],
              "resolution": [video["width"], video["height"]], "fps": meta["actual_fps"],
              "actual_duration": meta["actual_duration"], "actual_frame_count": video.get("nb_frames"),
              "node_parameters": {n: v["inputs"] for n, v in workflow.items() if v["class_type"] not in ["LoadImage", "PrimitiveStringMultiline"]},
              "baseline_source_path": str(baseline_source), "baseline_copy_path": str(baseline_copy),
              "baseline_sha256": digest(baseline_copy), "prompt_node": "138", "prompt_input": "value",
              "duration_node": "132", "video_save_node": "169"}
    previous = {"previous_video_available": False, "previous_frames": [],
                "evidence": {"capability": meta["capability"], "previous_approved_video_url": meta.get("previous_approved_video_url"),
                             "previous_clip": meta["execution_contract"].get("previous_clip")}}
    assert meta["capability"] == "GENERATE" and not meta.get("previous_approved_video_url")
    write_json("baseline/task_snapshot.json", task)
    write_json("baseline/shot_snapshot.json", shot)
    write_json("baseline/reference_manifest.json", manifest)
    write_json("baseline/canonical_dialogue.json", dialogue)
    write_json("baseline/input_assets.json", assets)
    write_json("baseline/generation_params.json", params)
    write_json("baseline/submitted_workflow.json", workflow)
    write_json("baseline/media_probe.json", probe)
    write_json("baseline/previous_video.json", previous)
    write_json("baseline/subjects.json", subjects)
    write_json("baseline/clip_metadata.json", meta)
    write_json("baseline/workflow_info.json", {
        "id": task["workflow_id"], "name": task["workflow_name"], "source": "tasks.workflow_json (actual submitted graph)",
        "sha256": digest(ROOT / "baseline/submitted_workflow.json"),
        "baseline_prompt_id": task["comfyui_prompt_id"], "baseline_task_id": task["id"],
        "queue_api": "POST /prompt {prompt: frozen_graph, client_id: experiment_uuid}; GET /history/{prompt_id}; GET /view",
        "baseline_started_at_utc": task["started_at"], "baseline_completed_at_utc": task["completed_at"],
    })
    (ROOT / "baseline/raw_h3_prompt.txt").write_text(raw, encoding="utf-8")
    # Record content hashes without reading or displaying credentials.
    files = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=PROJECT).decode().split("\0")
    hashes = {p: digest(PROJECT / p) for p in files if p and (PROJECT / p).is_file() and not (PROJECT / p).is_relative_to(ROOT)}
    write_json("logs/workspace_before.json", hashes)
    (ROOT / "logs/git_status_before.txt").write_text(subprocess.check_output(["git", "status", "--short"], cwd=PROJECT).decode())
    print(json.dumps({"shot_id": SHOT_ID, "clip_id": meta["clip_id"], "task_id": TASK_ID, "pictures": len(assets),
                      "subjects": subjects, "dialogue_events": len(dialogue), "duration": params["original_duration"],
                      "seed": params["seed"], "resolution": params["resolution"], "baseline": str(baseline_copy)}, ensure_ascii=False))


def endpoints():
    cfg = config()
    with httpx.Client(timeout=20, trust_env=False) as client:
        for name, url in [("comfyui_system_stats", cfg["comfyui_host"].rstrip("/") + "/system_stats"),
                          ("comfyui_queue", cfg["comfyui_host"].rstrip("/") + "/queue"),
                          ("llm_models", cfg["llm_api_url"].rstrip("/") + "/models")]:
            try:
                headers = {"Authorization": f"Bearer {cfg['llm_api_key']}"} if name == "llm_models" else {}
                resp = client.get(url, headers=headers)
                (ROOT / "logs" / f"{name}_response.txt").write_text(resp.text)
                write_json(f"logs/{name}_status.json", {"url": url, "http_status": resp.status_code})
                print(name, resp.status_code, resp.text[:350])
            except Exception as exc:
                write_json(f"logs/{name}_status.json", {"url": url, "error": str(exc), "error_type": type(exc).__name__})
                print(name, type(exc).__name__, str(exc))


def optimizer():
    assert not (ROOT / "optimizer/optimizer_result.json").exists(), "Do not rerun a successful optimizer"
    attempts_root = ROOT / "optimizer/attempts"
    attempts_root.mkdir(exist_ok=True)
    artifact_names = ["optimizer_input.json", "optimizer_meta_prompt.txt", "llm_request.json", "optimizer_raw_response.txt", "optimizer_content.txt", "call_log.json"]
    # Preserve the first failed call made before the attempt archive was added.
    if (ROOT / "optimizer/optimizer_raw_response.txt").exists() and not list(attempts_root.iterdir()):
        first = attempts_root / "attempt_001"
        first.mkdir()
        for name in artifact_names:
            path = ROOT / "optimizer" / name
            if path.exists():
                shutil.copy2(path, first / name)
    attempt_number = len(list(attempts_root.iterdir())) + 1
    attempt_dir = attempts_root / f"attempt_{attempt_number:03d}"
    attempt_dir.mkdir()
    cfg = config()
    request_text = Path("/Users/qianzhiwei/.codex/attachments/5d2af5e9-f700-4329-ac46-470cb090c8fa/Pasted text.txt").read_text()
    start = request_text.index("You are an execution-prompt optimizer")
    end = request_text.index("The optimized H3 prompt must remain directly usable as the final H3 generation prompt.", start)
    meta_prompt = request_text[start:end] + "The optimized H3 prompt must remain directly usable as the final H3 generation prompt."
    (ROOT / "optimizer/optimizer_meta_prompt.txt").write_text(meta_prompt, encoding="utf-8")
    authority = {
        "DIRECTOR_VISUAL_ANCHOR/TEMPORAL": ["chronological visual state", "composition", "blocking", "pose", "costume", "visible prop state", "camera/framing"],
        "CHARACTER_IDENTITY": {"allowed": ["identity", "stable facial/body characteristics"],
                               "forbidden": ["costume", "pose", "blocking", "background", "prop ownership", "current position"]},
        "SCENE": ["environment identity", "environment appearance"],
        "PROP": ["prop identity", "prop appearance"],
        "PREVIOUS_VIDEO_FRAMES": {"allowed": ["incoming temporal state", "incoming pose", "blocking", "costume", "visible motion tendency judged from multiple frames"],
                                  "cannot_override": "later Temporal/Director Visual Anchors"},
    }
    result_schema = {
        "optimized_prompt": "directly usable final H3 generation prompt",
        "duration": {"original": 13.1, "recommended": 13.1, "change_recommended": False, "reason": "string"},
        "complexity": {"level": "low|medium|high", "subjects": 0, "active_speakers": 0, "dialogue_events": 0, "speaker_switches": 0, "visual_anchors": 0},
        "risks": [{"type": "string", "severity": "low|medium|high", "description": "string"}],
        "changes": [{"type": "string", "description": "string"}],
        "timing_recommendations": [{"type": "string", "description": "string", "advisory_only": True}],
    }
    input_data = {
        "shot_id": SHOT_ID, "clip_id": f"{SHOT_ID}:clip:1", "source_task_id": TASK_ID,
        "raw_h3_prompt": (ROOT / "baseline/raw_h3_prompt.txt").read_text(),
        "reference_manifest": read_json("baseline/reference_manifest.json"),
        "canonical_dialogue": read_json("baseline/canonical_dialogue.json"),
        "subjects": read_json("baseline/subjects.json"),
        "original_duration": read_json("baseline/generation_params.json")["original_duration"],
        "previous_video": read_json("baseline/previous_video.json"),
        "reference_authority": authority,
        "vision_proxies": read_json("baseline/input_assets.json"),
        "requested_output_schema": result_schema,
        "experiment_rules": [
            "Experiment A uses the optimized_prompt exactly as returned, original duration and original dialogue/anchor times.",
            "Inspect all nine attached images. Labels and order match the actual ComfyUI reference inputs exactly.",
            "For a lightweight experiment check, retain D1-D6 event labels with speaker, start_time, end_time, exact_dialogue fields; consolidate shared restrictions elsewhere.",
            "Retain explicit Picture-to-Subject identity mapping and timed KF1/KF2/KF3 Picture anchors, and identifiable Subject definitions.",
            "Return a JSON object conforming to requested_output_schema, without Markdown fences or commentary.",
        ],
    }
    write_json("optimizer/optimizer_input.json", input_data)
    content = [{"type": "text", "text": json.dumps(input_data, ensure_ascii=False)}]
    for asset in input_data["vision_proxies"]:
        label = f"{asset['picture']} / {asset['kind']}"
        if asset["subject_binding"]:
            label += f" / identity only for {asset['subject_binding']} ({asset['source_name']})"
        if asset["source_keyframe_index"]:
            label += f" / KF{asset['source_keyframe_index']} / {asset['source_time_seconds']}s"
        content.append({"type": "text", "text": label})
        encoded = base64.b64encode(Path(asset["vision_proxy_path"]).read_bytes()).decode()
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + encoded, "detail": "high"}})
    body = {"model": cfg["llm_model"], "messages": [{"role": "system", "content": meta_prompt}, {"role": "user", "content": content}],
            "temperature": float(cfg["llm_temperature"] or 0.7), "max_tokens": cfg["llm_max_tokens"],
            "stream": False, "response_format": {"type": "json_object"}}
    endpoint = cfg["llm_api_url"].rstrip("/") + "/chat/completions"
    write_json("optimizer/llm_request.json", {"endpoint": endpoint, "headers": {"Content-Type": "application/json", "Authorization": "Bearer [REDACTED]"}, "body": body})
    log = {"provider": cfg["llm_provider"], "model": cfg["llm_model"], "endpoint": endpoint,
           "reasoning_thinking": "not explicitly set; provider/gateway default (not observable before response)",
           "image_count": 9, "retries": attempt_number - 1, "attempt_number": attempt_number, "attempts": [],
           "prior_attempt_directories": [str(p) for p in sorted(attempts_root.iterdir()) if p != attempt_dir],
           "started_at_utc": datetime.now(timezone.utc).isoformat()}
    write_json("optimizer/call_log.json", log)
    started = time.monotonic()
    try:
        with httpx.Client(timeout=cfg["llm_timeout"], trust_env=False) as client:
            resp = client.post(endpoint, headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['llm_api_key']}",
                                                "HTTP-Referer": "https://opencode.ai/", "X-Title": "opencode", "User-Agent": "Anthropic/JS 0.73.0"}, json=body)
        (ROOT / "optimizer/optimizer_raw_response.txt").write_text(resp.text)
        log["request_duration_seconds"] = time.monotonic() - started
        log["attempts"].append({"attempt": attempt_number, "http_status": resp.status_code, "duration_seconds": log["request_duration_seconds"]})
        resp.raise_for_status()
        data = resp.json()
        log["token_usage"] = data.get("usage")
        log["response_model"] = data.get("model")
        choice = data["choices"][0]
        log["finish_reason"] = choice.get("finish_reason")
        message = choice["message"]
        text = message["content"]
        (ROOT / "optimizer/optimizer_content.txt").write_text(text)
        result = json.loads(text)
        assert set(result_schema) <= set(result), "Missing required result fields"
        assert isinstance(result["optimized_prompt"], str) and result["optimized_prompt"]
        assert result["duration"]["original"] == input_data["original_duration"]
        assert choice.get("finish_reason") != "length", "Truncated response"
        write_json("optimizer/optimizer_result.json", result)
        (ROOT / "optimizer/optimized_h3_prompt.txt").write_text(result["optimized_prompt"])
        log["success"] = True
        print(json.dumps({"success": True, "seconds": log["request_duration_seconds"], "usage": log["token_usage"],
                          "prompt_chars": len(result["optimized_prompt"]), "duration": result["duration"], "complexity": result["complexity"]}, ensure_ascii=False))
    except Exception as exc:
        log["success"] = False
        log["error"] = {"type": type(exc).__name__, "message": str(exc)}
        log["request_duration_seconds"] = time.monotonic() - started
        print(json.dumps(log["error"], ensure_ascii=False))
    finally:
        write_json("optimizer/call_log.json", log)
        for name in artifact_names:
            path = ROOT / "optimizer" / name
            if path.exists():
                shutil.copy2(path, attempt_dir / name)


def authority():
    prompt = (ROOT / "optimizer/optimized_h3_prompt.txt").read_text()
    raw = (ROOT / "baseline/raw_h3_prompt.txt").read_text()
    canonical = read_json("baseline/canonical_dialogue.json")
    event_pattern = re.compile(r"(?m)^\s*(D\d+)\s*:\s*\n\s*speaker\s*:\s*(<Subject \d+>)\s*\n\s*start_time\s*:\s*([\d.]+)s?\s*\n\s*end_time\s*:\s*([\d.]+)s?\s*\n\s*exact_dialogue\s*:\s*([^\n]+)")
    parsed = [{"id": m[0], "subject": m[1], "start_time": float(m[2]), "end_time": float(m[3]), "text": m[4].strip()} for m in event_pattern.findall(prompt)]
    expected = [{"id": e["dialogue_id"], "subject": e["subject"], "start_time": e["start_time"], "end_time": e["end_time"], "text": e["text"]} for e in canonical]
    expected_subjects = {str(s["subject"]) for s in read_json("baseline/subjects.json")}
    actual_subjects = set(re.findall(r"<Subject (\d+)>", prompt))
    expected_pictures = {str(a["slot"]) for a in read_json("baseline/input_assets.json")}
    actual_pictures = set(re.findall(r"<Picture (\d+)>", prompt))
    identity_evidence = []
    for asset in read_json("baseline/input_assets.json"):
        if not asset["subject_binding"]:
            continue
        lines = [line for line in prompt.splitlines() if asset["picture"] in line and asset["subject_binding"] in line]
        identity_evidence.append({"picture": asset["picture"], "subject": asset["subject_binding"], "matching_lines": lines})
    anchors = []
    for asset in read_json("baseline/input_assets.json"):
        if asset["kind"] != "DIRECTOR_VISUAL_ANCHOR":
            continue
        kf = f"KF{asset['source_keyframe_index']}"
        lines = [line for line in prompt.splitlines() if re.search(rf"\b{kf}\b", line) and asset["picture"] in line
                 and re.search(rf"(?<![\d.]){asset['source_time_seconds']:.2f}s|(?<![\d.]){asset['source_time_seconds']:g}s", line)]
        anchors.append({"keyframe": kf, "picture": asset["picture"], "time_seconds": asset["source_time_seconds"],
                        "matching_lines": lines, "first_matching_offset": prompt.find(lines[0]) if lines else None})
    offsets = [a["first_matching_offset"] for a in anchors]
    subjects_evidence = [{"subject": f"<Subject {s['subject']}>", "name": s["name"],
                          "matching_lines": [line for line in prompt.splitlines() if f"<Subject {s['subject']}>" in line and s["name"] in line]}
                         for s in read_json("baseline/subjects.json")]
    check = {
        "status": "COMPLETED",
        "dialogue_event_count_preserved": len(parsed) == len(expected) and [e["id"] for e in parsed] == [e["id"] for e in expected],
        "dialogue_speaker_preserved": [e["subject"] for e in parsed] == [e["subject"] for e in expected],
        "exact_dialogue_preserved": [e["text"] for e in parsed] == [e["text"] for e in expected],
        "canonical_dialogue_times_preserved": [(e["start_time"], e["end_time"]) for e in parsed] == [(e["start_time"], e["end_time"]) for e in expected],
        "picture_binding_preserved": all(e["matching_lines"] for e in identity_evidence),
        "subject_identity_preserved": actual_subjects == expected_subjects and all(s["matching_lines"] for s in subjects_evidence),
        "no_new_picture_references": actual_pictures <= expected_pictures,
        "picture_set_preserved": actual_pictures == expected_pictures,
        "temporal_anchor_order_preserved": all(a is not None for a in offsets) and offsets == sorted(x for x in offsets if x is not None),
        "evidence": {"expected_dialogue": expected, "parsed_dialogue": parsed, "identity_bindings": identity_evidence,
                     "subject_bindings": subjects_evidence, "anchors": anchors, "actual_subjects": sorted(actual_subjects), "actual_pictures": sorted(actual_pictures)},
        "limitation": "Lightweight literal/structural experiment check. Semantic contradiction review is separate; no output has been edited.",
        "raw_prompt_sha256": digest(ROOT / "baseline/raw_h3_prompt.txt"),
        "optimized_prompt_sha256": digest(ROOT / "optimizer/optimized_h3_prompt.txt"),
    }
    check["all_checks_pass"] = all(v for v in check.values() if isinstance(v, bool))
    write_json("authority_check.json", check)
    print(json.dumps({k: v for k, v in check.items() if k != "evidence"}, ensure_ascii=False))


def submit():
    import uuid
    assert not (ROOT / "comfyui/experiment_a_submission_response.txt").exists(), "Never blindly resubmit"
    assert read_json("authority_check.json")["all_checks_pass"], "Optimizer authority violation: preserve output and record failure"
    cfg = config()
    frozen = read_json("baseline/submitted_workflow.json")
    graph = copy.deepcopy(frozen)
    graph["138"]["inputs"]["value"] = (ROOT / "optimizer/optimized_h3_prompt.txt").read_text()
    # Output destination only; use a unique experiment subfolder, never a production asset.
    graph["169"]["inputs"]["filename_prefix"] = "video/h3_prompt_optimizer_shot3_c1/optimized_original_duration"
    expected_changes = [("138", "value"), ("169", "filename_prefix")]
    actual_changes = []
    for nid in graph:
        assert graph[nid]["class_type"] == frozen[nid]["class_type"]
        for key, value in graph[nid]["inputs"].items():
            if value != frozen[nid]["inputs"][key]:
                actual_changes.append((nid, key))
    assert sorted(actual_changes) == sorted(expected_changes)
    write_json("comfyui/experiment_a_workflow.json", graph)
    request = {"prompt": graph, "client_id": str(uuid.uuid4()), "extra_data": {"experiment": "h3_prompt_optimizer_shot3_c1", "source_task_id": TASK_ID}}
    write_json("comfyui/experiment_a_request.json", request)
    write_json("comfyui/frozen_graph_check.json", {
        "passed": True, "changes": [{"node_id": nid, "input": key, "purpose": "optimized prompt" if nid == "138" else "isolated output prefix"} for nid, key in actual_changes],
        "topology_unchanged": True, "models_unchanged": True, "seed_unchanged": True, "duration_unchanged": True,
        "references_unchanged": True, "sampling_unchanged": True, "resolution_unchanged": True,
    })
    started = time.monotonic()
    state = {"submitted_at_utc": datetime.now(timezone.utc).isoformat(), "success": False, "submission_attempts": 1,
             "original_duration": 13.1, "seed": frozen["129"]["inputs"]["noise_seed"], "resolution": [864, 480],
             "workflow_source": "baseline actual submitted graph", "reference_source": "original full-resolution ComfyUI input files"}
    try:
        with httpx.Client(timeout=60, trust_env=False) as client:
            # Verify existing remote input bytes match the frozen original references. No overwrite or reupload.
            checks = []
            for asset in read_json("baseline/input_assets.json"):
                response = client.get(cfg["comfyui_host"].rstrip("/") + "/view", params={"filename": asset["uploaded_filename"], "type": "input"})
                response.raise_for_status()
                remote_sha = hashlib.sha256(response.content).hexdigest()
                checks.append({"picture": asset["picture"], "remote_sha256": remote_sha, "local_original_sha256": asset["original_sha256"], "match": remote_sha == asset["original_sha256"]})
            write_json("comfyui/reference_byte_check.json", checks)
            assert all(c["match"] for c in checks), "Remote originals differ: do not overwrite existing assets"
            resp = client.post(cfg["comfyui_host"].rstrip("/") + "/prompt", json=request)
        (ROOT / "comfyui/experiment_a_submission_response.txt").write_text(resp.text)
        state["http_status"] = resp.status_code
        resp.raise_for_status()
        result = resp.json()
        assert result.get("prompt_id") and not result.get("node_errors"), result
        state["prompt_id"] = result["prompt_id"]
        state["submission_success"] = True
        state["status"] = "QUEUED"
    except Exception as exc:
        state["status"] = "FAILED"
        state["error"] = {"type": type(exc).__name__, "message": str(exc)}
    state["submission_duration_seconds"] = time.monotonic() - started
    write_json("comfyui/experiment_a_execution.json", state)
    print(json.dumps(state, ensure_ascii=False))


def poll():
    state = read_json("comfyui/experiment_a_execution.json")
    assert state.get("prompt_id"), state
    cfg = config()
    prompt_id = state["prompt_id"]
    with httpx.Client(timeout=30, trust_env=False) as client:
        resp = client.get(cfg["comfyui_host"].rstrip("/") + "/history/" + prompt_id)
        resp.raise_for_status()
        history = resp.json()
        write_json("comfyui/experiment_a_history.json", history)
        record = history.get(prompt_id)
        if record:
            status = record.get("status", {})
            state["comfyui_status"] = status
            if status.get("completed") and status.get("status_str") == "success":
                output = record["outputs"]["169"]["images"][0]
                response = client.get(cfg["comfyui_host"].rstrip("/") + "/view", params={k: output[k] for k in ["filename", "subfolder", "type"]}, timeout=120)
                response.raise_for_status()
                path = ROOT / "output/optimized_original_duration.mp4"
                assert not path.exists(), "Do not overwrite experiment output"
                path.write_bytes(response.content)
                state.update(success=True, status="COMPLETED", output_path=str(path), output_sha256=digest(path), remote_output=output)
                write_json("output/optimized_media_probe.json", probe_video(path))
                messages = status.get("messages", [])
                times = {kind: value["timestamp"] for kind, value in messages if "timestamp" in value}
                if "execution_start" in times and "execution_success" in times:
                    state["generation_time_seconds"] = (times["execution_success"] - times["execution_start"]) / 1000
            elif status.get("status_str") == "error":
                state.update(status="FAILED", success=False)
        else:
            queue = client.get(cfg["comfyui_host"].rstrip("/") + "/queue").json()
            write_json("comfyui/experiment_a_queue.json", queue)
            state["status"] = "RUNNING_OR_QUEUED" if prompt_id in json.dumps(queue) else "MISSING_HISTORY_AND_QUEUE"
    write_json("comfyui/experiment_a_execution.json", state)
    print(json.dumps(state, ensure_ascii=False))


def frames():
    events = read_json("baseline/canonical_dialogue.json")
    times = sorted(set([0.0, 4.95, 13.0, 13.1] + [round((e["start_time"] + e["end_time"]) / 2, 3) for e in events]))
    frame_manifest = []
    for name in ["baseline", "optimized_original_duration"]:
        path = ROOT / "output" / f"{name}.mp4"
        if not path.exists():
            continue
        folder = ROOT / "review" / name
        folder.mkdir(exist_ok=True)
        for t in times:
            dest = folder / f"frame_{t:06.3f}.jpg"
            subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-q:v", "2", "-y", str(dest)], check=True)
            frame_manifest.append({"video": name, "time_seconds": t, "path": str(dest)})
        contact = Image.new("RGB", (1728, 530 * ((len(times) + 1) // 2)), "#ececec")
        draw = ImageDraw.Draw(contact)
        for i, t in enumerate(times):
            im = Image.open(folder / f"frame_{t:06.3f}.jpg").convert("RGB")
            x, y = i % 2 * 864, i // 2 * 530
            contact.paste(im, (x, y + 40))
            event = next((e for e in events if e["start_time"] <= t < e["end_time"]), None)
            label = f"{name} {t:.3f}s" + (f" {event['dialogue_id']} {event['subject']}" if event else " anchor / silent")
            draw.text((x + 8, y + 10), label, fill="black")
        contact.save(ROOT / "review" / f"{name}_contact_sheet.jpg", quality=90)
        # Decode the full AV to check the real media, not just completion metadata.
        proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
        write_json(f"review/{name}_decode_check.json", {"exit_code": proc.returncode, "stderr": proc.stderr})
    write_json("review/frame_manifest.json", frame_manifest)
    print(json.dumps({"videos": sorted(set(f['video'] for f in frame_manifest)), "frames": len(frame_manifest)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["prepare", "endpoints", "optimizer", "authority", "submit", "poll", "frames"])
    step = parser.parse_args().step
    globals()[step]()
