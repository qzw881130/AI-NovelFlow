"""Inspector tests use an isolated API and forbid writes after fixture setup."""
import copy
import json
import subprocess
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import clip_execution_inspector as api
from app.core.database import get_db
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.services.clip_execution_inspector_service import ClipExecutionInspectorService, expected_at_time, submitted_evidence
from app.services.inspector_frame_service import InspectorFrameService, build_mapping, resolve_sample, sampling_manifest
from app.services.inspector_store import InspectorError, InspectorStore


def measured(count=529, rate=24, pts=None):
    exact = pts or [str(Fraction(i, rate)) for i in range(count)]
    return {"status": "EXPLICIT", "frame_count": len(exact), "fps": str(rate), "fps_numerator": rate,
            "fps_denominator": 1, "is_cfr": pts is None, "pts_monotonic": True, "pts_exact": exact,
            "pts": [float(Fraction(p)) for p in exact], "end_pts_exact": str(Fraction(exact[-1]) + Fraction(1, rate)),
            "video_duration": float(Fraction(exact[-1]) + Fraction(1, rate)), "video_sha256": "a" * 64,
            "width": 960, "height": 544, "stream_time_base": "1/12288", "warnings": []}


@pytest.fixture
def sample(tmp_path):
    evidence = json.loads((Path(__file__).parents[2] / "docs/clip-execution-inspector/audit-evidence.json").read_text())["sample"]
    metadata = {"execution_scope": "CLIP", "execution_contract": evidence["execution_contract"],
                "physical_output": evidence["physical_output"], "dialogue_assignment": evidence["dialogue_assignment"]}
    prompt = "subject_definitions:\n<Subject 1> is 皇帝, human.\n<Subject 3> is 侍从2, human.\n<Subject 5> is 宫廷总管, human.\n\ndialogue_timeline:\n"
    for d in metadata["dialogue_assignment"]:
        prompt += f"{d['dialogue_id']}:\n  speaker: {evidence['subject_bindings'][d['speaker']]}\n  start_time: {d['clip_start_time']}s\n  end_time: {d['clip_end_time']}s\n  exact_dialogue: {d['text']}\n"
    prompt += "detailed_description:\nClip-local 0.0–5.4 seconds, camera orbits.\nClip-local 5.4–11.1 seconds, holds.\nexisting_body_binding:\nSubject5 exactly one body enters during KF2→KF3; exact entry time unknown.\nmotion_ownership:\n<Subject 5> TRANSLATIONAL_MOTION in KF2→KF3.\nreference_authority:\nPrevious AV owns carry-in.\n"
    graph = {"120": {"class_type": "CR Prompt Text", "inputs": {"prompt": prompt}},
             "55": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"prompt": ["120", 0], "length": ["126", 1]}},
             "126": {"class_type": "ComfyMathExpression", "inputs": {"expression": "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17", "values.a": ["125", 0]}},
             "125": {"class_type": "PrimitiveFloat", "inputs": {"value": 11.1}},
             "65": {"class_type": "MiniMaxH3StreamLiveExtensionAVToVHS", "inputs": {"save_output": True, "latent": ["55", 0]}},
             "116": evidence["submitted_anchor_node"], "66": evidence["submitted_previous_av_node"]}
    plan = {"clip_plan_revision": 1, "clip_plan": [{"clip_index": 2, "visual_state_indexes": [3], "carry_in_state_index": 2,
                "prompt_text": prompt, "start_time": 12, "end_time": 23.1}],
            "keyframes": [{"index": 2, "time_seconds": 11.9}, {"index": 3, "time_seconds": 17.4}],
            "transitions": [{"from_keyframe_index": 2, "to_keyframe_index": 3, "start_time": 11.9, "end_time": 17.4, "transition_description": "camera"}],
            "ai_calls": [{"step": "11", "final_prompt": "old prompt", "parsed_result": {"reference_binding": "wrong old authority"}}]}
    task = SimpleNamespace(id="task", type="shot_video", shot_id="shot", chapter_id="chapter", novel_id="novel",
                           metadata_json=json.dumps(metadata), workflow_json=json.dumps(graph), prompt_text=prompt,
                           result_url="/api/files/c2.mp4", comfyui_prompt_id="prompt", seed=1, status="completed", created_at=None, completed_at=None)
    shot = SimpleNamespace(id="shot", index=2, chapter_id="chapter", video_director_plan=json.dumps(plan))
    store = InspectorStore(tmp_path)
    frames = InspectorFrameService(store)
    frames.probe = Mock(return_value=measured())
    return task, shot, metadata, plan, graph, store, frames


