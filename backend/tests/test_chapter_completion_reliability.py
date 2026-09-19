import json
import time
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.services import chapter_video_merge_service as completion


def _chapter(db):
    novel = Novel(title="Completion")
    db.add(novel)
    db.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title="One", content="source")
    db.add(chapter)
    db.flush()
    db.add(Shot(chapter_id=chapter.id, index=1, description="shot", video_status="completed",
                completion_disposition="NORMAL", video_director_plan_revision=1))
    db.commit()
    return novel, chapter


def test_completion_admission_is_idempotent_and_retry_is_explicit(db_session):
    novel, chapter = _chapter(db_session)
    first, created = completion.admit_completion(db_session, novel.id, chapter.id)
    replay, replay_created = completion.admit_completion(db_session, novel.id, chapter.id)
    assert created is True and replay_created is False and replay.id == first.id
    assert db_session.query(Task).filter_by(type="chapter_video", chapter_id=chapter.id).count() == 1

    first.status = "failed"
    first.error_message = "failed"
    db_session.commit()
    same, same_created = completion.admit_completion(db_session, novel.id, chapter.id)
    assert same.id == first.id and same_created is False and same.status == "failed"

    retry, retry_created = completion.admit_completion(
        db_session, novel.id, chapter.id, retry_failed_task_id=first.id)
    duplicate, duplicate_created = completion.admit_completion(
        db_session, novel.id, chapter.id, retry_failed_task_id=first.id)
    assert retry_created is True and duplicate_created is False and duplicate.id == retry.id
    assert retry.id != first.id and retry.parent_task_id == first.id
    assert db_session.query(Task).filter_by(type="chapter_video", chapter_id=chapter.id).count() == 2


def test_completion_request_identity_includes_precondition_but_not_published_pointer(db_session):
    novel, chapter = _chapter(db_session)
    first, _ = completion.admit_completion(db_session, novel.id, chapter.id, expected_manifest_hash="one")
    first.status = "failed"
    db_session.commit()
    second, _ = completion.admit_completion(db_session, novel.id, chapter.id, expected_manifest_hash="two")
    assert second.id != first.id
    second.status = "completed"
    chapter.final_video = "/api/files/final.mp4"
    chapter.final_video_task_id = second.id
    db_session.commit()
    replay, created = completion.admit_completion(db_session, novel.id, chapter.id, expected_manifest_hash="two")
    assert created is False and replay.id == second.id


def test_completion_api_replay_returns_one_task_and_one_enqueue(client, db_session):
    novel, chapter = _chapter(db_session)
    url = f"/api/novels/{novel.id}/chapters/{chapter.id}/completion"
    first = client.post(url)
    replay = client.post(url)
    assert first.status_code == replay.status_code == 200
    first_data, replay_data = first.json()["data"], replay.json()["data"]
    assert first_data["taskId"] == replay_data["taskId"]
    assert first_data["reused"] is False and replay_data["reused"] is True
    worker = client.app.state.pytest_worker_manager.workers["chapter_video"]
    assert len(worker.jobs) == 1
    assert db_session.query(Task).filter_by(type="chapter_video", chapter_id=chapter.id).count() == 1


def test_successful_readiness_does_not_repeat_per_shot_receipts(db_session, monkeypatch):
    novel, chapter = _chapter(db_session)
    shot = db_session.query(Shot).filter_by(chapter_id=chapter.id).one()
    manifest = {"version": completion.COMPLETION_VERSION, "novel_id": novel.id, "chapter_id": chapter.id,
                "entries": [{"shot_id": shot.id, "shot_index": 1, "kind": "NORMAL_VIDEO",
                             "ownership": {"start": 0, "end": len(chapter.content)}}],
                "counts": {"normal": 1, "degraded": 0, "total": 1}}
    monkeypatch.setattr(completion, "capture_completion", lambda *_args, **_kwargs: manifest)
    monkeypatch.setattr(completion, "video_receipt",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("duplicate receipt")))
    result = completion.completion_readiness(db_session, novel.id, chapter.id)
    assert result["ready"] is True and result["counts"]["total"] == 1


