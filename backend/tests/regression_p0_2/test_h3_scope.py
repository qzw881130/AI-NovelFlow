import json
import pytest
from app.services.video_director_ai import prepare_h3_prompt
from regression_review.test_rir_h3 import CONSTRAINT


def prepare(body,mixed=False):
    document={'subject_definitions':{'<Subject 1>':'the grey wolf','<Subject 2>':'the sheep'},
        'initial_state_anchor':'Both subjects stand in the meadow.','summary':'Hold the same shot.',
        'detailed_description':body,'overall_soundscape':'Use final_audio without modification.'}
    timeline=[{'start_time':0,'end_time':4 if mixed else 8,'visible_speaker':'NONE'}]
    if mixed:timeline.append({'start_time':4,'end_time':8,'visible_speaker':'<Subject 1>'})
    return prepare_h3_prompt(json.dumps(document),constraint=CONSTRAINT,continuity_lock='',
        subject_manifest={'subjects':[{'subject_ref':'<Subject 1>'},{'subject_ref':'<Subject 2>'}]},speaker_timeline=timeline)


@pytest.mark.parametrize('body',[
    'NONE. No visible animal speaks except the grey wolf (<Subject 1>).',
    'NONE. No visible animal speaks except: <Subject 1>.',
    'NONE. No visible animal speaks unless it is <Subject 1>; this exception applies now.',
    'visible_speaker=NONE\n<Subject 1> and <Subject 2> both speak.',
    'visible_speaker=NONE\n<Subject 1> does speak clearly.',
    'visible_speaker=NONE\n<Subject 1> starts speaking.',
    'visible_speaker=NONE\n<Subject 1> stays still while <Subject 2>, who is on the left, speaks.',
    'visible_speaker=NONE\n<Subject 1>, who speaks quietly, waves.',
    'NONE. Except for the grey wolf (<Subject 1>), no visible animal speaks.',
])
def test_tg07_complete_h3_rejects_exception_subject_and_predicate_variants(body):
    with pytest.raises(RuntimeError,match='AUDIODRIVE_AUDIT_FAILED'):prepare(body)


@pytest.mark.parametrize('connection',[', and ','. ','; ',' while '])
def test_tg08_ra_new004_exception_is_bound_to_its_non_speech_predicate(connection):
    assert prepare('NONE. No visible animal speaks'+connection+'all remain still except <Subject 1>, who waves silently.')['passed']


@pytest.mark.parametrize('first',[
    'No visible animal speaks except <Subject 1> during the first four seconds.',
    '<Subject 1> starts speaking during this silent interval.',
    'visible_speaker=<Subject 1>. <Subject 1> speaks.',
])
def test_tg07_mixed_timeline_uses_actual_none_interval_not_prompt_claim(first):
    body='0s-4s visible_speaker=NONE.\n'+first+'\n4s-8s <Subject 1> speaks.'
    with pytest.raises(RuntimeError,match='AUDIODRIVE_AUDIT_FAILED'):prepare(body,mixed=True)


@pytest.mark.parametrize('first',[
    'No visible animal speaks. All remain silent.',
    '<Subject 1> and <Subject 2> do not speak and never lip-sync.',
    '<Subject 1> does not start speaking; no visible character or animal produces lip-sync movement.',
    'No visible animal speaks, and all remain still except <Subject 1>, who waves silently.',
])
def test_tg07_mixed_timeline_silence_then_real_dialogue_is_accepted(first):
    assert prepare('0s-4s visible_speaker=NONE.\n'+first+'\n4s-8s <Subject 1> speaks.',mixed=True)['passed']
