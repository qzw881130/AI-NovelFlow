import hashlib
import asyncio
import json
import math
import re
import uuid
import subprocess
import shutil
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session
from fastapi import HTTPException

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
from app.services.chapter_asset_parse_service import digest
from app.services.invalidation_service import InvalidationService
from app.services.video_director_plan_service import PlanRevisionConflict, VideoDirectorPlanService
from app.utils.path_utils import url_to_local_path
from app.services.runtime_gate import audio_source_pin as source_pin, validate_audio_source_pin as validate_source_pin

ACTIVE_AUDIO_TTS_TASK_IDS: Set[str] = set()
ACTIVE_AUDIO_PREPARE_TASK_IDS: Set[str] = set()
TTS_LEASE_STALE_SECONDS = 120

# RMS dBFS over the entire decoded utterance (including its internal silence), not LUFS.
# Duplicate mono at unity per channel; leave stereo intact. Never level padded clips.
CLIP_AUDIO_RENDER_PROFILE = {
    "id": "speech-rms-v1",
    "measurement": "whole_source_rms_dbfs",
    "targetRmsDbfs": -20.0,
    "minGainDb": -6.0,
    "maxGainDb": 6.0,
    "silenceThresholdDbfs": -55.0,
    "peakLimitDbfs": -1.0,
    "peakProtection": "zero_latency_sample_clamp_not_true_peak",
    "channelPolicy": "mono_unity_duplicate_stereo_preserve",
    "sampleRate": 44100,
    "channels": 2,
    "codec": "pcm_s16le",
    "mixNormalize": False,
}
SPEECH_FORMAT_FILTER = "aresample=44100:osf=fltp"


