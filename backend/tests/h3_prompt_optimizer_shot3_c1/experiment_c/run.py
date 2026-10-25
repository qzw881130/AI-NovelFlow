"""Shot 3 / C1 Experiment C. Add six local speech locks; no LLM or product writes."""
import argparse
import copy
import difflib
import hashlib
import json
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

C = Path(__file__).resolve().parent
ROOT = C.parent
PROJECT = ROOT.parents[2]
OUTPUT = ROOT / "output/experiment_c_speaker_binding.mp4"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(name, data):
    path = C / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def endpoint():
    return read(ROOT / "logs/comfyui_system_stats_status.json")["url"].removesuffix("/system_stats")


def events(prompt):
    pattern = r"(?m)^(D\d+):\nspeaker: (<Subject \d+>)\nstart_time: ([\d.]+)s\nend_time: ([\d.]+)s\nexact_dialogue: ([^\n]+)\n"
    return [{"id": m[0], "subject": m[1], "start": float(m[2]), "end": float(m[3]), "text": m[4]}
            for m in re.findall(pattern, prompt)]


def section(prompt, heading, next_heading):
    start = prompt.index(heading + "\n")
    end = prompt.index(next_heading + "\n", start) if next_heading else len(prompt)
    return prompt[start:end]


def prepare():
    assert not (C / "prompt.txt").exists() and not OUTPUT.exists(), "Preserve an existing C run"
    a_bytes = (ROOT / "optimizer/optimized_h3_prompt.txt").read_bytes()
    a = a_bytes.decode("utf-8")
    graph = read(ROOT / "comfyui/experiment_a_workflow.json")
    a_execution = read(ROOT / "comfyui/experiment_a_execution.json")
    a_history = read(ROOT / "comfyui/experiment_a_history.json")[a_execution["prompt_id"]]
    assert graph == a_history["prompt"][2]
    assert graph["138"]["inputs"]["value"] == a
    canonical = read(ROOT / "baseline/canonical_dialogue.json")
    expected = [{"id": e["dialogue_id"], "subject": e["subject"], "start": e["start_time"], "end": e["end_time"], "text": e["text"]} for e in canonical]
    assert events(a) == expected and len(expected) == 6
    assert [e["subject"] for e in expected] == ["<Subject 3>", "<Subject 4>", "<Subject 1>", "<Subject 3>", "<Subject 1>", "<Subject 4>"]
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob("*") if p.is_file() and not p.is_relative_to(C)}
    save("isolation_before.json", {"existing_experiment_files": frozen})
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=PROJECT).decode().split("\0")
    source_hashes = {p: sha(PROJECT / p) for p in tracked if p and (PROJECT / p).is_file() and not (PROJECT / p).is_relative_to(ROOT)}
    save("workspace_before.json", source_hashes)
    additions, chunks, cursor, added_so_far = [], [], 0, 0
    for e in expected:
        marker = "exact_dialogue: " + e["text"] + "\n"
        assert a.count(marker) == 1
        insertion = a.index(marker) + len(marker)
        others = [f"<Subject {i}>" for i in range(1, 5) if f"<Subject {i}>" != e["subject"]]
        other_text = f"{others[0]}, {others[1]}, and {others[2]}"
        block = (f"\nDuring {e['id']}, ONLY {e['subject']} may speak this dialogue.\n"
                 f"ONLY {e['subject']} may produce human vocalization.\n"
                 f"ONLY {e['subject']} may perform speech-synchronized mouth and lip movement.\n\n"
                 f"{other_text} remain non-vocal during {e['id']}\n"
                 f"and must not perform speech-like mouth or lip articulation.\n\n"
                 f"The voice, dialogue, and lip synchronization of {e['id']} belong exclusively\n"
                 f"to {e['subject']}.\n\n")
        additions.append({"event": e["id"], "speaker": e["subject"], "non_speakers": others,
                          "change_type": "PER_DIALOGUE_SPEAKER_OWNERSHIP_REINFORCEMENT",
                          "a_character_offset": insertion, "a_byte_offset": len(a[:insertion].encode("utf-8")),
                          "c_character_offset": insertion + added_so_far, "inserted_text": block})
        chunks.extend([a[cursor:insertion], block])
        cursor, added_so_far = insertion, added_so_far + len(block)
    chunks.append(a[cursor:])
    prompt = "".join(chunks)
    restored = prompt
    for item in additions:
        assert restored.count(item["inserted_text"]) == 1
        restored = restored.replace(item["inserted_text"], "", 1)
    assert restored.encode("utf-8") == a_bytes
    (C / "control_a_prompt.txt").write_bytes(a_bytes)
    (C / "prompt.txt").write_bytes(prompt.encode("utf-8"))
    save("control_a_workflow.json", graph)
    save("canonical_dialogue.json", canonical)
    unified = "".join(difflib.unified_diff(a.splitlines(True), prompt.splitlines(True), fromfile="Experiment A", tofile="Experiment C"))
    (C / "prompt_diff.patch").write_text(unified)
    diff = {"source": str(ROOT / "optimizer/optimized_h3_prompt.txt"), "source_a_prompt_id": a_execution["prompt_id"],
            "a_sha256": sha(C / "control_a_prompt.txt"), "c_sha256": sha(C / "prompt.txt"),
            "a_characters": len(a), "c_characters": len(prompt), "added_characters": added_so_far,
            "change_count": 6, "semantic_change_types": ["PER_DIALOGUE_SPEAKER_OWNERSHIP_REINFORCEMENT"],
            "changes": additions, "non_speaker_content_modified": False, "only_insertions": True,
            "removing_all_six_insertions_restores_a_byte_for_byte": True,
            "proof": "C is constructed by six event-local insertions into the exact submitted A bytes; removing precisely those six inserts restores all A bytes."}
    save("prompt_diff.json", diff)
    pairs = [("REFERENCE AUTHORITY", "SUBJECT IDENTITY LOCKS"),
             ("SUBJECT IDENTITY LOCKS", "CAMERA AND CHRONOLOGICAL VISUAL EXECUTION"),
             ("CAMERA AND CHRONOLOGICAL VISUAL EXECUTION", "DIALOGUE AND LIP SYNCHRONIZATION"),
             ("SOUNDSCAPE", "OUTPUT CONTINUITY"), ("OUTPUT CONTINUITY", None)]
    sections = {head: section(a, head, nxt) == section(prompt, head, nxt) for head, nxt in pairs}
    c_events = events(prompt)
    checks = {
        "dialogue_event_count_unchanged": len(c_events) == len(expected),
        "dialogue_speaker_unchanged": [e["subject"] for e in c_events] == [e["subject"] for e in expected],
        "exact_dialogue_unchanged": [e["text"] for e in c_events] == [e["text"] for e in expected],
        "dialogue_timing_unchanged": [(e["start"], e["end"]) for e in c_events] == [(e["start"], e["end"]) for e in expected],
        "dialogue_order_unchanged": [e["id"] for e in c_events] == [e["id"] for e in expected],
        "subject_set_unchanged": set(re.findall(r"<Subject \d+>", a)) == set(re.findall(r"<Subject \d+>", prompt)),
        "picture_set_unchanged": set(re.findall(r"<Picture \d+>", a)) == set(re.findall(r"<Picture \d+>", prompt)),
        "picture_binding_unchanged": sections["REFERENCE AUTHORITY"],
        "kf1_kf2_kf3_timing_unchanged": sections["CAMERA AND CHRONOLOGICAL VISUAL EXECUTION"],
        "temporal_anchor_order_unchanged": sections["CAMERA AND CHRONOLOGICAL VISUAL EXECUTION"],
        "duration_unchanged": a.splitlines()[0] == prompt.splitlines()[0],
        "reference_authority_unchanged": sections["REFERENCE AUTHORITY"],
        "identity_lock_unchanged": sections["SUBJECT IDENTITY LOCKS"],
        "camera_instructions_unchanged": sections["CAMERA AND CHRONOLOGICAL VISUAL EXECUTION"],
        "chronological_visual_execution_unchanged": sections["CAMERA AND CHRONOLOGICAL VISUAL EXECUTION"],
        "action_timing_unchanged": sections["CAMERA AND CHRONOLOGICAL VISUAL EXECUTION"],
        "soundscape_unchanged": sections["SOUNDSCAPE"],
        "unrelated_negative_constraints_unchanged": sections["OUTPUT CONTINUITY"],
        "global_dialogue_rules_preserved": a[a.index("DIALOGUE AND LIP SYNCHRONIZATION"):a.index("D1:\n")] == prompt[prompt.index("DIALOGUE AND LIP SYNCHRONIZATION"):prompt.index("D1:\n")],
        "only_six_local_speaker_reinforcement_insertions": restored.encode("utf-8") == a_bytes,
        "subject_2_has_no_dialogue": all(e["subject"] != "<Subject 2>" for e in c_events),
    }
    save("authority_check.json", {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
                                 "sections_unchanged": sections, "canonical_events": expected, "c_events": c_events,
                                 "proof": diff["proof"], "all_checks_pass": all(checks.values())})
    assert all(checks.values()), "Do not queue a prompt containing other changes"
    print(json.dumps({"authority": "PASS", "changes": 6, "only_change": diff["semantic_change_types"],
                      "a_characters": len(a), "c_characters": len(prompt), "restores_a_exactly": True}, ensure_ascii=False))


