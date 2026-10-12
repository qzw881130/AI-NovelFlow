"""Offline regressions from the saved Shot 6 C1 #14 failure; no model or ComfyUI calls."""
import copy
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.api import shots as shot_api
from app.models.task import Task
from app.services.h3_evidence import resolve_canonical_excerpt
from app.services.h3_execution_optimizer import check_authority
from app.services.shot_video_service import _project_semantic_clip_failure
from test_semantic_batch_scheduler import _fixture


EVIDENCE = Path(__file__).resolve().parents[2] / 'docs/shot6-auto-video-e2e'
CANONICAL_END = (
    '到12秒时摄影机沿原正面轴线停在中近景：骗子1位于左侧织机前，双手悬停并向右注视；'
    '骗子2位于右侧织机前微微前倾，以两只手共同锁定右侧织机空置编织区域内的同一细小位置；'
    '两架织机仍为空置状态，所有动作在该姿态上停止。'
)
MISQUOTED = ('摄影机沿原正面轴线停在中近景；两者的手势共同锁定右侧织机空置编织区域内'
             '一个细小位置，形成明确的共同检查关系。')
REQUIREMENT = {'source_excerpt': MISQUOTED,
               'requirement': 'The two subjects jointly inspect the same empty location in a frontal medium-close view.'}
AUTHORITY = {'subject_bindings': {'<Subject 1>': '骗子1', '<Subject 2>': '骗子2'}}


def saved_record():
    if not (EVIDENCE / 'optimizer-record.json').exists():
        pytest.skip('Local Shot 6 evidence archive is not distributed with the repository')
    return json.loads((EVIDENCE / 'optimizer-record.json').read_text())


def check(record, output):
    runtime = record['runtime_input']
    return check_authority(record['raw_prompt'], output, runtime['immutable_authority'],
                           runtime['initial_execution_timing'], runtime['duration_limits'])


def test_portable_exact_and_unique_misquote_resolution():
    exact = resolve_canonical_excerpt(CANONICAL_END, {**REQUIREMENT, 'source_excerpt': CANONICAL_END}, AUTHORITY)
    assert exact['status'] == 'RESOLVED' and exact['method'] == 'EXACT'
    resolved = resolve_canonical_excerpt(CANONICAL_END, REQUIREMENT, AUTHORITY)
    assert resolved['status'] == 'RESOLVED' and resolved['method'] == 'CANONICAL_UNIQUE_CITATION_ANCHORS'
    assert resolved['excerpt'] == CANONICAL_END[len('到12秒时'):]


@pytest.mark.parametrize('source,quote', [
    (CANONICAL_END + '\n\n' + CANONICAL_END, MISQUOTED),
    (CANONICAL_END, MISQUOTED + '并拿出真实布料'),
    (CANONICAL_END, MISQUOTED.replace('两者的手势', '骗子3的手势')),
])
def test_portable_ambiguous_or_invalid_citations_block(source, quote):
    result = resolve_canonical_excerpt(source, {**REQUIREMENT, 'source_excerpt': quote}, AUTHORITY)
    assert result['status'] != 'RESOLVED'


def test_exact_canonical_citation_passes_without_rewriting_candidate():
    record = saved_record()
    output = copy.deepcopy(record['original_output'])
    source = next(source['text'] for source in record['runtime_input']['immutable_authority']['anchor_policy']['canonical_visual_sources']
                  if source['id'] == 'transition_1')
    output['canonical_visual_requirements'][6]['source_excerpt'] = source[source.index('到12秒时'):]
    result = check(record, output)
    assert result['passed'], result['blocking_findings']
    assert result['resolved_evidence']['entries']['requirements.6.source']['method'] == 'EXACT'


def test_saved_shot6_citation_resolves_to_unique_actual_source_without_mutation():
    record = saved_record()
    before = copy.deepcopy(record)
    result = check(record, record['original_output'])
    assert result['passed'], result['blocking_findings']
    evidence = result['resolved_evidence']['entries']['requirements.6.source']
    assert evidence['method'] == 'CANONICAL_UNIQUE_CITATION_ANCHORS'
    assert evidence['mismatch'] and evidence['semantic_review_required']
    assert '骗子1位于左侧织机前' in evidence['excerpt']
    assert '骗子2位于右侧织机前' in evidence['excerpt']
    assert '两架织机仍为空置状态' in evidence['excerpt']
    assert evidence['supplied_excerpt'] == before['original_output']['canonical_visual_requirements'][6]['source_excerpt']
    assert record == before


