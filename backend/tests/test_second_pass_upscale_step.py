"""Optional second-pass upscale steps are applied only to mapped continuation nodes."""

import json

import pytest

from app.models.workflow import Workflow
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.workflow_service import WorkflowService


@pytest.mark.parametrize("workflow_type", ["VIDEO_CONTINUATION", "TEMPORAL_EXTEND"])
@pytest.mark.parametrize("node_type,input_name,original", [
    ("INTConstant", "value", 2),
    ("easy int", "value", 2),
    ("Int", "Number", "2"),
])
@pytest.mark.parametrize("step", [2, 3, 4])
def test_mapped_second_pass_step_is_written_to_submitted_workflow(
    db_session, workflow_type, node_type, input_name, original, step,
):
    WorkflowService(db_session).load_default_workflows()
    source = db_session.query(Workflow).filter(Workflow.type == workflow_type, Workflow.is_active == True).one()
    graph = json.loads(source.workflow_json)
    graph["999"] = {"class_type": node_type, "inputs": {input_name: original}}
    mapping = json.loads(source.node_mapping)
    mapping.update(second_pass_upscale_step_node_id="999", second_pass_upscale_step=str(step))
    builder = WorkflowBuilder()

    if workflow_type == "VIDEO_CONTINUATION":
        result = builder.build_video_continuation_workflow(
            graph, mapping, "previous.mp4", 5, "next scene", "clip-next",
        )
    else:
        result = builder.build_temporal_extend_workflow(
            graph, mapping, "previous.mp4", 5, [], "clip-next", "next scene",
        )

    assert result["999"]["inputs"][input_name] == (str(step) if isinstance(original, str) else step)
    assert graph["999"]["inputs"][input_name] == original


@pytest.mark.parametrize("workflow_type", ["VIDEO_CONTINUATION", "TEMPORAL_EXTEND"])
def test_unmapped_second_pass_step_leaves_workflow_untouched(db_session, workflow_type):
    WorkflowService(db_session).load_default_workflows()
    source = db_session.query(Workflow).filter(Workflow.type == workflow_type, Workflow.is_active == True).one()
    graph = json.loads(source.workflow_json)
    graph["999"] = {"class_type": "Int", "inputs": {"Number": "4"}}
    mapping = json.loads(source.node_mapping)
    mapping["second_pass_upscale_step"] = "2"
    builder = WorkflowBuilder()

    if workflow_type == "VIDEO_CONTINUATION":
        result = builder.build_video_continuation_workflow(
            graph, mapping, "previous.mp4", 5, "next scene", "clip-next",
        )
    else:
        result = builder.build_temporal_extend_workflow(
            graph, mapping, "previous.mp4", 5, [], "clip-next", "next scene",
        )

    assert result["999"]["inputs"]["Number"] == "4"


def test_mapped_second_pass_step_defaults_to_two():
    graph = {"153": {"class_type": "Int", "inputs": {"Number": "4"}}}
    WorkflowBuilder._set_second_pass_upscale_step(graph, {"second_pass_upscale_step_node_id": "153"})
    assert graph["153"]["inputs"]["Number"] == "2"


@pytest.mark.parametrize("step", [2, 3, 4])
def test_multi_reference_video_applies_optional_second_pass_step(db_session, step):
    WorkflowService(db_session).load_default_workflows()
    source = db_session.query(Workflow).filter(Workflow.name == "Minimax H3 多参考生视频 V20260928").one()
    graph = json.loads(source.workflow_json)
    graph["999"] = {"class_type": "Int", "inputs": {"Number": "2"}}
    mapping = json.loads(source.node_mapping)
    mapping.update(second_pass_upscale_step_node_id="999", second_pass_upscale_step=str(step))

    result = WorkflowBuilder().build_video_workflow("scene", json.dumps(graph), mapping)

    assert result["999"]["inputs"]["Number"] == str(step)
    assert graph["999"]["inputs"]["Number"] == "2"


def test_multi_reference_video_without_second_pass_mapping_keeps_original_step(db_session):
    WorkflowService(db_session).load_default_workflows()
    source = db_session.query(Workflow).filter(Workflow.name == "Minimax H3 多参考生视频 V20260928").one()
    graph = json.loads(source.workflow_json)
    graph["999"] = {"class_type": "Int", "inputs": {"Number": "4"}}

    result = WorkflowBuilder().build_video_workflow("scene", json.dumps(graph), json.loads(source.node_mapping))

    assert result["999"]["inputs"]["Number"] == "4"


def test_ui_workflow_step_survives_api_conversion():
    graph = {"nodes": [{"id": 153, "type": "Int", "widgets_values_named": {"Number": "2"},
                        "widgets_values": ["2"], "inputs": []}], "links": []}
    WorkflowBuilder._set_second_pass_upscale_step(graph, {
        "second_pass_upscale_step_node_id": "153", "second_pass_upscale_step": "3",
    })
    assert WorkflowBuilder().convert_ui_to_api(graph)["153"]["inputs"]["Number"] == "3"


@pytest.mark.parametrize("step", ["1", "5", "3.5"])
def test_invalid_second_pass_step_is_rejected(step):
    graph = {"153": {"class_type": "Int", "inputs": {"Number": "2"}}}
    with pytest.raises(ValueError, match="二采放大Step"):
        WorkflowBuilder._set_second_pass_upscale_step(graph, {
            "second_pass_upscale_step_node_id": "153", "second_pass_upscale_step": step,
        })
