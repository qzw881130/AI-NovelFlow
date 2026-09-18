"""Task operations plus read-only inspection of saved task evidence."""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories import TaskRepository
from app.services.task_service import TaskService
from app.services.task_execution import ExecutionConflict
from app.services.evidence_reader import workflow_snapshot
from app.api.deps import get_task_repo

router = APIRouter()


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    return TaskService(db)


@router.get('/', response_model=dict)
async def list_tasks(status: Optional[str] = None, type: Optional[str] = None,
                     chapter_id: Optional[str] = None, limit: int = 50,
                     db: Session = Depends(get_db), task_repo: TaskRepository = Depends(get_task_repo),
                     task_service: TaskService = Depends(get_task_service)):
    def selected_tasks():
        if chapter_id:
            rows = task_repo.get_by_chapter(chapter_id)
            return [t for t in rows if (not type or t.type == type) and (not status or t.status == status)][:limit]
        return task_repo.list_by_filters(status=status, task_type=type, limit=limit)

    tasks = selected_tasks()
    if any(t.status in ['pending', 'queued', 'running'] for t in tasks):
        if await task_service.reconcile_active_tasks(tasks, db=db):
            tasks = selected_tasks()
    novel_ids = {t.novel_id for t in tasks if t.novel_id}
    chapter_ids = {t.chapter_id for t in tasks if t.chapter_id}
    workflow_ids = {t.workflow_id for t in tasks if t.workflow_id}
    shot_ids = {t.shot_id for t in tasks if t.type == 'shot_video' and t.shot_id}
    novels = {n.id:n for n in db.query(Novel).filter(Novel.id.in_(novel_ids))} if novel_ids else {}
    chapters = {c.id:c for c in db.query(Chapter).filter(Chapter.id.in_(chapter_ids))} if chapter_ids else {}
    workflows = {w.id:w for w in db.query(Workflow).filter(Workflow.id.in_(workflow_ids))} if workflow_ids else {}
    shots = {s.id:s for s in db.query(Shot).filter(Shot.id.in_(shot_ids))} if shot_ids else {}
    return {'success':True, 'data':TaskService.format_task_list(tasks,novels,chapters,workflows,shots=shots)}


@router.get('/{task_id}', response_model=dict)
async def get_task(task_id: str, task_repo: TaskRepository = Depends(get_task_repo)):
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(404, '任务不存在')
    return {'success':True, 'data':TaskService.format_task_detail(task)}


@router.post('/{task_id}/cancel', response_model=dict)
async def cancel_task(task_id: str, task_service: TaskService = Depends(get_task_service)):
    result = await task_service.cancel_task(task_id)
    if result.get('status_code'):
        raise HTTPException(result['status_code'], result.get('message'))
    return {'success':True, 'message':result.get('message') or '任务已取消', 'details':result.get('details')}


