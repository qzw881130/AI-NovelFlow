from copy import deepcopy

import pytest
from sqlalchemy import event as sql_event

from app.models.novel import Character
from app.models.shot import Shot
from app.models.task import Task
from app.models.chapter_shot_split import ShotSource
from app.services.chapter_scope import collect_scope, validate_plan, SplitReview
from app.services.narration_coverage import validate_coverage
from test_chapter_shot_split import execute, LLM
from regression_baseline.support import db_session, chapter, fixture
from regression_baseline.treatment_cases import director_output


def test_required_narration_missing_must_fail_even_when_every_dialogue_is_present(db_session,chapter,fixture):
    data=director_output(narration=True);data['shots'][0]['audio_events']=[]
    with pytest.raises(SplitReview,match='NARRATION_EVENT_MISSING'):
        validate_plan(data,collect_scope(db_session,chapter.novel_id,chapter.id))


def test_deleting_both_treatment_and_event_does_not_turn_text_into_visual(db_session,chapter,fixture):
    data=director_output();data['shots'][0]['source_treatments']=[]
    with pytest.raises(SplitReview,match='SOURCE_TREATMENT_MISSING'):
        validate_plan(data,collect_scope(db_session,chapter.novel_id,chapter.id))


def test_shrinking_shot_range_cannot_hide_chapter_text(db_session,chapter,fixture):
    data=director_output()
    data['shots'][0]['source_evidence']=[{'text':'站定。'}]
    data['shots'][0]['source_treatments'][0]['source_evidence']=[{'text':'站定。'}]
    with pytest.raises(SplitReview,match='SOURCE_TREATMENT_MISSING'):
        validate_plan(data,collect_scope(db_session,chapter.novel_id,chapter.id))


def test_visual_adaptation_does_not_force_every_non_dialogue_word_to_be_read(db_session,chapter,fixture):
    basis=collect_scope(db_session,chapter.novel_id,chapter.id)
    result=validate_coverage(director_output(),basis)
    assert result['status']=='PASS'
    assert result['visual_semantics_verified'] is False
    assert result['counts']['narration']==0


def test_narration_is_audio_only_and_uses_only_the_same_shot_director(db_session,chapter,fixture):
    llm=LLM(db_session,director_output(narration=True))
    result=execute(db_session,chapter,llm)
    assert result['success'],result
    assert len(llm.calls)==1
    assert llm.calls[0]['task_type']=='split_chapter'
    from app.services.shot_treatment_contract import load_director_increment
    increment=load_director_increment()['definition']
    assert increment['system_suffix'] in llm.calls[0]['system_prompt']
    assert increment['dialogue_evidence_suffix'] in llm.calls[0]['system_prompt']
    assert not {'provider','model','endpoint','task_type'} & set(increment)
    assert getattr(llm,'coverage_calls',[])==[], 'A second coverage LLM is forbidden'
    profiles=db_session.query(Character).filter_by(novel_id=chapter.novel_id,is_narrator=True).all()
    assert len(profiles)==1
    assert all('旁白' not in shot['characters'] for shot in result['data']['shots'])
    assert profiles[0].voice_prompt in {None,''}, 'Coverage must not impose a new default voice strategy'


def test_inner_monologue_is_not_book_narrator(db_session,chapter,fixture):
    data=director_output(inner=True)
    result=execute(db_session,chapter,LLM(db_session,data))
    assert result['success'],result
    assert db_session.query(Character).filter_by(novel_id=chapter.novel_id,is_narrator=True).count()==0


def test_invalid_director_candidate_never_publishes_a_partial_head(db_session,chapter,fixture):
    old=Shot(chapter_id=chapter.id,index=1,description='accepted older editorial work',video_url='/accepted.mp4')
    db_session.add(old);chapter.final_video='/accepted-final.mp4';db_session.commit();old_id=old.id
    data=director_output(narration=True);data['shots'][0]['audio_events']=[]
    result=execute(db_session,chapter,LLM(db_session,data))
    assert not result['success']
    assert 'NARRATION_EVENT_MISSING' in result['message'],result
    db_session.expire_all()
    assert db_session.query(Shot).one().id==old_id
    assert db_session.get(Shot,old_id).video_url=='/accepted.mp4'
    assert chapter.final_video=='/accepted-final.mp4'
    assert db_session.query(ShotSource).count()==0
    assert db_session.query(Character).filter_by(is_narrator=True).count()==0


def test_correct_coverage_is_repeatable_pure_read_and_no_profile_creation(db_session,chapter,fixture,monkeypatch):
    data=director_output(narration=True);basis=collect_scope(db_session,chapter.novel_id,chapter.id)
    frozen=deepcopy((data,basis))
    from app.services.llm_service import LLMService
    monkeypatch.setattr(LLMService,'chat_completion',lambda *a,**k:pytest.fail('Validator invoked an LLM'))
    before=(db_session.query(Task).count(),db_session.query(Character).count(),db_session.query(Shot).count())
    def forbid(conn,cursor,statement,*args):
        assert statement.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','CREATE','ALTER','REPLACE'}
    sql_event.listen(db_session.bind,'before_cursor_execute',forbid)
    try:
        first=validate_coverage(data,basis);second=validate_coverage(data,basis)
        assert first==second and first['status']=='PASS'
        assert (data,basis)==frozen
        assert before==(db_session.query(Task).count(),db_session.query(Character).count(),db_session.query(Shot).count())
    finally:
        sql_event.remove(db_session.bind,'before_cursor_execute',forbid)
