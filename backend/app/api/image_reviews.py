"""Image quality review history and manual retry endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.models.image_quality_review import ImageQualityReview
from app.models.novel import Character, Scene, Prop
from app.models.task import Task
from app.services.image_quality_review import (IMAGE_TYPES, current_image_reviews,
                                                image_result_key, review_image_task, review_to_dict)

router = APIRouter()


class CurrentImage(BaseModel):
    taskId: str | None = None
    imageUrl: str


class CurrentImages(BaseModel):
    images: list[CurrentImage] = Field(max_length=200)


class LibraryImageReviewRequest(BaseModel):
    kind: str
    entityId: str


@router.post("/image-review-statuses")
def image_review_statuses(data: CurrentImages, db: Session = Depends(get_db)):
    return {"success": True, "data": current_image_reviews(db, [item.model_dump() for item in data.images])}


@router.get("/{task_id}/image-reviews")
def list_image_reviews(task_id: str, db: Session = Depends(get_db)):
    reviews = db.query(ImageQualityReview).filter(ImageQualityReview.task_id == task_id).order_by(
        ImageQualityReview.created_at.desc(), ImageQualityReview.id.desc()).all()
    return {"success": True, "data": [review_to_dict(review) for review in reviews]}


@router.post("/{task_id}/image-reviews")
async def create_image_review(task_id: str, db: Session = Depends(get_db)):
    try:
        review = await review_image_task(db, task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": review_to_dict(review)}


@router.post("/library-image-reviews")
async def create_library_image_review(data: LibraryImageReviewRequest, db: Session = Depends(get_db)):
    sources = {
        "character": (Character, "portrait_task_id", "character_id", "character_portrait"),
        "scene": (Scene, "scene_task_id", "scene_id", "scene_image"),
        "prop": (Prop, "prop_task_id", "prop_id", "prop_image"),
    }
    if data.kind not in sources:
        raise HTTPException(400, "不支持的图库类型")
    model, task_field, entity_field, task_type = sources[data.kind]
    entity = db.get(model, data.entityId)
    if not entity:
        raise HTTPException(404, "图库项目不存在")
    if not entity.image_url or (data.kind == "prop" and entity.existence == "FICTIONAL_OR_NONEXISTENT"):
        raise HTTPException(409, "当前项目没有可评审的图片")
    task = db.get(Task, getattr(entity, task_field)) if getattr(entity, task_field) else None
    if not (task and task.type in IMAGE_TYPES and task.status == "completed"
            and task.novel_id == entity.novel_id and getattr(task, entity_field) == entity.id
            and task.prompt_text and image_result_key(task.result_url) == image_result_key(entity.image_url)):
        if data.kind == "scene":
            prompt = (f"纯环境场景参考图：{entity.name}。场景描述：{entity.description or ''}。"
                      f"环境设定：{entity.setting or ''}。画面不应出现人物。")
        else:
            label = "角色" if data.kind == "character" else "道具"
            prompt = (f"{label}参考图：{entity.name}。{label}描述：{entity.description or ''}。"
                      f"外观：{entity.appearance or ''}")
        task = Task(type=task_type, status="completed", novel_id=entity.novel_id,
                    name=f"图库图片评审输入 · {entity.name}", result_url=entity.image_url,
                    prompt_text=prompt, **{entity_field: entity.id})
        db.add(task)
        db.flush()
        setattr(entity, task_field, task.id)
        db.commit()
    try:
        review = await review_image_task(db, task.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"success": True, "data": {"taskId": task.id, "review": review_to_dict(review)}}
