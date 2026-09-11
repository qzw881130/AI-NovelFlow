"""
分镜图生成服务

封装分镜图片生成的后台任务逻辑
"""

import asyncio
from copy import deepcopy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import urlencode
from uuid import uuid4

from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.task import Task
from app.models.workflow import Workflow
from app.core.database import SessionLocal
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.services.prompt_builder import get_style
from app.utils.path_utils import local_path_to_url, url_to_local_path
from app.utils.image_utils import merge_character_images, merge_prop_images
from app.repositories.shot_repository import ShotRepository
from app.services.background_workers import worker_manager
from app.utils.workflow_disconnect import disconnect_reference_chain


def _is_task_cancelled(db, task) -> bool:
    db.refresh(task)
    return task.status == "cancelled"


def enqueue_shot_image_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    shot_description: str,
    workflow_id: str,
) -> None:
    """Queue shot image generation in its dedicated serial worker."""
    worker_manager.worker("shot_image").enqueue(
        lambda: generate_shot_image_task(
            task_id,
            novel_id,
            chapter_id,
            shot_index,
            shot_description,
            workflow_id,
        )
    )


async def generate_shot_image_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    shot_description: str,
    workflow_id: str,
):
    """
    后台任务：生成分镜图片

    Args:
        task_id: 任务ID
        novel_id: 小说ID
        chapter_id: 章节ID
        shot_index: 分镜索引
        shot_description: 分镜描述
        workflow_id: 工作流ID
    """
    db = SessionLocal()
    production_path = False
    try:
        # 获取任务
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        from app.services.task_execution import is_benchmark
        if is_benchmark(task):
            await generate_benchmark_shot_image_task(db, task)
            return
        production_path = True
        if task.status == "cancelled":
            return

        # 更新任务状态为运行中
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.current_step = "准备生成环境..."
        db.commit()

        # 获取章节和小说
        chapter = (
            db.query(Chapter)
            .filter(Chapter.id == chapter_id, Chapter.novel_id == novel_id)
            .first()
        )

        if not chapter:
            task.status = "failed"
            task.error_message = "章节不存在"
            db.commit()
            return

        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        if not novel:
            task.status = "failed"
            task.error_message = "小说不存在"
            db.commit()
            return

        # 使用 ShotRepository 获取分镜数据
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)

        if not shot:
            task.status = "failed"
            task.error_message = "分镜不存在"
            db.commit()
            return

        # 从 Shot 模型获取分镜数据
        shot_characters = json.loads(shot.characters) if shot.characters else []
        shot_scene = shot.scene or ""
        shot_props = json.loads(shot.props) if shot.props else []

        print(
            f"[ShotTask {task_id}] Novel: {novel_id}, Chapter: {chapter_id}, Shot: {shot_index}"
        )
        print(f"[ShotTask {task_id}] Description: {shot_description}")
        print(f"[ShotTask {task_id}] Characters: {shot_characters}")
        print(f"[ShotTask {task_id}] Props: {shot_props}")

        # 获取工作流
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            task.status = "failed"
            task.error_message = "工作流不存在"
            db.commit()
            return

        # 获取节点映射
        node_mapping = (
            json.loads(workflow.node_mapping) if workflow.node_mapping else {}
        )
        print(f"[ShotTask {task_id}] Node mapping: {node_mapping}")

        # 获取风格提示词
        style, _ = get_style(db, novel, "character")
        from app.services.video_director_ai import build_visual_identity_context
        visual_identity = build_visual_identity_context(db, novel.id, shot_characters, shot_props, style)
        shot_characters = visual_identity["characters"]
        metadata = json.loads(task.metadata_json or "{}")
        metadata["visual_identity"] = visual_identity
        task.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()
        print(f"[ShotTask {task_id}] Using style: {style}")

        comfyui_service = ComfyUIService()

        # 合并角色图片
        character_reference_path = await _process_character_references(
            db, task, novel_id, chapter_id, shot_index, shot_characters, task_id, shot_repo
        )

        # 处理场景图
        scene_reference_path = await _process_scene_reference(
            db, task, novel_id, shot_scene, task_id
        )

        # 处理道具图
        prop_reference_paths = await _process_prop_references(
            db, task, novel_id, chapter_id, shot_index, shot_props, task_id, shot_repo
        )

        effective_prompt = shot_description
        task.prompt_text = effective_prompt
        db.commit()

        # ========== 查询角色/场景/道具的描述信息（用于占位符替换） ==========
        # 查询角色外貌描述
        character_appearances = visual_identity["character_appearances"]
        print(f"[ShotTask {task_id}] Character appearances: {character_appearances}")

        # 查询场景设定
        scene_setting = None
        if shot_scene:
            scene = (
                db.query(Scene)
                .filter(Scene.novel_id == novel_id, Scene.name == shot_scene)
                .first()
            )
            if scene and scene.setting:
                scene_setting = scene.setting
        print(f"[ShotTask {task_id}] Scene setting: {scene_setting}")

        # 查询道具外观
        prop_appearances = visual_identity["prop_appearances"]
        print(f"[ShotTask {task_id}] Prop appearances: {prop_appearances}")

        # 构建工作流
        task.current_step = "构建工作流..."
        db.commit()

        submitted_workflow = comfyui_service.builder.build_shot_workflow(
            prompt=effective_prompt,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            style=style,
            character_appearances=character_appearances,
            scene_setting=scene_setting,
            prop_appearances=prop_appearances,
        )

        # 上传参考图并更新工作流
        await _upload_references_and_update_workflow(
            comfyui_service,
            submitted_workflow,
            node_mapping,
            character_reference_path,
            scene_reference_path,
            task,
            db,
            task_id,
            prop_reference_paths=prop_reference_paths,
        )

        # 调用 ComfyUI 生成图片
        if _is_task_cancelled(db, task):
            return
        task.current_step = "正在调用 ComfyUI 生成图片..."
        task.progress = 30
        db.commit()

        def save_prompt_id(prompt_id: str):
            task.comfyui_prompt_id = prompt_id
            db.commit()
            print(f"[ShotTask {task_id}] Saved ComfyUI prompt_id: {prompt_id}")

        result = await comfyui_service.generate_shot_image_with_workflow(
            prompt=effective_prompt,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            character_reference_path=None,
            scene_reference_path=None,
            workflow=submitted_workflow,
            style=style,
            on_prompt_queued=save_prompt_id,
        )

        print(f"[ShotTask {task_id}] Generation result: {json.dumps(result, ensure_ascii=True)}")

        if _is_task_cancelled(db, task):
            return

        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]

        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(
                result["submitted_workflow"], ensure_ascii=False, indent=2
            )
            db.commit()

        if not result.get("success"):
            task.status = "failed"
            task.error_message = result.get("message", "生成失败")
            task.current_step = "生成失败"
            db.commit()
            return

        # 下载并保存生成的图片
        await _save_generated_image(
            result, task, chapter, novel_id, chapter_id, shot_index, db, task_id, shot.id, shot_repo
        )

    except Exception as e:
        print(f"[ShotTask {task_id}] Error: {e}")
        import traceback

        traceback.print_exc()

        if not production_path:
            return
        try:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ==================== 辅助函数 ====================


