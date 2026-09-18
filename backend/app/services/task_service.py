"""
任务服务层

封装任务相关的业务逻辑和后台任务
"""
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import get_settings
from app.utils.time_utils import format_datetime
from app.models.task import Task
from app.models.novel import Novel
from app.models.workflow import Workflow
from app.models.llm_log import LLMLog
from app.repositories import TaskRepository, WorkflowRepository
from app.repositories.shot_repository import ShotRepository
from app.repositories.character_repository import CharacterRepository
from app.repositories.scene_repository import SceneRepository
from app.repositories.prop_repository import PropRepository
from app.repositories.prompt_template import PromptTemplateRepository
from app.services.comfyui import ComfyUIService
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.services.file_storage import file_storage
from app.services.keyframe_reference_contract import (
    KeyframeReferenceError, assert_task_active, assert_target,
    frozen_keyframe_client, patch_target, read_contract, record_contract_observation,
    select_keyframe_output, store_contract, validate_frozen_contract,
)
from app.services.task_execution import ExecutionConflict, execution_purpose, execution_record, metadata
from app.services.shot_video_execution import has_video_execution, reconcile_video_execution, settle_terminated_video
from app.services.prompt_builder import (
    build_character_prompt,
    build_scene_prompt,
    get_style
)


class TaskService:
    """任务服务"""
    
    def __init__(self, db: Session = None):
        self.db = db
        self.comfyui_service = ComfyUIService()
    
    # ==================== 工作流验证 ====================
    
    @staticmethod
    def validate_workflow_node_mapping(workflow: Workflow, task_type: str) -> Tuple[bool, str]:
        """
        验证工作流的节点映射配置是否完整
        
        Args:
            workflow: 工作流对象
            task_type: 任务类型 (character, shot, video, transition)
            
        Returns:
            (是否有效, 错误信息)
        """
        if not workflow:
            # 使用默认工作流，不需要验证
            return True, ""

        # 解析节点映射
        node_mapping = {}
        if workflow.node_mapping:
            try:
                node_mapping = json.loads(workflow.node_mapping)
            except Exception:
                return False, f"工作流 '{workflow.name}' 的节点映射配置格式无效"
        if node_mapping.get("output_node_id") and not node_mapping.get("save_image_node_id"):
            node_mapping["save_image_node_id"] = node_mapping.get("output_node_id")
        if node_mapping.get("video_output_node_id") and not node_mapping.get("video_save_node_id"):
            node_mapping["video_save_node_id"] = node_mapping.get("video_output_node_id")

        # 根据任务类型检查必需的字段
        required_fields = {
            "character": ["prompt_node_id", "save_image_node_id"],
            "scene": ["prompt_node_id", "save_image_node_id"],
            "shot_scene": ["prompt_node_id", "save_image_node_id", "width_node_id", "height_node_id", "scene_reference_image_node_id"],
            "shot_character_scene": ["prompt_node_id", "save_image_node_id", "width_node_id", "height_node_id", "character_reference_image_node_id", "scene_reference_image_node_id"],
            "shot_scene_prop": ["prompt_node_id", "save_image_node_id", "width_node_id", "height_node_id", "scene_reference_image_node_id", "prop_reference_image_node_id"],
            "shot": ["prompt_node_id", "save_image_node_id", "width_node_id", "height_node_id"],
            "video": ["prompt_node_id", "video_save_node_id", "reference_image_node_id"],
            "first_last_video": ["prompt_node_id", "first_image_node_id", "last_image_node_id", "video_save_node_id"],
            "three_frame_video": ["prompt_node_id", "video_save_node_id", "reference_image_node_id", "keyframe_node_1", "keyframe_node_2"],
            "four_frame_video": ["prompt_node_id", "video_save_node_id", "reference_image_node_id", "keyframe_node_1", "keyframe_node_2", "keyframe_node_3"],
            "transition": ["first_image_node_id", "last_image_node_id", "video_save_node_id"],
            "character_audio": ["reference_audio_node_id", "text_node_id"]
        }

        fields = required_fields.get(task_type)
        if task_type == "shot" and node_mapping.get("output_node_id"):
            fields = ["prompt_node_id", "save_image_node_id"]
        if task_type == "video" and node_mapping.get("video_output_node_id"):
            fields = ["prompt_node_id", "video_save_node_id"]
        if not fields:
            return True, ""

        missing_fields = []
        field_names = {
            "prompt_node_id": "提示词输入节点",
            "save_image_node_id": "图片保存节点",
            "video_save_node_id": "视频保存节点",
            "width_node_id": "宽度节点",
            "height_node_id": "高度节点",
            "reference_image_node_id": "参考图片节点1",
            "character_reference_image_node_id": "角色参考图节点",
            "scene_reference_image_node_id": "场景参考图节点",
            "prop_reference_image_node_id": "道具参考图节点",
            "first_image_node_id": "第一张图片节点",
            "last_image_node_id": "最后一张图片节点",
            "frame_count_node_id": "总帧数节点",
            "duration_seconds_node_id": "时长秒数节点",
            "reference_audio_node_id": "参考音频节点",
            "text_node_id": "文本节点",
            "keyframe_node_1": "参考图片节点2",
            "keyframe_node_2": "参考图片节点3",
            "keyframe_node_3": "参考图片节点4",
        }

        for field in fields:
            if not node_mapping.get(field):
                missing_fields.append(field_names.get(field, field))

        if missing_fields:
            return False, f"工作流 '{workflow.name}' 的映射配置不完整，缺少以下必需字段：{', '.join(missing_fields)}。请在【系统配置-ComfyUI工作流】中配置完整后再试。"

        if task_type in {"video", "three_frame_video", "four_frame_video"} and not node_mapping.get("video_output_node_id"):
            has_max_side = bool(node_mapping.get("max_side_node_id"))
            has_megapixels = bool(node_mapping.get("megapixels_node_id"))
            if has_max_side == has_megapixels:
                return False, f"工作流 '{workflow.name}' 的映射配置不完整，最长边节点和 Megapixels 必须且只能配置其中一个。"

        if task_type in {"transition", "first_last_video"}:
            has_frame_count = bool(node_mapping.get("frame_count_node_id"))
            has_duration_seconds = bool(node_mapping.get("duration_seconds_node_id"))
            if has_frame_count == has_duration_seconds:
                return False, f"工作流 '{workflow.name}' 的映射配置不完整，总帧数节点和时长秒数节点必须且只能配置其中一个。"

        return True, ""
    
    # ==================== 任务创建 ====================
    
    # ==================== 任务操作 ====================

    @staticmethod
    def _task_snapshot(task: Task) -> dict:
        return {column.key: getattr(task, column.key) for column in Task.__table__.columns
                if column.key not in {"created_at", "updated_at"}}

    @staticmethod
    def cancellation_state(task: Task) -> str | None:
        """Read the persisted deletion fence without trying any remote action."""
        data = metadata(task)
        try:
            json.dumps(data, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ExecutionConflict("INVALID_CANCELLATION_METADATA") from exc
        execution_purpose(task)
        if "cancellation" not in data:
            return None
        saved = data["cancellation"]
        if (not isinstance(saved, dict) or type(saved.get("version")) is not int or saved["version"] != 1
                or not isinstance(saved.get("operation_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", saved["operation_id"])
                or not isinstance(saved.get("state"), str) or saved["state"] not in {"pending", "unknown", "confirmed"}
                or "claim_token" not in saved or saved["claim_token"] != task.claim_token
                or "attempt" not in saved or type(saved["attempt"]) is not type(task.attempt) or saved["attempt"] != task.attempt):
            raise ExecutionConflict("INVALID_TASK_CANCELLATION")
        return saved["state"]

    @staticmethod
    def format_execution_purpose(task: Task) -> dict:
        try:
            return {"execution_purpose": execution_purpose(task)}
        except ExecutionConflict as exc:
            return {"execution_purpose": None, "executionPurposeError": str(exc)}

    @staticmethod
    def format_video_execution(task: Task) -> dict:
        if task.type != "shot_video":
            return {}
        projection = {"strict": has_video_execution(task), "scope": None, "attachment": None, "published": False}
        if not projection["strict"]:
            return {"videoExecution": projection}
        try:
            from app.services.shot_video_execution import TASK_TARGET
            record = execution_record(task)
            request = record["request"]
            only = request["only_window_index"]
            if only is not None and (type(only) is not int or only < 1):
                raise ExecutionConflict("INVALID_REQUESTED_CLIP")
            scope = "whole_shot" if only is None else "clip"
            run = metadata(task).get("video_run")
            if run is not None:
                if (run["run_id"] != record["attempt_id"] or run["scope"] != scope or run["request"] != request
                        or run["target"] != {key: getattr(task, key) for key in TASK_TARGET}):
                    raise ExecutionConflict("VIDEO_EXECUTION_PROJECTION_CHANGED")
                result = run.get("result") or {}
                attachment = result.get("attachment")
                if attachment not in {None, "attached", "archived", "detached"}:
                    raise ExecutionConflict("INVALID_VIDEO_ATTACHMENT")
                projection["attachment"] = attachment
                projection["published"] = bool(execution_purpose(task) == "production" and scope == "whole_shot"
                    and task.status == "completed" and run["phase"] == "completed" and attachment == "attached"
                    and result.get("kind") == "whole_shot" and task.result_url and result.get("url") == task.result_url)
            projection["scope"] = scope
        except (ExecutionConflict, KeyError, TypeError, AttributeError, ValueError) as exc:
            projection["error"] = str(exc)
        return {"videoExecution": projection}

    @staticmethod
    def _transition_task_terminal(task: Task, db: Session, *, status="failed", message, step,
                                  expected=None, extra_conditions=(), cancellation=None) -> bool:
        """Fence the captured actor before remote I/O; never erase attempt evidence."""
        expected = expected if expected is not None else TaskService._task_snapshot(task)
        if expected["status"] not in {"pending", "queued", "running"}:
            return False
        from app.models.shot import Shot
        if any(isinstance(item, Shot) for item in (*db.new, *db.dirty, *db.deleted)):
            raise ExecutionConflict("LIVE_SHOT_DIRTY_IN_TERMINAL_TRANSITION")
        fields = {"status": status, "error_message": message, "current_step": step, "completed_at": datetime.utcnow()}
        if status == "cancelled":
            if TaskService.cancellation_state(task) in {"pending", "unknown"}:
                return False
            data = metadata(task)
            data["cancellation"] = cancellation or {"version": 1, "operation_id": uuid4().hex, "state": "unknown",
                                                    "claim_token": expected["claim_token"], "attempt": expected["attempt"]}
            fields["metadata_json"] = json.dumps(data, ensure_ascii=False, allow_nan=False)
        with db.no_autoflush:
            count = db.query(Task).filter(*[
                getattr(Task, key) == value for key, value in expected.items()
            ], *extra_conditions).update(fields, synchronize_session=False)
            if count != 1:
                db.rollback()
                return False
            db.refresh(task)
            TaskService._mark_related_task_failed(task, db)
            task._terminal_snapshot = TaskService._task_snapshot(task)
            db.commit()
        return True

    @staticmethod
    def _mark_related_task_failed(task: Task, db: Session) -> None:
        """Settle only a terminal task's still-owned production status, not its media."""
        if (TaskService.format_execution_purpose(task)["execution_purpose"] != "production"
                or task.status not in {"failed", "cancelled"}):
            return
        if task.type in {"shot_image","keyframe_image"}:
            from app.models.rsa_media import RsaImageAttempt
            if db.get(RsaImageAttempt,task.id):
                from app.services.rsa_image_service import settle_terminal
                settle_terminal(db,task)
                return
        if has_video_execution(task):
            settle_terminated_video(db, task)
            return
        if task.type == "character_appearance_generation":
            from app.services.appearance_generation_service import settle_terminal
            settle_terminal(db, task)
            return
        if task.type == "chapter_shot_split":
            from app.models.chapter_shot_split import ChapterShotSplitRun
            run=db.query(ChapterShotSplitRun).filter_by(task_id=task.id,status='RUNNING').first()
            if run and ((run.inputs.get('auto_repair') or {}).get('governance') or {}).get('version'):
                from app.services.chapter_shot_split_service import _interrupted_repair_issue,mark_repair_interruption
                run.status,run.issues,run.completed_at='NEEDS_REVIEW',[
                    _interrupted_repair_issue(run,task.error_message or 'TASK_TERMINATED')],datetime.utcnow()
                mark_repair_interruption(task,run,task.error_message or 'TASK_TERMINATED')
            elif run:
                run.status,run.issues,run.completed_at='FAILED',[{
                    'code':'TASK_TERMINATED','message':task.error_message}],datetime.utcnow()
            return
        if task.type == "shot_asset_resolution":
            from app.services.resolved_shot_assets_service import expire_rsa_task
            expire_rsa_task(db,task,commit=False)
            return
        if task.type == 'chapter_asset_rebuild':
            from app.services.chapter_rebuild_service import settle_rebuild
            settle_rebuild(db, task)
            return
        if task.type == 'audio_event_tts':
            from app.services.audio_drive_service import settle_audio_task
            settle_audio_task(db, task)
            return
        from app.models.shot import Shot

        task_condition = db.query(Task.id).filter(*[
            getattr(Task, key) == value for key, value in TaskService._task_snapshot(task).items()
        ]).exists()
        if task.type in {"shot_video", "narration_card_video", "shot_image"} and task.shot_id:
            prefix = "video" if task.type in {"shot_video","narration_card_video"} else "image"
            conditions = [Shot.id == task.shot_id, getattr(Shot, prefix + "_task_id") == task.id,
                          getattr(Shot, prefix + "_status").in_(["pending", "generating"]), task_condition]
            with db.no_autoflush:
                db.query(Shot).filter(*conditions).update({prefix + "_status": "failed"}, synchronize_session=False)
            return

        entity = owner_field = None
        if task.type == "character_portrait" and task.character_id:
            entity, owner_field = CharacterRepository(db).get_by_id(task.character_id), "portrait_task_id"
        elif task.type == "scene_image" and task.scene_id:
            entity, owner_field = SceneRepository(db).get_by_id(task.scene_id), "scene_task_id"
        elif task.type == "prop_image" and task.prop_id:
            entity, owner_field = PropRepository(db).get_by_id(task.prop_id), "prop_task_id"
        if entity:
            model = type(entity)
            db.query(model).filter(model.id == entity.id, getattr(model, owner_field) == task.id,
                                   model.generating_status.in_(["pending", "generating"]), task_condition).update(
                {"generating_status": "failed"}, synchronize_session=False)

    @staticmethod
    def _cleanup_cancelled_video_task(task: Task, db: Session) -> None:
        # Cancellation preserves archived clips and the current formal plan.
        if task.type == "shot_video":
            TaskService._mark_related_task_failed(task, db)

    @staticmethod
    def _mark_pending_video_llm_logs_cancelled(task: Task, db: Session) -> None:
        if (TaskService.format_execution_purpose(task)["execution_purpose"] != "production"
                or has_video_execution(task) or task.type != "shot_video" or not task.chapter_id):
            return
        h3_task_types = [
            "h3_single_frame_prompt",
            "h3_first_last_frame_prompt",
            "h3_multi_keyframe_prompt",
        ]
        query = db.query(LLMLog).filter(
            LLMLog.chapter_id == task.chapter_id,
            LLMLog.task_type.in_(h3_task_types),
            LLMLog.status == "pending",
        )
        if task.novel_id:
            query = query.filter(LLMLog.novel_id == task.novel_id)
        if task.created_at:
            query = query.filter(LLMLog.created_at >= task.created_at)

        for log in query.all():
            log.status = "error"
            log.error_message = "任务被用户取消，LLM 响应已忽略"

    async def _cancel_task_group(self, tasks, db: Session, *, parent_id=None) -> tuple[dict, dict]:
        requests, terminal_snapshots = [], {}
        details = {"cancelled_count": 0, "tasks": [], "conflicts": []}
        snapshots = [(task, self._task_snapshot(task)) for task in tasks]
        parent_conditions = ()
        for task, expected in snapshots:
            try:
                if self.cancellation_state(task) in {"pending", "unknown"}:
                    raise ExecutionConflict("REMOTE_CANCELLATION_UNCONFIRMED")
            except ExecutionConflict:
                details["conflicts"].append(expected["id"])
                if expected["id"] == parent_id:
                    break
                continue
            bindings, diagnostic = [], None
            remote_unconfirmed = False
            try:
                purpose = execution_purpose(task)
                frozen_endpoint_required = has_video_execution(task) or purpose == "benchmark" or task.type == "keyframe_image"
                if has_video_execution(task):
                    record = execution_record(task)
                    run = metadata(task).get("video_run") or {}
                    if run and (run.get("run_id") != record["attempt_id"]
                                or any(getattr(task, key) != value for key, value in run["target"].items())):
                        raise ExecutionConflict("CANCELLATION_VIDEO_RUN_CHANGED")
                    for slot in run.get("clips", {}).values():
                        submit = slot["submission"]
                        remote_unconfirmed |= submit.get("state") in {"submitting", "unknown"}
                        if submit.get("state") == "acknowledged":
                            bindings.append((submit["endpoint"], submit["prompt_id"]))
                elif task.type == "character_appearance_generation":
                    from app.models.appearance_generation import AppearanceGeneration
                    from app.services.chapter_asset_parse_service import digest
                    generation = db.get(AppearanceGeneration, task.id)
                    if not generation or digest(generation.inputs) != generation.input_hash:
                        raise ExecutionConflict("APPEARANCE_CANCELLATION_UNVERIFIED")
                    submit = generation.execution.get("submit") or {}
                    remote_unconfirmed = submit.get("state") in {"ATTEMPTED", "UNKNOWN"}
                    if submit.get("state") == "SUBMITTED":
                        bindings.append((generation.inputs["endpoint"], submit["prompt_id"]))
                elif task.type in {"shot_image","keyframe_image"} and purpose == "production":
                    from app.models.rsa_media import RsaImageAttempt
                    attempt=db.get(RsaImageAttempt,task.id)
                    if attempt:
                        from app.services.chapter_asset_parse_service import digest as media_digest
                        if media_digest(attempt.inputs)!=attempt.input_hash:raise ExecutionConflict("RSA_MEDIA_INPUTS_CHANGED")
                        submit=attempt.execution.get("submit",{})
                        remote_unconfirmed=submit.get("state") in {"ATTEMPTED","UNKNOWN"}
                        if submit.get("state")=="SUBMITTED":bindings.append((attempt.inputs["endpoint"],submit["prompt_id"]))
                    elif task.comfyui_prompt_id:
                        remote_unconfirmed=True
                        diagnostic="LEGACY_IMAGE_ENDPOINT_UNVERIFIED"
                elif task.type == "keyframe_image":
                    contract = read_contract(task)
                    remote_unconfirmed = bool(contract and contract.get("submit", {}).get("state") in {"attempted", "unknown"})
                    if contract and task.comfyui_prompt_id:
                        validate_frozen_contract(contract, task, require_submitted=True)
                        bindings.append((contract["endpoint"], contract["submit"]["prompt_id"]))
                elif purpose == "benchmark" and task.type == "shot_image":
                    proof = execution_record(task).get("shot_image") or {}
                    remote_unconfirmed = proof.get("submission_state") in {"attempted", "unknown"}
                    if proof.get("submission_state") == "submitted" and proof.get("prompt_id") == task.comfyui_prompt_id:
                        bindings.append((proof["endpoint"], proof["prompt_id"]))
                elif purpose == "production" and task.comfyui_prompt_id:
                    bindings.append((None, task.comfyui_prompt_id))
                elif task.comfyui_prompt_id:
                    raise ExecutionConflict("CANCELLATION_SUBMISSION_UNVERIFIED")
                if any(not isinstance(cid, str) or not cid.strip()
                       or ((frozen_endpoint_required or endpoint is not None) and (not isinstance(endpoint, str) or not endpoint.strip()))
                       for endpoint, cid in bindings):
                    raise ExecutionConflict("CANCELLATION_SUBMISSION_UNVERIFIED")
            except Exception as exc:
                bindings, diagnostic = [], str(exc)
                remote_unconfirmed = True
            if self._transition_task_terminal(task, db, status="cancelled", message="任务被用户取消",
                                              step="已终止", expected=expected, extra_conditions=parent_conditions,
                                              cancellation={"version": 1, "operation_id": uuid4().hex, "state": "pending",
                                                            "claim_token": expected["claim_token"], "attempt": expected["attempt"]}):
                details["cancelled_count"] += 1
                terminal_snapshots[expected["id"]] = task._terminal_snapshot
                requests.append((expected["id"], bindings, diagnostic, remote_unconfirmed))
                if task.id == parent_id:
                    from sqlalchemy.orm import aliased
                    parent = aliased(Task)
                    parent_conditions = (db.query(parent.id).filter(*[
                        getattr(parent, key) == value for key, value in self._task_snapshot(task).items()
                    ]).exists(),)
            elif expected["status"] in {"pending", "queued", "running"}:
                details["conflicts"].append(expected["id"])
                if expected["id"] == parent_id:
                    break

        # Every local actor is fenced before the first remote cancellation awaits.
        for task_id, bindings, diagnostic, remote_unconfirmed in requests:
            results = []
            for endpoint, prompt_id in bindings:
                try:
                    client = frozen_keyframe_client(endpoint) if endpoint else self.comfyui_service
                    result = await client.cancel_all_matching_tasks([prompt_id])
                    results.append(result)
                    confirmed = result.get("interrupted") is True or prompt_id in result.get("deleted_from_queue", [])
                    if not confirmed and prompt_id in result.get("not_found", []):
                        # An absent queue entry alone does not prove the job stopped.
                        poll_client = client if endpoint else self.comfyui_service.client
                        observed = await poll_client.get_prompt_state(prompt_id)
                        result["observed_state"] = observed.get("state")
                        confirmed = observed.get("state") in {"completed", "error"}
                    remote_unconfirmed |= not confirmed
                except Exception as exc:
                    results.append({"error": str(exc)})
                    remote_unconfirmed = True
            details["tasks"].append({"task_id": task_id, "remote": results, "diagnostic": diagnostic,
                                     "skipped_comfyui": not bool(bindings), "remote_unconfirmed": remote_unconfirmed})

        # A concurrent evidence write must leave the persisted fence in place.
        # Finalize parents last, after all child outcomes are durably recorded.
        parent_ids = {saved["parent_task_id"] for _, saved in snapshots}
        for outcome in sorted(details["tasks"], key=lambda item: item["task_id"] in parent_ids):
            task_id = outcome["task_id"]
            children = {saved["id"] for _, saved in snapshots if saved["parent_task_id"] == task_id}
            outcome["remote_unconfirmed"] |= bool(children.intersection(details["conflicts"])) or any(
                child["remote_unconfirmed"] for child in details["tasks"] if child["task_id"] in children)
            expected = terminal_snapshots[task_id]
            data = json.loads(expected["metadata_json"])
            data["cancellation"]["state"] = "unknown" if outcome["remote_unconfirmed"] else "confirmed"
            encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
            with db.no_autoflush:
                count = db.query(Task).filter(*[
                    getattr(Task, key) == value for key, value in expected.items()
                ]).update({"metadata_json": encoded}, synchronize_session=False)
                if count == 1:
                    terminal_snapshots[task_id] = {**expected, "metadata_json": encoded}
                    db.commit()
                else:
                    db.rollback()
                    outcome["remote_unconfirmed"] = True
        return details, terminal_snapshots

    async def cancel_task(self, task_id: str, db: Session = None) -> Dict[str, Any]:
        """Cancel locally first; remote cancellation is best-effort, task-scoped I/O."""
        db = db or self.db
        task = TaskRepository(db).get_by_id(task_id)
        if not task:
            return {"success": False, "message": "任务不存在", "status_code": 404}
        try:
            if self.cancellation_state(task) in {"pending", "unknown"}:
                raise ExecutionConflict("REMOTE_CANCELLATION_UNCONFIRMED")
        except ExecutionConflict as exc:
            return {"success": False, "message": str(exc), "status_code": 409, "task": task}
        if task.status not in {"pending", "queued", "running"}:
            return {"success": True, "message": "任务不是进行中状态，无需取消", "task": task,
                    "terminal_snapshot": self._task_snapshot(task), "details": {"skipped": True}}
        tasks = [task]
        is_batch = task.type in {"shot_image_batch", "shot_video_batch", "audio_prepare", "chapter_asset_rebuild"}
        if is_batch:
            purpose = self.format_execution_purpose(task)["execution_purpose"]
            tasks.extend(child for child in db.query(Task).filter(Task.parent_task_id == task.id).all()
                         if purpose is not None and self.format_execution_purpose(child)["execution_purpose"] == purpose)
        details, terminal_snapshots = await self._cancel_task_group(tasks, db, parent_id=task.id if is_batch else None)
        if details["conflicts"] or task_id not in terminal_snapshots:
            return {"success": False, "status_code": 409, "message": "任务执行状态已更改，取消冲突；请刷新后重试",
                    "task": task, "details": details}
        return {"success": True, "message": "任务已取消", "task": task, "details": details,
                "terminal_snapshot": terminal_snapshots[task_id]}

    async def cancel_all_tasks(self, db: Session = None) -> Dict[str, Any]:
        """Fence all local tasks before cancelling only their recorded remote jobs."""
        db = db or self.db
        tasks = db.query(Task).filter(Task.status.in_(["pending", "queued", "running"])).all()
        details, _ = await self._cancel_task_group(tasks, db)
        return {"success": not bool(details["conflicts"]), "message": f"已终止 {details['cancelled_count']} 个任务",
                "cancelled_count": details["cancelled_count"], "failed_count": len(details["conflicts"]), "details": details}
    
    def retry_task(self, task_id: str, db: Session = None) -> Dict[str, Any]:
        """
        重试失败的任务
        
        Args:
            task_id: 任务ID
            db: 数据库会话
            
        Returns:
            重试结果
        """
        db = db or self.db
        task_repo = TaskRepository(db)
        
        task = task_repo.get_by_id(task_id)
        if not task:
            return {"success": False, "message": "任务不存在", "status_code": 404}

        if task.status not in ["failed", "completed"]:
            return {"success": False, "message": "只能重试失败或已完成的任务", "status_code": 400}
        if task.type in {"shot_image","keyframe_image"}:
            return {"success":False,"message":"请从Shot或关键帧发起新的RSA生成任务，原图与lineage证据保留","status_code":409}
        if task.type in {'chapter_asset_rebuild', 'audio_event_tts', 'audio_prepare', 'chapter_video', 'transition_video', 'shot_image_batch', 'shot_video_batch'}:
            return {'success': False, 'status_code': 409, 'message': '请从对应制作入口新建任务并重新校验来源，原执行证据保留'}

        if task.type == "chapter_shot_split":
            return {"success": False, "message": "请从章回重新拆分；原分镜来源和任务证据已保留", "status_code": 409}
        if task.type == "shot_asset_resolution":
            return {"success":False,"message":"请显式重新解析分镜资产，新建冻结版本；原RSA证据保留","status_code":409}
        if task.type in {"chapter_asset_parse", "chapter_asset_resolution", "appearance_timeline", "shot_revision"}:
            return {"success": False, "message": "请从章回重新解析；原候选来源和任务证据已保留", "status_code": 400}
        if task.type == "character_appearance_generation":
            return {"success": False, "message": "请从角色外观列表重新生成，原任务和图像版本证据已保留", "status_code": 409}
        if task.type == "keyframe_image":
            return {"success": False, "message": "关键帧任务不支持重试，请从关键帧重新发起生成；原任务的参考合同与结果证据已保留", "status_code": 400}

        if task.type == "shot_video" or self.format_execution_purpose(task)["execution_purpose"] != "production":
            return {"success": False, "message": "视频或基准任务不支持原地重试，请新建完整执行；原任务证据已保留", "status_code": 400}

        character_repo = CharacterRepository(db)
        scene_repo = SceneRepository(db)
        # 重置任务状态
        task.status = "pending"
        task.progress = 0
        task.current_step = None
        task.error_message = None
        task.result_url = None
        task.completed_at = None
        task.comfyui_prompt_id = None
        task.workflow_json = None
        db.commit()

        # 根据任务类型重新执行
        restarted = False
        if task.type == "character_portrait" and task.character_id:
            # 从CharacterService重新执行任务
            from app.services.character_service import enqueue_character_portrait_task
            character = character_repo.get_by_id(task.character_id)
            if character:
                enqueue_character_portrait_task(
                    task.id,
                    character.id,
                    character.name,
                    character.appearance,
                    character.description,
                )
                restarted = True
        elif task.type == "scene_image" and task.scene_id:
            # 从SceneService重新执行任务
            from app.services.scene_service import enqueue_scene_image_task
            scene = scene_repo.get_by_id(task.scene_id)
            if scene:
                enqueue_scene_image_task(
                    task.id,
                    scene.id,
                    scene.name,
                    scene.setting,
                    scene.description,
                )
                restarted = True
        elif task.type == "prop_image" and task.prop_id:
            from app.services.prop_image_service import enqueue_prop_image_task

            prop_repo = PropRepository(db)
            prop = prop_repo.get_by_id(task.prop_id)
            if prop:
                enqueue_prop_image_task(
                    task.id,
                    prop.id,
                    prop.name,
                    prop.appearance,
                    prop.description,
                )
                restarted = True
        elif task.type == "shot_image" and task.novel_id and task.chapter_id and task.workflow_id:
            from app.services.shot_image_service import enqueue_shot_image_task

            shot_repo = ShotRepository(db)
            shot = shot_repo.get_by_id(task.shot_id) if task.shot_id else None
            if not shot:
                match = re.search(r"镜\s*(\d+)", task.name or "")
                if match:
                    shot = shot_repo.get_by_chapter_and_index(task.chapter_id, int(match.group(1)))

            if not shot:
                task.status = "failed"
                task.error_message = "重试失败：找不到关联分镜"
                task.current_step = "重试失败"
                db.commit()
                return {"success": False, "message": task.error_message, "status_code": 400}

            shot_repo.update(
                shot,
                image_url=None,
                image_path=None,
                image_status="generating",
                image_task_id=task.id,
            )

            enqueue_shot_image_task(
                task.id,
                task.novel_id,
                task.chapter_id,
                shot.index,
                shot.description or "",
                task.workflow_id,
            )
            restarted = True

        if not restarted:
            task.status = "failed"
            task.error_message = "当前任务类型暂不支持重试，或缺少必要关联数据"
            task.current_step = "重试失败"
            db.commit()
            return {"success": False, "message": task.error_message, "status_code": 400}

        return {
            "success": True,
            "message": "任务已重新启动",
            "data": {
                "taskId": task.id,
                "status": "pending"
            }
        }
    
    # ==================== 任务列表格式化 ====================

    async def _reconcile_benchmark_task(self, task: Task, db: Session) -> int:
        expected = self._task_snapshot(task)
        try:
            now = datetime.utcnow()
            started = task.started_at or task.created_at
            age = (now - started.replace(tzinfo=None)).total_seconds() if started else 0
            if not task.comfyui_prompt_id:
                timeout = 600 if task.type == "keyframe_image" else 1800
                if age > timeout:
                    raise ExecutionConflict("BENCHMARK_INTERRUPTED_WITHOUT_SUBMISSION: create a new task")
                return 0
            if task.type == "shot_image":
                proof = execution_record(task)["shot_image"]
                if proof.get("submission_state") != "submitted" or proof.get("prompt_id") != task.comfyui_prompt_id:
                    raise ExecutionConflict("BENCHMARK_IMAGE_SUBMISSION_UNVERIFIED")
                endpoint, prompt_id = proof["endpoint"], proof["prompt_id"]
            elif task.type == "keyframe_image":
                contract = read_contract(task)
                saved = assert_task_active(db, task, contract)
                validate_frozen_contract(saved, task, require_submitted=True)
                endpoint, prompt_id = saved["endpoint"], saved["submit"]["prompt_id"]
            else:
                return 0
            if not isinstance(endpoint, str) or not endpoint:
                raise ExecutionConflict("BENCHMARK_ENDPOINT_NOT_FROZEN")
            prompt_state = await frozen_keyframe_client(endpoint).get_prompt_state(prompt_id)
            current = db.query(Task).filter(Task.id == expected["id"]).populate_existing().first()
            if not current or self._task_snapshot(current) != expected:
                return 0
            state = prompt_state.get("state")
            if state == "completed":
                recover = (self._recover_completed_shot_image_prompt if task.type == "shot_image"
                           else self._recover_completed_keyframe_prompt)
                recovered = await recover(task, prompt_state.get("history"), db)
                return int(recovered or task.status != expected["status"])
            if state == "error" or (state == "missing" and age > 60):
                raise ExecutionConflict(prompt_state.get("message") or "BENCHMARK_SUBMITTED_JOB_MISSING")
            return 0
        except Exception as exc:
            return int(self._transition_task_terminal(task, db, message=str(exc),
                                                      step="Benchmark recovery blocked", expected=expected))

    async def reconcile_active_tasks(self, tasks=None, db: Session = None) -> int:
        """校准本地 running/pending 任务，避免 ComfyUI 已无任务但本地假死。"""
        db = db or self.db
        task_repo = TaskRepository(db)
        tasks = tasks if tasks is not None else task_repo.list_active_tasks()
        active_tasks = [task for task in tasks if task.status in ["pending", "running"]]
        if not active_tasks:
            return 0

        updated_count, legacy_tasks = 0, []
        for task in active_tasks:
            expected = self._task_snapshot(task)
            if self.format_execution_purpose(task)['execution_purpose'] != 'production' or task.type == 'transition_video':
                updated_count += int(self._transition_task_terminal(task, db, message='LEGACY_RUNTIME_RETIRED', step='旧执行入口已停用', expected=expected))
                continue
            task_meta=metadata(task)
            if (task.type in {'chapter_asset_rebuild', 'audio_event_tts', 'audio_prepare', 'shot_image_batch',
                    'shot_video_batch','narration_card_video'}
                    or (task.type=='chapter_video' and task_meta.get('delivery_mode')=='CHAPTER_COMPLETION')):
                continue  # Their source-pinned persistent workers own settlement; generic URL recovery cannot adopt outputs.
            if task.type == 'shot_video' and not has_video_execution(task):
                updated_count += int(self._transition_task_terminal(task, db, message='VIDEO_EXECUTION_AND_RSA_REQUIRED', step='请重新提交视频任务', expected=expected))
                continue
            if task.type in {"shot_image","keyframe_image"} and self.format_execution_purpose(task)["execution_purpose"] == "production":
                from app.models.rsa_media import RsaImageAttempt
                if not db.get(RsaImageAttempt,task.id):
                    updated_count += int(self._transition_task_terminal(task,db,message="LEGACY_IMAGE_REQUIRES_RSA_LINEAGE",step="需重新通过RSA Gate",expected=expected))
                continue
            if task.type == "character_appearance_generation":
                continue  # Its persistent worker owns recovery and image publication.
            if task.type == "chapter_shot_split":
                from app.services.chapter_shot_split_service import expire_split_task
                updated_count += int(expire_split_task(db, task))
                continue
            if task.type == "shot_asset_resolution":
                from app.services.resolved_shot_assets_service import expire_rsa_task
                updated_count += int(expire_rsa_task(db,task))
                continue
            if task.type == "chapter_asset_parse":
                from app.services.chapter_asset_parse_service import expire_run_for_task
                updated_count += int(expire_run_for_task(db, task))
                continue
            if task.type == "chapter_asset_resolution":
                from app.services.asset_resolution_service import expire_resolution_task
                updated_count += int(expire_resolution_task(db, task))
                continue
            if task.type == "appearance_timeline":
                from app.services.appearance_timeline_service import expire_timeline_task
                updated_count += int(expire_timeline_task(db, task))
                continue
            try:
                if task.type == "shot_video":
                    handled = await reconcile_video_execution(db, task)
                    if handled is not None:
                        if handled:
                            updated_count += 1
                            current = db.query(Task).filter(Task.id == expected["id"]).populate_existing().first()
                            if (current and current.claim_token == expected["claim_token"]
                                    and current.attempt == expected["attempt"]
                                    and execution_record(current)["attempt_id"] == json.loads(expected["metadata_json"])["execution"]["attempt_id"]):
                                self._mark_related_task_failed(current, db)
                                db.commit()
                        continue
                    if has_video_execution(task):
                        raise ExecutionConflict("VIDEO_INTEGRITY_DISPATCH_REQUIRED")
                if execution_purpose(task) == "benchmark":
                    updated_count += await self._reconcile_benchmark_task(task, db)
                    continue
            except Exception as exc:
                updated_count += int(self._transition_task_terminal(
                    task, db, message=f"EXECUTION_RECOVERY_BLOCKED: {exc}", step="Execution recovery blocked", expected=expected))
                continue
            legacy_tasks.append(task)
        active_tasks = legacy_tasks
        if not active_tasks:
            return updated_count

        snapshots = {task.id: self._task_snapshot(task) for task in active_tasks}
        keyframe_contracts = {}
        for task in active_tasks:
            if task.type == "keyframe_image":
                try:
                    contract = read_contract(task)
                except KeyframeReferenceError:
                    contract = None
                if contract:
                    keyframe_contracts[task.id] = contract
        queue_info = await self.comfyui_service.get_queue_info() if any(
            task.id not in keyframe_contracts for task in active_tasks
        ) else None
        now = datetime.utcnow()
        comfyui_timeout = int(getattr(get_settings(), "COMFYUI_TIMEOUT", 900) or 900)
        llm_timeout = int(getattr(get_settings(), "LLM_TIMEOUT", 300) or 300)

        def task_age_seconds(task: Task) -> float:
            started_at = task.started_at or task.created_at
            if not started_at:
                return 0
            if started_at.tzinfo is not None:
                started_at = started_at.astimezone(timezone.utc).replace(tzinfo=None)
            return (now - started_at).total_seconds()

        def inactive_seconds(task: Task) -> float:
            updated_at = task.updated_at or task.started_at or task.created_at
            if not updated_at:
                return 0
            if updated_at.tzinfo is not None:
                updated_at = updated_at.astimezone(timezone.utc).replace(tzinfo=None)
            return (now - updated_at).total_seconds()

        for task in active_tasks:
            age_seconds = task_age_seconds(task)
            expected = snapshots[task.id]

            def fail_task(message, step):
                nonlocal updated_count
                updated_count += int(self._transition_task_terminal(task, db, message=message, step=step, expected=expected))

            pending_start_timeout = 600 if task.type == "keyframe_image" else 1800
            is_batch_waiting_child = bool(getattr(task, "parent_task_id", None))
            db_backed_task = task.type in {"audio_event_tts", "audio_prepare", "shot_video_batch", "narration_card_video"} or (
                task.type=='chapter_video' and metadata(task).get('delivery_mode')=='CHAPTER_COMPLETION')
            if task.status == "pending" and not task.started_at and age_seconds > pending_start_timeout and task.type != "shot_image_batch" and not is_batch_waiting_child and not db_backed_task:
                fail_task("任务长期未启动，后台内存队列可能已因服务重启或热更新丢失，请重新提交", "任务未启动")
                continue

            if task.comfyui_prompt_id:
                contract = keyframe_contracts.get(task.id)
                if contract:
                    try:
                        task = db.query(Task).filter(Task.id == task.id).populate_existing().first()
                        if not task or task.status != "running":
                            continue
                        saved = assert_task_active(db, task, contract)
                        validate_frozen_contract(saved, task, require_submitted=True)
                        client = frozen_keyframe_client(contract.get("endpoint") or "")
                        prompt_state = await client.get_prompt_state(contract["submit"]["prompt_id"])
                        task = db.query(Task).filter(Task.id == task.id).populate_existing().first()
                        if not task or task.status != "running":
                            continue
                        saved = assert_task_active(db, task, contract)
                        validate_frozen_contract(saved, task, require_submitted=True)
                        if prompt_state.get("state") == "error":
                            raise KeyframeReferenceError("GENERATION_FAILED", prompt_state.get("message") or "ComfyUI execution failed")
                        if prompt_state.get("state") == "missing" and age_seconds > 60:
                            raise KeyframeReferenceError("SUBMITTED_JOB_MISSING")
                    except KeyframeReferenceError as error:
                        failed_contract = {**contract, "phase": "failed",
                                           "failure": {"stage": "reconciliation", "code": error.code, "message": str(error)}}
                        try:
                            changed = store_contract(db, task.id, failed_contract, terminal=True, status="failed",
                                                     error_message=str(error), current_step="关键帧恢复被阻止", completed_at=datetime.utcnow())
                            if changed:
                                updated_count += 1
                            else:
                                record_contract_observation(db, task.id, failed_contract, error)
                        except KeyframeReferenceError as conflict:
                            record_contract_observation(db, task.id, failed_contract, conflict)
                        continue
                else:
                    prompt_state = await self.comfyui_service.client.get_prompt_state(
                        task.comfyui_prompt_id,
                        queue_info=queue_info,
                    )
                    current = db.query(Task).filter(Task.id == expected["id"]).populate_existing().first()
                    if not current or self._task_snapshot(current) != expected:
                        continue
                state = prompt_state.get("state")
                if state in ["queued", "history", "unknown"]:
                    continue

                if state == "completed":
                    if task.type == "shot_image" and inactive_seconds(task) > 60:
                        recovered = await self._recover_completed_shot_image_prompt(task, prompt_state.get("history"), db)
                        if recovered:
                            updated_count += 1
                            continue
                    if task.type == "keyframe_image" and inactive_seconds(task) > 60:
                        previous_status = task.status
                        recovered = await self._recover_completed_keyframe_prompt(task, prompt_state.get("history"), db)
                        if recovered or task.status != previous_status:
                            updated_count += 1
                            continue
                        if contract:
                            continue
                    if task.type == "shot_video" and inactive_seconds(task) > 60:
                        recovered = await self._recover_completed_shot_video_prompt(task, prompt_state.get("history"), db)
                        if recovered:
                            updated_count += 1
                        continue
                    if age_seconds > comfyui_timeout:
                        fail_task("ComfyUI 已完成该任务，但后端未保存结果，可能是输出节点映射错误或后台任务中断", "任务异常")
                    continue

                if state == "error":
                    fail_task(prompt_state.get("message") or "ComfyUI 执行失败", "生成失败")
                    continue

                if state == "missing" and age_seconds > 60:
                    fail_task("ComfyUI 队列和 history 中均找不到该任务，可能已被清理、取消或 ComfyUI 异常退出", "任务异常")
                    continue

            elif task.status == "running":
                if db_backed_task:
                    continue
                clip_state = self._shot_video_clip_state_for_prompt(task, None) if task.type == "shot_video" else {}
                if clip_state.get("has_prompt_building_clip") and inactive_seconds(task) > llm_timeout + 60:
                    fail_task("任务停留在 H3 提示词构建阶段过久，可能是 LLM 调用中断或后台任务已退出", "任务异常")
                    continue
                if task.current_step and "ComfyUI" in task.current_step and age_seconds > 600:
                    fail_task("任务停留在 ComfyUI 调用阶段超过 10 分钟且未保存 prompt_id，可能是旧后台任务已中断", "任务异常")

        if updated_count:
            db.commit()
        return updated_count

    async def _recover_completed_shot_image_prompt(self, task: Task, prompt_history: dict, db: Session) -> bool:
        """Recover a completed shot image prompt when the worker missed persistence."""
        return False  # Sole recovery owner: RsaImageService, including acknowledged remote submissions.
        purpose = self.format_execution_purpose(task)["execution_purpose"]
        if purpose == "benchmark":
            from app.services.shot_image_service import recover_benchmark_shot_image
            return await recover_benchmark_shot_image(db, task, prompt_history)
        if purpose != "production":
            return False
        # Production recovery is exclusive to the persistent RSA image worker.
        from app.models.rsa_media import RsaImageAttempt
        if not db.get(RsaImageAttempt,task.id):
            self._transition_task_terminal(task,db,message="LEGACY_SHOT_IMAGE_REQUIRES_RSA",step="缺少RSA lineage")
        return False
        if task.type != "shot_image" or not task.shot_id or not prompt_history:
            return False
        expected = self._task_snapshot(task)
        if not self._legacy_recovery_is_current(task, db, expected):
            return False

        outputs = prompt_history.get("outputs") or {}
        if not outputs:
            return False

        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(task.shot_id)
        if not shot:
            return False

        node_mapping = {}
        if task.workflow_id:
            workflow = db.query(Workflow).filter(Workflow.id == task.workflow_id).first()
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                except Exception:
                    node_mapping = {}

        prompt_workflow = None
        prompt_payload = prompt_history.get("prompt") or []
        if isinstance(prompt_payload, list) and len(prompt_payload) > 2 and isinstance(prompt_payload[2], dict):
            prompt_workflow = prompt_payload[2]

        save_image_node_id = node_mapping.get("save_image_node_id") or node_mapping.get("output_node_id")
        result = self.comfyui_service.client._parse_outputs(outputs, prompt_workflow, save_image_node_id)
        if not result or not result.get("success") or not result.get("image_url"):
            return False

        local_path = await file_storage.download_image(
            url=result["image_url"],
            novel_id=task.novel_id,
            character_name=f"shot_{shot.id[:8]}",
            image_type="shot",
            chapter_id=task.chapter_id,
        )
        if not local_path:
            return False

        if not self._legacy_recovery_is_current(task, db, expected):
            return False
        local_url = local_path_to_url(local_path)
        shot_repo.update(shot, image_url=local_url, image_path=str(local_path), image_status="completed", image_task_id=task.id)
        task.status = "completed"
        task.progress = 100
        task.result_url = local_url
        task.error_message = None
        task.current_step = "生成完成"
        task.completed_at = datetime.utcnow()
        db.commit()
        return True

    async def _recover_completed_keyframe_prompt(self, task: Task, prompt_history: dict, db: Session) -> bool:
        return False  # Historical keyframe contracts are read-only; new images use the RSA ledger.
        """Recover only the acknowledged, task-owned #09 graph and unchanged target."""
        if task.type != "keyframe_image":
            return False
        from app.services.shot_keyframe_service import ShotKeyframeService

        purpose = self.format_execution_purpose(task)["execution_purpose"]
        if purpose == "benchmark":
            # Recovery needs only stateless contract methods, not an LLM client.
            service = ShotKeyframeService.__new__(ShotKeyframeService)
            return await service.recover_benchmark_image(db, task, prompt_history)
        if purpose != "production":
            self._transition_task_terminal(task, db, message="#09 LEGACY_CONTRACT_UNVERIFIED: invalid execution purpose",
                                            step="关键帧恢复被阻止")
            return False
        from app.models.rsa_media import RsaImageAttempt
        if not db.get(RsaImageAttempt,task.id):
            self._transition_task_terminal(task,db,message="LEGACY_KEYFRAME_REQUIRES_RSA_LINEAGE",step="缺少RSA lineage")
        return False

        try:
            contract = read_contract(task)
        except KeyframeReferenceError:
            contract = None
        task_id = task.id
        task = db.query(Task).filter(Task.id == task_id).populate_existing().first()
        if not task or task.type != "keyframe_image":
            return False
        try:
            saved = read_contract(task)
        except KeyframeReferenceError:
            saved = None
        if not contract:
            if not saved and task.status in {"pending", "running"}:
                # Legacy names/indexes cannot establish ownership of today's target.
                db.query(Task).filter(
                    Task.id == task_id, Task.status == task.status,
                    Task.metadata_json == task.metadata_json,
                ).update({"status": "failed", "current_step": "关键帧恢复被阻止",
                          "error_message": "#09 LEGACY_CONTRACT_UNVERIFIED: 缺少可验证的目标快照，不能安全恢复旧任务，请从关键帧重新发起生成。",
                          "completed_at": datetime.utcnow()}, synchronize_session=False)
                db.commit()
                db.refresh(task)
            return False

        def already_attached(current, recorded):
            if not current or current.status != "completed":
                return False
            validate_frozen_contract(recorded, current, require_submitted=True)
            result = recorded.get("result") or {}
            if not isinstance(result, dict):
                return False
            # This proves a historical attachment, not ownership of today's image.
            return bool(recorded["attempt_id"] == contract.get("attempt_id")
                        and recorded["submit"]["prompt_id"] == contract.get("submit", {}).get("prompt_id")
                        and result.get("attachment") == "attached"
                        and result.get("url") == current.result_url and current.result_url)

        if task.status not in {"running", "completed"}:
            return False

        def check_target():
            current = db.query(Task).filter(Task.id == task_id).populate_existing().first()
            if not current:
                raise KeyframeReferenceError("TASK_REMOVED")
            saved = assert_task_active(db, current, contract)
            validate_frozen_contract(saved, current, require_submitted=True)
            shot = ShotKeyframeService.load_task_shot(db, current, saved)
            if not shot:
                raise KeyframeReferenceError("TARGET_NOT_FOUND")
            assert_target(shot, task_id, contract)
            return current

        local_path = local_url = remote_url = None
        try:
            if task.status == "completed":
                return already_attached(task, saved)
            task = check_target()
            client = frozen_keyframe_client(contract["endpoint"])
            remote_url = select_keyframe_output(prompt_history, contract, client.base_url)
            local_path = await file_storage.download_image(
                url=remote_url, novel_id=contract["planned"]["novel_id"],
                character_name=f"keyframe_{contract['target']['frame_index']}",
                image_type="keyframe", chapter_id=contract["target"]["chapter_id"],
            )
            if not local_path:
                raise KeyframeReferenceError("IMAGE_DOWNLOAD_FAILED")
            local_url = local_path_to_url(local_path)
            if not local_url:
                raise KeyframeReferenceError("IMAGE_STORAGE_LOCATION_INVALID")
            check_target()
            from app.services.shot_keyframe_service import ShotKeyframeService

            ShotKeyframeService._read_reference_payload(local_url)
            if patch_target(db, task_id, contract, image_url=local_url):
                return True
            return already_attached(task, read_contract(task) or {})
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            contract["failure"] = {"stage": "recovery", "code": code, "message": str(exc)}
            contract["phase"] = "failed"
            if local_path:
                contract["result"] = {"url": local_url, "local_path": str(local_path), "source_url": remote_url,
                                      "attachment": "detached", "reason": code}
            # Keep the captured token. A newer contract/projection may only receive
            # a sibling observation, never a replacement failure, CID or resultUrl.
            try:
                try:
                    changed = store_contract(db, task_id, contract, terminal=True, status="failed",
                                             error_message=str(exc), current_step="关键帧恢复被阻止", completed_at=datetime.utcnow())
                    if not changed:
                        record_contract_observation(db, task_id, contract, exc, artifact_url=local_url)
                except KeyframeReferenceError as conflict:
                    record_contract_observation(db, task_id, contract, conflict, artifact_url=local_url)
                current = db.query(Task).filter(Task.id == task_id).populate_existing().first()
                if current and current.status == "completed":
                    return already_attached(current, read_contract(current))
            except KeyframeReferenceError:
                pass
            return False

    @staticmethod
    def _keyframe_frame_index_from_task(task: Task) -> int | None:
        match = re.search(r"-(\d+)\s*$", task.name or "")
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _shot_video_clip_state_for_prompt(task: Task, prompt_id: str) -> dict:
        try:
            window_plans = json.loads(task.video_director_clips or "[]")
            if not isinstance(window_plans, list):
                window_plans = []
        except Exception:
            window_plans = []

        result = {
            "status": None,
            "video_url": None,
            "has_prompt_building_clip": False,
        }
        for window in window_plans:
            if not isinstance(window, dict):
                continue
            status = str(window.get("status") or "").upper()
            if status == "PROMPT_BUILDING":
                result["has_prompt_building_clip"] = True
            if prompt_id and window.get("prompt_id") == prompt_id:
                result["status"] = status
                result["video_url"] = window.get("video_url")
        return result

    @staticmethod
    def _next_unfinished_shot_video_window_index(task: Task) -> int | None:
        try:
            window_plans = json.loads(task.video_director_clips or "[]")
            if not isinstance(window_plans, list):
                return None
        except Exception:
            return None

        for window in sorted(
            [item for item in window_plans if isinstance(item, dict)],
            key=lambda item: int(item.get("window_index") or item.get("clip_index") or 0),
        ):
            status = str(window.get("status") or "").upper()
            has_video = bool(window.get("video_url") or window.get("local_path"))
            if status != "SUCCEEDED" or not has_video:
                window_index = window.get("window_index") or window.get("clip_index")
                try:
                    return int(window_index)
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    def _legacy_recovery_is_current(task: Task, db: Session, expected: dict) -> bool:
        from app.models.shot import Shot
        from sqlalchemy.orm import aliased

        if expected["status"] not in {"pending", "running"}:
            return False
        conditions = [getattr(Task, key) == value for key, value in expected.items()]
        owner = Shot.video_task_id if expected["type"] == "shot_video" else Shot.image_task_id
        conditions.append(db.query(Shot.id).filter(Shot.id == expected["shot_id"], owner == expected["id"]).exists())
        if expected["parent_task_id"]:
            parent = aliased(Task)
            conditions.append(db.query(parent.id).filter(parent.id == expected["parent_task_id"],
                                                         parent.status.in_(["pending", "running"])).exists())
        with db.no_autoflush:
            return db.query(Task.id).filter(*conditions).first() is not None

    def _enqueue_remaining_shot_video_clip(self, task: Task, window_index: int, db: Session) -> None:
        if has_video_execution(task) or self.format_execution_purpose(task)["execution_purpose"] != "production":
            return
        self._fail_unproven_legacy_video(task, db)

    async def _recover_completed_shot_video_prompt(self, task: Task, prompt_history: dict, db: Session) -> bool:
        """Old clips are evidence, never inputs to a new whole-shot publication."""
        if has_video_execution(task) or self.format_execution_purpose(task)["execution_purpose"] != "production":
            return False
        return self._fail_unproven_legacy_video(task, db, prompt_history)

    async def _recover_completed_single_shot_video_prompt(self, task: Task, prompt_history: dict, db: Session) -> bool:
        """A legacy single clip also lacks a verifiable publication run."""
        if has_video_execution(task) or self.format_execution_purpose(task)["execution_purpose"] != "production":
            return False
        return self._fail_unproven_legacy_video(task, db, prompt_history)

    def _fail_unproven_legacy_video(self, task: Task, db: Session, prompt_history=None) -> bool:
        if task.type != "shot_video" or has_video_execution(task):
            return False
        expected = self._task_snapshot(task)
        changed = self._transition_task_terminal(task, db, expected=expected,
            message="LEGACY_VIDEO_RUN_UNVERIFIED: 已保留旧任务证据；请新建完整视频执行，不能继续或合并旧 Clip",
            step="Fresh complete video run required")
        if prompt_history is None:
            return changed
        observation = {"attachment": "detached", "reason": "LEGACY_VIDEO_RUN_UNVERIFIED",
                       "claim_token": expected["claim_token"], "attempt": expected["attempt"],
                       "prompt_id": expected["comfyui_prompt_id"], "workflow_json": expected["workflow_json"],
                       "clips_json": expected["video_director_clips"], "history": prompt_history}
        # Late history may be appended, never promoted into a newer actor's result.
        for _ in range(3):
            current = db.query(Task).filter(Task.id == expected["id"]).populate_existing().first()
            if not current:
                return changed
            original = current.metadata_json
            data = metadata(current)
            observations = data.setdefault("legacy_video_observations", [])
            if not isinstance(observations, list):
                raise ExecutionConflict("INVALID_LEGACY_VIDEO_OBSERVATIONS")
            if observation in observations:
                return changed
            observations.append(observation)
            count = db.query(Task).filter(Task.id == expected["id"], Task.status == current.status,
                                           Task.metadata_json == original).update(
                {"metadata_json": json.dumps(data, ensure_ascii=False, allow_nan=False)}, synchronize_session=False)
            if count == 1:
                db.commit()
                db.refresh(current)
                return changed
            db.rollback()
        raise ExecutionConflict("LEGACY_VIDEO_OBSERVATION_CONFLICT")

    @staticmethod
    def format_task_list(tasks: list, novels: dict, chapters: dict, workflows: dict, shots: dict = None) -> list:
        """
        格式化任务列表响应
        
        Args:
            tasks: 任务列表
            novels: 小说字典
            chapters: 章节字典
            workflows: 工作流字典
            
        Returns:
            格式化后的任务列表
        """
        import json

        shots = shots or {}
        from app.services.evidence_reader import decode_evidence, public_evidence, safe_value, task_field
        from app.services.task_execution import public_review_findings

        def parse_reference_images(value: str):
            return safe_value(task_field(value,'reference_images')['value'])

        def parse_metadata(value: str):
            return safe_value(decode_evidence(value,dict)['value'])

        def format_video_director_clips(task: Task):
            if task.type != "shot_video":
                return []
            window_plans = task_field(task.video_director_clips,'video_director_clips')['value']
            if window_plans is None:
                return None
            clips = []
            for window in window_plans:
                if not isinstance(window, dict):
                    continue
                video_url = window.get("video_url")
                status = window.get("status")
                clips.append({
                    "windowIndex": window.get("window_index"),
                    "status": status,
                    "startTime": window.get("start_time"),
                    "endTime": window.get("end_time"),
                    "workflowType": window.get("workflow_type"),
                    "workflowName": window.get("workflow_name"),
                    "promptId": window.get("prompt_id"),
                    "promptText": window.get("prompt_text"),
                    "hasWorkflowJson": window.get("workflow_json") is not None,
                    "referenceImages": parse_reference_images(window.get("reference_images")),
                    "videoUrl": video_url,
                    "sourceVideoUrl": window.get("source_video_url"),
                    "audioStatus": window.get("audio_status"),
                    "audioMessage": window.get("audio_message"),
                    "driveAudioUrl": window.get("drive_audio_url"),
                    "finalAudioUrl": window.get("final_audio_url"),
                    "clipAudioDuration": window.get("clip_audio_duration"),
                    "errorMessage": window.get("error_message") or (task.error_message if task.status == "failed" and status == "FAILED" else None),
                    "generatedAt": window.get("generated_at"),
                    "dialogueCount": len(window.get("clip_dialogues") or []) if isinstance(window.get("clip_dialogues"), list) else None,
                })
            return clips

        def chapter_completion(task):
            if task.type!='chapter_video':return None
            value=parse_metadata(getattr(task,'metadata_json',None)) or {};result=value.get('result') or {}
            manifest=value.get('completion_manifest')
            from app.services.chapter_asset_parse_service import digest
            if (task.status!='completed' or task.result_url!=result.get('url')
                    or value.get('execution_purpose')!='production' or value.get('delivery_mode')!='CHAPTER_COMPLETION'
                    or not isinstance(manifest,dict) or digest(manifest)!=value.get('manifest_hash')
                    or result.get('manifestHash')!=value.get('manifest_hash')
                    or result.get('outcome') not in {'SUCCEEDED','SUCCEEDED_WITH_DEGRADATION'}):return None
            return {key:result.get(key) for key in ('outcome','manifestHash','normalCount','degradedCount','degradedRanges')}
        return [
            {
                "id": t.id,
                **TaskService.format_execution_purpose(t),
                **TaskService.format_video_execution(t),
                "type": t.type,
                "name": t.name,
                "description": t.description,
                "status": t.status,
                "progress": t.progress,
                "currentStep": t.current_step,
                "resultUrl": t.result_url,
                "errorMessage": t.error_message,
                "workflowId": t.workflow_id,
                "workflowName": t.workflow_name,
                "workflowIsSystem": workflows.get(
                    t.workflow_id).is_system if t.workflow_id and t.workflow_id in workflows else False,
                "hasWorkflowJson": t.workflow_json is not None,
                "hasPromptText": t.prompt_text is not None,
                "referenceImages": parse_reference_images(t.reference_images),
                "videoDirectorClips": format_video_director_clips(t),
                "novelId": t.novel_id,
                "novelName": novels.get(t.novel_id).title if t.novel_id and t.novel_id in novels else None,
                "chapterId": t.chapter_id,
                "chapterTitle": chapters.get(t.chapter_id).title if t.chapter_id and t.chapter_id in chapters else None,
                "characterId": t.character_id,
                "sceneId": t.scene_id,
                "shotId": t.shot_id,
                "parentTaskId": getattr(t, "parent_task_id", None),
                "batchOrder": getattr(t, "batch_order", None),
                "reviewFindings": public_review_findings(t),
                "metadata": parse_metadata(getattr(t, "metadata_json", None)) if t.type in {
                    "shot_video_batch", "shot_image_batch", "audio_prepare"} else None,
                "chapterCompletion":chapter_completion(t),
                "evidence": {field:public_evidence(task_field(getattr(t,field,None),field),False)
                             for field,expected in [('metadata_json',dict),('reference_images',list),('video_director_clips',list)]},
                "createdAt": format_datetime(t.created_at),
                "startedAt": format_datetime(t.started_at),
                "completedAt": format_datetime(t.completed_at),
            }
            for t in tasks
        ]
    
    @staticmethod
    def format_task_detail(task: Task) -> dict:
        """
        格式化任务详情响应
        
        Args:
            task: 任务对象
            
        Returns:
            格式化后的任务详情
        """
        from app.services.evidence_reader import task_evidence,public_evidence,safe_value
        from app.services.task_execution import public_review_findings
        evidence=task_evidence(task)
        reference_images=safe_value(evidence['reference_images']['value'])
        metadata=safe_value(evidence['metadata_json']['value'])

        return {
            "id": task.id,
            **TaskService.format_execution_purpose(task),
            **TaskService.format_video_execution(task),
            "type": task.type,
            "name": task.name,
            "description": task.description,
            "status": task.status,
            "progress": task.progress,
            "currentStep": task.current_step,
            "resultUrl": task.result_url,
            "errorMessage": task.error_message,
            "workflowId": task.workflow_id,
            "workflowName": task.workflow_name,
            "workflowJson": safe_value(task.workflow_json),
            "promptText": safe_value(task.prompt_text),
            "referenceImages": reference_images,
            "metadata": metadata,
            "evidence": {key:public_evidence(value,False) for key,value in evidence.items()},
            "novelId": task.novel_id,
            "chapterId": task.chapter_id,
            "characterId": task.character_id,
            "sceneId": task.scene_id,
            "shotId": task.shot_id,
            "parentTaskId": getattr(task, "parent_task_id", None),
            "batchOrder": getattr(task, "batch_order", None),
            "reviewFindings": public_review_findings(task),
            "comfyuiPromptId": task.comfyui_prompt_id,
            "createdAt": format_datetime(task.created_at),
            "startedAt": format_datetime(task.started_at),
            "completedAt": format_datetime(task.completed_at),
        }
