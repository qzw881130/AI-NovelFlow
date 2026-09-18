from fastapi import APIRouter,Depends,HTTPException
from typing import Literal
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.chapter_governance import ChapterRebuildRun
from app.schemas.chapter_asset_parse import StrictPayload
from app.services.chapter_governance import pipeline_state
from app.services.chapter_rebuild_service import ChapterRebuildService,response

router=APIRouter()

class RebuildRequest(StrictPayload):
    mode: Literal['REBUILD','CONTINUE']='REBUILD'
    include_previous: bool=False

@router.get('/{novel_id}/chapters/{chapter_id}/pipeline-state')
def state(novel_id:str,chapter_id:str,db:Session=Depends(get_db)):
    return {'success':True,'data':pipeline_state(db,novel_id,chapter_id)}

@router.get('/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/runtime-readiness')
def runtime_readiness(novel_id:str,chapter_id:str,shot_id:str,db:Session=Depends(get_db)):
    from app.api.resolved_shot_assets import scope
    from app.services.runtime_gate import runtime_checks
    scope(db,novel_id,chapter_id,shot_id)
    return {'success':True,'data':runtime_checks(db,shot_id)}

@router.post('/{novel_id}/chapters/{chapter_id}/rebuild-assets')
def rebuild(novel_id:str,chapter_id:str,data:RebuildRequest,db:Session=Depends(get_db)):
    return ChapterRebuildService(db).enqueue(novel_id,chapter_id,**data.model_dump())

@router.get('/{novel_id}/chapters/{chapter_id}/rebuild-assets')
def history(novel_id:str,chapter_id:str,db:Session=Depends(get_db)):
    pipeline_state(db,novel_id,chapter_id)
    return {'success':True,'data':[response(r) for r in db.query(ChapterRebuildRun).filter_by(novel_id=novel_id,chapter_id=chapter_id).order_by(ChapterRebuildRun.created_at.desc())]}

@router.get('/{novel_id}/chapters/{chapter_id}/rebuild-assets/{run_id}')
def detail(novel_id:str,chapter_id:str,run_id:str,db:Session=Depends(get_db)):
    row=db.query(ChapterRebuildRun).filter_by(id=run_id,novel_id=novel_id,chapter_id=chapter_id).first()
    if not row:raise HTTPException(404,'重建记录不存在')
    return {'success':True,'data':{**response(row),'inputs':row.inputs}}
