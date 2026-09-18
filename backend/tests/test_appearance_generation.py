"""Generation proof, publication fences and demand selection without external services."""
import asyncio
from copy import deepcopy
from io import BytesIO
import hashlib
import json
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, inspect
from PIL import Image
from app.models.workflow import Workflow
from app.models.task import Task
from app.models.llm_log import LLMLog
from app.models.shot import Shot
from app.models.appearance_generation import AppearanceGeneration as Generation, AppearanceImageRevision as Revision, AppearanceShotUsage as Usage
from app.models.appearance_timeline import CharacterAppearance as Appearance
from app.services import appearance_image_contract as contract, appearance_generation_service as generation
from app.services.appearance_timeline_service import AppearanceTimelineService
from app.services.appearance_usage import plan_used_missing, shot_fingerprint, verify_usage
from app.services.chapter_asset_parse_service import digest, source_hash
from app.repositories.task import TaskRepository
from app.core.database import get_db
from test_appearance_timeline import db_session, chapter, prepare, change, row_snapshot


@pytest.fixture
def setup(db_session, chapter, tmp_path, monkeypatch):
    actor = prepare(db_session, chapter, "刘备披甲。刘备换袍。", [change("刘备披甲"), change("刘备换袍", "官服", "appearance_2")])
    result = AppearanceTimelineService(db_session).build(chapter.novel_id, chapter.id)
    assert result["success"], result
    root = tmp_path / "media"; root.mkdir()
    monkeypatch.setattr(contract.file_storage, "base_dir", root)
    for module in (contract, generation):
        monkeypatch.setattr(module, "url_to_local_path", lambda url: str(root / url.removeprefix("/api/files/")) if url and url.startswith("/api/files/") else None)
        monkeypatch.setattr(module, "local_path_to_url", lambda path: "/api/files/" + str(Path(path).relative_to(root)))
    Image.new("RGB", (160, 96), "navy").save(root / "base.png")
    actor.image_url = "/api/files/base.png"; db_session.commit()
    graph = json.loads((Path(__file__).parents[1] / "workflows/character_appearance_flux2_klein.json").read_text())
    workflow = Workflow(name="Appearance test", type=contract.WORKFLOW_TYPE, is_active=True, workflow_json=json.dumps(graph),
        node_mapping=json.dumps({"load_image_node_id": "76", "prompt_node_id": "117", "save_image_node_id": "9", "seed_node_id": "102"}))
    db_session.add(workflow); db_session.commit()
    assets = db_session.query(Appearance).all()
    first = next(a for a in assets if not a.previous_appearance_id)
    second = next(a for a in assets if a.previous_appearance_id)
    return actor, first, second, workflow, root


class EditLLM:
    provider, model = "test", "vision-test"
    def __init__(self, db, fail=False): self.db, self.fail = db, fail
    async def chat_completion(self, **kw):
        if self.fail: return {"success": False, "error": "MODEL_FAILED"}
        raw, log_id = "Preserve the reference identity and layout; change the clothing to the requested armor.", str(uuid4())
        self.db.add(LLMLog(id=log_id, provider=self.provider, model=self.model, status="success", response=raw,
            system_prompt=kw["system_prompt"], user_prompt=json.dumps(kw["user_content"]), task_type=kw["task_type"],
            novel_id=kw["novel_id"], chapter_id=kw["chapter_id"], character_id=kw["character_id"]))
        self.db.commit()
        return {"success": True, "content": raw, "llm_log_id": log_id}