def _image_graph_hash(graph):
    return hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _image_semantic_graph_hash(graph, *, code="BENCHMARK_IMAGE_SUBMISSION_UNVERIFIED"):
    from app.services.keyframe_reference_graph import KeyframeGraphError, numeric_graph_digest
    from app.services.task_execution import ExecutionConflict
    try:
        return numeric_graph_digest(graph)
    except KeyframeGraphError as exc:
        raise ExecutionConflict(code) from exc


def _benchmark_image_error(db, task, shot, error, *, artifact_url=None, source_url=None):
    from app.services.task_execution import ExecutionConflict, persist_execution_state, record_execution_observation
    task_id = shot._execution_task_id
    try:
        persist_execution_state(db, task, shot, {"failure": {"message": str(error), "source_url": source_url}},
                                status="failed", error_message=str(error), current_step="Benchmark image failed",
                                completed_at=datetime.utcnow())
    except ExecutionConflict:
        pass
    record_execution_observation(db, task_id, shot, error, artifact_url=artifact_url, source_url=source_url)


async def _archive_benchmark_shot_image(db, task, shot, source_url):
    from app.services.task_execution import artifact_directory, assert_execution_active, persist_execution_state
    from app.services.shot_keyframe_service import ShotKeyframeService
    assert_execution_active(db, task, shot)
    destination = artifact_directory(task) / f"image-{uuid4().hex}.png"
    local_url = None
    try:
        local_path = await file_storage.download_image(
            url=source_url, novel_id=task.novel_id, character_name=f"shot_{shot.id}",
            image_type="shot", chapter_id=task.chapter_id, destination=destination,
        )
        if not local_path:
            raise RuntimeError("BENCHMARK_IMAGE_DOWNLOAD_FAILED")
        if Path(local_path).resolve() != destination.resolve():
            raise RuntimeError("BENCHMARK_IMAGE_DESTINATION_CHANGED")
        local_url = local_path_to_url(local_path)
        _, payload = ShotKeyframeService._read_reference_payload(local_url)
        shot.image_url, shot.image_path = local_url, str(local_path)
        shot.image_task_id, shot.image_status = task.id, "completed"
        persist_execution_state(db, task, shot, {"result": {
            "url": local_url, "local_path": str(local_path), "source_url": source_url,
            "sha256": hashlib.sha256(payload).hexdigest(), "attachment": "archived",
        }}, status="completed", progress=100, result_url=local_url, error_message=None,
            current_step="Benchmark image archived", completed_at=datetime.utcnow())
        return True
    except asyncio.CancelledError:
        _benchmark_image_error(db, task, shot, "BENCHMARK_WORKER_INTERRUPTED", artifact_url=local_url, source_url=source_url)
        raise
    except Exception as exc:
        _benchmark_image_error(db, task, shot, exc, artifact_url=local_url, source_url=source_url)
        return False


