import json

import pytest
from fastapi import HTTPException

from app.models.audio_drive import ShotAudioEvent
from app.models.chapter_shot_split import ShotSource
from app.models.shot import Shot
from app.services.chapter_governance import require_source
from app.services.chapter_shot_split_service import source_payload
from app.services.audio_drive_service import AudioDriveService
from app.services.resolved_shot_assets_service import ResolvedShotAssetsService
from test_chapter_governance import client
from regression_baseline.support import db_session, chapter, fixture, base_setup, setup


@pytest.mark.parametrize('field,value',[
    ('description','Scene: 桃园\nCharacters:\n- 刘备: 画面右侧站立\nAction: 抬头'),
    ('video_description','刘备从当前首帧继续抬头，全程无说话口型。'),
    ('estimated_duration',12),
])
def test_official_edit_can_save_again_and_continue_without_overwriting_original_source(db_session,chapter,setup,field,value):
    shot=setup[3][0];base=db_session.get(ShotSource,shot.id)
    original=source_payload(base);seal=base.seal
    root=f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}/shots'
    c=client(db_session)
    saved=c.patch(root+'/batch',json={'shots':[{'id':shot.id,field:value,'expected_revision':0}]})
    assert saved.status_code==200,saved.text
    again=c.patch(root+'/batch',json={'shots':[{'id':shot.id,field:value,'expected_revision':1}]})
    assert again.status_code==200,again.text
    db_session.expire_all()
    require_source(db_session,shot.id)
    assert source_payload(db_session.get(ShotSource,shot.id))==original
    assert db_session.get(ShotSource,shot.id).seal==seal
    assert AudioDriveService(db_session).build_timeline(shot.id)['success']
    assert ResolvedShotAssetsService(db_session).resolveShotAssets(shot.id)['success']


def test_authorized_narration_addition_is_consumable_instead_of_200_then_permanent_409(db_session,chapter,setup):
    shot=setup[3][0];source=require_source(db_session,shot.id)
    text=chapter.content[source.source_start:source.source_end]
    event={'order':1,'type':'NARRATION','voiceOwnerName':'旁白','visibleSpeakerName':None,
        'requiresVisibleLipsync':False,'text':text,'emotionPrompt':'平静','pauseAfter':'NONE','treatment_ref':'authored-narration'}
    treatments=[{'key':'authored-narration','type':'NARRATION','source_evidence':[{'text':text}],
                 'visual_targets':['video_description'],'audio_type':'NARRATION'}]
    response=client(db_session).patch(f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}/shots/batch',
        json={'shots':[{'id':shot.id,'audio_events':[event],'source_treatments':treatments,'expected_revision':0}]})
    assert response.status_code==200,response.text
    require_source(db_session,shot.id)
    assert db_session.query(ShotAudioEvent).filter_by(shot_id=shot.id,event_type='NARRATION').count()==1


def test_direct_database_drift_is_still_rejected(db_session,chapter,setup):
    shot=setup[3][0];shot.description+=' unrecorded drift';db_session.commit()
    with pytest.raises(HTTPException):require_source(db_session,shot.id)


def test_stale_client_revision_is_a_revision_conflict_not_tampering(db_session,chapter,setup):
    shot=setup[3][0];root=f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}/shots'
    c=client(db_session)
    first=c.patch(root+'/batch',json={'shots':[{'id':shot.id,'video_description':'first edit','expected_revision':0}]})
    assert first.status_code==200,first.text
    stale=c.patch(root+'/batch',json={'shots':[{'id':shot.id,'video_description':'stale edit','expected_revision':0}]})
    assert stale.status_code==409
    assert stale.json()['detail']['code']=='SHOT_REVISION_CONFLICT'
    db_session.expire_all();assert db_session.get(Shot,shot.id).video_description=='first edit'


def test_batch_revision_validation_is_atomic(db_session,chapter,setup):
    first,second=setup[3];before=first.description
    response=client(db_session).patch(f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}/shots/batch',json={'shots':[
        {'id':first.id,'description':before+' edited','expected_revision':0},
        {'id':second.id,'characters':['不属于本章的人'],'expected_revision':0},
    ]})
    assert response.status_code in {409,422},response.text
    db_session.expire_all();assert db_session.get(Shot,first.id).description==before
