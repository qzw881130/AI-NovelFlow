"""Task-local ownership for the existing stage writers during explicit rebuilds."""
from contextvars import ContextVar
import json
from fastapi import HTTPException
from app.models.chapter_governance import ChapterLifecycle, ChapterRebuildRun
from app.models.novel import Chapter
from app.models.task import Task


rebuild_owner = ContextVar('chapter_rebuild_owner', default=None)


def stage_parent(db, chapter_id):
    """Called at admission and inside each stage's publication transaction."""
    from app.services.chapter_asset_parse_service import digest, source_hash
    head = db.query(ChapterLifecycle).filter_by(chapter_id=chapter_id).populate_existing().first()
    run = db.get(ChapterRebuildRun, head.rebuild_id) if head and head.rebuild_id else None
    owner = rebuild_owner.get()
    if not owner:
        if run and run.status in {'PENDING', 'RUNNING'}:
            raise HTTPException(409, 'CHAPTER_REBUILD_OWNS_WRITERS')
        return None
    if not run or owner != (run.id, run.claim_token):
        raise HTTPException(409, 'REBUILD_OWNER_CHANGED')
    task = db.query(Task).filter_by(id=run.task_id).populate_existing().first()
    if (not task or task.status != 'running' or run.status != 'RUNNING' or task.claim_token != owner[1]
            or digest(run.inputs) != run.input_hash
            or json.loads(task.metadata_json or '{}').get('input_hash') != run.input_hash):
        raise HTTPException(409, 'REBUILD_PARENT_FENCED')
    for item in run.inputs['chapters']:
        chapter = db.query(Chapter).filter_by(id=item['chapter_id']).populate_existing().first()
        lifecycle = db.get(ChapterLifecycle, item['chapter_id'])
        if (not chapter or chapter.novel_id != run.novel_id or source_hash(chapter) != item['source_hash']
                or not lifecycle or lifecycle.rebuild_id != run.id):
            raise HTTPException(409, 'REBUILD_SOURCE_OR_OWNER_CHANGED')
    from app.services.chapter_rebuild_service import check_protection
    check_protection(db, run.novel_id, run.inputs['protected'])
    return task.id