def submit():
    assert read(C / "authority_check.json")["all_checks_pass"]
    assert not (C / "comfyui/submission_started.json").exists(), "Do not blindly resubmit a queued or ambiguous request"
    assert sha(ROOT / "optimizer/optimized_h3_prompt.txt") == read(C / "prompt_diff.json")["a_sha256"]
    assert sha(C / "prompt.txt") == read(C / "prompt_diff.json")["c_sha256"]
    a = read(C / "control_a_workflow.json")
    graph = copy.deepcopy(a)
    graph["138"]["inputs"]["value"] = (C / "prompt.txt").read_bytes().decode("utf-8")
    graph["169"]["inputs"]["filename_prefix"] = "video/h3_prompt_optimizer_shot3_c1/experiment_c_speaker_binding"
    masked = copy.deepcopy(graph)
    for node, field in [("138", "value"), ("169", "filename_prefix")]:
        masked[node]["inputs"][field] = a[node]["inputs"][field]
    assert masked == a, "Only Prompt and isolated save prefix may change"
    assert a["129"]["inputs"]["noise_seed"] == 3720777255
    assert a["132"]["inputs"]["value"] == 13.1 and a["130"]["inputs"]["fps"] == 24
    assert a["124"]["inputs"]["steps"] == 6 and a["124"]["inputs"]["denoise"] == 1
    save("comfyui/workflow.json", graph)
    save("comfyui/workflow_diff.json", {
        "all_other_graph_bytes_semantically_identical": masked == a,
        "changes": [{"node": "138", "field": "value", "purpose": "six local speaker locks"},
                    {"node": "169", "field": "filename_prefix", "purpose": "isolated C output location"}],
        "topology_unchanged": True, "models_lora_sigma_shift_unchanged": True,
        "reference_order_binding_wiring_unchanged": True, "all_other_parameters_unchanged": True,
        "seed": 3720777255, "duration": 13.1, "resolution": [864, 480], "fps": 24,
        "expected_frames": 328, "sampling": "euler/simple/steps6/denoise1", "endpoint": endpoint(),
    })
    state = {"status": "PREFLIGHT", "success": False, "submission_attempts": 0,
             "endpoint": endpoint(), "source_a_prompt_id": read(ROOT / "comfyui/experiment_a_execution.json")["prompt_id"],
             "seed": 3720777255, "requested_duration": 13.1, "resolution": [864, 480], "fps": 24,
             "expected_frames": 328, "llm_calls": 0}
    try:
        with httpx.Client(timeout=60, trust_env=False) as client:
            for name in ["system_stats", "queue"]:
                resp = client.get(endpoint() + "/" + name)
                (C / "comfyui" / f"preflight_{name}_response.txt").write_text(resp.text)
                resp.raise_for_status()
            ref_checks = []
            for asset in read(ROOT / "baseline/input_assets.json"):
                assert sha(asset["original_path"]) == asset["original_sha256"], "Local reference changed"
                resp = client.get(endpoint() + "/view", params={"filename": asset["uploaded_filename"], "type": "input"})
                resp.raise_for_status()
                remote_sha = hashlib.sha256(resp.content).hexdigest()
                ref_checks.append({"picture": asset["picture"], "source": asset["original_path"],
                                   "remote_sha256": remote_sha, "a_original_sha256": asset["original_sha256"],
                                   "matches_a": remote_sha == asset["original_sha256"]})
            save("comfyui/reference_byte_check.json", ref_checks)
            assert all(check["matches_a"] for check in ref_checks), "Never overwrite a mismatching reference"
            request = {"prompt": graph, "client_id": str(uuid.uuid4()),
                       "extra_data": {"experiment": "h3_prompt_optimizer_shot3_c1_experiment_c_speaker_binding", "source_a_prompt_id": state["source_a_prompt_id"]}}
            save("comfyui/request.json", request)
            state.update(status="SUBMITTING", submission_attempts=1, submitted_at_utc=datetime.now(timezone.utc).isoformat())
            save("comfyui/submission_started.json", state)
            started = time.monotonic()
            resp = client.post(endpoint() + "/prompt", json=request)
            (C / "comfyui/submission_raw_response.txt").write_text(resp.text)
            state.update(http_status=resp.status_code, submission_duration_seconds=time.monotonic() - started)
            resp.raise_for_status()
            data = resp.json()
            assert data.get("prompt_id") and not data.get("node_errors"), data
            state.update(status="QUEUED", prompt_id=data["prompt_id"], submission_success=True)
    except Exception as error:
        state.update(status="FAILED_OR_AMBIGUOUS" if state["submission_attempts"] else "PREFLIGHT_FAILED",
                     error={"type": type(error).__name__, "message": str(error)})
    save("comfyui/execution.json", state)
    print(json.dumps(state, ensure_ascii=False))


