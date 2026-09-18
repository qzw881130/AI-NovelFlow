"""R-CD1: one exact-source narration card cannot fabricate visual facts."""
import asyncio
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import struct
import wave

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine,inspect,text

from app.models.audio_drive import AudioEventTTSAsset,ShotAudioEvent
from app.models.novel import Character
from app.models.chapter_shot_split import ChapterShotSplitRun,ShotSource
from app.models.shot import Shot
from app.models.task import Task
from app.services.chapter_governance import require_rsa
from app.services.chapter_asset_parse_service import digest
from app.services.chapter_shot_split_service import ChapterShotSplitService,checked_run,split_state
from app.services.controlled_degradation_service import (DISPOSITION,admit,compose_plan,load_policy)
from app.services.file_storage import file_storage
from app.services.narration_card_service import capture as capture_card
from app.services.rendered_subtitles import fingerprint,load,publish
from app.services.runtime_gate import source_pin
from app.services.audio_drive_service import AudioDriveService
from app.utils.path_utils import local_path_to_url
from app.repositories.audio_drive import AudioDriveRepository
from app.schemas.chapter_shot_split import parse_controlled_degradation_output
from app.services.shot_revision_service import ShotRevisionService
from app.services.resolved_shot_assets_service import ResolvedShotAssetsService
from app.services.chapter_shot_split_schema import upgrade as upgrade_split_schema
from test_chapter_shot_split import (TEXT,SequenceLLM,add_repair_template,chapter,db_session,fixture)


OWNERSHIP='chapter-shot-ownership-v2'


def visual_shot(index,text,*,scene='桃园',duration=12):
    return {'id':index,'source_citations':[{'text':text}],'source_ownership':{'text':text},
        'description':f'Scene: {scene}\nCharacters:\n- 刘备: 画面中央站立\nAction: 静立',
        'video_description':'从静态首帧继续，刘备注视前方，全程不产生说话口型。',
        'characters':['刘备'],'scene':scene,'props':[],'duration':duration,'continuity_mode':'NORMAL',
        'dialogues':[],'audio_events':[],'source_treatments':[{'key':'visual','type':'VISUAL',
            'source_evidence':[{'text':text}],'visual_targets':['video_description']}]}


def dialogue_shot(index,text):
    return {'id':index,'source_citations':[{'text':text}],'source_ownership':{'text':text},
        'description':'Scene: 桃园\nCharacters:\n- 刘备: 画面中央开口\nAction: 说话',
        'video_description':'从静态首帧继续，刘备开口说话。','characters':['刘备'],'scene':'桃园','props':[],
        'duration':8,'continuity_mode':'NORMAL','dialogues':[{'order':1,'character_name':'刘备','text':'出发！','emotion_prompt':'坚定'}],
        'audio_events':[{'order':1,'type':'DIALOGUE','voice_owner':'刘备','visible_speaker':'刘备',
            'requires_visible_lipsync':True,'text':'出发！','emotion_prompt':'坚定','pause_after':'NONE','treatment_ref':'speech'}],
        'source_treatments':[{'key':'speech','type':'DIALOGUE','source_evidence':[{'text':text}]}]}


def rejected_plan():
    quote=TEXT.index('“');first,second=TEXT[:quote],TEXT[quote:]
    return {'source_contract_version':OWNERSHIP,'chapter':'第一回','characters':['刘备'],'scenes':['桃园'],
        'props':[],'unresolved_assets':[],'shots':[visual_shot(1,first),dialogue_shot(2,second)]}


def failed_scene_repair():
    quote=TEXT.index('“');target=TEXT[:quote];boundary=target.index('刘备披甲')
    left=visual_shot(1,target[:boundary],duration=6)
    right=visual_shot(2,target[boundary:],scene='未绑定场景',duration=6)
    return {'repair_type':'SHOT_CROSSES_APPEARANCE_BOUNDARY','repairs':[{
        'shot_index':1,'replacements':[left,right]}]}


