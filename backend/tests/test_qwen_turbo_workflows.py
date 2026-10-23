"""Check the selectable Turbo workflows against task reference bindings."""

import json
from pathlib import Path

import pytest

from app.constants.workflow import EXTRA_SYSTEM_WORKFLOWS
from app.services.comfyui.workflows import WorkflowBuilder
from app.utils.workflow_disconnect import disconnect_reference_chain


WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"

REFERENCE_KEYS = {
    "shot_scene": ["scene_reference_image_node_id"],
    "shot_character_scene": ["character_reference_image_node_id", "scene_reference_image_node_id"],
    "shot_scene_prop": ["scene_reference_image_node_id", "prop_reference_image_node_id"],
    "shot": ["character_reference_image_node_id", "scene_reference_image_node_id", "prop_reference_image_node_id"],
    "keyframe_image": ["reference_image_node_id"],
    "single_image_edit": ["load_image_node_id"],
}


@pytest.mark.parametrize("workflow_type,reference_keys", REFERENCE_KEYS.items())
def test_qwen_turbo_workflow_has_only_task_reference_slots(workflow_type, reference_keys):
    config = next(
        item for item in EXTRA_SYSTEM_WORKFLOWS
        if item["type"] == workflow_type and "Qwen Image 2.1 Turbo" in item["name"]
    )
    graph = json.loads((WORKFLOWS_DIR / config["filename"]).read_text())
    mapping = config["node_mapping"]
    expected_nodes = [mapping[key] for key in reference_keys]

    assert {node_id for node_id, node in graph.items() if node["class_type"] == "LoadImage"} == set(expected_nodes)
    assert all(graph[node_id]["inputs"]["image"] == "" for node_id in expected_nodes)
    assert {
        name: value[0] for name, value in graph["485"]["inputs"].items()
        if name.startswith("images.image_")
    } == {f"images.image_{index}": node_id for index, node_id in enumerate(expected_nodes, 1)}
    assert graph["541"]["class_type"] == "LoraLoaderModelOnly"
    assert all(str(node_id) in graph for key, node_id in mapping.items() if "node" in key)

    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2:
                assert str(value[0]) in graph


def test_qwen_turbo_shot_binds_three_reference_types_in_picture_order():
    config = next(item for item in EXTRA_SYSTEM_WORKFLOWS if item["type"] == "shot" and "Qwen Image 2.1 Turbo" in item["name"])
    graph_text = (WORKFLOWS_DIR / config["filename"]).read_text()
    graph = WorkflowBuilder().build_shot_workflow("new shot prompt", graph_text, config["node_mapping"])
    for index, key in enumerate(REFERENCE_KEYS["shot"], 1):
        graph[config["node_mapping"][key]]["inputs"]["image"] = f"picture-{index}.png"
    assert graph["516"]["inputs"]["prompt"] == "new shot prompt"
    assert [graph[graph["485"]["inputs"][f"images.image_{index}"][0]]["inputs"]["image"] for index in range(1, 4)] == [
        "picture-1.png", "picture-2.png", "picture-3.png"
    ]


def test_qwen_turbo_missing_reference_disconnects_dynamic_image_input():
    graph = json.loads((WORKFLOWS_DIR / "qwen_image_2_1_turbo_shot_v20261018.json").read_text())
    disconnect_reference_chain(graph, "510")
    assert "images.image_2" not in graph["485"]["inputs"]
    assert "images.image_1" in graph["485"]["inputs"]
    assert "images.image_3" in graph["485"]["inputs"]
