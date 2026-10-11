"""Preserve original Clip playback after remote-history eviction."""
import json
from pathlib import Path
import pytest
from app.services import clip_playback as playback
from test_semantic_clip_assembly import _assembly_fixture

@pytest.mark.asyncio
@pytest.mark.parametrize('receipt_state, expected_error', [
    ('saved', None),
    ('missing', 'RAW_CLIP_RECEIPT_UNAVAILABLE'),
    ('wrong_prompt', 'CLIP_PLAYBACK_RECEIPT_MISMATCH'),
    ('wrong_workflow', 'CLIP_PLAYBACK_RECEIPT_MISMATCH'),
    ('missing_output', 'RAW_CLIP_OUTPUT_UNAVAILABLE'),
])
async def test_raw_receipt_or_cumulative_availability(db_session, tmp_path, monkeypatch, receipt_state, expected_error):
    novel, chapter, shot, tasks, clips = _assembly_fixture(db_session, tmp_path, monkeypatch)
    task = tasks[2]
    graph = {'39': {'class_type': 'VHS_VideoCombine', 'inputs': {}}}
    task.workflow_json = json.dumps(graph); task.comfyui_prompt_id = 'actual-prompt'
    metadata = json.loads(task.metadata_json)
    history = {'prompt': [0, 'actual-prompt', graph], 'outputs': {'39': {'gifs': []}}}
    if receipt_state == 'wrong_prompt': history['prompt'][1] = 'another-prompt'
    if receipt_state == 'wrong_workflow': history['prompt'][2] = {'different': {}}
    if receipt_state == 'missing_output': history['outputs'] = {}
    if receipt_state != 'missing': metadata['comfyui_history'] = history
    task.metadata_json = json.dumps(metadata); db_session.commit()
    class Client:
        base_url = 'http://comfy'
        def _parse_outputs(self, *args, **kwargs):
            return {'video_url': 'http://comfy/view?filename=raw-audio.mp4&type=output'}
    monkeypatch.setattr(playback.ComfyUIClient, 'for_product_runtime', lambda db: Client())
    calls = []
    class HTTP:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            calls.append(url)
            class Reply:
                content = b'original raw media'
                def raise_for_status(self): pass
                def json(self): return {}
            return Reply()
    monkeypatch.setattr(playback.httpx, 'AsyncClient', lambda **kw: HTTP())
    monkeypatch.setattr(playback, 'remux_native_av', lambda *args: {})
    span = metadata['physical_output']['assembly_span']
    monkeypatch.setattr(playback, 'probe_clip_av', lambda path: {'frame_count': span['end_frame']-span['start_frame']})
    monkeypatch.setattr(playback, 'local_path_to_url', lambda path: str(path))
    monkeypatch.setattr(playback, 'url_to_local_path', lambda url: str(tmp_path / Path(url).name) if url.startswith('/api/files/') else url)
    exports = []
    async def export(projection, output):
        exports.append(projection)
        Path(output).write_bytes(b'review derivative')
        return {'success': True, 'physical_output': {'frame_count': projection['frame_count']}}
    monkeypatch.setattr(playback.file_storage, 'merge_continuous_clip_spans', export)
    result = await playback.clip_playback(db_session, shot, 2, novel.id, chapter.id)
    assert result['cumulative_url'] == task.result_url
    if receipt_state == 'saved':
        assert result['independent_url'].endswith('/independent.mp4')
        assert not any('/history/' in u for u in calls)
        assert result['includes_shared_context']
        assert result['review_url'] is None
        assert exports == []
    else:
        assert result['independent_url'] is None
        assert result['independent_error'] == expected_error
        assert len(calls) == (1 if receipt_state == 'missing' else 0)
        if receipt_state in {'missing', 'missing_output'}:
            assert result['review_url'] != result['cumulative_url']
            assert 'cumulative_excerpt_' in result['review_url']
            assert exports[0]['spans'][0]['start_frame'] == span['start_frame']
            assert exports[0]['spans'][0]['end_frame'] == span['end_frame']
            assert result['review_provenance']['is_original_clip'] is False
            assert result['review_provenance']['overlap_frames'] == 39
            assert result['review_provenance']['overlap_already_blended'] is True
            assert result['review_provenance']['source_sha256'] == metadata['physical_output']['sha256']
        else:
            assert result['review_url'] is None
            assert exports == []
    # Reading playback only adds its metadata; all generation evidence is intact.
    db_session.refresh(task)
    after = json.loads(task.metadata_json)
    assert {k: v for k, v in after.items() if k != 'clip_playback'} == metadata
    assert task.workflow_json == json.dumps(graph)
    from app.services.task_service import TaskService
    listed = TaskService.format_task_list([task], {novel.id: novel}, {chapter.id: chapter}, {}, {shot.id: shot})
    assert listed[0]['clipExecution']['clip_playback'] == result
    if receipt_state == 'missing':
        again = await playback.clip_playback(db_session, shot, 2, novel.id, chapter.id)
        assert again == result
        assert len(exports) == 1
        assert len(calls) == 1


@pytest.mark.parametrize('change', ['start_frame', 'end_frame', 'overlap_frames'])
def test_review_does_not_use_unverified_boundary(db_session, tmp_path, monkeypatch, change):
    _, _, _, tasks, _ = _assembly_fixture(db_session, tmp_path, monkeypatch)
    metadata = json.loads(tasks[2].metadata_json)
    physical = metadata['physical_output']
    if change == 'overlap_frames': physical[change] = 0
    else: physical['assembly_span'][change] += 1
    with pytest.raises(ValueError, match='CLIP_REVIEW_BOUNDARY_MISMATCH'):
        playback._review_projection(metadata, str(tmp_path / 'c2.mp4'), tasks[2].id)


@pytest.mark.asyncio
async def test_review_extracts_shared_context_with_synchronized_audio(tmp_path):
    import subprocess
    from app.services.continuous_clip_av import probe_clip_av
    source = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x96:rate=24:duration=4',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=4',
                    '-c:v', 'libx264', '-c:a', 'aac', str(source)], check=True)
    original = probe_clip_av(str(source))
    metadata = {'physical_output': {**original, 'previous': {'physical_output': {'frame_count': 55}},
                 'overlap_frames': 39, 'assembly_span': {'start_frame': 16, 'end_frame': 96}}}
    projection = playback._review_projection(metadata, source, 'task')
    result = await playback.file_storage.merge_continuous_clip_spans(projection, str(tmp_path / 'review.mp4'))
    assert result['success'], result
    media = result['physical_output']
    assert media['frame_count'] == 80  # 39 shared frames + 41 new frames, exactly once.
    assert media['fps'] == 24
    assert media['audio_start_time'] == 0
    assert abs(media['audio_duration'] - 80 / 24) < 1 / 24
    assert 'trim=start_frame=16:end_frame=96' in result['filter_complex']
    assert probe_clip_av(str(source)) == original