def publish_child(db,chapter):
    add_repair_template(db);llm=SequenceLLM(db,[rejected_plan(),failed_scene_repair()])
    failed=asyncio.run(ChapterShotSplitService(db,llm).split(
        chapter.novel_id,chapter.id,source_contract_version=OWNERSHIP))
    assert not failed['success'] and len(llm.calls)==2
    repair=db.query(ChapterShotSplitRun).order_by(ChapterShotSplitRun.created_at.desc(),ChapterShotSplitRun.id.desc()).first()
    assert repair.status=='NEEDS_REVIEW' and repair.issues[0]['code']=='STILL_INVALID'
    result=admit(db,chapter.novel_id,chapter.id,repair.id)
    return repair,result


def test_cd1_publishes_exact_narration_card_child_and_preserves_failed_ancestors(db_session,chapter,fixture):
    repair,result=publish_child(db_session,chapter)
    child=db_session.get(ChapterShotSplitRun,result['splitRunId']);parent=db_session.get(
        ChapterShotSplitRun,repair.inputs['auto_repair']['parent_run_id'])
    assert parent.status==repair.status=='NEEDS_REVIEW'
    assert db_session.get(Task,parent.task_id).status==db_session.get(Task,repair.task_id).status=='failed'
    assert child.status=='SUCCEEDED' and checked_run(db_session,child)==child.inputs['basis']
    assert json.loads(db_session.get(Task,child.task_id).metadata_json)['execution_purpose']=='production'
    assert child.result['controlled_degradation']['outcome']=='SUCCEEDED_WITH_DEGRADATION'
    shots=db_session.query(Shot).filter_by(chapter_id=chapter.id).order_by(Shot.index).all()
    assert len(shots)==2 and [shot.completion_disposition for shot in shots]==[DISPOSITION,'NORMAL']
    card=shots[0];source=db_session.get(ShotSource,card.id);event=db_session.query(ShotAudioEvent).filter_by(shot_id=card.id).one()
    assert card.scene=='' and json.loads(card.characters)==json.loads(card.props)==[]
    assert source.bindings['characters']==source.bindings['scenes']==source.bindings['props']==[]
    assert source.source_start==0 and source.source_end==TEXT.index('“')
    assert event.event_type=='NARRATION' and event.voice_owner_name=='旁白' and event.text==TEXT[:TEXT.index('“')]
    assert event.visible_speaker_name is None and not event.requires_visible_lipsync
    assert source.treatment_contract['treatments'][0]['type']=='NARRATION'
    assert split_state(db_session,chapter.novel_id,chapter.id)['phase5Ready']
    with pytest.raises(HTTPException,match='NARRATION_CARD_RSA_FORBIDDEN'):require_rsa(db_session,card.id)
    with pytest.raises(HTTPException,match='NARRATION_CARD_RSA_FORBIDDEN'):
        ResolvedShotAssetsService(db_session).resolveShotAssets(card.id)
    with pytest.raises(HTTPException,match='NARRATION_CARD_IMMUTABLE'):
        ShotRevisionService(db_session).save_batch(chapter.novel_id,chapter.id,[{
            'id':card.id,'expected_revision':0,'description':card.description+' changed'}])


def test_cd1_replay_and_idempotency_fail_closed_on_tampering(db_session,chapter,fixture):
    repair,result=publish_child(db_session,chapter)
    again=admit(db_session,chapter.novel_id,chapter.id,repair.id)
    assert again['idempotent'] and again['splitRunId']==result['splitRunId']
    child=db_session.get(ChapterShotSplitRun,result['splitRunId']);before=deepcopy(child.result)
    child.result={**child.result,'controlled_degradation':{**child.result['controlled_degradation'],'targetShotIndex':99}}
    child.result_hash=__import__('app.services.chapter_asset_parse_service',fromlist=['digest']).digest(child.result)
    task=db_session.get(Task,child.task_id);meta=json.loads(task.metadata_json);meta['result_hash']=child.result_hash
    task.metadata_json=json.dumps(meta);db_session.commit()
    with pytest.raises(HTTPException,match='CONTROLLED_DEGRADATION_RESULT_CHANGED'):checked_run(db_session,child)
    assert before['controlled_degradation']['targetShotIndex']==1