def _benchmark_image_proof(task):
    from app.services.task_execution import ExecutionConflict, execution_record, is_benchmark
    if not is_benchmark(task):
        raise ExecutionConflict("BENCHMARK_PURPOSE_REQUIRED")
    record = execution_record(task)
    proof = record.get("shot_image", {})
    if (task.type != "shot_image" or not task.comfyui_prompt_id or proof.get("submission_state") != "submitted"
            or proof.get("prompt_id") != task.comfyui_prompt_id or task.prompt_text != proof.get("prompt_text")
            or not task.workflow_json):
        raise ExecutionConflict("BENCHMARK_IMAGE_SUBMISSION_UNVERIFIED")
    graph = json.loads(task.workflow_json)
    if _image_graph_hash(graph) != proof.get("graph_hash"):
        raise ExecutionConflict("BENCHMARK_IMAGE_SUBMISSION_UNVERIFIED")
    semantic_hash = _image_semantic_graph_hash(graph)
    if proof.get("semantic_graph_hash", semantic_hash) != semantic_hash:
        raise ExecutionConflict("BENCHMARK_IMAGE_SUBMISSION_UNVERIFIED")
    # Old receipts retain their raw hash; derive this comparison fact without a write.
    return {**proof, "semantic_graph_hash": semantic_hash}


def _benchmark_shot_image_output(task, history):
    from app.services.task_execution import ExecutionConflict
    proof = _benchmark_image_proof(task)
    # #06 can bind multiple references: compare all graph content, not a #09 profile/cache key.
    submitted = history.get("prompt") if isinstance(history, dict) else None
    if (not isinstance(submitted, list) or len(submitted) < 3 or submitted[1] != proof["prompt_id"]
            or _image_semantic_graph_hash(submitted[2], code="BENCHMARK_IMAGE_HISTORY_MISMATCH") != proof["semantic_graph_hash"]):
        raise ExecutionConflict("BENCHMARK_IMAGE_HISTORY_MISMATCH")
    status = history.get("status") or {}
    if status.get("status_str") == "error" or not (status.get("completed") is True or status.get("status_str") in {"success", "completed"}):
        raise ExecutionConflict("BENCHMARK_IMAGE_NOT_COMPLETED")
    output = (history.get("outputs") or {}).get(proof["output_node_id"], {})
    images = output.get("images") if isinstance(output, dict) else None
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
        raise ExecutionConflict("BENCHMARK_IMAGE_OUTPUT_UNCERTAIN")
    image = images[0]
    name, folder = image.get("filename"), image.get("subfolder", "")
    if (not isinstance(name, str) or not name or "/" in name or "\\" in name or name in {".", ".."}
            or not isinstance(folder, str) or "\\" in folder or folder.startswith("/") or ".." in folder.split("/")
            or image.get("type") != "output"):
        raise ExecutionConflict("BENCHMARK_IMAGE_OUTPUT_LOCATOR_INVALID")
    return proof["endpoint"].rstrip("/") + "/view?" + urlencode({"filename": name, "subfolder": folder, "type": "output"})


async def recover_benchmark_shot_image(db, task, prompt_history):
    """TaskService hook: archive frozen #06 history without touching production."""
    from app.services.task_execution import execution_record, is_benchmark, load_execution_shot
    if task.type != "shot_image" or not is_benchmark(task):
        return False
    task = db.query(Task).filter(Task.id == task.id).populate_existing().first()
    if not task or not is_benchmark(task) or task.status not in {"running", "completed"}:
        return False
    shot = load_execution_shot(task)
    result = execution_record(task).get("result", {})
    try:
        if task.status == "completed":
            _benchmark_image_proof(task)
            return bool(result.get("attachment") == "archived" and result.get("url") == task.result_url and task.result_url)
        source_url = _benchmark_shot_image_output(task, prompt_history)
    except Exception as exc:
        _benchmark_image_error(db, task, shot, exc)
        return False
    return await _archive_benchmark_shot_image(db, task, shot, source_url)