@pytest.mark.parametrize('change', ['ambiguous', 'invented_prop', 'wrong_actor'])
def test_unverifiable_citation_remains_blocked(change):
    record = saved_record()
    runtime = record['runtime_input']
    requirement = copy.deepcopy(record['original_output']['canonical_visual_requirements'][6])
    source = next(source['text'] for source in runtime['immutable_authority']['anchor_policy']['canonical_visual_sources']
                  if source['id'] == 'transition_1')
    if change == 'ambiguous':
        source += '\n\n' + source
    elif change == 'invented_prop':
        requirement['source_excerpt'] += '并拿出真实布料'
    else:
        requirement['source_excerpt'] = requirement['source_excerpt'].replace('两者的手势', '骗子3的手势')
    evidence = resolve_canonical_excerpt(source, requirement, runtime['immutable_authority'])
    assert evidence['status'] != 'RESOLVED'


def test_real_canonical_dialogue_change_still_blocks_saved_prompt():
    record = saved_record()
    output = copy.deepcopy(record['original_output'])
    output['optimized_prompt'] = output['optimized_prompt'].replace('把银线递给我。', '把金线递给我。')
    result = check(record, output)
    assert result['checks']['canonical_visual_requirement_trace']
    assert not result['passed']
    assert 'dialogue_ids_speakers_text_order' in result['blocking_findings']


def test_required_shared_inspection_removed_from_prompt_still_blocks():
    record = saved_record()
    output = copy.deepcopy(record['original_output'])
    excerpt = output['canonical_visual_requirements'][6]['prompt_excerpt']
    output['optimized_prompt'] = output['optimized_prompt'].replace(excerpt, '')
    result = check(record, output)
    assert result['checks']['canonical_visual_requirement_trace']
    assert not result['checks']['canonical_visual_requirement_consistency']
    assert not result['passed']


def test_failed_clip_projects_terminal_task_clip_shot_and_paused_batch(db_session):
    novel, chapter, shot, parent, child = _fixture(db_session, capabilities=('GENERATE', 'EXTEND'))
    parent.status = child.status = 'paused'
    shot.video_status = 'pending'
    shot.video_url = '/existing/approved.mp4'
    clip_task = Task(id='shot6-c1-failed', type='shot_video', status='running', name='C1',
                     novel_id=novel.id, chapter_id=chapter.id, shot_id=shot.id,
                     parent_task_id=parent.id, metadata_json=json.dumps({'approval_status': 'GENERATING'}))
    db_session.add(clip_task)
    db_session.commit()
    reason = '#14 preflight failed: canonical_visual_requirement_trace'
    _project_semantic_clip_failure(db_session, clip_task, shot, {'clip_index': 1}, reason)
    db_session.commit()
    db_session.expire_all()
    task = db_session.get(Task, clip_task.id)
    parent = db_session.get(Task, parent.id)
    child = db_session.get(Task, child.id)
    shot = db_session.get(type(shot), shot.id)
    clip = json.loads(shot.video_director_plan)['clip_plan'][0]
    assert task.status == 'failed' and task.completed_at is not None
    assert task.error_message == reason and json.loads(task.metadata_json)['approval_status'] == 'FAILED'
    assert clip['execution_status'] == 'FAILED' and clip['error_message'] == reason
    assert shot.video_status == 'failed' and shot.video_url == '/existing/approved.mp4'
    assert parent.status == child.status == 'paused'
    assert parent.error_message == child.error_message == reason


@pytest.mark.asyncio
async def test_batch_pause_branch_keeps_existing_clip_failure(db_session, monkeypatch):
    _, _, shot, parent, child = _fixture(db_session, capabilities=('GENERATE',))
    monkeypatch.setattr(shot_api, 'SessionLocal', sessionmaker(bind=db_session.get_bind()))

    async def paused_after_failure(db, batch, batch_child, current_shot):
        batch.error_message = 'C1 preflight failure'
        return 'paused'

    monkeypatch.setattr(shot_api, '_run_semantic_shot_for_batch', paused_after_failure)
    await shot_api.run_shot_video_batch_task(parent.id)
    db_session.expire_all()
    assert db_session.get(Task, parent.id).status == 'paused'
    assert db_session.get(Task, child.id).status == 'paused'
    assert db_session.get(Task, parent.id).error_message == 'C1 preflight failure'
    assert db_session.get(Task, child.id).error_message == 'C1 preflight failure'
