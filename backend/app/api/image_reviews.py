"""Image quality review history and manual retry endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.models.image_quality_review import ImageQualityReview
from app.services.image_quality_review import current_image_reviews, review_image_task, review_to_dict

router = APIRouter()


class CurrentImage(BaseModel):
    taskId: str | None = None
    imageUrl: str


class CurrentImages(BaseModel):
    images: list[CurrentImage] = Field(max_length=200)


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