def _reconciled_audio_windows(plan: dict) -> list:
    """Overlay exact planned windows onto the complete accepted execution set."""
    def identity(item):
        def integer(value):
            if isinstance(value, bool):
                raise ValueError("Clip window index is invalid")
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                if not math.isfinite(value) or not value.is_integer():
                    raise ValueError("Clip window index is invalid")
                return int(value)
            if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
                return int(value)
            raise ValueError("Clip window index is invalid")

        if not isinstance(item, dict):
            raise ValueError("Clip window must be an object")
        raw_index = item.get("window_index")
        if raw_index is None:
            raw_index = item.get("index")
        if raw_index is None:
            raise ValueError("Clip window index is invalid")
        if any(item.get(key) is None or isinstance(item.get(key), bool) for key in ("start_time", "end_time")):
            raise ValueError("Clip window range is missing")
        try:
            index, start, end = integer(raw_index), float(item["start_time"]), float(item["end_time"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Clip window identity is invalid") from exc
        alias = item.get("index") if item.get("window_index") is not None else None
        try:
            alias_conflicts = alias is not None and integer(alias) != index
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Clip window aliases conflict") from exc
        if (index < 1 or alias_conflicts or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start):
            raise ValueError("Clip window identity is invalid")
        return index, start, end

    raw_planned = plan.get("window_plans")
    raw_accepted = plan.get("execution_windows")
    if raw_planned is not None and not isinstance(raw_planned, list):
        raise ValueError("window_plans must be a list")
    if raw_accepted is not None and not isinstance(raw_accepted, list):
        raise ValueError("execution_windows must be a list")
    planned = raw_planned or []
    accepted = planned if raw_accepted is None else raw_accepted

    planned_by_identity = {}
    for item in planned:
        key = identity(item)
        if key in planned_by_identity:
            raise ValueError("Duplicate planned Clip window identity")
        planned_by_identity[key] = item

    reconciled, accepted_indexes = [], set()
    for item in accepted:
        key = identity(item)
        if key[0] in accepted_indexes:
            raise ValueError("Duplicate accepted Clip window index")
        accepted_indexes.add(key[0])
        merged = {**item, **planned_by_identity.get(key, {})}
        merged.update(window_index=key[0], start_time=item["start_time"], end_time=item["end_time"])
        reconciled.append(merged)
    return reconciled


def settle_audio_task(db, task):
    """A terminal TTS task may clear only its still-unclaimed GENERATING event."""
    if task.type != 'audio_event_tts' or task.status not in {'failed', 'cancelled'}:
        return
    try:
        event_id = json.loads(task.metadata_json or '{}').get('audio_event_id')
    except (ValueError, TypeError, AttributeError):
        return
    event = db.query(ShotAudioEvent).filter_by(id=event_id).populate_existing().first() if event_id else None
    if not event or event.shot_id != task.shot_id or event.tts_status != 'GENERATING':
        return
    other = db.query(Task.id).filter(Task.id != task.id, Task.type == 'audio_event_tts',
                                     Task.status.in_(['pending', 'running']), Task.metadata_json.contains(event.id)).exists()
    db.query(ShotAudioEvent).filter(ShotAudioEvent.id == event.id, ShotAudioEvent.shot_id == task.shot_id,
                                   ShotAudioEvent.tts_status == 'GENERATING', ~other).update({'tts_status': 'FAILED'}, synchronize_session=False)


class AudioDriveService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AudioDriveRepository(db)
        self.shot_repo = ShotRepository(db)
        self.prepare_owner = None

    def _source_gate(self, shot_id):
        pin = source_pin(self.db, shot_id)
        if self.prepare_owner:
            task_id, token, inputs = self.prepare_owner
            task = self.db.query(Task).filter_by(id=task_id).populate_existing().first()
            current = json.loads(task.metadata_json or '{}') if task else {}
            if (not task or task.status != 'running' or task.claim_token != token
                    or current != inputs or inputs.get('source_pins', {}).get(shot_id) != pin):
                raise HTTPException(409, 'AUDIO_PREPARE_SOURCE_OR_OWNER_CHANGED')
            task.heartbeat_at = datetime.utcnow()
        return pin

    def _voice_binding(self, event):
        from app.models.novel import Character
        from app.services.rendered_subtitles import fingerprint
        shot = self.shot_repo.get_by_id(event.shot_id)
        if event.event_type == 'NARRATION' and event.voice_owner_character_id is None:
            # An explicit audio-only Book role, never a name-based visual identity fallback.
            profiles = self.db.query(Character).filter_by(novel_id=shot.chapter.novel_id, is_narrator=True).all()
            character = profiles[0] if len(profiles) == 1 else None
        else:
            character = self.db.get(Character, event.voice_owner_character_id) if event.voice_owner_character_id else None
        if not character or character.novel_id != shot.chapter.novel_id or not character.reference_audio_url:
            raise HTTPException(409, {'code': 'VOICE_PROFILE_REQUIRED', 'eventId': event.id, 'voiceOwner': event.voice_owner_name})
        path = url_to_local_path(character.reference_audio_url)
        if not path or not Path(path).is_file():
            raise HTTPException(409, 'VOICE_PROFILE_FILE_REQUIRED')
        return {'character_id': character.id, 'url': character.reference_audio_url, 'sha256': fingerprint(path),
                'role': 'BOOK_NARRATOR' if character.is_narrator else 'CHARACTER'}

    def _tts_gate(self, task, event, inputs):
        if (not task or not event or not isinstance(inputs, dict)
                or task.shot_id != event.shot_id or inputs.get('audio_event_id') != event.id
                or json.loads(task.metadata_json or '{}') != inputs):
            raise HTTPException(409, 'AUDIO_EVENT_TASK_BINDING_CHANGED')
        validate_source_pin(self.db, event.shot_id, inputs.get('source_pin'))
        if inputs.get('voice_binding') != self._voice_binding(event):
            raise HTTPException(409, 'VOICE_PROFILE_CHANGED')
        if task.parent_task_id:
            parent = self.db.query(Task).filter_by(id=task.parent_task_id).populate_existing().first()
            if not parent or parent.status not in {'pending', 'running'}:
                raise HTTPException(409, 'AUDIO_PARENT_NOT_ACTIVE')

    def _tts_asset_eligible(self, event, asset, pin):
        config=json.loads(asset.config_json or '{}')
        if config.get('voice_binding')!=self._voice_binding(event):return False
        if config.get('source_pin')==pin:return True
        from app.services.shot_revision_service import approved_audio_ancestor
        old=approved_audio_ancestor(self.db,event.shot_id,config.get('source_pin'),event.id)
        fields=('event_type','voice_owner_character_id','voice_owner_name','text','emotion_prompt')
        if not old or any(old[key]!=getattr(event,key) for key in fields):return False
        if asset.text_hash!=self._hash_payload({'text':event.text}) or config.get('emotion_prompt')!=event.emotion_prompt:return False
        producer=self.db.get(Task,config.get('task_id')) if config.get('task_id') else None
        metadata=json.loads(producer.metadata_json or '{}') if producer else {}
        if (not producer or producer.status!='completed' or producer.type!='audio_event_tts' or producer.shot_id!=event.shot_id
                or metadata.get('audio_event_id')!=event.id or metadata.get('source_pin')!=config['source_pin']
                or metadata.get('voice_binding')!=config['voice_binding']):return False
        from app.services.rendered_subtitles import load
        saved=load(asset.audio_path) if asset.audio_path else None
        return bool(saved and saved['lineage'].get('tts_asset_id')==asset.id and saved['lineage'].get('audio_event_id')==event.id
                    and saved['lineage'].get('text_hash')==asset.text_hash)

    def _hash_payload(self, payload: Any) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _event_to_response(self, event: ShotAudioEvent) -> dict:
        asset = self.repo.current_tts_asset(event.id)
        from app.services.shot_treatment_contract import saved_contract
        contract=saved_contract(self.db,event.shot_id)
        ref=next((b['treatment_ref'] for b in (contract or {}).get('event_bindings',[]) if b['event_id']==event.id),None)
        return {
            "id": event.id,
            "shotId": event.shot_id,
            "treatmentRef": ref,
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
        from app.models.shot_revision import ShotRevisionHead
        head=self.db.get(ShotRevisionHead,shot_id)
        return {
            "success": True,
            "data": {
                "shotId": shot_id,
                "sourceRevision": head.revision if head else 0,
                "sourceRevisionId": head.revision_id if head else None,
                "audioStatus": getattr(shot, "audio_status", None) or "NOT_READY",
                "events": [self._event_to_response(event) for event in events],
            },
        }

    def create_tts_task(self, event_id: str, force: bool = False) -> dict:
        event = self.repo.get_event(event_id)
        if not event:
            return {"success": False, "status_code": 404, "message": "Audio Event 不存在"}
        pin = self._source_gate(event.shot_id)
        voice = self._voice_binding(event)
        active = self.db.query(Task).filter(Task.type == 'audio_event_tts', Task.status.in_(['pending', 'running']),
                                            Task.metadata_json.contains(event.id)).first()
        if active:
            return {'success': False, 'status_code': 409, 'message': '该 Audio Event 已有进行中的任务'}
        current_asset = self.repo.current_tts_asset(event_id)
        if current_asset and current_asset.status == "READY" and event.tts_status == "READY" and not force and self._tts_asset_eligible(event,current_asset,pin):
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
            novel_id=shot.chapter.novel_id,
            shot_id=shot.id,
            character_id=voice['character_id'],
            parent_task_id=self.prepare_owner[0] if self.prepare_owner else None,
            status="pending",
            progress=0,
            current_step="等待处理",
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            metadata_json=json.dumps({'execution_purpose': 'production', 'audio_event_id': event.id,
                                      'source_pin': pin, 'voice_binding': voice}, ensure_ascii=False),
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
            # A lost audio worker is not permission to re-submit or adopt an unrelated READY asset.
            cutoff = datetime.utcnow() - timedelta(seconds=TTS_LEASE_STALE_SECONDS)
            for task in db.query(Task).filter(Task.type == 'audio_event_tts', Task.status == 'running').all():
                if not task.heartbeat_at or task.heartbeat_at < cutoff:
                    task.status, task.error_message = 'failed', 'AUDIO_WORKER_INTERRUPTED_RETRY_EXPLICITLY'
                    task.completed_at = datetime.utcnow()
                    settle_audio_task(db, task)
            db.commit()
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
                try:
                    AudioDriveService(db)._tts_gate(task, event, metadata)
                    if task.comfyui_prompt_id:
                        raise HTTPException(409, 'AUDIO_SUBMISSION_NOT_REPLAYED')
                except Exception as exc:
                    task.status, task.error_message, task.completed_at = 'failed', str(exc), datetime.utcnow()
                    settle_audio_task(db, task)
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
        AudioDriveService.resume_active_tts_tasks()
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
        self._source_gate(shot_id)
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        events = self.repo.list_events(shot_id)
        allowed = set(event_ids or [])
        if allowed - {event.id for event in events}:
            raise HTTPException(404, 'AUDIO_EVENT_OUTSIDE_SHOT')
        tasks = []
        blocked = []
        for event in events:
            if allowed and event.id not in allowed:
                continue
            if event.tts_status == "GENERATING" and not force:
                continue
            if only_stale and event.tts_status == "READY" and not force:
                continue
            try:
                result = self.create_tts_task(event.id, force=force)
            except HTTPException as exc:
                result = {'success': False, 'message': exc.detail}
            if result.get("success"):
                tasks.append(result.get("data"))
            else:
                blocked.append({'eventId': event.id, 'reason': result.get('message')})
        return {'success': not blocked, 'message': f'已提交 {len(tasks)} 个 TTS 任务，{len(blocked)} 项依赖未就绪',
                'data': {'tasks': tasks, 'blocked': blocked}}

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
        if any(shot.chapter_id != chapter_id for shot in shots):
            raise HTTPException(409, 'AUDIO_PREPARE_SINGLE_CHAPTER_REQUIRED')
        pins = {shot.id: self._source_gate(shot.id) for shot in shots}
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
                "source_pins": pins,
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
                if not task.heartbeat_at or task.heartbeat_at < datetime.utcnow() - timedelta(seconds=TTS_LEASE_STALE_SECONDS):
                    task.status = 'failed'
                    task.error_message = 'AUDIO_PREPARE_INTERRUPTED_RETRY_EXPLICITLY'
                    task.completed_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

    @staticmethod
    async def run_next_persistent_audio_prepare_task() -> bool:
        if ACTIVE_AUDIO_PREPARE_TASK_IDS:
            return False
        AudioDriveService.resume_active_audio_prepare_tasks()
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
            service._source_gate(shot_id)
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
            if not task or task.status != 'pending':
                return
            encoded=task.metadata_json
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

            for shot_id in shot_ids:
                validate_source_pin(db, shot_id, metadata.get('source_pins', {}).get(shot_id))
            token = str(uuid.uuid4())
            if db.query(Task).filter_by(id=task_id, status='pending', metadata_json=encoded).update({
                    'status': 'running', 'claim_token': token, 'heartbeat_at': datetime.utcnow(),
                    'started_at': datetime.utcnow(), 'progress': 1, 'current_step': '开始准备音频'}, synchronize_session=False) != 1:
                db.rollback()
                return
            db.commit()
            db.refresh(task)
            service.prepare_owner = (task_id, token, metadata)

            failures = []
            total = len(shot_ids)
            for index, shot_id in enumerate(shot_ids, 1):
                shot = service.shot_repo.get_by_id(shot_id)
                if not shot:
                    failures.append({"shotId": shot_id, "error": "分镜不存在"})
                    continue
                base_progress = int(((index - 1) / total) * 100)
                try:
                    service._source_gate(shot_id)
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

            for shot_id in shot_ids:
                service._source_gate(shot_id)
            final_metadata=json.dumps({**metadata,'result':{'total':total,'failed':failures,
                'succeeded':total-len(failures)}},ensure_ascii=False)
            fields={'completed_at':datetime.utcnow(),'metadata_json':final_metadata}
            if failures:
                fields.update(status='failed',error_message=f'音频准备完成但有 {len(failures)} 个分镜失败',current_step='音频准备部分失败')
            else:
                fields.update(status='completed',progress=100,current_step='音频准备完成')
            if db.query(Task).filter_by(id=task_id,status='running',claim_token=token,metadata_json=encoded).update(
                    fields,synchronize_session=False)!=1:
                db.rollback();return
            db.commit()
        except Exception as exc:
            db.rollback();task = task_repo.get_by_id(task_id)
            if task and task.status=='running' and task.claim_token==locals().get('token'):
                db.query(Task).filter_by(id=task.id,status='running',claim_token=task.claim_token).update({
                    'status':'failed','error_message':str(exc),'current_step':'音频准备任务异常',
                    'completed_at':datetime.utcnow()},synchronize_session=False)
            db.commit()
        finally:
            db.close()

    def patch_event(self, event_id: str, data: dict) -> dict:
        event = self.repo.get_event(event_id)
        if not event:
            return {"success": False, "status_code": 404, "message": "Audio Event 不存在"}
        from app.schemas.shot_revision import normalize_revision_aliases
        from app.services.shot_revision_service import ShotRevisionService, conflict
        from app.services.chapter_governance import require_source
        try:data=normalize_revision_aliases(data)
        except ValueError as exc:conflict(str(exc))
        current=require_source(self.db,event.shot_id)
        expected=data.get('expected_revision')
        if type(expected) is not int or expected<0:conflict('SHOT_REVISION_REQUIRED',shotId=event.shot_id)
        if expected!=current.revision:conflict('SHOT_REVISION_CONFLICT',shotId=event.shot_id,expected=expected,current=current.revision)
        shot=self.shot_repo.get_by_id(event.shot_id)
        events=[self._event_to_response(e) for e in self.repo.list_events(shot.id)]
        editable={'voiceOwnerCharacterId','voiceOwnerName','visibleSpeakerCharacterId','visibleSpeakerName',
                  'requiresVisibleLipsync','text','emotionPrompt','pauseAfter'}
        target=next(e for e in events if e['id']==event_id)
        target.update({k:v for k,v in data.items() if k in editable})
        saved=ShotRevisionService(self.db).save_batch(shot.chapter.novel_id,shot.chapter_id,
            [{'id':shot.id,'expected_revision':expected,'audio_events':events}])['data']['shots'][0]
        return {'success':True,'data':{**self._event_to_response(self.repo.get_event(event_id)),
            'sourceRevision':saved['sourceRevision'],'shot':saved}}

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
        inputs = None
        def claim_current() -> bool:
            return bool(claim_token and task_repo.task_claim_is_current(task_id, claim_token))

        def update_task(fields: dict) -> bool:
            if fields.get('status') != 'failed':
                guarded = task_repo.get_by_id(task_id)
                service._tts_gate(guarded, service.repo.get_event(event_id), inputs)
            return task_repo.update_claimed_task(task_id, claim_token, fields)

        async def wait_owned(awaitable):
            operation = asyncio.ensure_future(awaitable)
            try:
                service._tts_gate(task_repo.get_by_id(task_id), service.repo.get_event(event_id), inputs)
                while True:
                    done, _ = await asyncio.wait({operation}, timeout=15)
                    db.expire_all()
                    if not claim_current():
                        raise HTTPException(409, 'AUDIO_TASK_NOT_ACTIVE')
                    service._tts_gate(task_repo.get_by_id(task_id), service.repo.get_event(event_id), inputs)
                    if done:
                        return operation.result()
                    task_repo.heartbeat_task(task_id, claim_token)
            finally:
                if not operation.done():
                    operation.cancel()
                    try:
                        await operation
                    except asyncio.CancelledError:
                        pass

        def fail_task(message: str, step: str = "任务异常") -> None:
            db.rollback()
            if not claim_current():
                return
            changed = update_task({
                "status": "failed",
                "error_message": message,
                "current_step": step,
                "completed_at": datetime.utcnow(),
            })
            if changed:
                settle_audio_task(db, task_repo.get_by_id(task_id))
                db.commit()

        try:
            task = task_repo.get_by_id(task_id)
            event = service.repo.get_event(event_id)
            workflow = WorkflowRepository(db).get_by_id(workflow_id)
            if not task or not event or not workflow:
                fail_task('AUDIO_TASK_INPUT_REMOVED')
                return
            if not claim_current():
                return
            inputs = json.loads(task.metadata_json or '{}')
            service._tts_gate(task, event, inputs)
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
            strict_card=getattr(shot,'completion_disposition','NORMAL')=='DEGRADED_NARRATION_CARD'
            if not update_task({"current_step": "准备参考音色"}):
                return

            char_repo = CharacterRepository(db)
            character = char_repo.get_by_id(inputs['voice_binding']['character_id'])
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
            upload_result = await wait_owned(comfy.client.upload_audio(str(reference_path)))
            if not upload_result.get("success"):
                fail_task(upload_result.get("message") or "上传参考音色失败", "上传参考音色失败")
                return
            if not task_repo.heartbeat_task(task_id, claim_token):
                return

            node_mapping = json.loads(workflow.node_mapping or "{}") if workflow.node_mapping else {}
            submitted_text = event.text
            submitted_workflow = comfy.builder.build_audio_workflow(
                text=submitted_text,
                workflow_json=workflow.workflow_json,
                novel_id=shot.chapter.novel_id,
                character_name=event.voice_owner_name,
                node_mapping=node_mapping,
                reference_audio_filename=upload_result.get("filename"),
                emotion_prompt=event.emotion_prompt or "自然",
            )
            text_node_id=str(node_mapping.get('text_node_id') or '')
            text_node=submitted_workflow.get(text_node_id) if isinstance(submitted_workflow,dict) else None
            text_inputs=text_node.get('inputs') if isinstance(text_node,dict) else None
            text_field=next((key for key in ('text','prompt','value')
                if isinstance(text_inputs,dict) and isinstance(text_inputs.get(key),str)),None)
            if strict_card and (not text_node_id or not text_field or text_inputs.get(text_field)!=submitted_text):
                fail_task('NARRATION_CARD_TTS_TEXT_NODE_PROOF_REQUIRED','TTS 文本节点证明无效')
                return
            if not update_task({
                "workflow_json": json.dumps(submitted_workflow, ensure_ascii=False, indent=2),
                "prompt_text": f"Audio Event: {event.id}\n角色: {event.voice_owner_name}\n文本: {event.text}\n情感: {event.emotion_prompt or '自然'}",
                "current_step": "提交 ComfyUI 音频生成",
            }):
                return

            queue_result = await wait_owned(comfy.client.queue_prompt(submitted_workflow))
            if not queue_result.get("success"):
                fail_task(queue_result.get("error") or "提交任务失败", "提交任务失败")
                return
            if not update_task({"comfyui_prompt_id": queue_result.get("prompt_id"), "current_step": "正在生成 TTS"}):
                return

            result = await wait_owned(comfy.client.wait_for_audio_result(
                queue_result.get("prompt_id"),
                submitted_workflow,
                node_mapping.get("save_audio_node_id"),
                timeout=600,
            ))
            if not result.get("success"):
                fail_task(result.get("message") or "生成失败", "生成失败")
                return
            remote_proof={'prompt_id':result.get('prompt_id'),'output_node_id':result.get('output_node_id'),
                'output':result.get('output'),'audio_url':result.get('audio_url'),
                'history':result.get('history'),'status':result.get('status'),
                'submitted_workflow':submitted_workflow,'submitted_workflow_hash':service._hash_payload(submitted_workflow),
                'text_node_id':text_node_id,'text_input_field':text_field,
                'save_audio_node_id':str(node_mapping.get('save_audio_node_id')) if node_mapping.get('save_audio_node_id') is not None else None,
                'submitted_text':submitted_text}
            if strict_card and (remote_proof['prompt_id']!=queue_result.get('prompt_id')
                    or not remote_proof['history'] or not remote_proof['output_node_id']
                    or remote_proof['output_node_id']!=remote_proof['save_audio_node_id']
                    or not remote_proof['status']):
                fail_task('NARRATION_CARD_TTS_REMOTE_PROOF_REQUIRED','生成结果证明无效')
                return
            if not task_repo.heartbeat_task(task_id, claim_token):
                return

            remote_url = result.get("audio_url")
            local_path = await wait_owned(file_storage.download_audio(
                url=remote_url,
                novel_id=shot.chapter.novel_id,
                character_name=f"event_{event.event_order}_{event.voice_owner_name}",
                audio_type="audio_event",
            ))
            audio_url = remote_url
            duration = result.get("duration")
            if local_path:
                relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                audio_url = f"/api/files/{relative_path.lstrip('/')}"
                duration = AudioDriveService._probe_audio_duration(local_path) or duration
            if not claim_current():
                return
            from app.services.rendered_subtitles import fingerprint
            local_hash=fingerprint(local_path) if local_path and Path(local_path).is_file() else None
            local_size=Path(local_path).stat().st_size if local_path and Path(local_path).is_file() else None
            asset = service.repo.add_tts_asset(
                event.id,
                commit=False,
                provider="comfyui",
                model=workflow.name,
                voice_id=character.id,
                audio_url=audio_url,
                audio_path=local_path,
                duration_seconds=duration,
                file_size=local_size,
                content_hash=local_hash,
                text_hash=service._hash_payload({"text": submitted_text}),
                config_json=json.dumps({'emotion_prompt': event.emotion_prompt, 'source_pin': inputs['source_pin'],
                                        'voice_binding': inputs['voice_binding'], 'task_id': task_id,
                                        'remote_proof':remote_proof}, ensure_ascii=False),
                status="READY",
            )
            event.tts_status = "READY"
            if local_path and duration:
                from app.services.rendered_subtitles import publish
                publish(local_path, [{"start": "0", "end": str(duration), "text": submitted_text}],
                        {"kind": "tts", "audio_event_id": event.id, "tts_asset_id": asset.id,
                         "task_id": task_id, "text_hash": asset.text_hash})
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
        pin = self._source_gate(shot_id)
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        current = self.repo.latest_timeline(shot_id)
        if current and current.status == "READY" and not force:
            self._timeline_gate(shot_id, current, pin)
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
            config = json.loads(asset.config_json or '{}')
            if not self._tts_asset_eligible(event,asset,pin):
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
            "source_pin": pin,
            "event_count": len(events),
            "authored_final_pause_seconds": PAUSE_AFTER_SECONDS.get((events[-1].pause_after or "NONE").upper(), 0.0) if events else 0.0,
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
        validate_source_pin(self.db, shot_id, pin)
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
        audio_summary = json.loads(timeline.audio_summary_json or "{}")
        return {
            "id": timeline.id,
            "shotId": timeline.shot_id,
            "revision": timeline.revision,
            "totalDuration": timeline.total_duration,
            "audioRequiredDuration": timeline.audio_required_duration,
            "status": timeline.status,
            "audioSummary": audio_summary,
            "timingSummary": self._timing_summary(timeline, events, audio_summary),
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

    def _timing_summary(self, timeline: ShotAudioTimeline, events: list, audio_summary: dict) -> dict:
        """Read stored, timeline-bound READY file durations; never probe, rebuild or trim on GET."""
        shot = self.shot_repo.get_by_id(timeline.shot_id)
        intervals = []
        missing = []
        for event in events:
            asset = self.repo.get_tts_asset(event.tts_asset_id) if event.tts_asset_id else None
            duration = float(asset.duration_seconds or 0) if asset and asset.status == "READY" else 0.0
            if not math.isfinite(duration) or duration <= 0:
                missing.append(event.audio_event_id)
                continue
            intervals.append((float(event.start_time), float(event.start_time) + duration))

        coverage = 0.0
        covered_end = 0.0
        for start, end in sorted(intervals):
            coverage += max(0.0, end - max(start, covered_end))
            covered_end = max(covered_end, end)
        last_end = max((end for _, end in intervals), default=None)
        complete = timeline.status == "READY" and not missing
        duration = resolved_duration(shot, timeline)
        final_pause = audio_summary.get("authored_final_pause_seconds")
        if not events:
            final_pause = 0.0
        elif final_pause is None and timeline.audio_required_duration is not None:
            # Legacy timelines stored the audio cursor including the final pause, separately
            # from the visual floor. Do not read today's edited pause into an old timeline.
            final_pause = max(0.0, float(timeline.audio_required_duration) - max(float(event.end_time) for event in events))
        hold = max(0.0, duration - (last_end or 0.0)) if complete else None
        extra_hold = max(0.0, hold - final_pause) if hold is not None and final_pause is not None else None
        return {
            "measurementBasis": "READY_TTS_ASSET_FILE_DURATION",
            "ttsEventCount": len(events),
            "readyTtsEventCount": len(intervals),
            "ttsCoverageComplete": complete,
            "unmeasuredAudioEventIds": missing,
            "measuredTtsDurationSeconds": round(sum(end - start for start, end in intervals), 3),
            "measuredTtsCoverageSeconds": round(coverage, 3),
            "lastTtsFileEndSeconds": round(last_end, 3) if last_end is not None else None,
            "authoredFinalPauseSeconds": round(final_pause, 3) if final_pause is not None else None,
            "visualEstimatedFloorSeconds": visual_required_duration(shot),
            "resolvedDurationSeconds": duration,
            "remainingNonSpeechHoldSeconds": round(hold, 3) if hold is not None else None,
            "holdAfterAuthoredFinalPauseSeconds": round(extra_hold, 3) if extra_hold is not None else None,
            "longTailReviewSuggested": bool(last_end is not None and extra_hold is not None and extra_hold >= 3.0),
        }

    def _timeline_gate(self, shot_id, timeline, pin):
        if json.loads(timeline.audio_summary_json or '{}').get('source_pin') != pin:
            raise HTTPException(409, 'AUDIO_TIMELINE_SOURCE_CHANGED: 请显式重建音频时间线')

    def build_execution_windows(self, shot_id: str, max_clip_duration: Optional[float] = None) -> dict:
        pin = self._source_gate(shot_id)
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        timeline = self.repo.latest_timeline(shot_id)
        if not timeline or timeline.status != "READY":
            return {"success": False, "status_code": 400, "message": "Audio Timeline 未 READY"}
        self._timeline_gate(shot_id, timeline, pin)
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
        # Bind window geometry even before Clip Audio exists, without rebinding cached audio.
        windows = [{**window, "audio_timeline_id": timeline.id,
                    "audio_timeline_revision": timeline.revision,
                    "audio_timeline_hash": timeline.generated_from_hash} for window in windows]
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
        pin = self._source_gate(shot_id)
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return {"success": False, "status_code": 404, "message": "分镜不存在"}
        is_card=getattr(shot,'completion_disposition','NORMAL')=='DEGRADED_NARRATION_CARD'
        card_video_owner=(shot.video_task_id,shot.video_status) if is_card else None
        if is_card and self.db.query(Task.id).filter_by(type='narration_card_video',shot_id=shot.id).filter(
                Task.status.in_(['pending','running'])).first():
            return {"success":False,"status_code":409,"message":"NARRATION_CARD_TASK_ACTIVE"}
        timeline = self.repo.latest_timeline(shot_id)
        if not timeline or timeline.status != "READY":
            return {"success": False, "status_code": 400, "message": "Audio Timeline 未 READY"}
        self._timeline_gate(shot_id, timeline, pin)
        plan = json.loads(shot.video_director_plan or "{}") if shot.video_director_plan else {}
        try:
            windows = _reconciled_audio_windows(plan)
        except ValueError:
            return {"success": False, "status_code": 409, "message": "Clip window contract is invalid; refresh and rebuild execution windows."}
        window = next((item for item in windows if int(item.get("window_index") or item.get("index") or 0) == window_index), None)
        if not window:
            return {"success": False, "status_code": 404, "message": "Clip window 不存在"}
        start = float(window.get("start_time") or 0)
        end = float(window.get("end_time") or start)
        clip_duration = contract_clip_duration(start, end)
        if clip_duration <= 0:
            return {"success": False, "status_code": 400, "message": "Clip window 时长无效"}

        drive_path = window.get("drive_audio_path") or url_to_local_path(window.get("drive_audio_url") or "")
        final_path = window.get("final_audio_path") or url_to_local_path(window.get("final_audio_url") or "")
        drive_path = Path(drive_path) if drive_path else file_storage.get_clip_audio_path(shot.chapter.novel_id, shot.chapter_id, shot.id, window_index, "drive_audio")
        final_path = Path(final_path) if final_path else file_storage.get_clip_audio_path(shot.chapter.novel_id, shot.chapter_id, shot.id, window_index, "final_audio")
        timeline_revision = int(timeline.revision or 0)
        timeline_hash = timeline.generated_from_hash

        bound_revision = window.get("audio_timeline_revision") or window.get("audioTimelineRevision")
        bound_hash = window.get("audio_timeline_hash") or window.get("audioTimelineHash")
        cache_matches_timeline = (
            window.get("audio_timeline_id") == timeline.id
            and int(bound_revision or 0) == timeline_revision
            and (not timeline_hash or bound_hash == timeline_hash)
        )
        from app.services.rendered_subtitles import load, publish, fingerprint
        if not force and window.get("audio_status") == "READY" and cache_matches_timeline and drive_path.exists() and final_path.exists():
            # A missing/legacy subtitle snapshot is not permission to replace READY audio.
            # Keep subtitle verification fail-closed, independently of audio reuse.
            snapshot = load(final_path, require_ready=False)
            lineage = snapshot.get("lineage", {}) if snapshot else {}
            render_metadata = None
            if (lineage.get("timeline_id") == timeline.id
                    and lineage.get("timeline_revision") == timeline_revision
                    and lineage.get("timeline_hash") == timeline_hash
                    and lineage.get("clip_start") == start and lineage.get("clip_end") == end):
                render_metadata = lineage.get("render_metadata")
            manifest_path=window.get('clip_audio_manifest_path');manifest=None
            try:manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8')) if manifest_path else None
            except (OSError,ValueError,TypeError):manifest=None
            expected_receipt=window.get('audio_receipt')
            actual_receipt={'manifest_hash':digest(manifest) if isinstance(manifest,dict) else None,
                'drive_audio_sha256':fingerprint(drive_path),'drive_audio_bytes':drive_path.stat().st_size,
                'final_audio_sha256':fingerprint(final_path),'final_audio_bytes':final_path.stat().st_size,
                'final_audio_snapshot_hash':digest(snapshot) if snapshot else None}
            if expected_receipt!=actual_receipt:
                return {"success":False,"status_code":409,"message":"CLIP_AUDIO_CACHE_UNVERIFIED_REBUILD_REQUIRED"}
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
                    "renderMetadata": render_metadata or None,
                    "subtitleStatus": "READY" if snapshot and not snapshot.get("unavailable") else "UNAVAILABLE",
                    "message": "Clip Audio 已存在",
                },
            }

        audio_window_keys = (
            "window_index", "index", "start_time", "end_time",
            "audio_timeline_id", "audio_timeline_revision", "audio_timeline_hash",
            "audioTimelineId", "audioTimelineRevision", "audioTimelineHash",
            "audio_status", "speaker_timeline", "clip_audio_duration",
            "drive_audio_url", "final_audio_url", "drive_audio_path", "final_audio_path",
            "clip_audio_manifest_path",
            "audio_receipt",
        )
        starting_audio_window = {key: window.get(key) for key in audio_window_keys}
        starting_timeline = (timeline.id, timeline_revision, timeline_hash, "READY")
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

        # Publish new paths only after both tracks, subtitle snapshot and manifest exist.
        # Even an explicit rerender of identical inputs must not replace historical bytes.
        render_id = uuid.uuid4().hex
        suffix = f"{CLIP_AUDIO_RENDER_PROFILE['id']}_{render_id}"
        drive_path = file_storage.get_clip_audio_path(shot.chapter.novel_id, shot.chapter_id, shot.id, window_index, f"drive_audio_{suffix}")
        final_path = file_storage.get_clip_audio_path(shot.chapter.novel_id, shot.chapter_id, shot.id, window_index, f"final_audio_{suffix}")
        manifest_path = file_storage.get_clip_audio_path(shot.chapter.novel_id, shot.chapter_id, shot.id, window_index, f"manifest_{suffix}", ext=".json")

        # Capture text and source bytes before rendering, never from later business state.
        cues = []
        subtitle_missing = False
        for segment in final_segments:
            event = self.repo.get_event(segment["audio_event_id"])
            asset = self.repo.get_tts_asset(segment["tts_asset_id"])
            segment["source_sha256"] = fingerprint(segment["source_path"])
            tts_snapshot = load(segment["source_path"])
            if (not event or not asset or asset.text_hash != self._hash_payload({"text": event.text})
                    or not tts_snapshot or tts_snapshot["lineage"].get("tts_asset_id") != asset.id
                    or tts_snapshot["lineage"].get("text_hash") != asset.text_hash
                    or len(tts_snapshot["cues"]) != 1 or tts_snapshot["cues"][0]["text"] != event.text):
                subtitle_missing = True
                continue
            cues.append({"start": str(segment["clip_start"]),
                         "end": str(round(segment["clip_start"] + segment["duration"], 3)),
                         "text": event.text or "", "audio_event_id": event.id,
                         "tts_asset_id": asset.id, "text_hash": asset.text_hash})

        final_result = self._render_clip_audio(final_segments, final_path, clip_duration)
        if not final_result.get("success"):
            return final_result
        final_sources = {segment["source_path"]: segment for segment in final_segments}
        for segment in drive_segments:
            source = final_sources[segment["source_path"]]
            segment.update({key: source[key] for key in ("source_sha256", "speech_level") if key in source})
        drive_result = self._render_clip_audio(drive_segments, drive_path, clip_duration)
        if not drive_result.get("success"):
            return drive_result

        if any(fingerprint(s["source_path"]) != s["source_sha256"] for s in final_segments):
            return {"success": False, "status_code": 409, "message": "TTS source changed during Clip Audio rendering; retry the explicit build."}
        render_metadata = {
            "renderId": render_id,
            "profile": dict(CLIP_AUDIO_RENDER_PROFILE),
            "sourceLevels": [{"audioEventId": segment["audio_event_id"],
                              "ttsAssetId": segment["tts_asset_id"],
                              "sourceSha256": segment["source_sha256"],
                              **segment.get("speech_level", {})} for segment in final_segments],
        }
        published_snapshot=publish(final_path, cues, {"kind": "clip_audio", "timeline_id": timeline.id,
                "timeline_revision": timeline_revision, "timeline_hash": timeline_hash,
                "window_index": window_index, "clip_start": start, "clip_end": end,
                "segments": final_segments, "render_metadata": render_metadata},
                unavailable="TTS text/source binding could not be verified; regenerate TTS." if subtitle_missing else None)

        manifest = {
            "source_pin": pin,
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
            "render_metadata": render_metadata,
            "drive_audio_sha256": fingerprint(drive_path),
            "drive_audio_bytes": drive_path.stat().st_size,
            "final_audio_sha256": fingerprint(final_path),
            "final_audio_bytes": final_path.stat().st_size,
            "final_audio_snapshot_hash": digest(published_snapshot),
            "generated_at": datetime.utcnow().isoformat(),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        audio_receipt={'manifest_hash':digest(manifest),'drive_audio_sha256':manifest['drive_audio_sha256'],
            'drive_audio_bytes':manifest['drive_audio_bytes'],'final_audio_sha256':manifest['final_audio_sha256'],
            'final_audio_bytes':manifest['final_audio_bytes'],'final_audio_snapshot_hash':manifest['final_audio_snapshot_hash']}

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
        window['audio_receipt']=audio_receipt
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
            "audio_receipt":audio_receipt,
        }

        def mutate_audio_window(latest: dict) -> dict:
            validate_source_pin(self.db, shot_id, pin)
            self._source_gate(shot_id)
            # Scalar reads bypass ORM identity-map state held while FFmpeg was running.
            current_timeline = self.db.query(
                ShotAudioTimeline.id, ShotAudioTimeline.revision,
                ShotAudioTimeline.generated_from_hash, ShotAudioTimeline.status,
            ).filter(ShotAudioTimeline.shot_id == shot_id).order_by(ShotAudioTimeline.revision.desc()).first()
            try:
                current_windows = _reconciled_audio_windows(latest)
            except ValueError as exc:
                raise PlanRevisionConflict("Clip Audio window contract changed") from exc
            current_window = next((item for item in current_windows if (
                int(item["window_index"]), float(item["start_time"]), float(item["end_time"])
            ) == (int(window["window_index"]), start, end)), None)
            if (current_timeline != starting_timeline or current_window is None
                    or {key: current_window.get(key) for key in audio_window_keys} != starting_audio_window):
                raise PlanRevisionConflict("Clip Audio render inputs changed")
            try:
                sources_match = all(fingerprint(s["source_path"]) == s["source_sha256"] for s in final_segments)
            except OSError:
                sources_match = False
            if not sources_match:
                raise PlanRevisionConflict("TTS source changed before Clip Audio publication")
            current_window.update(audio_fields)
            latest["window_plans"] = current_windows
            return latest

        try:
            self.db.expire(shot, ["video_director_plan", "video_director_plan_revision"])
            if is_card and self.db.query(Shot).filter(Shot.id==shot.id,
                    Shot.video_task_id.is_(None) if card_video_owner[0] is None else Shot.video_task_id==card_video_owner[0],
                    Shot.video_status==card_video_owner[1]).update({'id':shot.id},synchronize_session=False)!=1:
                raise PlanRevisionConflict('NARRATION_CARD_VIDEO_OWNER_CHANGED')
            if is_card and self.db.query(Task.id).filter_by(type='narration_card_video',shot_id=shot.id).filter(
                    Task.status.in_(['pending','running'])).first():
                raise PlanRevisionConflict('NARRATION_CARD_TASK_ACTIVE')
            # Retry only the publication CAS; every attempt rechecks audio inputs and
            # merges into the latest plan without repeating either FFmpeg render.
            VideoDirectorPlanService(self.db).mutate(shot_id, mutate_audio_window, max_retries=3,commit=not is_card)
            self.db.expire_all();current_shot=self.shot_repo.get_by_id(shot_id)
            if is_card and current_shot:
                current_shot.video_url=current_shot.video_task_id=None;current_shot.video_status='pending'
                current_shot.chapter.final_video=current_shot.chapter.final_video_task_id=None
                self.db.commit()
        except PlanRevisionConflict:
            return {
                "success": False, "status_code": 409,
                "message": "Clip Audio inputs changed or the plan is still being updated. Refresh the timeline and window, then explicitly rebuild Clip Audio. The current selection was not replaced.",
            }
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
                "renderMetadata": render_metadata,
                "subtitleStatus": "UNAVAILABLE" if subtitle_missing else "READY",
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
            from app.services.rendered_subtitles import fingerprint
            if (not asset.content_hash or asset.file_size is None
                    or fingerprint(source_path)!=asset.content_hash or Path(source_path).stat().st_size!=asset.file_size):
                missing.append({"audio_event_id":event.audio_event_id,"tts_asset_id":event.tts_asset_id,
                    "reason":"tts_asset_bytes_changed","track":"drive" if drive_only else "final"})
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

    @staticmethod
    def _measure_speech_level(source_path: str) -> dict:
        result = subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-v", "info", "-xerror", "-i", source_path,
            "-map", "0:a:0", "-af", f"{SPEECH_FORMAT_FILTER},astats=reset=0:measure_perchannel=RMS_level+Peak_level:measure_overall=RMS_level+Peak_level",
            "-f", "null", "-",
        ], capture_output=True, text=True, check=False)
        rms_match = re.findall(r"RMS level dB:\s*([^\s]+)", result.stderr)
        peak_match = re.findall(r"Peak level dB:\s*([^\s]+)", result.stderr)
        if result.returncode or not rms_match or not peak_match:
            raise ValueError("Could not measure the full TTS source: " + result.stderr[-500:])
        channels = len(re.findall(r"Channel:\s*\d+", result.stderr))
        if channels not in (1, 2):
            raise ValueError("Clip Audio speech sources must be mono or stereo")
        rms, peak = float(rms_match[-1]), float(peak_match[-1])
        profile = CLIP_AUDIO_RENDER_PROFILE
        if rms == -math.inf and peak == -math.inf:
            gain, reason = 0.0, "silence_guard"
        elif not math.isfinite(rms) or not math.isfinite(peak):
            raise ValueError("Non-finite TTS source level")
        elif rms <= profile["silenceThresholdDbfs"]:
            gain, reason = 0.0, "silence_guard"
        else:
            requested = profile["targetRmsDbfs"] - rms
            bounded = max(profile["minGainDb"], min(profile["maxGainDb"], requested))
            gain = max(profile["minGainDb"], min(bounded, profile["peakLimitDbfs"] - peak))
            reason = "peak_headroom" if gain < bounded else "gain_bound" if bounded != requested else "target"
        return {
            "sourceChannels": channels,
            "sourceRmsDbfs": round(rms, 6) if math.isfinite(rms) else None,
            "sourcePeakDbfs": round(peak, 6) if math.isfinite(peak) else None,
            "gainDb": round(gain, 6),
            "gainReason": reason,
        }

    def _render_clip_audio(self, segments: list, output_path: Path, duration: float) -> dict:
        from app.services.rendered_subtitles import fingerprint

        levels = {};output_path.parent.mkdir(parents=True, exist_ok=True)
        workspace=Path(tempfile.mkdtemp(prefix='.clip_audio_sources_',dir=str(output_path.parent)))
        render_segments=deepcopy(segments)
        try:
            frozen_by_hash={}
            for index,(segment,render_segment) in enumerate(zip(segments,render_segments)):
                digest = segment.get("source_sha256") or fingerprint(segment["source_path"])
                segment["source_sha256"] = digest
                frozen=frozen_by_hash.get(digest)
                if frozen is None:
                    suffix=Path(segment['source_path']).suffix or '.wav';frozen=workspace/f'source_{index:03d}{suffix}'
                    shutil.copyfile(segment['source_path'],frozen)
                    if fingerprint(frozen)!=digest:raise ValueError('TTS source changed while freezing Clip Audio inputs')
                    frozen_by_hash[digest]=frozen
                render_segment['source_path']=str(frozen);render_segment['source_sha256']=digest
                if digest not in levels:
                    levels[digest] = segment.get("speech_level") or self._measure_speech_level(str(frozen))
                segment["speech_level"] = levels[digest]
                render_segment['speech_level']=levels[digest]
        except (OSError, ValueError) as exc:
            shutil.rmtree(workspace,ignore_errors=True);return {"success": False, "status_code": 500, "message": str(exc)}
        try:
            cmd = ["ffmpeg", "-nostdin", "-n", "-v", "error", "-xerror", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
            for segment in render_segments:cmd.extend(["-i", segment["source_path"]])
            filters = [f"[0:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[base]"];mix_inputs = ["[base]"]
            for index, segment in enumerate(render_segments, 1):
                delay_ms = int(round(float(segment["clip_start"]) * 1000));source_start = float(segment["source_start"])
                segment_duration = float(segment["duration"]);channel_filter = ",pan=stereo|c0=c0|c1=c0" if segment["speech_level"]["sourceChannels"] == 1 else ""
                label = f"a{index}";filters.append(f"[{index}:a]{SPEECH_FORMAT_FILTER}{channel_filter},atrim=start={source_start:.3f}:duration={segment_duration:.3f},"
                    f"asetpts=PTS-STARTPTS,volume={segment['speech_level']['gainDb']:.6f}dB,adelay={delay_ms}|{delay_ms}[{label}]");mix_inputs.append(f"[{label}]")
            ceiling = math.floor(32768 * 10 ** (CLIP_AUDIO_RENDER_PROFILE["peakLimitDbfs"] / 20)) / 32768
            filters.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0:normalize=0,"
                f"aeval=exprs='clip(val(0),-{ceiling},{ceiling})|clip(val(1),-{ceiling},{ceiling})',atrim=0:{duration:.3f}[out]")
            cmd.extend(["-filter_complex", ";".join(filters), "-map", "[out]", "-acodec", "pcm_s16le", str(output_path)])
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:return {"success": False, "status_code": 500, "message": result.stderr or "生成 Clip Audio 失败"}
            return {"success": True}
        finally:shutil.rmtree(workspace,ignore_errors=True)

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