async def generate_benchmark_shot_image_task(db, task):
    """The existing queue entry dispatches here only for explicit benchmarks."""
    from app.services.file_storage import FileStorageService
    from app.services.keyframe_reference_contract import frozen_keyframe_client
    from app.services.task_execution import (
        artifact_directory, assert_execution_active, is_benchmark, load_execution_shot,
        persist_execution_shot, persist_execution_state, record_execution_observation,
    )
    if not is_benchmark(task) or task.status != "pending":
        return
    shot = load_execution_shot(task)
    task_id = task.id
    try:
        prompt = task.prompt_text
        if not isinstance(prompt, str) or not prompt.strip():
            raise RuntimeError("BENCHMARK_FINAL_PROMPT_REQUIRED")
        shot.shot_image_prompt = prompt
        persist_execution_shot(db, task, shot, status="running", started_at=datetime.utcnow(), current_step="Preparing benchmark image")
        novel = db.query(Novel).filter(Novel.id == task.novel_id).first()
        workflow = db.query(Workflow).filter(Workflow.id == task.workflow_id).first()
        if not novel or not workflow:
            raise RuntimeError("BENCHMARK_INPUT_NOT_FOUND")
        mapping = json.loads(workflow.node_mapping or "{}")
        service = ComfyUIService()
        client = frozen_keyframe_client(service.client.base_url)
        style, _ = get_style(db, novel, "character")
        from app.services.video_director_ai import build_visual_identity_context
        visual_identity = build_visual_identity_context(db, novel.id, json.loads(shot.characters or "[]"), json.loads(shot.props or "[]"), style)
        root = artifact_directory(task)
        # Legacy merge utilities may glob-delete old composites. Give them a fresh private storage root.
        references_storage = FileStorageService(base_dir=root / "references" / uuid4().hex)
        references, source_records = {}, []
        scene_setting = None
        for model, names, role, merge in (
            (Character, visual_identity["characters"], "character", merge_character_images),
            (Scene, [shot.scene] if shot.scene else [], "scene", None),
            (Prop, json.loads(shot.props or "[]"), "prop", merge_prop_images),
        ):
            images = []
            for name in names:
                entity = db.query(model).filter(model.novel_id == task.novel_id, model.name == name).first()
                if not entity:
                    continue
                if role == "scene":
                    scene_setting = entity.setting
                path = url_to_local_path(entity.image_url) if entity.image_url else None
                if path:
                    payload = Path(path).read_bytes()
                    captured = references_storage.base_dir / f"input-{uuid4().hex}{Path(path).suffix or '.png'}"
                    with captured.open("xb") as output:
                        output.write(payload)
                    images.append((name, str(captured)))
                    source_records.append({"role": role, "name": name, "source_url": entity.image_url,
                                           "url": local_path_to_url(str(captured)), "sha256": hashlib.sha256(payload).hexdigest()})
            if not images:
                continue
            path = merge(task.novel_id, task.chapter_id, shot.index, images, references_storage) if merge and (role == "character" or len(images) > 1) else images[0][1]
            if not path:
                raise RuntimeError("BENCHMARK_REFERENCE_MERGE_FAILED")
            references[role] = {"label": role, "url": local_path_to_url(str(path)), "path": str(path)}
            if role in {"character", "prop"}:
                setattr(shot, f"merged_{role}_image", references[role]["url"])
        persist_execution_state(db, task, shot, {"reference_sources": source_records, "visual_identity": visual_identity})
        graph = service.builder.build_shot_workflow(
            prompt=prompt, workflow_json=workflow.workflow_json, node_mapping=mapping,
            aspect_ratio=novel.aspect_ratio or "16:9", style=style,
            character_appearances=visual_identity["character_appearances"], scene_setting=scene_setting, prop_appearances=visual_identity["prop_appearances"],
        )
        by_key = {f"{role}_reference_image_node_id": value for role, value in references.items()}
        custom = _get_first_custom_reference_node_key(mapping)
        if custom and "prop" in references:
            by_key[custom] = references["prop"]
        visible = []
        for key in _get_compact_reference_node_keys(mapping):
            node_id = str(mapping[key])
            item = by_key.get(key)
            if node_id not in graph:
                continue
            if item:
                assert_execution_active(db, task, shot)
                receipt = await client.upload_image(item["path"])
                assert_execution_active(db, task, shot)
                if not receipt.get("success") or not receipt.get("filename"):
                    raise RuntimeError("BENCHMARK_REFERENCE_UPLOAD_FAILED")
                graph[node_id]["inputs"]["image"] = receipt["filename"]
                visible.append({"label": item["label"], "url": item["url"]})
            else:
                graph[node_id]["inputs"]["image"] = ""
                disconnect_reference_chain(graph, node_id)
        output_id = str(mapping.get("save_image_node_id") or mapping.get("output_node_id") or "")
        if not output_id or graph.get(output_id, {}).get("class_type") != "SaveImage":
            raise RuntimeError("BENCHMARK_IMAGE_OUTPUT_UNVERIFIED")
        graph_hash, semantic_hash = _image_graph_hash(graph), _image_semantic_graph_hash(graph)
        proof = {"endpoint": client.base_url, "output_node_id": output_id, "graph_hash": graph_hash, "semantic_graph_hash": semantic_hash,
                 "prompt_text": prompt, "submission_state": "attempted", "node_mapping": deepcopy(mapping)}
        persist_execution_state(db, task, shot, {"shot_image": proof}, workflow_json=json.dumps(graph, ensure_ascii=False),
                                reference_images=json.dumps(visible, ensure_ascii=False), progress=30, current_step="Submitting benchmark image")
        queued = await client.queue_prompt(graph)
        prompt_id = queued.get("prompt_id")
        if not queued.get("success") or not isinstance(prompt_id, str) or not prompt_id.strip():
            raise RuntimeError("BENCHMARK_IMAGE_SUBMISSION_UNCONFIRMED")
        proof.update(submission_state="submitted", prompt_id=prompt_id)
        try:
            persist_execution_state(db, task, shot, {"shot_image": proof}, comfyui_prompt_id=prompt_id)
        except Exception as exc:
            record_execution_observation(db, task_id, shot, exc, details={
                "prompt_id": prompt_id, "endpoint": proof["endpoint"], "graph_hash": proof["graph_hash"], "workflow": graph,
            })
            raise
        deadline = asyncio.get_running_loop().time() + 7200
        while asyncio.get_running_loop().time() < deadline:
            assert_execution_active(db, task, shot)
            state = await client.get_prompt_state(prompt_id)
            assert_execution_active(db, task, shot)
            if state.get("state") == "completed":
                source_url = _benchmark_shot_image_output(task, state.get("history"))
                await _archive_benchmark_shot_image(db, task, shot, source_url)
                return
            if state.get("state") in {"error", "missing"}:
                raise RuntimeError(state.get("message") or "BENCHMARK_IMAGE_JOB_UNAVAILABLE")
            await asyncio.sleep(2)
        raise RuntimeError("BENCHMARK_IMAGE_TIMEOUT")
    except asyncio.CancelledError:
        _benchmark_image_error(db, task, shot, "BENCHMARK_WORKER_INTERRUPTED")
        raise
    except Exception as exc:
        _benchmark_image_error(db, task, shot, exc)