def test_cd1_rejects_dialogue_or_existing_audio_target():
    text='刘备说：“出发！”';target=dialogue_shot(1,'“出发！”')
    target['source_citations']=[{'text':text}];target['source_ownership']={'text':text}
    plan={'source_contract_version':OWNERSHIP,'chapter':'章','characters':['刘备'],'scenes':['桃园'],
        'props':[],'unresolved_assets':[],'shots':[target]}
    with pytest.raises(HTTPException,match='CONTROLLED_DEGRADATION_TARGET_INELIGIBLE'):
        compose_plan(plan,1,text,load_policy())


def test_real_shot18_is_exact_source_narration_card_eligible():
    fixture=json.loads((__import__('pathlib').Path(__file__).parent/'fixtures'/'scene_aware_shot18.json').read_text())
    text=fixture['before']+fixture['after']
    original=visual_shot(1,text,duration=24);original['characters']=fixture['characters'];original['scene']=fixture['parentScene']
    original['source_treatments']=[{'key':'all','type':'VISUAL','source_evidence':[{'text':text}],
        'visual_targets':['video_description']}]
    plan={'source_contract_version':OWNERSHIP,'chapter':'章','characters':fixture['characters'],
        'scenes':[fixture['parentScene']],'props':[],'unresolved_assets':[],'shots':[original]}
    composed,card,source=compose_plan(plan,1,text,load_policy())
    assert [source['start'],source['end']]==[0,len(text)] and card['audio_events'][0]['text']==text
    assert card['scene']=='' and card['characters']==card['props']==card['dialogues']==[]
    assert composed['shots'][0]['completion_disposition']==DISPOSITION
    skipped=deepcopy(composed);skipped['shots'][0]['completion_disposition']='SKIPPED'
    with pytest.raises(Exception):parse_controlled_degradation_output(json.dumps(skipped,ensure_ascii=False))


