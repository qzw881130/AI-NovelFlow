"""关键帧服务

提供关键帧描述生成、图片生成、图片上传、参考图设置等功能。
"""

import json
import os
import uuid
import httpx
import asyncio
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session, object_session

from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.novel import Novel, Chapter
from app.models.prompt_template import PromptTemplate
from app.repositories.shot_repository import ShotRepository
from app.repositories.prompt_template import PromptTemplateRepository
from app.services.comfyui import ComfyUIService
from app.services.llm_service import LLMService
from app.services.file_storage import file_storage
from app.services.video_director_plan_service import VideoDirectorPlanService
from app.services.background_workers import worker_manager
from app.services.prompt_builder import get_style
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.services.keyframe_reference_contract import (
    CONTRACT_KEY, CONTRACT_VERSION, KeyframeReferenceError, assert_target, assert_task_active,
    digest, frozen_keyframe_client, json_value, patch_target, read_contract, reference_images,
    reference_manifest, select_keyframe_output, snapshot_target, store_contract, validate_reference_prompt,
    seal_contract, reference_cache_fingerprint, validate_frozen_contract, record_contract_observation,
    semantic_reference_cache_fingerprint,
)
from app.services.keyframe_reference_graph import (
    normalize_keyframe_mapping, prepare_keyframe_graph, stable_graph_fingerprint, validate_keyframe_graph,
)


