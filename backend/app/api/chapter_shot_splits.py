from fastapi import APIRouter, Depends, HTTPException
import json
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.chapter_shot_split import ChapterShotSplitRun
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.services.chapter_shot_split_service import split_state
from app.services.scene_grounding import classify_run as classify_scene_grounding
from app.services.controlled_degradation_service import admit as admit_narration_card

router = APIRouter()


@router.get('/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/treatment-validation')
def treatment_validation(novel_id:str,chapter_id:str,shot_id:str,db:Session=Depends(get_db)):
    from app.services.chapter_governance import require_source
    from app.services.shot_treatment_contract import validate_source_contract
    if not db.query(Chapter.id).filter_by(id=chapter_id,novel_id=novel_id).first() or not db.query(Shot.id).filter_by(id=shot_id,chapter_id=chapter_id).first():
        raise HTTPException(404,'分镜不存在')
    try:
        source=require_source(db,shot_id)
        run=db.get(ChapterShotSplitRun,source.run_id)
        report=validate_source_contract(source,run.inputs['basis'])
        report.update(shot_id=shot_id,authoritative_revision_id=source.revision_id or source.run_id,
                      revision=source.revision,revision_seal=source.seal)
        return {'success':True,'data':report}
    except HTTPException as exc:
        unavailable='CONTRACT_UNAVAILABLE' in str(exc.detail)
        return {'success':True,'data':{'status':'CONTRACT_UNAVAILABLE' if unavailable else 'FAIL',
            'visual_semantics_verified':False,'issues':[{'code':'CONTRACT_UNAVAILABLE' if unavailable else 'SOURCE_NOT_CURRENT','detail':exc.detail}]}}
    except ValueError as exc:
        return {'success':True,'data':{'status':'FAIL','visual_semantics_verified':False,'issues':[{'code':'TREATMENT_VALIDATION_FAILED','message':str(exc)}]}}


@router.get("/{novel_id}/chapters/{chapter_id}/split-state")
def state(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    return {"success": True, "data": split_state(db, novel_id, chapter_id)}


@router.get("/{novel_id}/chapters/{chapter_id}/split-runs")
def runs(novel_id: str, chapter_id: str, db: Session = Depends(get_db)):
    if not db.query(Chapter.id).filter_by(id=chapter_id,novel_id=novel_id).first():
        raise HTTPException(404,"章回不存在")
    rows = db.query(ChapterShotSplitRun).filter_by(novel_id=novel_id,chapter_id=chapter_id).order_by(ChapterShotSplitRun.created_at.desc(),ChapterShotSplitRun.id.desc()).all()
    return {"success":True,"data":[{"id":r.id,"taskId":r.task_id,"status":r.status,"issues":r.issues,"createdAt":r.created_at} for r in rows]}


@router.get("/{novel_id}/chapters/{chapter_id}/split-runs/{run_id}")
def detail(novel_id: str, chapter_id: str, run_id: str, db: Session = Depends(get_db)):
    row = db.query(ChapterShotSplitRun).filter_by(id=run_id,novel_id=novel_id,chapter_id=chapter_id).first()
    if not row: raise HTTPException(404,"分镜拆分记录不存在")
    return {"success":True,"data":{"id":row.id,"taskId":row.task_id,"version":row.version,"status":row.status,
        "inputs":row.inputs,"inputHash":row.input_hash,"call":row.call,"result":row.result,"resultHash":row.result_hash,"issues":row.issues}}


@router.get("/{novel_id}/chapters/{chapter_id}/split-runs/{run_id}/scene-grounding")
def scene_grounding(novel_id: str, chapter_id: str, run_id: str, db: Session = Depends(get_db)):
    return {"success":True,"data":classify_scene_grounding(db,novel_id,chapter_id,run_id)}


@router.post("/{novel_id}/chapters/{chapter_id}/split-runs/{run_id}/narration-card")
def create_narration_card_child(novel_id: str, chapter_id: str, run_id: str, db: Session = Depends(get_db)):
    return {"success":True,"data":admit_narration_card(db,novel_id,chapter_id,run_id)}


def _card_shot(db,novel_id,chapter_id,shot_id):
    if not db.query(Chapter.id).filter_by(id=chapter_id,novel_id=novel_id).first():raise HTTPException(404,'章回不存在')
    shot=db.query(Shot).filter_by(id=shot_id,chapter_id=chapter_id).first()
    if not shot:raise HTTPException(404,'分镜不存在')
    return shot


@router.post('/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/narration-card/audio-prepare')
def prepare_narration_card_audio(novel_id:str,chapter_id:str,shot_id:str,forceTts:bool=False,db:Session=Depends(get_db)):
    _card_shot(db,novel_id,chapter_id,shot_id)
    from app.services.narration_card_service import prepare_audio
    return prepare_audio(db,shot_id,force_tts=forceTts)


@router.post('/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/narration-card/render')
async def render_narration_card(novel_id:str,chapter_id:str,shot_id:str,db:Session=Depends(get_db)):
    _card_shot(db,novel_id,chapter_id,shot_id)
    from app.services.narration_card_service import create_render_task
    return {'success':True,'data':create_render_task(db,shot_id)}


@router.get('/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/narration-card')
def narration_card_state(novel_id:str,chapter_id:str,shot_id:str,db:Session=Depends(get_db)):
    shot=_card_shot(db,novel_id,chapter_id,shot_id)
    from app.services.narration_card_service import capture,completed_artifact
    try:inputs=capture(db,shot_id);blocker=None
    except HTTPException as exc:inputs=None;blocker=exc.detail
    try:artifact=completed_artifact(db,shot);blocker=None
    except HTTPException as exc:artifact=None;blocker=blocker or exc.detail
    public_artifact=({key:artifact.get(key) for key in ('task_id','url','sha256','bytes','duration','frames','source_range')}
        if artifact else None)
    return {'success':True,'data':{'shotId':shot_id,'completionDisposition':getattr(shot,'completion_disposition','NORMAL'),
        'audioReady':inputs is not None,'artifact':public_artifact,'blocker':blocker}}


@router.get('/{novel_id}/chapters/{chapter_id}/completion-readiness')
def chapter_completion_readiness(novel_id:str,chapter_id:str,db:Session=Depends(get_db)):
    from app.services.chapter_video_merge_service import completion_readiness
    return {'success':True,'data':completion_readiness(db,novel_id,chapter_id)}


@router.get('/{novel_id}/chapters/{chapter_id}/completion')
def chapter_completion(novel_id:str,chapter_id:str,db:Session=Depends(get_db)):
    from app.services.chapter_video_merge_service import current_completion
    return {'success':True,'data':current_completion(db,novel_id,chapter_id)}


@router.post('/{novel_id}/chapters/{chapter_id}/completion')
async def complete_chapter(novel_id:str,chapter_id:str,expectedManifestHash:str|None=None,
        retryFailedTaskId:str|None=None,db:Session=Depends(get_db)):
    from app.services.chapter_video_merge_service import admit_completion,run_completion
    task,created=admit_completion(db,novel_id,chapter_id,expected_manifest_hash=expectedManifestHash,
        retry_failed_task_id=retryFailedTaskId)
    from app.services.background_workers import worker_manager
    if task.status=='pending':worker_manager.worker('chapter_video').enqueue_once(task.id,lambda:run_completion(task.id))
    value=json.loads(task.metadata_json or '{}');manifest=value.get('completion_manifest') or {}
    return {'success':True,'data':{'taskId':task.id,'status':task.status,
        'manifestHash':value.get('manifest_hash'),'counts':manifest.get('counts'),
        'reused':not created,'retryRequired':task.status=='failed'}}
