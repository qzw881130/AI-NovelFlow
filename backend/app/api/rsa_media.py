from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.rsa_media import RsaImageAttempt, RsaMediaArtifact
from app.services.rsa_media_contract import artifact_proof

router=APIRouter()


@router.get('/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/image-lineage')
def image_lineage(novel_id:str,chapter_id:str,shot_id:str,db:Session=Depends(get_db)):
    shot=db.query(Shot).join(Chapter,Chapter.id==Shot.chapter_id).filter(Shot.id==shot_id,Chapter.id==chapter_id,Chapter.novel_id==novel_id).first()
    if not shot:raise HTTPException(404,'分镜不存在')
    attempts=db.query(RsaImageAttempt).filter_by(shot_id=shot_id,novel_id=novel_id,chapter_id=chapter_id).order_by(RsaImageAttempt.created_at.desc()).all()
    artifacts=[]
    for row in db.query(RsaMediaArtifact).filter_by(shot_id=shot_id).order_by(RsaMediaArtifact.created_at):
        issue=None
        try:artifact_proof(db,row.id,rsa_id=row.rsa_id,rsa_hash=row.data['rsa_hash'])
        except (HTTPException,ValueError,RuntimeError,KeyError,TypeError) as exc:issue=str(exc.detail if isinstance(exc,HTTPException) else exc)
        artifacts.append({'id':row.id,'taskId':row.task_id,'rsaId':row.rsa_id,'stage':row.stage,'frameIndex':row.frame_index,'seal':row.seal,'verified':issue is None,'issue':issue,'data':row.data})
    return {'success':True,'data':{'shotId':shot.id,'primaryTaskId':shot.image_task_id,'artifacts':artifacts,
        'attempts':[{'id':a.id,'status':a.status,'stage':a.stage,'frameIndex':a.frame_index,'rsaId':a.rsa_id,'rsaHash':a.rsa_hash,'inputHash':a.input_hash,
            'inputs':a.inputs,'execution':a.execution,'artifactId':a.artifact_id,'error':a.error} for a in attempts]}}
