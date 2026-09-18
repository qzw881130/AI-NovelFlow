from copy import deepcopy
import json
from pathlib import Path
import pytest
from fastapi import HTTPException
from regression_review.cases import story, project_dialogues, full_validate
from app.services.chapter_scope import SplitReview
from app.services.chapter_governance import require_source
from app.services.shot_revision_service import ShotRevisionService
from app.services.shot_treatment_contract import validate_source_contract
from app.models.chapter_shot_split import ChapterShotSplitRun
from app.models.shot import Shot
from app.models.audio_drive import ShotAudioEvent
from app.models.prompt_template import PromptTemplate
from app.models.novel import Scene
from app.repositories.shot_repository import ShotRepository
from test_chapter_shot_split import LLM, execute
from test_appearance_timeline import db_session, chapter, prepare
from test_asset_resolution import extract, resolve
from app.services.appearance_timeline_service import AppearanceTimelineService


@pytest.mark.parametrize('parts',[
    [('阿青说，','VISUAL'),('“先开门。”','DIALOGUE')],
    [('“先开门。”','DIALOGUE'),('阿青说。','VISUAL')],
    [('阿青低声说道，','VISUAL'),('“先开门。”','DIALOGUE')],
    [('“先开门。”','DIALOGUE'),('阿青轻声回答。','VISUAL')],
])
@pytest.mark.parametrize('replacement',['VISUAL','NARRATION','INNER_MONOLOGUE'])
def test_tg01_speech_attribution_survives_punctuation_and_postposed_speaker(parts,replacement):
    candidate,basis=story(parts);assert full_validate(candidate,basis)['status']=='PASS'
    shot=candidate['shots'][0];event=shot['audio_events'][0]
    treatment=next(t for t in shot['source_treatments'] if t['key']==event['treatment_ref'])
    if replacement=='VISUAL':treatment['type']='VISUAL';shot['audio_events']=[]
    else:
        treatment.update(type='NARRATION',audio_type=replacement)
        event.update(type=replacement,voice_owner='旁白' if replacement=='NARRATION' else '阿青',visible_speaker=None,requires_visible_lipsync=False)
        if replacement=='NARRATION':event['text']='“'+event['text']+'”'
    project_dialogues(shot)
    with pytest.raises(SplitReview,match='DIRECT_SPEECH'):full_validate(candidate,basis)


@pytest.mark.parametrize('prefix,kind',[
    ('门上写着：','VISUAL'),('门上刻着：','VISUAL'),('纸上印着：','VISUAL'),
    ('阿青心里想：','INNER_MONOLOGUE'),('阿青心中想着，','INNER_MONOLOGUE'),('阿青暗自想道：','INNER_MONOLOGUE'),
])
def test_tg02_ra_new001_written_and_internal_expressions_are_not_forced_dialogue(prefix,kind):
    assert full_validate(*story([(prefix,'VISUAL'),('“明天再来。”',kind)]))['status']=='PASS'


def test_tg02_speaking_after_writing_is_still_speech():
    candidate,basis=story([('阿青写完后说道：','VISUAL'),('“明天再来。”','INNER_MONOLOGUE')])
    with pytest.raises(SplitReview,match='DIRECT_SPEECH'):full_validate(candidate,basis)


@pytest.fixture
def grouped(db_session,chapter):
    candidate,_=story([('夜深了。','NARRATION','n'),('阿青说：','VISUAL'),('“关门。”','DIALOGUE'),('雨停了。','NARRATION','n')])
    text=candidate['shots'][0]['source_evidence'][0]['text']
    prepare(db_session,chapter,text,name='阿青')
    db_session.add(Scene(novel_id=chapter.novel_id,name='门厅',setting='门厅'));db_session.commit()
    extract(db_session,chapter,[{'name':'门厅','description':'门厅','setting':'门厅','source_evidence':[{'text':'关门'}]}],'scenes')
    resolution=resolve(db_session,chapter,kinds=['scenes']);assert resolution['success'],resolution
    extract(db_session,chapter,[],'props');assert resolve(db_session,chapter,kinds=['props'])['success']
    assert AppearanceTimelineService(db_session).build(chapter.novel_id,chapter.id)['success']
    db_session.add(PromptTemplate(name='Director',type='chapter_split',is_system=True,is_active=True,
        template=(Path(__file__).parents[2]/'prompt_templates/05_NovelFlow_VideoDirector_ShotDirector_V1.txt').read_text()))
    db_session.commit();candidate['chapter']=chapter.title
    result=execute(db_session,chapter,LLM(db_session,candidate));assert result['success'],result
    return db_session.query(Shot).filter_by(chapter_id=chapter.id).one()


