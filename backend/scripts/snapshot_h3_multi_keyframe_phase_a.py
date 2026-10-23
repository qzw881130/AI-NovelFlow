"""Read saved tasks through SQLite mode=ro; export isolated Phase A fixtures.

No service/client construction, generation, migration or database writes.
The output directory must not exist. Current Canonical is explicitly identified
and checked against the saved Builder's owned states and Clip boundaries.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3


SAMPLES = {
    "shot12_c1_generate": "5c919770-a7ef-4e82-a1d9-d5d13ddd42b8",
    "shot3_c6_extend": "b28d0eea-2748-405c-bea3-723ca78804ae",
    "shot5_c2_temporal_extend": "45bc29fa-8f3b-4d55-8a49-fa68fde4d880",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def snapshot(connection, task_id):
    task = connection.execute("select * from tasks where id=?", (task_id,)).fetchone()
    meta = json.loads(task["metadata_json"])
    record = meta["h3_prompt_optimizer"]
    if task["status"] != "completed" or record["status"] != "OPTIMIZED" or not record["authority_check"]["passed"]:
        raise ValueError("Saved task is not a successful verified execution")
    shot = connection.execute("select * from shots where id=?", (task["shot_id"],)).fetchone()
    plan = json.loads(shot["video_director_plan"])
    clip = next(c for c in plan["clip_plan"] if c["clip_index"] == meta["clip_index"])
    matches = []
    for row in connection.execute(
        "select id,user_prompt,response from llm_logs where chapter_id=? and task_type='h3_multi_keyframe_prompt'",
        (shot["chapter_id"],),
    ):
        try:
            text = row["user_prompt"]
            payload = json.loads(text[text.index("{"):])
        except (ValueError, TypeError):
            continue
        if (payload.get("shot", {}).get("id") == shot["id"]
                and payload.get("clip", {}).get("clip_index") == meta["clip_index"]
                and row["response"] and row["response"][:200] in record["raw_prompt"]):
            matches.append((row["id"], payload))
    if len(matches) != 1:
        raise ValueError("Saved Builder input cannot be uniquely identified")
    log_id, payload = matches[0]
    for key in ("start_time", "end_time", "visual_state_indexes", "carry_in_state_index", "capability"):
        if clip.get(key) != payload["clip"].get(key):
            raise ValueError("Current Clip differs from saved Builder: " + key)
    states = {s["index"]: s for s in plan["keyframes"]}
    for state in payload["visual_controls"]:
        current = states[state["index"]]
        if (state["description"] != current["description"]
                or abs(current["time_seconds"] - clip["start_time"] - state["time_seconds"]) > 1e-6):
            raise ValueError("Current Canonical differs from saved Builder")
    # Recover original physical slots from saved projection, not names or reports.
    selected = record["execution_reference_manifest"]
    original = []
    for item in sorted(selected["references"] + selected["excluded_references"], key=lambda r: r["source_slot"]):
        ref = deepcopy(item)
        slot = ref["source_slot"]
        for key in ("source_slot", "source_picture", "logical_id", "picture", "anchor_id",
                    "decision", "reason", "included_in_execution", "binding"):
            ref.pop(key, None)
        ref["slot"] = slot
        original.append(ref)
    workflow = connection.execute("select * from workflows where id=?", (task["workflow_id"],)).fetchone()
    runtime = record["runtime_input"]
    frames = runtime["previous_video_context"].get("frames") or []
    canonical = {k: deepcopy(plan[k]) for k in ("keyframes", "transitions", "dialogue_timeline_source")}
    clip_keys = ("clip_id", "clip_index", "start_time", "end_time", "planned_duration", "capability",
                 "visual_state_indexes", "carry_in_state_index", "continuity_to_previous", "duration_planning")
    canonical["clip_plan"] = [{k: deepcopy(clip[k]) for k in clip_keys if k in clip}]
    # Keep only proof/decision data, never request_info (may contain credentials).
    frozen = {k: deepcopy(record[k]) for k in ("status", "raw_prompt", "runtime_input", "output", "authority_check", "llm_log_id")}
    return {
        "source": {"task_id": task_id, "task_status": task["status"], "shot_id": shot["id"],
                   "builder_log_id": log_id, "optimizer_log_id": record["llm_log_id"],
                   "canonical_source": "Read-only current Canonical, owned states and Clip matched to saved Builder; full carry-in is from this snapshot",
                   "canonical_sha256": digest(canonical), "builder_input_sha256": digest(payload),
                   "frozen_record_sha256": digest(frozen)},
        "builder_input": payload, "canonical_plan": canonical, "frozen_record": frozen,
        "reference_manifest": {"references": original},
        "workflow": {"id": workflow["id"], "type": workflow["type"],
                     "workflow_json": task["workflow_json"], "node_mapping": workflow["node_mapping"]},
        "previous_video_path": frames[0]["source_video_path"] if frames else None,
        "user_camera_requirements": {"status": "UNKNOWN", "requirements": []},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        snapshots = {name: snapshot(connection, task_id) for name, task_id in SAMPLES.items()}
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in snapshots.items():
        (args.output / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2))
        print(name, value["source"]["task_id"])