def project(sample):
    task, shot, _, _, _, store, frames = sample
    return ClipExecutionInspectorService(store=store, frames=frames).project(task, shot)


def test_c2_domains_dialogues_authority_and_exact_expected(sample):
    p, raw = project(sample)
    assert p["execution"]["requested_latent_frame_count"] == 277
    assert p["media"]["frame_count"] == 529
    assert p["time_mapping"]["replacement_frames"] == 274
    assert p["time_mapping"]["origin_frame_index0"] == 255
    ds = [e for e in p["events"] if e["type"] == "DIALOGUE"]
    assert [(d["start"], d["end"], d["payload"]["subject_token"]) for d in ds] == [(.1, 5.35, "<Subject 3>"), (5.55, 8.3, "<Subject 5>"), (8.5, 11, "<Subject 1>")]
    states = [e for e in p["events"] if e["type"] == "SEMANTIC_KF" and e["payload"].get("keyframe_index") == 3]
    assert states[0]["start"] == 5.4
    anchor = next(e for e in p["events"] if e["type"] == "PHYSICAL_ANCHOR")
    assert anchor["start"] == pytest.approx(205 / 24)
    assert anchor["payload"]["native_frame_index0"] == 460
    assert all(a["status"] == "ABSENT" for a in p["authority_items"][-4:])
    assert "exactly one body" in next(a for a in p["authority_items"] if a["title"] == "Body lifecycle")["sections"][0]["text"]
    assert p["historical_auxiliary"][0]["relation_to_execution"] == "UNLINKED"
    frame = resolve_sample(p["media"], p["time_mapping"], 5.55)
    assert not expected_at_time(p, frame["sample_clip_time"])["dialogues"]
    assert expected_at_time(p, 5.55)["dialogues"][0]["payload"]["dialogue_id"] == "D5"
    assert expected_at_time(p, 4.5)["dialogues"][0]["payload"]["speaker"] == "侍从2"
    assert raw["submitted_prompt"]["node_id"] == "120"


def test_historical_attention_absent_does_not_borrow_current_plan(sample):
    task, shot, _, plan, _, _, _ = sample
    names = ["visual_attention_owner", "foreground_speaker", "background_entrant", "background_motion_subject"]
    current_attention = {name: "CURRENT_ONLY_ATTENTION_MUST_NOT_BECOME_HISTORY" for name in names}
    plan.update(current_attention)
    plan["visual_attention"] = {"version": 1, "time_base": "SHOT_SECONDS",
                                "character_catalog": [{"character_id": "current-subject", "character_name": "CURRENT_ONLY_ATTENTION_MUST_NOT_BECOME_HISTORY"}],
                                "windows": [{"start_time_seconds": 12, "end_time_seconds": 23.1,
                                             "primary_subjects": ["current-subject"], "background_motion_subjects": []}]}
    plan["clip_plan"][0].update(current_attention)
    plan["clip_plan"][0]["prompt_text"] += "\n" + "\n".join(f"{name}:\nCURRENT_ONLY_ATTENTION_MUST_NOT_BECOME_HISTORY" for name in names)
    shot.video_director_plan = json.dumps(plan)
    projection, raw = project(sample)
    assert projection["plan_context"]["status"] == "CURRENT_PLAN"
    assert "CURRENT_ONLY_ATTENTION_MUST_NOT_BECOME_HISTORY" not in raw["final_prompt"]
    for item in projection["authority_items"][-4:]:
        assert item["status"] == "ABSENT"
        assert item["presence"] == "ABSENT_EXPLICIT_FIELD"
        assert item["sections"] == []
    assert task.status == "completed"


@pytest.mark.parametrize("t,local,n,pts", [(3.542, 85, 340, 340 / 24), (4.5, 108, 363, 15.125),
                                        (5.4, 130, 385, 385 / 24), (5.55, 133, 388, 388 / 24), (205 / 24, 205, 460, 460 / 24)])
def test_native_mapping_rational(sample, t, local, n, pts):
    p, _ = project(sample)
    result = resolve_sample(p["media"], p["time_mapping"], t)
    assert (result["local_frame_index0"], result["native_frame_index0"]) == (local, n)
    assert result["native_pts"] == pytest.approx(pts)


