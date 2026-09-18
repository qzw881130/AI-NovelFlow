import json
import pytest
from app.models.audio_drive import ShotAudioEvent
from app.models.shot_revision import ShotRevision
from app.models.shot import Shot
from app.services.chapter_governance import require_source
from app.services.audio_drive_service import AudioDriveService
from test_chapter_governance import client
from test_rsa_media import db_session, chapter, fixture, base_setup, setup


def root(chapter):return f'/api/novels/{chapter.novel_id}/chapters/{chapter.id}/shots'


def test_rir003_audio_page_writer_publishes_revision_and_can_save_again(db_session,chapter,setup):
    shot=setup[3][1];event=db_session.query(ShotAudioEvent).filter_by(shot_id=shot.id).one();identity=event.id
    c=client(db_session)
    for revision,pause in [(0,'LONG'),(1,'SHORT')]:
        saved=c.patch(f'/api/audio-events/{identity}',json={'pauseAfter':pause,'expectedRevision':revision})
        assert saved.status_code==200,saved.text
        assert require_source(db_session,shot.id).revision==revision+1
        assert saved.json()['data']['shot']['sourceRevision']==revision+1
        assert db_session.get(ShotAudioEvent,identity).pause_after==pause
    assert db_session.query(ShotRevision).filter_by(shot_id=shot.id).count()==2
    assert json.loads(db_session.get(Shot,shot.id).dialogues)[0]['text']=='出发！'


@pytest.mark.parametrize('endpoint',['batch','single','event'])
@pytest.mark.parametrize('alias',['expected_revision','expectedRevision'])
def test_rir004_stale_versions_rejected_identically_across_entrypoints(db_session,chapter,setup,endpoint,alias):
    shot=setup[3][1];event=db_session.query(ShotAudioEvent).filter_by(shot_id=shot.id).one();c=client(db_session)
    first=c.patch(root(chapter)+'/batch',json={'shots':[{'id':shot.id,'expected_revision':0,'video_description':'客户端A修改'}]})
    assert first.status_code==200,first.text
    if endpoint=='event':
        response=c.patch('/api/audio-events/'+event.id,json={alias:0,'pauseAfter':'LONG'})
    else:
        patch={alias:0,'video_description':'客户端B过期修改'}
        response=c.patch(root(chapter)+('/batch' if endpoint=='batch' else '/'+shot.id),
                         json={'shots':[{'id':shot.id,**patch}]} if endpoint=='batch' else patch)
    assert response.status_code==409,response.text
    assert 'SHOT_REVISION_CONFLICT' in response.text
    assert require_source(db_session,shot.id).revision==1


@pytest.mark.parametrize('endpoint',['batch','single','event'])
def test_rir004_missing_cas_never_uses_latest_head(db_session,chapter,setup,endpoint):
    shot=setup[3][1];event=db_session.query(ShotAudioEvent).filter_by(shot_id=shot.id).one();c=client(db_session)
    if endpoint=='event':response=c.patch('/api/audio-events/'+event.id,json={'pauseAfter':'LONG'})
    else:
        patch={'video_description':'没有版本的请求'}
        response=c.patch(root(chapter)+('/batch' if endpoint=='batch' else '/'+shot.id),
                         json={'shots':[{'id':shot.id,**patch}]} if endpoint=='batch' else patch)
    assert response.status_code in {409,422},response.text
    assert require_source(db_session,shot.id).revision==0


@pytest.mark.parametrize('aliases',[{'expected_revision':0,'expectedRevision':1},{'expectedRevision':0,'sourceRevision':1}])
def test_rir004_conflicting_aliases_are_not_silently_selected(db_session,chapter,setup,aliases):
    shot=setup[3][1];c=client(db_session)
    response=c.patch(root(chapter)+'/batch',json={'shots':[{'id':shot.id,**aliases,'video_description':'冲突别名'}]})
    assert response.status_code in {409,422},response.text
    assert require_source(db_session,shot.id).revision==0


@pytest.mark.parametrize('alias',['expected_revision','expectedRevision'])
def test_rir004_valid_cas_and_event_ids_survive_noop_save(db_session,chapter,setup,alias):
    shot=setup[3][1];identity=db_session.query(ShotAudioEvent).filter_by(shot_id=shot.id).one().id
    response=client(db_session).patch(root(chapter)+'/batch',json={'shots':[{'id':shot.id,alias:0,'video_description':shot.video_description}]})
    assert response.status_code==200,response.text
    assert require_source(db_session,shot.id).revision==0
    assert db_session.query(ShotAudioEvent).filter_by(shot_id=shot.id).one().id==identity