async def _process_character_references(
    db,
    task,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    shot_characters: list,
    task_id: str,
    shot_repo: ShotRepository = None,
) -> Optional[str]:
    """处理角色参考图片"""
    character_reference_path = None

    if not shot_characters:
        return None

    task.current_step = f"合并角色图片: {', '.join(shot_characters)}"
    db.commit()

    character_images = []
    print(
        f"[ShotTask {task_id}] Looking for {len(shot_characters)} characters: {shot_characters}"
    )

    for char_name in shot_characters:
        character = (
            db.query(Character)
            .filter(Character.novel_id == novel_id, Character.name == char_name)
            .first()
        )
        print(
            f"[ShotTask {task_id}] Character '{char_name}': found={character is not None}, has_image={character.image_url if character else None}"
        )
        if character and not character.is_narrator and character.name.casefold() not in {"narrator", "旁白"} and character.image_url:
            full_path = url_to_local_path(character.image_url)
            if not full_path or not Path(full_path).is_file():
                raise RuntimeError(f"角色参考图不可用: {char_name}；请修复或重新上传该图片后重试，未提交生成。")
            character_images.append((char_name, full_path))
            print(f"[ShotTask {task_id}] Found character image: {char_name} -> {full_path}")

    print(f"[ShotTask {task_id}] Total character images found: {len(character_images)}")

    if character_images:
        merged_path = merge_character_images(
            novel_id, chapter_id, shot_index, character_images, file_storage
        )

        if merged_path:
            character_reference_path = merged_path

            # 更新 Shot 记录中的合并角色图 URL
            _update_shot_merged_character_url(
                db, chapter_id, shot_index, merged_path, shot_repo
            )

            print(f"[ShotTask {task_id}] Merged character image saved: {merged_path}")
            task.current_step = f"已合并 {len(character_images)} 个角色图片"
            db.commit()
        else:
            raise RuntimeError(f"角色参考图合并失败: {', '.join(name for name, _ in character_images)}；请检查源图片后重试，未提交生成。")

    return character_reference_path


