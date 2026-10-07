"""Continuation mux packet preservation and physical anchor bounds."""
import os
from pathlib import Path
import shutil

import httpx
import pytest

from app.services import continuous_clip_av as av, native_av_mux as mux
from test_continuous_clip_native_av import physical


def result():
    return {"physical_output_role": av.NATIVE_CONTINUITY_OUTPUT, "output_node_id": "65",
            "video_url": "http://comfy/view?filename=clip_00001-audio.mp4&subfolder=story%2Fclips&type=output"}


def test_video_only_source_is_same_node65_filename_counter_and_subfolder():
    assert mux.native_video_only_url(result()) == "http://comfy/view?filename=clip_00001.mp4&subfolder=story%2Fclips&type=output"


@pytest.mark.parametrize('change', [
    {'output_node_id': '39'}, {'physical_output_role': 'RAW_CONTEXT_OUTPUT'},
    {'video_url': 'http://comfy/view?filename=clip.mp4&type=output'},
    {'video_url': 'http://comfy/view?filename=clip-audio.mp4&type=input'},
    {'video_url': 'http://comfy/view?filename=a-audio.mp4&filename=b-audio.mp4&type=output'},
])
def test_wrong_or_ambiguous_mux_source_is_rejected(change):
    with pytest.raises(ValueError, match='NATIVE_AV_MUX_INPUT_UNAVAILABLE'):
        mux.native_video_only_url({**result(), **change})


@pytest.mark.asyncio
async def test_missing_video_only_fails_without_replacing_original_or_retry(tmp_path, monkeypatch):
    original=tmp_path/'native.mp4';original.write_bytes(b'original');calls=[]
    def get(request):
        calls.append(str(request.url));return httpx.Response(404)
    client=httpx.AsyncClient(transport=httpx.MockTransport(get))
    monkeypatch.setattr(mux.httpx, 'AsyncClient', lambda: client)
    monkeypatch.setattr(mux, 'remux_native_av', lambda *_: pytest.fail('Missing input must not be repaired'))
    with pytest.raises(ValueError,match='NATIVE_AV_MUX_INPUT_UNAVAILABLE'):
        await mux.preserve_native_av(result(),str(original))
    assert original.read_bytes()==b'original' and len(calls)==1
    assert list(tmp_path.iterdir())==[original]


@pytest.mark.asyncio
async def test_download_pairs_only_node65_input_and_cleans_temporary_file(tmp_path,monkeypatch):
    output=tmp_path/'native.mp4';output.write_bytes(b'existing AV');requests=[]
    def get(request):
        requests.append(str(request.url));return httpx.Response(200,content=b'paired video-only')
    client=httpx.AsyncClient(transport=httpx.MockTransport(get))
    monkeypatch.setattr(mux.httpx,'AsyncClient',lambda:client)
    def remux(video_only,av_path):
        assert Path(video_only).read_bytes()==b'paired video-only' and av_path==str(output)
        return {'frames_after':532}
    monkeypatch.setattr(mux,'remux_native_av',remux)
    proof=await mux.preserve_native_av(result(),str(output))
    assert requests==[mux.native_video_only_url(result())]
    assert proof['video_only_source_url']==requests[0] and proof['frames_after']==532
    assert list(tmp_path.iterdir())==[output]


@pytest.mark.parametrize('clip,expected',[(2,532),(3,784)])
def test_existing_native_artifact_remux_preserves_video_and_audio_packets(clip,expected,tmp_path):
    evidence=os.environ.get('NOVELFLOW_NATIVE_MUX_ARTIFACT_DIR')
    if not evidence:pytest.skip('Set NOVELFLOW_NATIVE_MUX_ARTIFACT_DIR to existing Phase2.6 artifacts')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('ffmpeg/ffprobe required')
    video=Path(evidence)/f'C{clip}-node65-video-only.mp4';source=Path(evidence)/f'C{clip}-node65-av.mp4'
    output=tmp_path/'native.mp4';shutil.copyfile(source,output)
    proof=mux.remux_native_av(str(video),str(output))
    assert proof['frames_after']==expected
    assert proof['video_packets_timestamps_preserved'] and proof['audio_packets_timestamps_preserved']
    assert av.probe_clip_av(str(output))['frame_count']==expected


def test_video_provenance_mismatch_leaves_original_untouched(monkeypatch,tmp_path):
    path=tmp_path/'native.mp4';path.write_bytes(b'original')
    monkeypatch.setattr(mux,'probe_clip_av',lambda p:{**physical(532 if p=='video-only' else 529),
                                                    'has_audio':p!='video-only','audio_duration':532/24})
    monkeypatch.setattr(mux,'_packets',lambda p,s:[{'data_hash':'correct' if p=='video-only' else 'wrong'}])
    with pytest.raises(ValueError,match='NATIVE_AV_MUX_VIDEO_PROVENANCE_INVALID'):
        mux.remux_native_av('video-only',str(path))
    assert path.read_bytes()==b'original'
