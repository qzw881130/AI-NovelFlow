from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.shot import Shot
from app.models.novel import Chapter,Character,Scene,Prop
from app.models.appearance_timeline import CharacterAppearance
from app.models.asset_resolution import ChapterCharacterAppearanceEvent
from app.models.resolved_shot_assets import ResolvedShotAssets
from app.schemas.chapter_asset_parse import StrictPayload, NonBlank
from app.services.resolved_shot_assets_service import ResolvedShotAssetsService, current_rsa, rsa_response, require_frozen_rsa, check_logical_rsa
from app.services.resolved_asset_images import observe_image, MODELS

router = APIRouter()


class ResolveChapterRequest(StrictPayload):
    shot_ids: list[NonBlank] | None = Field(None,min_length=1,max_length=500)


class FrozenAssetCheck(StrictPayload):
    rsa_id: NonBlank
    rsa_hash: NonBlank


def scope(db, novel_id, chapter_id, shot_id=None):
    if not db.query(Chapter.id).filter_by(id=chapter_id,novel_id=novel_id).first():
        raise HTTPException(404,"章回不存在")
    if shot_id and not db.query(Shot.id).filter_by(id=shot_id,chapter_id=chapter_id).first():
        raise HTTPException(404,"分镜不存在")


def readiness(db, novel_id, chapter_id):
    scope(db,novel_id,chapter_id)
    chapter_shots=db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index,Shot.id).all()
    degraded=[shot.id for shot in chapter_shots if getattr(shot,'completion_disposition','NORMAL')=='DEGRADED_NARRATION_CARD']
    rows = [{"index":shot.index,**current_rsa(db,shot.id)} for shot in chapter_shots if shot.id not in degraded]
    for item in rows:
        row=db.get(ResolvedShotAssets,item['id']) if item['id'] else None
        logic=row.inputs.get('logical') if row else None
        characters=[];actions=[];logical_current=False
        if logic:
            try:
                check_logical_rsa(db,row)
                logical_current=True
            except (HTTPException,ValueError,KeyError,TypeError,OSError):
                pass
        def generation_action(kind, asset_id):
            observation,_=observe_image(db,novel_id,kind,asset_id)
            origin=observation['origin']
            if observation['ready'] or origin.get('owner_task_active') or str(origin.get('status','')).lower() in {'pending','running','generating'}:
                return
            resource={'CHARACTER_BASE':'characters','SCENE':'scenes','PROP':'props'}[kind]
            asset=db.get(MODELS[kind],asset_id)
            suffix='generate-portrait' if kind=='CHARACTER_BASE' else 'generate-image'
            actions.append({'kind':resource,'id':asset_id,'name':asset.name,'url':f'/{resource}/{asset_id}/{suffix}'})
        if logic:
            for actor in logic['characters']:
                app=db.get(CharacterAppearance,actor['appearance_id']) if actor['appearance_id'] else None
                base=db.get(Character,actor['character_id'])
                source_chapter=db.get(Chapter,app.source_chapter_id) if app else None
                events=db.query(ChapterCharacterAppearanceEvent).filter(ChapterCharacterAppearanceEvent.id.in_(actor['selection']['sourceEventIds'])).all() if app else []
                characters.append({'characterId':actor['character_id'],'name':actor['definition']['name'],'appearanceId':actor['appearance_id'],
                    'appearanceName':actor.get('appearance_definition',{}).get('description') if actor['appearance_id'] else '基础造型',
                    'appearanceStatus':(app.status if app else 'MISSING_RECORD') if actor['appearance_id'] else ('READY' if item['assets']['characters'][len(characters)]['image_status']=='READY' else 'NEEDS_GENERATION'),
                    'sourceChapter':{'id':source_chapter.id,'number':source_chapter.number,'title':source_chapter.title} if source_chapter else None,
                    'events':[{'id':e.id,'key':e.event_key,'evidence':e.source_evidence} for e in events]})
                if logical_current and app and app.status in {'NEEDS_GENERATION','FAILED'} and base:
                    generation_action('CHARACTER_BASE',base.id)
            for slot,image in row.inputs['images'].items():
                origin=image['origin'];kind=origin['kind']
                if logical_current and kind!='CHARACTER_APPEARANCE':generation_action(kind,origin['asset_id'])
        item['view']={'characters':characters,'generationActions':actions,'logicalCurrent':logical_current}
    ready = [r for r in rows if r["ready"]]
    failed = [r for r in rows if r["effectiveStatus"]=="FAILED"]
    pending = [r for r in rows if r["effectiveStatus"]=="RUNNING"]
    blocked = [r for r in rows if not r["ready"] and r not in failed and r not in pending]
    return {"chapterReady":bool(chapter_shots) and len(ready)==len(rows),"shots":rows,"readyShotIds":[r["shotId"] for r in ready],
        "degradedShotIds":degraded,
        "blockedShotIds":[r["shotId"] for r in blocked],"failedShotIds":[r["shotId"] for r in failed],"pendingShotIds":[r["shotId"] for r in pending],
        "readyManifest":[{"shot_id":r["shotId"],"rsa_id":r["id"],"rsa_hash":r["resultHash"]} for r in ready],
        "counts":{"total":len(chapter_shots),"normal":len(rows),"degraded":len(degraded),"ready":len(ready),"blocked":len(blocked),"failed":len(failed),"pending":len(pending)}}


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/resolve-assets")
def resolve(novel_id:str,chapter_id:str,shot_id:str,db:Session=Depends(get_db)):
    scope(db,novel_id,chapter_id,shot_id)
    return ResolvedShotAssetsService(db).resolveShotAssets(shot_id)


