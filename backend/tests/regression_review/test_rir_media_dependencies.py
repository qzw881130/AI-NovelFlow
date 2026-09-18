"""RIR-010/011: private DB copies of actual source/RSA/TTS/multi-Clip receipts.

Run explicitly with REVIEW_SOURCE_DB set to a read-only source snapshot path.
No worker, LLM, ComfyUI or media writer is started; all publications are private.
"""
from copy import deepcopy
import hashlib,json,os,sqlite3
from pathlib import Path
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.models.shot_revision import ShotRevisionHead
from app.services.chapter_governance import require_source,require_rsa,require_primary
from app.services.runtime_gate import source_pin,audio_source_pin
from app.services.shot_revision_service import ShotRevisionService
from app.services.audio_drive_service import AudioDriveService
from app.services.chapter_video_merge_service import video_receipt
from app.repositories.shot_repository import ShotRepository
from app.repositories.audio_drive import AudioDriveRepository
from app.services.rendered_subtitles import load

BOOK='31295501-a729-4fe7-aa76-a98c06121b98';CHAPTER='49a0e2aa-b633-44de-adb0-f2573f790e97'


@pytest.fixture
def media_db(tmp_path):
    source_path=os.environ.get('REVIEW_SOURCE_DB')
    if not source_path:pytest.skip('Requires explicit read-only REVIEW_SOURCE_DB; never substitutes a silent fixture')
    destination=tmp_path/'review.db'
    with sqlite3.connect(f'file:{Path(source_path).resolve()}?mode=ro',uri=True) as source:
        source.execute('PRAGMA query_only=ON')
        with sqlite3.connect(destination) as target:source.backup(target)
        assert source.total_changes==0
    engine=create_engine('sqlite:///'+str(destination))
    with Session(engine,autoflush=False) as db:
        assert db.get(Chapter,CHAPTER).final_video
        yield db
    engine.dispose()


def shot_at(db,index):return db.query(Shot).filter_by(chapter_id=CHAPTER,index=index).one()
def row_data(row):return {c.name:getattr(row,c.name) for c in row.__table__.columns}
def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def save(db,shot,**fields):
    return ShotRevisionService(db).save_batch(BOOK,CHAPTER,[{'id':shot.id,'expected_revision':require_source(db,shot.id).revision,**fields}])


def audio_facts(db,shot):
    service=AudioDriveService(db);events=service.repo.list_events(shot.id);pin=audio_source_pin(db,shot.id)
    assets=[service.repo.current_tts_asset(e.id) for e in events]
    assert events and all(a and a.status=='READY' and service._tts_asset_eligible(e,a,pin) for e,a in zip(events,assets))
    timeline=service.repo.latest_timeline(shot.id);assert timeline.status=='READY';service._timeline_gate(shot.id,timeline,pin)
    plan=json.loads(shot.video_director_plan);windows=plan.get('window_plans') or plan.get('clips')
    audio=[]
    for window in windows:
        manifest_path=window.get('clip_audio_manifest_path');assert manifest_path
        manifest=json.loads(Path(manifest_path).read_text())
        assert load(manifest['final_audio_path'])
        audio.append({'fields':{k:v for k,v in window.items() if k.startswith(('audio_','drive_','final_','clip_audio','speaker_timeline'))},
                      'manifest':file_hash(manifest_path),'drive':file_hash(manifest['drive_audio_path']),'final':file_hash(manifest['final_audio_path'])})
    return {'tts':[{'row':row_data(a),'bytes':file_hash(a.audio_path)} for a in assets],
            'timeline':row_data(timeline),'timeline_events':[row_data(e) for e in service.repo.list_timeline_events(timeline.id)],'clips':audio}