class Remote:
    def __init__(self, fault=None, on_poll=None): self.fault, self.on_poll, self.submits = fault, on_poll, 0
    async def upload_image(self, path, *, upload_name, payload):
        self.payload = payload
        return {"success": True, "filename": upload_name, "subfolder": "", "type": "input",
            "payload_sha256": hashlib.sha256(payload).hexdigest(), "payload_size": len(payload)}
    def _client(self):
        output = BytesIO(); Image.new("RGB", (160, 96), "gold").save(output, format="PNG")
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=(
            b"wrong" if self.fault == "outputbytes" else output.getvalue()) if r.url.params.get("type") == "output" else (
                b"wrong" if self.fault == "upload" else self.payload))))
    async def queue_prompt(self, graph):
        self.submits += 1; self.graph = deepcopy(graph)
        return {"success": False} if self.fault == "submit" else {"success": True, "prompt_id": "comfy-test"}
    async def get_prompt_state(self, cid):
        if self.on_poll: self.on_poll()
        if self.fault == "cancel-worker": raise asyncio.CancelledError()
        graph = deepcopy(self.graph)
        if self.fault == "float-widgets":
            graph["108"]["inputs"]["cfg"] = float(graph["108"]["inputs"]["cfg"])
            graph["107"]["inputs"]["megapixels"] = float(graph["107"]["inputs"]["megapixels"])
        if self.fault == "graph": graph["117"]["inputs"]["text"] = "tampered"
        images = [{"filename": "result.png", "subfolder": "", "type": "output"}]
        if self.fault == "count": images *= 2
        return {"state": "completed", "history": {"prompt": [0, cid, graph], "status": {"completed": True, "status_str": "success"}, "outputs": {"9": {"images": images}}}}


def enqueue(db, actor, asset, **kw):
    return generation.AppearanceGenerationService(db).enqueue(actor.novel_id, actor.id, asset.id, seed=42, **kw)["data"]["taskId"]


def run(db, task_id, monkeypatch, remote=None, fail_llm=False, recover=False):
    remote = remote or Remote()
    if recover:
        task = db.get(Task, task_id)
    else:
        task = TaskRepository(db).claim_pending_task(contract.TASK_TYPE, "test-worker")
        assert task.id == task_id
        row = db.get(Generation, task_id); row.status, row.claim_token = "RUNNING", task.claim_token; db.commit()
    async def download(url, *args, destination, **kw):
        Image.new("RGB", (160, 96), "gold").save(destination)
        return str(destination)
    monkeypatch.setattr(generation.file_storage, "download_image", download)
    asyncio.run(generation.AppearanceGenerationService(db, llm=EditLLM(db, fail_llm), client=remote).execute(task_id, task.claim_token, recover=recover))
    db.expire_all()
    return remote


def test_complete_receipt_identity_and_immutable_revision(db_session, setup, monkeypatch):
    actor, first, second, _, _ = setup
    before = row_snapshot(actor)
    task_id = enqueue(db_session, actor, first)
    assert enqueue(db_session, actor, first) == task_id
    remote = run(db_session, task_id, monkeypatch)
    g, rev = db_session.get(Generation, task_id), db_session.query(Revision).one()
    assert g.status == "SUCCEEDED", g.error
    assert first.status == "READY" and remote.submits == 1
    assert rev.sha256 == g.execution["result"]["sha256"] and rev.receipt["actual_graph_hash"] == digest(g.execution["graph"])
    assert g.execution["upload"]["remote_sha256"] == g.inputs["source"]["sha256"]
    assert row_snapshot(actor) == before
    _, source = contract.source_reference(db_session, second, actor, contract.load_prompt()["definition"])
    assert source["url"] == actor.image_url and source["kind"] == "CHARACTER_BASE"
    assert source["prior_appearances"][0]["appearance_id"] == first.id
    generation.AppearanceGenerationService(db_session).reject(first, task_id, rev.id, "layout review")
    assert first.status == "REJECTED"
    with pytest.raises(HTTPException): enqueue(db_session, actor, first)
    next_id = enqueue(db_session, actor, first, regenerate=True)
    run(db_session, next_id, monkeypatch, fail_llm=True)
    assert first.status == "FAILED" and db_session.query(Revision).count() == 1
    selection = AppearanceTimelineService(db_session).at(actor.novel_id, first.source_chapter_id, actor.id, 0)["selection"]
    assert selection["appearanceId"] == first.id and selection["referenceImageUrl"] is None and selection["imageRevisionId"] is None
    _, source = contract.source_reference(db_session, second, actor, contract.load_prompt()["definition"])
    assert source["prior_appearances"][0]["appearance_id"] == first.id  # FAILED prior image does not erase the logical change.


