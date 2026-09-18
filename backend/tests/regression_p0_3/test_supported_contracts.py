from copy import deepcopy
import json
import pytest
from fastapi import HTTPException
from regression_review.cases import story,project_dialogues,full_validate
from regression_p0_2.test_source_contracts import db_session,chapter,grouped,publish
from app.services.chapter_scope import SplitReview
from app.repositories.shot_repository import ShotRepository
from app.services.chapter_governance import require_source
from app.services.video_director_ai import prepare_h3_prompt
from regression_review.test_rir_h3 import CONSTRAINT


@pytest.mark.parametrize('field',['description','video_description'])
@pytest.mark.parametrize('row',['* 审计外来人物: 走入','* 阿青: 站立','+ 阿青: 站立','1. 阿青: 站立','未标明归属的游离说明'])
def test_characters_flat_contract_consumes_every_nonblank_line(db_session,chapter,grouped,field,row):
    shot=grouped;bad=getattr(shot,field)+'\nCharacters:\n- 阿青: 站立\n'+row+'\nAction: 两人对视。'
    with pytest.raises(HTTPException,match='SHOT_CHARACTER_DESCRIPTION_FORMAT'):
        publish(db_session,chapter,shot,ShotRepository(db_session).to_response(shot)['audioEvents'],**{field:bad})
    candidate,basis=story();candidate['shots'][0][field]+='\nCharacters:\n- 阿青: 站立\n'+row+'\nAction: 静立'
    with pytest.raises(SplitReview,match='SHOT_CHARACTER_DESCRIPTION_FORMAT'):full_validate(candidate,basis)
    assert require_source(db_session,shot.id).revision==0


@pytest.mark.parametrize('newline',['\n','\r\n'])
def test_canonical_character_blocks_and_plain_video_remain_valid(newline):
    candidate,basis=story();candidate['shots'][0]['description']=newline.join(['Scene: 门厅','Characters:','  - 阿青：站立','Action: 静立'])
    assert full_validate(candidate,basis)['status']=='PASS'


@pytest.mark.parametrize('newline',['\n','\r\n','\n  \n'])
@pytest.mark.parametrize('kind',['VISUAL','NARRATION','INNER_MONOLOGUE'])
def test_supported_standard_attribution_keeps_its_newline(newline,kind):
    candidate,basis=story([('阿青说：'+newline,'VISUAL'),('“先开门。”','DIALOGUE')])
    assert full_validate(candidate,basis)['status']=='PASS'
    shot=candidate['shots'][0];event=shot['audio_events'][0];t=next(t for t in shot['source_treatments'] if t['key']==event['treatment_ref'])
    if kind=='VISUAL':t['type']='VISUAL';shot['audio_events']=[]
    else:
        t.update(type='NARRATION',audio_type=kind);event.update(type=kind,voice_owner='旁白' if kind=='NARRATION' else '阿青',visible_speaker=None,requires_visible_lipsync=False)
        if kind=='NARRATION':event['text']='“'+event['text']+'”'
    project_dialogues(shot)
    with pytest.raises(SplitReview,match='DIRECT_SPEECH'):full_validate(candidate,basis)


def test_next_quote_introduction_cannot_be_borrowed_by_a_name_quote():
    candidate,basis=story([('他的名字是“阿青”，他说：','VISUAL'),('“先开门。”','DIALOGUE')])
    assert full_validate(candidate,basis)['counts']['dialogue']==1
    assert full_validate(*story([('门上的标语是：“禁止入内。”','VISUAL')]))['counts']['dialogue']==0


def h3(body,sound='Use final_audio without modification.',timeline=None):
    document={'subject_definitions':{'<Subject 1>':'the grey wolf','<Subject 2>':'the sheep'},
        'initial_state_anchor':'Both subjects stand in the meadow.','summary':'Hold the same shot.',
        'detailed_description':body,'overall_soundscape':sound}
    return prepare_h3_prompt(json.dumps(document,ensure_ascii=False),constraint=CONSTRAINT,continuity_lock='',
        subject_manifest={'subjects':[{'subject_ref':'<Subject 1>','character_name':'灰狼'},{'subject_ref':'<Subject 2>','character_name':'白羊'}]},
        speaker_timeline=timeline or [{'start_time':0,'end_time':8,'visible_speaker':'NONE'}])


@pytest.mark.parametrize('sound',[
    '画外旁白用低沉的声音说话，可见人物始终保持闭嘴。',
    'The offscreen book narrator speaks over final_audio; all visible subjects remain silent.',
])
def test_audio_only_narrator_does_not_become_a_visible_subject(sound):
    result=h3('All visible subjects remain silent.',sound)
    assert result['passed'] and result['profile']=='director_json'


@pytest.mark.parametrize('body',[
    '<Subject 1>张嘴喘气，没有说话。',
    '<Subject 1> opens its mouth to breathe, without speech or lip-sync.',
    '<Subject 1> looks left and does not speak.',
    '<Subject 1> mouth moves.',
])
def test_non_speech_action_does_not_contradict_visible_none(body):
    assert h3(body)['passed']


@pytest.mark.parametrize('body',[
    '<Subject 1> looks left and speaks.',
    '<Subject 1> turns toward the camera and lip-syncs.',
    '<Subject 1> does not speak at first, but then speaks clearly.',
    'The grey wolf (<Subject 1>) moves forward, then speaks.',
    '<Subject 1>开口说话。',
    '灰狼说话。',
])
def test_explicit_visible_speech_cannot_override_structured_none(body):
    with pytest.raises(RuntimeError,match='AUDIODRIVE_AUDIT_FAILED'):h3(body)


def test_audio_only_description_is_not_a_blanket_soundscape_exemption():
    with pytest.raises(RuntimeError,match='AUDIODRIVE_AUDIT_FAILED'):
        h3('All visible subjects remain silent.','画外旁白说话。<Subject 1>开口说话。')


@pytest.mark.parametrize('mixed',[False,True])
def test_explicit_timed_subject_cannot_replace_the_structured_speaker(mixed):
    timeline=([{'start_time':0,'end_time':4,'visible_speaker':'NONE'}] if mixed else [])+[
        {'start_time':4 if mixed else 0,'end_time':8,'visible_speaker':'<Subject 1>'}]
    start=4 if mixed else 0
    assert h3(f'{start}s-8s <Subject 1> speaks.',timeline=timeline)['passed']
    with pytest.raises(RuntimeError,match='AUDIODRIVE_AUDIT_FAILED'):
        h3(f'{start}s-8s <Subject 2> speaks.',timeline=timeline)
