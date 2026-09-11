import re
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Chapter, Novel
from app.services.chapter_subtitle_service import SubtitleNotReady, chapter_subtitles


router = APIRouter()


@router.get("/{novel_id}/chapters/{chapter_id}/subtitles", response_class=Response)
def download_chapter_subtitles(
    novel_id: str,
    chapter_id: str,
    format: Literal["srt", "ass"] = Query("srt"),
    db: Session = Depends(get_db),
):
    """Download the content-bound snapshot of Chapter.final_video, or fail closed."""
    chapter = db.query(Chapter).join(Novel, Chapter.novel_id == Novel.id).filter(
        Chapter.id == chapter_id, Novel.id == novel_id,
    ).first()
    if not chapter:
        raise HTTPException(404, "\u7ae0\u8282\u4e0d\u5b58\u5728\u6216\u4e0d\u5c5e\u4e8e\u5f53\u524d\u5c0f\u8bf4")
    try:
        content = chapter_subtitles(db, chapter.id, format)
    except SubtitleNotReady as exc:
        raise HTTPException(409, str(exc)) from exc
    title = re.sub(r'[\x00-\x1f\x7f/\\:"<>|?*]', "_", chapter.title or "chapter").strip(" .")[:120] or "chapter"
    filename = f"{chapter.number}-{title}.{format}"
    return Response(
        content=content.encode("utf-8"),
        headers={
            "Content-Type": f"{'application/x-subrip' if format == 'srt' else 'text/x-ssa'}; charset=utf-8",
            "Content-Disposition": f"attachment; filename=\"chapter.{format}\"; filename*=UTF-8''{quote(filename, safe='')}",
            "X-Subtitle-Timeline": "rendered-media-v1",
            "Cache-Control": "no-store",
        },
    )