class ShotKeyframeService:
    """关键帧服务类"""

    def __init__(self):
        self.llm_service = LLMService()

    def _sync_video_director_keyframe_image(self, shot: Shot, keyframe: dict, image_url: str, task_id: Optional[str] = None) -> None:
        plan_keyframe_index = keyframe.get("plan_keyframe_index")
        if plan_keyframe_index is None or not shot.video_director_plan:
            return
        def mutate(plan: dict) -> dict:
            keyframes = plan.get("keyframes") if isinstance(plan.get("keyframes"), list) else []
            for plan_keyframe in keyframes:
                if isinstance(plan_keyframe, dict) and int(plan_keyframe.get("index") or -1) == int(plan_keyframe_index):
                    plan_keyframe["image_url"] = image_url
                    if task_id:
                        plan_keyframe["image_task_id"] = task_id
                    break
            plan["keyframes"] = keyframes
            return plan

        db = object_session(shot)
        if db:
            VideoDirectorPlanService(db).mutate(shot.id, mutate)

    def _sync_video_director_keyframe_fields(self, shot: Shot, keyframe: dict, fields: dict) -> None:
        plan_keyframe_index = keyframe.get("plan_keyframe_index")
        if plan_keyframe_index is None or not shot.video_director_plan:
            return
        def mutate(plan: dict) -> dict:
            keyframes = plan.get("keyframes") if isinstance(plan.get("keyframes"), list) else []
            for plan_keyframe in keyframes:
                if isinstance(plan_keyframe, dict) and int(plan_keyframe.get("index") or -1) == int(plan_keyframe_index):
                    plan_keyframe.update(fields)
                    break
            plan["keyframes"] = keyframes
            return plan

        db = object_session(shot)
        if db:
            VideoDirectorPlanService(db).mutate(shot.id, mutate)

    def _get_reusable_keyframe_prompt(self, db: Session, task: Task, contract: dict, *, graph=None) -> str:
        from app.services.task_execution import is_benchmark

        present = [entry["value"] for entry in contract["draft"].values() if entry["present"]]
        if present and (any(not isinstance(value, str) or not value.strip() for value in present) or len(set(present)) != 1):
            raise KeyframeReferenceError("UNVERIFIED_CURRENT_PROMPT", "请使用 LLM+ 显式生成新的提示词；不会替换当前草稿。")
        candidate = present[0] if present else None
        for previous in db.query(Task).filter(
            Task.type == "keyframe_image", Task.shot_id == task.shot_id, Task.id != task.id,
        ).order_by(Task.created_at.desc()).all():
            saved = read_contract(previous)
            if contract.get("execution_purpose", "production") == "production" and is_benchmark(previous):
                continue
            if not saved:
                continue
            prompt_record = saved.get("prompt") or {}
            text = previous.prompt_text
            if (not isinstance(text, str) or not text.strip() or (candidate is not None and text != candidate)
                    or prompt_record.get("text_hash") != digest(text)
                    or not prompt_record.get("validation", {}).get("passed")
                    or not saved.get("validation", {}).get("passed") or not saved.get("binding_resolved")):
                continue
            try:
                validate_frozen_contract(saved, previous)
                # Older callers can use a verified prior graph only when its
                # exact stable hash also proves the current staged workflow.
                current_graph = graph if graph is not None else contract.get("prepared_workflow", saved["prepared_workflow"])
                if (semantic_reference_cache_fingerprint(saved)
                        != semantic_reference_cache_fingerprint(contract, graph=current_graph)):
                    continue
            except (KeyframeReferenceError, RuntimeError, KeyError, TypeError, ValueError):
                continue
            validate_reference_prompt(text, contract["resolved"]["source_kind"] if contract["resolved"] else "NONE")
            contract["prompt"].update(origin="reuse", reused_from_task_id=previous.id, llm_invoked=False)
            return text
        raise KeyframeReferenceError("CACHE_BINDING_UNVERIFIED", "当前提示词缺少与本次参考绑定一致的独立记录，请使用 LLM+。")

    def _get_keyframe_image_prompt_template(self, db: Session, novel: Optional[Novel]) -> Optional[PromptTemplate]:
        template = None
        if novel and novel.keyframe_image_prompt_template_id:
            template = db.query(PromptTemplate).filter(
                PromptTemplate.id == novel.keyframe_image_prompt_template_id
            ).first()
        if not template:
            template = PromptTemplateRepository(db).get_default_system_template("keyframe_image_prompt")
        return template

    def _extract_keyframe_image_prompt(self, content: str) -> str:
        text = (content or "").strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except Exception:
            return text
        if not isinstance(parsed, dict):
            return text
        for key in ("final_prompt", "prompt", "promptText", "prompt_text"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return text

    @staticmethod
    def _build_keyframe_reference_manifest(contract: dict) -> list:
        return reference_manifest(contract)

    async def _build_qwen_keyframe_prompt(
        self,
        db: Session,
        novel: Novel,
        shot: Shot,
        task: Task,
        contract: dict,
    ) -> str:
        payload = {**contract["context"], "reference_image_manifest": self._build_keyframe_reference_manifest(contract),
                   "reference_resolution": {"source_kind": contract["resolved"]["source_kind"] if contract["resolved"] else "NONE",
                                            "fallback": contract.get("fallback"), "reference_count": len(contract["manifest"])},
                   "audit_context": {"task_id": task.id, "binding_hash": contract["frozen_binding_hash"]}}
        user_content = "请仅依据本次已绑定的参考图清单和当前关键帧状态，生成最终编辑提示词。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
        contract["prompt"].update(origin="llm", llm_invoked=True, input_hash=digest(user_content))
        contract["phase"] = "prompt_building"
        store_contract(db, task.id, contract, current_step="正在调用 #09 绑定提示词构建...")
        result = await self.llm_service.chat_completion(
            system_prompt=contract["template"]["text"],
            user_content=user_content,
            temperature=0.3,
            max_tokens=2500,
            task_type="keyframe_image_prompt",
            prompt_template_name=contract["template"]["name"],
            novel_id=novel.id,
            chapter_id=shot.chapter_id,
        )
        contract["prompt"]["raw_response"] = result.get("content")
        if not result.get("success"):
            contract["prompt"].update(failure_kind=result.get("failure_kind"), diagnostic_content=result.get("diagnostic_content"))
            raise KeyframeReferenceError("PROMPT_BUILD_FAILED", result.get("error") or "#09 提示词构建失败")
        if not isinstance(result.get("content"), str):
            raise KeyframeReferenceError("INVALID_PROMPT_RESPONSE_TYPE")
        return self._extract_keyframe_image_prompt(result["content"])

    def _get_novel_id(self, db: Session, shot: Shot) -> Optional[str]:
        """通过分镜获取小说ID

        Args:
            db: 数据库会话
            shot: 分镜对象

        Returns:
            小说ID，如果获取失败返回None
        """
        chapter = db.query(Chapter).filter(Chapter.id == shot.chapter_id).first()
        return chapter.novel_id if chapter else None

    @staticmethod
    def load_task_shot(db, task, contract):
        """The recovery path must use the same private target as the worker."""
        purpose = json_value(task.metadata_json, dict).get("execution_purpose", "production")
        if purpose not in ("production", "benchmark") or purpose != contract.get("execution_purpose", "production"):
            raise KeyframeReferenceError("EXECUTION_PURPOSE_CHANGED")
        if purpose == "benchmark":
            from app.services.task_execution import load_execution_shot
            shot = load_execution_shot(task)
            if shot._execution_attempt_id != contract.get("execution_attempt_id"):
                raise KeyframeReferenceError("EXECUTION_ATTEMPT_CHANGED")
            return shot
        return db.query(Shot).filter(Shot.id == task.shot_id).populate_existing().first()

    @staticmethod
    def _check_reference_task(db, task_id, contract):
        task = db.query(Task).filter(Task.id == task_id).populate_existing().first()
        if not task:
            raise KeyframeReferenceError("TASK_REMOVED")
        assert_task_active(db, task, contract)
        if task.comfyui_prompt_id != contract.get("submit", {}).get("prompt_id"):
            raise KeyframeReferenceError("TASK_SUBMISSION_CHANGED")
        if contract.get("workflow") and (task.workflow_id != contract["workflow"]["id"] or task.workflow_name != contract["workflow"]["name"]):
            raise KeyframeReferenceError("TASK_WORKFLOW_CHANGED")
        if contract.get("binding_resolved"):
            saved = read_contract(task)
            if (json_value(task.reference_images, list) != reference_images(contract)
                    or digest({key: saved.get(key) for key in ("resolved", "binding", "manifest")}) != contract["frozen_binding_hash"]):
                raise KeyframeReferenceError("TASK_BINDING_PROJECTION_CHANGED")
        if contract.get("prompt", {}).get("text") is not None and task.prompt_text != contract["prompt"]["text"]:
            raise KeyframeReferenceError("TASK_PROMPT_CHANGED")
        shot = ShotKeyframeService.load_task_shot(db, task, contract)
        if not shot:
            raise KeyframeReferenceError("TARGET_NOT_FOUND")
        assert_target(shot, task.id, contract)
        return task, shot

    @staticmethod
    def _read_reference_payload(url):
        from PIL import Image
        if not isinstance(url, str) or not url:
            raise KeyframeReferenceError("REFERENCE_FILE_UNAVAILABLE")
        path = url_to_local_path(url) if url else None
        if not path or not Path(path).is_file():
            raise KeyframeReferenceError("REFERENCE_FILE_UNAVAILABLE")
        try:
            payload = Path(path).read_bytes()
            with Image.open(BytesIO(payload)) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise KeyframeReferenceError("MULTIFRAME_REFERENCE_UNSUPPORTED")
                image.verify()
            # Container checks alone do not prove that the pixels can decode.
            with Image.open(BytesIO(payload)) as image:
                image.load()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise KeyframeReferenceError("INVALID_REFERENCE_IMAGE") from exc
        return str(path), payload

    def _previous_keyframe_state_proof(self, db, producers, *, shot_id, frame_index, current_state):
        """Compare independent production inputs, never the mutable image owner pointer."""
        from math import isclose, isfinite

        proof = {"status": "unknown", "state_validated": False,
                 "producer_task_ids": sorted(producer.id for producer in producers), "evidence": []}
        if len(producers) != 1:
            return {**proof, "reason": "producer_not_unique" if producers else "producer_not_found"}
        producer = producers[0]
        if producer.type != "keyframe_image" or producer.shot_id != shot_id or producer.status != "completed":
            return {**proof, "reason": "producer_identity_unverified"}

        def state_fields(state):
            if not isinstance(state, dict):
                return {}, True
            values = {**state}
            if "index" not in values and "plan_keyframe_index" in values:
                values["index"] = values["plan_keyframe_index"]
            fields, invalid = {}, False
            for key in ("description", "time_seconds", "role", "index"):
                value = values.get(key)
                if value is None or value == "":
                    continue
                try:
                    valid = (isinstance(value, str) if key in {"description", "role"}
                             else type(value) is int if key == "index"
                             else type(value) in {int, float} and isfinite(value))
                except OverflowError:
                    valid = False
                if valid:
                    fields[key] = value
                else:
                    invalid = True
            if "index" in state and state.get("plan_keyframe_index") is not None and state["index"] != state["plan_keyframe_index"]:
                invalid = True
            return fields, invalid

        def differences(left, right):
            return sorted(key for key in left.keys() & right.keys()
                          if not (isclose(left[key], right[key], rel_tol=0, abs_tol=0.001 + 1e-9)
                                  if key == "time_seconds" else left[key] == right[key]))

        expected, _ = state_fields(current_state)
        try:
            metadata = json_value(producer.metadata_json, dict)
        except KeyframeReferenceError:
            return {**proof, "status": "unverified_p1", "reason": "invalid_producer_metadata"}
        invalid = False
        if CONTRACT_KEY in metadata:
            proof.update(status="unverified_p1", source="p1_task")
            saved = metadata[CONTRACT_KEY]
            if not isinstance(saved, dict) or type(saved.get("version")) is not int or saved["version"] != CONTRACT_VERSION:
                return {**proof, "reason": "unsupported_producer_contract"}
            if "storage_hash" in saved or "storage_revision" in saved:
                from app.services.keyframe_reference_contract import seal_contract
                try:
                    checked = seal_contract(deepcopy(saved))
                except KeyframeReferenceError:
                    return {**proof, "reason": "invalid_producer_seal"}
                if checked["storage_hash"] != saved.get("storage_hash") or checked["storage_revision"] != saved.get("storage_revision"):
                    return {**proof, "reason": "invalid_producer_seal"}
            # A damaged/new contract must not be replaced with a convenient old log.
            for container, field in (("context", "current_keyframe"), ("target", "current_state")):
                record = saved.get(container)
                if record is None:
                    continue
                if not isinstance(record, dict):
                    invalid = True
                    continue
                identity = record.get("shot") if container == "context" else {"id": record.get("shot_id")}
                if identity is not None and (not isinstance(identity, dict) or identity.get("id") is not None and identity["id"] != shot_id):
                    return {**proof, "reason": "producer_snapshot_shot_mismatch"}
                if field in record:
                    state, malformed = state_fields(record[field])
                    invalid |= malformed
                    proof["evidence"].append({"source": f"{container}.{field}", "state": state})
        else:
            from app.models.llm_log import LLMLog

            proof.update(status="unverified_legacy", source="legacy_llm_log")
            if (not isinstance(producer.prompt_text, str) or not producer.prompt_text.strip()
                    or not producer.created_at or not producer.completed_at or producer.created_at > producer.completed_at):
                return {**proof, "reason": "producer_prompt_or_interval_missing"}
            logs = db.query(LLMLog).filter(
                LLMLog.task_type == "keyframe_image_prompt", LLMLog.status == "success",
                LLMLog.novel_id == producer.novel_id,
                LLMLog.created_at >= producer.created_at, LLMLog.created_at <= producer.completed_at,
            ).order_by(LLMLog.created_at, LLMLog.id).all()
            for log in logs:
                if (producer.chapter_id and log.chapter_id != producer.chapter_id
                        or not isinstance(log.response, str)
                        or self._extract_keyframe_image_prompt(log.response) != producer.prompt_text):
                    continue
                if log.duration is not None and (type(log.duration) not in {int, float} or not isfinite(log.duration) or log.duration < 0
                                                or log.duration > (producer.completed_at - log.created_at).total_seconds()):
                    continue
                try:
                    text = log.user_prompt.strip()
                    payload = json.loads(text if text.startswith("{") else text.split("\n\n", 1)[1])
                except (ValueError, IndexError, AttributeError):
                    continue
                if (not isinstance(payload, dict) or not isinstance(payload.get("shot"), dict)
                        or payload["shot"].get("id") != shot_id):
                    continue
                current = payload.get("current_keyframe")
                if not isinstance(current, dict) or type(current.get("frame_index")) is not int or current["frame_index"] != frame_index:
                    continue
                state, malformed = state_fields(current)
                invalid |= malformed
                proof["evidence"].append({"source": "llm_log", "log_id": log.id, "state": state})

        evidence = proof["evidence"]
        if not evidence:
            return {**proof, "reason": "producer_state_missing"}
        produced, conflicts = {}, []
        for key in ("description", "time_seconds", "role", "index"):
            values = [entry["state"][key] for entry in evidence if key in entry["state"]]
            if not values:
                continue
            produced[key] = values[0]
            if (not isclose(min(values), max(values), rel_tol=0, abs_tol=0.001 + 1e-9) if key == "time_seconds"
                    else any(value != values[0] for value in values)):
                conflicts.append(key)
        if conflicts:
            return {**proof, "reason": "contradictory_producer_states", "conflicting_fields": sorted(conflicts)}
        proof.update(compared_fields=sorted(produced.keys() & expected.keys()),
                     conflicting_fields=sorted({key for entry in evidence for key in differences(entry["state"], expected)}))
        if proof["conflicting_fields"]:
            return {**proof, "status": "mismatch", "reason": "PREVIOUS_PRODUCER_STATE_MISMATCH"}
        required = expected.keys() - ({"role"} if proof["source"] == "legacy_llm_log" else set())
        if invalid or "description" not in produced or "description" not in expected or not required <= produced.keys():
            return {**proof, "reason": "incomplete_producer_state"}
        return {**proof, "status": "verified", "state_validated": True}

    def _resolve_keyframe_reference(self, db, shot, contract):
        intent = contract["planned"]["intent"]
        if intent["selection"] == "none":
            return None, None, None
        index = contract["target"]["frame_index"]
        frames = json_value(shot.keyframes, list)
        previous = frames[index - 1] if index else None
        candidates = []
        if intent["selection"] == "dynamic_auto":
            if previous is not None:
                candidates.append(("PREVIOUS_KEYFRAME", previous.get("image_url"), previous.get("plan_keyframe_index") or index))
            candidates.append(("PRIMARY_STORYBOARD", shot.image_url, None))
        else:
            kind = "CUSTOM_REFERENCE" if intent["selection"] == "custom" else "SAVED_REFERENCE"
            source_index = None
            if intent["selection"] == "fixed_auto":
                if intent["url"] == shot.image_url:
                    kind = "PRIMARY_STORYBOARD"
                elif previous and intent["url"] == previous.get("image_url"):
                    kind, source_index = "PREVIOUS_KEYFRAME", previous.get("plan_keyframe_index") or index
            candidates.append((kind, intent["url"], source_index))
        contract["resolution_attempts"] = []
        for kind, url, source_index in candidates:
            attempt = {"source_kind": kind, "url": url}
            try:
                if kind == "PREVIOUS_KEYFRAME" and intent["selection"] == "dynamic_auto":
                    previous_state = contract["target"].get("previous_state_text") or {}
                    if previous.get("description", "") != previous_state.get("description", ""):
                        raise KeyframeReferenceError("PREVIOUS_STATE_STALE")
                    if not url:
                        raise KeyframeReferenceError("PREVIOUS_IMAGE_NOT_READY")
                path, payload = self._read_reference_payload(url)
                producers = db.query(Task).filter(Task.result_url == url, Task.novel_id == contract["planned"]["novel_id"]).all()
                producer_ids = sorted({producer.id for producer in producers})
                proof = {"status": "not_applicable", "state_validated": False, "producer_task_ids": producer_ids,
                         "reason": "primary_storyboard" if kind == "PRIMARY_STORYBOARD" else "explicit_reference"}
                if kind == "PREVIOUS_KEYFRAME":
                    proof = self._previous_keyframe_state_proof(
                        db, producers, shot_id=shot.id, frame_index=index - 1,
                        current_state=contract["target"].get("previous_state_text") or {},
                    )
                attempt["state_proof"] = proof
                if intent["selection"] == "dynamic_auto" and proof["status"] == "mismatch":
                    raise KeyframeReferenceError("PREVIOUS_PRODUCER_STATE_MISMATCH")
            except KeyframeReferenceError as exc:
                contract["resolution_attempts"].append({**attempt, "reason": exc.code})
                if intent["selection"] != "dynamic_auto" or kind != "PREVIOUS_KEYFRAME":
                    raise
                contract["fallback"] = {"from": kind, "to": "PRIMARY_STORYBOARD", "reason": exc.code}
                continue
            label = {"PRIMARY_STORYBOARD": "主分镜图", "PREVIOUS_KEYFRAME": f"上一关键帧 KF{source_index}",
                     "CUSTOM_REFERENCE": "自定义参考图", "SAVED_REFERENCE": "已固定参考图"}[kind]
            resolved = {"source_kind": kind, "label": label, "url": url, "source_keyframe_index": source_index,
                         "producer_task_id": producer_ids[0] if len(producer_ids) == 1 else None,
                        "sha256": digest(payload), "size": len(payload), "state_proof": proof}
            contract["resolution_attempts"].append({**attempt, "accepted": True})
            return resolved, payload, path
        raise KeyframeReferenceError("REFERENCE_UNAVAILABLE")

    @staticmethod
    def _reference_call(contract, *, error=None):
        prompt = contract.get("prompt") or {}
        response = prompt.get("raw_response") if prompt.get("llm_invoked") else ""
        if response is not None and not isinstance(response, str):
            response = json.dumps(response, ensure_ascii=False)
        return {"step": "09", "task_type": "keyframe_image_prompt",
                "prompt_template_name": contract.get("template", {}).get("name"),
                "status": "error" if error else "success", "error_message": str(error or ""),
                "input_summary": f"KF {contract['target']['current_state']['index']}",
                "response": response or "", "final_prompt": None if error else prompt.get("text"),
                "workflow_type": contract.get("workflow", {}).get("type"),
                "workflow_name": contract.get("workflow", {}).get("name"),
                "reference_images": reference_images(contract) if contract.get("binding_resolved") else [],
                "parsed_result": {"contract_version": CONTRACT_VERSION, "attempt_id": contract["attempt_id"],
                                  "phase": contract["phase"], "manifest": contract.get("manifest", []),
                                  "resolved": contract.get("resolved"), "fallback": contract.get("fallback"),
                                  "binding_hash": contract.get("frozen_binding_hash"),
                                  "llm_invoked": bool(prompt.get("llm_invoked")), "validation": prompt.get("validation"),
                                  "cache_fingerprint": prompt.get("cache_fingerprint")}}

    def _finish_reference_error(self, db, task_id, contract, error, *, local_url=None):
        if not contract:
            return
        if contract.get("execution_purpose") == "benchmark" and any(isinstance(item, Shot) for item in (*db.new, *db.dirty, *db.deleted)):
            return
        contract["failure"] = {"stage": contract["phase"], "code": getattr(error, "code", type(error).__name__), "message": str(error)}
        if local_url:
            contract["result"] = {"url": local_url, "attachment": "detached", "reason": contract["failure"]["code"]}
        try:
            task, _ = self._check_reference_task(db, task_id, contract)
            patch_target(db, task_id, contract, ai_call=self._reference_call(contract, error=error))
        except KeyframeReferenceError:
            pass
        contract["phase"] = "failed"
        try:
            fields = {"status": "failed", "error_message": str(error), "current_step": "#09 参考合同失败", "completed_at": datetime.utcnow()}
            if local_url:
                fields["result_url"] = local_url
            current = db.query(Task).filter(Task.id == task_id).populate_existing().first()
            if current and contract.get("submit", {}).get("prompt_id") and current.comfyui_prompt_id is None:
                fields["comfyui_prompt_id"] = contract["submit"]["prompt_id"]
                fields["workflow_json"] = json.dumps(contract["prepared_workflow"], ensure_ascii=False)
            store_contract(db, task_id, contract, terminal=True, **fields)
        except KeyframeReferenceError as conflict:
            record_contract_observation(db, task_id, contract, conflict, artifact_url=local_url)

    async def _wait_for_reference_result(self, db, task_id, contract, client):
        loop = asyncio.get_running_loop()
        deadline, missing_since = loop.time() + 7200, None
        while loop.time() < deadline:
            self._check_reference_task(db, task_id, contract)
            state = await client.get_prompt_state(contract["submit"]["prompt_id"])
            self._check_reference_task(db, task_id, contract)
            if state.get("state") == "completed":
                return select_keyframe_output(state.get("history"), contract, client.base_url)
            if state.get("state") == "error":
                raise KeyframeReferenceError("GENERATION_FAILED", state.get("message", ""))
            if state.get("state") == "missing":
                missing_since = missing_since if missing_since is not None else loop.time()
                if loop.time() - missing_since >= 30:
                    raise KeyframeReferenceError("SUBMITTED_JOB_MISSING")
            else:
                missing_since = None
            await asyncio.sleep(2)
        raise KeyframeReferenceError("GENERATION_TIMEOUT")

    async def generate_keyframe_descriptions(
        self,
        db: Session,
        shot_id: str,
        count: int = 3
    ) -> Tuple[bool, List[dict], str]:
        """生成关键帧描述

        使用 LLM 根据分镜描述生成关键帧描述列表。
        支持使用小说级别配置的关键帧描述提示词模板。

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            count: 要生成的关键帧数量

        Returns:
            (success, keyframes, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, [], f"分镜 {shot_id} 不存在"

        # 获取小说信息以获取模板配置
        novel_id = self._get_novel_id(db, shot)
        novel = db.query(Novel).filter(Novel.id == novel_id).first() if novel_id else None

        # 构建提示词
        template = self._get_keyframe_template(db, novel)
        prompt = self._build_keyframe_prompt(db, shot, count, novel, template)

        try:
            # 调用 LLM 生成
            response = await self.llm_service.chat_completion(
                system_prompt="你是一个专业的视频分镜师，擅长分析镜头并拆分关键帧。请根据镜头描述生成关键帧的详细描述。",
                user_content=prompt,
                temperature=0.7,
                response_format="json_object",
                task_type="keyframe_description",
                prompt_template_name=template.name if template else "默认关键帧描述提示词",
                novel_id=novel_id,
                chapter_id=shot.chapter_id
            )

            content = response.get("content", "")

            # 解析 JSON
            # 尝试提取 JSON 数组
            import re
            json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)

            keyframes = json.loads(content)

            # 验证格式
            validated_keyframes = []
            for i, kf in enumerate(keyframes[:count]):
                validated_keyframes.append({
                    "frame_index": kf.get("frame_index", i),
                    "description": kf.get("description", ""),
                    "image_url": None,
                    "image_task_id": None,
                    "reference_image_url": None,
                    "reference_mode": "auto_select"
                })

            # 更新分镜的关键帧数据
            shot_repo.update(shot, keyframes=validated_keyframes)

            return True, validated_keyframes, f"成功生成 {len(validated_keyframes)} 个关键帧描述"

        except json.JSONDecodeError as e:
            return False, [], f"解析关键帧描述失败：{str(e)}"
        except Exception as e:
            return False, [], f"生成关键帧描述失败：{str(e)}"

    def _get_keyframe_template(self, db: Session, novel: Optional[Novel]) -> Optional[PromptTemplate]:
        template = None
        if novel and novel.keyframe_description_prompt_template_id:
            template = db.query(PromptTemplate).filter(
                PromptTemplate.id == novel.keyframe_description_prompt_template_id
            ).first()

        if not template:
            template = db.query(PromptTemplate).filter(
                PromptTemplate.type == "keyframe_description",
                PromptTemplate.is_system == True,
                PromptTemplate.is_active == True
            ).first()
        return template

    def _build_keyframe_prompt(
        self,
        db: Session,
        shot: Shot,
        count: int,
        novel: Optional[Novel],
        template: Optional[PromptTemplate] = None
    ) -> str:
        """构建关键帧描述生成提示词

        优先使用小说配置的关键帧描述提示词模板。

        Args:
            db: 数据库会话
            shot: 分镜对象
            count: 关键帧数量
            novel: 小说对象

        Returns:
            构建好的提示词
        """
        if not template:
            template = self._get_keyframe_template(db, novel)

        # 构建视频描述部分
        video_description = f"视频描述：{shot.video_description}" if shot.video_description else ""

        if template:
            # 使用模板生成提示词
            prompt = template.template.format(
                count=count,
                shot_description=shot.description,
                video_description=video_description
            )
        else:
            # 使用默认硬编码提示词
            prompt = f"""请根据以下分镜描述，生成 {count} 个关键帧描述。

分镜描述：
{shot.description}

{video_description}

要求：
1. 每个关键帧描述应该是该分镜中一个重要的画面瞬间
2. 描述应该详细且具有画面感，包含人物动作、表情、场景细节等
3. 关键帧应该按照时间顺序排列，展示分镜的动态过程
4. 每个描述控制在50-100字

请直接返回JSON数组格式，每个元素包含：
- frame_index: 帧序号（从0开始）
- description: 关键帧描述

示例格式：
[
  {{"frame_index": 0, "description": "第1个关键帧的描述"}},
  {{"frame_index": 1, "description": "第2个关键帧的描述"}}
]"""

        return prompt

    async def generate_keyframe_image(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        workflow_id: Optional[str] = None,
        skip_llm_when_prompt_exists: bool = False,
        parent_task_id: Optional[str] = None,
        batch_order: Optional[int] = None,
        execution_purpose: str = "production",
    ) -> Tuple[bool, Optional[str], str]:
        """生成关键帧图片

        使用 ComfyUI 工作流生成关键帧图片。

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号
            workflow_id: 指定的工作流 ID

        Returns:
            (success, task_id, message) 元组
        """
        if execution_purpose not in ("production", "benchmark"):
            return False, None, "INVALID_EXECUTION_PURPOSE"
        if execution_purpose == "benchmark" and any(isinstance(item, Shot) for item in (*db.new, *db.dirty, *db.deleted)):
            return False, None, "PRODUCTION_SHOT_DIRTY"
        if parent_task_id:
            parent = db.query(Task).filter(Task.id == parent_task_id).populate_existing().first()
            if (not parent or parent.status not in {"pending", "running"}
                    or json_value(parent.metadata_json, dict).get("execution_purpose", "production") != execution_purpose):
                return False, None, "PARENT_EXECUTION_PURPOSE_MISMATCH"
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        try:
            target = snapshot_target(shot, frame_index)
        except KeyframeReferenceError as exc:
            return False, None, str(exc)
        novel_id = self._get_novel_id(db, shot)
        if not novel_id:
            return False, None, "无法获取小说信息"
        planned = {"intent": target["reference_intent"], "novel_id": novel_id, "parent_task_id": parent_task_id,
                   "requested_workflow_id": workflow_id, "skip_llm_when_prompt_exists": bool(skip_llm_when_prompt_exists),
                   "batch_order": batch_order}

        active_tasks = db.query(Task).filter(
            Task.type == "keyframe_image",
            Task.shot_id == shot_id,
            Task.name == f"生成关键帧图片: {shot_id}-{frame_index}",
            Task.status.in_(["pending", "running"]),
        ).order_by(Task.created_at.desc()).all()
        existing_task = next((item for item in active_tasks
                              if json_value(item.metadata_json, dict).get("execution_purpose", "production") == execution_purpose), None)
        if existing_task:
            existing_contract = read_contract(existing_task)
            if not existing_contract or existing_contract.get("planned") != planned:
                return False, None, "该关键帧已有不同意图或旧版本任务，请等待完成或取消后重新生成。"
            try:
                assert_target(self.load_task_shot(db, existing_task, existing_contract), existing_task.id, existing_contract)
            except KeyframeReferenceError:
                return False, None, "该关键帧已有任务，但目标已修改，请等待或取消原任务。"
            return True, existing_task.id, "已复用相同意图的现有任务，当前任务的参考绑定不会改变。"

        # 创建任务
        task = Task(
            id=str(uuid.uuid4()),
            type="keyframe_image",
            name=f"生成关键帧图片: {shot_id}-{frame_index}",
            description=f"为分镜 {shot.index} 的第 {frame_index} 帧生成图片",
            status="pending",
            shot_id=shot_id,
            novel_id=novel_id,
            chapter_id=shot.chapter_id,
            workflow_id=workflow_id,
            parent_task_id=parent_task_id,
            batch_order=batch_order,
        )
        contract = {"version": CONTRACT_VERSION, "attempt_id": uuid.uuid4().hex, "phase": "planned",
                    "planned": planned, "target": target, "draft": deepcopy(target["draft"]),
                    "binding_resolved": False, "resolved": None, "binding": None,
                    "prompt": {"llm_invoked": False}, "submit": {"state": "not_submitted"}}
        from app.services.video_director_ai import build_visual_identity_context
        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        visual_style, _ = get_style(db, novel, "character")
        contract["context"] = {"visual_identity": build_visual_identity_context(
            db, novel_id, target["shot_state"]["characters"], target["shot_state"]["props"], visual_style,
        )}
        task_metadata = {"execution_purpose": execution_purpose}
        if execution_purpose == "benchmark":
            from app.services.task_execution import create_execution_metadata
            task_metadata = create_execution_metadata(shot, purpose=execution_purpose, request={
                "frame_index": frame_index, "workflow_id": workflow_id,
                "skip_llm_when_prompt_exists": bool(skip_llm_when_prompt_exists),
            })
            contract.update(execution_purpose="benchmark", execution_attempt_id=task_metadata["execution"]["attempt_id"])
        seal_contract(contract)
        task_metadata[CONTRACT_KEY] = contract
        task.metadata_json = json.dumps(task_metadata, ensure_ascii=False)
        db.add(task)
        try:
            db.flush()
            patch_target(db, task.id, contract, claiming=True)
        except Exception as exc:
            db.rollback()
            return False, None, str(exc)
        new_task_id = task.id

        # 加入关键帧图片专用串行 worker，避免多个关键帧同时占用 ComfyUI。
        from app.core.database import SessionLocal

        async def run_background_task():
            db_bg = SessionLocal()
            try:
                await self._generate_keyframe_image_task(db_bg, new_task_id, shot_id, frame_index, workflow_id, skip_llm_when_prompt_exists)
            except Exception:
                # The worker records failure without resurrecting terminal tasks.
                pass
            finally:
                db_bg.close()

        worker_manager.worker("keyframe_image").enqueue(run_background_task)

        return True, new_task_id, "关键帧图片生成任务已创建"

    async def _generate_keyframe_image_task(
        self,
        db: Session,
        task_id: str,
        shot_id: str,
        frame_index: int,
        workflow_id: Optional[str] = None,
        skip_llm_when_prompt_exists: bool = False,
    ):
        """Resolve/bind once; the LLM, graph and publication share that contract."""
        task = db.query(Task).filter(Task.id == task_id).populate_existing().first()
        if not task or task.status != "pending":
            return
        contract = read_contract(task)
        if not contract:
            task.status, task.error_message, task.completed_at = "failed", "#09 LEGACY_CONTRACT_UNVERIFIED，请重新发起生成。", datetime.utcnow()
            db.commit()
            return
        local_url, queue_started = None, False
        try:
            if contract["phase"] != "planned" or task.comfyui_prompt_id:
                raise KeyframeReferenceError("ATTEMPT_ALREADY_STARTED")
            if (shot_id != task.shot_id or frame_index != contract["target"]["frame_index"]
                    or workflow_id != contract["planned"]["requested_workflow_id"]
                    or bool(skip_llm_when_prompt_exists) != contract["planned"]["skip_llm_when_prompt_exists"]):
                raise KeyframeReferenceError("QUEUED_INTENT_MISMATCH")
            store_contract(db, task_id, contract, statuses=("pending",), status="running", started_at=datetime.utcnow(), current_step="解析 #09 参考合同...")
            task, shot = self._check_reference_task(db, task_id, contract)
            novel = db.query(Novel).filter(Novel.id == contract["planned"]["novel_id"]).first()
            if not novel:
                raise KeyframeReferenceError("NOVEL_NOT_FOUND")
            requested = contract["planned"]["requested_workflow_id"]
            selection = "explicit" if requested else "default_keyframe"
            workflow = db.query(Workflow).filter(Workflow.id == requested).first() if requested else db.query(Workflow).filter(Workflow.type == "keyframe_image", Workflow.is_active == True).first()
            if workflow is None and not requested:
                selection = "fallback_shot"
                workflow = db.query(Workflow).filter(Workflow.type == "shot", Workflow.is_active == True).first()
            if workflow is None:
                raise KeyframeReferenceError("WORKFLOW_NOT_FOUND")
            mapping_source, graph_source = workflow.node_mapping, workflow.workflow_json
            contract["workflow"] = {"id": workflow.id, "name": workflow.name, "type": workflow.type,
                                    "selection": selection, "mapping_source_hash": digest(mapping_source)}
            contract["phase"] = "workflow_selected"
            store_contract(db, task_id, contract, workflow_id=workflow.id, workflow_name=workflow.name)
            mapping = normalize_keyframe_mapping(json_value(mapping_source, dict))
            workflow_data = json_value(graph_source, dict)
            template = self._get_keyframe_image_prompt_template(db, novel)
            if not template or template.type != "keyframe_image_prompt" or not isinstance(template.template, str) or not template.template.strip():
                raise KeyframeReferenceError("KEYFRAME_TEMPLATE_UNAVAILABLE")
            contract["template"] = {"id": template.id, "name": template.name, "type": template.type,
                                    "text": template.template, "hash": digest(template.template)}
            contract["workflow"].update(node_mapping=mapping, template_graph_hash=digest(workflow_data))
            service = ComfyUIService()
            client = frozen_keyframe_client(service.client.base_url)
            contract["endpoint"] = client.base_url
            contract["client_id"] = client.client_id
            aspect_ratio = novel.aspect_ratio or "16:9"
            visual_style, _ = get_style(db, novel, "character")
            configured_tokens = getattr(self.llm_service, "max_tokens", None)
            tokens = configured_tokens if configured_tokens is not None else 2500
            normalize_tokens = getattr(self.llm_service, "_normalize_max_tokens", None)
            tokens = normalize_tokens(tokens) if callable(normalize_tokens) else tokens
            configured_temperature = getattr(self.llm_service, "temperature", None)
            contract["llm_config"] = {"provider": getattr(self.llm_service, "provider", None), "model": getattr(self.llm_service, "model", None),
                                      "max_tokens": tokens, "temperature": float(configured_temperature) if configured_temperature else 0.3}
            target = contract["target"]
            # Only new admissions carry these facts. Never retrofit a persisted request.
            visual_identity = contract.get("context", {}).get("visual_identity")
            if visual_identity is not None:
                visual_style = visual_identity["visual_style"]
            contract["context"] = {**contract.get("context", {}), "shot": {"id": shot.id, "index": shot.index, **target["shot_state"]},
                                   "current_keyframe": {**target["current_state"], "frame_index": frame_index},
                                   "previous_keyframe_state_text": target["previous_state_text"],
                                   "visual_style": visual_style, "aspect_ratio": aspect_ratio}
            if visual_identity is not None:
                contract["context"]["shot"]["characters"] = visual_identity["characters"]
            contract["resolved"], payload, path = self._resolve_keyframe_reference(db, shot, contract)
            if contract.get("execution_purpose") != "benchmark" and contract["resolved"]:
                producer_ids = contract["resolved"].get("state_proof", {}).get("producer_task_ids", [])
                for producer in db.query(Task).filter(Task.id.in_(producer_ids)).all():
                    try:
                        producer_metadata = json_value(producer.metadata_json, dict)
                    except KeyframeReferenceError:
                        continue
                    if producer_metadata.get("execution_purpose") == "benchmark":
                        raise KeyframeReferenceError("BENCHMARK_REFERENCE_REQUIRES_ADOPTION")
            count = int(contract["resolved"] is not None)
            graph = service.builder.build_shot_workflow(prompt="", workflow_json=json.dumps(workflow_data), node_mapping=mapping, aspect_ratio=aspect_ratio, style="")
            graph = prepare_keyframe_graph(graph, mapping, has_reference=bool(count))
            inspection = validate_keyframe_graph(graph, mapping, reference_count=count)
            contract["workflow"].update(family=inspection["family"], output_node_id=inspection["save_image_node_id"],
                                        contract_hash=stable_graph_fingerprint(graph, mapping))
            contract["phase"] = "resolved"
            store_contract(db, task_id, contract, workflow_id=contract["workflow"]["id"], workflow_name=contract["workflow"]["name"], reference_images="[]")
            if count:
                upload_name = f"kf-{task_id}-{contract['attempt_id']}-ref1{Path(path).suffix or '.png'}"
                receipt = await client.upload_image(path, upload_name=upload_name, payload=payload)
                self._check_reference_task(db, task_id, contract)
                if not receipt.get("success"):
                    raise KeyframeReferenceError("REFERENCE_UPLOAD_FAILED", receipt.get("message", ""))
                if (receipt.get("payload_sha256") != contract["resolved"]["sha256"] or receipt.get("payload_size") != len(payload)
                        or not isinstance(receipt.get("filename"), str) or not receipt["filename"]):
                    raise KeyframeReferenceError("UPLOAD_RECEIPT_MISMATCH")
                graph[inspection["reference_node_id"]]["inputs"]["image"] = receipt["filename"]
                contract["binding"] = {"picture_index": 1, "node_id": inspection["reference_node_id"], "field": "image", "output_slot": 0,
                                       "uploaded_filename": receipt["filename"], "payload_sha256": receipt["payload_sha256"],
                                       "payload_size": receipt["payload_size"]}
            contract["binding_resolved"] = True
            contract["manifest"] = self._build_keyframe_reference_manifest(contract)
            frozen = {"resolved": contract["resolved"], "binding": contract["binding"], "manifest": contract["manifest"]}
            contract["frozen_binding_hash"] = digest(frozen)
            contract["phase"] = "frozen"
            contract["prompt"]["cache_fingerprint"] = reference_cache_fingerprint(contract)
            store_contract(db, task_id, contract, reference_images=json.dumps(reference_images(contract), ensure_ascii=False), current_step="#09 参考绑定已冻结")
            self._check_reference_task(db, task_id, contract)
            if contract["planned"]["skip_llm_when_prompt_exists"]:
                prompt = self._get_reusable_keyframe_prompt(db, task, contract, graph=graph)
                reused_id = contract["prompt"].get("reused_from_task_id")
                if reused_id and contract.get("execution_purpose") != "benchmark":
                    reused = db.query(Task).filter(Task.id == reused_id).first()
                    if reused and json_value(reused.metadata_json, dict).get("execution_purpose") == "benchmark":
                        raise KeyframeReferenceError("BENCHMARK_PROMPT_REQUIRES_ADOPTION")
            else:
                prompt = await self._build_qwen_keyframe_prompt(db, novel, shot, task, contract)
            self._check_reference_task(db, task_id, contract)
            source_kind = contract["resolved"]["source_kind"] if count else "NONE"
            contract["prompt"]["validation"] = validate_reference_prompt(prompt, source_kind)
            service.builder._set_prompt(graph, inspection["prompt_node_id"], prompt)
            filename = contract["binding"]["uploaded_filename"] if count else None
            final_inspection = validate_keyframe_graph(graph, mapping, reference_count=count, expected_filename=filename, expected_prompt=prompt)
            if digest({"resolved": contract["resolved"], "binding": contract["binding"], "manifest": reference_manifest(contract)}) != contract["frozen_binding_hash"]:
                raise KeyframeReferenceError("FROZEN_BINDING_CHANGED")
            contract["phase"] = "prompt_publish"
            staged = deepcopy(contract)
            staged["validation"] = {"passed": True, "graph": final_inspection}
            staged["prompt"].update(text=prompt, text_hash=digest(prompt))
            staged["prepared_workflow"] = deepcopy(graph)
            staged["phase"] = "prompt_ready"
            try:
                patch_target(db, task_id, staged, prompt=prompt, ai_call=self._reference_call(staged))
            except Exception:
                # A rejected publication must not turn an uncommitted candidate
                # into an expected Task.prompt_text projection during failure.
                contract["prompt"]["unpublished_candidate"] = {"text": prompt, "text_hash": digest(prompt),
                                                                "validation": contract["prompt"]["validation"]}
                raise
            contract = staged
            self._check_reference_task(db, task_id, contract)
            contract["submit"] = {"state": "attempted", "graph_hash": digest(graph)}
            contract["phase"] = "submitting"
            store_contract(db, task_id, contract, current_step="提交 #09 ComfyUI 任务...")
            task, _ = self._check_reference_task(db, task_id, contract)
            validate_frozen_contract(contract, task)
            validate_keyframe_graph(graph, mapping, reference_count=count, expected_filename=filename, expected_prompt=prompt)
            if digest(graph) != contract["submit"]["graph_hash"]:
                raise KeyframeReferenceError("PREPARED_GRAPH_CHANGED")
            queue_started = True
            queue_result = await client.queue_prompt(graph)
            prompt_id = queue_result.get("prompt_id")
            if not queue_result.get("success") or not isinstance(prompt_id, str) or not prompt_id.strip():
                contract["submit"]["state"] = "unknown"
                raise KeyframeReferenceError("SUBMISSION_UNCONFIRMED", queue_result.get("error", ""))
            contract["submit"].update(state="submitted", prompt_id=prompt_id)
            contract["phase"] = "submitted"
            store_contract(db, task_id, contract, comfyui_prompt_id=prompt_id, workflow_json=json.dumps(graph, ensure_ascii=False), current_step="ComfyUI 关键帧生成中")
            remote_url = await self._wait_for_reference_result(db, task_id, contract, client)
            download_options = {}
            if contract.get("execution_purpose") == "benchmark":
                from app.services.task_execution import artifact_directory
                download_options["destination"] = artifact_directory(task) / f"image-{uuid.uuid4().hex}.png"
            local_path = await file_storage.download_image(url=remote_url, novel_id=contract["planned"]["novel_id"],
                                                         character_name=f"keyframe_{frame_index}", image_type="keyframe", chapter_id=contract["target"]["chapter_id"], **download_options)
            if not local_path:
                raise KeyframeReferenceError("IMAGE_DOWNLOAD_FAILED")
            if download_options and Path(local_path).resolve() != download_options["destination"].resolve():
                raise KeyframeReferenceError("IMAGE_STORAGE_LOCATION_INVALID")
            local_url = local_path_to_url(local_path)
            if not local_url:
                raise KeyframeReferenceError("IMAGE_STORAGE_LOCATION_INVALID")
            self._read_reference_payload(local_url)
            self._check_reference_task(db, task_id, contract)
            patch_target(db, task_id, contract, image_url=local_url)
        except asyncio.CancelledError as exc:
            if not contract["submit"].get("prompt_id"):
                contract["submit"]["state"] = "unknown" if queue_started else "not_submitted"
            self._finish_reference_error(db, task_id, contract, KeyframeReferenceError("WORKER_INTERRUPTED"), local_url=local_url)
            raise
        except Exception as exc:
            if not contract["submit"].get("prompt_id"):
                contract["submit"]["state"] = "unknown" if queue_started else "not_submitted"
            self._finish_reference_error(db, task_id, contract, exc, local_url=local_url)
            raise

    async def recover_benchmark_image(self, db, task, prompt_history):
        """Recover acknowledged #09 output into Task state only; no generation."""
        task_id = task.id
        contract = read_contract(task)
        if not contract or contract.get("execution_purpose") != "benchmark":
            return False
        local_url = None
        try:
            task = db.query(Task).filter(Task.id == task_id).populate_existing().first()
            if not task or task.status not in {"running", "completed"}:
                return False
            saved = read_contract(task)
            if not saved or saved.get("attempt_id") != contract["attempt_id"]:
                raise KeyframeReferenceError("TASK_REPLACED")
            validate_frozen_contract(saved, task, require_submitted=True)
            self.load_task_shot(db, task, saved)
            if task.status == "completed":
                return bool(saved.get("result", {}).get("attachment") == "archived"
                            and saved["result"].get("url") == task.result_url and task.result_url)
            task, _ = self._check_reference_task(db, task_id, contract)
            client = frozen_keyframe_client(contract["endpoint"])
            remote_url = select_keyframe_output(prompt_history, contract, client.base_url)
            from app.services.task_execution import artifact_directory
            destination = artifact_directory(task) / f"image-{uuid.uuid4().hex}.png"
            local_path = await file_storage.download_image(
                url=remote_url, novel_id=task.novel_id, character_name=f"keyframe_{contract['target']['frame_index']}",
                image_type="keyframe", chapter_id=task.chapter_id,
                destination=destination,
            )
            if not local_path:
                raise KeyframeReferenceError("IMAGE_DOWNLOAD_FAILED")
            if Path(local_path).resolve() != destination.resolve():
                raise KeyframeReferenceError("IMAGE_STORAGE_LOCATION_INVALID")
            local_url = local_path_to_url(local_path)
            self._read_reference_payload(local_url)
            self._check_reference_task(db, task_id, contract)
            return patch_target(db, task_id, contract, image_url=local_url)
        except Exception as exc:
            self._finish_reference_error(db, task_id, contract, exc, local_url=local_url)
            return False

    async def upload_keyframe_image(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        file_content: bytes,
        filename: str
    ) -> Tuple[bool, Optional[str], str]:
        """上传关键帧图片

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号
            file_content: 文件内容
            filename: 文件名

        Returns:
            (success, image_url, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        # 通过 chapter 获取 novel_id
        chapter = db.query(Chapter).filter(Chapter.id == shot.chapter_id).first()
        if not chapter:
            return False, None, f"章节 {shot.chapter_id} 不存在"

        novel_id = chapter.novel_id

        try:
            # 保存图片到本地存储
            file_ext = os.path.splitext(filename)[1] or ".png"
            save_dir = file_storage.base_dir / novel_id / "keyframes" / shot_id / str(frame_index)
            save_dir.mkdir(parents=True, exist_ok=True)

            file_name = f"{uuid.uuid4()}{file_ext}"
            full_path = save_dir / file_name

            with open(full_path, "wb") as f:
                f.write(file_content)

            # 构建本地 URL
            relative_path = str(full_path.relative_to(file_storage.base_dir)).replace("\\", "/")
            image_url = f"/api/files/{relative_path}"

            # 更新关键帧数据
            keyframes[frame_index]["image_url"] = image_url
            self._sync_video_director_keyframe_image(shot, keyframes[frame_index], image_url)
            shot_repo.update(shot, keyframes=keyframes)

            return True, image_url, "关键帧图片上传成功"

        except Exception as e:
            return False, None, f"上传失败：{str(e)}"

    async def replace_keyframe_image(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        image_url: str,
    ) -> Tuple[bool, Optional[str], str]:
        """用已有本地图片 URL 替换关键帧图片。"""
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)
        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        try:
            keyframes[frame_index]["image_url"] = image_url
            self._sync_video_director_keyframe_image(shot, keyframes[frame_index], image_url)
            shot_repo.update(shot, keyframes=keyframes)
            return True, image_url, "关键帧图片已替换"
        except Exception as e:
            return False, None, f"替换失败：{str(e)}"

    async def upload_reference_image(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        file_content: bytes,
        filename: str
    ) -> Tuple[bool, Optional[str], str]:
        """上传参考图

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号
            file_content: 文件内容
            filename: 文件名

        Returns:
            (success, reference_url, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        # 通过 chapter 获取 novel_id
        chapter = db.query(Chapter).filter(Chapter.id == shot.chapter_id).first()
        if not chapter:
            return False, None, f"章节 {shot.chapter_id} 不存在"

        novel_id = chapter.novel_id

        try:
            # 保存参考图到本地存储
            file_ext = os.path.splitext(filename)[1] or ".png"
            save_dir = file_storage.base_dir / novel_id / "keyframes" / shot_id / str(frame_index) / "reference"
            save_dir.mkdir(parents=True, exist_ok=True)

            file_name = f"{uuid.uuid4()}{file_ext}"
            full_path = save_dir / file_name

            with open(full_path, "wb") as f:
                f.write(file_content)

            # 构建本地 URL
            relative_path = str(full_path.relative_to(file_storage.base_dir)).replace("\\", "/")
            reference_url = f"/api/files/{relative_path}"

            # 更新关键帧数据：同时保存 reference_image_url 和 reference_mode
            keyframes[frame_index]["reference_image_url"] = reference_url
            keyframes[frame_index]["reference_mode"] = "custom"
            shot_repo.update(shot, keyframes=keyframes)

            return True, reference_url, "参考图上传成功"

        except Exception as e:
            return False, None, f"上传失败：{str(e)}"

    async def set_reference_image(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        mode: str = "auto_select",
        reference_url: Optional[str] = None
    ) -> Tuple[bool, Optional[str], str]:
        """设置参考图

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号
            mode: 模式 ("auto_select" | "custom" | "none")
            reference_url: 自定义参考图 URL（mode 为 "custom" 时使用）

        Returns:
            (success, reference_url, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        final_reference_url = None

        if mode == "none":
            # 不使用参考图
            final_reference_url = None

        elif mode == "custom":
            # 使用自定义参考图
            final_reference_url = reference_url

        elif mode == "auto_select":
            # 自动选择参考图
            final_reference_url = self._auto_select_reference_image(
                shot, keyframes, frame_index
            )

        # 更新关键帧数据：同时保存 reference_image_url 和 reference_mode
        keyframes[frame_index]["reference_image_url"] = final_reference_url
        keyframes[frame_index]["reference_mode"] = mode
        shot_repo.update(shot, keyframes=keyframes)

        return True, final_reference_url, "参考图设置成功"

    def _auto_select_reference_image(
        self,
        shot: Shot,
        keyframes: List[dict],
        frame_index: int
    ) -> Optional[str]:
        """自动选择参考图

        选择优先级：
        1. 如果有上一关键帧且已生成图片，使用上一关键帧图片
        2. 否则使用分镜图

        Args:
            shot: 分镜对象
            keyframes: 关键帧列表
            frame_index: 当前关键帧序号

        Returns:
            参考图 URL 或 None
        """
        # 检查是否有上一关键帧
        if frame_index > 0:
            prev_keyframe = keyframes[frame_index - 1]
            prev_image_url = prev_keyframe.get("image_url")
            if prev_image_url:
                return prev_image_url

        # 使用分镜图
        if shot.image_url:
            return shot.image_url

        return None

    def _get_auto_reference_image_with_label(
        self,
        shot: Shot,
        keyframes: List[dict],
        frame_index: int,
    ) -> Tuple[Optional[str], Optional[str]]:
        if frame_index > 0:
            prev_keyframe = keyframes[frame_index - 1]
            prev_image_url = prev_keyframe.get("image_url")
            if prev_image_url:
                return prev_image_url, f"上一关键帧 KF{prev_keyframe.get('plan_keyframe_index') or frame_index}"
        if shot.image_url:
            return shot.image_url, "主分镜图"
        return None, None

    async def add_keyframe(
        self,
        db: Session,
        shot_id: str,
        description: str,
        insert_index: Optional[int] = None
    ) -> Tuple[bool, Optional[dict], str]:
        """添加关键帧

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            description: 关键帧描述
            insert_index: 插入位置（如果为 None 则追加到最后）

        Returns:
            (success, keyframe, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []

        new_keyframe = {
            "frame_index": 0,
            "description": description,
            "image_url": None,
            "image_task_id": None,
            "reference_image_url": None
        }

        if insert_index is not None and 0 <= insert_index <= len(keyframes):
            # 插入到指定位置
            keyframes.insert(insert_index, new_keyframe)
        else:
            # 追加到最后
            keyframes.append(new_keyframe)

        # 更新 frame_index
        for i, kf in enumerate(keyframes):
            kf["frame_index"] = i

        shot_repo.update(shot, keyframes=keyframes)

        return True, keyframes[new_keyframe["frame_index"]], "关键帧添加成功"

    async def update_keyframe(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        description: Optional[str] = None
    ) -> Tuple[bool, Optional[dict], str]:
        """更新关键帧

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号
            description: 新的关键帧描述

        Returns:
            (success, keyframe, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        if description is not None:
            keyframes[frame_index]["description"] = description

        shot_repo.update(shot, keyframes=keyframes)

        return True, keyframes[frame_index], "关键帧更新成功"

    async def delete_keyframe(
        self,
        db: Session,
        shot_id: str,
        frame_index: int
    ) -> Tuple[bool, None, str]:
        """删除关键帧

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号

        Returns:
            (success, None, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        # 删除关键帧
        del keyframes[frame_index]

        # 更新 frame_index
        for i, kf in enumerate(keyframes):
            kf["frame_index"] = i

        shot_repo.update(shot, keyframes=keyframes)

        return True, None, "关键帧删除成功"