@pytest.mark.parametrize('index',[1,2,4])
def test_rir010_metadata_key_rename_preserves_actual_rendered_dependencies(media_db,index):
    db=media_db;shot=shot_at(db,index);source=require_source(db,shot.id)
    audio=audio_facts(db,shot);video=video_receipt(db,shot);rsa=require_rsa(db,shot.id).id
    plan=shot.video_director_plan;final=shot.chapter.final_video;pin=source_pin(db,shot.id)
    dto=ShotRepository(db).to_response(shot);treatments=deepcopy(dto['sourceTreatments']);events=deepcopy(dto['audioEvents'])
    chosen=next(t for t in treatments if t['type']==('NARRATION' if index==1 else 'DIALOGUE'))
    old=chosen['key'];chosen['key']='metadata-rename-'+old
    for event in events:
        if event['treatmentRef']==old:event['treatmentRef']=chosen['key']
    save(db,shot,source_treatments=treatments,audio_events=events)
    current=require_source(db,shot.id)
    assert current.revision==source.revision+1 and current.seal!=source.seal
    assert audio_facts(db,shot)==audio
    assert require_rsa(db,shot.id).id==rsa and source_pin(db,shot.id)==pin
    assert shot.video_director_plan==plan and shot.chapter.final_video==final
    assert video_receipt(db,shot)==video


@pytest.mark.parametrize('field',['description','video_description'])
def test_rir011_two_distinct_edits_keep_real_tts_timeline_and_multiclip_audio(media_db,field):
    db=media_db;shot=shot_at(db,4);before=audio_facts(db,shot);assert len(before['clips'])==2
    rsa=require_rsa(db,shot.id).id;primary=require_primary(db,shot.id)[1].id;original=getattr(shot,field)
    start=require_source(db,shot.id).revision
    for index in (1,2):
        save(db,shot,**{field:original+f'\n第{index}次独立编辑：微风吹动草叶。'})
        assert require_source(db,shot.id).revision==start+index
        assert audio_facts(db,shot)==before
        assert shot.video_url is None and shot.video_status=='pending'
        if field=='video_description':
            assert require_rsa(db,shot.id).id==rsa and require_primary(db,shot.id)[1].id==primary
        else:
            from app.services.resolved_shot_assets_service import ResolvedShotAssetsService
            resolved=ResolvedShotAssetsService(db).resolveShotAssets(shot.id)
            assert resolved['success'] and resolved['data']['ready'],resolved
            assert resolved['data']['id']!=rsa
    count=db.query(Task).count();saved=save(db,shot,**{field:getattr(shot,field)})
    assert saved['data']['shots'][0]['sourceRevision']==start+2 and db.query(Task).count()==count
    assert audio_facts(db,shot)==before


def test_rir011_dialogue_pause_speaker_sequence_keeps_unaffected_real_narration_tts(media_db):
    db=media_db;shot=shot_at(db,2);repo=AudioDriveRepository(db);before=repo.list_events(shot.id)
    narrator=next(e for e in before if e.event_type=='NARRATION');asset=repo.current_tts_asset(narrator.id);original=row_data(asset);sha=file_hash(asset.audio_path)
    for patch in [{'text':'狼来了！快来帮忙！'},{'pauseAfter':'LONG'},
                  {'voiceOwnerName':'村民','voiceOwnerCharacterId':None,'visibleSpeakerName':'村民','visibleSpeakerCharacterId':None}]:
        dto=ShotRepository(db).to_response(shot);events=deepcopy(dto['audioEvents']);events[0].update(patch)
        save(db,shot,audio_events=events)
        require_source(db,shot.id)
        kept=repo.current_tts_asset(narrator.id)
        assert row_data(kept)==original and file_hash(kept.audio_path)==sha
        service=AudioDriveService(db)
        assert service.create_tts_task(narrator.id)['data']['skipped']
    assert repo.latest_timeline(shot.id).status=='STALE'
    assert shot.video_url is None


