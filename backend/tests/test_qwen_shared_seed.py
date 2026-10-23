import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.task import Task
from app.services.background_workers import save_image_prompt, saved_image_attempt
from app.services.comfyui.service import ComfyUIService
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.task_service import TaskService
from app.utils.workflow_seed import extract_workflow_seed, randomize_prompt_rewrite_seeds


def graph():
    return {
        "519": {"class_type": "QwenPERewriteT8", "inputs": {"seed": 42, "user_prompt": ["516", 0]}, "_meta": {"title": "#498 Qwen Image 2.1 PE Rewrite T8"}},
        "482": {"class_type": "KSampler", "inputs": {"seed": 900}},
        "516": {"class_type": "CR Prompt Text", "inputs": {"prompt": "original"}},
        "515": {"class_type": "SaveImage", "inputs": {}},
    }


def test_new_runs_randomize_one_common_legal_seed_without_changing_template(monkeypatch):
    seeds = iter([2**31 + 101, 2**31 + 102])
    monkeypatch.setattr("app.services.comfyui.workflows.random.randint", lambda *_: next(seeds))
    template = json.dumps(graph())
    builder = WorkflowBuilder()
    runs = [builder.build_shot_workflow("new prompt", template, {"prompt_node_id": "516"}) for _ in range(2)]
    for run, expected in zip(runs, [101, 102]):
        assert run["519"]["inputs"]["seed"] == run["482"]["inputs"]["seed"] == expected
        assert run["519"]["inputs"]["user_prompt"] == ["516", 0]
        assert extract_workflow_seed(run) == expected
    assert json.loads(template)["519"]["inputs"]["seed"] == 42


@pytest.mark.asyncio
async def test_prepared_graph_first_submission_and_receipt_share_sampler_seed():
    service = ComfyUIService.__new__(ComfyUIService)
    service.builder = WorkflowBuilder()
    service.client = MagicMock()
    submitted = []
    async def queue(workflow):
        submitted.append(json.loads(json.dumps(workflow)))
        return {"success": True, "prompt_id": "first"}
    service.client.queue_prompt = AsyncMock(side_effect=queue)
    service.client.wait_for_result = AsyncMock(return_value={"success": True, "image_url": "/image.png"})
    receipts = []
    result = await service.generate_shot_image_with_workflow(
        "test", "{}", {"save_image_node_id": "515"}, workflow=graph(),
        on_prompt_queued=lambda pid, workflow: receipts.append((pid, extract_workflow_seed(workflow))),
    )
    assert result["success"]
    assert submitted[0]["519"]["inputs"]["seed"] == submitted[0]["482"]["inputs"]["seed"] == 900
    assert result["submitted_workflow"] == submitted[0]
    assert receipts == [("first", 900)]


def test_retry_uses_one_different_seed_even_when_random_draw_collides(monkeypatch):
    workflow = graph()
    workflow["482"]["inputs"]["seed"] = 42
    workflow["noise"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": 42}}
    monkeypatch.setattr("app.utils.workflow_seed.random.randint", lambda *_: 42)
    assert randomize_prompt_rewrite_seeds(workflow)
    assert extract_workflow_seed(workflow) == 43
    assert workflow["519"]["inputs"]["seed"] == workflow["482"]["inputs"]["seed"] == workflow["noise"]["inputs"]["noise_seed"] == 43


def test_image_receipt_persists_shared_seed_for_task_list(db_session):
    task = Task(id="image-seed", type="shot_image", name="Shot", status="running")
    db_session.add(task)
    db_session.commit()
    workflow = graph()
    WorkflowBuilder()._set_random_seed(workflow, 1001)
    save_image_prompt(db_session, task, "prompt", workflow, "515")
    db_session.expire_all()
    assert task.seed == 1001
    saved, _ = saved_image_attempt(task)
    assert saved["519"]["inputs"]["seed"] == saved["482"]["inputs"]["seed"] == 1001
    assert TaskService.format_task_list([task], {}, {}, {})[0]["seed"] == 1001


def test_historical_images_display_real_sampler_seed_without_rewriting_history():
    workflow = graph()
    task = Task(id="old-image", type="shot_image", name="Shot", status="completed", workflow_json=json.dumps(workflow))
    listed = TaskService.format_task_list([task], {}, {}, {})[0]
    assert listed["seed"] == TaskService.format_task_detail(task)["seed"] == 900
    assert json.loads(task.workflow_json)["519"]["inputs"]["seed"] == 42


def test_zero_seed_and_ambiguous_sampler_seeds_are_not_misreported():
    task = Task(id="zero", type="shot_image", name="Shot", status="completed", seed=0)
    assert TaskService.format_task_list([task], {}, {}, {})[0]["seed"] == 0
    workflow = graph()
    workflow["other"] = {"class_type": "KSampler", "inputs": {"seed": 901}}
    assert extract_workflow_seed(workflow) is None