@pytest.mark.parametrize("fault,code", [("upload", "REMOTE_REFERENCE_BYTES_CHANGED"), ("submit", "SUBMISSION_UNCONFIRMED"),
    ("graph", "HISTORY_GRAPH_MISMATCH"), ("count", "OUTPUT_COUNT_INVALID"), ("outputbytes", "OUTPUT_BYTES_MISMATCH")])
def test_remote_failures_cannot_publish(db_session, setup, monkeypatch, fault, code):
    actor, first, _, _, _ = setup
    task_id = enqueue(db_session, actor, first)
    remote = run(db_session, task_id, monkeypatch, Remote(fault))
    g = db_session.get(Generation, task_id)
    assert g.status == "FAILED" and code in g.error, g.error
    assert first.status == "FAILED" and not db_session.query(Revision).count()
    assert remote.submits <= 1


@pytest.mark.parametrize("mutation", ["source", "chapter", "cancel", "metadata", "workflow", "prompt_id"])
def test_changes_after_remote_submission_fence_publication(db_session, setup, monkeypatch, mutation):
    actor, first, _, _, root = setup
    task_id = enqueue(db_session, actor, first)
    def modify():
        if mutation == "source": Image.new("RGB", (160, 96), "red").save(root / "base.png")
        elif mutation == "chapter": db_session.get(__import__("app.models.novel", fromlist=["Chapter"]).Chapter, first.source_chapter_id).content += "修改"
        elif mutation == "cancel": db_session.get(Task, task_id).status = "cancelled"
        elif mutation == "workflow": db_session.get(Task, task_id).workflow_json = "{}"
        elif mutation == "prompt_id": db_session.get(Task, task_id).comfyui_prompt_id = "another-prompt"
        else: db_session.get(Task, task_id).metadata_json = "{}"
        db_session.commit()
    run(db_session, task_id, monkeypatch, Remote(on_poll=modify))
    assert first.status == "FAILED" and not db_session.query(Revision).count()
    assert db_session.get(Task, task_id).status == ("cancelled" if mutation == "cancel" else "failed")


def test_restart_recovers_acknowledged_graph_without_resubmit(db_session, setup, monkeypatch):
    actor, first, _, _, _ = setup
    task_id = enqueue(db_session, actor, first)
    remote = Remote("cancel-worker")
    with pytest.raises(asyncio.CancelledError): run(db_session, task_id, monkeypatch, remote)
    assert db_session.get(Generation, task_id).execution["submit"]["state"] == "SUBMITTED"
    remote.fault = None
    run(db_session, task_id, monkeypatch, remote, recover=True)
    assert first.status == "READY" and remote.submits == 1
    assert db_session.query(LLMLog).filter_by(task_type=contract.TASK_TYPE).count() == 1


def test_reviewed_float_widget_spelling_preserves_actual_graph_evidence(db_session, setup, monkeypatch):
    actor, first, _, _, _ = setup
    task_id = enqueue(db_session, actor, first)
    run(db_session, task_id, monkeypatch, Remote("float-widgets"))
    g = db_session.get(Generation, task_id)
    assert first.status == "READY", g.error
    receipt = g.execution["output_receipt"]
    assert receipt["actual_graph_hash"] != receipt["submitted_graph_hash"]
    assert receipt["semantic_graph_hash"] == contract.semantic_graph_digest(g.execution["graph"])


def test_missing_base_and_wrong_workflow_fail_admission(db_session, setup):
    actor, first, second, workflow, _ = setup
    _, source = contract.source_reference(db_session, second, actor, contract.load_prompt()["definition"])
    assert source["kind"] == "CHARACTER_BASE" and first.status == "NEEDS_GENERATION"
    actor.image_url = None; db_session.commit()
    with pytest.raises(HTTPException): enqueue(db_session, actor, first)
    actor.image_url = "/api/files/base.png"; workflow.type = "single_image_edit"; db_session.commit()
    with pytest.raises(HTTPException): enqueue(db_session, actor, first)
    assert not db_session.query(Generation).count()


