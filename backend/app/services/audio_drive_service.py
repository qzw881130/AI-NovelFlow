import hashlib
import asyncio
import json
import uuid
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.constants.audio_drive import PAUSE_AFTER_SECONDS
from app.models.audio_drive import ShotAudioEvent, ShotAudioTimeline
from app.models.task import Task
from app.repositories.audio_drive import AudioDriveRepository
from app.repositories.character_repository import CharacterRepository
from app.repositories.shot_repository import ShotRepository
from app.repositories import TaskRepository, WorkflowRepository
from app.services.comfyui import ComfyUIService
from app.services.duration_contract import audio_required_duration, clip_duration as contract_clip_duration, resolved_duration, visual_required_duration
from app.services.execution_window_builder import build_natural_execution_windows
from app.services.file_storage import file_storage
from app.services.invalidation_service import InvalidationService
from app.services.video_director_plan_service import VideoDirectorPlanService
from app.utils.path_utils import url_to_local_path

ACTIVE_AUDIO_TTS_TASK_IDS: Set[str] = set()
ACTIVE_AUDIO_PREPARE_TASK_IDS: Set[str] = set()
TTS_LEASE_STALE_SECONDS = 120


class AudioDriveService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AudioDriveRepository(db)
        self.shot_repo = ShotRepository(db)

    def _hash_payload(self, payload: Any) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _event_to_response(self, event: ShotAudioEvent) -> dict:
        asset = self.repo.current_tts_asset(event.id)
        return {
            "id": event.id,
            "shotId": event.shot_id,
            "order": event.event_order,
            "type": event.event_type,
            "voiceOwnerCharacterId": event.voice_owner_character_id,
            "voiceOwnerName": event.voice_owner_name,
            "visibleSpeakerCharacterId": event.visible_speaker_character_id,
            "visibleSpeakerName": event.visible_speaker_name,
            "requiresVisibleLipsync": bool(event.requires_visible_lipsync),
            "text": event.text,
            "emotionPrompt": event.emotion_prompt,
            "pauseAfter": event.pause_after or "NONE",
            "ttsStatus": event.tts_status or "NOT_GENERATED",
            "currentTtsAsset": self._asset_to_response(asset) if asset else None,
        }

    def _asset_to_response(self, asset) -> dict:
        return {
            "id": asset.id,
            "audioEventId": asset.audio_event_id,
            "provider": asset.provider,
            "model": asset.model,
            "voiceId": asset.voice_id,
            "audioUrl": asset.audio_url,
            "audioPath": asset.audio_path,
            "durationSeconds": asset.duration_seconds,
            "sampleRate": asset.sample_rate,
            "channels": asset.channels,
            "revision": asset.revision,
            "isCurrent": asset.is_current,
            "status": asset.status,
        }

    def list_events(self, shot_id: str) -> dict:
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        events = self.repo.list_events(shot_id)
        if not events:
            events = self._seed_events_from_dialogues(shot)
        return {
            "success": True,
            "data": {
                "shotId": shot_id,
                "audioStatus": getattr(shot, "audio_status", None) or "NOT_READY",
                "events": [self._event_to_response(event) for event in events],
            },
        }

    def _seed_events_from_dialogues(self, shot) -> List[ShotAudioEvent]:
        dialogues = json.loads(shot.dialogues or "[]") if shot.dialogues else []
        if not isinstance(dialogues, list) or not dialogues:
            return []
        audio_events = []
        for index, dialogue in enumerate(dialogues, 1):
            dialogue_type = str(dialogue.get("type") or "character").lower()
            is_narration = dialogue_type == "narration" or dialogue.get("character_name") == "旁白"
            character_name = dialogue.get("character_name") or ("旁白" if is_narration else "")
            audio_events.append({
                "order": dialogue.get("order") or index,
                "type": "NARRATION" if is_narration else "DIALOGUE",
                "voice_owner": character_name,
                "visible_speaker": None if is_narration else character_name,
                "requires_visible_lipsync": not is_narration,
                "text": dialogue.get("text") or "",
                "emotion_prompt": dialogue.get("emotion_prompt") or "自然",
                "pause_after": dialogue.get("pause_after") or "NONE",
            })
        created = self.repo.replace_events(shot.id, audio_events)
        shot.audio_status = "NOT_READY"
        self.db.commit()
        return created

    def create_tts_task(self, event_id: str, force: bool = False) -> dict:
        event = self.repo.get_event(event_id)
        if not event:
            return {"success": False, "status_code": 404, "message": "Audio Event 不存在"}
        current_asset = self.repo.current_tts_asset(event_id)
        if current_asset and current_asset.status == "READY" and event.tts_status == "READY" and not force:
            return {"success": True, "data": {"eventId": event_id, "skipped": True, "currentTtsAsset": self._asset_to_response(current_asset)}}
        shot = self.shot_repo.get_by_id(event.shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        workflow = WorkflowRepository(self.db).get_active_by_type("audio")
        if not workflow:
            return {"success": False, "status_code": 400, "message": "未配置音频生成工作流"}
        task = Task(
            type="audio_event_tts",
            name=f"生成 Audio Event TTS: {event.voice_owner_name}",
            description=f"为 Audio Event {event.event_order} 生成 TTS: {(event.text or '')[:50]}",
            chapter_id=shot.chapter_id,
            shot_id=shot.id,
            character_id=event.voice_owner_character_id,
            status="pending",
            progress=0,
            current_step="等待处理",
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            metadata_json=json.dumps({"audio_event_id": event.id}, ensure_ascii=False),
        )
        task = TaskRepository(self.db).create(task)
        event.tts_status = "GENERATING"
        self._mark_shot_audio_stale(event.shot_id)
        self.db.commit()
        return {"success": True, "data": {"eventId": event_id, "taskId": task.id, "status": task.status}}

    @staticmethod
    def resume_active_tts_tasks() -> None:
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            TaskRepository(db).recover_stale_running_tasks("audio_event_tts", TTS_LEASE_STALE_SECONDS)
            tasks = db.query(Task).filter(
                Task.type == "audio_event_tts",
                Task.status == "pending",
            ).order_by(Task.created_at.asc()).all()
            for task in tasks:
                try:
                    metadata = json.loads(task.metadata_json or "{}") if task.metadata_json else {}
                except Exception:
                    metadata = {}
                event_id = metadata.get("audio_event_id")
                if not event_id:
                    continue
                event = AudioDriveRepository(db).get_event(event_id)
                if not event:
                    continue
                current_asset = AudioDriveRepository(db).current_tts_asset(event_id)
                if current_asset and current_asset.status == "READY" and event.tts_status == "READY":
                    task.status = "completed"
                    task.progress = 100
                    task.result_url = current_asset.audio_url
                    task.current_step = "TTS 已存在，恢复完成"
                    task.completed_at = task.completed_at or datetime.utcnow()
                    db.commit()
                    continue
                event.tts_status = "GENERATING"
                db.commit()
        finally:
            db.close()

    @staticmethod
    async def run_next_persistent_tts_task() -> bool:
        """Consume one AudioDrive TTS task from the DB-backed queue."""
        if ACTIVE_AUDIO_TTS_TASK_IDS:
            return False
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            worker_id = f"audio-tts-{uuid.uuid4()}"
            task = TaskRepository(db).claim_pending_task("audio_event_tts", worker_id)
            if not task:
                return False
            try:
                metadata = json.loads(task.metadata_json or "{}") if task.metadata_json else {}
            except Exception:
                metadata = {}
            event_id = metadata.get("audio_event_id")
            if not event_id or not task.workflow_id:
                task.status = "failed"
                task.error_message = "Audio Event TTS 任务缺少持久化队列元数据"
                task.current_step = "任务元数据无效"
                task.completed_at = datetime.utcnow()
                db.commit()
                return True
            task_id = task.id
            workflow_id = task.workflow_id
            claim_token = task.claim_token
        finally:
            db.close()

        ACTIVE_AUDIO_TTS_TASK_IDS.add(task_id)
        try:
            await AudioDriveService._run_tts_task(task_id, event_id, workflow_id, claim_token)
        finally:
            ACTIVE_AUDIO_TTS_TASK_IDS.discard(task_id)
        return True

    def create_batch_tts_tasks(self, shot_id: str, event_ids: Optional[List[str]] = None, only_stale: bool = True, force: bool = False) -> dict:
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        events = self.repo.list_events(shot_id)
        allowed = set(event_ids or [])
        tasks = []
        for event in events:
            if allowed and event.id not in allowed:
                continue
            if event.tts_status == "GENERATING" and not force:
                continue
            if only_stale and event.tts_status == "READY" and not force:
                continue
            result = self.create_tts_task(event.id, force=force)
            if result.get("success"):
                tasks.append(result.get("data"))
        return {"success": True, "message": f"已提交 {len(tasks)} 个 TTS 任务", "data": {"tasks": tasks}}

    def create_audio_prepare_task(
        self,
        shot_ids: List[str],
        max_clip_duration: Optional[float] = None,
        force_tts: bool = False,
        force_clip_audio: bool = True,
    ) -> dict:
        unique_shot_ids = []
        for shot_id in shot_ids or []:
            if shot_id and shot_id not in unique_shot_ids:
                unique_shot_ids.append(shot_id)
        if not unique_shot_ids:
            return {"success": False, "status_code": 400, "message": "请选择要准备音频的分镜"}

        shots = []
        for shot_id in unique_shot_ids:
            shot = self.shot_repo.get_by_id(shot_id)
            if not shot:
                return {"success": False, "status_code": 404, "message": f"分镜不存在: {shot_id}"}
            shots.append(shot)

        chapter_id = shots[0].chapter_id if shots else None
        novel_id = shots[0].chapter.novel_id if shots and shots[0].chapter else None
        task = Task(
            type="audio_prepare",
            name=f"准备 AudioDrive 音频: {len(shots)} 个分镜",
            description="持久化执行 TTS、Audio Timeline、执行窗口和 Clip Audio 准备",
            novel_id=novel_id,
            chapter_id=chapter_id,
            shot_id=shots[0].id if len(shots) == 1 else None,
            status="pending",
            progress=0,
            current_step="等待准备音频",
            metadata_json=json.dumps({
                "shot_ids": unique_shot_ids,
                "max_clip_duration": max_clip_duration,
                "force_tts": force_tts,
                "force_clip_audio": force_clip_audio,
            }, ensure_ascii=False),
        )
        task = TaskRepository(self.db).create(task)
        return {"success": True, "data": {"taskId": task.id, "status": task.status, "shotIds": unique_shot_ids}}

    @staticmethod
    def resume_active_audio_prepare_tasks() -> None:
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            tasks = db.query(Task).filter(
                Task.type == "audio_prepare",
                Task.status == "running",
            ).order_by(Task.created_at.asc()).all()
            for task in tasks:
                task.status = "pending"
                task.progress = min(int(task.progress or 0), 95)
                task.current_step = "等待恢复音频准备"
            db.commit()
        finally:
            db.close()

    @staticmethod
    async def run_next_persistent_audio_prepare_task() -> bool:
        if ACTIVE_AUDIO_PREPARE_TASK_IDS:
            return False
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            task = db.query(Task).filter(
                Task.type == "audio_prepare",
                Task.status == "pending",
            ).order_by(Task.created_at.asc()).first()
            if not task:
                return False
            task_id = task.id
        finally:
            db.close()

        ACTIVE_AUDIO_PREPARE_TASK_IDS.add(task_id)
        try:
            await AudioDriveService._run_audio_prepare_task(task_id)
        finally:
            ACTIVE_AUDIO_PREPARE_TASK_IDS.discard(task_id)
        return True

    @staticmethod
    async def _wait_for_prepare_tts_ready(service: "AudioDriveService", shot_id: str, task: Task, shot_index: int) -> None:
        for _ in range(600):
            events = service.repo.list_events(shot_id)
            if not events:
                return
            failed = [event for event in events if event.tts_status == "FAILED"]
            if failed:
                raise RuntimeError(f"镜 {shot_index} 存在 TTS 失败事件")
            if all(event.tts_status == "READY" for event in events):
                return
            task.current_step = f"镜 {shot_index}：等待 TTS READY"
            service.db.commit()
            await asyncio.sleep(2)
        raise RuntimeError(f"镜 {shot_index} 等待 TTS READY 超时")

    @staticmethod
    async def _run_audio_prepare_task(task_id: str) -> None:
        from app.core.database import SessionLocal

        db = SessionLocal()
        service = AudioDriveService(db)
        task_repo = TaskRepository(db)
        try:
            task = task_repo.get_by_id(task_id)
            if not task or task.status in {"completed", "cancelled"}:
                return
            metadata = json.loads(task.metadata_json or "{}") if task.metadata_json else {}
            shot_ids = metadata.get("shot_ids") or []
            max_clip_duration = metadata.get("max_clip_duration")
            force_tts = bool(metadata.get("force_tts"))
            force_clip_audio = bool(metadata.get("force_clip_audio", True))
            if not shot_ids:
                task.status = "failed"
                task.error_message = "音频准备任务缺少 shot_ids"
                task.completed_at = datetime.utcnow()
                db.commit()
                return

            task.status = "running"
            task.started_at = task.started_at or datetime.utcnow()
            task.current_step = "开始准备音频"
            task.progress = 1
            db.commit()

            failures = []
            total = len(shot_ids)
            for index, shot_id in enumerate(shot_ids, 1):
                shot = service.shot_repo.get_by_id(shot_id)
                if not shot:
                    failures.append({"shotId": shot_id, "error": "分镜不存在"})
                    continue
                base_progress = int(((index - 1) / total) * 100)
                try:
                    task.current_step = f"镜 {shot.index}：提交 TTS"
                    task.progress = min(99, max(task.progress or 0, base_progress + 2))
                    db.commit()
                    result = service.create_batch_tts_tasks(shot_id, only_stale=not force_tts, force=force_tts)
                    if not result.get("success"):
                        raise RuntimeError(result.get("message") or "提交 TTS 失败")
                    await AudioDriveService._wait_for_prepare_tts_ready(service, shot_id, task, shot.index)

                    task.current_step = f"镜 {shot.index}：构建 Timeline"
                    task.progress = min(99, max(task.progress or 0, base_progress + 35))
                    db.commit()
                    result = service.build_timeline(shot_id, force=True)
                    if not result.get("success"):
                        raise RuntimeError(result.get("message") or "构建 Timeline 失败")

                    task.current_step = f"镜 {shot.index}：构建执行窗口"
                    task.progress = min(99, max(task.progress or 0, base_progress + 50))
                    db.commit()
                    result = service.build_execution_windows(shot_id, max_clip_duration=max_clip_duration)
                    if not result.get("success"):
                        raise RuntimeError(result.get("message") or "构建执行窗口失败")
                    windows = result.get("data", {}).get("executionWindows") or []
                    if not windows:
                        raise RuntimeError("未生成执行窗口")

                    for window in windows:
                        window_index = int(window.get("windowIndex") or window.get("window_index") or 0)
                        if not window_index:
                            continue
                        task.current_step = f"镜 {shot.index}：构建 Clip {window_index} Audio"
                        db.commit()
                        result = service.build_clip_audio(shot_id, window_index, force=force_clip_audio)
                        if not result.get("success"):
                            raise RuntimeError(result.get("message") or f"构建 Clip {window_index} Audio 失败")
                    task.progress = min(99, int((index / total) * 100))
                    db.commit()
                except Exception as exc:
                    failures.append({"shotId": shot_id, "shotIndex": shot.index, "error": str(exc)})
                    db.commit()

            metadata["result"] = {"total": total, "failed": failures, "succeeded": total - len(failures)}
            task.metadata_json = json.dumps(metadata, ensure_ascii=False)
            task.completed_at = datetime.utcnow()
            if failures:
                task.status = "failed"
                task.error_message = f"音频准备完成但有 {len(failures)} 个分镜失败"
                task.current_step = "音频准备部分失败"
            else:
                task.status = "completed"
                task.progress = 100
                task.current_step = "音频准备完成"
            db.commit()
        except Exception as exc:
            task = task_repo.get_by_id(task_id)
            if task:
                task.status = "failed"
                task.error_message = str(exc)
                task.current_step = "音频准备任务异常"
                task.completed_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

    def patch_event(self, event_id: str, data: dict) -> dict:
        event = self.repo.get_event(event_id)
        if not event:
            return {"success": False, "status_code": 404, "message": "Audio Event 不存在"}

        tts_stale_fields = {"voiceOwnerCharacterId", "voiceOwnerName", "text", "emotionPrompt"}
        timeline_stale_fields = tts_stale_fields | {"visibleSpeakerCharacterId", "visibleSpeakerName", "requiresVisibleLipsync", "pauseAfter"}
        changed = set()

        mapping = {
            "voiceOwnerCharacterId": "voice_owner_character_id",
            "voiceOwnerName": "voice_owner_name",
            "visibleSpeakerCharacterId": "visible_speaker_character_id",
            "visibleSpeakerName": "visible_speaker_name",
            "requiresVisibleLipsync": "requires_visible_lipsync",
            "text": "text",
            "emotionPrompt": "emotion_prompt",
            "pauseAfter": "pause_after",
        }
        for api_key, attr in mapping.items():
            if api_key not in data or data[api_key] is None:
                continue
            value = data[api_key]
            if api_key == "pauseAfter":
                value = str(value).upper()
            if getattr(event, attr) != value:
                setattr(event, attr, value)
                changed.add(api_key)

        if changed & tts_stale_fields:
            event.tts_status = "STALE"
            event.text_hash = None
            self.repo._mark_current_tts_assets_stale(event.id)
        if changed & timeline_stale_fields:
            level = "SPEAKER_BINDING_CHANGED" if changed <= {"visibleSpeakerCharacterId", "visibleSpeakerName", "requiresVisibleLipsync"} else "AUDIO_TIMING_CHANGED"
            self._mark_shot_audio_stale(event.shot_id, level=level)

        self.db.commit()
        self.db.refresh(event)
        return {"success": True, "data": self._event_to_response(event)}

    def _mark_shot_audio_stale(self, shot_id: str, level: str = "AUDIO_TIMING_CHANGED") -> None:
        InvalidationService(self.db).invalidate_audio_downstream(
            shot_id,
            reason="Audio Event 变更，AudioDrive 下游产物已失效",
            level=level,
        )

    @staticmethod
    async def _run_tts_task(task_id: str, event_id: str, workflow_id: str, claim_token: str) -> None:
        from app.core.database import SessionLocal

        db = SessionLocal()
        service = AudioDriveService(db)
        task_repo = TaskRepository(db)
        def claim_current() -> bool:
            return bool(claim_token and task_repo.task_claim_is_current(task_id, claim_token))

        def update_task(fields: dict) -> bool:
            return task_repo.update_claimed_task(task_id, claim_token, fields)

        def fail_task(message: str, step: str = "任务异常") -> None:
            if not claim_current():
                return
            event = service.repo.get_event(event_id)
            if event:
                event.tts_status = "FAILED"
            update_task({
                "status": "failed",
                "error_message": message,
                "current_step": step,
                "completed_at": datetime.utcnow(),
            })

        try:
            task = task_repo.get_by_id(task_id)
            event = service.repo.get_event(event_id)
            workflow = WorkflowRepository(db).get_by_id(workflow_id)
            if not task or not event or not workflow:
                return
            if not claim_current():
                return
            current_asset = service.repo.current_tts_asset(event.id)
            if current_asset and current_asset.status == "READY" and event.tts_status == "READY":
                update_task({
                    "status": "completed",
                    "progress": 100,
                    "result_url": current_asset.audio_url,
                    "current_step": "TTS 已存在，跳过生成",
                    "completed_at": task.completed_at or datetime.utcnow(),
                })
                return
            shot = service.shot_repo.get_by_id(event.shot_id)
            if not shot:
                fail_task("分镜不存在", "分镜不存在")
                return
            if not update_task({"current_step": "准备参考音色"}):
                return

            character = None
            char_repo = CharacterRepository(db)
            if event.voice_owner_character_id:
                character = char_repo.get_by_id(event.voice_owner_character_id)
            if not character and event.voice_owner_name:
                character = char_repo.get_by_name(shot.chapter.novel_id, event.voice_owner_name)
            if not character or not character.reference_audio_url:
                fail_task(f"声音角色 '{event.voice_owner_name}' 未配置参考音色", "缺少参考音色")
                return

            reference_path = url_to_local_path(character.reference_audio_url)
            if not reference_path:
                fail_task("参考音色文件不存在或不是本地文件", "参考音色不可用")
                return

            comfy = ComfyUIService()
            if not task_repo.heartbeat_task(task_id, claim_token):
                return
            upload_result = await comfy.client.upload_audio(str(reference_path))
            if not upload_result.get("success"):
                fail_task(upload_result.get("message") or "上传参考音色失败", "上传参考音色失败")
                return
            if not task_repo.heartbeat_task(task_id, claim_token):
                return

            node_mapping = json.loads(workflow.node_mapping or "{}") if workflow.node_mapping else {}
            submitted_workflow = comfy.builder.build_audio_workflow(
                text=event.text,
                workflow_json=workflow.workflow_json,
                novel_id=shot.chapter.novel_id,
                character_name=event.voice_owner_name,
                node_mapping=node_mapping,
                reference_audio_filename=upload_result.get("filename"),
                emotion_prompt=event.emotion_prompt or "自然",
            )
            if not update_task({
                "workflow_json": json.dumps(submitted_workflow, ensure_ascii=False, indent=2),
                "prompt_text": f"Audio Event: {event.id}\n角色: {event.voice_owner_name}\n文本: {event.text}\n情感: {event.emotion_prompt or '自然'}",
                "current_step": "提交 ComfyUI 音频生成",
            }):
                return

            queue_result = await comfy.client.queue_prompt(submitted_workflow)
            if not queue_result.get("success"):
                fail_task(queue_result.get("error") or "提交任务失败", "提交任务失败")
                return
            if not update_task({"comfyui_prompt_id": queue_result.get("prompt_id"), "current_step": "正在生成 TTS"}):
                return

            result = await comfy.client.wait_for_audio_result(
                queue_result.get("prompt_id"),
                submitted_workflow,
                node_mapping.get("save_audio_node_id"),
                timeout=600,
            )
            if not result.get("success"):
                fail_task(result.get("message") or "生成失败", "生成失败")
                return
            if not task_repo.heartbeat_task(task_id, claim_token):
                return

            remote_url = result.get("audio_url")
            local_path = await file_storage.download_audio(
                url=remote_url,
                novel_id=shot.chapter.novel_id,
                character_name=f"event_{event.event_order}_{event.voice_owner_name}",
                audio_type="audio_event",
            )
            audio_url = remote_url
            duration = result.get("duration")
            if local_path:
                relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                audio_url = f"/api/files/{relative_path.lstrip('/')}"
                duration = duration or AudioDriveService._probe_audio_duration(local_path)
            if not claim_current():
                return
            asset = service.repo.add_tts_asset(
                event.id,
                commit=False,
                provider="comfyui",
                model=workflow.name,
                voice_id=character.id,
                audio_url=audio_url,
                audio_path=local_path,
                duration_seconds=duration,
                text_hash=service._hash_payload({"text": event.text}),
                config_json=json.dumps({"emotion_prompt": event.emotion_prompt}, ensure_ascii=False),
                status="READY",
            )
            event.tts_status = "READY"
            event.voice_owner_character_id = character.id
            if not update_task({
                "status": "completed",
                "progress": 100,
                "result_url": asset.audio_url,
                "current_step": "TTS 生成完成",
                "completed_at": datetime.utcnow(),
            }):
                return
            db.commit()
        except Exception as exc:
            fail_task(str(exc), "任务异常")
        finally:
            db.close()

    @staticmethod
    def _probe_audio_duration(path: str) -> Optional[float]:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True,
                text=True,
                check=False,
            )
            value = float((result.stdout or "").strip())
            return round(value, 3) if value > 0 else None
        except Exception:
            return None

    def build_timeline(self, shot_id: str, force: bool = False) -> dict:
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        current = self.repo.latest_timeline(shot_id)
        if current and current.status == "READY" and not force:
            return {"success": True, "data": self._timeline_to_response(current)}

        events = self.repo.list_events(shot_id)
        timeline_events = []
        cursor = 0.0
        missing = []
        speaker_switch_count = 0
        previous_speaker = None

        for event in events:
            asset = self.repo.current_tts_asset(event.id)
            if not asset or asset.status != "READY" or not asset.duration_seconds:
                missing.append(event.id)
                continue
            start = cursor
            end = start + float(asset.duration_seconds)
            visible = event.visible_speaker_name if event.requires_visible_lipsync else None
            if visible and previous_speaker and visible != previous_speaker:
                speaker_switch_count += 1
            if visible:
                previous_speaker = visible
            timeline_events.append({
                "audio_event_id": event.id,
                "event_order": event.event_order,
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "event_type": event.event_type,
                "voice_owner_character_id": event.voice_owner_character_id,
                "voice_owner_name": event.voice_owner_name,
                "visible_speaker_character_id": event.visible_speaker_character_id,
                "visible_speaker_name": visible,
                "requires_visible_lipsync": bool(event.requires_visible_lipsync),
                "tts_asset_id": asset.id,
            })
            cursor = end + PAUSE_AFTER_SECONDS.get((event.pause_after or "NONE").upper(), 0.0)

        if missing:
            return {
                "success": False,
                "status_code": 400,
                "message": "存在未 READY 的 TTS 资产，请先生成音频",
                "data": {"missingEventIds": missing},
            }

        if shot.estimated_duration is None:
            shot.estimated_duration = shot.duration or 4
        audio_duration = audio_required_duration(cursor)
        visual_duration = visual_required_duration(shot)
        total_duration = resolved_duration(shot, None, default=visual_duration)
        total_duration = max(total_duration, audio_duration)
        summary = {
            "event_count": len(events),
            "visual_required_duration": visual_duration,
            "audio_required_duration": audio_duration,
            "resolved_duration": round(total_duration, 3),
            "has_visible_dialogue": any(event.requires_visible_lipsync for event in events),
            "visible_speaker_count": len({event.visible_speaker_name for event in events if event.requires_visible_lipsync and event.visible_speaker_name}),
            "speaker_switch_count": speaker_switch_count,
            "has_narration": any(event.event_type == "NARRATION" for event in events),
            "has_inner_monologue": any(event.event_type == "INNER_MONOLOGUE" for event in events),
        }
        source_hash = self._hash_payload({
            "events": [self._event_to_response(event) for event in events],
            "assets": [self._asset_to_response(self.repo.current_tts_asset(event.id)) for event in events],
        })
        timeline = self.repo.create_timeline(shot_id, round(total_duration, 3), source_hash, summary, timeline_events, audio_required_duration=audio_duration)
        InvalidationService(self.db).invalidate_audio_downstream(
            shot_id,
            reason="Audio Timeline 已重建，视频下游产物已失效",
            level="AUDIO_TIMING_CHANGED",
            mark_audio_stale=False,
            mark_timeline_stale=False,
        )
        shot.audio_status = "READY"
        audio_timeline_plan = {
            "id": timeline.id,
            "revision": timeline.revision,
            "source_hash": timeline.generated_from_hash,
            "audio_required_duration": audio_duration,
            "resolved_duration": round(total_duration, 3),
            "audio_summary": summary,
            "events": self._timeline_to_response(timeline).get("events") or [],
        }
        VideoDirectorPlanService(self.db).mutate(
            shot_id,
            lambda plan: {**plan, "audio_timeline": audio_timeline_plan},
        )
        return {"success": True, "data": self._timeline_to_response(timeline)}

    def get_timeline(self, shot_id: str) -> dict:
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        timeline = self.repo.latest_timeline(shot_id)
        if not timeline:
            return {"success": True, "data": None}
        return {"success": True, "data": self._timeline_to_response(timeline)}

    def _timeline_to_response(self, timeline: ShotAudioTimeline) -> dict:
        events = self.repo.list_timeline_events(timeline.id)
        source_events = {event.id: event for event in self.repo.list_events(timeline.shot_id)}
        return {
            "id": timeline.id,
            "shotId": timeline.shot_id,
            "revision": timeline.revision,
            "totalDuration": timeline.total_duration,
            "audioRequiredDuration": timeline.audio_required_duration,
            "status": timeline.status,
            "audioSummary": json.loads(timeline.audio_summary_json or "{}"),
            "events": [
                {
                    "audioEventId": event.audio_event_id,
                    "order": event.event_order,
                    "startTime": event.start_time,
                    "endTime": event.end_time,
                    "type": event.event_type,
                    "voiceOwnerName": event.voice_owner_name,
                    "visibleSpeakerName": event.visible_speaker_name,
                    "requiresVisibleLipsync": bool(event.requires_visible_lipsync),
                    "text": source_events.get(event.audio_event_id).text if source_events.get(event.audio_event_id) else "",
                    "ttsAssetId": event.tts_asset_id,
                }
                for event in events
            ],
        }

    def build_execution_windows(self, shot_id: str, max_clip_duration: Optional[float] = None) -> dict:
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        timeline = self.repo.latest_timeline(shot_id)
        if not timeline or timeline.status != "READY":
            return {"success": False, "status_code": 400, "message": "Audio Timeline 未 READY"}
        duration = resolved_duration(shot, timeline)
        max_duration = float(max_clip_duration or 15)
        timeline_events = [
            {
                "start_time": event.start_time,
                "end_time": event.end_time,
                "type": event.event_type,
                "requires_visible_lipsync": bool(event.requires_visible_lipsync),
            }
            for event in self.repo.list_timeline_events(timeline.id)
        ]
        windows = build_natural_execution_windows(duration, max_duration, timeline_events)
        plan = json.loads(shot.video_director_plan or "{}") if shot.video_director_plan else {}
        existing_window_plans = plan.get("window_plans") or []
        windows_changed = len(existing_window_plans) != len(windows) or any(
            not isinstance(existing, dict)
            or abs(float(existing.get("start_time") or 0) - float(window.get("start_time") or 0)) > 0.001
            or abs(float(existing.get("end_time") or 0) - float(window.get("end_time") or 0)) > 0.001
            for existing, window in zip(existing_window_plans, windows)
        )
        merged_window_plans = []
        for window in windows:
            existing = next((item for item in existing_window_plans if (
                isinstance(item, dict)
                and int(item.get("window_index") or item.get("index") or 0) == int(window["window_index"])
                and float(item.get("start_time") or 0) == float(window["start_time"])
                and float(item.get("end_time") or 0) == float(window["end_time"])
            )), None)
            merged_window_plans.append({**existing, **window} if existing else window)
        def mutate_plan(plan: dict) -> dict:
            plan["execution_windows"] = windows
            plan["window_plans"] = merged_window_plans
            if windows_changed:
                plan["keyframes"] = []
                plan["keyframe_planning_status"] = "STALE"
                plan["keyframe_planning_message"] = "AudioDrive 重新构建了 execution_windows，请重新规划关键帧。"
            return plan

        VideoDirectorPlanService(self.db).mutate(shot_id, mutate_plan)
        return {"success": True, "data": {"shotId": shot_id, "executionWindows": windows}}

    def build_clip_audio(self, shot_id: str, window_index: int, force: bool = False) -> dict:
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        timeline = self.repo.latest_timeline(shot_id)
        if not timeline or timeline.status != "READY":
            return {"success": False, "status_code": 400, "message": "Audio Timeline 未 READY"}
        plan = json.loads(shot.video_director_plan or "{}") if shot.video_director_plan else {}
        windows = plan.get("window_plans") or plan.get("execution_windows") or []
        window = next((item for item in windows if int(item.get("window_index") or item.get("index") or 0) == window_index), None)
        if not window:
            return {"success": False, "status_code": 404, "message": "Clip window 不存在"}
        start = float(window.get("start_time") or 0)
        end = float(window.get("end_time") or start)
        clip_duration = contract_clip_duration(start, end)
        if clip_duration <= 0:
            return {"success": False, "status_code": 400, "message": "Clip window 时长无效"}

        drive_path = file_storage.get_clip_audio_path(shot.chapter.novel_id, shot.chapter_id, shot.id, window_index, "drive_audio")
        final_path = file_storage.get_clip_audio_path(shot.chapter.novel_id, shot.chapter_id, shot.id, window_index, "final_audio")
        manifest_path = file_storage.get_clip_audio_path(shot.chapter.novel_id, shot.chapter_id, shot.id, window_index, "manifest", ext=".json")
        timeline_revision = int(timeline.revision or 0)
        timeline_hash = timeline.generated_from_hash

        bound_revision = window.get("audio_timeline_revision") or window.get("audioTimelineRevision")
        bound_hash = window.get("audio_timeline_hash") or window.get("audioTimelineHash")
        cache_matches_timeline = (
            window.get("audio_timeline_id") == timeline.id
            and int(bound_revision or 0) == timeline_revision
            and (not timeline_hash or bound_hash == timeline_hash)
        )
        if not force and window.get("audio_status") == "READY" and cache_matches_timeline and drive_path.exists() and final_path.exists():
            return {
                "success": True,
                "data": {
                    "shotId": shot_id,
                    "windowIndex": window_index,
                    "audioTimelineId": timeline.id,
                    "audioTimelineRevision": timeline_revision,
                    "audioTimelineHash": timeline_hash,
                    "speakerTimeline": window.get("speaker_timeline") or [],
                    "audioStatus": "READY",
                    "driveAudioUrl": window.get("drive_audio_url") or self._path_to_file_url(drive_path),
                    "finalAudioUrl": window.get("final_audio_url") or self._path_to_file_url(final_path),
                    "message": "Clip Audio 已存在",
                },
            }

        speaker_timeline = self._build_speaker_timeline(timeline, start, end)
        final_collection = self._collect_clip_audio_segments(timeline, start, end, drive_only=False)
        drive_collection = self._collect_clip_audio_segments(timeline, start, end, drive_only=True)
        missing_segments = final_collection["missing"] + drive_collection["missing"]
        if missing_segments:
            return {
                "success": False,
                "status_code": 400,
                "message": "Clip Audio 所需 TTS 资产缺失或不可用，请重新生成 TTS。",
                "data": {"missingSegments": missing_segments},
            }
        final_segments = final_collection["segments"]
        drive_segments = drive_collection["segments"]

        final_result = self._render_clip_audio(final_segments, final_path, clip_duration)
        if not final_result.get("success"):
            return final_result
        drive_result = self._render_clip_audio(drive_segments, drive_path, clip_duration)
        if not drive_result.get("success"):
            return drive_result

        manifest = {
            "shot_id": shot_id,
            "window_index": window_index,
            "audio_timeline_id": timeline.id,
            "audio_timeline_revision": timeline_revision,
            "audio_timeline_hash": timeline_hash,
            "clip_start": start,
            "clip_end": end,
            "clip_duration": clip_duration,
            "drive_audio_path": str(drive_path),
            "final_audio_path": str(final_path),
            "speaker_timeline": speaker_timeline,
            "final_segments": final_segments,
            "drive_segments": drive_segments,
            "generated_at": datetime.utcnow().isoformat(),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        window["audio_timeline_id"] = timeline.id
        window["audio_timeline_revision"] = timeline_revision
        window["audio_timeline_hash"] = timeline_hash
        window["speaker_timeline"] = speaker_timeline
        window["audio_status"] = "READY"
        window["audio_message"] = "Clip Audio READY"
        window["drive_audio_url"] = self._path_to_file_url(drive_path)
        window["final_audio_url"] = self._path_to_file_url(final_path)
        window["drive_audio_path"] = str(drive_path)
        window["final_audio_path"] = str(final_path)
        window["clip_audio_manifest_path"] = str(manifest_path)
        window["clip_audio_duration"] = clip_duration
        audio_fields = {
            "audio_timeline_id": timeline.id,
            "audio_timeline_revision": timeline_revision,
            "audio_timeline_hash": timeline_hash,
            "speaker_timeline": speaker_timeline,
            "audio_status": window["audio_status"],
            "audio_message": window["audio_message"],
            "drive_audio_url": window["drive_audio_url"],
            "final_audio_url": window["final_audio_url"],
            "drive_audio_path": window["drive_audio_path"],
            "final_audio_path": window["final_audio_path"],
            "clip_audio_manifest_path": window["clip_audio_manifest_path"],
            "clip_audio_duration": clip_duration,
        }

        def mutate_audio_window(latest: dict) -> dict:
            latest_windows = latest.get("window_plans") if isinstance(latest.get("window_plans"), list) else []
            for item in latest_windows:
                if isinstance(item, dict) and int(item.get("window_index") or item.get("index") or 0) == window_index:
                    item.update(audio_fields)
                    break
            else:
                latest_windows.append({**window, **audio_fields})
            latest["window_plans"] = latest_windows
            return latest

        VideoDirectorPlanService(self.db).mutate(shot_id, mutate_audio_window)
        return {
            "success": True,
            "data": {
                "shotId": shot_id,
                "windowIndex": window_index,
                "audioTimelineId": timeline.id,
                "audioTimelineRevision": timeline_revision,
                "audioTimelineHash": timeline_hash,
                "speakerTimeline": speaker_timeline,
                "audioStatus": window["audio_status"],
                "driveAudioUrl": window["drive_audio_url"],
                "finalAudioUrl": window["final_audio_url"],
                "message": window["audio_message"],
            },
        }

    def _path_to_file_url(self, path: Path) -> str:
        relative_path = str(path).replace(str(file_storage.base_dir), "").replace("\\", "/")
        return f"/api/files/{relative_path.lstrip('/')}"

    def _collect_clip_audio_segments(self, timeline: ShotAudioTimeline, clip_start: float, clip_end: float, drive_only: bool) -> dict:
        segments = []
        missing = []
        for event in self.repo.list_timeline_events(timeline.id):
            if drive_only and (not event.requires_visible_lipsync or not event.visible_speaker_name):
                continue
            overlap_start = max(float(event.start_time), clip_start)
            overlap_end = min(float(event.end_time), clip_end)
            if overlap_end <= overlap_start:
                continue
            if not event.tts_asset_id:
                missing.append({"audio_event_id": event.audio_event_id, "reason": "missing_tts_asset_id", "track": "drive" if drive_only else "final"})
                continue
            asset = self.repo.get_tts_asset(event.tts_asset_id)
            if not asset or asset.status != "READY":
                missing.append({"audio_event_id": event.audio_event_id, "tts_asset_id": event.tts_asset_id, "reason": "tts_asset_not_ready", "track": "drive" if drive_only else "final"})
                continue
            source_path = asset.audio_path or url_to_local_path(asset.audio_url or "")
            if not source_path or not Path(source_path).is_file():
                missing.append({"audio_event_id": event.audio_event_id, "tts_asset_id": event.tts_asset_id, "reason": "tts_file_missing", "track": "drive" if drive_only else "final"})
                continue
            segments.append({
                "source_path": str(source_path),
                "audio_event_id": event.audio_event_id,
                "tts_asset_id": event.tts_asset_id,
                "event_order": event.event_order,
                "source_start": round(overlap_start - float(event.start_time), 3),
                "duration": round(overlap_end - overlap_start, 3),
                "clip_start": round(overlap_start - clip_start, 3),
                "voice_owner_name": event.voice_owner_name,
                "visible_speaker_name": event.visible_speaker_name,
                "requires_visible_lipsync": bool(event.requires_visible_lipsync),
            })
        return {"segments": segments, "expected_count": len(segments) + len(missing), "missing": missing}

    def _render_clip_audio(self, segments: list, output_path: Path, duration: float) -> dict:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not segments:
            cmd = [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", f"{duration:.3f}",
                "-acodec", "pcm_s16le",
                str(output_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                return {"success": False, "status_code": 500, "message": result.stderr or "生成静音 Clip Audio 失败"}
            return {"success": True}

        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        for segment in segments:
            cmd.extend(["-i", segment["source_path"]])

        filters = [f"[0:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[base]"]
        mix_inputs = ["[base]"]
        for index, segment in enumerate(segments, 1):
            delay_ms = int(round(float(segment["clip_start"]) * 1000))
            source_start = float(segment["source_start"])
            segment_duration = float(segment["duration"])
            label = f"a{index}"
            filters.append(
                f"[{index}:a]atrim=start={source_start:.3f}:duration={segment_duration:.3f},"
                f"asetpts=PTS-STARTPTS,aresample=44100,aformat=sample_fmts=s16:channel_layouts=stereo,"
                f"adelay={delay_ms}|{delay_ms}[{label}]"
            )
            mix_inputs.append(f"[{label}]")
        filters.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0,atrim=0:{duration:.3f}[out]")
        cmd.extend(["-filter_complex", ";".join(filters), "-map", "[out]", "-acodec", "pcm_s16le", str(output_path)])

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return {"success": False, "status_code": 500, "message": result.stderr or "生成 Clip Audio 失败"}
        return {"success": True}

    def _build_speaker_timeline(self, timeline: ShotAudioTimeline, clip_start: float, clip_end: float) -> list:
        segments = []
        cursor = 0.0
        for event in self.repo.list_timeline_events(timeline.id):
            if not event.requires_visible_lipsync or not event.visible_speaker_name:
                continue
            overlap_start = max(float(event.start_time), clip_start)
            overlap_end = min(float(event.end_time), clip_end)
            if overlap_end <= overlap_start:
                continue
            local_start = round(overlap_start - clip_start, 3)
            local_end = round(overlap_end - clip_start, 3)
            if local_start > cursor:
                segments.append({"start_time": cursor, "end_time": local_start, "visible_speaker": "NONE"})
            segments.append({"start_time": local_start, "end_time": local_end, "visible_speaker": event.visible_speaker_name})
            cursor = local_end
        clip_duration = round(clip_end - clip_start, 3)
        if cursor < clip_duration:
            segments.append({"start_time": cursor, "end_time": clip_duration, "visible_speaker": "NONE"})
        return segments or [{"start_time": 0.0, "end_time": clip_duration, "visible_speaker": "NONE"}]
