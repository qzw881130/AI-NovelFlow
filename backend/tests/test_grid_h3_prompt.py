import pytest

from app.services.grid_h3_prompt import enforce_grid_no_voice, normalize_grid_dialogue_markers, validate_grid_h3_prompt


SUBJECTS = {"<Subject 1>": "杜甫", "<Subject 2>": "老妇"}
DIALOGUES = [
    {"id": "D1", "speaker": "<Subject 2>", "text": "先生可是要投宿？", "start_time": 1, "end_time": 3},
    {"id": "D2", "speaker": "<Subject 1>", "text": "求一处避雨之所。", "start_time": 5, "end_time": 8},
]
PROMPT = """subject_definitions:
<Subject 1> is 杜甫, the traveler shown in <Picture 1>.
<Subject 2> is 老妇, the woman shown in <Picture 2>.
<Picture 1> anchors the first camera composition.
<Picture 2> anchors the reverse camera composition.

summary:
[reference generation] A 10-second farmhouse conversation between <Subject 1> and <Subject 2>.

retention_analysis:
<Picture 1>: fully_preserved - first camera composition.
<Picture 2>: fully_preserved - reverse camera composition.
<Subject 1>: fully_preserved - face and costume.
<Subject 2>: fully_preserved - face and costume.

detailed_description:
[Shot 1] Over <Subject 1>'s shoulder, <Subject 2> (S2) [D1 @ 1-3s generated-clip] asks, <d>[Chinese] 先生可是要投宿？</d>
[Shot 2] At 00:04.000, reverse over <Subject 2>'s shoulder. <Subject 1> (S1) [D2 @ 5-8s generated-clip] replies, <d>[Chinese] 求一处避雨之所。</d>

overall_soundscape:
Quiet dusk ambience and natural dialogue.

non_diegetic_music:
None.
"""


def test_grid_h3_prompt_accepts_official_sections_and_canonical_dialogue():
    assert all(validate_grid_h3_prompt(PROMPT, SUBJECTS, DIALOGUES, [1, 2], 10).values())


def test_grid_h3_prompt_accepts_natural_plural_duration():
    prompt = PROMPT.replace('A 10-second farmhouse', 'A farmhouse scene lasting 10 seconds')
    assert all(validate_grid_h3_prompt(prompt, SUBJECTS, DIALOGUES, [1, 2], 10).values())


def test_grid_h3_prompt_restores_only_missing_language_marker_for_exact_line():
    raw = PROMPT.replace('<d>[Chinese] 先生可是要投宿？</d>', '<d>先生可是要投宿？</d>')
    assert normalize_grid_dialogue_markers(raw, DIALOGUES) == PROMPT
    altered = raw.replace('先生可是要投宿？', '换一句台词。')
    assert normalize_grid_dialogue_markers(altered, DIALOGUES) == altered


def test_grid_h3_prompt_uses_subject_number_for_only_speaker():
    prompt = PROMPT.replace(
        "<Subject 1> (S1) [D2 @ 5-8s generated-clip] replies, <d>[Chinese] 求一处避雨之所。</d>",
        "<Subject 1> listens without speaking.",
    )
    assert all(validate_grid_h3_prompt(prompt, SUBJECTS, [DIALOGUES[0]], [1, 2], 10).values())


def test_grid_h3_prompt_allows_listener_subject_in_speech_lead_and_padded_cue():
    prompt = PROMPT.replace(
        "(S1) [D2 @ 5-8s generated-clip] replies",
        "(S1) [D2 @ 5.000-8.000s generated-clip] looks toward <Subject 2> and replies",
    )
    normalized = normalize_grid_dialogue_markers(prompt, DIALOGUES)
    assert all(validate_grid_h3_prompt(normalized, SUBJECTS, DIALOGUES, [1, 2], 10).values())


def test_grid_h3_prompt_normalizes_voice_id_to_its_canonical_subject():
    prompt = PROMPT.replace('<Subject 2> (S2) [D1', '<Subject 2> (S1) [D1')
    normalized = normalize_grid_dialogue_markers(prompt, DIALOGUES)
    assert normalized == PROMPT
    assert all(validate_grid_h3_prompt(normalized, SUBJECTS, DIALOGUES, [1, 2], 10).values())


def test_grid_h3_accepts_unpictured_offscreen_voice_and_requires_lip_lock():
    prompt = """subject_definitions:
<Picture 1> defines the empty farmhouse door.

summary:
A 5-second full-reference view of the door.

retention_analysis:
<Picture 1> supplies the empty environment.

detailed_description:
[Shot 1] Off-screen voice: a rough adult male officer outside the door (S1) [D1 @ 1-2s generated-clip] shouts off-screen, <d>[Chinese] 开门！</d> while all visible subjects' lips remain completely closed.

overall_soundscape:
Night footsteps and a rattling door.

non_diegetic_music:
None.
"""
    dialogues = [{'id': 'D1', 'speaker': 'Off-screen voice: a rough adult male officer outside the door',
                  'text': '开门！', 'delivery': 'offscreen', 'start_time': 1, 'end_time': 2}]
    assert all(validate_grid_h3_prompt(prompt, {}, dialogues, [1], 5).values())
    with pytest.raises(ValueError, match='offscreen_lip_lock'):
        validate_grid_h3_prompt(prompt.replace("lips remain completely closed", "does not speak"),
                                {}, dialogues, [1], 5)


def test_grid_no_voice_contract_keeps_six_sections_and_ambience():
    raw = """subject_definitions:
<Subject 1> is 杜甫, a traveler in <Picture 1>.

summary:
A 6-second courtyard view of <Subject 1>.

retention_analysis:
<Picture 1> anchors the shot.

detailed_description:
[Shot 1] <Subject 1> straightens after finishing the earlier response.

overall_soundscape:
Wind and footsteps.

non_diegetic_music:
None.
"""
    prompt = enforce_grid_no_voice(raw)
    assert enforce_grid_no_voice(prompt) == prompt
    assert 'after finishing the earlier response' not in prompt
    assert 'NO_VOICE for the entire generated clip' in prompt
    assert 'No human speech, human vocalization' in prompt
    assert 'Wind and footsteps.' in prompt
    assert all(validate_grid_h3_prompt(prompt, {'<Subject 1>': '杜甫'}, [], [1], 6).values())


@pytest.mark.parametrize("bad,reason", [
    (PROMPT.replace("summary:", "overview:"), "six_sections"),
    (PROMPT.replace("A 10-second farmhouse", "杜甫 in a 10-second farmhouse"), "character_names_only_in_definitions"),
    (PROMPT.replace("<Picture 2>: fully_preserved", "<Picture 3>: fully_preserved"), "physical_picture_slots"),
    (PROMPT.replace("求一处避雨之所。", "换一句台词。"), "dialogue_order_and_text"),
    (PROMPT.replace("<Subject 1> (S1) [D2", "<Subject 1> (S2) [D2"), "stable_speaker_ids"),
    (PROMPT.replace("[D2 @ 5-8s generated-clip]", "[D2 @ 6-8s generated-clip]"), "dialogue_time_assignment"),
    (PROMPT.replace("[Shot 2] At 00:04.000", "[Shot 2] At 00:11.000"), "shot_order_and_duration"),
])
def test_grid_h3_prompt_blocks_bad_submission(bad, reason):
    with pytest.raises(ValueError, match=reason):
        validate_grid_h3_prompt(bad, SUBJECTS, DIALOGUES, [1, 2], 10)
