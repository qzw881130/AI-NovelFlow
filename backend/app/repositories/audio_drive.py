import json
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.audio_drive import (
    AudioEventTTSAsset,
    ShotAudioEvent,
    ShotAudioTimeline,
    ShotAudioTimelineEvent,
)


class AudioDriveRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_events(self, shot_id: str) -> List[ShotAudioEvent]:
        return self.db.query(ShotAudioEvent).filter(
            ShotAudioEvent.shot_id == shot_id
        ).order_by(ShotAudioEvent.event_order).all()

    def get_event(self, event_id: str) -> Optional[ShotAudioEvent]:
        return self.db.query(ShotAudioEvent).filter(ShotAudioEvent.id == event_id).first()

    def replace_events(self, shot_id: str, events: list) -> List[ShotAudioEvent]:
        self.db.query(ShotAudioEvent).filter(ShotAudioEvent.shot_id == shot_id).delete()
        created = []
        for index, item in enumerate(events or [], 1):
            event = ShotAudioEvent(
                shot_id=shot_id,
                event_order=int(item.get("order") or item.get("event_order") or index),
                event_type=str(item.get("type") or item.get("event_type") or "DIALOGUE").upper(),
                voice_owner_character_id=item.get("voice_owner_character_id") or item.get("voiceOwnerCharacterId"),
                voice_owner_name=item.get("voice_owner") or item.get("voice_owner_name") or item.get("voiceOwnerName") or item.get("character_name") or "",
                visible_speaker_character_id=item.get("visible_speaker_character_id") or item.get("visibleSpeakerCharacterId"),
                visible_speaker_name=item.get("visible_speaker") or item.get("visible_speaker_name") or item.get("visibleSpeakerName"),
                requires_visible_lipsync=bool(item.get("requires_visible_lipsync") or item.get("requiresVisibleLipsync")),
                text=item.get("text") or "",
                emotion_prompt=item.get("emotion_prompt") or item.get("emotionPrompt") or "自然",
                pause_after=str(item.get("pause_after") or item.get("pauseAfter") or "NONE").upper(),
                tts_status=item.get("tts_status") or item.get("ttsStatus") or "NOT_GENERATED",
                text_hash=item.get("text_hash") or item.get("textHash"),
            )
            self.db.add(event)
            created.append(event)
        self.db.commit()
        for event in created:
            self.db.refresh(event)
        return created

    def current_tts_asset(self, audio_event_id: str) -> Optional[AudioEventTTSAsset]:
        return self.db.query(AudioEventTTSAsset).filter(
            AudioEventTTSAsset.audio_event_id == audio_event_id,
            AudioEventTTSAsset.is_current == True,
        ).order_by(AudioEventTTSAsset.revision.desc()).first()

    def get_tts_asset(self, asset_id: str) -> Optional[AudioEventTTSAsset]:
        return self.db.query(AudioEventTTSAsset).filter(AudioEventTTSAsset.id == asset_id).first()

    def add_tts_asset(self, audio_event_id: str, **kwargs) -> AudioEventTTSAsset:
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
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def latest_timeline(self, shot_id: str) -> Optional[ShotAudioTimeline]:
        return self.db.query(ShotAudioTimeline).filter(
            ShotAudioTimeline.shot_id == shot_id
        ).order_by(ShotAudioTimeline.revision.desc()).first()

    def create_timeline(self, shot_id: str, total_duration: float, generated_from_hash: str, audio_summary: dict, events: list) -> ShotAudioTimeline:
        latest = self.latest_timeline(shot_id)
        timeline = ShotAudioTimeline(
            shot_id=shot_id,
            revision=(latest.revision + 1) if latest else 1,
            total_duration=total_duration,
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
