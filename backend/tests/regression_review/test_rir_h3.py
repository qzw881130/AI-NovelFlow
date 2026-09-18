import json
import pytest
from app.services.video_director_ai import prepare_h3_prompt

CONSTRAINT='The input drive_audio is only for visible lip-sync. Never transcribe drive_audio. Spoken audio must remain audio only. Do not render audio as text. No subtitles, no captions, no audio transcription.'


def prepare(body):
    document={'subject_definitions':{'<Subject 1>':'the grey wolf','<Subject 2>':'the sheep'},
        'initial_state_anchor':'Both subjects stand in the meadow.', 'summary':'Hold the same shot.',
        'detailed_description':body,'overall_soundscape':'Use final_audio without modification.'}
    return prepare_h3_prompt(json.dumps(document),constraint=CONSTRAINT,continuity_lock='',
        subject_manifest={'subjects':[{'subject_ref':'<Subject 1>'},{'subject_ref':'<Subject 2>'}]},
        speaker_timeline=[{'start_time':0,'end_time':8,'visible_speaker':'NONE'}])


@pytest.mark.parametrize('body',[
    'NONE. No visible animal speaks except <Subject 1>.',
    'NONE. No visible subject has lip-sync except <Subject 1>.',
    'NONE. Except for <Subject 1>, no visible animal speaks.',
    'NONE. No visible animal speaks, but <Subject 1> speaks.',
    'NONE. No visible subject has lip-sync while <Subject 1> speaks.',
    'visible_speaker=NONE\n<Subject 1> speaks throughout the entire clip.',
    'visible_speaker=NONE; <Subject 2> lip-syncs throughout the entire clip.',
    'visible_speaker=NONE\n<Subject 1>\nspeaks throughout the entire clip.',
    'NONE. No visible animal speaks\nexcept <Subject 1>.',
])
def test_rir008_full_prepare_rejects_speech_exceptions_and_cross_line_actions(body):
    with pytest.raises(RuntimeError,match='AUDIODRIVE_AUDIT_FAILED'):prepare(body)


@pytest.mark.parametrize('body',[
    'NONE. No visible character or animal produces lip-sync movement.',
    'visible_speaker=NONE\n<Subject 1> does not speak and never lip-syncs.',
    'NONE. No visible animal speaks; all remain silent.',
    'NONE. All remain still except <Subject 1>, who waves silently.',
    'NONE. No visible animal speaks. All remain still except <Subject 1>, who waves silently.',
    'visible_speaker=NONE\n<Subject 1>\ndoes not speak and never lip-syncs.',
])
def test_rir008_full_prepare_accepts_true_silence_and_non_speech_exception(body):
    result=prepare(body);assert result['passed'] and result['profile']=='director_json'