def probe(path):
    return json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))


def poll():
    state = read(C / "comfyui/execution.json")
    assert state.get("prompt_id"), state
    if state["status"] == "COMPLETED":
        print(json.dumps(state, ensure_ascii=False))
        return
    with httpx.Client(timeout=30, trust_env=False) as client:
        resp = client.get(endpoint() + "/history/" + state["prompt_id"])
        resp.raise_for_status()
        (C / "comfyui/history_raw_response.txt").write_text(resp.text)
        history = resp.json()
        record = history.get(state["prompt_id"])
        save("comfyui/history.json", history)
        if record:
            assert record["prompt"][2] == read(C / "comfyui/workflow.json"), "Remote history graph differs"
            status = record.get("status", {})
            state["comfyui_status"] = status
            if status.get("status_str") == "success" and status.get("completed"):
                out = record["outputs"]["169"]["images"][0]
                response = client.get(endpoint() + "/view", params={k: out[k] for k in ["filename", "subfolder", "type"]}, timeout=120)
                response.raise_for_status()
                with OUTPUT.open("xb") as f:
                    f.write(response.content)
                media = probe(OUTPUT)
                save("media_probe.json", media)
                video = next(s for s in media["streams"] if s["codec_type"] == "video")
                assert [video["width"], video["height"]] == [864, 480]
                assert video["avg_frame_rate"] == "24/1" and int(video["nb_frames"]) == 328
                times = {kind: value["timestamp"] for kind, value in status.get("messages", []) if "timestamp" in value}
                state.update(status="COMPLETED", success=True, output_path=str(OUTPUT), output_sha256=sha(OUTPUT),
                             remote_output=out, physical_duration=float(video["duration"]), frames=int(video["nb_frames"]),
                             generation_time_seconds=(times["execution_success"] - times["execution_start"]) / 1000)
            elif status.get("status_str") == "error":
                state.update(status="EXECUTION_FAILED", success=False)
        else:
            queue = client.get(endpoint() + "/queue").json()
            save("comfyui/queue.json", queue)
            state["status"] = "RUNNING_OR_QUEUED" if state["prompt_id"] in json.dumps(queue) else "MISSING_QUEUE_AND_HISTORY"
    save("comfyui/execution.json", state)
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["prepare", "submit", "poll"])
    globals()[parser.parse_args().step]()