def publish(db,chapter,shot,events,**extra):
    current=require_source(db,shot.id)
    return ShotRevisionService(db).save_batch(chapter.novel_id,chapter.id,
        [{'id':shot.id,'expected_revision':current.revision,'audio_events':events,**extra}])


def test_tg03_ra_new002_authored_interleaving_keeps_each_existing_event_source(db_session,chapter,grouped):
    shot=grouped;events=deepcopy(ShotRepository(db_session).to_response(shot)['audioEvents']);ids=[e['id'] for e in events]
    for first,last in [('夜色深沉。','雨停了。'),('夜色更深。','雨已经停了。')]:
        events[0]['text'],events[2]['text']=first,last
        result=publish(db_session,chapter,shot,events)
        events=deepcopy(result['data']['shots'][0]['audioEvents'])
        assert [e['id'] for e in events]==ids
        current=require_source(db_session,shot.id)
        assert validate_source_contract(current,db_session.get(ChapterShotSplitRun,current.run_id).inputs['basis'])['status']=='PASS'
    reordered=[events[0],events[2],events[1]]
    with pytest.raises(HTTPException,match='AUDIO_SOURCE_ORDER'):publish(db_session,chapter,shot,reordered)
    assert require_source(db_session,shot.id).revision==2
    assert publish(db_session,chapter,shot,events)['data']['shots'][0]['sourceRevision']==2


def test_tg05_new_client_ids_are_mapped_by_the_actual_publisher(db_session,chapter,grouped):
    shot=grouped;dto=ShotRepository(db_session).to_response(shot);events=deepcopy(dto['audioEvents']);treatments=deepcopy(dto['sourceTreatments'])
    # Explicitly split the two source declarations before replacing only the tail Event.
    n=next(t for t in treatments if t['key']=='n');tail={**deepcopy(n),'key':'tail','source_evidence':[n['source_evidence'][1]]}
    n['source_evidence']=n['source_evidence'][:1];treatments.append(tail);events[2]['treatmentRef']='tail'
    old_id=events[2]['id'];events[2]['id']='local-tail'
    result=publish(db_session,chapter,shot,events,source_treatments=treatments)
    created=result['data']['shots'][0]['audioEvents'][2]['id']
    assert result['data']['eventIdMaps'][shot.id]['local-tail']==created and created!=old_id
    assert require_source(db_session,shot.id).revision==1


@pytest.mark.parametrize('field',['description','video_description'])
def test_tg06_all_explicit_character_blocks_are_checked_in_split_and_revision(db_session,chapter,grouped,field):
    shot=grouped;bad=getattr(shot,field)+'\nCharacters:\n- 审计外来人物: 中央站立\nAction: 他走入画面。'
    with pytest.raises(HTTPException,match='SHOT_VISIBLE_CHARACTER_CLOSURE'):
        publish(db_session,chapter,shot,ShotRepository(db_session).to_response(shot)['audioEvents'],**{field:bad})
    candidate,basis=story();candidate['shots'][0][field]+='\nCharacters:\n- 审计外来人物: 中央站立\nAction: 静立'
    with pytest.raises(SplitReview,match='SHOT_VISIBLE_CHARACTER_CLOSURE'):full_validate(candidate,basis)


def test_tg06_repeated_known_blocks_and_plain_video_prose_remain_valid():
    candidate,basis=story();shot=candidate['shots'][0]
    shot['description']+='\nCharacters:\n- 阿青: 画面右侧\nAction: 回头'
    shot['video_description']='Characters:\n- 阿青: 转头\nAction: 平稳移动'
    assert full_validate(candidate,basis)['status']=='PASS'
