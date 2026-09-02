"""
分镜图生成服务

封装分镜图片生成的后台任务逻辑
"""

import json
from datetime import datetime
from typing import Optional, Dict

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
    try:
        # 获取任务
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
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
        character_appearances = {}
        for char_name in shot_characters:
            character = (
                db.query(Character)
                .filter(Character.novel_id == novel_id, Character.name == char_name)
                .first()
            )
            if character and character.appearance:
                character_appearances[char_name] = character.appearance
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
        prop_appearances = {}
        for prop_name in shot_props:
            prop = (
                db.query(Prop)
                .filter(Prop.novel_id == novel_id, Prop.name == prop_name)
                .first()
            )
            if prop and prop.appearance:
                prop_appearances[prop_name] = prop.appearance
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
        if character and character.image_url:
            full_path = url_to_local_path(character.image_url)
            if full_path:
                character_images.append((char_name, full_path))
                print(
                    f"[ShotTask {task_id}] Found character image: {char_name} -> {full_path}"
                )

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
            print(f"[ShotTask {task_id}] Failed to merge character images")
            task.current_step = "角色图片合并失败，继续生成..."
            db.commit()

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
        if full_path:
            print(
                f"[ShotTask {task_id}] Found scene image: {shot_scene} -> {full_path}"
            )
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
            if full_path:
                prop_images.append((prop_name, full_path))
                print(
                    f"[ShotTask {task_id}] Found prop image: {prop_name} -> {full_path}"
                )

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

    print(f"[ShotTask {task_id}] Failed to merge prop images")
    task.current_step = "道具图片合并失败，继续使用首个道具图..."
    db.commit()
    return {prop_images[0][0]: prop_images[0][1]}


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
        if character_url:
            reference_items_by_key["character_reference_image_node_id"] = {"label": "角色合并图", "url": character_url, "path": character_reference_path}
    if scene_reference_path:
        scene_url = local_path_to_url(scene_reference_path)
        if scene_url:
            reference_items_by_key["scene_reference_image_node_id"] = {"label": "场景图", "url": scene_url, "path": scene_reference_path}
    if prop_reference_paths:
        prop_label = "、".join(prop_reference_paths.keys())
        prop_path = next((path for path in prop_reference_paths.values() if path), None)
        prop_url = local_path_to_url(prop_path) if prop_path else None
        if prop_path and prop_url:
            prop_item = {"label": f"道具合并图: {prop_label}", "url": prop_url, "path": prop_path}
            reference_items_by_key["prop_reference_image_node_id"] = prop_item
            first_custom_key = _get_first_custom_reference_node_key(node_mapping)
            if first_custom_key:
                reference_items_by_key[first_custom_key] = prop_item

    reference_node_keys = _get_compact_reference_node_keys(node_mapping)
    reference_items = [reference_items_by_key.get(key) for key in reference_node_keys]
    visible_reference_items = [item for item in reference_items if item]

    task.reference_images = (
        json.dumps(
            [{"label": item["label"], "url": item["url"]} for item in visible_reference_items],
            ensure_ascii=False,
        )
        if visible_reference_items
        else None
    )
    db.commit()

    uploaded_filenames = []
    for item in reference_items:
        if not item:
            uploaded_filenames.append(None)
            continue
        upload_result = await comfyui_service.client.upload_image(item["path"])
        if upload_result.get("success"):
            uploaded_filenames.append(upload_result.get("filename"))
            print(
                f"[ShotTask {task_id}] {item['label']} uploaded successfully: "
                f"{upload_result.get('filename')}"
            )
        else:
            uploaded_filenames.append(None)
            print(
                f"[ShotTask {task_id}] Failed to upload {item['label']}: "
                f"{upload_result.get('message')}"
            )

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
        else:
            submitted_workflow[node_id_str]["inputs"]["image"] = ""
            disconnect_reference_chain(submitted_workflow, node_id_str)
            print(f"[ShotTask {task_id}] Disconnected unused reference node {node_id_str}")

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
        _update_shot_image(db, chapter_id, shot_index, local_path, local_url, shot_repo)

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
        _update_shot_image(db, chapter_id, shot_index, None, image_url, shot_repo)


def _update_shot_image(
    db,
    chapter_id: str,
    shot_index: int,
    local_path: Optional[str],
    image_url: str,
    shot_repo: ShotRepository = None,
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
    if local_path:
        update_data["image_path"] = str(local_path)

    shot_repo.update(shot, **update_data)
    print(f"[ShotImage] Updated shot {shot.id}: image_url={image_url}")