@pytest.mark.parametrize("interval", [.5, 1, 2])
def test_sampling_union_neighbors_dedup_boundaries(sample, interval):
    p, _ = project(sample)
    manifest = sampling_manifest(p, {"uniform_interval_seconds": interval})
    samples = manifest["samples"]
    requested = [r["time"] for s in samples for r in s["requested_times"]]
    for t in (0, .1, 5.35, 5.4, 5.55, 8.3, 8.5, 205 / 24, 11, 11.1, 274 / 24):
        assert any(abs(r - t) < 1e-7 for r in requested)
    assert 5.8 in requested and 5.3 in requested
    assert len(set(s["native_frame_index0"] for s in samples)) == len(samples)
    assert manifest["deduplicated_count"] > 0
    assert samples[-1]["native_frame_index0"] == 528
    assert any(r["boundary_behavior"] == "LAST_VALID_FRAME" for r in samples[-1]["requested_times"])
    assert next(s for s in samples if s["native_frame_index0"] == 460)["h3_position1"] == 206
    out = sampling_manifest(p, {"requested_times": [12]})
    assert any(r["status"] == "OUT_OF_VIDEO" and r["time"] == 12 for r in out["unresolved"])


def test_generate_extend_and_missing_snapshot(sample):
    task, shot, meta, _, _, _, _ = sample
    for capability in ("GENERATE", "EXTEND", "TEMPORAL_EXTEND"):
        value = copy.deepcopy(meta)
        value["execution_contract"]["capability"] = capability
        if capability == "GENERATE":
            value["execution_contract"]["artifact_kind"] = "CLIP_ONLY"
            value["execution_contract"].pop("previous_clip")
            value["execution_contract"].pop("temporal_anchor_manifest")
            value.pop("physical_output")
        elif capability == "EXTEND":
            value["execution_contract"].pop("temporal_anchor_manifest")
        task.metadata_json = json.dumps(value)
        p, _ = project(sample)
        assert p["artifact"]["capability"] == capability
        assert p["time_mapping"]["origin_frame_index0"] == (0 if capability == "GENERATE" else 255)
        assert bool(p["execution"]["previous_av"]) == (capability != "GENERATE")
        assert any(e["type"] == "PHYSICAL_ANCHOR" for e in p["events"]) == (capability == "TEMPORAL_EXTEND")
    task.metadata_json = "{}"
    task.prompt_text = None
    task.workflow_json = None
    p, _ = project(sample)
    assert p["time_mapping"]["time_domain"] == "NATIVE"
    assert all(a["status"] == "SOURCE_NOT_AVAILABLE" for a in p["authority_items"])
    assert task.status == "completed"


def test_conflicts_media_missing_invalid_json_and_artifact_identity(sample):
    task, shot, meta, plan, _, _, frames = sample
    original, _ = project(sample)
    task.comfyui_prompt_id = "retry"
    retry, _ = project(sample)
    assert retry["artifact"]["artifact_id"] != original["artifact"]["artifact_id"]
    task.prompt_text = "changed column"
    plan["clip_plan_revision"] = 2
    shot.video_director_plan = json.dumps(plan)
    frames.probe.side_effect = InspectorError("MEDIA_UNAVAILABLE", "deleted", 404)
    p, _ = project(sample)
    assert p["media"]["status"] == "SOURCE_NOT_AVAILABLE"
    assert p["time_mapping"]["status"] == "DEGRADED"
    assert p["artifact"]["identity_status"] == "PENDING"
    assert {c["code"] for c in p["conflicts"]} >= {"TASK_PROMPT_DIFFERS_FROM_SUBMITTED", "CURRENT_PLAN_DIFFERS_FROM_EXECUTION"}
    task.metadata_json = "broken-json"
    p, _ = project(sample)
    assert "INVALID_JSON:Task.metadata_json" in p["warnings"]
    assert task.status == "completed"


def test_unknown_graph_does_not_guess_prompt(sample):
    *_, graph, _, _ = sample
    graph["120"]["class_type"] = "UnknownTextConcat"
    assert submitted_evidence(graph, {"output_node_id": "65"})["prompt"] is None


