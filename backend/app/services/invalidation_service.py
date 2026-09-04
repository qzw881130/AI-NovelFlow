import json
from typing import Literal

from sqlalchemy.orm import Session

from app.models.audio_drive import ShotAudioTimeline
from app.services.video_director_plan_service import VideoDirectorPlanService
from app.models.shot import Shot


InvalidationLevel = Literal["AUDIO_TIMING_CHANGED", "SPEAKER_BINDING_CHANGED"]


AUDIO_FIELD_KEYS = [
    "audio_status",
    "audio_message",
    "audio_timeline_id",
    "audio_timeline_revision",
    "audio_timeline_hash",
    "speaker_timeline",
    "drive_audio_url",
    "final_audio_url",
    "drive_audio_path",
    "final_audio_path",
    "clip_audio_manifest_path",
    "clip_audio_duration",
]

VIDEO_FACT_KEYS = [
    "prompt_text",
    "prompt_id",
    "workflow_json",
    "video_url",
    "local_path",
    "source_video_url",
    "generated_at",
    "generated_by_task_id",
    "error_message",
]


class InvalidationService:
    def __init__(self, db: Session):
        self.db = db

    def invalidate_audio_downstream(
        self,
        shot_id: str,
        reason: str,
        level: InvalidationLevel = "AUDIO_TIMING_CHANGED",
        mark_audio_stale: bool = True,
        mark_timeline_stale: bool = True,
    ) -> dict:
        shot = self.db.query(Shot).filter(Shot.id == shot_id).first()
        if not shot:
            return {"changed": False, "reason": reason, "level": level}

        if mark_audio_stale:
            shot.audio_status = "STALE"
        shot.video_url = None
        shot.video_status = "pending"
        shot.video_task_id = None

        if shot.chapter:
            shot.chapter.final_video = None

        latest = self.db.query(ShotAudioTimeline).filter(
            ShotAudioTimeline.shot_id == shot_id
        ).order_by(ShotAudioTimeline.revision.desc()).first()
        if latest and mark_timeline_stale:
            latest.status = "STALE"

        def mutate(plan: dict) -> dict:
            plan["invalidation_reason"] = reason
            plan["invalidation_level"] = level
            plan.pop("task_error_message", None)
            plan.pop("error_message", None)
            plan.pop("merged_video_url", None)
            plan.pop("merged_at", None)

            if level == "AUDIO_TIMING_CHANGED":
                plan["keyframe_planning_status"] = "STALE"
                plan["keyframe_planning_message"] = reason

            for key in ("window_plans", "execution_windows", "clips"):
                value = plan.get(key)
                if not isinstance(value, list):
                    continue
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    for field in AUDIO_FIELD_KEYS:
                        item.pop(field, None)
                    for field in VIDEO_FACT_KEYS:
                        item.pop(field, None)
                    item["audio_status"] = "STALE"
                    item["audio_message"] = reason
                    if item.get("status") not in {"PENDING", "STALE"}:
                        item["status"] = "PENDING"
            return plan

        VideoDirectorPlanService(self.db).mutate(shot_id, mutate)
        self.db.flush()
        return {"changed": True, "reason": reason, "level": level}

    @staticmethod
    def _safe_json_dict(value) -> dict:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
