"""R-P0 narration-only H3: accept silence without hiding real speech conflicts."""
import pytest

from app.services.video_director_ai import audit_audiodrive_h3_prompt
from test_video_director_gate_d4 import AUDIO_TEXT_RENDERING_CONSTRAINT_FIXTURE


MANIFEST = {"subjects": [{"subject_ref": "<Subject 1>"}, {"subject_ref": "<Subject 2>"}]}
TIMELINE = [{"start_time": 0, "end_time": 8, "visible_speaker": "NONE"}]


def audit(body):
    return audit_audiodrive_h3_prompt(
        body + "\n\n" + AUDIO_TEXT_RENDERING_CONSTRAINT_FIXTURE, TIMELINE, MANIFEST,
    )


def test_real_wolf_narration_only_h3_silence_instruction():
    # Exact paragraph from LLM log ca1da01b-7c76-4e91-a9c0-968c12619974.
    body = (
        "From t=0.0 to t=8.0, speaker_timeline is visible_speaker=NONE. "
        "Therefore all visible characters and animals remain silent throughout the entire clip. "
        "No speaking, no dialogue, no whispering, no murmuring, no shouting, no laughter, no human vocalization. "
        "Mouths remain naturally closed except for subtle expressions or breathing. "
        "No visible character or animal produces lip-sync movement."
    )
    result = audit(body)
    assert result["passed"], result["blocking_issues"]


@pytest.mark.parametrize("body", [
    "NONE. No visible character or animal produces lip-sync movement.",
    "NONE. No visible animal produces lip-sync movement.",
    "NONE. No visible subject has lip-sync.",
    "NONE. No visible characters or visible animals perform speech or lip-sync.",
    "NONE. No character or animal produces any speech or lip-sync.",
    "NONE. No visible character nor animal performs lip-sync.",
])
def test_negated_visible_subjects_remain_silent(body):
    result = audit(body)
    assert result["passed"], result["blocking_issues"]


@pytest.mark.parametrize("body", [
    "NONE. No visible character or animal produces lip-sync, but <Subject 1> speaks.",
    "NONE. No visible animal produces lip-sync, while <Subject 2> lip-syncs.",
    "NONE. No visible subject has lip-sync, but <Subject 1> lip-syncs.",
    "NONE. No visible characters or visible animals perform speech or lip-sync, but <Subject 1> talks.",
    "NONE. No visible character or animal prevents <Subject 1> speaking.",
    "NONE. No visible animal approaches <Subject 1> talking.",
    "NONE. No visible character or animal produces gestures while <Subject 1> speaks.",
])
def test_negated_subjects_do_not_hide_affirmative_speech(body):
    result = audit(body)
    assert not result["passed"]
    assert [issue["code"] for issue in result["blocking_issues"]] == ["NONE_SEGMENT_LIPSYNC_CONTRADICTION"]