def _running_task(db, chapter, heartbeat):
    value = {"execution_purpose": "production", "delivery_mode": "CHAPTER_COMPLETION"}
    task = Task(type="chapter_video", status="running", novel_id=chapter.novel_id,
                chapter_id=chapter.id, name="complete", claim_token="claim", worker_id="worker",
                attempt=1, heartbeat_at=heartbeat, metadata_json=json.dumps(value))
    db.add(task)
    db.commit()
    return task


def test_stale_settler_cas_loses_to_new_heartbeat(db_session):
    _novel, chapter = _chapter(db_session)
    old = datetime.utcnow() - timedelta(minutes=10)
    task = _running_task(db_session, chapter, old)

    def renew(current):
        db_session.query(Task).filter_by(id=current.id).update({"heartbeat_at": datetime.utcnow()},
                                                               synchronize_session=False)
        db_session.commit()

    settled = completion._settle_stale_completion_rows(
        db_session, datetime.utcnow() - timedelta(minutes=3), before_update=renew)
    db_session.expire_all()
    assert settled == [] and db_session.get(Task, task.id).status == "running"


def test_true_stale_worker_is_settled_once(db_session):
    _novel, chapter = _chapter(db_session)
    task = _running_task(db_session, chapter, datetime.utcnow() - timedelta(minutes=10))
    cutoff = datetime.utcnow() - timedelta(minutes=3)
    assert completion._settle_stale_completion_rows(db_session, cutoff) == [task.id]
    db_session.commit()
    assert completion._settle_stale_completion_rows(db_session, cutoff) == []
    db_session.expire_all()
    saved = db_session.get(Task, task.id)
    assert saved.status == "failed"
    assert saved.error_message == "CHAPTER_COMPLETION_WORKER_INTERRUPTED_RETRY_EXPLICITLY"


def test_legacy_pending_completion_requires_explicit_new_proof(db_session):
    _novel, chapter = _chapter(db_session)
    legacy = Task(type="chapter_video", status="pending", novel_id=chapter.novel_id,
                  chapter_id=chapter.id, name="legacy", metadata_json=json.dumps({
                      "execution_purpose": "production", "delivery_mode": "CHAPTER_COMPLETION",
                      "completion_manifest": {"version": "chapter-completion-manifest-v1"},
                  }))
    db_session.add(legacy)
    db_session.commit()
    completion.resume_completion_tasks()
    db_session.expire_all()
    saved = db_session.get(Task, legacy.id)
    assert saved.status == "failed" and saved.error_message == "CHAPTER_COMPLETION_PROOF_REQUIRED"


def test_completion_lease_heartbeats_without_progress_events(db_session):
    _novel, chapter = _chapter(db_session)
    task = _running_task(db_session, chapter, datetime.utcnow() - timedelta(minutes=1))
    encoded = task.metadata_json
    previous_heartbeat = task.heartbeat_at
    lease = completion.CompletionLease(task.id, "claim", "worker", 1, encoded, interval=0.02)
    lease.start()
    time.sleep(0.09)
    lease.stop()
    db_session.expire_all()
    saved = db_session.get(Task, task.id)
    metrics = lease.metrics()
    assert saved.status == "running" and saved.heartbeat_at > previous_heartbeat
    assert metrics["count"] >= 3 and metrics["max_gap_ms"] < 100


def test_completion_lease_progress_never_regresses(db_session):
    _novel, chapter = _chapter(db_session)
    task = _running_task(db_session, chapter, datetime.utcnow())
    lease = completion.CompletionLease(task.id, "claim", "worker", 1, task.metadata_json, interval=1)
    lease.start()
    lease.checkpoint(10, "encode")
    lease.checkpoint(0, "source")
    lease.stop()
    db_session.expire_all()
    saved = db_session.get(Task, task.id)
    assert saved.progress == 10 and saved.current_step == "source"


