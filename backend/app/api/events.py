"""Read-only event center; notification settings retain their existing API."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.notification import BusinessEvent
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.models.llm_log import LLMLog
from app.models.image_quality_review import ImageQualityReview
from app.services.business_events import obj
from app.services.notification_registry import EVENT_REGISTRY

router = APIRouter()


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value and value.tzinfo is None else value.isoformat() if value else None


def serialize(row, novel_title=None, chapter_title=None, shot_index=None):
    registry = EVENT_REGISTRY.get(row.event_type)
    return {"event_id": row.id, "event_type": row.event_type,
            "name": registry.name if registry else row.event_type,
            "category": registry.category if registry else "其他",
            "timestamp": iso(row.timestamp), "recorded_at": iso(row.recorded_at),
            **{key: getattr(row, key) for key in ("novel_id", "chapter_id", "shot_id", "visual_state_id", "clip_id",
                "task_id", "review_id", "llm_log_id", "status", "raw_status", "needs_attention", "source", "trigger",
                "message", "historical", "is_test", "notification_status")},
            "novel_title": novel_title, "chapter_title": chapter_title,
            "shot_index": shot_index, "details": obj(row.details_json)}


def utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


@router.get("")
def list_business_events(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                         event_type: str | None = None, status: str | None = None,
                         novel_id: str | None = None, chapter_id: str | None = None,
                         shot_id: str | None = None, start_time: datetime | None = None,
                         end_time: datetime | None = None, view: str = "all",
                         timezone_offset: int = Query(0, ge=-840, le=840), db: Session = Depends(get_db)):
    if status and status not in {"SUCCESS", "FAIL", "ERROR", "INFO"}:
        raise HTTPException(422, "无效状态")
    if view not in {"all", "attention", "today"}:
        raise HTTPException(422, "无效事件视图")
    if start_time and end_time and utc_naive(start_time) > utc_naive(end_time):
        raise HTTPException(422, "开始时间不能晚于结束时间")
    query = db.query(BusinessEvent)
    for key, value in (("event_type", event_type), ("status", status), ("novel_id", novel_id),
                       ("chapter_id", chapter_id), ("shot_id", shot_id)):
        if value:
            query = query.filter(getattr(BusinessEvent, key) == value)
    if start_time:
        query = query.filter(BusinessEvent.timestamp >= utc_naive(start_time))
    if end_time:
        query = query.filter(BusinessEvent.timestamp <= utc_naive(end_time))
    # Browser offset (UTC minus local) makes "today" match the user's timezone.
    local_now = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=timezone_offset)
    today_utc = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=timezone_offset)
    today_filters = (BusinessEvent.status.in_(["FAIL", "ERROR"]), BusinessEvent.timestamp >= today_utc,
                     BusinessEvent.timestamp < today_utc + timedelta(days=1))
    counts = {"all": query.count(), "attention": query.filter(BusinessEvent.needs_attention.is_(True)).count(),
              "today": query.filter(*today_filters).count()}
    if view == "attention":
        query = query.filter(BusinessEvent.needs_attention.is_(True))
    elif view == "today":
        query = query.filter(*today_filters)
    total = query.count()
    # Only the three display fields are needed here. Loading a complete Shot also
    # fetches video_director_plan, which can be several MB for each event row.
    rows = (query.add_columns(Novel.title, Chapter.title, Shot.index)
            .outerjoin(Novel, BusinessEvent.novel_id == Novel.id)
            .outerjoin(Chapter, BusinessEvent.chapter_id == Chapter.id)
            .outerjoin(Shot, BusinessEvent.shot_id == Shot.id)
            .order_by(BusinessEvent.timestamp.desc(), BusinessEvent.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return {"success": True, "data": {"items": [serialize(*row) for row in rows],
            "page": page, "page_size": page_size, "total": total, "counts": counts}}


@router.get("/options")
def event_options(db: Session = Depends(get_db)):
    novels = db.query(Novel.id, Novel.title).join(BusinessEvent, BusinessEvent.novel_id == Novel.id).distinct().all()
    chapters = db.query(Chapter.id, Chapter.title, Chapter.novel_id).join(BusinessEvent, BusinessEvent.chapter_id == Chapter.id).distinct().all()
    shots = db.query(Shot.id, Shot.index, Shot.chapter_id).join(BusinessEvent, BusinessEvent.shot_id == Shot.id).distinct().all()
    return {"success": True, "data": {
        "events": [{"event_type": code, "name": e.name, "category": e.category} for code, e in EVENT_REGISTRY.items()],
        "novels": [{"id": id, "title": title} for id, title in novels],
        "chapters": [{"id": id, "title": title, "novel_id": novel} for id, title, novel in chapters],
        "shots": [{"id": id, "index": index, "chapter_id": chapter} for id, index, chapter in shots]}}


@router.get("/{event_id}")
def event_detail(event_id: str, db: Session = Depends(get_db)):
    row = db.get(BusinessEvent, event_id)
    if not row:
        raise HTTPException(404, "事件不存在")
    novel = db.get(Novel, row.novel_id) if row.novel_id else None
    chapter = db.get(Chapter, row.chapter_id) if row.chapter_id else None
    shot = db.get(Shot, row.shot_id) if row.shot_id else None
    result = serialize(row, novel.title if novel else None,
                       chapter.title if chapter else None, shot.index if shot else None)
    links = []
    if novel and chapter and shot and chapter.novel_id == novel.id and shot.chapter_id == chapter.id:
        params = {"tab": "video", "eventShot": shot.id}
        plan = obj(shot.video_director_plan)
        valid_state = any(str(k.get("index")) == row.visual_state_id for k in plan.get("keyframes", []))
        clip = next((c for c in plan.get("clip_plan", []) if f"{shot.id}:clip:{c.get('clip_index')}" == row.clip_id), None)
        if row.visual_state_id and valid_state:
            params["visualState"] = row.visual_state_id
        elif clip:
            params["clip"] = str(clip["clip_index"])
        links.append({"label": "查看视觉状态" if valid_state and row.visual_state_id else "查看对应 Clip" if clip else "查看对应 Shot",
                      "href": f"/novels/{novel.id}/chapters/{chapter.id}/generate?{urlencode(params)}#shot-{shot.index}"})
    task = db.get(Task, row.task_id) if row.task_id else None
    review = db.get(ImageQualityReview, row.review_id) if row.review_id else None
    result["review_target"] = {"id": task.id, "name": task.name, "review_id": review.id} if review and task and review.task_id == task.id else None
    if row.llm_log_id and db.get(LLMLog, row.llm_log_id):
        links.append({"label": "查看 LLM 日志", "href": f"/llm-logs?{urlencode({'logId': row.llm_log_id})}"})
    result["links"] = links
    result["notification_result"] = obj(row.notification_result)
    return {"success": True, "data": result}
