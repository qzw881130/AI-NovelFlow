"""Manual, DB-backed Character Appearance ImageEdit with frozen source and output receipts."""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import secrets
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from app.models.appearance_timeline import CharacterAppearance as Appearance
from app.models.appearance_generation import AppearanceGeneration as Generation, AppearanceImageRevision as Revision
from app.models.novel import Novel
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.llm_log import LLMLog
from app.repositories.task import TaskRepository
from app.services.file_storage import file_storage
from app.services.prompt_builder import get_style
from app.services.llm_service import LLMService
from app.services.keyframe_reference_contract import frozen_keyframe_client
from app.services.comfyui.client import ComfyUIClient
from app.services.chapter_asset_parse_service import digest
from app.services.appearance_image_contract import (VERSION, WORKFLOW_TYPE, TASK_TYPE, load_prompt, image_bytes,
    current_appearance, source_reference, ready_revision, build_graph,
    output_receipt, receipt_url, artifact_path, capture_source)
from app.utils.path_utils import url_to_local_path, local_path_to_url

WORKER_ID = "appearance-" + uuid4().hex


def logical_snapshot(asset):
    return {key: getattr(asset, key) for key in ("id", "novel_id", "character_id", "source_chapter_id", "source_event_id",
                                               "definition", "definition_hash", "description", "previous_appearance_id")}


def proof_identity(proof):
    return {key: value for key, value in proof.items() if key != "run_id"}


def settle_terminal(db, task):
    """Task cancellation never rewrites the Character base or adopts old READY images."""
    generation = db.get(Generation, task.id)
    if generation and generation.status in {"PENDING", "RUNNING"} and task.status in {"cancelled", "failed"}:
        generation.status, generation.error, generation.completed_at = "FAILED", task.error_message or "TASK_TERMINATED", datetime.utcnow()
        db.query(Appearance).filter_by(id=generation.appearance_id, task_id=task.id, status="GENERATING").update({
            "status": "FAILED", "last_error": generation.error}, synchronize_session=False)