def _update_shot_merged_character_url(
    db, chapter_id: str, shot_index: int, merged_path: str, shot_repo: ShotRepository = None
):
    """更新 Shot 记录中合并角色图的 URL"""
    if shot_repo is None:
        shot_repo = ShotRepository(db)

    shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)
    if not shot:
        return

    merged_relative_path = (
        str(merged_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
    )
    merged_url = f"/api/files/{merged_relative_path.lstrip('/')}"

    shot_repo.update(shot, merged_character_image=merged_url)


async def _process_scene_reference(
    db, task, novel_id: str, shot_scene: str, task_id: str
) -> Optional[str]:
    """处理场景参考图片"""
    if not shot_scene:
        return None

    task.current_step = f"查找场景图: {shot_scene}"
    db.commit()

    scene = (
        db.query(Scene)
        .filter(Scene.novel_id == novel_id, Scene.name == shot_scene)
        .first()
    )

    print(
        f"[ShotTask {task_id}] Scene '{shot_scene}': found={scene is not None}, has_image={scene.image_url if scene else None}"
    )

    if scene and scene.image_url:
        full_path = url_to_local_path(scene.image_url)
        if not full_path or not Path(full_path).is_file():
            raise RuntimeError(f"场景参考图不可用: {shot_scene}；请修复或重新上传该图片后重试，未提交生成。")
        print(f"[ShotTask {task_id}] Found scene image: {shot_scene} -> {full_path}")
        return full_path

    return None


async def _process_prop_references(
    db,
    task,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    shot_props: list,
    task_id: str,
    shot_repo: ShotRepository = None,
) -> Optional[Dict[str, str]]:
    """
    处理道具参考图片

    Args:
        db: 数据库会话
        task: 任务对象
        novel_id: 小说 ID
        shot_props: 道具名称列表
        task_id: 任务 ID

    Returns:
        道具名称到图片路径的映射字典。多个道具时返回合并道具图。
    """
    if not shot_props:
        return None

    task.current_step = f"查找道具图: {', '.join(shot_props)}"
    db.commit()

    prop_images = []
    print(f"[ShotTask {task_id}] Looking for {len(shot_props)} props: {shot_props}")

    for prop_name in shot_props:
        prop = (
            db.query(Prop)
            .filter(Prop.novel_id == novel_id, Prop.name == prop_name)
            .first()
        )

        print(
            f"[ShotTask {task_id}] Prop '{prop_name}': found={prop is not None}, has_image={prop.image_url if prop else None}"
        )

        if prop and prop.image_url:
            full_path = url_to_local_path(prop.image_url)
            if not full_path or not Path(full_path).is_file():
                raise RuntimeError(f"道具参考图不可用: {prop_name}；请修复或重新上传该图片后重试，未提交生成。")
            prop_images.append((prop_name, full_path))
            print(f"[ShotTask {task_id}] Found prop image: {prop_name} -> {full_path}")

    print(f"[ShotTask {task_id}] Total prop images found: {len(prop_images)}")

    if not prop_images:
        return None

    if len(prop_images) == 1:
        task.current_step = "已找到 1 个道具图片"
        db.commit()
        return {prop_images[0][0]: prop_images[0][1]}

    task.current_step = f"合并道具图片: {', '.join(name for name, _ in prop_images)}"
    db.commit()

    merged_path = merge_prop_images(novel_id, chapter_id, shot_index, prop_images, file_storage)
    if merged_path:
        _update_shot_merged_prop_url(db, chapter_id, shot_index, merged_path, shot_repo)
        print(f"[ShotTask {task_id}] Merged prop image saved: {merged_path}")
        task.current_step = f"已合并 {len(prop_images)} 个道具图片"
        db.commit()
        return {"合并道具图": merged_path}

    raise RuntimeError(f"道具参考图合并失败: {', '.join(name for name, _ in prop_images)}；请检查源图片后重试，未提交生成。")


def _update_shot_merged_prop_url(
    db, chapter_id: str, shot_index: int, merged_path: str, shot_repo: ShotRepository = None
):
    """更新 Shot 记录中合并道具图的 URL"""
    if shot_repo is None:
        shot_repo = ShotRepository(db)

    shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)
    if not shot:
        return

    merged_relative_path = (
        str(merged_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
    )
    merged_url = f"/api/files/{merged_relative_path.lstrip('/')}"

    shot_repo.update(shot, merged_prop_image=merged_url)


async def _upload_references_and_update_workflow(
    comfyui_service,
    submitted_workflow: dict,
    node_mapping: dict,
    character_reference_path: Optional[str],
    scene_reference_path: Optional[str],
    task,
    db,
    task_id: str,
    prop_reference_paths: Optional[Dict[str, str]] = None,
):
    """
    上传参考图并更新工作流

    Args:
        comfyui_service: ComfyUI 服务实例
        submitted_workflow: 工作流字典
        node_mapping: 节点映射
        character_reference_path: 角色参考图路径
        scene_reference_path: 场景参考图路径
        task: 任务对象
        db: 数据库会话
        task_id: 任务 ID
        prop_reference_paths: 道具参考图路径字典 {道具名称: 图片路径}
    """
    task.current_step = "上传参考图..."
    db.commit()
    print(f"[ShotTask {task_id}] Uploading compact reference images before submission")

    reference_items_by_key = {}
    if character_reference_path:
        character_url = local_path_to_url(character_reference_path)
        if not character_url:
            raise RuntimeError("角色参考图路径不可用；请检查图片存储路径后重试，未提交生成。")
        reference_items_by_key["character_reference_image_node_id"] = {"label": "角色合并图", "url": character_url, "path": character_reference_path}
    if scene_reference_path:
        scene_url = local_path_to_url(scene_reference_path)
        if not scene_url:
            raise RuntimeError("场景参考图路径不可用；请检查图片存储路径后重试，未提交生成。")
        reference_items_by_key["scene_reference_image_node_id"] = {"label": "场景图", "url": scene_url, "path": scene_reference_path}
    if prop_reference_paths:
        prop_label = "、".join(prop_reference_paths.keys())
        prop_path = next((path for path in prop_reference_paths.values() if path), None)
        prop_url = local_path_to_url(prop_path) if prop_path else None
        if not prop_path or not prop_url or len(prop_reference_paths) != 1:
            raise RuntimeError("道具参考图集合不可用；请检查合并结果与存储路径后重试，未提交生成。")
        prop_key = "prop_reference_image_node_id"
        if not node_mapping.get(prop_key):
            prop_key = _get_first_custom_reference_node_key(node_mapping) or prop_key
        reference_items_by_key[prop_key] = {"label": f"道具合并图: {prop_label}", "url": prop_url, "path": prop_path}

    bound_nodes = set()
    for key, item in reference_items_by_key.items():
        node_id = str(node_mapping.get(key))
        node = submitted_workflow.get(node_id)
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict) or "image" not in node["inputs"]:
            raise RuntimeError(f"工作流无法绑定{item['label']}: {key}；请选择支持该参考图的工作流或修复节点映射，未提交生成。")
        if node_id in bound_nodes:
            raise RuntimeError(f"参考图节点重复: {key}；请为每张参考图配置独立节点，未提交生成。")
        bound_nodes.add(node_id)

    reference_node_keys = _get_compact_reference_node_keys(node_mapping)
    reference_items = [reference_items_by_key.get(key) for key in reference_node_keys]
    visible_reference_items = [item for item in reference_items if item]

    uploaded_filenames = []
    for item in reference_items:
        if not item:
            uploaded_filenames.append(None)
            continue
        try:
            upload_result = await comfyui_service.client.upload_image(item["path"])
        except Exception as exc:
            raise RuntimeError(f"参考图上传失败: {item['label']}；请检查 ComfyUI 连接后重试，未提交生成。{exc}") from exc
        filename = upload_result.get("filename") if isinstance(upload_result, dict) else None
        if not filename or not isinstance(filename, str) or not filename.strip() or not upload_result.get("success"):
            raise RuntimeError(f"参考图上传失败: {item['label']}；请检查 ComfyUI 上传结果后重试，未提交生成。{upload_result}")
        uploaded_filenames.append(filename)

    for index, ref_key in enumerate(reference_node_keys):
        node_id = node_mapping.get(ref_key)
        node_id_str = str(node_id) if node_id else ""
        if not node_id_str or node_id_str not in submitted_workflow:
            continue
        uploaded_filename = uploaded_filenames[index] if index < len(uploaded_filenames) else None
        if uploaded_filename:
            submitted_workflow[node_id_str]["inputs"]["image"] = uploaded_filename
            print(
                f"[ShotTask {task_id}] Set <Picture {index + 1}> node "
                f"{node_id_str} to {uploaded_filename}"
            )
        elif node_id_str not in bound_nodes:
            submitted_workflow[node_id_str]["inputs"]["image"] = ""
            disconnect_reference_chain(submitted_workflow, node_id_str)
            print(f"[ShotTask {task_id}] Disconnected unused reference node {node_id_str}")

    task.reference_images = json.dumps(
        [{"label": item["label"], "url": item["url"]} for item in visible_reference_items], ensure_ascii=False,
    ) if visible_reference_items else None
    task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
    db.commit()
    print(f"[ShotTask {task_id}] Saved workflow with reference images to task")


