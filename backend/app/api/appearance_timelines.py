from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.novel import Chapter
from app.models.asset_resolution import ChapterCharacterAppearanceEvent as Event
from app.models.appearance_timeline import AppearanceTimelineRun as Run
from app.schemas.appearance_timeline import TimelineBuildRequest, AppearanceReviewRequest
from app.services.appearance_timeline_service import AppearanceTimelineService, timeline_response, chapter_basis

router = APIRouter()
ROOT = "/{novel_id}/chapters/{chapter_id}"


def require_chapter(db, novel_id, chapter_id):
    chapter = db.query(Chapter).filter_by(id=chapter_id, novel_id=novel_id).first()
    if not chapter:
        raise HTTPException(404, "章回不存在")
    return chapter


@router.post(ROOT + "/appearance-timelines")
def build(novel_id: str, chapter_id: str, data: TimelineBuildRequest, db: Session = Depends(get_db)):
    return AppearanceTimelineService(db).build(novel_id, chapter_id, data.force)


@router.post(ROOT + "/appearance-timelines/rebuild-through")
def rebuild_through(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    return AppearanceTimelineService(db).rebuild_through(novel_id, chapter_id)


@router.get(ROOT + "/appearance-timelines")
def history(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    require_chapter(db, novel_id, chapter_id)
    rows = db.query(Run).filter_by(novel_id=novel_id, chapter_id=chapter_id).order_by(Run.created_at.desc(), Run.id.desc()).all()
    return {"success": True, "data": [timeline_response(db, row, False) for row in rows]}


@router.get(ROOT + "/appearance-timelines/{run_id}")
def detail(novel_id: str, chapter_id: str, run_id: str, db: Session = Depends(get_db)):
    require_chapter(db, novel_id, chapter_id)
    row = db.query(Run).filter_by(id=run_id, novel_id=novel_id, chapter_id=chapter_id).first()
    if not row:
        raise HTTPException(404, "时间线记录不存在")
    return {"success": True, "data": timeline_response(db, row)}


@router.get(ROOT + "/appearance-events")
def events(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    chapter = require_chapter(db, novel_id, chapter_id)
    try:
        basis = chapter_basis(db, novel_id, chapter)
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    rows = []
    for item in basis["events"]:
        event = db.get(Event, item["proposal"]["id"])
        rows.append({**item, "source_start": event.source_start, "source_end": event.source_end, "status": event.status,
                     "resolvedAppearanceId": event.resolved_appearance_id, "locationProof": event.location_proof})
    return {"success": True, "data": {"sourceHash": basis["source_hash"], "content": basis["content"], "events": rows}}


@router.post(ROOT + "/appearance-events/{event_id}/review")
def review(novel_id: str, chapter_id: str, event_id: str, data: AppearanceReviewRequest, db: Session = Depends(get_db)):
    return AppearanceTimelineService(db).review(novel_id, chapter_id, event_id, data)


@router.get(ROOT + "/appearance-at")
def appearance_at(novel_id: str, chapter_id: str, character_id: str, source_start: int, db: Session = Depends(get_db)):
    require_chapter(db, novel_id, chapter_id)
    return {"success": True, "data": AppearanceTimelineService(db).at(novel_id, chapter_id, character_id, source_start)}
