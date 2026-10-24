"""Stage, review, and (when needed) clean scene references before publishing."""

import json
from datetime import datetime
from pathlib import Path

from app.models.novel import Novel
from app.models.image_quality_review import ImageQualityReview
from app.repositories import PromptTemplateRepository, WorkflowRepository
from app.services.background_workers import ensure_task_active, resume_image_prompt, save_image_prompt
from app.services.comfyui.errors import persist_task_comfyui_error
from app.services.file_storage import file_storage
from app.services.image_quality_review import execute_image_review, review_image_task
from app.services.prompt_builder import build_scene_prompt, get_style
from app.utils.path_utils import url_to_local_path


MAX_SCENE_CYCLES = 3
SCENE_EMPTY_REQUIREMENT = (
    "Scene reference asset requirement: EMPTY ENVIRONMENT ONLY. ZERO visible people, "
    "including distant figures, silhouettes, riders and crowds. Preserve the setting as "
    "a clean background plate for later character compositing.\n"
)
CLEANUP_PROMPT = (
    "Edit this scene reference image into an EMPTY ENVIRONMENT PLATE. Remove every visible "
    "person, human figure, silhouette, face, body, crowd, guard and rider, including tiny "
    "distant figures and people in windows or doorways. Reconstruct the background naturally "
    "where they stood. Preserve the same camera angle, architecture, terrain, props, lighting, "
    "colors and art style. Add no new people and no text. The final image must contain ZERO people."
)


