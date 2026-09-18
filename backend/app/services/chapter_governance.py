"""One runtime admission chain. Origin, rebuild requirement and media readiness are separate facts."""
from fastapi import HTTPException
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
import json
from app.models.chapter_governance import ChapterLifecycle,ChapterRebuildRun
from app.models.chapter_asset_parse import ChapterAssetParseRun
from app.models.appearance_timeline import AppearanceTimelineRun
from app.models.chapter_shot_split import ChapterShotSplitRun
from app.services.chapter_asset_parse_service import digest,run_response
from app.services.asset_resolution_service import binding_state
from app.services.appearance_timeline_service import timeline_response
from app.services.chapter_shot_split_service import checked_source,split_state


def register_new_chapter(db,chapter):
    db.flush()
    if not db.get(ChapterLifecycle,chapter.id):
        db.add(ChapterLifecycle(chapter_id=chapter.id,novel_id=chapter.novel_id,origin='NEW',origin_evidence={'method':'EXPLICIT_CHAPTER_CREATION'}))


def rebuild_blocker(db, chapter_id):
    state=db.get(ChapterLifecycle,chapter_id)
    run=db.get(ChapterRebuildRun,state.rebuild_id) if state and state.rebuild_id else None
    if not state or not state.rebuild_id:
        return None
    from app.services.rebuild_context import rebuild_owner
    task = db.get(Task, run.task_id) if run else None
    meta = json.loads(task.metadata_json or '{}') if task else {}
    valid = bool(run and task and digest(run.inputs) == run.input_hash and meta.get('input_hash') == run.input_hash
                 and run.result_hash == digest(run.result))
    if valid and run.status == 'RUNNING':
        valid = task.status == 'running' and rebuild_owner.get() == (run.id, run.claim_token) and task.claim_token == run.claim_token
    elif valid:
        valid = run.status in {'SUCCEEDED', 'BLOCKED', 'NEEDS_REVIEW'} and task.status == 'completed' and meta.get('result_hash') == run.result_hash
    if valid:
        receipt = run.result.get('chapters', {}).get(chapter_id, {})
        latest = db.query(ChapterShotSplitRun).filter_by(chapter_id=chapter_id).order_by(ChapterShotSplitRun.created_at.desc(), ChapterShotSplitRun.id.desc()).first()
        valid = bool(receipt.get('structuralReady') and latest and latest.status == 'SUCCEEDED'
                     and receipt.get('source', {}).get('latestRunId') == latest.id)
    if not valid:
        return {'code':'CHAPTER_REBUILD_REQUIRED','rebuildId':state.rebuild_id,'status':run.status if run else 'MISSING', 'error':run.error if run else 'REBUILD_LEDGER_MISSING'}
    return None


def rebuild_barrier(db, chapter_id):
    blocker = rebuild_blocker(db, chapter_id)
    if blocker:
        raise HTTPException(409, blocker)


def require_source(db,shot_id):
    shot=db.get(Shot,shot_id)
    if not shot:raise HTTPException(404,'分镜不存在；仅接受稳定Shot ID')
    rebuild_barrier(db,shot.chapter_id)
    try:return checked_source(db,shot)
    except HTTPException as exc:
        raise HTTPException(409,{'code':'NEEDS_REBUILD','shotId':shot.id,'cause':exc.detail}) from exc


def require_rsa(db,shot_id,memo=None):
    shot=db.get(Shot,shot_id)
    if shot and getattr(shot,'completion_disposition','NORMAL')=='DEGRADED_NARRATION_CARD':
        raise HTTPException(409,'NARRATION_CARD_RSA_FORBIDDEN')
    require_source(db,shot_id)
    from app.services.rsa_media_contract import pin_rsa
    return pin_rsa(db,shot_id,memo=memo)


def require_primary(db,shot_id,memo=None):
    rsa=require_rsa(db,shot_id,memo=memo)
    from app.services.rsa_media_contract import current_primary
    image=current_primary(db,db.get(Shot,shot_id),memo=memo)
    if image.rsa_id!=rsa.id or image.data['rsa_hash']!=rsa.result_hash:raise HTTPException(409,'PRIMARY_RSA_MANIFEST_CONFLICT')
    return rsa,image


def pipeline_state(db,novel_id,chapter_id):
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).first()
    if not chapter:raise HTTPException(404,'章回不存在')
    lifecycle=db.get(ChapterLifecycle,chapter_id)
    has_split=bool(db.query(ChapterShotSplitRun.id).filter_by(chapter_id=chapter_id).first())
    has_derived=bool(db.query(Shot.id).filter_by(chapter_id=chapter_id).first() or chapter.parsed_data or chapter.shot_images or chapter.shot_videos or chapter.final_video)
    origin=lifecycle.origin if lifecycle else ('LEGACY' if has_derived and not has_split else 'NEW')
    parses=db.query(ChapterAssetParseRun).filter_by(chapter_id=chapter_id,novel_id=novel_id).order_by(ChapterAssetParseRun.created_at.desc(),ChapterAssetParseRun.id.desc()).all()
    candidates={}
    for kind in ('characters','scenes','props'):
        run=next((r for r in parses if kind in r.kinds),None)
        candidates[kind]={'status':run_response(db,run,detail=False)['effectiveStatus'] if run else 'NOT_PARSED','runId':run.id if run else None}
    bindings=binding_state(db,novel_id,chapter_id)
    timeline=db.query(AppearanceTimelineRun).filter_by(chapter_id=chapter_id,novel_id=novel_id).order_by(AppearanceTimelineRun.created_at.desc(),AppearanceTimelineRun.id.desc()).first()
    timeline_state=timeline_response(db,timeline,detail=False)['effectiveStatus'] if timeline else 'NOT_BUILT'
    source=split_state(db,novel_id,chapter_id)
    rebuild=db.get(ChapterRebuildRun,lifecycle.rebuild_id) if lifecycle and lifecycle.rebuild_id else None
    barrier=bool(rebuild_blocker(db,chapter_id))
    structural=source['phase5Ready'] and not barrier
    needs=bool(barrier or (has_derived and not structural))
    condition='CURRENT' if structural else 'NEEDS_REBUILD' if needs else 'NOT_PARSED' if not parses else 'NOT_READY'
    missing=[]
    if any(v['status']!='SUCCEEDED' for v in candidates.values()):missing.append('CANDIDATES')
    if not bindings['phase2Ready']:missing.append('CHAPTER_BINDINGS')
    if timeline_state!='SUCCEEDED':missing.append('APPEARANCE_TIMELINE')
    if not source['phase5Ready']:missing.append('SHOT_SOURCE')
    return {'chapterId':chapter_id,'origin':origin,'originEvidence':lifecycle.origin_evidence if lifecycle else {'method':'READ_ONLY_STRUCTURAL_OBSERVATION'},
        'condition':condition,'needsRebuild':needs,'structuralReady':structural,'missingStages':missing,
        'candidates':candidates,'bindings':bindings,'timelineStatus':timeline_state,'shotSources':source,
        'rebuild':{'id':rebuild.id,'taskId':rebuild.task_id,'status':rebuild.status,'steps':rebuild.steps,'result':rebuild.result,'error':rebuild.error} if rebuild else None}
