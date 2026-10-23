"""Local acceptance against existing C2 media. No main-app startup or generation.

Run from backend: venv/bin/python tests/inspector_local_acceptance.py
"""
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))
from app.services.clip_execution_inspector_service import ClipExecutionInspectorService, expected_at_time
from app.services.inspector_frame_service import InspectorFrameService, resolve_sample, sampling_manifest
from app.services.inspector_store import InspectorStore, atomic_json, utc_now

TASK_ID = "8d4cb355-9540-42a8-b8a3-bc31a58eb9d1"


def main():
    root = Path(__file__).parents[2]
    db = sqlite3.connect((root / "backend/novelflow.db").as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    task = SimpleNamespace(**dict(db.execute("SELECT * FROM tasks WHERE id=?", (TASK_ID,)).fetchone()))
    shot = SimpleNamespace(**dict(db.execute("SELECT * FROM shots WHERE id=?", (task.shot_id,)).fetchone()))
    before = dict(vars(task)), dict(vars(shot))
    store = InspectorStore()
    frames = InspectorFrameService(store)
    service = ClipExecutionInspectorService(store=store, frames=frames)
    p, raw = service.project(task, shot)
    assert p["media"]["frame_count"] == 529
    assert p["time_mapping"]["replacement_frames"] == 274
    assert p["execution"]["requested_latent_frame_count"] == 277
    assert len(raw["final_prompt"]) == 15009
    assert raw["task_prompt"] == raw["submitted_prompt"]["text"]
    assert raw["submitted_prompt"]["node_id"] == "120"
    dialogues = [e for e in p["events"] if e["type"] == "DIALOGUE"]
    assert [(d["start"], d["end"], d["payload"]["subject_token"]) for d in dialogues] == [(.1, 5.35, "<Subject 3>"), (5.55, 8.3, "<Subject 5>"), (8.5, 11, "<Subject 1>")]
    semantic = next(e for e in p["events"] if e["type"] == "SEMANTIC_KF" and e["payload"].get("keyframe_index") == 3)
    anchor = next(e for e in p["events"] if e["type"] == "PHYSICAL_ANCHOR")
    assert semantic["start"] == 5.4 and anchor["payload"]["frame_position"] == 206
    assert anchor["payload"]["submitted_position_verified"]
    assert all(a["status"] == "ABSENT" for a in p["authority_items"][-4:])
    cases = [(3.542, 85, 340), (4.5, 108, 363), (5.4, 130, 385), (5.55, 133, 388), (205 / 24, 205, 460)]
    resolved = []
    for t, k, n in cases:
        sample = resolve_sample(p["media"], p["time_mapping"], t)
        assert (sample["local_frame_index0"], sample["native_frame_index0"]) == (k, n)
        assert abs(sample["native_pts"] - n / 24) < 1e-9
        resolved.append(sample)
    paths = frames.extract(p["artifact"]["video_sha256"], [n for _, _, n in cases], "detail")
    extracted = frames.extractions
    frames.extract(p["artifact"]["video_sha256"], list(paths), "detail")
    assert frames.extractions == extracted
    for sample in resolved:
        path = paths[sample["native_frame_index0"]]
        metadata = json.loads(path.with_suffix(".json").read_text())
        assert metadata["native_frame_index0"] == sample["native_frame_index0"]
        assert abs(metadata["decoded_native_pts"] - sample["native_pts"]) < .0001
        sample.update(frame_artifact_path=str(path), extraction_evidence=metadata)
    sampling = []
    for interval in (.5, 1, 2):
        manifest = sampling_manifest(p, {"uniform_interval_seconds": interval})
        frames.save_sampling(manifest)
        requested = [r["time"] for s in manifest["samples"] for r in s["requested_times"]]
        for t in (0, .1, 5.35, 5.4, 5.55, 8.3, 8.5, 205 / 24, 11, 11.1, 274 / 24):
            assert any(abs(value - t) < 1e-7 for value in requested)
        assert 5.3 in requested and 5.8 in requested
        assert len(set(s["native_frame_index0"] for s in manifest["samples"])) == manifest["unique_frame_count"]
        sampling.append({k: manifest[k] for k in ("manifest_id", "spec", "requested_count", "unique_frame_count", "deduplicated_count")})
    analysis = store.create(p, raw, "C2 local acceptance — temporary")
    identity = analysis["analysis_id"]
    directory = store.analysis_dir(identity)
    try:
        saved = store.mutate_observation(identity, {"time_seconds": 3.542, "categories": ["PORTRAIT_CLOSEUP"], "note": "test observation"}, revision=1)
        note = saved["observations"][0]
        assert note["frame_evidence"]["native_frame_index0"] == 340
        assert InspectorStore().read(identity)["observations"] == saved["observations"]
        updated = store.mutate_observation(identity, {"note": "test observation edited", "categories": ["OTHER"]}, note["observation_id"], 2)
        assert updated["observations"][0]["note"] == "test observation edited"
        deleted = store.mutate_observation(identity, observation_id=note["observation_id"], revision=3, delete=True)
        assert InspectorStore().read(identity)["observations"] == deleted["observations"] == []
    finally:
        # Only this run's explicitly temporary analysis is removed. Cache/evidence remain.
        shutil.rmtree(directory)
    after_task = dict(db.execute("SELECT * FROM tasks WHERE id=?", (TASK_ID,)).fetchone())
    after_shot = dict(db.execute("SELECT * FROM shots WHERE id=?", (task.shot_id,)).fetchone())
    assert before == (after_task, after_shot)
    evidence = {"at": utc_now(), "status": "PASS", "task_id": TASK_ID, "artifact": p["artifact"],
                "mapping": p["time_mapping"], "media": {k: v for k, v in p["media"].items() if k not in ("pts", "pts_exact")},
                "dialogues": dialogues, "semantic_kf3": semantic, "physical_anchor": anchor,
                "prompt_chars": len(raw["final_prompt"]), "task_equals_submitted_prompt": True, "submitted_prompt_node": "120",
                "requested_latent_frames": p["execution"]["requested_latent_frame_count"], "frames": resolved,
                "sampling": sampling, "cache_second_request_extra_extractions": 0,
                "new_detail_frame_extractions_this_run": extracted, "detail_frame_artifacts_verified": len(paths),
                "observation_crud": "CREATE/READ/RELOAD/UPDATE/DELETE PASS; temporary analysis removed",
                "temporary_analysis_id": identity, "business_rows_unchanged": True,
                "llm_calls": 0, "comfyui_calls": 0, "video_generations": 0, "ai_image_generations": 0,
                "expected_3_542": expected_at_time(p, 3.542), "expected_5_55": expected_at_time(p, 5.55)}
    atomic_json(root / "docs/clip-execution-inspector/c2-acceptance.json", evidence)
    atomic_json(root / "frontend/my-app/tests/fixtures/clip-execution-inspector-c2.json", p)
    print(json.dumps({"status": "PASS", "frame_paths": [str(path) for path in paths.values()], "new_extractions": extracted,
                      "sampling": sampling, "observation_crud": "PASS", "business_rows_unchanged": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
