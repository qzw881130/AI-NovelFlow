"""Focused Stage 6 API and planning checks; generation is covered at Stage 8."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.novel import Chapter, Character, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.schemas.grid_shot import GridPanel, GridShotData, dump_grid_clip_plan, dump_grid_data, load_grid_data, read_grid_clip_plan
from app.services.grid_pipeline import GridPipeline, GridPipelineError, _assert_narration_coverage, _dialogues, _h3_bindings
from app.services.grid_tasks import _validate as validate_grid_step


def test_silent_clip_plan_accepts_no_voice_marker(db_session, monkeypatch):
    novel = Novel(title='无台词测试', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='村口', content='杜甫走近。')
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description='走进村口', duration=10,
                dialogues='[]')
    grid = GridShotData(revision=1, layout='2x2', seed=7, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat=f'Beat {i}', camera='中景',
                                          image_url=f'/api/files/panel_{i}.png',
                                          review_status='warning' if i == 1 else 'pending' if i == 2 else 'passed')
                                for i in range(1, 5)])
    shot.grid_data = dump_grid_data(grid)
    db_session.add(shot)
    db_session.commit()

    async def fake_ask(*_args, **_kwargs):
        return {'clips': [
            {'clip_index': 1, 'start_time': 0, 'end_time': 5,
             'physical_reference_panels': [1, 2], 'dialogue_ids': ['NO_VOICE']},
            {'clip_index': 2, 'start_time': 5, 'end_time': 10,
             'physical_reference_panels': [3, 4], 'dialogue_ids': []},
        ]}, 'template'

    monkeypatch.setattr(GridPipeline, '_ask', fake_ask)
    validate_grid_step(db_session, novel, chapter, shot, 'clips_plan')
    result = asyncio.run(GridPipeline(db_session).plan_clips(novel, chapter, shot))
    assert len(result['clip_plan']) == 2
    assert all(not clip['dialogues'] for clip in result['clip_plan'])
    monkeypatch.setattr('app.services.grid_pipeline.url_to_local_path', lambda _url: '/tmp/panel.png')
    assert len(GridPipeline(db_session)._clip_refs(grid, result['clip_plan'][0])) == 2
    grid.panels[0].review_status = 'failed'
    shot.grid_data = dump_grid_data(grid)
    with pytest.raises(GridPipelineError, match='FAIL'):
        validate_grid_step(db_session, novel, chapter, shot, 'clips_plan')
    with pytest.raises(GridPipelineError, match='FAIL'):
        GridPipeline(db_session)._clip_refs(grid, result['clip_plan'][0])


def test_offscreen_clip_plan_repairs_missing_silent_panels(db_session, monkeypatch):
    novel = Novel(title='画外声完整格序', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='村口', content='夜深了。')
    db_session.add(chapter)
    db_session.flush()
    dialogues = [
        {'speaker': '旁白', 'text': '夜深了。', 'delivery': 'offscreen',
         'voice_description': 'a calm adult narrator'},
        {'speaker': '旁白', 'text': '村庄寂静。', 'delivery': 'offscreen',
         'voice_description': 'a calm adult narrator'},
    ]
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat=f'Beat {i}', camera='远景',
                                          image_url=f'/api/files/panel_{i}.png', review_status='passed')
                                for i in range(1, 5)])
    shot = Shot(chapter_id=chapter.id, index=1, description='空村', duration=8,
                dialogues=json.dumps(dialogues, ensure_ascii=False), grid_data=dump_grid_data(grid))
    db_session.add(shot)
    db_session.commit()
    calls = []

    async def fake_ask(_self, _novel, _chapter, _shot, _kind, payload):
        calls.append(payload)
        if len(calls) == 1:
            return {'clips': [
                {'clip_index': 1, 'start_time': 0, 'end_time': 4,
                 'physical_reference_panels': [1], 'dialogue_ids': ['D1']},
                {'clip_index': 2, 'start_time': 4, 'end_time': 8,
                 'physical_reference_panels': [3], 'dialogue_ids': ['D2']},
            ]}, 'template'
        return {'clips': [
            {'clip_index': i, 'start_time': (i - 1) * 2, 'end_time': i * 2,
             'physical_reference_panels': [i],
             'dialogue_ids': ['D1'] if i == 1 else ['D2'] if i == 3 else []}
            for i in range(1, 5)
        ]}, 'template'

    monkeypatch.setattr(GridPipeline, '_ask', fake_ask)
    plan = asyncio.run(GridPipeline(db_session).plan_clips(novel, chapter, shot))
    assert len(calls) == 2
    assert '2, 4' in calls[1]['repair_errors']
    assert [clip['panel_indexes'] for clip in plan['clip_plan']] == [[1], [2], [3], [4]]
    assert [len(clip['dialogues']) for clip in plan['clip_plan']] == [1, 0, 1, 0]


def test_offscreen_clip_cannot_send_whole_board(db_session):
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        board_image_url='/api/files/board.png',
                        panels=[GridPanel(index=i, beat='门外', camera='近景',
                                          image_url=f'/api/files/panel_{i}.png', review_status='passed')
                                for i in range(1, 5)])
    clip = {'reference_strategy': 'whole_board', 'panel_indexes': [1],
            'dialogues': [{'delivery': 'offscreen', 'text': '开门！'}]}
    with pytest.raises(GridPipelineError, match='不能整板直传'):
        GridPipeline(db_session)._clip_refs(grid, clip)


def test_rejecting_panel_invalidates_shot_and_chapter_video(db_session):
    novel = Novel(title='宫格失效测试', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='章回', content='正文',
                      final_video='/api/files/chapter.mp4')
    db_session.add(chapter)
    db_session.flush()
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat=f'Beat {i}', camera='近景',
                                          image_url=f'/api/files/panel_{i}.png', review_status='passed')
                                for i in range(1, 5)])
    shot = Shot(chapter_id=chapter.id, index=1, description='门前', duration=8,
                grid_data=dump_grid_data(grid), video_url='/api/files/shot.mp4',
                video_status='completed')
    db_session.add(shot)
    db_session.commit()

    GridPipeline(db_session).review_panel(shot, 1, 'warning', '构图可复核')
    assert shot.video_url == '/api/files/shot.mp4'
    assert chapter.final_video == '/api/files/chapter.mp4'
    GridPipeline(db_session).review_panel(shot, 2, 'failed', '机位错误')
    assert shot.video_url is None and shot.video_status == 'pending'
    assert chapter.final_video is None
    assert load_grid_data(shot.grid_data).panels[1].review_status == 'failed'


def test_wrong_speaker_panel_invalidates_only_its_clip_and_blocks_reuse(db_session):
    novel = Novel(title='台词焦点修复', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='章回', content='正文',
                      final_video='/api/files/chapter.mp4')
    db_session.add(chapter)
    db_session.flush()
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat=f'Beat {i}', camera='近景',
                                          image_url=f'/api/files/panel_{i}.png', review_status='passed')
                                for i in range(1, 5)])
    clips = [{'clip_index': i, 'duration': 6, 'panel_indexes': [i],
              'reference_strategy': 'split_panels', 'prompt': f'Prompt {i}',
              'reference_images': [{'picture_index': 1, 'url': f'/api/files/panel_{i}.png'}],
              'validation': {'six_sections': True}, 'video_url': f'/api/files/clip_{i}.mp4'}
             for i in range(1, 5)]
    shot = Shot(chapter_id=chapter.id, index=7, description='门前', duration=24,
                grid_data=dump_grid_data(grid), video_director_plan=dump_grid_clip_plan(grid, clips),
                video_url='/api/files/shot.mp4', video_status='completed')
    db_session.add(shot)
    db_session.commit()

    pipeline = GridPipeline(db_session)
    pipeline.review_panel(shot, 3, 'failed', '说话人和过肩前景颠倒')
    kept = read_grid_clip_plan(shot.video_director_plan, grid_revision=1)['clip_plan']
    assert [clip.get('video_url') for clip in kept] == [
        '/api/files/clip_1.mp4', '/api/files/clip_2.mp4', None, '/api/files/clip_4.mp4']
    assert not any(kept[2].get(key) for key in ('prompt', 'reference_images', 'validation'))
    assert shot.video_url is None and chapter.final_video is None
    with pytest.raises(GridPipelineError, match='FAIL'):
        pipeline._clip_refs(load_grid_data(shot.grid_data), kept[2])


def test_replanning_cannot_discard_generated_clip(db_session):
    novel = Novel(title='宫格 Clip 保护', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='章回', content='正文')
    db_session.add(chapter)
    db_session.flush()
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat=f'Beat {i}', camera='近景',
                                          image_url=f'/api/files/panel_{i}.png', review_status='passed')
                                for i in range(1, 5)])
    shot = Shot(chapter_id=chapter.id, index=1, description='门前', duration=8,
                grid_data=dump_grid_data(grid), dialogues='[]',
                video_director_plan=dump_grid_clip_plan(grid, [{
                    'clip_index': 1, 'duration': 8, 'panel_indexes': [1, 2, 3, 4],
                    'video_url': '/api/files/clip.mp4',
                }]))
    db_session.add(shot)
    db_session.commit()

    with pytest.raises(GridPipelineError, match='已有生成的 Clip'):
        asyncio.run(GridPipeline(db_session).plan_clips(novel, chapter, shot))


def test_replanning_completed_shot_replaces_only_after_valid_plan(db_session, monkeypatch):
    novel = Novel(title='重新规划宫格', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='土墙', content='老翁爬上土墙。',
                      final_video='/api/files/chapter.mp4')
    db_session.add(chapter)
    db_session.flush()
    old = GridShotData(revision=3, layout='2x2', seed=7, panel_width=768, panel_height=432,
                       board_image_url='/api/files/board.png',
                       panels=[GridPanel(index=i, beat='无人土墙', camera='近景',
                                         image_url=f'/api/files/old_{i}.png', review_status='passed')
                               for i in range(1, 5)])
    shot = Shot(chapter_id=chapter.id, index=6, description='老翁翻墙', duration=8,
                characters='["老翁"]', dialogues=json.dumps([
                    {'speaker': '旁白', 'text': '老翁爬上土墙。', 'delivery': 'offscreen'}], ensure_ascii=False),
                grid_data=dump_grid_data(old), video_url='/api/files/shot.mp4',
                video_director_plan=dump_grid_clip_plan(old, [{
                    'clip_index': 1, 'panel_indexes': [1], 'video_url': '/api/files/clip.mp4'}]))
    db_session.add(shot)
    db_session.commit()
    validate_grid_step(db_session, novel, chapter, shot, 'panels_plan')

    async def invalid_plan(*_args, **_kwargs):
        return {'panels': []}, 'template'

    monkeypatch.setattr(GridPipeline, '_ask', invalid_plan)
    with pytest.raises(GridPipelineError, match='子格数量'):
        asyncio.run(GridPipeline(db_session).plan_panels(novel, chapter, shot))
    assert load_grid_data(shot.grid_data).board_image_url == '/api/files/board.png'
    assert shot.video_url == '/api/files/shot.mp4'
    assert chapter.final_video == '/api/files/chapter.mp4'

    async def valid_plan(*_args, **_kwargs):
        return {'panels': [
            {'index': i, 'story_beat': '老翁爬墙' if i == 1 else '土墙近景',
             'camera': {'shot_size': '中景'}, 'visible_characters': ['老翁'] if i == 1 else [],
             'action': '老翁攀爬' if i == 1 else '夜风', 'dialogue_ids': ['D1'] if i == 1 else []}
            for i in range(1, 5)]}, 'template'

    monkeypatch.setattr(GridPipeline, '_ask', valid_plan)
    new = asyncio.run(GridPipeline(db_session).plan_panels(novel, chapter, shot))
    assert new.revision == 4 and new.layout == '2x2' and new.seed == 7
    assert new.board_image_url is None and all(not panel.image_url for panel in new.panels)
    assert shot.video_director_plan == '{}'
    assert shot.video_url is None and chapter.final_video is None
    assert json.loads(shot.dialogues)[0]['delivery'] == 'narration'


def test_novel_mode_create_edit_and_existing_shot_lock(client, db_session):
    grid = client.post('/api/novels/', json={'title': '宫格小说', 'videoMode': 'grid'})
    assert grid.status_code == 200
    novel_id = grid.json()['data']['id']
    assert grid.json()['data']['videoMode'] == 'grid'
    assert client.get(f'/api/novels/{novel_id}').json()['data']['videoMode'] == 'grid'
    assert client.put(f'/api/novels/{novel_id}', json={'videoMode': 'single'}).status_code == 200
    assert client.put(f'/api/novels/{novel_id}', json={'videoMode': 'grid'}).status_code == 200
    chapter = Chapter(novel_id=novel_id, number=1, title='第一章', content='正文')
    db_session.add(chapter)
    db_session.flush()
    db_session.add(Shot(chapter_id=chapter.id, index=1, description='已有 Shot'))
    db_session.commit()
    assert client.put(f'/api/novels/{novel_id}', json={'videoMode': 'single'}).status_code == 409
    assert client.get(f'/api/novels/{novel_id}/chapters/{chapter.id}/grid').status_code == 200
    old = client.post('/api/novels/', json={'title': '旧调用'})
    assert old.json()['data']['videoMode'] == 'single'
    assert client.get(f'/api/novels/{old.json()["data"]["id"]}/chapters/{chapter.id}/grid').status_code == 409


def test_grid_shot_and_clip_planning_preserve_dialogue_and_layout(db_session):
    db_session.add(PromptTemplate(name='Grid Planner', type='grid_shot_plan', template='grid planner', is_system=True, is_active=True))
    db_session.add(PromptTemplate(name='Clip Planner', type='grid_clip_plan', template='clip planner', is_system=True, is_active=True))
    novel = Novel(title='宫格', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='黄昏投宿', content='老妪说：“进来吧。”杜甫说：“多谢。”')
    db_session.add(chapter)
    db_session.commit()

    async def complete(**kwargs):
        payload = json.loads(kwargs['user_content'])
        if payload.get('operation') == 'chapter_shots':
            return {'success': True, 'content': json.dumps({'shots': [{
                'title': '交谈', 'description': '门前交替台词', 'duration': 10,
                'characters': [], 'scene': '', 'props': [],
                'dialogues': [{'speaker': '旁白', 'text': '进来吧。'}, {'speaker': '旁白', 'text': '多谢。'}],
            }]}, ensure_ascii=False)}
        if payload.get('operation') == 'shot_panels':
            return {'success': True, 'content': json.dumps({'panels': [{
                'index': i, 'story_beat': f'Beat {i}',
                'camera': {'shot_size': '近景', 'screen_direction': 'left'},
                'visible_characters': [], 'action': '交谈',
                'dialogue_ids': [f'D{i}'] if i <= 2 else [],
            } for i in range(payload['panel_count']) for i in [i + 1]]}, ensure_ascii=False)}
        return {'success': True, 'content': json.dumps({'clips': [
            {'clip_index': 1, 'start_time': 0, 'end_time': 5, 'physical_reference_panels': [1, 2], 'dialogue_ids': ['D1'], 'reference_strategy': 'split_panels'},
            {'clip_index': 2, 'start_time': 5, 'end_time': 10, 'physical_reference_panels': [3, 4], 'dialogue_ids': ['D2'], 'reference_strategy': 'split_panels'},
        ]})}

    pipeline = GridPipeline(db_session, SimpleNamespace(chat_completion=complete))
    shots = asyncio.run(pipeline.plan_chapter(novel, chapter))
    assert len(shots) == 1
    grid = asyncio.run(pipeline.plan_panels(novel, chapter, shots[0], '2x2'))
    assert grid.layout == '2x2' and grid.board_size == (1536, 864)
    assert [p.dialogue_indexes for p in grid.panels] == [[1], [2], [], []]
    for panel in grid.panels:
        panel.image_url = '/api/files/panel.png'
        panel.review_status = 'passed'
    shots[0].grid_data = dump_grid_data(grid)
    db_session.commit()
    plan = asyncio.run(pipeline.plan_clips(novel, chapter, shots[0]))
    assert plan['contract'] == 'GRID_CLIP_PLAN_V1'
    assert [c['dialogues'][0]['text'] for c in plan['clip_plan']] == ['进来吧。', '多谢。']
    assert load_grid_data(shots[0].grid_data).seed == grid.seed


@pytest.mark.parametrize('response,expected', [
    ({'shots': [
        {'description': '屋内', 'characters': ['老翁'], 'dialogues': []},
        {'description': '门外喊话', 'characters': ['老翁'],
         'dialogues': [{'speaker': '门外喊声', 'text': '开门！'}]},
    ]}, 'Shot 2 第 1 句说话人“门外喊声”不在已批准角色中'),
])
def test_grid_chapter_plan_reports_missing_offscreen_speaker(db_session, monkeypatch, response, expected):
    novel = Novel(title='画外喊话', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='夜半惊变', content='门外传来喊声：“开门！”')
    db_session.add(chapter)
    db_session.add(Character(novel_id=novel.id, name='老翁'))
    db_session.commit()

    async def fake_ask(*_args, **_kwargs):
        return response, 'template'

    monkeypatch.setattr(GridPipeline, '_ask', fake_ask)
    with pytest.raises(GridPipelineError, match=expected):
        asyncio.run(GridPipeline(db_session).plan_chapter(novel, chapter))
    assert db_session.query(Shot).filter(Shot.chapter_id == chapter.id).count() == 0


def test_grid_offscreen_dialogue_needs_no_visual_character(db_session, monkeypatch):
    novel = Novel(title='门外喊话', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='夜半惊变', content='门外传来喊声：“开门！”')
    db_session.add(chapter)
    db_session.commit()
    async def fake_ask(*_args, **_kwargs):
        return {'shots': [
            {'description': '木门外有人喊话', 'characters': [],
             'dialogues': [{'speaker': '门外官差', 'text': '开门！', 'delivery': 'offscreen',
                            'voice_description': 'a harsh adult male officer outside the farmhouse'}]},
            {'description': '门外官差怒喝', 'characters': [],
             'dialogues': [{'speaker': '门外官差', 'text': '再不开门，就撞门了！',
                            'delivery': 'offscreen',
                            'voice_description': 'a furious adult male officer outside the farmhouse'}]},
        ]}, 'template'
    monkeypatch.setattr(GridPipeline, '_ask', fake_ask)
    shot, later_shot = asyncio.run(GridPipeline(db_session).plan_chapter(novel, chapter))
    assert json.loads(shot.characters) == []
    assert json.loads(shot.dialogues)[0]['delivery'] == 'offscreen'
    assert json.loads(later_shot.dialogues)[0]['voice_description'] == (
        'a furious adult male officer outside the farmhouse')
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat='木门', camera='特写') for i in range(1, 5)])
    subjects, events = _h3_bindings(grid, {'panel_indexes': [1], 'dialogues': [
        {'speaker': '门外官差', 'text': '开门！', 'delivery': 'offscreen',
         'voice_description': 'a rough adult male officer outside the door'},
        {'speaker': '门外官差', 'text': '再不开门就撞门了！', 'delivery': 'offscreen',
         'voice_description': 'a furious adult male officer outside the door'}]})
    assert subjects == {}
    assert events[0]['speaker'] == 'Off-screen voice: a rough adult male officer outside the door'
    assert events[1]['speaker'] == events[0]['speaker']
    assert events[1]['voice_description'] == 'a furious adult male officer outside the door'


def test_grid_panel_rejects_visible_people_during_offscreen_dialogue(db_session, monkeypatch):
    novel = Novel(title='画外声子格', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='夜半惊变', content='门外传来喊声：“开门！”')
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description='门外喊话', duration=10,
                characters=json.dumps(['老翁'], ensure_ascii=False),
                dialogues=json.dumps([{'speaker': '门外官差', 'text': '开门！',
                                       'delivery': 'offscreen',
                                       'voice_description': 'a rough adult male officer outside the door'}],
                                     ensure_ascii=False))
    db_session.add(shot)
    db_session.commit()
    async def fake_ask(*_args, **_kwargs):
        return {'panels': [
            {'index': i, 'story_beat': '老翁听到喊话', 'camera': {'shot_size': '近景'},
             'visible_characters': ['老翁'] if i == 1 else [],
             'dialogue_ids': ['D1'] if i == 1 else []}
            for i in range(1, 5)
        ]}, 'template'
    monkeypatch.setattr(GridPipeline, '_ask', fake_ask)
    with pytest.raises(GridPipelineError, match='画外台词期间不得出现人物'):
        asyncio.run(GridPipeline(db_session).plan_panels(novel, chapter, shot, '2x2'))


def test_narrated_action_requires_its_actor_in_the_assigned_panel(db_session):
    shot = Shot(index=4, description='老妇冲出', characters='["老妇", "老翁"]',
                dialogues=json.dumps([{'speaker': '旁白', 'text': '老妇从屋里冲出来。',
                                       'delivery': 'narration', 'visual_subjects': ['老妇']}], ensure_ascii=False))
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat='门口', camera='中景',
                                          characters=['老妇'] if i == 2 else [],
                                          dialogue_indexes=[1] if i == 1 else []) for i in range(1, 5)])
    assert _dialogues(shot)[0]['visual_subjects'] == ['老妇']
    with pytest.raises(GridPipelineError, match='缺少可见人物'):
        _assert_narration_coverage(shot, grid, [1], [1])
    grid.panels[0].characters = ['老妇']
    _assert_narration_coverage(shot, grid, [1], [1])


def test_legacy_narrator_action_requires_people_visible_in_shot_six():
    shot = Shot(index=6, characters='["老翁", "老妇"]', dialogues=json.dumps([
        {'speaker': '旁白', 'delivery': 'offscreen', 'text': '老翁扶着柴垛，艰难地爬上土墙。'},
        {'speaker': '旁白', 'delivery': 'offscreen', 'text': '他年纪大了，动作十分迟缓。'},
        {'speaker': '旁白', 'delivery': 'offscreen', 'text': '老妇跑过去，在下面托住他的脚。'},
        {'speaker': '旁白', 'delivery': 'offscreen', 'text': '老翁翻过墙头。'},
    ], ensure_ascii=False))
    dialogues = _dialogues(shot)
    assert [line['visual_subjects'] for line in dialogues] == [
        ['老翁'], ['老翁'], ['老妇', '老翁'], ['老翁']]
    assert all(line['delivery'] == 'narration' for line in dialogues)
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat='土墙', camera='近景', dialogue_indexes=[i])
                                for i in range(1, 5)])
    with pytest.raises(GridPipelineError, match='旁白 D1.*老翁'):
        _assert_narration_coverage(shot, grid, [1], [1])
    grid.panels[0].characters = ['老翁']
    _assert_narration_coverage(shot, grid, [1], [1])


def test_revising_legacy_narration_panel_updates_voice_contract(db_session):
    novel = Novel(title='旧旁白修订', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='夜半惊变', content='老翁爬上土墙。')
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=6, characters='["老翁"]', dialogues=json.dumps([
        {'speaker': '旁白', 'delivery': 'offscreen', 'text': '老翁爬上土墙。'}], ensure_ascii=False))
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat='空墙', camera='近景', action='墙下无人',
                                          dialogue_indexes=[1] if i == 1 else [],
                                          image_url=f'/api/files/panel_{i}.png') for i in range(1, 5)])
    shot.grid_data = dump_grid_data(grid)
    db_session.add(shot)
    db_session.commit()
    revised = GridPipeline(db_session).revise_panel(shot, 1, beat='老翁爬墙', camera='中景',
                                                     action='老翁扶柴垛爬墙', characters=['老翁'])
    assert json.loads(shot.dialogues)[0]['delivery'] == 'narration'
    assert json.loads(shot.dialogues)[0]['visual_subjects'] == ['老翁']
    assert revised.panels[0].characters == ['老翁']
    assert revised.panels[0].image_url is None


def test_video_visual_review_rejects_unexpected_person(db_session, monkeypatch, tmp_path):
    novel = Novel(title='成片验收', video_mode='grid')
    chapter = Chapter(title='门口', number=1)
    shot = Shot(index=1, description='空门')
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat='空门', camera='近景') for i in range(1, 5)])
    clip = {'clip_index': 1, 'panel_indexes': [1], 'reference_images': [
        {'picture_index': 1, 'panel_index': 1, 'url': '/api/files/panel.png'}]}
    monkeypatch.setattr('app.services.grid_pipeline.probe_nameplate_video', lambda _path: (1280, 720, 3.0))
    monkeypatch.setattr('app.services.grid_pipeline.extract_review_frame',
                        lambda _video, _time, frame: frame.write_bytes(b'frame'))
    monkeypatch.setattr('app.services.grid_pipeline.local_path_to_url',
                        lambda frame: f'/api/files/{Path(frame).name}')
    monkeypatch.setattr('app.services.grid_pipeline.vision_proxy',
                        lambda _source, **metadata: {'url': 'data:image/jpeg;base64,AA==', **metadata})
    class FakeLLM:
        async def chat_completion(self, **kwargs):
            assert len([image for image in kwargs['images'] if image['role'] == 'generated_video_frame']) == 4
            return {'success': True, 'content': '{"overall":"FAIL","unexpected_people":true,"missing_subjects":[],"summary":"第1帧出现男子"}'}
    evidence_urls = []
    with pytest.raises(GridPipelineError, match='第1帧出现男子'):
        asyncio.run(GridPipeline(db_session, llm=FakeLLM())._review_clip_video(
            novel, chapter, shot, grid, clip, str(tmp_path / 'clip.mp4'), evidence_urls))
    assert len(evidence_urls) == 4


def test_revise_narrated_panel_keeps_unrelated_clip(db_session):
    novel = Novel(title='局部修订', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='夜半', content='老妇从屋里冲出来。')
    db_session.add(chapter)
    db_session.flush()
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        board_image_url='/api/files/board.png',
                        panels=[GridPanel(index=i, beat='空门', camera='中景', action='灯光摇晃',
                                          image_url=f'/api/files/panel_{i}.png', review_status='passed',
                                          dialogue_indexes=[1] if i == 1 else []) for i in range(1, 5)])
    clips = [{'clip_index': i, 'panel_indexes': [i], 'dialogue_indexes': [1] if i == 1 else [],
              'video_url': f'/api/files/clip_{i}.mp4', 'prompt': 'old'} for i in range(1, 5)]
    shot = Shot(chapter_id=chapter.id, index=1, description='老妇冲出',
                characters='["老妇"]', dialogues='[{"speaker":"旁白","text":"老妇从屋里冲出来。","delivery":"narration","visual_subjects":["老妇"]}]',
                grid_data=dump_grid_data(grid), video_director_plan=dump_grid_clip_plan(grid, clips))
    db_session.add(shot)
    db_session.commit()
    pipeline = GridPipeline(db_session)
    with pytest.raises(GridPipelineError, match='缺少可见人物'):
        pipeline.revise_panel(shot, 1, beat='冲出', camera='中景', action='冲出门', characters=[])
    revised = pipeline.revise_panel(shot, 1, beat='老妇冲出', camera='中景', action='老妇冲出门', characters=['老妇'])
    plan = read_grid_clip_plan(shot.video_director_plan, grid_revision=revised.revision)['clip_plan']
    assert revised.panels[0].image_url is None
    assert 'video_url' not in plan[0] and plan[1]['video_url'] == '/api/files/clip_2.mp4'


def test_offscreen_clip_preserves_h3_video_without_asr_gate(db_session, tmp_path, monkeypatch):
    novel = Novel(title='动态画外声', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='门外', content='开门。')
    db_session.add(chapter)
    db_session.flush()
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat='空门', camera='近景',
                                          image_url=f'/api/files/panel_{i}.png', review_status='passed')
                                for i in range(1, 5)])
    refs = [{'picture_index': 1, 'role': 'GRID_PANEL', 'panel_index': 1,
             'url': '/api/files/panel_1.png'}]
    clip = {'clip_index': 1, 'duration': 5, 'panel_indexes': [1],
            'reference_strategy': 'split_panels', 'prompt': 'validated prompt',
            'reference_images': refs, 'dialogues': [{
                'id': 'D1', 'speaker': '门外官差', 'text': '开门！', 'delivery': 'offscreen',
                'voice_description': 'a rough adult male voice outside the door',
                'start_time': 1, 'end_time': 2}], 'prompt_template_snapshot': 'template'}
    shot = Shot(chapter_id=chapter.id, index=1, description='空门', duration=5,
                dialogues=json.dumps([{'speaker': '门外官差', 'text': '开门！',
                                       'delivery': 'offscreen', 'voice_description': 'a rough adult male voice outside the door'}], ensure_ascii=False),
                grid_data=dump_grid_data(grid), video_director_plan=dump_grid_clip_plan(grid, [clip]))
    db_session.add(shot)
    db_session.flush()
    workflow = Workflow(name='H3', type='multi_reference_video', is_active=True,
                        workflow_json='{}', node_mapping='{}')
    db_session.add(workflow)
    db_session.flush()
    task = Task(type='grid_h3_clip', status='running', name='C1', novel_id=novel.id,
                chapter_id=chapter.id, shot_id=shot.id, clip_index=1,
                comfyui_prompt_id='queued-h3', workflow_id=workflow.id,
                workflow_json='{"1": {"class_type": "MiniMaxH3ReferenceToVideo"}}', metadata_json='{}')
    db_session.add(task)
    db_session.commit()

    async def result(*_args, **_kwargs):
        return {'success': True, 'video_url': '/remote/h3.mp4'}

    async def download(*_args, **_kwargs):
        return str(tmp_path / 'h3.mp4')

    monkeypatch.setattr('app.services.grid_pipeline.ComfyUIService',
                        lambda: SimpleNamespace(client=SimpleNamespace(wait_for_result=result)))
    monkeypatch.setattr('app.services.grid_pipeline.validate_grid_h3_prompt',
                        lambda *_args, **_kwargs: {})
    monkeypatch.setattr('app.services.grid_pipeline.url_to_local_path',
                        lambda _url: str(tmp_path / 'panel.png'))
    monkeypatch.setattr('app.services.grid_pipeline.local_path_to_url',
                        lambda path: '/api/files/h3.mp4' if path == str(tmp_path / 'h3.mp4') else None)
    monkeypatch.setattr('app.services.grid_pipeline.file_storage.download_video_receipt', download)
    async def visual_review(*_args, **_kwargs):
        return {'overall': 'PASS', 'summary': '空门无人物', 'missing_subjects': []}
    monkeypatch.setattr(GridPipeline, '_review_clip_video', visual_review)

    generated = asyncio.run(GridPipeline(db_session).generate_clip(novel, chapter, shot, 1, task=task))
    assert generated['videoUrl'] == '/api/files/h3.mp4'
    assert generated['clip']['video_url'] == '/api/files/h3.mp4'
    assert 'offscreen_asr_transcript' not in json.loads(task.metadata_json)


@pytest.mark.parametrize('reject', [False, True])
def test_narrated_clip_records_visual_review_attempts_and_retries_only_errors(
        db_session, tmp_path, monkeypatch, reject):
    from app.services.grid_pipeline import GridVisualReviewError

    novel = Novel(title='验收记录', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='门口', content='老妇出门。')
    db_session.add(chapter)
    db_session.flush()
    grid = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat='老妇出门', camera='近景',
                                          characters=['老妇'] if i == 1 else [],
                                          image_url=f'/api/files/panel_{i}.png', review_status='passed')
                                for i in range(1, 5)])
    dialogue = {'id': 'D1', 'speaker': '旁白', 'text': '老妇出门。', 'delivery': 'narration',
                'visual_subjects': ['老妇']}
    clip = {'clip_index': 1, 'duration': 5, 'panel_indexes': [1],
            'reference_strategy': 'split_panels', 'prompt': 'validated prompt',
            'reference_images': [{'picture_index': 1, 'role': 'GRID_PANEL', 'panel_index': 1,
                                  'url': '/api/files/panel_1.png'}],
            'dialogues': [dialogue], 'prompt_template_snapshot': 'template'}
    shot = Shot(chapter_id=chapter.id, index=1, description='老妇出门', duration=5,
                characters='["老妇"]', dialogues=json.dumps([dialogue], ensure_ascii=False),
                grid_data=dump_grid_data(grid), video_director_plan=dump_grid_clip_plan(grid, [clip]))
    db_session.add(shot)
    db_session.flush()
    workflow = Workflow(name='H3', type='multi_reference_video', is_active=True,
                        workflow_json='{}', node_mapping='{}')
    db_session.add(workflow)
    db_session.flush()
    task = Task(type='grid_h3_clip', status='running', name='C1', novel_id=novel.id,
                chapter_id=chapter.id, shot_id=shot.id, clip_index=1,
                comfyui_prompt_id='queued-h3', workflow_id=workflow.id,
                workflow_json='{"1": {"class_type": "MiniMaxH3ReferenceToVideo"}}', metadata_json='{}')
    db_session.add(task)
    db_session.commit()
    video_calls = []

    async def video_result(*_args, **_kwargs):
        video_calls.append(1)
        return {'success': True, 'video_url': '/remote/h3.mp4'}

    async def download(*_args, **_kwargs):
        return str(tmp_path / 'h3.mp4')

    monkeypatch.setattr('app.services.grid_pipeline.ComfyUIService',
                        lambda: SimpleNamespace(client=SimpleNamespace(wait_for_result=video_result)))
    monkeypatch.setattr('app.services.grid_pipeline.validate_grid_h3_prompt', lambda *_args, **_kwargs: {})
    monkeypatch.setattr('app.services.grid_pipeline.url_to_local_path', lambda _url: str(tmp_path / 'panel.png'))
    monkeypatch.setattr('app.services.grid_pipeline.local_path_to_url',
                        lambda path: '/api/files/h3.mp4' if path == str(tmp_path / 'h3.mp4') else None)
    monkeypatch.setattr('app.services.grid_pipeline.file_storage.download_video_receipt', download)
    review_calls = []

    async def visual_review(*_args, **_kwargs):
        review_calls.append(1)
        if reject:
            raise GridVisualReviewError('成片视觉验收未通过：多余人物', category='rejected',
                                        result={'overall': 'FAIL', 'summary': '多余人物'})
        if len(review_calls) == 1:
            raise GridVisualReviewError('模型暂时不可用', category='execution_error')
        return {'overall': 'PASS', 'summary': '人物正确'}

    monkeypatch.setattr(GridPipeline, '_review_clip_video', visual_review)
    if reject:
        with pytest.raises(GridPipelineError, match='多余人物'):
            asyncio.run(GridPipeline(db_session).generate_clip(novel, chapter, shot, 1, task=task))
    else:
        asyncio.run(GridPipeline(db_session).generate_clip(novel, chapter, shot, 1, task=task))
    db_session.refresh(task)
    events = json.loads(task.metadata_json)['visual_review_attempts']
    assert len(video_calls) == 1
    assert len(events) == (1 if reject else 2)
    assert events[0]['category'] == ('rejected' if reject else 'execution_error')
    assert events[-1]['category'] == ('rejected' if reject else 'accepted')
    assert task.status == ('failed' if reject else 'completed')


def test_wrong_mode_and_wrong_template_cannot_start_grid(client, db_session):
    single = client.post('/api/novels/', json={'title': '单镜'})
    novel_id = single.json()['data']['id']
    chapter = Chapter(novel_id=novel_id, number=1, title='章', content='正文')
    db_session.add(chapter)
    db_session.commit()
    assert client.post(f'/api/novels/{novel_id}/chapters/{chapter.id}/grid/plan').status_code == 409
    bad = client.post('/api/novels/', json={'title': '错误绑定', 'videoMode': 'grid', 'chapterSplitPromptTemplateId': 'old'})
    assert bad.status_code == 422


def test_single_video_write_routes_reject_grid_before_changing_plan_or_queue(client, db_session):
    novel = Novel(title='宫格旧入口保护', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='章', content='正文')
    db_session.add(chapter)
    db_session.flush()
    plan = json.dumps({'contract': 'GRID_CLIP_PLAN_V1', 'clip_plan_revision': 1,
                       'clip_plan': [{'clip_index': 1}]})
    shot = Shot(chapter_id=chapter.id, index=1, description='宫格镜头', duration=5,
                video_director_plan=plan)
    db_session.add(shot)
    db_session.commit()
    base = f'/api/novels/{novel.id}/chapters/{chapter.id}'
    requests = [
        client.patch(f'{base}/shots/{shot.id}/video-director', json={'validation': {'passed': True}}),
        client.post(f'{base}/shots/{shot.id}/video-director/plan-clips', json={}),
        client.post(f'{base}/shots/{shot.id}/video-director/plan-keyframes', json={}),
        client.post(f'{base}/shots/{shot.id}/video-director/clips/1/generate',
                    json={'clip_plan_revision': 1}),
        client.post(f'{base}/shots/{shot.id}/video-director/clips/merge'),
        client.post(f'{base}/shots/{shot.id}/auto-generation/start', json={}),
        client.post(f'{base}/shot-videos/batch', json={'shot_ids': [shot.id]}),
        client.post(f'{base}/shot-videos/batch/preflight', json={'shot_ids': [shot.id]}),
        client.post(f'{base}/shot-images/batch', json={'shot_ids': [shot.id]}),
        client.post(f'{base}/transitions/batch', json={}),
    ]
    assert all(response.status_code == 409 for response in requests)
    db_session.refresh(shot)
    assert shot.video_director_plan == plan
    from app.models.task import Task
    assert db_session.query(Task).count() == 0


def test_single_video_plan_route_remains_available(client, db_session):
    novel = Novel(title='单镜旧入口', video_mode='single')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='章', content='正文')
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description='单镜', duration=5)
    db_session.add(shot)
    db_session.commit()
    response = client.patch(
        f'/api/novels/{novel.id}/chapters/{chapter.id}/shots/{shot.id}/video-director',
        json={'validation': {'passed': True}},
    )
    assert response.status_code == 200
    assert response.json()['data']['validation'] == {'passed': True}


@pytest.mark.parametrize(('layout', 'source_size'), [
    ('2x2', (1536, 864)), ('2x2', (1536, 1024)), ('2x3', (1800, 1024)),
])
def test_board_generation_crops_in_reading_order_and_keeps_legacy_image_empty(
        db_session, tmp_path, monkeypatch, layout, source_size):
    import io
    from pathlib import Path
    from PIL import Image
    from app.models.task import Task
    from app.models.workflow import Workflow
    from app.services.file_storage import file_storage
    from app.schemas.grid_shot import GridPanel, GridShotData

    db_session.add(PromptTemplate(name='Grid Image', type='grid_image_prompt', template='grid image template', is_system=True, is_active=True))
    workflow = Workflow(name='test image', type='shot', is_active=True,
                        workflow_json=json.dumps({'w': {'class_type': 'INTConstant', 'inputs': {'value': 1280}},
                                                  'h': {'class_type': 'INTConstant', 'inputs': {'value': 720}}}),
                        node_mapping=json.dumps({'width_node_id': 'w', 'height_node_id': 'h',
                                                 'prompt_node_id': 'p', 'save_image_node_id': 's'}))
    novel = Novel(title='宫格', video_mode='grid')
    db_session.add_all([workflow, novel])
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='章', content='正文')
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, description='四格', duration=8)
    rows, cols = map(int, layout.split('x'))
    grid = GridShotData(revision=1, layout=layout, seed=42, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat=f'Beat {i}', camera='近景') for i in range(1, rows * cols + 1)])
    shot.grid_data = dump_grid_data(grid)
    db_session.add(shot)
    db_session.commit()

    async def complete(**kwargs):
        return {'success': True, 'content': 'Four equal cinematic panels; no text.'}

    image = Image.new('RGB', source_size)
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255),
              (255, 255, 0), (255, 0, 255), (0, 255, 255)][:rows * cols]
    for i, color in enumerate(colors):
        col, row = i % cols, i // cols
        box = (round(col * source_size[0] / cols), round(row * source_size[1] / rows),
               round((col + 1) * source_size[0] / cols), round((row + 1) * source_size[1] / rows))
        image.paste(color, box)
    output = io.BytesIO()
    image.save(output, format='PNG')

    class FakeClient:
        async def upload_image(self, path):
            return {'success': True, 'filename': 'uploaded.png'}

    class FakeBuilder:
        def build_shot_workflow(self, prompt, workflow_json, mapping, **kwargs):
            return json.loads(workflow_json)

    class FakeComfy:
        def __init__(self):
            self.builder, self.client = FakeBuilder(), FakeClient()
        async def generate_shot_image_with_workflow(self, **kwargs):
            assert kwargs['workflow']['w']['inputs']['value'] == cols * 768
            assert kwargs['workflow']['h']['inputs']['value'] == 864
            kwargs['on_prompt_queued']('prompt-1', kwargs['workflow'])
            return {'success': True, 'image_url': 'http://comfy/image.png'}

    class FakeResponse:
        content = output.getvalue()
        def raise_for_status(self): pass
    class FakeHttpClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url): return FakeResponse()

    monkeypatch.setattr('app.services.grid_pipeline.ComfyUIService', FakeComfy)
    monkeypatch.setattr('app.services.grid_pipeline.httpx.AsyncClient', FakeHttpClient)
    monkeypatch.setattr(file_storage, 'base_dir', tmp_path)
    pipeline = GridPipeline(db_session, SimpleNamespace(chat_completion=complete))
    asyncio.run(pipeline.prepare_board(novel, chapter, shot))
    asyncio.run(pipeline.generate_board(novel, chapter, shot))
    generated = load_grid_data(shot.grid_data)
    assert shot.image_url is None
    assert generated.board_image_url and all(p.image_url for p in generated.panels)
    board_path = Path(tmp_path) / generated.board_image_url.removeprefix('/api/files/')
    with Image.open(board_path) as saved_board:
        assert saved_board.size == (cols * 768, rows * 432)
        for i, color in enumerate(colors):
            assert saved_board.getpixel(((i % cols) * 768 + 384, (i // cols) * 432 + 216)) == color
    for panel, color in zip(generated.panels, colors):
        path = Path(tmp_path) / panel.image_url.removeprefix('/api/files/')
        with Image.open(path) as saved_panel:
            assert saved_panel.size == (768, 432)
            assert saved_panel.getpixel((384, 216)) == color
    task = db_session.query(Task).filter(Task.type == 'grid_board_image').one()
    assert task.prompt_text == 'Four equal cinematic panels; no text.'
    metadata = json.loads(task.metadata_json)
    assert metadata['grid_revision'] == 1
    if source_size != (cols * 768, rows * 432):
        assert metadata['board_size_normalization'] == {
            'source': list(source_size), 'saved': [cols * 768, rows * 432],
            'method': 'split_panels_then_resize'}
    else:
        assert 'board_size_normalization' not in metadata


def test_panel_retry_submits_supported_size_and_stores_grid_size(db_session, tmp_path, monkeypatch):
    import io
    from pathlib import Path
    from PIL import Image
    from app.models.task import Task
    from app.services.file_storage import file_storage

    workflow = Workflow(name='panel image', type='shot', is_active=True,
                        workflow_json=json.dumps({'w': {'class_type': 'easy int', 'inputs': {'value': 768}},
                                                  'h': {'class_type': 'easy int', 'inputs': {'value': 432}}}),
                        node_mapping=json.dumps({'width_node_id': 'w', 'height_node_id': 'h',
                                                 'save_image_node_id': 's'}))
    novel = Novel(title='单格尺寸', video_mode='grid')
    db_session.add_all([workflow, novel])
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='章', content='正文')
    db_session.add(chapter)
    db_session.flush()
    grid = GridShotData(revision=1, layout='2x2', seed=42, panel_width=768, panel_height=432,
                        board_image_url='/api/files/board.png',
                        panels=[GridPanel(index=i, beat=f'Beat {i}', camera='近景') for i in range(1, 5)])
    shot = Shot(chapter_id=chapter.id, index=1, description='单格', duration=8,
                grid_data=dump_grid_data(grid))
    db_session.add(shot)
    db_session.commit()

    image = io.BytesIO()
    Image.new('RGB', (1280, 720), (12, 34, 56)).save(image, format='PNG')

    class FakeBuilder:
        def build_shot_workflow(self, prompt, workflow_json, mapping, **kwargs):
            return json.loads(workflow_json)

    class FakeComfy:
        def __init__(self):
            self.builder = FakeBuilder()
        async def generate_shot_image_with_workflow(self, **kwargs):
            graph = kwargs['workflow']
            assert (graph['w']['inputs']['value'], graph['h']['inputs']['value']) == (1280, 720)
            kwargs['on_prompt_queued']('prompt-panel', graph)
            return {'success': True, 'image_url': 'http://comfy/panel.png'}

    class FakeResponse:
        content = image.getvalue()
        def raise_for_status(self): pass

    class FakeHttpClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url): return FakeResponse()

    monkeypatch.setattr('app.services.grid_pipeline.ComfyUIService', FakeComfy)
    monkeypatch.setattr('app.services.grid_pipeline.httpx.AsyncClient', FakeHttpClient)
    monkeypatch.setattr(file_storage, 'base_dir', tmp_path)
    pipeline = GridPipeline(db_session)
    assert pipeline.prepare_panel_retry(novel, shot, 1)['size'] == [1280, 720]
    asyncio.run(pipeline.generate_panel_retry(novel, chapter, shot, 1))
    panel = load_grid_data(shot.grid_data).panels[0]
    with Image.open(Path(tmp_path) / panel.image_url.removeprefix('/api/files/')) as saved:
        assert saved.size == (768, 432)
    task = db_session.query(Task).filter(Task.type == 'grid_panel_image').one()
    submitted = json.loads(task.workflow_json)
    assert (submitted['w']['inputs']['value'], submitted['h']['inputs']['value']) == (1280, 720)


def test_grid_chapter_stats_and_novel_cover_use_board_without_changing_single(client, db_session):
    from app.schemas.grid_shot import GridPanel, GridShotData

    grid_response = client.post('/api/novels/', json={'title': '宫格统计', 'videoMode': 'grid'})
    grid_id = grid_response.json()['data']['id']
    old_response = client.post('/api/novels/', json={'title': '单镜统计'})
    old_id = old_response.json()['data']['id']
    grid_chapter = Chapter(novel_id=grid_id, number=1, title='宫格章', content='正文')
    old_chapter = Chapter(novel_id=old_id, number=1, title='单镜章', content='正文')
    db_session.add_all([grid_chapter, old_chapter])
    db_session.flush()
    board = GridShotData(revision=1, layout='2x2', seed=1, panel_width=768, panel_height=432,
                         panels=[GridPanel(index=i, beat=f'Beat {i}', camera='近景',
                                           review_status='passed', image_url=f'/api/files/p{i}.png')
                                 for i in range(1, 5)],
                         board_image_url='/api/files/board.png')
    db_session.add_all([
        Shot(chapter_id=grid_chapter.id, index=1, description='宫格', grid_data=dump_grid_data(board)),
        Shot(chapter_id=old_chapter.id, index=1, description='单镜', image_url='/api/files/old.png'),
    ])
    db_session.commit()
    grid_stats = client.get(f'/api/novels/{grid_id}/chapters').json()['data'][0]
    old_stats = client.get(f'/api/novels/{old_id}/chapters').json()['data'][0]
    assert grid_stats['shotImageStats']['generated'] == 1
    assert grid_stats['shotImageStats']['passed'] == 1
    assert grid_stats['firstShotImageUrl'] == '/api/files/board.png'
    assert old_stats['shotImageStats']['generated'] == 1
    assert old_stats['firstShotImageUrl'] == '/api/files/old.png'
    novels = {item['id']: item for item in client.get('/api/novels/').json()['data']}
    assert novels[grid_id]['cover'] == '/api/files/board.png'
    assert novels[old_id]['cover'] == '/api/files/old.png'


def test_multiple_character_sheets_become_one_visible_identity_reference(db_session, tmp_path, monkeypatch):
    from PIL import Image
    from app.models.novel import Character
    from app.services.file_storage import file_storage
    from app.services.grid_pipeline import _asset_refs

    novel = Novel(title='双人场面', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='章')
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1, characters=json.dumps(['甲', '乙'], ensure_ascii=False))
    db_session.add_all([shot, Character(novel_id=novel.id, name='甲', image_url='/api/files/a.png'),
                        Character(novel_id=novel.id, name='乙', image_url='/api/files/b.png')])
    db_session.commit()
    for name, color in [('a', 'red'), ('b', 'blue')]:
        Image.new('RGB', (128, 128), color).save(tmp_path / f'{name}.png')
    monkeypatch.setattr(file_storage, 'base_dir', tmp_path)
    monkeypatch.setattr('app.services.grid_pipeline.url_to_local_path',
                        lambda url: str(tmp_path / url.rsplit('/', 1)[-1]))
    monkeypatch.setattr('app.services.grid_pipeline.local_path_to_url',
                        lambda path: f'/api/files/{path.rsplit("/", 1)[-1]}')
    refs = _asset_refs(db_session, novel, shot)
    again = _asset_refs(db_session, novel, shot)
    assert len(refs) == 1 and refs == again
    assert refs[0]['role'] == 'CHARACTER_IDENTITY'
    assert refs[0]['name'] == '甲、乙'
    assert refs[0]['url'].endswith('_characters.png')


def test_grid_qwen_uses_separate_speakers_and_owned_props(db_session, tmp_path, monkeypatch):
    from PIL import Image
    from app.models.novel import Character, Scene, Prop
    from app.services.grid_pipeline import _grid_asset_refs, _board_bindings, _panel_asset_refs, _picture_roles

    novel = Novel(title='反打场面', video_mode='grid')
    db_session.add(novel)
    db_session.flush()
    chapter = Chapter(novel_id=novel.id, number=1, title='章')
    db_session.add(chapter)
    db_session.flush()
    shot = Shot(chapter_id=chapter.id, index=1,
                characters=json.dumps(['杜甫', '老妇', '老翁'], ensure_ascii=False),
                dialogues=json.dumps([{'speaker': '老翁', 'text': '请进'},
                                      {'speaker': '杜甫', 'text': '多谢'}], ensure_ascii=False),
                scene='前院',
                props=json.dumps(['木门', '杜甫的行囊', '老翁木杖'], ensure_ascii=False))
    db_session.add_all([shot, *[Character(novel_id=novel.id, name=name, image_url=f'/api/files/{name}.png')
                               for name in ('杜甫', '老妇', '老翁')],
                        Scene(novel_id=novel.id, name='前院', image_url='/api/files/前院.png'),
                        *[Prop(novel_id=novel.id, name=name, image_url=f'/api/files/{name}.png')
                          for name in ('木门', '杜甫的行囊', '老翁木杖')]])
    db_session.commit()
    for name in ('杜甫', '老妇', '老翁', '前院', '木门', '杜甫的行囊', '老翁木杖'):
        Image.new('RGB', (8, 8), 'grey').save(tmp_path / f'{name}.png')
    monkeypatch.setattr('app.services.grid_pipeline.url_to_local_path',
                        lambda url: str(tmp_path / url.rsplit('/', 1)[-1]))
    graph = {'470': {'class_type': 'LoadImage', 'inputs': {'image': ''}},
             '510': {'class_type': 'LoadImage', 'inputs': {'image': ''}},
             '503': {'class_type': 'LoadImage', 'inputs': {'image': ''}},
             '485': {'class_type': 'TextEncodeQwenImage21',
                     'inputs': {'images.image_1': ['470', 0], 'images.image_2': ['510', 0],
                                'images.image_3': ['503', 0]}}}
    mapping = {'character_reference_image_node_id': '470', 'scene_reference_image_node_id': '510',
               'custom_reference_image_node_1': '503'}
    refs = _grid_asset_refs(db_session, novel, shot, graph)
    assert [ref['name'] for ref in refs] == ['杜甫', '老翁', '老妇', '前院', '杜甫的行囊', '老翁木杖']
    bindings = _board_bindings(refs, mapping, graph)
    assert len(bindings) == 6
    assert [graph['485']['inputs'][f'images.image_{i}'][0] for i in range(1, 7)] == [
        node_id for node_id, _ in bindings]
    assert all(graph[node_id]['class_type'] == 'LoadImage' for node_id, _ in bindings)
    assert 'Picture 2: CHARACTER_IDENTITY — 老翁' in _picture_roles(refs)
    panel = GridPanel(index=1, beat='杜甫反打老翁', camera='过肩近景', characters=['杜甫', '老翁'])
    assert [ref['name'] for ref in _panel_asset_refs(refs, panel)] == [
        '杜甫', '老翁', '前院', '杜甫的行囊', '老翁木杖']
