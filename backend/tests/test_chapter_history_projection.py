"""Page reads defer historical payloads without losing stored execution or audit data."""
import json
from unittest.mock import Mock
import pytest
from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.repositories.shot_repository import ShotRepository
from app.repositories.chapter_repository import ChapterRepository


@pytest.fixture
def history(db_session):
    novel = Novel(id='projection-novel', title='projection')
    chapter = Chapter(id='projection-chapter', novel_id=novel.id, title='chapter', number=1, content='canonical')
    calls = [{'step': '14', 'created_at': '2026-10-11T00:00:00', 'status': 'success',
              'input_summary': 'C1', 'final_prompt': 'Exact final prompt', 'response': 'Exact response',
              'parsed_result': {'nested': {'canonical': 'unchanged'}}}]
    plan = {'ai_calls': calls, 'clip_plan': [{'clip_index': 1, 'prompt_text': 'current execution'}],
            'visual_states': [{'state_id': 'state1', 'description': 'canonical state'}]}
    shot = Shot(id='projection-shot', chapter_id=chapter.id, index=1, duration=10,
                dialogues='[{"text":"unchanged"}]', video_director_plan=json.dumps(plan))
    db_session.add_all([novel, chapter, shot]); db_session.commit()
    return novel, chapter, shot, plan


def test_projection_keeps_plan_and_never_writes_history(db_session, history):
    _, _, shot, plan = history
    repo = ShotRepository(db_session); before = shot.video_director_plan
    summary = repo.to_response(shot, include_ai_history=False)
    compact = summary['videoDirectorPlan']
    assert compact['clip_plan'] == plan['clip_plan']
    assert compact['visual_states'] == plan['visual_states']
    assert compact['ai_calls'][0]['details_deferred']
    assert compact['ai_calls'][0]['history_index'] == 0
    assert not {'response', 'parsed_result', 'final_prompt'} & compact['ai_calls'][0].keys()
    assert repo.to_response(shot)['videoDirectorPlan'] == plan
    assert shot.video_director_plan == before
    assert not db_session.dirty


def test_saving_projected_plan_preserves_complete_server_history(db_session, history):
    _, _, shot, plan = history
    repo = ShotRepository(db_session)
    compact = repo.to_response(shot, include_ai_history=False)['videoDirectorPlan']
    # Also protect a new call appended AFTER the page was read.
    plan['ai_calls'].append({'step': '14', 'response': 'later result'})
    shot.video_director_plan = json.dumps(plan); db_session.commit()
    compact['selected_mode'] = 'SINGLE_FRAME'
    repo.update(shot, video_director_plan=compact)
    saved = json.loads(shot.video_director_plan)
    assert saved['ai_calls'] == plan['ai_calls']
    assert saved['selected_mode'] == 'SINGLE_FRAME'
    assert 'ai_history_deferred' not in saved


def test_chapter_without_shots_does_not_read_or_serialize_shots(db_session, history, monkeypatch):
    _, chapter, _, _ = history
    read = Mock(side_effect=AssertionError('duplicate shots query'))
    monkeypatch.setattr(ShotRepository, 'get_by_chapter', read)
    result = ChapterRepository(db_session).to_detail_response(chapter, include_shots=False)
    assert result['content'] == 'canonical' and 'shots' not in result
    read.assert_not_called()


def test_api_lazy_history_is_exact_and_validates_scope(client, history):
    novel, chapter, shot, plan = history
    base = f'/api/novels/{novel.id}/chapters/{chapter.id}'
    chapter_data = client.get(base + '?include_shots=false').json()['data']
    assert 'shots' not in chapter_data
    assert client.get(base).json()['data']['shots'][0]['videoDirectorPlan']['ai_calls'] == plan['ai_calls']
    summary = client.get(base + '/shots?include_ai_history=false').json()['data'][0]
    call = summary['videoDirectorPlan']['ai_calls'][0]
    url = base + f'/shots/{shot.id}/ai-calls/0'
    result = client.get(url, params={'created_at': call['created_at']})
    assert result.status_code == 200 and result.json()['data'] == plan['ai_calls'][0]
    assert client.get(url, params={'created_at': 'changed'}).status_code == 409
    assert client.get(url.replace('/ai-calls/0', '/ai-calls/-1')).status_code == 404
    assert client.get(url.replace(novel.id, 'wrong-novel')).status_code == 404
    assert client.get(url.replace(chapter.id, 'wrong-chapter')).status_code == 404


def test_chapter_task_filter_loads_only_requested_rows(client, db_session, history):
    from app.models.task import Task
    from sqlalchemy import event
    novel, chapter, shot, _ = history
    db_session.add_all([
        Task(id='selected', name='selected', type='shot_image', status='completed', chapter_id=chapter.id, shot_id=shot.id),
        Task(id='unrelated', name='unrelated', type='shot_video', status='failed', chapter_id=chapter.id, workflow_json='LARGE'),
    ]); db_session.commit()
    chapter_id, shot_id = chapter.id, shot.id
    db_session.expunge_all()
    loaded = []
    def on_load(session, instance):
        if isinstance(instance, Task): loaded.append(instance.id)
    event.listen(db_session, 'loaded_as_persistent', on_load)
    try:
        result = client.get('/api/tasks/', params={'chapter_id': chapter_id, 'type': 'shot_image', 'status': 'completed', 'shot_id': shot_id})
        assert result.status_code == 200
        assert [row['id'] for row in result.json()['data']] == ['selected']
        assert loaded == ['selected']
    finally:
        event.remove(db_session, 'loaded_as_persistent', on_load)


def test_task_list_parses_shared_shot_history_only_once(history, monkeypatch):
    from app.models.task import Task
    from app.services.task_service import TaskService
    _, _, shot, _ = history
    raw = shot.video_director_plan
    original_loads = json.loads
    parsed = []
    def counted(value, *args, **kwargs):
        if value == raw: parsed.append(value)
        return original_loads(value, *args, **kwargs)
    monkeypatch.setattr(json, 'loads', counted)
    tasks = [Task(id=f't{i}', name='video', type='shot_video', shot_id=shot.id, status='completed') for i in range(3)]
    assert len(TaskService.format_task_list(tasks, {}, {}, {}, {shot.id: shot})) == 3
    assert len(parsed) == 1