def test_owner_change_after_subprocess_blocks_old_worker_updates(db_session):
    _novel, chapter = _chapter(db_session)
    task = _running_task(db_session, chapter, datetime.utcnow())
    lease = completion.CompletionLease(task.id, "claim", "worker", 1, task.metadata_json, interval=1)
    lease.start()
    db_session.query(Task).filter_by(id=task.id).update({"claim_token": "replacement", "worker_id": "new-worker"},
                                                       synchronize_session=False)
    db_session.commit()
    with pytest.raises(HTTPException, match="CHAPTER_COMPLETION_OWNER_CHANGED"):
        lease.checkpoint(99, "publish")
    lease.stop()
    db_session.expire_all()
    saved = db_session.get(Task, task.id)
    assert saved.status == "running" and saved.claim_token == "replacement" and saved.worker_id == "new-worker"


@pytest.mark.parametrize("bucket", [
    "source_pin", "source_dependency", "revision", "shot", "producer", "dependency", "media_stat", "subtitle",
])
def test_verified_entry_proof_reuses_only_an_identical_fence(bucket):
    fence = {
        "source_pin": {"seal": "source"}, "source_dependency": {"snapshot_hash": "source-dependencies"},
        "revision": {"revision": 1},
        "shot": {"video_task_id": "producer", "video_director_plan_revision": 3},
        "producer": {"id": "producer", "status": "completed"},
        "dependency": {"binding_hash": "binding", "artifacts": [{"seal": "artifact"}]},
        "media_stat": {"size": 10, "mtime_ns": 20},
        "subtitle": {"snapshot_hash": "subtitle", "envelope_hash": "envelope"},
    }
    body = {"version": completion.ENTRY_PROOF_VERSION, "kind": "NORMAL_VIDEO", "fence": fence}
    proof = {**deepcopy(body), "proof_hash": completion.digest(body)}
    assert completion._verify_entry_proof(proof, "NORMAL_VIDEO", deepcopy(fence)) is True

    changed = deepcopy(fence)
    changed[bucket] = {"changed": True}
    with pytest.raises(HTTPException, match="CHAPTER_COMPLETION_PROOF_STALE"):
        completion._verify_entry_proof(proof, "NORMAL_VIDEO", changed)


def test_persisted_v1_entry_proof_remains_verifiable():
    body = {"version": completion.LEGACY_ENTRY_PROOF_VERSION, "kind": "NORMAL_VIDEO",
            "fence": {"source_pin": {"seal": "legacy"}}}
    proof = {**body, "proof_hash": completion.digest(body)}
    assert completion._verify_entry_proof(proof, "NORMAL_VIDEO", deepcopy(body["fence"])) is True


def test_verified_entry_proof_tampering_is_rejected():
    body = {"version": completion.ENTRY_PROOF_VERSION, "kind": "NORMAL_VIDEO", "fence": {"value": 1}}
    proof = {**body, "proof_hash": completion.digest(body)}
    proof["fence"] = {"value": 2}
    with pytest.raises(HTTPException, match="CHAPTER_COMPLETION_PROOF_TAMPERED"):
        completion._verify_entry_proof(proof, "NORMAL_VIDEO", {"value": 2})


def test_durable_proof_json_normalizes_datetime_values():
    safe = completion._json_safe({"completed_at": datetime(2026, 9, 19, 12, 0, 0)})
    assert safe == {"completed_at": "2026-09-19 12:00:00"}
    assert completion.digest(safe)


def test_binding_dependency_fingerprint_ignores_process_and_connection_identity():
    from app.services.runtime_gate import _semantic_dependency_fingerprint
    snapshot = {"version": "video-binding-proof-v1", "processId": 1,
                "database": {"connectionId": 2, "dataVersion": 3}, "rsa": {"seal": "same"}}
    changed_runtime = deepcopy(snapshot)
    changed_runtime.update(processId=99, database={"connectionId": 100, "dataVersion": 200})
    assert _semantic_dependency_fingerprint(snapshot) == _semantic_dependency_fingerprint(changed_runtime)
    changed_runtime["rsa"] = {"seal": "changed"}
    assert _semantic_dependency_fingerprint(snapshot) != _semantic_dependency_fingerprint(changed_runtime)


