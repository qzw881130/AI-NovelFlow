import copy
import json
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.models.shot import Shot


WORKER_FACT_KEYS = {
    "status",
    "video_url",
    "local_path",
    "source_video_url",
    "generated_at",
    "generated_by_task_id",
    "workflow_json",
    "prompt_id",
    "audio_status",
    "audio_message",
    "drive_audio_url",
    "final_audio_url",
    "drive_audio_path",
    "final_audio_path",
    "audio_timeline_id",
    "audio_timeline_revision",
    "audio_timeline_hash",
    "speaker_timeline",
    "clip_audio_manifest_path",
    "clip_audio_duration",
}
TOP_LEVEL_FACT_KEYS = {
    "merged_video_url",
    "merged_at",
    "task_error_message",
    "error_message",
    "invalidation_reason",
    "invalidation_level",
}


class PlanRevisionConflict(Exception):
    pass


class PlanOwnershipError(Exception):
    pass


class VideoDirectorPlanService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def safe_json_dict(value) -> dict:
        if isinstance(value, dict):
            return copy.deepcopy(value)
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def assert_user_plan_payload_allowed(payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        forbidden = set(payload) & TOP_LEVEL_FACT_KEYS
        for key in ("clips", "window_plans", "execution_windows"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        forbidden |= set(item) & WORKER_FACT_KEYS
        if forbidden:
            raise PlanOwnershipError(f"用户请求不能写入生成事实字段: {', '.join(sorted(forbidden))}")

    def mutate(
        self,
        shot_id: str,
        mutator: Callable[[dict], Optional[dict]],
        *,
        expected_revision: Optional[int] = None,
        require_revision: bool = False,
        max_retries: int = 3,
    ) -> tuple[dict, int]:
        for _ in range(max_retries):
            shot = self.db.query(Shot).filter(Shot.id == shot_id).first()
            if not shot:
                raise ValueError("分镜不存在")
            current_revision = int(shot.video_director_plan_revision or 0)
            if require_revision:
                if expected_revision is None or expected_revision != current_revision:
                    raise PlanRevisionConflict("Video Director Plan 已更新，请刷新后重试")

            current_plan = self.safe_json_dict(shot.video_director_plan)
            next_plan = mutator(copy.deepcopy(current_plan))
            if next_plan is None:
                next_plan = current_plan
            if next_plan == current_plan:
                return next_plan, current_revision

            next_revision = current_revision + 1
            updated = self.db.query(Shot).filter(
                Shot.id == shot_id,
                Shot.video_director_plan_revision == current_revision,
            ).update({
                "video_director_plan": json.dumps(next_plan, ensure_ascii=False),
                "video_director_plan_revision": next_revision,
            }, synchronize_session=False)
            if updated == 1:
                self.db.commit()
                self.db.refresh(shot)
                return next_plan, next_revision
            self.db.rollback()

        raise PlanRevisionConflict("Video Director Plan 并发更新，请重试")

    def replace_structure(self, shot_id: str, plan: dict, expected_revision: Optional[int]) -> tuple[dict, int]:
        return self.mutate(
            shot_id,
            lambda _current: copy.deepcopy(plan),
            expected_revision=expected_revision,
            require_revision=True,
            max_retries=1,
        )

    def patch_clip_prompt(self, shot_id: str, collection: str, index: int, prompt_text: str) -> tuple[dict, int]:
        def apply(plan: dict) -> dict:
            items = plan.get(collection) if isinstance(plan.get(collection), list) else []
            key = "window_index" if collection == "window_plans" else "clip_index"
            fallback_key = "clip_index" if collection == "window_plans" else "window_index"
            for position, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                item_index = item.get(key) or item.get(fallback_key) or position + 1
                if int(item_index or 0) == int(index):
                    item["prompt_text"] = prompt_text
                    break
            else:
                items.append({key: index, "prompt_text": prompt_text})
            plan[collection] = items
            return plan

        return self.mutate(shot_id, apply)

    def patch_keyframe_description(self, shot_id: str, keyframe_index: int, description: str) -> tuple[dict, int]:
        def apply(plan: dict) -> dict:
            keyframes = plan.get("keyframes") if isinstance(plan.get("keyframes"), list) else []
            for item in keyframes:
                if isinstance(item, dict) and int(item.get("index") or -1) == int(keyframe_index):
                    item["description"] = description
                    break
            plan["keyframes"] = keyframes
            return plan

        return self.mutate(shot_id, apply)
