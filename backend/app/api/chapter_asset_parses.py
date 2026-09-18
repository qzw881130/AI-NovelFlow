from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Chapter
from app.models.chapter_asset_parse import ChapterAssetParseRun
from app.schemas.chapter_asset_parse import ParseChapterAssetsRequest
from app.services.chapter_asset_parse_service import ChapterAssetParseService, run_response
from app.services.chapter_asset_pipeline import parse_and_resolve

router = APIRouter()
PREFIX = "/{novel_id}/chapters/{chapter_id}/asset-parses"


def require_chapter(db, novel_id, chapter_id):
    if not db.query(Chapter.id).filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id).first():
        raise HTTPException(404, "章回不存在")


@router.post(PREFIX)
async def parse_assets(novel_id: str, chapter_id: str, data: ParseChapterAssetsRequest, db: Session = Depends(get_db)):
    return await parse_and_resolve(db, novel_id, chapter_id, data.kinds)


@router.get(PREFIX)
def list_parses(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    require_chapter(db, novel_id, chapter_id)
    runs = db.query(ChapterAssetParseRun).filter_by(novel_id=novel_id, chapter_id=chapter_id).order_by(
        ChapterAssetParseRun.created_at.desc(), ChapterAssetParseRun.id.desc()).all()
    return {"success": True, "data": [run_response(db, run, detail=False) for run in runs]}


@router.get(PREFIX + "/{run_id}")
def get_parse(novel_id: str, chapter_id: str, run_id: str, db: Session = Depends(get_db)):
    require_chapter(db, novel_id, chapter_id)
    run = db.query(ChapterAssetParseRun).filter_by(id=run_id, novel_id=novel_id, chapter_id=chapter_id).first()
    if not run:
        raise HTTPException(404, "解析记录不存在")
    return {"success": True, "data": run_response(db, run)}