def test_cd1_migration_is_additive_idempotent_and_defaults_existing_shots_normal():
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE chapters (id VARCHAR PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE shots (id VARCHAR PRIMARY KEY)'))
        connection.execute(text("INSERT INTO shots (id) VALUES ('old-shot')"))
    upgrade_split_schema(engine);upgrade_split_schema(engine)
    assert 'completion_disposition' in {row['name'] for row in inspect(engine).get_columns('shots')}
    assert 'final_video_task_id' in {row['name'] for row in inspect(engine).get_columns('chapters')}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT completion_disposition FROM shots WHERE id='old-shot'")).scalar_one()=='NORMAL'
    engine.dispose()


def ready_card_audio(db,card,path):
    event=db.query(ShotAudioEvent).filter_by(shot_id=card.id).one();rate=48000;frames=rate
    def write_audio(target):
        target.parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(target),'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(rate)
            stream.writeframes(b''.join(struct.pack('<h',int(1200*math.sin(2*math.pi*220*i/rate))) for i in range(frames)))
    write_audio(path);tts_path=path.with_name('tts.wav');write_audio(tts_path)
    narrator=db.query(Character).filter_by(novel_id=card.chapter.novel_id,is_narrator=True).one()
    reference=Path(file_storage.base_dir)/f'{card.id}_voice.wav';write_audio(reference)
    narrator.reference_audio_url=local_path_to_url(str(reference));db.flush()
    service=AudioDriveService(db);pin=source_pin(db,card.id);voice=service._voice_binding(event)
    producer=Task(type='audio_event_tts',status='completed',novel_id=card.chapter.novel_id,chapter_id=card.chapter_id,
        shot_id=card.id,character_id=narrator.id,name='tts',result_url=local_path_to_url(str(tts_path)),metadata_json=json.dumps({
            'execution_purpose':'production','audio_event_id':event.id,'source_pin':pin,'voice_binding':voice}))
    db.add(producer);db.flush();text_hash=service._hash_payload({'text':event.text})
    submitted_workflow={'text-node':{'inputs':{'text':event.text}}}
    remote_proof={'prompt_id':'prompt','output_node_id':'save','save_audio_node_id':'save',
        'output':{'filename':'tts.wav'},'audio_url':'remote','history':{'outputs':{'save':{'audio':[{'filename':'tts.wav'}]}}},
        'status':{'completed':True},'submitted_workflow':submitted_workflow,
        'submitted_workflow_hash':service._hash_payload(submitted_workflow),'submitted_text':event.text,
        'text_node_id':'text-node','text_input_field':'text'}
    asset=AudioEventTTSAsset(audio_event_id=event.id,status='READY',is_current=True,duration_seconds=1,
        sample_rate=rate,channels=1,file_size=tts_path.stat().st_size,content_hash=fingerprint(tts_path),
        text_hash=text_hash,audio_path=str(tts_path),audio_url=local_path_to_url(str(tts_path)),revision=1,
        config_json=json.dumps({'emotion_prompt':event.emotion_prompt,'source_pin':pin,'voice_binding':voice,
            'task_id':producer.id,'remote_proof':remote_proof}))
    db.add(asset);db.flush();event.tts_status='READY';event.text_hash=text_hash
    publish(tts_path,[{'start':'0','end':'1','text':event.text}],{'kind':'tts','audio_event_id':event.id,
        'tts_asset_id':asset.id,'task_id':producer.id,'text_hash':text_hash})
    timeline=AudioDriveRepository(db).create_timeline(
        card.id,1,'timeline-hash',{'source_pin':pin,'has_narration':True},[{
            'audio_event_id':event.id,'event_order':1,'start_time':0,'end_time':1,'event_type':'NARRATION',
            'voice_owner_character_id':None,'voice_owner_name':'旁白','visible_speaker_character_id':None,
            'visible_speaker_name':None,'requires_visible_lipsync':False,'tts_asset_id':asset.id}],audio_required_duration=1)
    speech={'sourceChannels':1,'sourceRmsDbfs':-20.0,'sourcePeakDbfs':-10.0,'gainDb':0.0,'gainReason':'test'}
    segment={'audio_event_id':event.id,'tts_asset_id':asset.id,'source_path':str(tts_path),'source_sha256':fingerprint(tts_path),
        'event_order':1,'source_start':0.0,'duration':1.0,'clip_start':0.0,'voice_owner_name':'旁白',
        'visible_speaker_name':None,'requires_visible_lipsync':False,'speech_level':speech}
    levels=[{'audioEventId':event.id,'ttsAssetId':asset.id,'sourceSha256':fingerprint(tts_path),**speech}]
    final_snapshot=publish(path,[{'start':'0','end':'1','text':event.text,'audio_event_id':event.id,'tts_asset_id':asset.id}],
        {'kind':'clip_audio','timeline_id':timeline.id,'timeline_revision':timeline.revision,
         'timeline_hash':timeline.generated_from_hash,'window_index':1,'clip_start':0,'clip_end':1,
         'segments':[segment],'render_metadata':{'sourceLevels':levels}})
    manifest_path=path.with_name('manifest.json');manifest={'source_pin':pin,'shot_id':card.id,'window_index':1,
        'audio_timeline_id':timeline.id,'audio_timeline_revision':timeline.revision,'audio_timeline_hash':timeline.generated_from_hash,
        'clip_start':0,'clip_end':1,'clip_duration':1,'final_audio_path':str(path),
        'final_segments':[segment],'render_metadata':{'sourceLevels':levels},
        'drive_audio_sha256':fingerprint(path),'drive_audio_bytes':path.stat().st_size,
        'final_audio_sha256':fingerprint(path),'final_audio_bytes':path.stat().st_size,
        'final_audio_snapshot_hash':digest(final_snapshot)}
    manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
    receipt={'manifest_hash':digest(manifest),'drive_audio_sha256':manifest['drive_audio_sha256'],
        'drive_audio_bytes':manifest['drive_audio_bytes'],'final_audio_sha256':manifest['final_audio_sha256'],
        'final_audio_bytes':manifest['final_audio_bytes'],'final_audio_snapshot_hash':manifest['final_audio_snapshot_hash']}
    window={'window_index':1,'start_time':0,'end_time':1,'audio_status':'READY','final_audio_path':str(path),
        'clip_audio_manifest_path':str(manifest_path),'audio_timeline_id':timeline.id,
        'audio_timeline_revision':timeline.revision,'audio_timeline_hash':timeline.generated_from_hash,'audio_receipt':receipt}
    card.video_director_plan=json.dumps({'execution_windows':[{'window_index':1,'start_time':0,'end_time':1,
        'audio_timeline_id':timeline.id,'audio_timeline_revision':timeline.revision,'audio_timeline_hash':timeline.generated_from_hash}],
        'window_plans':[window]})
    card.audio_status='READY';db.commit();return capture_card(db,card.id)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='ffmpeg required')
