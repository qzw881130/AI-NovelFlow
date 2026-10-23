"""Optional second-pass scale is applied to the selected Float node only."""

import json

import pytest

from app.models.workflow import Workflow
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.workflow_service import WorkflowService


@pytest.mark.parametrize("workflow_type", ["VIDEO_CONTINUATION", "TEMPORAL_EXTEND", "multi_reference_video"])
@pytest.mark.parametrize("scale", [1.5, 2, 3, 4])
def test_selected_scale_reaches_submitted_workflow(db_session, workflow_type, scale):
    WorkflowService(db_session).load_default_workflows()
    source = db_session.query(Workflow).filter(Workflow.type == workflow_type, Workflow.is_active == True).one()
    graph = json.loads(source.workflow_json)
    graph["999"] = {"class_type": "PrimitiveFloat", "inputs": {"value": 2.0}}
    mapping = json.loads(source.node_mapping)
    mapping.update(second_pass_upscale_scale_node_id="999", second_pass_upscale_scale=str(scale))
    builder = WorkflowBuilder()

    if workflow_type == "VIDEO_CONTINUATION":
        result = builder.build_video_continuation_workflow(
            graph, mapping, "previous.mp4", 5, "next scene", "clip-next",
        )
    elif workflow_type == "TEMPORAL_EXTEND":
        result = builder.build_temporal_extend_workflow(
            graph, mapping, "previous.mp4", 5, [], "clip-next", "next scene",
        )
    else:
        result = builder.build_video_workflow("scene", json.dumps(graph), mapping)

    assert result["999"]["inputs"]["value"] == float(scale)
    assert graph["999"]["inputs"]["value"] == 2.0


def test_unselected_scale_keeps_workflow_value():
    graph = {"230": {"class_type": "PrimitiveFloat", "inputs": {"value": 3.0}}}
    WorkflowBuilder._set_second_pass_upscale_scale(graph, {"second_pass_upscale_scale": "1.5"})
    assert graph["230"]["inputs"]["value"] == 3.0


def test_selected_scale_defaults_to_two():
    graph = {"230": {"class_type": "PrimitiveFloat", "inputs": {"value": 4.0}}}
    WorkflowBuilder._set_second_pass_upscale_scale(graph, {"second_pass_upscale_scale_node_id": "230"})
    assert graph["230"]["inputs"]["value"] == 2.0


def test_ui_workflow_scale_survives_api_conversion():
    graph = {"nodes": [{"id": 230, "type": "PrimitiveFloat", "widgets_values_named": {"value": 2.0},
                        "widgets_values": [2.0], "inputs": []}], "links": []}
    WorkflowBuilder._set_second_pass_upscale_scale(graph, {
        "second_pass_upscale_scale_node_id": "230", "second_pass_upscale_scale": "1.5",
    })
    assert WorkflowBuilder().convert_ui_to_api(graph)["230"]["inputs"]["value"] == 1.5


@pytest.mark.parametrize("scale", ["1", "2.5", "5", "bad"])
def test_invalid_scale_is_rejected(scale):
    graph = {"230": {"class_type": "PrimitiveFloat", "inputs": {"value": 2.0}}}
    with pytest.raises(ValueError, match="二采放大scale"):
        WorkflowBuilder._set_second_pass_upscale_scale(graph, {
            "second_pass_upscale_scale_node_id": "230", "second_pass_upscale_scale": scale,
        })