def test_later_appearance_uses_formal_base_and_logical_context_without_generating_unused_prior(db_session, setup, monkeypatch):
    actor, first, second, _, _ = setup
    before = row_snapshot(actor)
    task_id = enqueue(db_session, actor, second)
    run(db_session, task_id, monkeypatch)
    g = db_session.get(Generation,task_id)
    assert second.status == "READY", g.error
    assert first.status == "NEEDS_GENERATION" and first.task_id is None
    assert g.inputs["source"]["url"] == actor.image_url
    assert g.inputs["source"]["prior_appearances"][0]["description"] == first.description
    assert g.inputs["prompt_template"]["definition"]["prior_appearance_instruction"] in g.execution["llm"]["user_text"]
    assert row_snapshot(actor) == before


def test_usage_is_not_inferred_from_legacy_names_and_stale_receipt_blocks(db_session, chapter, setup):
    actor, first, second, _, _ = setup
    shot = Shot(chapter_id=chapter.id, index=1, description=chapter.content, characters='["刘备"]')
    db_session.add(shot); db_session.commit()
    assert plan_used_missing(db_session, chapter.novel_id, chapter.id, [shot.id])["blocked"][0]["code"] == "SHOT_USAGE_NOT_READY"
    timeline = AppearanceTimelineService(db_session).at(chapter.novel_id, chapter.id, actor.id, 0)
    receipt = Usage(novel_id=chapter.novel_id, chapter_id=chapter.id, shot_id=shot.id, character_id=actor.id,
        appearance_id=first.id, timeline_run_id=timeline["timelineRunId"], source_hash=source_hash(chapter), source_start=0, source_end=5,
        shot_hash=shot_fingerprint(shot), producer="SHOT_ASSET_RESOLVER", producer_version="test-only")
    db_session.add(receipt); db_session.commit()
    plan = plan_used_missing(db_session, chapter.novel_id, chapter.id, [shot.id])
    assert not plan["eligible"]  # Phase6 requires a real immutable RSA demand, not this old placeholder.
    with pytest.raises(HTTPException): verify_usage(db_session, receipt.id, first.id)
    receipt.source_end = len(chapter.content); db_session.commit()
    with pytest.raises(HTTPException): verify_usage(db_session, receipt.id, first.id)
    receipt.source_end = 5; shot.description += "变更"; db_session.commit()
    assert not plan_used_missing(db_session, chapter.novel_id, chapter.id, [shot.id])["eligible"]


def test_api_scope_strict_seed_read_only_detail_and_no_in_place_retry(db_session, setup):
    from app.api.appearance_generations import router
    from app.services.task_service import TaskService
    actor, first, _, _, _ = setup
    app = FastAPI(); app.include_router(router, prefix="/api/novels")
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    prefix = f"/api/novels/{actor.novel_id}/characters/{actor.id}/appearances"
    before = row_snapshot(actor)
    assert client.get(prefix).json()["data"]["appearances"][0]["logicalCurrent"]
    for data in ({"seed": -1}, {"seed": True}, {"seed": 2**64}, {"prompt": "injected"}):
        assert client.post(prefix+f"/{first.id}/generate", json=data).status_code == 422
    assert client.post(prefix.replace(actor.novel_id,"wrong-book")+f"/{first.id}/generate", json={}).status_code == 404
    task_id = client.post(prefix+f"/{first.id}/generate", json={"seed":0}).json()["data"]["taskId"]
    ledger_before = row_snapshot(db_session.get(Generation, task_id))
    assert client.get(prefix+f"/{first.id}").json()["data"]["attempts"][0]["inputs"]["seed"] == 0
    assert row_snapshot(db_session.get(Generation, task_id)) == ledger_before and row_snapshot(actor) == before
    service = TaskService(db_session)
    assert asyncio.run(service.reconcile_active_tasks([db_session.get(Task,task_id)])) == 0
    cancelled = asyncio.run(service.cancel_task(task_id))
    assert cancelled["success"] and db_session.get(Generation,task_id).status == "FAILED"
    db_session.refresh(first); assert first.status == "FAILED"
    task = db_session.get(Task,task_id); task.status = "failed"; db_session.commit()
    snapshot = row_snapshot(task)
    assert service.retry_task(task_id)["status_code"] == 409 and row_snapshot(task) == snapshot


