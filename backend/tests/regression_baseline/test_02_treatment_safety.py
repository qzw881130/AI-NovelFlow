from copy import deepcopy
import json
import pytest

from app.models.chapter_shot_split import ChapterShotSplitRun,ShotSource
from app.models.shot import Shot
from app.services.chapter_scope import collect_scope,validate_plan,SplitReview
from app.services.chapter_governance import require_source
from app.services.narration_coverage import validate_coverage
from test_chapter_shot_split import execute,LLM
from regression_baseline.support import db_session,chapter,fixture
from regression_baseline.treatment_cases import director_output


@pytest.mark.parametrize('case,code',[
    ('overlap','TREATMENT_CONFLICT'),('orphan','AUDIO_EVENT_TREATMENT_MISSING'),
    ('wrong_type','TREATMENT_CONFLICT'),('bad_evidence','TREATMENT_SOURCE_NOT_FOUND'),
    ('no_visual','TREATMENT_VISUAL_TARGET_MISSING'),
])
def test_coverage_rejects_conflicts_without_repairing_intent(db_session,chapter,fixture,case,code):
    data=director_output(narration=True)
    if case=='overlap':data['shots'][0]['source_treatments'].append({**deepcopy(data['shots'][0]['source_treatments'][0]),'key':'overlap'})
    elif case=='orphan':data['shots'][0]['audio_events'][0]['treatment_ref']='unknown'
    elif case=='wrong_type':data['shots'][0]['source_treatments'][0]['audio_type']='INNER_MONOLOGUE'
    elif case=='bad_evidence':data['shots'][0]['source_treatments'][0]['source_evidence']=[{'text':'not in source'}]
    else:data['shots'][1]['source_treatments'][0]['visual_targets']=[]
    before=deepcopy(data)
    report=validate_coverage(data,collect_scope(db_session,chapter.novel_id,chapter.id))
    assert report['status']=='FAIL'
    assert code in {issue['code'] for issue in report['issues']}
    assert before==data


def test_unreferenced_matching_text_is_not_adopted(db_session,chapter,fixture):
    data=director_output(narration=True);data['shots'][0]['audio_events'][0].pop('treatment_ref')
    report=validate_coverage(data,collect_scope(db_session,chapter.novel_id,chapter.id))
    assert {'NARRATION_EVENT_MISSING','AUDIO_EVENT_TREATMENT_MISSING'}<={i['code'] for i in report['issues']}


def test_structure_preserving_director_rejects_unrelated_replanning(db_session,chapter,fixture):
    original=director_output()
    first=execute(db_session,chapter,LLM(db_session,original));assert first['success']
    ids=[s.id for s in db_session.query(Shot).order_by(Shot.index)]
    changed=deepcopy(original);changed['shots'][0]['duration']=30
    from app.services.chapter_shot_split_service import ChapterShotSplitService
    import asyncio
    result=asyncio.run(ChapterShotSplitService(db_session,LLM(db_session,changed)).split(chapter.novel_id,chapter.id,preserve_structure=True))
    assert not result['success'] and 'REPAIR_SCOPE_VIOLATION' in result['message']
    assert ids==[s.id for s in db_session.query(Shot).order_by(Shot.index)]
    assert db_session.get(Shot,ids[0]).estimated_duration==8


def test_missing_contract_cannot_be_used_as_a_runtime_fallback(db_session,chapter,fixture):
    assert execute(db_session,chapter,LLM(db_session,director_output()))['success']
    shot=db_session.query(Shot).order_by(Shot.index).first()
    run=db_session.query(ChapterShotSplitRun).one()
    # The admission marker is server-owned; historical records without it stay unavailable.
    inputs=deepcopy(run.inputs);inputs.pop('treatment_contract_version');run.inputs=inputs;db_session.commit()
    from fastapi import HTTPException
    with pytest.raises(HTTPException,match='CONTRACT_UNAVAILABLE'):require_source(db_session,shot.id)
