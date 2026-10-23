import json
from unittest.mock import AsyncMock
import pytest
from app.api import shots as api
from app.models.task import Task
from test_semantic_batch_scheduler import _fixture, _install_execution_fake

@pytest.mark.asyncio
async def test_auto_reuses_prefix_passes_optimizer_and_links_tasks(db_session, monkeypatch, tmp_path):
 _,_,shot,parent,child=_fixture(db_session)
 m=json.loads(child.metadata_json);m.update(automatic_shot=True,optimize_h3_prompt=True)
 child.metadata_json=json.dumps(m);db_session.commit()
 monkeypatch.setattr(api,'_prepare_automatic_shot',AsyncMock(return_value=True))
 calls=[];add=_install_execution_fake(db_session,monkeypatch,tmp_path,calls)
 add(shot,1,'GENERATE',3)
 original=api.execute_semantic_clip
 async def execute(*args,**kwargs):
  assert args[4].optimize_h3_prompt and args[4].preflight_auto_repair
  return await original(*args,**kwargs)
 monkeypatch.setattr(api,'execute_semantic_clip',execute)
 assert await api._run_semantic_shot_for_batch(db_session,parent,child,shot)=='completed'
 assert calls==[2,3]
 assert db_session.get(Task,'generated-3').parent_task_id==parent.id
 assert await api._run_semantic_shot_for_batch(db_session,parent,child,shot)=='completed'
 assert calls==[2,3]

@pytest.mark.asyncio
async def test_pause_before_next_clip_then_resume_reuses_completed(db_session, monkeypatch, tmp_path):
 _,_,shot,parent,child=_fixture(db_session)
 calls=[];_install_execution_fake(db_session,monkeypatch,tmp_path,calls)
 original=api.execute_semantic_clip
 async def execute(*args,**kwargs):
  result=await original(*args,**kwargs)
  parent.metadata_json=json.dumps({'pause_requested':True});db_session.commit()
  return result
 monkeypatch.setattr(api,'execute_semantic_clip',execute)
 assert await api._run_semantic_shot_for_batch(db_session,parent,child,shot)=='paused'
 assert calls==[1]
 parent.metadata_json='{}';db_session.commit();monkeypatch.setattr(api,'execute_semantic_clip',original)
 assert await api._run_semantic_shot_for_batch(db_session,parent,child,shot)=='completed'
 assert calls==[1,2,3]

@pytest.mark.asyncio
async def test_failed_comfy_receipt_never_resubmits(db_session, monkeypatch, tmp_path):
 _,_,shot,parent,child=_fixture(db_session,capabilities=('GENERATE',))
 m=json.loads(child.metadata_json);m['automatic_shot']=True;child.metadata_json=json.dumps(m)
 task=Task(type='shot_video',name='failed',shot_id=shot.id,status='failed',comfyui_prompt_id='existing-receipt',
  metadata_json=json.dumps({'execution_scope':'CLIP','clip_index':1,'clip_plan_revision':3}))
 db_session.add(task);db_session.commit()
 monkeypatch.setattr(api,'_prepare_automatic_shot',AsyncMock(return_value=True))
 calls=[];_install_execution_fake(db_session,monkeypatch,tmp_path,calls)
 assert await api._run_semantic_shot_for_batch(db_session,parent,child,shot)=='failed'
 assert calls==[] and task.comfyui_prompt_id=='existing-receipt'

def test_pipeline_identity_survives_planning_revision(db_session):
 _,_,shot,parent,child=_fixture(db_session)
 child.metadata_json=json.dumps({'automatic_shot':True,'clip_plan_revision':0});db_session.commit()
 assert api._find_automatic_shot_task(db_session,shot).id==parent.id
 parent.status='completed';child.metadata_json=json.dumps({'automatic_shot':True,'clip_plan_revision':3});db_session.commit()
 assert api._find_automatic_shot_task(db_session,shot).id==parent.id
 plan=json.loads(shot.video_director_plan);plan['clip_plan_revision']=4;shot.video_director_plan=json.dumps(plan);db_session.commit()
 assert api._find_automatic_shot_task(db_session,shot) is None

@pytest.mark.asyncio
async def test_interrupted_receipt_waits_for_existing_saver_without_regeneration(db_session, monkeypatch):
 from app.services.clip_result_recovery import INTERRUPTED_CLIP_ERROR
 _,_,shot,parent,child=_fixture(db_session)
 task=Task(id='interrupted',type='shot_video',name='existing receipt',shot_id=shot.id,
  status='failed',comfyui_prompt_id='original-receipt',error_message=INTERRUPTED_CLIP_ERROR)
 db_session.add(task);db_session.commit()
 async def reconcile(self,tasks,db=None):
  assert tasks[0].comfyui_prompt_id=='original-receipt'
  tasks[0].status='completed';db.commit()
 monkeypatch.setattr(api.TaskService,'reconcile_active_tasks',reconcile)
 monkeypatch.setattr(api.asyncio,'sleep',AsyncMock())
 result=await api._wait_for_semantic_clip_task(db_session,task.id,timeout_iterations=2,batch_task_id=parent.id)
 assert result.status=='completed' and result.comfyui_prompt_id=='original-receipt'
 assert len(json.loads(parent.metadata_json)['automatic_recoveries'])==1
 task.status='failed';task.error_message='genuine GPU error';db_session.commit()
 assert (await api._wait_for_semantic_clip_task(db_session,task.id,timeout_iterations=2,batch_task_id=parent.id)).status=='failed'

def test_auto_status_exposes_actual_failure_instead_of_only_batch_count(db_session):
    novel,chapter,shot,parent,child=_fixture(db_session)
    child.metadata_json=json.dumps({'automatic_shot':True,'clip_plan_revision':3,'failed_clip_index':2})
    child.status='failed';child.error_message='Canonical speaker mismatch in Clip 2'
    parent.status='failed';parent.error_message='完成：成功 0，失败 1，取消 0';db_session.commit()
    result=api.get_shot_auto_generation(novel.id,chapter.id,shot.id,db_session)['data']
    assert result['error']==child.error_message