@router.get("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/resolved-assets")
def current(novel_id:str,chapter_id:str,shot_id:str,db:Session=Depends(get_db)):
    scope(db,novel_id,chapter_id,shot_id)
    return {"success":True,"data":current_rsa(db,shot_id)}


@router.get("/{novel_id}/chapters/{chapter_id}/resolved-assets/{rsa_id}")
def detail(novel_id:str,chapter_id:str,rsa_id:str,db:Session=Depends(get_db)):
    row = db.query(ResolvedShotAssets).filter_by(id=rsa_id,novel_id=novel_id,chapter_id=chapter_id).first()
    if not row: raise HTTPException(404,"RSA不存在")
    return {"success":True,"data":{**rsa_response(db,row),"inputs":row.inputs}}


@router.get("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/resolved-assets/history")
def history(novel_id:str,chapter_id:str,shot_id:str,db:Session=Depends(get_db)):
    scope(db,novel_id,chapter_id,shot_id)
    rows = db.query(ResolvedShotAssets).filter_by(shot_id=shot_id,novel_id=novel_id,chapter_id=chapter_id).order_by(ResolvedShotAssets.revision.desc()).all()
    return {"success":True,"data":[{"id":r.id,"revision":r.revision,"status":r.status,"resultHash":r.result_hash,"createdAt":r.created_at} for r in rows]}


@router.post("/{novel_id}/chapters/{chapter_id}/shots/{shot_id}/resolved-assets/validate")
def validate(novel_id:str,chapter_id:str,shot_id:str,request:FrozenAssetCheck,db:Session=Depends(get_db)):
    scope(db,novel_id,chapter_id,shot_id)
    row = require_frozen_rsa(db,shot_id,request.rsa_id,request.rsa_hash)
    return {"success":True,"data":{"rsaId":row.id,"rsaHash":row.result_hash,"ready":True}}


@router.post("/{novel_id}/chapters/{chapter_id}/resolve-assets")
def resolve_chapter(novel_id:str,chapter_id:str,request:ResolveChapterRequest,db:Session=Depends(get_db)):
    scope(db,novel_id,chapter_id)
    ids = list(dict.fromkeys(request.shot_ids)) if request.shot_ids is not None else [s.id for s in db.query(Shot).filter_by(chapter_id=chapter_id).order_by(Shot.index,Shot.id)
        if getattr(s,'completion_disposition','NORMAL')!='DEGRADED_NARRATION_CARD']
    for shot_id in ids: scope(db,novel_id,chapter_id,shot_id)
    attempts = []
    for shot_id in ids:
        try:
            result = ResolvedShotAssetsService(db).resolveShotAssets(shot_id)
            attempts.append({"shotId":shot_id,"success":result["success"],"rsaId":result["data"]["id"],"message":result.get("message")})
        except HTTPException as exc:
            db.rollback()
            attempts.append({"shotId":shot_id,"success":False,"message":exc.detail})
    return {"success":all(r["success"] for r in attempts),"data":{**readiness(db,novel_id,chapter_id),"attempts":attempts}}


@router.get("/{novel_id}/chapters/{chapter_id}/asset-readiness")
def get_readiness(novel_id:str,chapter_id:str,db:Session=Depends(get_db)):
    return {"success":True,"data":readiness(db,novel_id,chapter_id)}
