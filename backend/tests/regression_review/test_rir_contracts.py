from copy import deepcopy
import json
import pytest
from fastapi import HTTPException
from app.services.chapter_scope import SplitReview
from app.services.narration_coverage import validate_coverage
from app.services.chapter_governance import require_source
from app.services.shot_revision_service import ShotRevisionService
from app.models.chapter_shot_split import ShotSource, ChapterShotSplitRun
from test_rsa_media import db_session, chapter, fixture, base_setup, setup
from regression_review.cases import story, project_dialogues, full_validate


@pytest.mark.parametrize('kind',['VISUAL','NARRATION','INNER_MONOLOGUE'])
def test_rir001_explicit_speech_cannot_be_swallowed_by_treatment_type(kind):
    candidate,basis=story();shot=candidate['shots'][0]
    if kind=='VISUAL':
        shot['source_treatments']=[{'key':'all','type':'VISUAL','source_evidence':shot['source_evidence'],'visual_targets':['description']}]
        shot['audio_events']=[]
    else:
        for t in shot['source_treatments']:
            if t['type']=='DIALOGUE':t.update(type='NARRATION',audio_type=kind)
        for e in shot['audio_events']:
            e.update(type=kind,voice_owner='旁白' if kind=='NARRATION' else '阿青',visible_speaker=None,requires_visible_lipsync=False)
            if kind=='NARRATION':e['text']='“'+e['text']+'”'
    project_dialogues(shot)
    with pytest.raises(SplitReview,match='DIRECT_SPEECH'):full_validate(candidate,basis)
    assert any('DIRECT_SPEECH' in i['code'] for i in validate_coverage(candidate,basis)['issues'])


def test_rir001_explicit_dialogue_and_non_speech_visual_controls():
    assert full_validate(*story())['counts']['dialogue']==2
    for text in ['旗上书：“甲子”。刀名“冷艳锯”。','他在门厅静立。','他心想：“明天再来。”']:
        assert full_validate(*story([(text,'VISUAL')]))['counts']['dialogue']==0


@pytest.mark.parametrize('parts',[
    None,
    [('天色渐暗。','NARRATION'),('阿青说：','VISUAL'),('“先开门。”','DIALOGUE'),('他心想：','VISUAL'),('“再等等。”','INNER_MONOLOGUE')],
])
def test_rir002_cross_treatment_audio_order_is_grounded(parts):
    candidate,basis=story(parts);assert full_validate(candidate,basis)['status']=='PASS'
    shot=candidate['shots'][0];shot['audio_events'].reverse();project_dialogues(shot)
    with pytest.raises(SplitReview,match='AUDIO_SOURCE_ORDER'):full_validate(candidate,basis)
    assert any(i['code']=='AUDIO_SOURCE_ORDER_INVALID' for i in validate_coverage(candidate,basis)['issues'])


def test_rir002_same_treatment_segments_can_interleave_in_true_source_order():
    candidate,basis=story([('天色渐暗。','NARRATION','n'),('阿青说：','VISUAL'),('“先开门。”','DIALOGUE'),('他转身离开。','NARRATION','n')])
    assert full_validate(candidate,basis)['status']=='PASS'
    shot=candidate['shots'][0];shot['audio_events']=[shot['audio_events'][0],shot['audio_events'][2],shot['audio_events'][1]]
    project_dialogues(shot)
    with pytest.raises(SplitReview,match='AUDIO_SOURCE_ORDER'):full_validate(candidate,basis)


def prepare(db,shot,patch):
    current=require_source(db,shot.id);base=db.get(ShotSource,shot.id)
    return ShotRevisionService(db)._prepare(shot,{'expected_revision':current.revision,**patch},base,current,db.get(ChapterShotSplitRun,base.run_id).inputs['basis'])


def test_rir007_revision_cannot_introduce_unbound_visible_description(db_session,setup):
    shot=setup[3][0]
    with pytest.raises(HTTPException,match='SHOT_VISIBLE_CHARACTER_CLOSURE'):
        prepare(db_session,shot,{'description':'Scene: 桃园\nCharacters:\n- 审计外来人物: 中央站立\nAction: 静立'})
    assert not db_session.new and not db_session.dirty and not db_session.deleted


def test_rir007_legal_description_edit_keeps_shared_closure(db_session,setup):
    shot=setup[3][0]
    result=prepare(db_session,shot,{'description':shot.description+'\n微风吹动树叶。'})
    assert result['changed'] and result['source']['bindings']==require_source(db_session,shot.id).bindings
