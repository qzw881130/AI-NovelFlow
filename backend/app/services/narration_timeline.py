"""Repair oversized narration events before semantic Clip planning."""

import json
import math
import re
from copy import deepcopy

from app.constants.capability import CLIP_PREFERRED_MAX_DURATION
from app.services.video_director_ai import (
    _dialogue_speaker,
    _estimate_dialogue_seconds,
    build_dialogue_timeline,
    timeline_matches_shot_dialogues,
)


def _complete_sentences(text: str) -> list[str]:
    """Keep every character, including punctuation and inter-sentence whitespace."""
    boundaries = [match.end() for match in re.finditer(r'[。！？!?]+[”’"」』）)]*', text)]
    if not boundaries:
        return [text]
    result = []
    start = 0
    for end in boundaries:
        result.append(text[start:end])
        start = end
    if start < len(text):
        # An unfinished tail is not a sentence boundary. Keep it attached to
        # the final sentence, which may make this event genuinely infeasible.
        result[-1] += text[start:]
    return result


def _pack_sentences(text: str, emotion: str) -> list[str] | None:
    sentences = _complete_sentences(text)
    if len(sentences) < 2 or any(
        _estimate_dialogue_seconds(sentence, emotion) > CLIP_PREFERRED_MAX_DURATION
        for sentence in sentences
    ):
        return None
    groups = []
    current = ""
    for sentence in sentences:
        if current and _estimate_dialogue_seconds(current + sentence, emotion) > CLIP_PREFERRED_MAX_DURATION:
            groups.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        groups.append(current)
    if (len(groups) > 1
            and _estimate_dialogue_seconds(groups[-1], emotion) < 4
            and _estimate_dialogue_seconds(groups[-2] + groups[-1], emotion) <= CLIP_PREFERRED_MAX_DURATION):
        groups[-2:] = [groups[-2] + groups[-1]]
    if len(groups) < 2 or "".join(groups) != text:
        return None
    return groups


def split_oversized_narration_records(
    dialogues: list[dict], timeline: list[dict] | None = None,
) -> list[dict] | None:
    """Split multi-sentence narration while preserving exact text and metadata."""
    if not isinstance(dialogues, list) or (timeline is not None and len(timeline) != len(dialogues)):
        return None
    if not all(isinstance(dialogue, dict) for dialogue in dialogues):
        return None
    def order_key(pair):
        position, dialogue = pair
        try:
            return (0, int(dialogue["order"]), position)
        except (KeyError, TypeError, ValueError):
            return (1, position, position)

    ordered = sorted(enumerate(dialogues), key=order_key)
    replacement = []
    changed = False
    original_ids = {
        str(dialogue.get("dialogue_id") or dialogue.get("id") or f"D{position}")
        for position, (_, dialogue) in enumerate(ordered, 1)
    }
    for position, (_, dialogue) in enumerate(ordered, 1):
        event_id = str(dialogue.get("dialogue_id") or dialogue.get("id") or f"D{position}")
        raw_text = str(dialogue.get("text") or dialogue.get("dialogue") or "")
        emotion = str(dialogue.get("emotion_prompt") or dialogue.get("emotion") or "")
        if timeline is None:
            duration = _estimate_dialogue_seconds(raw_text, emotion)
        else:
            event = timeline[position - 1]
            if not isinstance(event, dict):
                return None
            duration = float(event["end_time"]) - float(event["start_time"])
        parts = None
        if duration > CLIP_PREFERRED_MAX_DURATION + 1e-6 and _dialogue_speaker(dialogue) == "旁白":
            # A previously generated audio file or manually timed line cannot
            # be divided without also editing its separate media authority.
            if any(dialogue.get(key) for key in (
                "audio_url", "audio_task_id", "start_time", "end_time", "duration"
            )):
                return None
            parts = _pack_sentences(raw_text, emotion)
            if parts is None:
                return None
            changed = True
        for part_number, part in enumerate(parts or [raw_text], 1):
            item = deepcopy(dialogue)
            item.pop("id", None)
            item.pop("dialogue", None)
            item["text"] = part
            item["dialogue_id"] = (
                f"{event_id}__sentence_{part_number}" if parts else event_id
            )
            if parts and item["dialogue_id"] in original_ids:
                return None
            item["order"] = len(replacement) + 1
            replacement.append(item)
    if not changed:
        return None
    return replacement


def minimum_shot_duration_for_dialogues(dialogues: list[dict]) -> int:
    """Allow the canonical timeline's lead-in, speech, turn gaps and tail."""
    speech = sum(
        _estimate_dialogue_seconds(item.get("text") or "", item.get("emotion_prompt") or item.get("emotion") or "")
        for item in dialogues
    )
    return math.ceil(1 + speech + 0.2 * max(0, len(dialogues) - 1) + 0.25)


def segment_oversized_narration(shot, timeline: list[dict]) -> tuple[list[dict], list[dict], dict] | None:
    """Return a validated replacement L1 only when full-sentence narration fits.

    The caller commits the replacement dialogue records and timeline together,
    after its new Clip plan passes validation. Existing records are never mutated.
    """
    replacement = split_oversized_narration_records(json.loads(shot.dialogues or "[]"), timeline)
    if replacement is None:
        return None
    characters = json.loads(shot.characters or "[]")
    new_timeline, _, status = build_dialogue_timeline(
        {"start_time": 0, "end_time": shot.duration}, replacement, characters
    )
    if status.get("status") != "ok" or not timeline_matches_shot_dialogues(new_timeline, replacement):
        return None
    if any(float(event["end_time"]) - float(event["start_time"]) > CLIP_PREFERRED_MAX_DURATION + 1e-6
           for event in new_timeline):
        return None
    return replacement, new_timeline, status