def test_vfr_non24_and_half_open_end():
    media = measured(count=50, rate=25)
    mapping = build_mapping(media, {"capability": "GENERATE", "artifact_kind": "CLIP_ONLY"}, {}, 2)
    assert resolve_sample(media, mapping, 1)["native_frame_index0"] == 25
    assert resolve_sample(media, mapping, 2)["status"] == "OUT_OF_VIDEO"
    assert resolve_sample(media, mapping, 2, boundary=True)["native_frame_index0"] == 49
    vfr = measured(rate=25, pts=["1/5", "6/25", "3/10", "2/5"])
    mapping = build_mapping(vfr, {"capability": "GENERATE", "artifact_kind": "CLIP_ONLY"}, {}, .3)
    assert mapping["mode"] == "PTS_VFR"
    assert resolve_sample(vfr, mapping, .075)["native_frame_index0"] == 2  # .275 nearer .3 than .24
    assert resolve_sample(vfr, mapping, .02)["native_frame_index0"] == 1  # tie -> later PTS
    vfr["start_pts"] = .2
    native = build_mapping(vfr, {}, {}, None)
    assert native["axis_duration"] == pytest.approx(.44)
    assert resolve_sample(vfr, native, .1)["status"] == "OUT_OF_VIDEO"
    assert resolve_sample(vfr, native, .4)["native_frame_index0"] == 3


def test_sampling_identity_stable_across_refresh_and_boundary_neighbors(sample):
    p, _ = project(sample)
    again, _ = project(sample)
    one = sampling_manifest(p, {"uniform_interval_seconds": 2})
    two = sampling_manifest(again, {"uniform_interval_seconds": 2})
    assert one["manifest_id"] == two["manifest_id"]
    reasons = [r["reason"] for s in one["samples"] for r in s["requested_times"]]
    assert "CLIP_START:NEIGHBOR:+0.25" in reasons
    assert "PLANNED_CLIP_END:NEIGHBOR:-0.25" in reasons
    assert "WINDOW_END:NEIGHBOR:-0.25" in reasons


def test_cached_image_survives_deleted_media_cache_miss_does_not_switch_source(tmp_path):
    from app.services.inspector_store import atomic_json
    store = InspectorStore(tmp_path)
    frames = InspectorFrameService(store)
    sha = "b" * 64
    cache = store.story_root("novel") / "cache" / sha
    atomic_json(cache / "locator.json", {"result_url": "/api/files/deleted.mp4"})
    atomic_json(cache / "probe-v1.json", measured(2))
    image = cache / "frames/frame-v1/thumb/0.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"already cached")
    assert frames.extract(sha, [0])[0] == image
    assert frames.extractions == 0
    with pytest.raises(InspectorError) as exc:
        frames.extract(sha, [1])
    assert exc.value.code == "MEDIA_UNAVAILABLE"


