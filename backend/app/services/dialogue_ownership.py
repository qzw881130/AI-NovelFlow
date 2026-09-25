"""Deterministically assign ordered dialogue text spans to semantic Clips."""

from app.services.video_director_ai import _dialogue_text, _estimate_dialogue_seconds, _dialogue_speaker


def assign_dialogues_to_clips(dialogues: list, clips: list) -> tuple[list[dict], dict]:
    indexed_dialogues = [(index, item) for index, item in enumerate(dialogues or []) if isinstance(item, dict) and _dialogue_text(item)]
    indexed_dialogues.sort(key=lambda pair: (pair[1].get("order") is None, pair[1].get("order", pair[0]), pair[0]))
    ordered_dialogues = [item for _, item in indexed_dialogues]
    ordered_clips = sorted(clips or [], key=lambda item: float(item.get("start_time") or 0))
    if not ordered_clips:
        return [], {"passed": not ordered_dialogues, "findings": ["NO_CLIPS_FOR_DIALOGUE"] if ordered_dialogues else []}

    total_clip_duration = sum(max(0.0, float(clip.get("end_time", 0)) - float(clip.get("start_time", 0))) for clip in ordered_clips)
    if total_clip_duration <= 0:
        return [], {"passed": False, "findings": ["INVALID_CLIP_DURATIONS"]}

    boundaries = []
    cursor = 0.0
    for clip in ordered_clips:
        duration = max(0.0, float(clip.get("end_time", 0)) - float(clip.get("start_time", 0)))
        cursor += duration
        boundaries.append((cursor / total_clip_duration, clip))

    raw_items = []
    total_estimated_duration = 0.0
    for dialogue_index, dialogue in enumerate(ordered_dialogues, 1):
        raw_text = dialogue.get("text") or dialogue.get("dialogue") or ""
        text = str(raw_text) if str(raw_text).strip() else ""
        emotion = str(dialogue.get("emotion_prompt") or dialogue.get("emotion") or "")
        duration = _estimate_dialogue_seconds(text, emotion)
        raw_items.append((dialogue_index, dialogue, text, duration))
        total_estimated_duration += duration

    assignments = {int(clip.get("clip_index") or index): [] for index, clip in enumerate(ordered_clips, 1)}
    timeline_cursor = 0.0
    for dialogue_index, dialogue, text, estimated_duration in raw_items:
        start_ratio = timeline_cursor / total_estimated_duration if total_estimated_duration else 0.0
        end_ratio = (timeline_cursor + estimated_duration) / total_estimated_duration if total_estimated_duration else 1.0
        text_cursor = 0
        for boundary_index, (boundary_ratio, clip) in enumerate(boundaries):
            span_start_ratio = max(start_ratio, 0.0 if boundary_index == 0 else boundaries[boundary_index - 1][0])
            span_end_ratio = min(end_ratio, boundary_ratio)
            if span_end_ratio <= span_start_ratio:
                continue
            start = min(len(text), round((span_start_ratio - start_ratio) / max(end_ratio - start_ratio, 1e-12) * len(text)))
            end = len(text) if span_end_ratio >= end_ratio - 1e-12 else min(len(text), round((span_end_ratio - start_ratio) / max(end_ratio - start_ratio, 1e-12) * len(text)))
            start = max(text_cursor, start)
            end = max(end, start)
            if start > text_cursor:
                previous_clause = max(text.rfind(mark, text_cursor, start) for mark in "。！？；，、.?!;,")
                if previous_clause >= text_cursor:
                    start = previous_clause + 1
            if end < len(text):
                next_clause = min((position for mark in "。！？；，、.?!;," if (position := text.find(mark, end)) >= 0), default=-1)
                if next_clause >= end and next_clause - end <= max(1, round(len(text) * 0.1)):
                    end = next_clause + 1
                if not text[end:].strip(" \t\r\n\"'“”‘’「」『』【】()（）[]{}"):
                    end = len(text)
            if end <= start:
                continue
            span_text = text[start:end]
            text_cursor = end
            clip_index = int(clip.get("clip_index") or boundary_index + 1)
            dialogue_id = str(dialogue.get("id") or f"D{dialogue_index}")
            segment_index = sum(1 for items in assignments.values() for item in items if item["dialogue_id"] == dialogue_id) + 1
            assignments.setdefault(clip_index, []).append({
                "dialogue_id": dialogue_id,
                "segment_index": segment_index,
                "speaker": _dialogue_speaker(dialogue),
                "text": span_text,
                "emotion_prompt": str(dialogue.get("emotion_prompt") or dialogue.get("emotion") or ""),
                "estimated_duration": round(estimated_duration * (end - start) / max(len(text), 1), 2),
                "source_order": dialogue_index,
                "is_continuation": start > 0,
                "continues_in_next_clip": end < len(text),
            })
        timeline_cursor += estimated_duration

    flattened = [item for clip in ordered_clips for item in assignments.get(int(clip.get("clip_index") or 0), [])]
    reconstructed = {}
    for item in flattened:
        reconstructed.setdefault(item["source_order"], "")
        reconstructed[item["source_order"]] += item["text"]
    findings = []
    if [item["source_order"] for item in flattened] != sorted(item["source_order"] for item in flattened):
        findings.append("DIALOGUE_ORDER_CHANGED")
    if any(reconstructed.get(index) != text for index, _, text, _ in raw_items):
        findings.append("DIALOGUE_TEXT_MISSING_OR_CHANGED")
    span_ids = [(item["dialogue_id"], item["segment_index"]) for item in flattened]
    if len(span_ids) != len(set(span_ids)):
        findings.append("DIALOGUE_SPAN_DUPLICATED")

    result = [
        {"clip_index": int(clip.get("clip_index") or index), "dialogues": assignments.get(int(clip.get("clip_index") or index), [])}
        for index, clip in enumerate(ordered_clips, 1)
    ]
    return result, {"passed": not findings, "findings": findings, "source_dialogue_count": len(ordered_dialogues), "assigned_segment_count": len(flattened)}
