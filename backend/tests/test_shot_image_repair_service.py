import json
from copy import deepcopy
from types import SimpleNamespace

from app.models.task import Task
from app.services.image_quality_review import build_review_input
from app.services.shot_image_repair_service import build_masked_repair_graph


def test_masked_graph_uses_base_only_for_inpaint_and_separate_reference_slots():
    mapping = {"prompt_node_id": "516", "save_image_node_id": "515"}
    mapping.update({f"load_image_node_{i}": str(500 + i) for i in range(1, 10)})
    graph = {str(500 + i): {"class_type": "LoadImage", "inputs": {"image": "old.png"}}
             for i in range(1, 10)}
    graph.update({
        "485": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "images.image_1": ["501", 0], "images.image_2": ["509", 0]}},
        "484": {"class_type": "QwenImage21Cache", "inputs": {}},
        "479": {"class_type": "VAELoader", "inputs": {}},
        "481": {"class_type": "VAEDecode", "inputs": {"samples": ["482", 0]}},
        "515": {"class_type": "SaveImage", "inputs": {"images": ["481", 0]}},
        "482": {"class_type": "KSampler", "inputs": {}},
    })
    service = SimpleNamespace(builder=SimpleNamespace(build_shot_workflow=lambda **_: deepcopy(graph)))
    workflow = SimpleNamespace(node_mapping=json.dumps(mapping), workflow_json="{}")

    result, output = build_masked_repair_graph(
        service, workflow, "只修复一个人物", "16:9", 123,
        ["failed.png", "character.png", "scene.png", "mask.png"])

    assert output == "515"
    assert result["501"]["inputs"]["image"] == "failed.png"
    assert result["502"]["inputs"]["image"] == "character.png"
    assert result["503"]["inputs"]["image"] == "scene.png"
    assert result["485"]["inputs"]["images.image_1"] == ["502", 0]
    assert result["485"]["inputs"]["images.image_2"] == ["503", 0]
    assert result["801"]["inputs"]["pixels"] == ["501", 0]
    assert result["801"]["inputs"]["mask"] == ["800", 0]
    assert result["802"]["inputs"]["latent_image"] == ["801", 2]
    assert "504" not in result and "482" not in result


def test_repair_candidate_is_reviewed_as_a_shot_without_becoming_a_generation_task():
    task = Task(type="shot_image_repair_candidate", status="running", result_url="/api/files/candidate.png",
                prompt_text="五个人", novel_id="novel", chapter_id="chapter", shot_id="shot")
    snapshot = build_review_input(task, generation_review=True)
    assert snapshot["task_type"] == "shot_image"
    assert snapshot["generated_image"] == "/api/files/candidate.png"
