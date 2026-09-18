from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.asset_debug_service import AssetDebugService

router = APIRouter()


@router.get('/novels/{novel_id}/asset-debug')
def record_trace(novel_id:str, kind:str, record_id:str, limit:int=Query(400,ge=20,le=1200), db:Session=Depends(get_db)):
    with db.no_autoflush:
        data=AssetDebugService(db,novel_id,limit).anchor(kind,record_id)
    return {'success':True,'data':data}


@router.get('/novels/{novel_id}/chapters/{chapter_id}/asset-debug')
def chapter_trace(novel_id:str, chapter_id:str, shot_id:str|None=None, rsa_id:str|None=None,
                  limit:int=Query(400,ge=20,le=1200), db:Session=Depends(get_db)):
    with db.no_autoflush:
        data=AssetDebugService(db,novel_id,limit).chapter(chapter_id,shot_id=shot_id,rsa_id=rsa_id)
    return {'success':True,'data':data}


@router.get('/tasks/{task_id}/asset-debug')
def task_trace(task_id:str, limit:int=Query(400,ge=20,le=1200), db:Session=Depends(get_db)):
    with db.no_autoflush:
        data=AssetDebugService.from_task(db,task_id,limit)
    return {'success':True,'data':data}


@router.get('/novels/{novel_id}/asset-debug/records/{kind}/{record_id}')
def record(novel_id:str, kind:str, record_id:str, db:Session=Depends(get_db)):
    with db.no_autoflush:
        data=AssetDebugService(db,novel_id).record(kind,record_id)
    return {'success':True,'data':data}
