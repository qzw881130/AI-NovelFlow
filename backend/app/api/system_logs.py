"""Read-only Stage B System Logs API."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.system_log_service import SystemLogService


router = APIRouter()


@router.get("/filters")
def system_log_filters(db: Session = Depends(get_db)):
    with db.no_autoflush:
        data = SystemLogService(db).filters()
    return {"success": True, "data": data}


@router.get("/")
def system_logs(
    view: str = Query("attention", pattern="^(all|errors|needs_review|attention)$"),
    level: str | None = None,
    service: str | None = None,
    provider: str | None = None,
    novel_id: str | None = None,
    chapter_id: str | None = None,
    shot_id: str | None = None,
    task_id: str | None = None,
    error_code: str | None = None,
    failure_class: str | None = None,
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    filters = {
        "view": view, "level": level, "service": service, "provider": provider,
        "novel_id": novel_id, "chapter_id": chapter_id, "shot_id": shot_id,
        "task_id": task_id, "error_code": error_code, "failure_class": failure_class,
        "from_time": from_time, "to_time": to_time, "cursor": cursor, "limit": limit,
    }
    with db.no_autoflush:
        data = SystemLogService(db).list(**filters)
    return {"success": True, "data": data}


@router.get("/{event_id}")
def system_log_detail(event_id: str, db: Session = Depends(get_db)):
    with db.no_autoflush:
        data = SystemLogService(db).detail(event_id)
    return {"success": True, "data": data}