def test_durable_binding_proof_strips_runtime_fields():
    proof = {"version": "video-binding-proof-v1", "validatedAt": 1.5, "processId": 123,
             "database": {"connectionId": 4}, "bindingFingerprint": "binding",
             "dependencyFingerprint": "dependency", "files": {"/api/files/a.png": {"size": 10}}}
    expected = {key: deepcopy(proof[key]) for key in (
        "version", "bindingFingerprint", "dependencyFingerprint", "files")}
    assert completion._durable_binding_validation_proof(proof) == expected
    changed_runtime = {**proof, "validatedAt": 9.5, "processId": 999,
                       "database": {"connectionId": 500}}
    assert completion._durable_binding_validation_proof(changed_runtime) == expected


def test_readiness_selects_latest_completion_not_newer_subset_merge(db_session):
    novel, chapter = _chapter(db_session)
    completion_task = Task(type="chapter_video", status="failed", novel_id=novel.id,
                           chapter_id=chapter.id, name="completion", created_at=datetime(2026, 9, 19, 12),
                           error_message="retry", metadata_json=json.dumps({"delivery_mode": "CHAPTER_COMPLETION"}))
    subset_task = Task(type="chapter_video", status="completed", novel_id=novel.id,
                       chapter_id=chapter.id, name="subset", created_at=datetime(2026, 9, 19, 13),
                       metadata_json=json.dumps({"mode": "shots_only"}))
    db_session.add_all([completion_task, subset_task])
    db_session.commit()
    result = completion.completion_readiness(db_session, novel.id, chapter.id)
    assert result["latestTask"] == {"taskId": completion_task.id, "status": "failed", "error": "retry"}


def test_normal_dependency_fence_hashes_full_validation_file_set(monkeypatch):
    from app.services import appearance_image_contract, runtime_gate
    state = {"source": {"size": 10, "mtime_ns": 1}, "created_at": datetime(2026, 9, 19)}
    head = SimpleNamespace(rsa_id="rsa", revision=3)
    rsa = SimpleNamespace(id="rsa", revision=3, status="READY", input_hash="input", result_hash="result",
                          seal="seal", task_id=None)

    def get(model, _key):
        return head if model.__name__ == "ShotAssetHead" else rsa

    monkeypatch.setattr(runtime_gate, "_live_asset_state", lambda _db, _rsa: {"upstream": deepcopy(state)})
    monkeypatch.setattr(appearance_image_contract, "image_source_signature",
                        lambda url: {"url": url, **deepcopy(state["source"])})
    monkeypatch.setattr(completion, "_row_hash", lambda row: completion.digest(vars(row)) if row else None)
    db = SimpleNamespace(get=get)
    shot = SimpleNamespace(id="shot", video_task_id="task")
    binding = {"rsa_id": "rsa", "images": [{"url": "/api/files/primary.png"}]}
    urls = ["/api/files/primary.png", "/api/files/upstream-character.png"]
    validation = {"bindingFingerprint": completion.digest(binding), "dependencyFingerprint": "validated",
                  "files": {url: {"url": url, **deepcopy(state["source"])} for url in urls}}
    first = completion._normal_dependency_fence(
        db, shot, binding, urls, validation)
    assert first["version"] == completion.DEPENDENCY_FENCE_VERSION
    assert first["file_dependencies"] == urls
    assert completion.digest(first)
    state["source"]["mtime_ns"] = 2
    with pytest.raises(HTTPException, match="CHAPTER_COMPLETION_BINDING_FILES_CHANGED"):
        completion._normal_dependency_fence(db, shot, binding, urls, validation)
    state["source"]["mtime_ns"] = 1
    rsa.result_hash = "changed"
    second = completion._normal_dependency_fence(db, shot, binding, urls, validation)
    assert second["snapshot_hash"] != first["snapshot_hash"]


def test_legacy_dependency_fence_remains_verifiable(monkeypatch):
    from app.services import runtime_gate
    monkeypatch.setattr(runtime_gate, "binding_dependency_snapshot", lambda *_args: {
        "processId": 99, "database": {"dataVersion": 1}, "files": {"source": {"size": 10}}})
    db = SimpleNamespace(get=lambda *_args: SimpleNamespace(id="task"))
    result = completion._legacy_normal_dependency_fence(
        db, SimpleNamespace(video_task_id="task"), {"images": []}, [])
    assert result["version"] == completion.LEGACY_DEPENDENCY_FENCE_VERSION
    assert result["snapshot_hash"]
