"""Ordinary batch uses the existing automatic preparation and semantic scheduler."""
import json
from pathlib import Path
import pytest
from app.api import shots as api
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.repositories import NovelRepository, ChapterRepository, ShotRepository

@pytest.mark.asyncio
@pytest.mark.parametrize('first_fails', [False, True])
async def test_one_batch_prepares_two_shots_and_preserves_phase_b(db_session, monkeypatch, tmp_path, first_fails):
    db = db_session
    monkeypatch.setattr(api, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    n = Novel(id='n', title='test'); c = Chapter(id='c', novel_id=n.id, number=1, title='test')
    shots = [Shot(id=f's{i}', chapter_id=c.id, index=i, duration=10, image_url='/api/files/start.png', video_director_plan='{}') for i in [1,2]]
    db.add_all([n,c,*shots]); db.commit(); queued=[]; calls=[]
    monkeypatch.setattr(api, 'enqueue_shot_video_batch_task', queued.append)
    async def visual(novel_id, chapter_id, sid, *args):
        calls.append((sid,'08/10'))
        shot=db.get(Shot,sid);shot.video_director_plan=json.dumps({'canonical_visual_plan':True,'keyframes':[{'index':1},{'index':2}], 'transitions':[{'from_keyframe_index':1,'to_keyframe_index':2}]});db.commit()
        return {'success':True}
    async def clips(novel_id, chapter_id, sid, *args):
        calls.append((sid,'10A'));shot=db.get(Shot,sid);p=json.loads(shot.video_director_plan)
        p.update(clip_plan_revision=1,clip_plan_validation={'passed':True},clip_plan=[{'clip_id':sid+':clip:1','clip_index':1,'clip_plan_revision':1,'capability':'GENERATE','continuity_to_previous':'NONE','dialogue_assignment':[]}])
        shot.video_director_plan=json.dumps(p);db.commit();return {'success':True,'data':{'validation':{'passed':True}}}
    async def images(novel_id, chapter_id, sid, *args):calls.append((sid,'images'));return {'success':True,'data':{'items':[]}}
    monkeypatch.setattr(api,'plan_video_keyframes',visual);monkeypatch.setattr(api,'plan_shot_clips',clips);monkeypatch.setattr(api,'prepare_shot_required_images',images)
    monkeypatch.setattr(api,'get_canonical_execution_readiness',lambda *a, **kw:{'ready':True})
    def validate(db,shot,clip,*args):
        if not clip.get('generated_by_task_id'):raise ValueError('no clip')
        t=db.get(Task,clip['generated_by_task_id']);return t,json.loads(t.metadata_json),str(tmp_path/(t.id+'.mp4'))
    monkeypatch.setattr(api,'validate_semantic_clip_artifact',validate)
    async def execute(novel_id, chapter_id, sid, index, request, *args, **kwargs):
        calls.append((sid,'phase_b'))
        assert request.h3_prompt_pipeline=='phase_b' and not request.optimize_h3_prompt and not request.preflight_auto_repair
        if first_fails and sid=='s1':raise api.HTTPException(409,'contract failure')
        shot=db.get(Shot,sid);t=Task(id=sid+'-clip',type='shot_video',status='completed',name='clip',shot_id=sid,result_url='/api/files/'+sid+'.mp4',metadata_json=json.dumps({'execution_scope':'CLIP','clip_plan_revision':1,'clip_index':1,'approval_status':'APPROVED'}));db.add(t)
        p=json.loads(shot.video_director_plan);p['clip_plan'][0].update(generated_by_task_id=t.id,execution_status='APPROVED');shot.video_director_plan=json.dumps(p);db.commit();return {'success':True,'data':{'taskId':t.id}}
    async def merge(db,shot,*args):
        calls.append((shot.id,'merge'));shot.video_url='/api/files/'+shot.id+'-final.mp4';shot.video_status='completed';p=json.loads(shot.video_director_plan);p['assembly_status']='COMPLETED';shot.video_director_plan=json.dumps(p);db.commit();return {'success':True}
    monkeypatch.setattr(api,'execute_semantic_clip',execute);monkeypatch.setattr(api,'merge_video_director_clip_videos',merge)
    result=await api.generate_shot_videos_batch('n','c',api.BatchShotVideoRequest(shot_ids=['s1','s2'],auto_complete_details=True,force_rerun=False),db,NovelRepository(db),ChapterRepository(db),ShotRepository(db))
    bid=result['data']['batchTaskId'];assert queued==[bid]
    children=db.query(Task).filter(Task.parent_task_id==bid).order_by(Task.batch_order).all()
    assert [t.shot_id for t in children]==['s1','s2']
    assert json.loads(db.get(Task,bid).metadata_json)['h3_prompt_pipeline']=='phase_b'
    assert all(json.loads(t.metadata_json)['h3_prompt_pipeline']=='phase_b' for t in children)
    assert all(json.loads(t.metadata_json)['auto_complete_details'] and json.loads(t.metadata_json)['batch_mode']=='SEMANTIC_CLIP' for t in children)
    await api.run_shot_video_batch_task(bid)
    assert db.get(Task,bid).status==('failed' if first_fails else 'completed')
    assert db.get(Task,bid).progress==100
    assert calls==[('s1','08/10'),('s1','10A'),('s1','images'),('s1','phase_b'),*([('s1','merge')] if not first_fails else []),('s2','08/10'),('s2','10A'),('s2','images'),('s2','phase_b'),('s2','merge')]
    assert db.get(Shot,'s2').video_status=='completed'
    assert db.get(Shot,'s1').video_status==('failed' if first_fails else 'completed')
