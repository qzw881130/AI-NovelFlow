"""Focused Stage 6 API and planning checks; generation is covered at Stage 8."""
import asyncio
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.models.novel import Chapter, Character, Novel
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.models.workflow import Workflow
from app.schemas.grid_shot import GridPanel, GridShotData, dump_grid_clip_plan, dump_grid_data, load_grid_data, read_grid_clip_plan
from app.services.grid_pipeline import GridPipeline, GridPipelineError, _h3_bindings, _render_offscreen_clip_visual
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
            {'index': i, 'visible_characters': ['老翁'] if i == 1 else [],
             'dialogue_ids': ['D1'] if i == 1 else []}
            for i in range(1, 5)
        ]}, 'template'
    monkeypatch.setattr(GridPipeline, '_ask', fake_ask)
    with pytest.raises(GridPipelineError, match='画外台词期间不得出现人物'):
        asyncio.run(GridPipeline(db_session).plan_panels(novel, chapter, shot, '2x2'))


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg unavailable')
def test_offscreen_clip_keeps_audio_and_freezes_approved_visual(tmp_path):
    from PIL import Image

    image = tmp_path / 'empty_door.png'
    Image.new('RGB', (320, 180), (87, 54, 32)).save(image)
    source, output = tmp_path / 'h3.mp4', tmp_path / 'safe.mp4'
    subprocess.run([
        'ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=24',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=32000', '-t', '1',
        '-c:v', 'libx264', '-c:a', 'aac', str(source),
    ], check=True, timeout=30)
    _render_offscreen_clip_visual(str(source), str(image), str(output))
    metadata = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'json', str(output),
    ], text=True))
    assert {row['codec_type'] for row in metadata['streams']} == {'video', 'audio'}
    frame_hashes = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-i', str(output), '-map', '0:v:0',
        '-vf', 'select=eq(n\\,0)+eq(n\\,20),format=rgb24', '-vsync', '0', '-f', 'framemd5', '-',
    ], text=True)
    assert len({line.rsplit(',', 1)[-1].strip() for line in frame_hashes.splitlines()
                if line and not line.startswith('#')}) == 1


@pytest.mark.parametrize('transcript,valid', [
    ('开门！官府查丁，各家开门。', True),
    ('开门！各家开门。', False),
])
def test_offscreen_audio_is_checked_against_original_dialogue(db_session, tmp_path, monkeypatch,
                                                              transcript, valid):
    workflow = Workflow(name='ASR', type='audio_transcription', is_active=True,
                        workflow_json=json.dumps({'12': {'inputs': {'audio': 'sample.flac'}}}),
                        node_mapping=json.dumps({'load_audio_node_id': '12', 'text_output_node_id': '13'}))
    db_session.add(workflow)
    db_session.commit()
    def fake_run(command, **_kwargs):
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('app.services.grid_pipeline.subprocess.run', fake_run)
    class FakeClient:
        async def upload_audio(self, _path):
            return {'success': True, 'filename': 'speech.flac'}
        async def queue_prompt(self, graph):
            assert graph['12']['inputs']['audio'] == 'speech.flac'
            return {'success': True, 'prompt_id': 'asr-prompt'}
        async def wait_for_text_outputs(self, _id, _nodes, **_kwargs):
            return {'success': True, 'outputs': {'13': transcript}}
    dialogues = [{'text': '开门！'}, {'text': '官府查丁！各家开门！'}]
    call = GridPipeline(db_session)._verify_offscreen_audio(SimpleNamespace(client=FakeClient()),
                                                            str(tmp_path / 'h3.mp4'), dialogues)
    if valid:
        assert asyncio.run(call) == transcript
    else:
        with pytest.raises(GridPipelineError, match='台词与原文不一致'):
            asyncio.run(call)


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


def test_board_generation_crops_in_reading_order_and_keeps_legacy_image_empty(db_session, tmp_path, monkeypatch):
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
    grid = GridShotData(revision=1, layout='2x2', seed=42, panel_width=768, panel_height=432,
                        panels=[GridPanel(index=i, beat=f'Beat {i}', camera='近景') for i in range(1, 5)])
    shot.grid_data = dump_grid_data(grid)
    db_session.add(shot)
    db_session.commit()

    async def complete(**kwargs):
        return {'success': True, 'content': 'Four equal cinematic panels; no text.'}

    image = Image.new('RGB', (1536, 864))
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    for i, color in enumerate(colors):
        x, y = (i % 2) * 768, (i // 2) * 432
        image.paste(color, (x, y, x + 768, y + 432))
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
            assert kwargs['workflow']['w']['inputs']['value'] == 1536
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
    for panel, color in zip(generated.panels, colors):
        path = Path(tmp_path) / panel.image_url.removeprefix('/api/files/')
        assert Image.open(path).getpixel((384, 216)) == color
    task = db_session.query(Task).filter(Task.type == 'grid_board_image').one()
    assert task.prompt_text == 'Four equal cinematic panels; no text.'
    assert json.loads(task.metadata_json)['grid_revision'] == 1


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