@router.delete('/{task_id}')
async def delete_task(task_id: str, task_service: TaskService = Depends(get_task_service),
                      task_repo: TaskRepository = Depends(get_task_repo)):
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(404, '任务不存在')
    db=task_repo.db
    from app.models.novel import Chapter
    from app.models.shot import Shot
    if task.type=='chapter_video' and task_repo.db.query(Chapter.id).filter_by(final_video_task_id=task.id).first():
        raise HTTPException(409,'CHAPTER_COMPLETION_PRODUCER_TASK_REQUIRED')
    if task.type=='narration_card_video' and task_repo.db.query(Shot.id).filter_by(video_task_id=task.id).first():
        raise HTTPException(409,'NARRATION_CARD_PRODUCER_TASK_REQUIRED')
    from app.models.chapter_shot_split import ChapterShotSplitRun
    split_lineage_tasks={row[0] for row in db.query(ChapterShotSplitRun.task_id).all()}
    if task.id in split_lineage_tasks:raise HTTPException(409,'SHOT_SPLIT_LINEAGE_TASK_REQUIRED')
    controlled_runs=[row for row in task_repo.db.query(ChapterShotSplitRun).filter_by(status='SUCCEEDED').all()
        if row.inputs.get('controlled_degradation')]
    protected={row.task_id for row in controlled_runs}
    for row in controlled_runs:
        proof=(row.inputs.get('controlled_degradation') or {}).get('proof') or {}
        for run_id in (proof.get('parent_run_id'),proof.get('repair_run_id')):
            ancestor=task_repo.db.get(ChapterShotSplitRun,run_id) if run_id else None
            if ancestor:protected.add(ancestor.task_id)
    governance_heads=[row for row in task_repo.db.query(ChapterShotSplitRun).filter_by(status='SUCCEEDED').all()
        if ((row.inputs.get('auto_repair') or {}).get('governance') or {}).get('root_run_id')]
    for row in governance_heads:
        current=row;seen=set()
        while current and current.id not in seen:
            seen.add(current.id);protected.add(current.task_id)
            governance=((current.inputs.get('auto_repair') or {}).get('governance') or {})
            current=db.get(ChapterShotSplitRun,governance.get('predecessor_run_id')) if governance else None
    from app.models.resolved_shot_assets import ResolvedShotAssets
    completion_tasks=[db.get(Task,row.final_video_task_id) for row in db.query(Chapter).filter(
        Chapter.final_video_task_id.isnot(None)).all()]
    for completion in [row for row in completion_tasks if row]:
        try:manifest=json.loads(completion.metadata_json or '{}').get('completion_manifest') or {}
        except (TypeError,ValueError):manifest={}
        split=db.get(ChapterShotSplitRun,(manifest.get('source') or {}).get('split_run_id'))
        if split:protected.add(split.task_id)
        for entry in manifest.get('entries') or []:
            media=entry.get('media') or {};producer_id=media.get('task_id')
            if producer_id:protected.add(producer_id)
            binding=media.get('rsa_binding') or {};rsa_id=binding.get('rsa_id') or binding.get('rsaId') or binding.get('id')
            rsa=db.get(ResolvedShotAssets,rsa_id) if rsa_id else None
            if rsa:protected.add(rsa.task_id)
    from app.models.audio_drive import AudioEventTTSAsset,ShotAudioEvent
    card_ids=[shot.id for shot in task_repo.db.query(Shot).filter_by(completion_disposition='DEGRADED_NARRATION_CARD')]
    if card_ids:
        event_ids=[row.id for row in task_repo.db.query(ShotAudioEvent).filter(ShotAudioEvent.shot_id.in_(card_ids))]
        for asset in task_repo.db.query(AudioEventTTSAsset).filter(
                AudioEventTTSAsset.audio_event_id.in_(event_ids),AudioEventTTSAsset.is_current==True):
            try:producer_id=json.loads(asset.config_json or '{}').get('task_id')
            except (TypeError,ValueError):producer_id=None
            if producer_id:protected.add(producer_id)
    if task.id in protected:raise HTTPException(409,'CONTROLLED_DEGRADATION_LINEAGE_TASK_REQUIRED')
    try:
        if TaskService.cancellation_state(task) in {'pending','unknown'}:
            raise ExecutionConflict('REMOTE_CANCELLATION_UNCONFIRMED')
    except ExecutionConflict as exc:
        raise HTTPException(409,str(exc)) from exc
    expected = TaskService._task_snapshot(task)
    if task.status in ['pending','queued','running']:
        result = await task_service.cancel_task(task_id)
        if not result.get('success') or result.get('status_code'):
            raise HTTPException(result.get('status_code') or 409,result.get('message'))
        if any(item.get('remote_unconfirmed') for item in result.get('details',{}).get('tasks',[])):
            raise HTTPException(409,'本地任务已取消，但远程执行尚未确认终止；已保留任务证据')
        expected = result.get('terminal_snapshot')
    if not expected or expected.get('id') != task_id or expected.get('status') not in {'completed','failed','cancelled'}:
        raise HTTPException(409,'任务尚未稳定终止，不能删除')
    from types import SimpleNamespace
    try:
        if TaskService.cancellation_state(SimpleNamespace(**expected)) in {'pending','unknown'}:
            raise ExecutionConflict('REMOTE_CANCELLATION_UNCONFIRMED')
    except ExecutionConflict as exc:
        raise HTTPException(409,str(exc)) from exc
    from sqlalchemy.orm import aliased
    child = aliased(Task)
    with db.no_autoflush:
        count = db.query(Task).filter(*[getattr(Task,k)==v for k,v in expected.items()],
            ~db.query(child.id).filter(child.parent_task_id==task_id,child.status.in_(['pending','queued','running'])).exists()).delete(synchronize_session=False)
        if count != 1:
            db.rollback()
            raise HTTPException(409,'任务或子任务执行证据已更改，未删除；请刷新后重试')
        db.commit()
    return {'success':True,'message':'任务已删除'}


@router.post('/cancel-all/', response_model=dict)
async def cancel_all_tasks(task_service: TaskService = Depends(get_task_service)):
    return await task_service.cancel_all_tasks()


@router.post('/{task_id}/retry')
async def retry_task(task_id: str, task_service: TaskService = Depends(get_task_service)):
    result = task_service.retry_task(task_id)
    if result.get('status_code'):
        raise HTTPException(result['status_code'],result.get('message'))
    return result


@router.get('/{task_id}/workflow', response_model=dict)
async def get_task_workflow(task_id: str, task_repo: TaskRepository = Depends(get_task_repo)):
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(404,'任务不存在')
    return {'success':True,'data':{**TaskService.format_execution_purpose(task),**TaskService.format_video_execution(task),**workflow_snapshot(task)}}


@router.get('/{task_id}/clips/{window_index}/workflow', response_model=dict)
async def get_task_clip_workflow(task_id: str, window_index: int, db: Session = Depends(get_db),
                                 task_repo: TaskRepository = Depends(get_task_repo)):
    task = task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(404,'任务不存在')
    if task.type != 'shot_video' or not task.shot_id:
        raise HTTPException(400,'该任务不是分镜视频任务')
    return {'success':True,'data':{**TaskService.format_execution_purpose(task),**TaskService.format_video_execution(task),**workflow_snapshot(task,window_index)}}
