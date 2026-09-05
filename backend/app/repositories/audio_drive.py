import json
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audio_drive import (
    AudioEventTTSAsset,
    ShotAudioEvent,
    ShotAudioTimeline,
    ShotAudioTimelineEvent,
)
from app.models.task import Task


TTS_STALE_FIELDS = {
    "event_type",
    "voice_owner_character_id",
    "voice_owner_name",
    "text",
    "emotion_prompt",
}
TIMELINE_STALE_FIELDS = TTS_STALE_FIELDS | {
    "event_order",
    "visible_speaker_character_id",
    "visible_speaker_name",
    "requires_visible_lipsync",
    "pause_after",
}
SPEAKER_BINDING_FIELDS = {
    "visible_speaker_character_id",
    "visible_speaker_name",
    "requires_visible_lipsync",
}


class AudioDriveRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_events(self, shot_id: str) -> List[ShotAudioEvent]:
        return self.db.query(ShotAudioEvent).filter(
            ShotAudioEvent.shot_id == shot_id
        ).order_by(ShotAudioEvent.event_order).all()

    def get_event(self, event_id: str) -> Optional[ShotAudioEvent]:
        return self.db.query(ShotAudioEvent).filter(ShotAudioEvent.id == event_id).first()

    def cleanup_shot_audio_drive(self, shot_id: str, commit: bool = True) -> None:
        """Delete all AudioDrive-owned rows for a Shot in dependency order."""
        timeline_ids = select(ShotAudioTimeline.id).where(ShotAudioTimeline.shot_id == shot_id)
        event_ids = select(ShotAudioEvent.id).where(ShotAudioEvent.shot_id == shot_id)
        self.db.query(ShotAudioTimelineEvent).filter(
            ShotAudioTimelineEvent.timeline_id.in_(timeline_ids)
        ).delete(synchronize_session=False)
        self.db.query(ShotAudioTimelineEvent).filter(
            ShotAudioTimelineEvent.audio_event_id.in_(event_ids)
        ).delete(synchronize_session=False)
        self.db.query(ShotAudioTimeline).filter(
            ShotAudioTimeline.shot_id == shot_id
        ).delete(synchronize_session=False)
        self.db.query(AudioEventTTSAsset).filter(
            AudioEventTTSAsset.audio_event_id.in_(event_ids)
        ).delete(synchronize_session=False)
        self.db.query(ShotAudioEvent).filter(
            ShotAudioEvent.shot_id == shot_id
        ).delete(synchronize_session=False)
        if commit:
            self.db.commit()

    def cleanup_shots_audio_drive(self, shot_ids: list[str], commit: bool = True) -> None:
        for shot_id in shot_ids or []:
            self.cleanup_shot_audio_drive(shot_id, commit=False)
        if commit:
            self.db.commit()

    def _normalize_event_payload(self, item: dict, index: int) -> dict:
        return {
            "event_order": int(item.get("order") or item.get("event_order") or index),
            "event_type": str(item.get("type") or item.get("event_type") or "DIALOGUE").upper(),
            "voice_owner_character_id": item.get("voice_owner_character_id") or item.get("voiceOwnerCharacterId"),
            "voice_owner_name": item.get("voice_owner") or item.get("voice_owner_name") or item.get("voiceOwnerName") or item.get("character_name") or "",
            "visible_speaker_character_id": item.get("visible_speaker_character_id") or item.get("visibleSpeakerCharacterId"),
            "visible_speaker_name": item.get("visible_speaker") or item.get("visible_speaker_name") or item.get("visibleSpeakerName"),
            "requires_visible_lipsync": bool(item.get("requires_visible_lipsync") or item.get("requiresVisibleLipsync")),
            "text": item.get("text") or "",
            "emotion_prompt": item.get("emotion_prompt") or item.get("emotionPrompt") or "自然",
            "pause_after": str(item.get("pause_after") or item.get("pauseAfter") or "NONE").upper(),
        }

    def _changed_fields(self, event: ShotAudioEvent, values: dict) -> set[str]:
        return {key for key, value in values.items() if getattr(event, key) != value}

    def _mark_current_tts_assets_stale(self, event_id: str) -> None:
        self.db.query(AudioEventTTSAsset).filter(
            AudioEventTTSAsset.audio_event_id == event_id,
            AudioEventTTSAsset.is_current == True,
        ).update({"is_current": False, "status": "STALE"})

    def _mark_shot_audio_stale(self, shot_id: str, level: str = "AUDIO_TIMING_CHANGED") -> None:
        from app.services.invalidation_service import InvalidationService
        InvalidationService(self.db).invalidate_audio_downstream(
            shot_id,
            reason="Audio Event 变更，AudioDrive 下游产物已失效",
            level=level,
        )

    def _delete_event_references(self, event: ShotAudioEvent) -> None:
        self.db.query(ShotAudioTimelineEvent).filter(
            ShotAudioTimelineEvent.audio_event_id == event.id
        ).delete(synchronize_session=False)
        self.db.query(Task).filter(
            Task.type == "audio_event_tts",
            Task.status.in_(["pending", "running"]),
            Task.metadata_json.contains(event.id),
        ).update({"status": "cancelled", "error_message": "Audio Event 已删除"}, synchronize_session=False)

    def sync_events(self, shot_id: str, events: list) -> List[ShotAudioEvent]:
        self.last_sync_changed = False
        self.last_sync_timeline_stale = False
        existing = {
            event.id: event
            for event in self.db.query(ShotAudioEvent).filter(ShotAudioEvent.shot_id == shot_id).all()
        }
        seen_ids = set()
        changed = False
        timeline_stale = False
        invalidation_level = "SPEAKER_BINDING_CHANGED"
        result = []

        for index, item in enumerate(events or [], 1):
            if not isinstance(item, dict):
                continue

            event_id = item.get("id") or item.get("audioEventId") or item.get("audio_event_id")
            if isinstance(event_id, str) and event_id.startswith("local-"):
                event_id = None
            values = self._normalize_event_payload(item, index)

            event = existing.get(event_id) if event_id else None
            if event:
                seen_ids.add(event.id)
                changed_fields = self._changed_fields(event, values)
                if changed_fields:
                    for key, value in values.items():
                        setattr(event, key, value)
                    if changed_fields & TTS_STALE_FIELDS:
                        event.tts_status = "STALE"
                        event.text_hash = None
                        self._mark_current_tts_assets_stale(event.id)
                    if changed_fields & TIMELINE_STALE_FIELDS:
                        timeline_stale = True
                        if changed_fields - SPEAKER_BINDING_FIELDS:
                            invalidation_level = "AUDIO_TIMING_CHANGED"
                    changed = True
                result.append(event)
                continue

            event = ShotAudioEvent(
                shot_id=shot_id,
                tts_status=str(item.get("tts_status") or item.get("ttsStatus") or "NOT_GENERATED").upper(),
                text_hash=item.get("text_hash") or item.get("textHash"),
                **values,
            )
            self.db.add(event)
            result.append(event)
            changed = True
            timeline_stale = True
            invalidation_level = "AUDIO_TIMING_CHANGED"

        removed = [event for event_id, event in existing.items() if event_id not in seen_ids]
        for event in removed:
            self._delete_event_references(event)
            self.db.delete(event)
            changed = True
            timeline_stale = True
            invalidation_level = "AUDIO_TIMING_CHANGED"

        if timeline_stale:
            self._mark_shot_audio_stale(shot_id, invalidation_level)
        self.last_sync_changed = changed
        self.last_sync_timeline_stale = timeline_stale

        if changed:
            self.db.commit()
        else:
            self.db.flush()
        for event in result:
            self.db.refresh(event)
        return self.list_events(shot_id)

    def replace_events(self, shot_id: str, events: list) -> List[ShotAudioEvent]:
        return self.sync_events(shot_id, events)

    def current_tts_asset(self, audio_event_id: str) -> Optional[AudioEventTTSAsset]:
        return self.db.query(AudioEventTTSAsset).filter(
            AudioEventTTSAsset.audio_event_id == audio_event_id,
            AudioEventTTSAsset.is_current == True,
        ).order_by(AudioEventTTSAsset.revision.desc()).first()

    def get_tts_asset(self, asset_id: str) -> Optional[AudioEventTTSAsset]:
        return self.db.query(AudioEventTTSAsset).filter(AudioEventTTSAsset.id == asset_id).first()

    def add_tts_asset(self, audio_event_id: str, commit: bool = True, **kwargs) -> AudioEventTTSAsset:
        self.db.query(AudioEventTTSAsset).filter(
            AudioEventTTSAsset.audio_event_id == audio_event_id,
            AudioEventTTSAsset.is_current == True,
        ).update({"is_current": False})
        latest = self.db.query(AudioEventTTSAsset).filter(
            AudioEventTTSAsset.audio_event_id == audio_event_id
        ).order_by(AudioEventTTSAsset.revision.desc()).first()
        asset = AudioEventTTSAsset(
            audio_event_id=audio_event_id,
            revision=(latest.revision + 1) if latest else 1,
            is_current=True,
            **kwargs,
        )
        self.db.add(asset)
        if commit:
            self.db.commit()
            self.db.refresh(asset)
        else:
            self.db.flush()
        return asset

    def latest_timeline(self, shot_id: str) -> Optional[ShotAudioTimeline]:
        return self.db.query(ShotAudioTimeline).filter(
            ShotAudioTimeline.shot_id == shot_id
        ).order_by(ShotAudioTimeline.revision.desc()).first()

    def create_timeline(self, shot_id: str, total_duration: float, generated_from_hash: str, audio_summary: dict, events: list, audio_required_duration: Optional[float] = None) -> ShotAudioTimeline:
        latest = self.latest_timeline(shot_id)
        timeline = ShotAudioTimeline(
            shot_id=shot_id,
            revision=(latest.revision + 1) if latest else 1,
            total_duration=total_duration,
            audio_required_duration=audio_required_duration,
            status="READY",
            generated_from_hash=generated_from_hash,
            audio_summary_json=json.dumps(audio_summary, ensure_ascii=False),
        )
        self.db.add(timeline)
        self.db.flush()
        for item in events:
            self.db.add(ShotAudioTimelineEvent(timeline_id=timeline.id, **item))
        self.db.commit()
        self.db.refresh(timeline)
        return timeline

    def list_timeline_events(self, timeline_id: str) -> List[ShotAudioTimelineEvent]:
        return self.db.query(ShotAudioTimelineEvent).filter(
            ShotAudioTimelineEvent.timeline_id == timeline_id
        ).order_by(ShotAudioTimelineEvent.event_order).all()