@pytest.mark.parametrize("mutation", ["reference", "seed", "prompt", "output", "duplicate"])
def test_invalid_workflow_rejected_before_task_creation(db_session, setup, mutation):
    actor, first, _, workflow, _ = setup
    mapping = json.loads(workflow.node_mapping)
    mapping[{"reference":"load_image_node_id", "seed":"seed_node_id", "prompt":"prompt_node_id", "output":"save_image_node_id", "duplicate":"seed_node_id"}[mutation]] = "76" if mutation == "duplicate" else "missing"
    workflow.node_mapping=json.dumps(mapping); db_session.commit()
    with pytest.raises((ValueError, KeyError)): enqueue(db_session, actor, first)
    assert not db_session.query(Generation).count()


def test_worker_claim_crash_fails_without_resubmission(db_session, setup, monkeypatch):
    from datetime import datetime, timedelta
    import app.core.database as database
    actor, first, _, _, _ = setup
    task_id = enqueue(db_session, actor, first)
    task = TaskRepository(db_session).claim_pending_task(contract.TASK_TYPE, "lost-worker")
    task.heartbeat_at = datetime.utcnow()-timedelta(minutes=5);db_session.commit()
    # Simulate death between the Task claim commit and ledger RUNNING commit.
    monkeypatch.setattr(database,"SessionLocal",lambda: db_session)
    assert asyncio.run(generation.run_next_appearance_task())
    g = db_session.get(Generation, task_id)
    assert g.status == "FAILED" and "NOT_REPLAYED" in g.error
    assert not db_session.query(Revision).count()


def test_migration_preserves_old_images_and_is_idempotent():
    from app.services.appearance_generation_schema import upgrade
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE character_appearances (id VARCHAR PRIMARY KEY, status VARCHAR, reference_image_url VARCHAR)"))
        db.execute(text("INSERT INTO character_appearances VALUES ('old', 'READY', '/old-image.png')"))
    upgrade(engine); upgrade(engine)
    with engine.connect() as db:
        row = dict(db.execute(text("SELECT * FROM character_appearances")).mappings().one())
        assert row == {"id":"old","status":"READY","reference_image_url":"/old-image.png","reference_image_revision_id":None,"generation_revision":0,"last_error":None}
        assert all(inspect(db).has_table(name) for name in ("appearance_generations","appearance_image_revisions","appearance_shot_usages"))
    engine.dispose()


def test_classified_local_templates_remain_file_backed_without_database_shadow(db_session, monkeypatch):
    from app.services import prompt_template_service as templates
    from app.models.prompt_template import PromptTemplate
    from app.api.prompt_templates import PROMPT_TEMPLATE_EXPORT_CATEGORIES
    service = templates.PromptTemplateService(db_session)
    before = db_session.query(PromptTemplate).count()
    for kind, (filename, name) in templates.LOCAL_PROMPT_FILES.items():
        rows = service.list_templates(kind)
        assert len(rows) == 1 and rows[0].name == name and rows[0].id == "local:"+kind
        assert rows[0].template == templates.load_template(filename)
        assert service.to_response(rows[0])["sourceFile"].endswith(filename)
        with pytest.raises(PermissionError): service.create_template("shadow", "", "ignored prompt", kind)
        with pytest.raises(PermissionError): service.copy_template(rows[0].id)
        with pytest.raises(PermissionError): service.update_template(rows[0].id, template="ignored prompt")
        assert any((kind,name) in entries for _,entries in PROMPT_TEMPLATE_EXPORT_CATEGORIES)
    monkeypatch.setattr(templates,"load_template",lambda filename: '{"version":"local-live-edit"}')
    assert service.get_template_by_id("local:character_appearance_generation").template == '{"version":"local-live-edit"}'
    assert db_session.query(PromptTemplate).count() == before