def test_narration_card_renderer_is_model_free_and_receipt_bound(db_session,chapter,fixture,tmp_path):
    _repair,result=publish_child(db_session,chapter)
    card=db_session.query(Shot).filter_by(chapter_id=chapter.id,completion_disposition=DISPOSITION).one()
    audio=tmp_path/'final.wav';inputs=ready_card_audio(db_session,card,audio);output=tmp_path/'card.mp4'
    rendered=asyncio.run(file_storage.render_narration_card(str(audio),str(output),1,
        inputs['render_profile'],{'version':'test','input_hash':digest(inputs),'shot_id':card.id},
        expected_audio_sha256=inputs['audio']['sha256'],expected_snapshot_hash=inputs['audio']['snapshot_hash']))
    assert rendered['success'] and output.is_file() and rendered['frames']==24
    assert rendered['sha256']==fingerprint(output) and rendered['bytes']==output.stat().st_size
    assert result['controlledDegradation']['degradedCount']==1


def test_narration_card_rejects_unproved_tts_producer(db_session,chapter,fixture,tmp_path):
    publish_child(db_session,chapter);card=db_session.query(Shot).filter_by(
        chapter_id=chapter.id,completion_disposition=DISPOSITION).one()
    ready_card_audio(db_session,card,tmp_path/'final.wav')
    event=db_session.query(ShotAudioEvent).filter_by(shot_id=card.id).one()
    asset=db_session.query(AudioEventTTSAsset).filter_by(audio_event_id=event.id,is_current=True).one()
    producer=db_session.get(Task,json.loads(asset.config_json)['task_id']);producer.status='failed';db_session.commit()
    with pytest.raises(HTTPException,match='NARRATION_CARD_TTS_PRODUCER_PROOF_REQUIRED'):
        capture_card(db_session,card.id)


def test_completion_manifest_is_server_ordered_and_has_no_skipped(db_session,chapter,fixture,tmp_path,monkeypatch):
    publish_child(db_session,chapter)
    shots=db_session.query(Shot).filter_by(chapter_id=chapter.id).order_by(Shot.index).all()
    card,normal=shots;audio=tmp_path/'final.wav';ready_card_audio(db_session,card,audio)
    import app.services.chapter_video_merge_service as completion
    normal_path=tmp_path/'normal.mp4';normal_path.write_bytes(b'normal')
    normal_snapshot={'kind':'normal'};card_snapshot={'kind':'card'}
    monkeypatch.setattr(completion,'video_receipt',lambda db,shot,**_kwargs:{'shot_id':shot.id,'path':str(normal_path),
        'sha256':fingerprint(normal_path),'subtitle_snapshot_hash':digest(normal_snapshot),'source_pin':source_pin(db,shot.id),'task_id':'normal-task','run_id':'run','rsa_binding':{},'result':{}})
    import app.services.narration_card_service as cards
    card_path=tmp_path/'card.mp4';card_path.write_bytes(b'card')
    monkeypatch.setattr(cards,'completed_artifact',lambda db,shot:{'shot_id':shot.id,'path':str(card_path),
        'sha256':fingerprint(card_path),'subtitle_snapshot_hash':digest(card_snapshot),'source_pin':source_pin(db,shot.id),'task_id':'card-task','source_range':[0,card.source_end]})
    manifest=completion.capture_completion(db_session,chapter.novel_id,chapter.id)
    assert [row['kind'] for row in manifest['entries']]==['DEGRADED_NARRATION_CARD','NORMAL_VIDEO']
    assert [row['ordinal'] for row in manifest['entries']]==[1,2]
    assert manifest['counts']=={'normal':1,'degraded':1,'total':2}
    assert manifest['entries'][0]['ownership']['start']==0
    assert manifest['entries'][-1]['ownership']['end']==len(chapter.content)
    assert 'SKIPPED' not in json.dumps(manifest)


