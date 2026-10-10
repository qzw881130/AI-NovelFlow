"""Small, provider-facing capability contracts for Clip Planner V1."""

CLIP_MAX_DURATION = 20.0
# Planning headroom is a preference, never a provider validation ceiling.
CLIP_PREFERRED_MAX_DURATION = 15.0


def clip_duration_maximum(extension=None):
    """Product ceiling intersected with an explicit, possibly lower workflow limit."""
    extension = extension or {}
    return min(CLIP_MAX_DURATION, float(
        extension.get("max_clip_duration") or extension.get("max_seconds") or CLIP_MAX_DURATION
    ))


VIDEO_CAPABILITY_CONTRACTS = {
    "GENERATE": {
        "enabled": True,
        "provider": "MINIMAX_H3",
        "min_duration": 4.0,
        "max_duration": CLIP_MAX_DURATION,
        "requires_previous_video": False,
        "min_temporal_anchors": 0,
        "max_temporal_anchors": 0,
        "required_inputs": [],
    },
    "SINGLE_FRAME": {
        "enabled": True,
        "provider": "MINIMAX_H3",
        "min_duration": 4.0,
        "max_duration": CLIP_MAX_DURATION,
        "requires_previous_video": False,
        "min_temporal_anchors": 0,
        "max_temporal_anchors": 0,
        "required_inputs": ["shot_image"],
    },
    "FIRST_LAST_FRAME": {
        "enabled": True,
        "provider": "MINIMAX_H3",
        "min_duration": 4.0,
        "max_duration": CLIP_MAX_DURATION,
        "requires_previous_video": False,
        "min_temporal_anchors": 0,
        "max_temporal_anchors": 2,
        "required_inputs": ["shot_image", "end_keyframe_image"],
    },
    "MULTI_KEYFRAME": {
        "enabled": True,
        "provider": "MINIMAX_H3",
        "min_duration": 4.0,
        "max_duration": CLIP_MAX_DURATION,
        "requires_previous_video": False,
        "min_temporal_anchors": 0,
        "max_temporal_anchors": 4,
        "min_keyframes": 3,
        "max_keyframes": 4,
        "required_inputs": ["keyframe_images"],
    },
    "VIDEO_CONTINUATION": {
        "enabled": True,
        "provider": "MINIMAX_H3",
        "min_duration": 4.0,
        "max_duration": CLIP_MAX_DURATION,
        "requires_previous_video": True,
        "min_temporal_anchors": 0,
        "max_temporal_anchors": 0,
        "required_inputs": ["previous_approved_video"],
    },
    "TEMPORAL_EXTEND": {
        "enabled": True,
        "provider": "MINIMAX_H3",
        "min_duration": 4.0,
        "max_duration": CLIP_MAX_DURATION,
        "requires_previous_video": True,
        "min_temporal_anchors": 1,
        "max_temporal_anchors": 8,
        "required_inputs": ["previous_approved_video", "temporal_anchor_images"],
    },
    "EXTEND": {
        "enabled": True,
        "provider": "MINIMAX_H3",
        "min_duration": 4.0,
        "max_duration": CLIP_MAX_DURATION,
        "requires_previous_video": True,
        "min_temporal_anchors": 0,
        "max_temporal_anchors": 0,
        "required_inputs": ["previous_approved_video"],
    },
}

# EXTEND is a semantic capability.  This is the one deliberate physical
# adapter to the frozen historical continuation workflow.
EXTEND_WORKFLOW_ID = "6dcdf466-69f1-41e5-9ccf-7a51b0c7de71"
EXTEND_PHYSICAL_WORKFLOW_TYPE = "VIDEO_CONTINUATION"
TEMPORAL_EXTEND_WORKFLOW_ID = "cb0804a7-157e-4c12-9174-5fa43838ecf4"