class AppearanceGenerationService:
    def __init__(self, db, *, llm=None, client=None):
        self.db, self.llm, self.client = db, llm, client

    def enqueue(self, novel_id, character_id, appearance_id, *, seed=None, regenerate=False, usage_ids=None):
        db = self.db
        asset = db.get(Appearance, appearance_id)
        if not asset or asset.novel_id != novel_id or asset.character_id != character_id:
            raise HTTPException(404, "角色外观不存在")
        asset, actor, timeline = current_appearance(db, asset.id)
        if usage_ids:
            from app.services.appearance_usage import verify_usage
            for usage_id in usage_ids:
                verify_usage(db, usage_id, appearance_id)
        active = db.query(Generation).filter(Generation.appearance_id == appearance_id, Generation.status.in_(["PENDING", "RUNNING"])).first()
        if active:
            task = db.get(Task, active.id)
            if task and task.status in {"pending", "running"}:
                return {"success": True, "data": {"taskId": active.id, "appearanceId": asset.id, "status": asset.status, "reused": True}}
            if task:
                settle_terminal(db, task)
            else:
                active.status, active.error = "FAILED", "TASK_RECORD_MISSING"
                asset.status = "FAILED"
            db.commit()
        prompt = load_prompt()
        if asset.status == "READY" and not regenerate:
            ready_revision(db, asset, prompt["definition"])
            return {"success": True, "data": {"appearanceId": asset.id, "status": "READY", "reused": True, "taskId": asset.task_id}}
        if asset.status == "REJECTED" and not regenerate:
            raise HTTPException(409, "外观图已拒绝，请显式选择重新生成")
        asset, actor, timeline = current_appearance(db, asset.id)
        payload, source = source_reference(db, asset, actor, prompt["definition"])
        workflows = db.query(Workflow).filter_by(type=WORKFLOW_TYPE, is_active=True).all()
        if len(workflows) != 1:
            raise HTTPException(409, "CHARACTER_APPEARANCE_WORKFLOW_REQUIRED")
        workflow = workflows[0]
        mapping, graph = json.loads(workflow.node_mapping or "{}"), json.loads(workflow.workflow_json)
        seed = seed if seed is not None else secrets.randbits(63)
        if type(seed) is not int or not 0 <= seed <= 18446744073709551615:
            raise HTTPException(422, "seed无效")
        build_graph(graph, mapping, seed=seed)
        style, style_template = get_style(db, db.get(Novel, novel_id), "character")
        task_id = str(uuid4())
        source["captured_url"] = capture_source(novel_id, asset.id, task_id, payload, source)
        old_task, old_revision = asset.task_id, asset.generation_revision
        inputs = {"version": VERSION, "asset": logical_snapshot(asset), "timeline": timeline, "source": source,
                  "purpose": "USED_BY_SHOTS" if usage_ids else "MANUAL_APPEARANCE", "usage_ids": usage_ids or [],
                  "character": {"id": actor.id, "name": actor.name, "entity_type": actor.entity_type},
                  "style_context": {"text": style, "template_id": style_template.id if style_template else None, "hash": digest(style)},
                  "prompt_template": prompt, "seed": seed, "generation_revision": old_revision + 1,
                  "endpoint": frozen_keyframe_client(ComfyUIClient().base_url).base_url,
                  "workflow": {"id": workflow.id, "name": workflow.name, "type": workflow.type, "mapping": mapping,
                               "graph": graph, "hash": digest(graph)}}
        task = Task(id=task_id, type=TASK_TYPE, novel_id=novel_id, character_id=character_id, chapter_id=asset.source_chapter_id,
            name=f"角色外观生成：{actor.name}", description=asset.description, status="pending", current_step="等待外观编辑工作队列",
            workflow_id=workflow.id, workflow_name=workflow.name,
            reference_images=json.dumps([{"label": "Book正式角色基图", "url": source["captured_url"]}], ensure_ascii=False),
            metadata_json=json.dumps({"execution_purpose": "production", "appearance_generation_id": task_id,
                "appearance_id": asset.id, "definition_hash": asset.definition_hash, "inputs_hash": digest(inputs)}, ensure_ascii=False))
        changed = db.query(Appearance).filter(Appearance.id == appearance_id, Appearance.task_id == old_task,
            Appearance.generation_revision == old_revision, Appearance.status != "GENERATING").update({
                "status": "GENERATING", "task_id": task_id, "workflow_id": workflow.id,
                "generation_revision": old_revision + 1, "last_error": None}, synchronize_session=False)
        if changed != 1:
            db.rollback(); raise HTTPException(409, "外观状态已变化，请刷新")
        db.add_all([task, Generation(id=task_id, appearance_id=appearance_id, novel_id=novel_id, character_id=character_id,
                                    status="PENDING", inputs=inputs, input_hash=digest(inputs), execution={"phase": "PENDING"})])
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback(); raise HTTPException(409, "外观已有进行中的生成任务") from exc
        return {"success": True, "data": {"taskId": task_id, "appearanceId": appearance_id, "status": "GENERATING", "seed": seed}}

    def _guard(self, generation_id, token, *, sources=True):
        db = self.db
        db.expire_all()
        g, task = db.get(Generation, generation_id), db.get(Task, generation_id)
        if not g or not task or g.status != "RUNNING" or task.status != "running" or g.claim_token != token or task.claim_token != token:
            raise RuntimeError("APPEARANCE_EXECUTION_FENCED")
        if digest(g.inputs) != g.input_hash:
            raise RuntimeError("APPEARANCE_INPUTS_CHANGED")
        meta = json.loads(task.metadata_json or "{}")
        if (task.type != TASK_TYPE or task.novel_id != g.novel_id or task.character_id != g.character_id
                or task.workflow_id != g.inputs["workflow"]["id"]
                or meta.get("inputs_hash") != g.input_hash or meta.get("appearance_id") != g.appearance_id):
            raise RuntimeError("APPEARANCE_TASK_BINDING_CHANGED")
        if (g.execution or {}).get("submit", {}).get("state") == "SUBMITTED":
            if (task.comfyui_prompt_id != g.execution["submit"]["prompt_id"]
                    or digest(json.loads(task.workflow_json or "{}")) != g.execution["submit"]["graph_hash"]
                    or task.prompt_text != g.execution["prompt"]):
                raise RuntimeError("APPEARANCE_TASK_SUBMISSION_CHANGED")
        asset = db.get(Appearance, g.appearance_id)
        if not asset or asset.task_id != g.id or asset.status != "GENERATING" or asset.generation_revision != g.inputs["generation_revision"]:
            raise RuntimeError("APPEARANCE_OWNER_CHANGED")
        if sources:
            if g.inputs.get("usage_ids"):
                from app.services.appearance_usage import verify_usage
                for usage_id in g.inputs["usage_ids"]:
                    verify_usage(db, usage_id, g.appearance_id)
            asset, actor, timeline = current_appearance(db, g.appearance_id)
            if logical_snapshot(asset) != g.inputs["asset"] or proof_identity(timeline) != proof_identity(g.inputs["timeline"]):
                raise RuntimeError("APPEARANCE_LOGICAL_SOURCE_CHANGED")
            _, source = source_reference(db, asset, actor, g.inputs["prompt_template"]["definition"])
            if source != {k: v for k, v in g.inputs["source"].items() if k != "captured_url"}:
                raise RuntimeError("APPEARANCE_SOURCE_IMAGE_CHANGED")
        return g, task, asset

    def _save(self, generation_id, token, execution, step, *, prompt=None, graph=None, cid=None):
        g, task, _ = self._guard(generation_id, token, sources=False)
        g.execution = deepcopy(execution)
        task.current_step, task.heartbeat_at = step, datetime.utcnow()
        if prompt is not None: task.prompt_text = prompt
        if graph is not None: task.workflow_json = json.dumps(graph, ensure_ascii=False)
        if cid is not None: task.comfyui_prompt_id = cid
        self.db.commit()

    async def _await(self, awaitable, generation_id, token):
        operation = asyncio.ensure_future(awaitable)
        try:
            while True:
                done, _ = await asyncio.wait({operation}, timeout=15)
                if done:
                    return operation.result()
                _, task, _ = self._guard(generation_id, token)
                task.heartbeat_at = datetime.utcnow(); self.db.commit()
        finally:
            if not operation.done():
                operation.cancel()

    def _fail(self, generation_id, token, execution, error):
        self.db.rollback()
        g, task = self.db.get(Generation, generation_id), self.db.get(Task, generation_id)
        if not g or g.claim_token != token or g.status == "SUCCEEDED":
            return
        g.execution, g.error, g.status, g.completed_at = deepcopy(execution), str(error), "FAILED", datetime.utcnow()
        if task and task.claim_token == token:
            if task.status in {"pending", "running"}:
                task.status, task.error_message, task.current_step, task.completed_at = "failed", str(error), "外观编辑失败", datetime.utcnow()
            submit = execution.get("submit") or {}
            if submit.get("prompt_id"):
                task.comfyui_prompt_id = submit["prompt_id"]
        self.db.query(Appearance).filter_by(id=g.appearance_id, task_id=g.id, status="GENERATING").update({
            "status": "FAILED", "last_error": str(error)}, synchronize_session=False)
        self.db.commit()

    async def execute(self, generation_id, token, *, recover=False):
        g = self.db.get(Generation, generation_id)
        inputs, execution = deepcopy(g.inputs), deepcopy(g.execution or {})
        client = self.client or frozen_keyframe_client(inputs["endpoint"])
        try:
            self._guard(generation_id, token)
            if not recover:
                captured, info = image_bytes(inputs["source"]["captured_url"], inputs["prompt_template"]["definition"])
                if info["sha256"] != inputs["source"]["sha256"]:
                    raise RuntimeError("CAPTURED_REFERENCE_CHANGED")
                policy = inputs["prompt_template"]["definition"]
                data = {"character": inputs["character"], "appearance_description": inputs["asset"]["description"],
                        "source_reference": inputs["source"], "style_context": inputs["style_context"],
                        "appearance_id": inputs["asset"]["id"]}
                user_text = policy["user_template"].format_map({"payload": json.dumps(data, ensure_ascii=False)})
                user_text += "\n" + policy["preservation_instruction"]
                if inputs["source"].get("prior_appearances"):
                    user_text += "\n" + policy["prior_appearance_instruction"]
                mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[info["format"]]
                llm = self.llm or LLMService()
                execution.update(phase="PROMPT_BUILDING", llm={"system_prompt": policy["system_prompt"], "user_text": user_text,
                    "image_sha256": info["sha256"], "provider": llm.provider, "model": llm.model})
                self._save(generation_id, token, execution, "构建角色外观编辑提示词")
                response = await self._await(llm.chat_completion(system_prompt=policy["system_prompt"], user_content=[
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64," + base64.b64encode(captured).decode("ascii")}}],
                    response_format=None, temperature=0.2, max_tokens=4096, task_type=TASK_TYPE,
                    prompt_template_name=inputs["prompt_template"]["version"], novel_id=inputs["asset"]["novel_id"],
                    chapter_id=inputs["asset"]["source_chapter_id"], character_id=inputs["character"]["id"]), generation_id, token)
                execution["llm"].update(log_id=response.get("llm_log_id"), response=response.get("content"), success=response.get("success"))
                self._save(generation_id, token, execution, "校验外观编辑提示词")
                if not response.get("success"):
                    raise RuntimeError(response.get("error") or "APPEARANCE_PROMPT_FAILED")
                raw = response.get("content")
                if not isinstance(raw, str) or not raw.strip() or raw.lstrip().startswith(("{", "[", "```")):
                    raise RuntimeError("APPEARANCE_PROMPT_INVALID")
                log = self.db.get(LLMLog, response.get("llm_log_id")) if response.get("llm_log_id") else None
                if (not log or log.status != "success" or log.response != raw or log.system_prompt != policy["system_prompt"]
                        or log.novel_id != inputs["asset"]["novel_id"] or log.character_id != inputs["character"]["id"]
                        or log.chapter_id != inputs["asset"]["source_chapter_id"] or log.task_type != TASK_TYPE
                        or json.loads(log.user_prompt)[0] != {"type": "text", "text": user_text}):
                    raise RuntimeError("APPEARANCE_LLM_LOG_UNVERIFIED")
                prompt = raw.strip() + policy["image_prompt_suffix"]
                self._guard(generation_id, token)
                extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[info["format"]]
                upload = await self._await(client.upload_image(url_to_local_path(inputs["source"]["captured_url"]),
                    upload_name=f"appearance-{generation_id}-source{extension}", payload=captured), generation_id, token)
                if not upload.get("success") or upload.get("payload_sha256") != info["sha256"] or upload.get("payload_size") != len(captured):
                    raise RuntimeError("APPEARANCE_UPLOAD_RECEIPT_INVALID")
                execution["upload"] = upload
                async with client._client() as http:
                    remote = await http.get(receipt_url(inputs["endpoint"], {"filename": upload["filename"].rsplit("/", 1)[-1],
                        "subfolder": upload["subfolder"], "type": "input"}), timeout=30)
                    remote.raise_for_status()
                remote_hash = hashlib.sha256(remote.content).hexdigest()
                if remote_hash != info["sha256"]:
                    raise RuntimeError("REMOTE_REFERENCE_BYTES_CHANGED")
                execution["upload"]["remote_sha256"] = remote_hash
                graph, graph_proof = build_graph(inputs["workflow"]["graph"], inputs["workflow"]["mapping"],
                    seed=inputs["seed"], prompt=prompt, filename=upload["filename"])
                output_id = str(inputs["workflow"]["mapping"]["save_image_node_id"])
                graph[output_id]["inputs"]["filename_prefix"] = f"appearance-{generation_id}"
                execution.update(phase="PREPARED", prompt=prompt, graph=graph, graph_proof=graph_proof,
                                 submit={"state": "ATTEMPTED", "graph_hash": digest(graph)})
                self._save(generation_id, token, execution, "提交外观ImageEdit工作流", prompt=prompt)
                self._guard(generation_id, token)
                queued = await self._await(client.queue_prompt(graph), generation_id, token)
                if not queued.get("success") or not isinstance(queued.get("prompt_id"), str) or not queued["prompt_id"]:
                    execution["submit"]["state"] = "UNKNOWN"
                    raise RuntimeError("APPEARANCE_SUBMISSION_UNCONFIRMED")
                execution["submit"].update(state="SUBMITTED", prompt_id=queued["prompt_id"])
                execution["phase"] = "SUBMITTED"
                self._save(generation_id, token, execution, "外观图生成中", graph=graph, cid=queued["prompt_id"])
            else:
                if execution.get("submit", {}).get("state") != "SUBMITTED":
                    raise RuntimeError("UNCONFIRMED_APPEARANCE_ATTEMPT_NOT_REPLAYED")
                graph = execution["graph"]
                if digest(graph) != execution["submit"]["graph_hash"]:
                    raise RuntimeError("SAVED_APPEARANCE_GRAPH_CHANGED")
            cid = execution["submit"]["prompt_id"]
            deadline = asyncio.get_running_loop().time() + 7200
            missing_since = None
            while True:
                self._guard(generation_id, token)
                state = await self._await(client.get_prompt_state(cid), generation_id, token)
                if state.get("state") == "completed":
                    receipt = output_receipt(state["history"], cid, graph, inputs["workflow"]["mapping"]["save_image_node_id"])
                    execution.update(phase="OUTPUT_VERIFIED", output_receipt=receipt)
                    self._save(generation_id, token, execution, "下载并校验角色外观图")
                    break
                if state.get("state") == "missing":
                    missing_since = missing_since or asyncio.get_running_loop().time()
                else:
                    missing_since = None
                if state.get("state") == "error" or (missing_since and asyncio.get_running_loop().time() - missing_since > 60):
                    raise RuntimeError(state.get("message") or "APPEARANCE_REMOTE_JOB_UNAVAILABLE")
                if asyncio.get_running_loop().time() > deadline:
                    raise RuntimeError("APPEARANCE_GENERATION_TIMEOUT")
                _, task, _ = self._guard(generation_id, token)
                task.heartbeat_at = datetime.utcnow(); self.db.commit()
                await asyncio.sleep(2)
            destination = artifact_path(inputs["asset"]["novel_id"], inputs["asset"]["id"], generation_id, "result.png")
            async with client._client() as http:
                remote_output = await self._await(http.get(receipt_url(inputs["endpoint"], receipt["image"]), timeout=60), generation_id, token)
                remote_output.raise_for_status()
            if len(remote_output.content) > inputs["prompt_template"]["definition"]["max_source_bytes"]:
                raise RuntimeError("APPEARANCE_OUTPUT_TOO_LARGE")
            remote_output_hash = hashlib.sha256(remote_output.content).hexdigest()
            if not destination.is_file():
                path = await self._await(file_storage.download_image(receipt_url(inputs["endpoint"], receipt["image"]),
                    inputs["asset"]["novel_id"], "appearance", destination=destination), generation_id, token)
                if not path:
                    raise RuntimeError("APPEARANCE_DOWNLOAD_FAILED")
            image_url = local_path_to_url(str(destination))
            payload, image = image_bytes(image_url, inputs["prompt_template"]["definition"])
            if image["sha256"] != remote_output_hash:
                raise RuntimeError("APPEARANCE_OUTPUT_BYTES_MISMATCH")
            execution["output_receipt"]["remote_sha256"] = remote_output_hash
            if abs((image["width"] / image["height"]) / (inputs["source"]["width"] / inputs["source"]["height"]) - 1) > inputs["prompt_template"]["definition"]["max_aspect_error"]:
                raise RuntimeError("APPEARANCE_REFERENCE_LAYOUT_ASPECT_CHANGED")
            execution["result"] = image
            self._save(generation_id, token, execution, "发布角色外观图")
            # Take the DB write fence before rechecking the source chain and publishing.
            locked = self.db.query(Appearance).filter_by(id=inputs["asset"]["id"], task_id=generation_id,
                status="GENERATING", generation_revision=inputs["generation_revision"]).update({
                    "generation_revision": inputs["generation_revision"]}, synchronize_session=False)
            if locked != 1:
                raise RuntimeError("APPEARANCE_PUBLICATION_FENCED")
            g, task, asset = self._guard(generation_id, token)
            revision = Revision(id=str(uuid4()), appearance_id=asset.id, generation_id=g.id, image_url=image_url,
                sha256=image["sha256"], width=image["width"], height=image["height"], receipt=execution["output_receipt"])
            count = self.db.query(Appearance).filter_by(id=asset.id, task_id=g.id, status="GENERATING",
                generation_revision=inputs["generation_revision"], definition_hash=inputs["asset"]["definition_hash"]).update({
                    "status": "READY", "reference_image_url": image_url, "reference_image_revision_id": revision.id,
                    "last_error": None}, synchronize_session=False)
            if count != 1:
                raise RuntimeError("APPEARANCE_PUBLICATION_FENCED")
            self.db.add(revision)
            execution.update(phase="COMPLETED", image_revision_id=revision.id)
            g.execution, g.status, g.completed_at = execution, "SUCCEEDED", datetime.utcnow()
            task.status, task.result_url, task.progress, task.current_step, task.completed_at = "completed", image_url, 100, "角色外观图已就绪", datetime.utcnow()
            self.db.commit()
        except asyncio.CancelledError:
            self.db.rollback()
            task = self.db.get(Task, generation_id)
            if task and task.claim_token == token:
                task.heartbeat_at = datetime.utcnow() - timedelta(minutes=5)
                self.db.commit()
            raise
        except Exception as exc:
            self._fail(generation_id, token, execution, exc)

    def reject(self, asset, expected_generation_id, expected_revision_id, reason):
        count = self.db.query(Appearance).filter_by(id=asset.id, task_id=expected_generation_id,
            reference_image_revision_id=expected_revision_id, status="READY").update({"status": "REJECTED", "last_error": reason}, synchronize_session=False)
        if count != 1:
            self.db.rollback(); raise HTTPException(409, "图像版本已变化，请刷新再拒绝")
        g = self.db.get(Generation, expected_generation_id)
        if g:
            g.execution = {**g.execution, "review": {"action": "REJECT", "image_revision_id": expected_revision_id,
                                                   "reason": reason, "at": datetime.utcnow().isoformat()}}
        self.db.commit()
        return {"success": True}


async def run_next_appearance_task():
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        # Restart recovery polls only acknowledged submissions. It never resubmits a graph or rebuilds a prompt.
        for g in db.query(Generation).filter(Generation.status.in_(["PENDING", "RUNNING"])).order_by(Generation.created_at).all():
            task = db.get(Task, g.id)
            if task and task.status in {"failed", "cancelled"}:
                settle_terminal(db, task); db.commit()
            elif not task:
                g.status, g.error = "FAILED", "TASK_RECORD_MISSING"
                db.query(Appearance).filter_by(id=g.appearance_id, task_id=g.id, status="GENERATING").update({
                    "status": "FAILED", "last_error": g.error}, synchronize_session=False)
                db.commit()
        task = TaskRepository(db).claim_pending_task(TASK_TYPE, WORKER_ID)
        if task:
            g = db.get(Generation, task.id)
            if not g or g.status != "PENDING":
                task.status, task.error_message = "failed", "GENERATION_LEDGER_UNAVAILABLE"; db.commit(); return True
            g.status, g.claim_token = "RUNNING", task.claim_token
            db.commit()
            await AppearanceGenerationService(db).execute(task.id, task.claim_token)
            return True
        stale = db.query(Task).filter(Task.type == TASK_TYPE, Task.status == "running",
            or_(Task.heartbeat_at.is_(None), Task.heartbeat_at < datetime.utcnow() - timedelta(seconds=90))).order_by(Task.created_at).first()
        if stale:
            old_token, old_heartbeat, task_id = stale.claim_token, stale.heartbeat_at, stale.id
            token = str(uuid4())
            count = db.query(Task).filter_by(id=task_id, status="running", claim_token=old_token, heartbeat_at=old_heartbeat).update({
                "claim_token": token, "worker_id": WORKER_ID, "heartbeat_at": datetime.utcnow()}, synchronize_session=False)
            g = db.get(Generation, task_id)
            if count == 1 and g and g.status in {"PENDING", "RUNNING"}:
                g.status, g.claim_token = "RUNNING", token; db.commit()
                await AppearanceGenerationService(db).execute(task_id, token, recover=True)
                return True
            db.rollback()
        return False
    finally:
        db.close()