def _get_compact_reference_node_keys(node_mapping: dict):
    keys = []
    if node_mapping.get("character_reference_image_node_id"):
        keys.append("character_reference_image_node_id")
    if node_mapping.get("scene_reference_image_node_id"):
        keys.append("scene_reference_image_node_id")
    if node_mapping.get("prop_reference_image_node_id"):
        keys.append("prop_reference_image_node_id")
    index = 1
    while node_mapping.get(f"custom_reference_image_node_{index}"):
        keys.append(f"custom_reference_image_node_{index}")
        index += 1
    return keys


def _get_first_custom_reference_node_key(node_mapping: dict) -> Optional[str]:
    index = 1
    while node_mapping.get(f"custom_reference_image_node_{index}"):
        return f"custom_reference_image_node_{index}"
    return None


async def _save_generated_image(
    result: dict,
    task,
    chapter,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    db,
    task_id: str,
    shot_id: str = None,
    shot_repo: ShotRepository = None,
):
    """下载并保存生成的图片"""
    if _is_task_cancelled(db, task):
        return
    task.current_step = "正在下载生成的图片..."
    task.progress = 80
    db.commit()

    image_url = result.get("image_url")
    if not image_url:
        task.status = "failed"
        task.error_message = "未获取到图片URL"
        task.current_step = "生成失败"
        db.commit()
        return

    # 使用 shot_id 作为文件名的一部分（如果提供）
    file_prefix = f"shot_{shot_id[:8]}" if shot_id else f"shot_{shot_index:03d}"
    local_path = await file_storage.download_image(
        url=image_url,
        novel_id=novel_id,
        character_name=file_prefix,
        image_type="shot",
        chapter_id=chapter_id,
    )

    if local_path:
        if _is_task_cancelled(db, task):
            return
        relative_path = local_path.replace(str(file_storage.base_dir), "").replace(
            "\\", "/"
        )
        local_url = f"/api/files/{relative_path.lstrip('/')}"

        task.status = "completed"
        task.progress = 100
        task.result_url = local_url
        task.current_step = "生成完成"
        task.completed_at = datetime.utcnow()
        db.commit()

        # 更新 Shot 记录
        _update_shot_image(db, chapter_id, shot_index, local_path, local_url, shot_repo, task_id=task.id)

        print(f"[ShotTask {task_id}] Completed, image saved: {local_path}")
    else:
        if _is_task_cancelled(db, task):
            return
        task.status = "completed"
        task.progress = 100
        task.result_url = image_url
        task.current_step = "生成完成（使用远程图片）"
        task.completed_at = datetime.utcnow()
        db.commit()

        # 更新 Shot 记录（使用远程URL）
        _update_shot_image(db, chapter_id, shot_index, None, image_url, shot_repo, task_id=task.id)


def _update_shot_image(
    db,
    chapter_id: str,
    shot_index: int,
    local_path: Optional[str],
    image_url: str,
    shot_repo: ShotRepository = None,
    task_id: Optional[str] = None,
):
    """更新 Shot 记录中的分镜图片数据"""
    if shot_repo is None:
        shot_repo = ShotRepository(db)

    shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)
    if not shot:
        print(f"[Warning] Shot not found: chapter_id={chapter_id}, index={shot_index}")
        return

    update_data = {
        "image_url": image_url,
        "image_status": "completed",
    }
    if task_id:
        update_data["image_task_id"] = task_id
    if local_path:
        update_data["image_path"] = str(local_path)

    shot_repo.update(shot, **update_data)
    print(f"[ShotImage] Updated shot {shot.id}: image_url={image_url}")