def test_manifest_only_assembly_publishes_succeeded_with_degradation(db_session,chapter,fixture,tmp_path,monkeypatch):
    publish_child(db_session,chapter)
    shots=db_session.query(Shot).filter_by(chapter_id=chapter.id).order_by(Shot.index).all();card,normal=shots
    card_path=tmp_path/'card.mp4';normal_path=tmp_path/'normal.mp4';card_path.write_bytes(b'card');normal_path.write_bytes(b'normal')
    import app.services.chapter_video_merge_service as completion
    import app.services.narration_card_service as cards
    normal_snapshot={'kind':'normal'};card_snapshot={'kind':'card'}
    monkeypatch.setattr(completion,'video_receipt',lambda db,shot,**_kwargs:{'shot_id':shot.id,'path':str(normal_path),
        'sha256':fingerprint(normal_path),'subtitle_snapshot_hash':digest(normal_snapshot),'source_pin':source_pin(db,shot.id),'task_id':'normal-task','run_id':'run','rsa_binding':{},'result':{}})
    monkeypatch.setattr(cards,'completed_artifact',lambda db,shot:{'shot_id':shot.id,'path':str(card_path),
        'sha256':fingerprint(card_path),'subtitle_snapshot_hash':digest(card_snapshot),'source_pin':source_pin(db,shot.id),'task_id':'card-task','source_range':[0,card.source_end]})
    manifest=completion.capture_completion(db_session,chapter.novel_id,chapter.id);manifest_hash=digest(manifest)
    task=Task(type='chapter_video',status='pending',novel_id=chapter.novel_id,chapter_id=chapter.id,name='complete',
        metadata_json=json.dumps({'execution_purpose':'production','delivery_mode':'CHAPTER_COMPLETION','completion_manifest':manifest,
            'manifest_hash':manifest_hash}))
    db_session.add(task);db_session.commit()
    async def fake_merge(paths,destination,**_kwargs):
        Path(destination).parent.mkdir(parents=True,exist_ok=True);Path(destination).write_bytes(b'chapter')
        segments=[{'source_sha256':fingerprint(path)} for path in paths]
        snapshot=publish(destination,[],{'kind':'merge','sources':[card_snapshot,normal_snapshot],'segments':segments})
        return {'success':True,'output_path':destination,'media_segments':segments,
            'subtitle_snapshot':snapshot}
    monkeypatch.setattr(file_storage,'merge_videos',fake_merge)
    from app.core import database
    class SessionProxy:
        def __init__(self,session):self.session=session
        def __getattr__(self,name):return getattr(self.session,name)
        def close(self):pass
    monkeypatch.setattr(database,'SessionLocal',lambda:SessionProxy(db_session))
    asyncio.run(completion.run_completion(task.id));db_session.expire_all()
    saved=db_session.get(Task,task.id);saved_chapter=db_session.get(type(chapter),chapter.id);meta=json.loads(saved.metadata_json)
    assert saved.status=='completed' and meta['result']['outcome']=='SUCCEEDED_WITH_DEGRADATION'
    assert meta['result']['normalCount']==meta['result']['degradedCount']==1
    assert saved_chapter.final_video_task_id==task.id and saved_chapter.final_video==saved.result_url
    assert completion.current_completion(db_session,chapter.novel_id,chapter.id)['manifestHash']==manifest_hash
    saved_chapter.content+=' changed';db_session.commit()
    assert completion.current_completion(db_session,chapter.novel_id,chapter.id) is None
