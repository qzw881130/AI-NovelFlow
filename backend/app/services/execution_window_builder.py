from typing import Any, Dict, List, Optional


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _event_start(event: Dict[str, Any]) -> float:
    return _num(event.get("startTime", event.get("start_time")))


def _event_end(event: Dict[str, Any]) -> float:
    return _num(event.get("endTime", event.get("end_time")))


def build_natural_execution_windows(
    duration: float,
    max_clip_duration: float,
    audio_events: Optional[List[Dict[str, Any]]] = None,
    min_clip_duration: float = 3.0,
) -> List[Dict[str, Any]]:
    """Build H3 execution windows, preferring natural audio boundaries over fixed cuts."""
    total = round(max(0.0, float(duration or 0)), 3)
    max_duration = max(0.001, float(max_clip_duration or 15))
    if total <= 0:
        return []
    if total <= max_duration:
        return [{
            "window_index": 1,
            "start_time": 0,
            "end_time": total,
            "duration": total,
            "boundary_reason": "SHOT_END",
        }]

    events = sorted([event for event in audio_events or [] if _event_end(event) > _event_start(event)], key=_event_start)
    windows: List[Dict[str, Any]] = []
    start = 0.0
    index = 1

    while start < total - 0.001:
        hard_end = min(total, start + max_duration)
        if hard_end >= total - 0.001:
            end = total
            reason = "SHOT_END"
        else:
            min_end = min(total, start + min(min_clip_duration, max_duration))
            candidates = []
            for event_index, event in enumerate(events):
                event_end = round(_event_end(event), 3)
                if event_end <= start + 0.001 or event_end < min_end - 0.001 or event_end > hard_end + 0.001:
                    continue
                next_event = next((item for item in events[event_index + 1:] if _event_start(item) >= event_end - 0.001), None)
                silence_after = max(0.0, (_event_start(next_event) - event_end) if next_event else (total - event_end))
                distance_to_limit = max(0.0, hard_end - event_end)
                candidates.append({
                    "time": event_end,
                    "silence_after": silence_after,
                    "distance_to_limit": distance_to_limit,
                    "reason": "SILENCE_BOUNDARY" if silence_after >= 0.25 else "AUDIO_EVENT_BOUNDARY",
                })
            if candidates:
                best = sorted(candidates, key=lambda item: (item["silence_after"] >= 0.25, -item["distance_to_limit"], item["time"]), reverse=True)[0]
                end = best["time"]
                reason = best["reason"]
            else:
                end = hard_end
                reason = "MAX_DURATION"

        end = round(max(end, start), 3)
        windows.append({
            "window_index": index,
            "start_time": round(start, 3),
            "end_time": end,
            "duration": round(end - start, 3),
            "boundary_reason": reason,
        })
        if end >= total - 0.001:
            break
        start = end
        index += 1

    return windows
