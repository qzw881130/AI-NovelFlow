"""Pre-submit contract for grid-derived MiniMax H3 Ref2VA prompts.

This is intentionally separate from the single-image Phase B compiler. The
official six-section format is documented in MiniMaxAI/MiniMax-H3's
VIDEO_PROMPT_WRITING_GUIDE_ref_en.md; the extra name-location rule is a
NovelFlow constraint requested for grid Clips.
"""

import re

from app.services.h3_native_prompt import (
    MAX_PROMPT_CHARACTERS, SECTIONS, declared_duration,
    dialogue_time_cue, sections,
)


_GRID_DIALOGUE_PATTERN = re.compile(
    r"(<Subject \d+>|<Narrator>)\s+\((S\d+)\)\s+(.+?)<d>\[([^\]\n]+)\][ \t]?(.*?)</d>", re.S,
)


def _grid_dialogue_events(prompt: str) -> list[dict]:
    """A listener Subject may be named in the speech lead before the <d> tag."""
    detail = sections(prompt).get("detailed_description", "")
    return [{"speaker": match[1], "speaker_id": match[2], "speech_lead": match[3],
             "language": match[4], "exact_dialogue": match[5]}
            for match in _GRID_DIALOGUE_PATTERN.finditer(detail)]


def normalize_grid_dialogue_markers(prompt: str, dialogues: list[dict]) -> str:
    """Add only a missing Chinese language tag to an otherwise exact line."""
    tags = list(re.finditer(r"<d>(.*?)</d>", prompt, re.S))
    if len(tags) != len(dialogues):
        return prompt
    chunks, cursor = [], 0
    for tag, line in zip(tags, dialogues):
        chunks.append(prompt[cursor:tag.start()])
        body = tag.group(1)
        if body == line["text"] and re.search(r"[\u3400-\u9fff]", body):
            chunks.append(f"<d>[Chinese] {body}</d>")
        else:
            chunks.append(tag.group())
        cursor = tag.end()
    normalized = "".join(chunks) + prompt[cursor:]
    by_id = {line["id"]: line for line in dialogues}

    def canonical_cue(match: re.Match) -> str:
        event = by_id.get(match[1])
        if event and abs(float(match[2]) - event["start_time"]) < 1e-6 \
                and abs(float(match[3]) - event["end_time"]) < 1e-6:
            return dialogue_time_cue({"id": event["id"], "optimized_start": event["start_time"],
                                      "optimized_end": event["end_time"]})
        return match.group()

    normalized = re.sub(r"\[(D\d+) @ (\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)s generated-clip\]",
                        canonical_cue, normalized)

    def canonical_speaker(match: re.Match) -> str:
        event = by_id.get(match[3])
        subject = match[1]
        if event and event["speaker"] == subject:
            return f"{subject} (S{match[2]}) "
        return match.group()

    return re.sub(r"(<Subject (\d+)>)\s+\(S\d+\)\s+(?=\[(D\d+) @)",
                  canonical_speaker, normalized)


def enforce_grid_no_voice(prompt: str) -> str:
    """Keep the six official sections while making a silent Clip's audio authority explicit."""
    if "<d>" in prompt or "NO_VOICE for the entire generated clip" in prompt:
        return prompt
    if not re.search(r"(?m)^detailed_description:\s*$", prompt) or not re.search(
            r"(?m)^overall_soundscape:\s*$", prompt):
        return prompt
    # A silent beat may follow a dialogue Clip, but the video model must not
    # interpret a recap such as "after finishing the earlier response" as a
    # request to continue or replay that utterance.
    prompt = re.sub(
        r"\bafter (?:finishing|completing|delivering) (?:the|his|her|an) "
        r"(?:(?:earlier|previous|preceding) )?(?:response|reply|line|utterance)\b",
        "after a quiet pause", prompt, flags=re.I,
    )
    visual_contract = (
        "NO_VOICE for the entire generated clip: no Subject is authorized to speak, "
        "narrate, murmur, laugh, vocalize, or ad-lib any words or syllables. "
        "Do not continue, replay, or imitate an utterance from an earlier Clip. "
        "No Subject performs speech-like mouth or lip articulation at any moment; "
        "natural breathing, blinking, facial expression, and non-speech jaw movement remain allowed."
    )
    sound_contract = (
        "No human speech, human vocalization, background conversation, or voice-over "
        "at any point. Keep the audio track active for the specified environmental ambience "
        "and synchronized Foley."
    )
    prompt = re.sub(r"(?m)^overall_soundscape:\s*$",
                    visual_contract + "\n\noverall_soundscape:", prompt, count=1)
    return re.sub(r"(?m)^non_diegetic_music:\s*$",
                  sound_contract + "\n\nnon_diegetic_music:", prompt, count=1)


