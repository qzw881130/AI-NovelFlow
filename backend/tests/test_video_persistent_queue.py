"""Restart admission for unstarted video tasks; never replay attempted submissions."""
import asyncio
import json
from datetime import datetime
import pytest
from sqlalchemy.orm import Session
from app.models.task import Task
from app.models.shot import Shot
from app.services import shot_video_execution as execution
from test_rsa_media import db_session, chapter, fixture, base_setup, setup, enqueue, run
from test_chapter_governance import admit_video


def pending(db,chapter,setup):
    shot=setup[3][0]
    attempt,_,_=run(db,enqueue(db,shot));assert attempt.status=='SUCCEEDED'
    return admit_video(db,chapter,shot)


def test_pending_child_of_failed_parent_is_settled_without_waiting_30_minutes(db_session,chapter,setup):
    task=pending(db_session,chapter,setup)
    parent=Task(name='interrupted batch',type='shot_video_batch',status='failed',novel_id=chapter.novel_id,chapter_id=chapter.id)
    db_session.add(parent);db_session.flush();task.parent_task_id=parent.id;db_session.commit()
    original=task.metadata_json
    assert asyncio.run(execution.reconcile_video_execution(db_session,task)) is True
    db_session.expire_all()
    assert task.status=='failed' and 'PARENT' in task.error_message
    assert task.metadata_json==original and task.comfyui_prompt_id is None
    assert db_session.get(Shot,task.shot_id).video_status=='failed'


def test_persistent_worker_claims_the_same_unstarted_task_once(db_session,chapter,setup,monkeypatch):
    from app.core import database
    task=pending(db_session,chapter,setup);tid=task.id;calls=[]
    monkeypatch.setattr(database,'SessionLocal',lambda:Session(db_session.bind,autoflush=False))
    async def claimed(db,identity):
        current,shot,handle=execution.claim_video_execution(db,identity)
        assert identity==tid and current.attempt==1
        calls.append(identity)
    monkeypatch.setattr(execution,'run_video_execution',claimed)
    assert asyncio.run(execution.run_next_persistent_video_task())
    assert not asyncio.run(execution.run_next_persistent_video_task())
    assert calls==[tid]


@pytest.mark.parametrize('marker',['started_at','comfyui_prompt_id','workflow_json','attempt','working_state'])
def test_pending_with_attempt_evidence_is_not_treated_as_unstarted(db_session,chapter,setup,marker):
    task=pending(db_session,chapter,setup)
    if marker=='started_at':task.started_at=datetime.utcnow()
    elif marker=='comfyui_prompt_id':task.comfyui_prompt_id='unconfirmed-or-original-job'
    elif marker=='workflow_json':task.workflow_json='{}'
    elif marker=='attempt':task.attempt=1
    else:
        data=json.loads(task.metadata_json);data['execution']['revision']=1;task.metadata_json=json.dumps(data)
    db_session.commit()
    with pytest.raises(execution.ExecutionConflict,match='NOT_UNSTARTED'):
        execution.claim_video_execution(db_session,task.id)


def test_queue_revalidates_source_before_remote_work(db_session,chapter,setup,monkeypatch):
    from app.core import database
    from app.services import comfyui
    task=pending(db_session,chapter,setup);tid=task.id
    chapter.content+=' user edit';db_session.commit()
    monkeypatch.setattr(database,'SessionLocal',lambda:Session(db_session.bind,autoflush=False))
    monkeypatch.setattr(comfyui,'ComfyUIService',lambda *a,**k:pytest.fail('No remote work after source drift'))
    assert asyncio.run(execution.run_next_persistent_video_task())
    db_session.expire_all();assert db_session.get(Task,tid).status=='failed'