def test_rir011_narration_edit_then_pause_then_character_inner_voice(media_db):
    db=media_db;shot=shot_at(db,1);dto=ShotRepository(db).to_response(shot);events=deepcopy(dto['audioEvents']);identity=events[0]['id']
    old_asset=AudioDriveRepository(db).current_tts_asset(identity);path=old_asset.audio_path;sha=file_hash(path)
    for index in (1,2,3):
        dto=ShotRepository(db).to_response(shot);events=deepcopy(dto['audioEvents']);treatments=deepcopy(dto['sourceTreatments'])
        if index==1:events[0]['text']='阿乐照常放羊，此时觉得有些无聊。'
        elif index==2:events[0]['pauseAfter']='LONG'
        else:
            events[0].update(type='INNER_MONOLOGUE',voiceOwnerName='阿乐',voiceOwnerCharacterId=None,visibleSpeakerName=None,visibleSpeakerCharacterId=None,requiresVisibleLipsync=False)
            next(t for t in treatments if t['key']==events[0]['treatmentRef'])['audio_type']='INNER_MONOLOGUE'
        save(db,shot,audio_events=events,source_treatments=treatments)
        assert require_source(db,shot.id).revision==dto['sourceRevision']+1
        assert AudioDriveRepository(db).list_events(shot.id)[0].id==identity and file_hash(path)==sha
    current=AudioDriveRepository(db).list_events(shot.id)[0]
    assert current.voice_owner_character_id=='30c90869-6947-46f0-861c-4dd649b21e6f'
    assert current.visible_speaker_character_id is None and not current.requires_visible_lipsync


def test_rir011_two_sessions_stale_head_is_client_conflict_not_tampering(media_db):
    db=media_db;shot=shot_at(db,2);identity=shot.id
    with Session(db.bind,autoflush=False) as other:
        stale_head=other.get(ShotRevisionHead,identity);version=stale_head.revision
        save(db,shot,video_description=shot.video_description+'\n客户端A的编辑。')
        with pytest.raises(HTTPException,match='SHOT_REVISION_CONFLICT'):
            ShotRevisionService(other).save_batch(BOOK,CHAPTER,[{'id':identity,'expected_revision':version,'video_description':'客户端B的旧草稿'}])
        assert require_source(db,identity).revision==version+1


def ledger(db):
    tables=['shots','chapters','shot_sources','shot_revisions','shot_revision_heads','shot_audio_events','audio_event_tts_assets',
            'shot_audio_timelines','shot_audio_timeline_events','tasks','characters']
    return {table:hashlib.sha256(json.dumps([dict(row) for row in db.execute(text(f'SELECT * FROM {table} ORDER BY rowid')).mappings()],sort_keys=True,default=str).encode()).hexdigest() for table in tables}


@pytest.mark.parametrize('failure',['second_publication','commit'])
def test_rir011_late_failure_rolls_back_head_events_tasks_and_all_dependencies(media_db,monkeypatch,failure):
    db=media_db;first,second=shot_at(db,2),shot_at(db,4);before=ledger(db)
    current=[require_source(db,s.id).revision for s in (first,second)]
    original_sync=AudioDriveRepository.sync_events;seen=[]
    def sync(repo,*args,**kwargs):
        result=original_sync(repo,*args,**kwargs);seen.append(args[0])
        if failure=='second_publication' and len(seen)==2:
            assert db.get(ShotRevisionHead,first.id).revision==current[0]+1
            raise RuntimeError('INJECTED_LATE_PUBLICATION_FAILURE')
        return result
    monkeypatch.setattr(AudioDriveRepository,'sync_events',sync)
    if failure=='commit':
        def commit():
            assert all(db.get(ShotRevisionHead,s.id).revision==v+1 for s,v in zip((first,second),current))
            raise RuntimeError('INJECTED_LATE_PUBLICATION_FAILURE')
        monkeypatch.setattr(db,'commit',commit)
    patches=[{'id':s.id,'expected_revision':v,'video_description':s.video_description+'\n晚期回滚编辑。'} for s,v in zip((first,second),current)]
    with pytest.raises(RuntimeError,match='INJECTED_LATE_PUBLICATION_FAILURE'):
        ShotRevisionService(db).save_batch(BOOK,CHAPTER,patches)
    db.expire_all();assert ledger(db)==before
    assert all(require_source(db,s.id).revision==v for s,v in zip((first,second),current))
