"""Keep confirmed people in generated scene assets out of Shot references."""

import json

from app.models.image_quality_review import ImageQualityReview
from app.models.task import Task
from app.services.image_quality_review import image_result_key


def scene_reference_review_status(db, scene) -> tuple[bool, str]:
    """Reject a scene reference only when its current image was confirmed to contain people.

    A manually uploaded or explicitly replaced scene image has no matching
    scene-image task result; that replacement is treated as user-approved.
    Historical images without a conclusive review remain usable.
    """
    if not scene or not scene.image_url:
        return False, "场景图不存在"
    task = db.get(Task, scene.scene_task_id) if scene.scene_task_id else None
    if not task or task.type != "scene_image" or image_result_key(task.result_url) != image_result_key(scene.image_url):
        return True, "用户提供或替换的场景图"

    reviews = db.query(ImageQualityReview).filter(
        ImageQualityReview.task_id == task.id,
        ImageQualityReview.status == "success",
    ).order_by(ImageQualityReview.created_at.desc(), ImageQualityReview.id.desc()).all()
    for review in reviews:
        try:
            snapshot = json.loads(review.input_snapshot_json or "{}")
        except (TypeError, ValueError):
            continue
        if image_result_key(snapshot.get("generated_image")) != image_result_key(scene.image_url):
            continue
        try:
            dimensions = json.loads(review.dimensions_json or "{}")
        except (TypeError, ValueError):
            dimensions = {}
        person_count = dimensions.get("CHARACTER_COUNT") or {}
        if isinstance(person_count, dict) and person_count.get("status") == "FAIL":
            return False, "场景图 AI 审核确认有人物；请使用无人背景版本"
        return True, "场景图未确认有人物"
    return True, "当前场景图尚无明确人物违规记录"
