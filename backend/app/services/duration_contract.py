def visual_required_duration(shot, default: float = 4.0) -> float:
    value = getattr(shot, "estimated_duration", None)
    if value is None:
        value = default
    try:
        return round(max(0.0, float(value)), 3)
    except (TypeError, ValueError):
        return round(max(0.0, float(default)), 3)


def audio_required_duration(value) -> float:
    try:
        return round(max(0.0, float(value or 0)), 3)
    except (TypeError, ValueError):
        return 0.0


def resolved_duration(shot, latest_timeline=None, default: float = 4.0) -> float:
    visual = visual_required_duration(shot, default=default)
    audio = 0.0
    if latest_timeline is not None and getattr(latest_timeline, "status", None) == "READY":
        audio = audio_required_duration(
            getattr(latest_timeline, "audio_required_duration", None)
            if getattr(latest_timeline, "audio_required_duration", None) is not None
            else getattr(latest_timeline, "total_duration", 0)
        )
    return round(max(visual, audio), 3)


def clip_duration(start_time, end_time) -> float:
    try:
        return round(max(0.0, float(end_time) - float(start_time)), 3)
    except (TypeError, ValueError):
        return 0.0


def legal_h3_frame_count(duration_seconds: float, fps: int = 25) -> int:
    duration = max(0.001, float(duration_seconds or 0))
    raw_frame_count = int(fps * duration)
    return ((raw_frame_count // 8) * 8) + 1
