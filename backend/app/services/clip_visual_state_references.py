"""Per-Clip image selection. Canonical states and their text are never filtered."""


def owned_visual_state_ids(clip: dict) -> list[str]:
    return list(dict.fromkeys(f"KF{int(index)}" for index in clip.get("visual_state_indexes") or []))


def disabled_visual_state_ids(clip: dict) -> list[str]:
    config = clip.get("visual_state_reference_config")
    if config is None:
        return []
    enabled = config.get("enabled_state_ids") if isinstance(config, dict) else None
    owned = owned_visual_state_ids(clip)
    if (not isinstance(enabled, list) or any(not isinstance(sid, str) for sid in enabled)
            or len(set(enabled)) != len(enabled) or not set(enabled).issubset(owned)):
        raise ValueError("VISUAL_STATE_REFERENCE_CONFIG_INVALID")
    return [sid for sid in owned if sid not in enabled]


def visual_state_reference_enabled(clip: dict, state_id: str) -> bool:
    return state_id not in disabled_visual_state_ids(clip)


def temporal_reference_enabled(clip: dict, anchor: dict) -> bool:
    source = anchor.get("source") or anchor.get("provenance") or {}
    index = source.get("keyframe_index") or anchor.get("source_state_index")
    state_id = f"KF{int(index)}" if index is not None else source.get("id")
    # Only canonical state identity can disable an input, never its Picture slot.
    return visual_state_reference_enabled(clip, state_id)