def _metadata(task):
    try:
        value = json.loads(task.metadata_json or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _save_state(db, task, state):
    metadata = _metadata(task)
    metadata["scene_quality"] = state
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    db.commit()


def _reset_receipt(db, task):
    metadata = _metadata(task)
    metadata.pop("image_attempt", None)
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
    task.comfyui_prompt_id = None
    task.workflow_json = None
    db.commit()


async def _save_candidate(db, task, image_url, name, cycle, kind):
    if not image_url:
        raise RuntimeError("ComfyUI 未返回场景图片")
    task.current_step = f"第 {cycle} 轮：保存{'清理后' if kind == 'edit' else '生成的'}场景候选图"
    db.commit()
    path = await file_storage.download_image(
        image_url, task.novel_id or "default", f"{name}_{task.id[:8]}_round{cycle}_{kind}",
        image_type="scene_edit" if kind == "edit" else "scene",
    )
    if not path:
        raise RuntimeError("场景候选图下载失败，未发布未验证图片")
    relative = Path(path).relative_to(file_storage.base_dir).as_posix()
    return f"/api/files/{relative}"


async def _generate(db, task, scene, service, cycle):
    if task.comfyui_prompt_id:
        return await resume_image_prompt(db, task, service)

    workflow = WorkflowRepository(db).get_active_by_type("scene")
    try:
        mapping = json.loads(workflow.node_mapping or "{}") if workflow else None
    except (TypeError, ValueError) as exc:
        raise RuntimeError("场景生图工作流节点映射无效") from exc
    novel = db.get(Novel, task.novel_id)
    template = PromptTemplateRepository(db).resolve_for_type(
        novel.scene_prompt_template_id if novel else None, "scene",
    )
    style, _ = get_style(db, novel, "scene")
    prompt = SCENE_EMPTY_REQUIREMENT + build_scene_prompt(
        scene.name, scene.setting, "", template.template if template else None, style,
    )
    if cycle > 1:
        prompt += "\nPrevious scene attempt did not pass review. This is an environment-only asset: ZERO visible people anywhere in the frame."
    task.prompt_text = prompt
    task.workflow_id = workflow.id if workflow else None
    task.workflow_name = workflow.name if workflow else None
    task.current_step = f"第 {cycle}/{MAX_SCENE_CYCLES} 轮：ComfyUI 生成场景图"
    task.progress = min(10 + (cycle - 1) * 28, 75)
    db.commit()
    graph = service.builder.build_scene_workflow(
        prompt=prompt, workflow_json=workflow.workflow_json if workflow else None,
        novel_id=task.novel_id, scene_name=scene.name,
        aspect_ratio=novel.aspect_ratio if novel else None,
        node_mapping=mapping, style=style,
    )

    def queued(prompt_id, submitted_workflow=None):
        save_image_prompt(db, task, prompt_id, submitted_workflow or graph,
                          mapping.get("save_image_node_id") if mapping else None, reserve_retry=True)

    return await service.generate_scene_image(
        prompt, workflow_json=workflow.workflow_json if workflow else None, novel_id=task.novel_id,
        scene_name=scene.name, aspect_ratio=novel.aspect_ratio if novel else None,
        node_mapping=mapping, workflow=graph, on_prompt_queued=queued,
    )


async def _edit(db, task, scene, service, state):
    if task.comfyui_prompt_id:
        return await resume_image_prompt(db, task, service)

    source = url_to_local_path(state["candidate_url"])
    if not source:
        raise RuntimeError("待清理场景候选图不存在")
    workflow = WorkflowRepository(db).get_active_by_type("single_image_edit")
    if not workflow:
        raise RuntimeError("未配置单图编辑工作流，无法清理场景参考图")
    try:
        mapping = json.loads(workflow.node_mapping or "{}")
    except (TypeError, ValueError) as exc:
        raise RuntimeError("单图编辑工作流节点映射无效") from exc
    for field in ("load_image_node_id", "prompt_node_id", "save_image_node_id"):
        if not mapping.get(field):
            raise RuntimeError(f"单图编辑工作流缺少 {field} 节点映射")
    task.workflow_id = workflow.id
    task.workflow_name = workflow.name
    task.current_step = f"第 {state['cycle']}/{MAX_SCENE_CYCLES} 轮：清理场景参考图中的人物"
    task.progress = min(18 + (state["cycle"] - 1) * 28, 83)
    db.commit()

    def queued(prompt_id, graph):
        save_image_prompt(db, task, prompt_id, graph, mapping["save_image_node_id"], reserve_retry=True)

    return await service.edit_image_with_workflow(
        image_path=source, prompt=CLEANUP_PROMPT, workflow_json=workflow.workflow_json,
        node_mapping=mapping, on_prompt_queued=queued,
    )


async def _review(db, task, state, kind):
    task.result_url = state["candidate_url"] if kind == "generated" else state["cleaned_url"]
    task.current_step = f"第 {state['cycle']}/{MAX_SCENE_CYCLES} 轮：AI 审核{'清理后' if kind == 'cleaned' else '生成的'}场景图"
    task.progress = min((25 if kind == "generated" else 33) + (state["cycle"] - 1) * 28, 95)
    db.commit()
    review = await review_image_task(db, task.id, trigger="generation")
    ensure_task_active(db, task)
    if review.status == "running":
        # The scene worker is the sole inline reviewer for a running scene task.
        # A running record here is from an interrupted backend process.
        db.query(ImageQualityReview).filter_by(id=review.id, status="running").update(
            {"status": "pending"}, synchronize_session=False,
        )
        db.commit()
        review = await execute_image_review(db, review.id)
        ensure_task_active(db, task)
    if review.status != "success":
        raise RuntimeError(f"场景图 AI 审核未完成：{review.error_message or review.status}")
    dimensions = json.loads(review.dimensions_json or "{}")
    count = dimensions.get("CHARACTER_COUNT") or {}
    result = {"review_id": review.id, "overall": review.overall,
              "character_count": count.get("status"), "summary": review.summary}
    return result


def _complete(db, task, scene, state, image_url):
    if (scene.scene_task_id and scene.scene_task_id != task.id) or scene.image_url != state["original_url"]:
        raise RuntimeError("场景图片已被用户替换，审核通过的候选图未覆盖当前素材")
    scene.image_url = image_url
    scene.generating_status = "completed"
    task.result_url = image_url
    task.status = "completed"
    task.progress = 100
    task.current_step = "场景图通过 AI 审核并已发布"
    task.completed_at = datetime.utcnow()
    _save_state(db, task, state)


async def run_scene_quality_pipeline(db, task, scene, service):
    """Three durable generate → review → optional clean → review cycles."""
    metadata = _metadata(task)
    state = metadata.get("scene_quality")
    if not isinstance(state, dict):
        state = {"cycle": 1, "stage": "generate", "original_url": scene.image_url,
                 "attempts": []}
        _save_state(db, task, state)
    if task.status == "pending":
        task.status = "running"
        task.started_at = task.started_at or datetime.utcnow()
        if scene.scene_task_id == task.id:
            scene.generating_status = "running"
        db.commit()

    while state["cycle"] <= MAX_SCENE_CYCLES:
        ensure_task_active(db, task)
        if (scene.scene_task_id and scene.scene_task_id != task.id) or scene.image_url != state["original_url"]:
            raise RuntimeError("场景图片已被用户替换，停止自动生成以保护当前素材")
        cycle = state["cycle"]
        if len(state["attempts"]) < cycle:
            state["attempts"].append({"cycle": cycle})
            _save_state(db, task, state)
        attempt = state["attempts"][cycle - 1]
        stage = state["stage"]

        if stage == "generate":
            result = await _generate(db, task, scene, service, cycle)
            ensure_task_active(db, task)
            persist_task_comfyui_error(task, result)
            if not result.get("success"):
                raise RuntimeError(result.get("message") or "场景图生成失败")
            state["candidate_url"] = await _save_candidate(db, task, result.get("image_url"), scene.name, cycle, "generate")
            attempt["generated_url"] = state["candidate_url"]
            attempt["generation_prompt_id"] = task.comfyui_prompt_id
            state["stage"] = "generated_review"
            _save_state(db, task, state)
            continue

        if stage == "generated_review":
            verdict = await _review(db, task, state, "generated")
            attempt["generated_review"] = verdict
            _save_state(db, task, state)
            if verdict["overall"] == "PASS" and verdict["character_count"] == "PASS":
                _complete(db, task, scene, state, state["candidate_url"])
                return
            if verdict["character_count"] != "PASS":
                state["stage"] = "edit"
            else:
                state["stage"] = "next_cycle"
            _reset_receipt(db, task)
            _save_state(db, task, state)
            continue

        if stage == "edit":
            result = await _edit(db, task, scene, service, state)
            ensure_task_active(db, task)
            persist_task_comfyui_error(task, result)
            if not result.get("success"):
                raise RuntimeError(result.get("message") or "清理场景参考图失败")
            state["cleaned_url"] = await _save_candidate(db, task, result.get("image_url"), scene.name, cycle, "edit")
            attempt["cleaned_url"] = state["cleaned_url"]
            attempt["cleanup_prompt_id"] = task.comfyui_prompt_id
            state["stage"] = "edited_review"
            _save_state(db, task, state)
            continue

        if stage == "edited_review":
            verdict = await _review(db, task, state, "cleaned")
            attempt["cleaned_review"] = verdict
            _save_state(db, task, state)
            if verdict["overall"] == "PASS" and verdict["character_count"] == "PASS":
                _complete(db, task, scene, state, state["cleaned_url"])
                return
            state["stage"] = "next_cycle"
            _save_state(db, task, state)
            continue

        if stage == "next_cycle":
            state.pop("candidate_url", None)
            state.pop("cleaned_url", None)
            state["cycle"] += 1
            state["stage"] = "generate"
            _reset_receipt(db, task)
            _save_state(db, task, state)
            continue

        raise RuntimeError(f"未知场景审核阶段：{stage}")

    raise RuntimeError(f"场景图经过 {MAX_SCENE_CYCLES} 轮生成、清理和 AI 审核仍未通过；保留原场景图")