def inspect_grid_h3_prompt(prompt: str, subject_names: dict[str, str],
                           dialogues: list[dict], reference_slots: list[int],
                           clip_duration: float | None = None) -> dict[str, bool]:
    """Check a compiled Clip prompt against its actual references and dialogue."""
    try:
        parts = sections(prompt) if re.search(r"(?m)^subject_definitions:\s*$", prompt) else {}
    except (IndexError, TypeError):
        parts = {}
    structure = bool(parts) and all(parts.get(name) for name in SECTIONS)
    if not structure:
        return {"six_sections": False}

    definitions = parts["subject_definitions"]
    actual = _grid_dialogue_events(prompt)
    names_outside_definitions = "\n".join(value for key, value in parts.items() if key != "subject_definitions")
    names_outside_definitions = re.sub(r"<d>.*?</d>", "", names_outside_definitions, flags=re.S)
    definitions_map = re.findall(
        r"(?m)^\s*(<Subject \d+>)\s+is\s+([^,，\n.;；。:：]+)", definitions,
    )
    defined_subjects = {subject for subject, _ in definitions_map}
    used_subjects = set(re.findall(r"<Subject \d+>", prompt))
    picture_slots = {int(value) for value in re.findall(r"<Picture (\d+)>", prompt)}
    supplied_slots = set(reference_slots)
    expected_dialogues = [(row["speaker"], row["text"]) for row in dialogues]
    actual_dialogues = [(row["speaker"], row["exact_dialogue"]) for row in actual]
    speaker_ids = {}
    stable_speakers = True
    for row in actual:
        speaker = row["speaker"]
        subject_number = re.fullmatch(r"<Subject (\d+)>", speaker)
        expected_id = speaker_ids.setdefault(
            speaker, f"S{subject_number.group(1)}" if subject_number else f"S{len(subject_names) + 1}",
        )
        if row["speaker_id"] != expected_id:
            stable_speakers = False

    shot_marks = re.findall(r"\[Shot (\d+)\](?: At (\d{2}):(\d{2})\.(\d{3}))?", parts["detailed_description"])
    duration = declared_duration(prompt)
    if duration is None:
        # H3 may phrase the same total as "5 seconds". Keep this grid-only
        # tolerance separate from the single-image Phase B parser.
        plural_durations = re.findall(r"\b(\d+(?:\.\d+)?) seconds\b", parts["summary"], re.I)
        if len(plural_durations) == 1:
            duration = float(plural_durations[0])
    shot_times = [int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000
                  for _, minutes, seconds, milliseconds in shot_marks[1:]
                  if minutes and seconds and milliseconds]
    timed_dialogues = all(
        {"id", "start_time", "end_time"} <= row.keys() for row in dialogues
    )
    if timed_dialogues:
        expected_cues = [dialogue_time_cue({
            "id": row["id"], "optimized_start": row["start_time"],
            "optimized_end": row["end_time"],
        }) for row in dialogues]
        actual_cues = [re.search(r"\[D\d+ @ [^\]]+\]", row["speech_lead"])
                       for row in actual]
        timing_valid = len(actual_cues) == len(expected_cues) and all(
            cue is not None and cue.group() == expected and prompt.count(expected) == 1
            for cue, expected in zip(actual_cues, expected_cues)
        ) and all(0 <= row["start_time"] < row["end_time"] <= (clip_duration or duration or 20) + 1e-6
                  for row in dialogues)
    else:
        timing_valid = not dialogues

    return {
        "six_sections": True,
        "prompt_length": 0 < len(prompt) <= MAX_PROMPT_CHARACTERS,
        "subject_definitions": len(definitions_map) == len(subject_names)
            and dict(definitions_map) == subject_names and used_subjects <= defined_subjects,
        "character_names_only_in_definitions": all(
            not re.search(re.escape(name), names_outside_definitions) for name in subject_names.values() if name
        ),
        "physical_picture_slots": picture_slots == supplied_slots,
        "dialogue_order_and_text": actual_dialogues == expected_dialogues
            and prompt.count("<d>") == prompt.count("</d>") == len(dialogues),
        "dialogue_time_assignment": timing_valid,
        "stable_speaker_ids": stable_speakers,
        "dialogue_language": all(
            row["language"] == "Chinese" for row in actual
            if re.search(r"[\u3400-\u9fff]", row["exact_dialogue"])
        ),
        "no_unknown_speakers": all(row["speaker"] in subject_names or row["speaker"] == "<Narrator>"
                                   for row in actual),
        "shot_order_and_duration": bool(shot_marks) and all(
            int(mark[0]) == i for i, mark in enumerate(shot_marks, 1)
        ) and len(shot_times) == len(shot_marks) - 1
            and shot_times == sorted(set(shot_times))
            and all(time < (clip_duration or duration or 20) for time in shot_times)
            and (clip_duration is None or duration == clip_duration),
    }


def validate_grid_h3_prompt(prompt: str, subject_names: dict[str, str],
                            dialogues: list[dict], reference_slots: list[int],
                            clip_duration: float | None = None) -> dict[str, bool]:
    checks = inspect_grid_h3_prompt(prompt, subject_names, dialogues, reference_slots, clip_duration)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("GRID_H3_PROMPT_INVALID: " + ", ".join(failed))
    return checks