def test_observation_write_failure_preserves_file_and_revision(sample, monkeypatch):
    import app.services.inspector_store as module
    p, raw = project(sample)
    store = sample[-2]
    analysis = store.create(p, raw)
    before = (store.analysis_dir(analysis["analysis_id"]) / "observations.json").read_bytes()
    monkeypatch.setattr(module, "atomic_json", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        store.mutate_observation(analysis["analysis_id"], {"time_seconds": 3.542, "categories": ["OTHER"], "note": "draft"}, revision=1)
    assert (store.analysis_dir(analysis["analysis_id"]) / "observations.json").read_bytes() == before
    assert store.read(analysis["analysis_id"])["revision"] == 1


def test_generic_probe_cached_and_path_boundary(tmp_path, monkeypatch):
    store = InspectorStore(tmp_path)
    frames = InspectorFrameService(store)
    path = tmp_path / "existing.mp4"
    path.write_bytes(b"probe fixture only; no media generated")
    raw = {"streams": [{"codec_type": "video", "avg_frame_rate": "25/1", "r_frame_rate": "25/1", "time_base": "1/1000", "duration": ".12", "width": 10, "height": 10}],
           "frames": [{"media_type": "video", "best_effort_timestamp": t, "pkt_duration": 40} for t in (0, 40, 80)],
           "format": {"duration": ".14"}}
    run = Mock(return_value=SimpleNamespace(stdout=json.dumps(raw)))
    monkeypatch.setattr(subprocess, "run", run)
    first = frames.probe("/api/files/existing.mp4", "novel", "task")
    second = frames.probe("/api/files/existing.mp4", "novel", "task")
    assert first == second and run.call_count == 1
    assert first["fps"] == "25" and "NON_24_FPS" in first["warnings"]
    for url in ("/api/files/../../secret", "/api/files/%2Fetc/passwd", "https://example.com/video.mp4"):
        with pytest.raises(InspectorError):
            frames.resolve_path(url)
    external = tmp_path.parent / "external.mp4"
    external.write_bytes(b"external")
    (tmp_path / "symlink.mp4").symlink_to(external)
    with pytest.raises(InspectorError) as exc:
        frames.resolve_path("/api/files/symlink.mp4")
    assert exc.value.code == "UNSAFE_PATH"


def test_durable_crud_multiple_analyses_conflict_and_server_frame_evidence(sample):
    p, raw = project(sample)
    store = sample[-2]
    one, two = store.create(p, raw), store.create(p, raw)
    assert one["analysis_id"] != two["analysis_id"]
    note = {"time_seconds": 3.542, "categories": ["PORTRAIT_CLOSEUP"], "note": "test observation", "frame_evidence": {"native_frame_index0": 1}}
    saved = store.mutate_observation(one["analysis_id"], note, revision=1)
    obs = saved["observations"][0]
    assert obs["categories"] == ["PORTRAIT_DRIFT"]
    assert obs["frame_evidence"]["native_frame_index0"] == 340
    reopened = InspectorStore(store.media_root).read(one["analysis_id"])
    assert reopened["observations"] == saved["observations"]
    with pytest.raises(InspectorError) as exc:
        store.mutate_observation(one["analysis_id"], note, revision=1)
    assert exc.value.code == "REVISION_CONFLICT"
    updated = store.mutate_observation(one["analysis_id"], {"note": "edited", "time_seconds": 4.5}, obs["observation_id"], 2)
    assert updated["observations"][0]["frame_evidence"]["native_frame_index0"] == 363
    deleted = store.mutate_observation(one["analysis_id"], observation_id=obs["observation_id"], revision=3, delete=True)
    assert deleted["observations"] == []
    assert InspectorStore(store.media_root).read(two["analysis_id"])["observations"] == []


def test_isolated_api_pagination_no_business_writes_or_reconcile(sample, db_session, monkeypatch):
    task, shot, _, _, _, store, frames = sample
    db_session.add_all([Novel(id="novel", title="Inspector"), Chapter(id="chapter", novel_id="novel", number=1, title="Inspector"),
                        Shot(id="shot", chapter_id="chapter", index=2, video_director_plan=shot.video_director_plan),
                        Task(**vars(task), name="C2")])
    db_session.commit()
    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(api, "frames", frames)
    frames.save_sampling = Mock()
    app = FastAPI()
    app.include_router(api.router, prefix="/api/clip-execution-inspector")
    app.dependency_overrides[get_db] = lambda: db_session
    monkeypatch.setattr(db_session, "commit", Mock(side_effect=AssertionError("Business commit forbidden")))
    monkeypatch.setattr(db_session, "flush", Mock(side_effect=AssertionError("Business flush forbidden")))
    from app.services.task_service import TaskService
    monkeypatch.setattr(TaskService, "reconcile_active_tasks", Mock(side_effect=AssertionError("Reconcile forbidden")))
    with TestClient(app) as client:
        base = "/api/clip-execution-inspector"
        p = client.get(base + "/executions/task").json()["data"]
        assert client.get(base + "/shots/shot/clips/2/artifacts").json()["data"]["artifacts"][0]["task_id"] == "task"
        assert client.get(base + "/executions/task?artifact_id=wrong").status_code == 409
        page = client.post(base + "/executions/task/sampling?limit=2", json={"artifact_id": p["artifact"]["artifact_id"]}).json()["data"]
        assert len(page["samples"]) == 2 and page["next_offset"] == 2
        analysis = client.post(base + "/analyses", json={"task_id": "task", "artifact_id": p["artifact"]["artifact_id"]}).json()["data"]
        url = base + "/analyses/" + analysis["analysis_id"]
        saved = client.post(url + "/observations", headers={"If-Match": '"1"'}, json={"time_seconds": 3.542, "categories": ["OTHER"], "note": "API"})
        assert saved.status_code == 200 and saved.headers["etag"] == '"2"'
        assert client.get(url).json()["data"]["observations"][0]["time_seconds"] == 3.542
        obs_id = saved.json()["data"]["observations"][0]["observation_id"]
        assert client.patch(url + "/observations/" + obs_id, headers={"If-Match": '"2"'}, json={"note": "updated"}).status_code == 200
        assert client.delete(url + "/observations/" + obs_id, headers={"If-Match": '"3"'}).json()["data"]["observations"] == []
        assert client.get(url + "/../..%2Fsecret").status_code in (400, 404)
    db_session.expire_all()
    assert db_session.get(Task, "task").status == "completed"
    assert db_session.get(Shot, "shot").video_director_plan == shot.video_director_plan
