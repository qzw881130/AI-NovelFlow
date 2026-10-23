"""Mapped Megapixels values reach both continuation workflow types."""

import pytest

from app.services.comfyui.workflows import WorkflowBuilder


@pytest.mark.parametrize("workflow_type", ["VIDEO_CONTINUATION", "TEMPORAL_EXTEND"])
def test_continuation_megapixels_reaches_api_graph(workflow_type):
    graph = {
        "1": {"class_type": "VHS_LoadVideoFFmpeg", "inputs": {"video": "old.mp4"}},
        "2": {"class_type": "PrimitiveFloat", "inputs": {"value": 4}},
        "3": {"class_type": "CR Prompt Text", "inputs": {"prompt": "old"}},
        "4": {"class_type": "VHS_VideoCombine", "inputs": {"filename_prefix": "old"}},
        "5": {"class_type": "MiniMaxH3CustomKeyframes", "inputs": {}},
        "6": {"class_type": "easy float", "inputs": {"value": 0.4}},
    }
    mapping = {
        "load_video_node_id": "1", "duration_seconds_node_id": "2",
        "prompt_node_id": "3", "video_save_node_id": "4",
        "custom_keyframes_node_id": "5",
        "megapixels_node_id": "6", "megapixels_value": "0.52",
    }
    builder = WorkflowBuilder()

    if workflow_type == "TEMPORAL_EXTEND":
        result = builder.build_temporal_extend_workflow(graph, mapping, "previous.mp4", 5, [], "clip", "next")
    else:
        result = builder.build_video_continuation_workflow(graph, mapping, "previous.mp4", 5, "next", "clip")

    assert result["6"]["inputs"]["value"] == 0.52
    assert graph["6"]["inputs"]["value"] == 0.4


def test_temporal_megapixels_survives_ui_to_api_conversion():
    graph = {
        "nodes": [
            {"id": 1, "type": "VHS_LoadVideoFFmpeg", "widgets_values_named": {"video": "old.mp4"}},
            {"id": 2, "type": "PrimitiveFloat", "widgets_values_named": {"value": 4}, "widgets_values": [4]},
            {"id": 3, "type": "CR Prompt Text", "widgets_values_named": {"prompt": "old"}},
            {"id": 4, "type": "VHS_VideoCombine", "widgets_values_named": {"filename_prefix": "old"}},
            {"id": 5, "type": "MiniMaxH3CustomKeyframes", "widgets_values_named": {}},
            {"id": 6, "type": "easy float", "widgets_values_named": {"value": 0.4}, "widgets_values": [0.4]},
        ],
        "links": [],
    }
    mapping = {
        "load_video_node_id": "1", "duration_seconds_node_id": "2",
        "prompt_node_id": "3", "video_save_node_id": "4",
        "custom_keyframes_node_id": "5",
        "megapixels_node_id": "6", "megapixels_value": "0.52",
    }
    builder = WorkflowBuilder()

    result = builder.build_temporal_extend_workflow(graph, mapping, "previous.mp4", 5, [], "clip", "next")

    assert builder.convert_ui_to_api(result)["6"]["inputs"]["value"] == 0.52


def test_unmapped_megapixels_keeps_original_value():
    graph = {"6": {"class_type": "easy float", "inputs": {"value": 0.4}}}

    WorkflowBuilder._set_megapixels(graph, {"megapixels_value": "0.52"})

    assert graph["6"]["inputs"]["value"] == 0.4
