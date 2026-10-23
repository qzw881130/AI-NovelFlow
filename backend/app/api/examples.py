"""示例小说目录、正文预览与原子导入。"""
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.novels import create_novel_in_session
from app.constants.examples import EXAMPLES
from app.core.database import get_db
from app.models.novel import Chapter
from app.schemas.novel import NovelCreate
from app.services.business_events import publish

router = APIRouter()
logger = logging.getLogger(__name__)


def _record_import_event(event_type: str, payload: dict) -> None:
    try:
        publish(event_type, payload)
    except Exception:
        logger.exception("示例小说导入结果已确定，但事件记录失败: %s", event_type)


def _summary(example_id: str, example: dict) -> dict:
    return {
        "id": example_id,
        "title": example["title"],
        "category": example["category"],
        "description": example["description"],
        "chapterCount": len(example["chapters"]),
    }


@router.get("/", response_model=dict)
def list_examples():
    return {"success": True, "data": [_summary(key, value) for key, value in EXAMPLES.items()]}


@router.get("/{example_id}/", response_model=dict)
def get_example(example_id: str):
    example = EXAMPLES.get(example_id)
    if not example:
        raise HTTPException(status_code=404, detail="示例小说不存在")
    return {"success": True, "data": {
        **_summary(example_id, example),
        "chapters": [
            {"number": number, "title": chapter["title"], "content": chapter["content"]}
            for number, chapter in enumerate(example["chapters"], 1)
        ],
    }}


@router.post("/{example_id}/import/", response_model=dict)
def import_example(example_id: str, db: Session = Depends(get_db)):
    started = time.perf_counter()
    example = EXAMPLES.get(example_id)
    novel_id = None
    chapter_count = len(example["chapters"]) if example else 0
    try:
        if not example:
            raise HTTPException(status_code=404, detail="示例小说不存在")
        if not example["chapters"] or any(
            not chapter.get("title", "").strip() or not chapter.get("content", "").strip()
            for chapter in example["chapters"]
        ):
            raise HTTPException(status_code=422, detail="示例章节数据不完整，导入已取消")

        # 与 POST /api/novels/ 共用默认模板、宽高比及状态初始化。
        novel = create_novel_in_session(NovelCreate(
            title=example["title"], description=example["description"]
        ), db)
        novel_id = novel.id
        for number, source in enumerate(example["chapters"], 1):
            db.add(Chapter(
                novel_id=novel.id, number=number,
                title=source["title"], content=source["content"],
            ))
        novel.chapter_count = chapter_count
        db.commit()
    except Exception as exc:
        db.rollback()
        _record_import_event("example.import.failed", {
            "novel_id": novel_id,
            "source": "example_import", "trigger": "manual", "status": "FAIL",
            "message": f"示例小说导入失败：{str(exc.detail) if isinstance(exc, HTTPException) else str(exc)}",
            "details": {"example_id": example_id, "chapter_count": chapter_count,
                        "duration_ms": round((time.perf_counter() - started) * 1000)},
        })
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"导入失败：{exc}") from exc

    _record_import_event("example.import.completed", {
        "novel_id": novel_id,
        "source": "example_import", "trigger": "manual", "status": "SUCCESS",
        "message": f"示例小说已导入，共 {chapter_count} 章",
        "details": {"example_id": example_id, "chapter_count": chapter_count,
                    "duration_ms": round((time.perf_counter() - started) * 1000)},
    })
    return {"success": True, "data": {"novel_id": novel_id, "chapter_count": chapter_count}}
