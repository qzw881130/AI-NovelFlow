"""
分镜图生成服务

封装分镜图片生成的后台任务逻辑
"""
import json
from datetime import datetime
from typing import Optional

from app.models.novel import Novel, Chapter, Character, Scene
from app.models.prompt_template import PromptTemplate
from app.models.task import Task
from app.models.workflow import Workflow
from app.core.database import SessionLocal
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.utils.path_utils import url_to_local_path
from app.utils.image_utils import merge_character_images


async def generate_shot_image_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    shot_description: str,
    workflow_id: str
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
        
        # 更新任务状态为运行中
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.current_step = "准备生成环境..."
        db.commit()
        
        # 获取章节和小说
        chapter = db.query(Chapter).filter(
            Chapter.id == chapter_id,
            Chapter.novel_id == novel_id
        ).first()
        
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
        
        # 解析章节数据
        parsed_data = json.loads(chapter.parsed_data) if isinstance(chapter.parsed_data, str) else chapter.parsed_data
        shots = parsed_data.get("shots", [])
        
        if shot_index < 1 or shot_index > len(shots):
            task.status = "failed"
            task.error_message = "分镜索引超出范围"
            db.commit()
            return
        
        shot = shots[shot_index - 1]
        shot_characters = shot.get("characters", [])
        shot_scene = shot.get("scene", "")
        
        print(f"[ShotTask {task_id}] Novel: {novel_id}, Chapter: {chapter_id}, Shot: {shot_index}")
        print(f"[ShotTask {task_id}] Description: {shot_description}")
        print(f"[ShotTask {task_id}] Characters: {shot_characters}")
        
        # 获取工作流
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            task.status = "failed"
            task.error_message = "工作流不存在"
            db.commit()
            return
        
        # 获取节点映射
        node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}
        print(f"[ShotTask {task_id}] Node mapping: {node_mapping}")
        
        # 先保存提示词
        task.prompt_text = shot_description
        db.commit()
        
        # 获取小说配置的角色提示词模板 style
        style = _get_style_from_novel(db, novel)
        print(f"[ShotTask {task_id}] Using style: {style}")
        
        comfyui_service = ComfyUIService()
        
        # 合并角色图片
        character_reference_path = await _process_character_references(
            db, task, novel_id, chapter_id, shot_index, shot_characters, task_id
        )
        
        # 处理场景图
        scene_reference_path = await _process_scene_reference(
            db, task, novel_id, shot_scene, task_id
        )
        
        # 构建工作流
        task.current_step = "构建工作流..."
        db.commit()
        
        submitted_workflow = comfyui_service.builder.build_shot_workflow(
            prompt=shot_description,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            style=style
        )
        
        # 上传参考图并更新工作流
        await _upload_references_and_update_workflow(
            comfyui_service, submitted_workflow, node_mapping,
            character_reference_path, scene_reference_path,
            task, db, task_id
        )
        
        # 调用 ComfyUI 生成图片
        task.current_step = "正在调用 ComfyUI 生成图片..."
        task.progress = 30
        db.commit()
        
        result = await comfyui_service.generate_shot_image_with_workflow(
            prompt=shot_description,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            character_reference_path=None,
            scene_reference_path=None,
            workflow=submitted_workflow,
            style=style
        )
        
        print(f"[ShotTask {task_id}] Generation result: {result}")
        
        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]
        
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
        
        if not result.get("success"):
            task.status = "failed"
            task.error_message = result.get("message", "生成失败")
            task.current_step = "生成失败"
            db.commit()
            return
        
        # 下载并保存生成的图片
        await _save_generated_image(
            result, task, chapter, novel_id, chapter_id, shot_index, db, task_id
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

def _get_style_from_novel(db, novel: Novel) -> str:
    """从小说配置获取风格"""
    style = "anime style, high quality, detailed"
    if novel.prompt_template_id:
        prompt_template = db.query(PromptTemplate).filter(
            PromptTemplate.id == novel.prompt_template_id
        ).first()
        if prompt_template and prompt_template.template:
            import re
            try:
                template_data = json.loads(prompt_template.template)
                if isinstance(template_data, dict) and "style" in template_data:
                    style = template_data["style"]
                else:
                    style = prompt_template.template.replace("{appearance}", "").replace("{description}", "").strip(", ")
            except json.JSONDecodeError:
                style = prompt_template.template.replace("{appearance}", "").replace("{description}", "").strip(", ")
                style = re.sub(r',\s*,', ',', style)
                style = re.sub(r'\s+', ' ', style)
                style = style.strip(", ")
    return style


async def _process_character_references(
    db, task, novel_id: str, chapter_id: str, shot_index: int,
    shot_characters: list, task_id: str
) -> Optional[str]:
    """处理角色参考图片"""
    character_reference_path = None
    
    if not shot_characters:
        return None
    
    task.current_step = f"合并角色图片: {', '.join(shot_characters)}"
    db.commit()
    
    character_images = []
    print(f"[ShotTask {task_id}] Looking for {len(shot_characters)} characters: {shot_characters}")
    
    for char_name in shot_characters:
        character = db.query(Character).filter(
            Character.novel_id == novel_id,
            Character.name == char_name
        ).first()
        print(f"[ShotTask {task_id}] Character '{char_name}': found={character is not None}, has_image={character.image_url if character else None}")
        if character and character.image_url:
            full_path = url_to_local_path(character.image_url)
            if full_path:
                character_images.append((char_name, full_path))
                print(f"[ShotTask {task_id}] Found character image: {char_name} -> {full_path}")
    
    print(f"[ShotTask {task_id}] Total character images found: {len(character_images)}")
    
    if character_images:
        merged_path = merge_character_images(
            novel_id, chapter_id, shot_index, character_images, file_storage
        )
        
        if merged_path:
            character_reference_path = merged_path
            
            # 更新章节中的合并角色图 URL
            _update_chapter_merged_character_url(db, chapter_id, shot_index, merged_path)
            
            print(f"[ShotTask {task_id}] Merged character image saved: {merged_path}")
            task.current_step = f"已合并 {len(character_images)} 个角色图片"
            db.commit()
        else:
            print(f"[ShotTask {task_id}] Failed to merge character images")
            task.current_step = "角色图片合并失败，继续生成..."
            db.commit()
    
    return character_reference_path


def _update_chapter_merged_character_url(db, chapter_id: str, shot_index: int, merged_path: str):
    """更新章节中合并角色图的 URL"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not chapter:
        return
    
    merged_relative_path = str(merged_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
    merged_url = f"/api/files/{merged_relative_path.lstrip('/')}"
    
    latest_parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {"shots": []}
    if "shots" not in latest_parsed_data:
        latest_parsed_data["shots"] = []
    while len(latest_parsed_data["shots"]) < shot_index:
        latest_parsed_data["shots"].append({})
    latest_parsed_data["shots"][shot_index - 1]["merged_character_image"] = merged_url
    chapter.parsed_data = json.dumps(latest_parsed_data, ensure_ascii=False)
    db.commit()


async def _process_scene_reference(
    db, task, novel_id: str, shot_scene: str, task_id: str
) -> Optional[str]:
    """处理场景参考图片"""
    if not shot_scene:
        return None
    
    task.current_step = f"查找场景图: {shot_scene}"
    db.commit()
    
    scene = db.query(Scene).filter(
        Scene.novel_id == novel_id,
        Scene.name == shot_scene
    ).first()
    
    print(f"[ShotTask {task_id}] Scene '{shot_scene}': found={scene is not None}, has_image={scene.image_url if scene else None}")
    
    if scene and scene.image_url:
        full_path = url_to_local_path(scene.image_url)
        if full_path:
            print(f"[ShotTask {task_id}] Found scene image: {shot_scene} -> {full_path}")
            return full_path
    
    return None


async def _upload_references_and_update_workflow(
    comfyui_service, submitted_workflow: dict, node_mapping: dict,
    character_reference_path: Optional[str], scene_reference_path: Optional[str],
    task, db, task_id: str
):
    """上传参考图并更新工作流"""
    if not character_reference_path and not scene_reference_path:
        task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
        db.commit()
        return
    
    task.current_step = "上传参考图..."
    db.commit()
    print(f"[ShotTask {task_id}] Uploading reference images before submission")
    
    character_uploaded_filename = None
    if character_reference_path:
        upload_result = await comfyui_service.client.upload_image(character_reference_path)
        if upload_result.get("success"):
            character_uploaded_filename = upload_result.get("filename")
            print(f"[ShotTask {task_id}] Character image uploaded successfully: {character_uploaded_filename}")
        else:
            print(f"[ShotTask {task_id}] Failed to upload character image: {upload_result.get('message')}")
    
    scene_uploaded_filename = None
    if scene_reference_path:
        upload_result = await comfyui_service.client.upload_image(scene_reference_path)
        if upload_result.get("success"):
            scene_uploaded_filename = upload_result.get("filename")
            print(f"[ShotTask {task_id}] Scene image uploaded successfully: {scene_uploaded_filename}")
        else:
            print(f"[ShotTask {task_id}] Failed to upload scene image: {upload_result.get('message')}")
    
    if character_uploaded_filename or scene_uploaded_filename:
        character_node_id = node_mapping.get("character_reference_image_node_id")
        scene_node_id = node_mapping.get("scene_reference_image_node_id")
        
        print(f"[ShotTask {task_id}] Node mapping - character_node: {character_node_id}, scene_node: {scene_node_id}")
        
        if character_uploaded_filename and character_node_id:
            node_id_str = str(character_node_id)
            if node_id_str in submitted_workflow:
                submitted_workflow[node_id_str]["inputs"]["image"] = character_uploaded_filename
                print(f"[ShotTask {task_id}] Set LoadImage node {node_id_str} to character image: {character_uploaded_filename}")
            else:
                print(f"[ShotTask {task_id}] Warning: character_reference_image_node_id '{node_id_str}' not found in workflow")
        
        if scene_uploaded_filename and scene_node_id:
            node_id_str = str(scene_node_id)
            if node_id_str in submitted_workflow:
                submitted_workflow[node_id_str]["inputs"]["image"] = scene_uploaded_filename
                print(f"[ShotTask {task_id}] Set LoadImage node {node_id_str} to scene image: {scene_uploaded_filename}")
            else:
                print(f"[ShotTask {task_id}] Warning: scene_reference_image_node_id '{node_id_str}' not found in workflow")
        
        task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
        db.commit()
        print(f"[ShotTask {task_id}] Saved workflow with LoadImage replacement to task")
    else:
        task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
        db.commit()


async def _save_generated_image(
    result: dict, task, chapter, novel_id: str, chapter_id: str,
    shot_index: int, db, task_id: str
):
    """下载并保存生成的图片"""
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
    
    local_path = await file_storage.download_image(
        url=image_url,
        novel_id=novel_id,
        character_name=f"shot_{shot_index:03d}",
        image_type="shot",
        chapter_id=chapter_id
    )
    
    if local_path:
        relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
        local_url = f"/api/files/{relative_path.lstrip('/')}"
        
        task.status = "completed"
        task.progress = 100
        task.result_url = local_url
        task.current_step = "生成完成"
        task.completed_at = datetime.utcnow()
        db.commit()
        
        # 更新章节数据
        _update_chapter_shot_image(db, chapter, shot_index, local_path, local_url)
        
        print(f"[ShotTask {task_id}] Completed, image saved: {local_path}")
    else:
        task.status = "completed"
        task.progress = 100
        task.result_url = image_url
        task.current_step = "生成完成（使用远程图片）"
        task.completed_at = datetime.utcnow()
        db.commit()
        
        # 更新章节数据（使用远程URL）
        _update_chapter_shot_image(db, chapter, shot_index, None, image_url)


def _update_chapter_shot_image(db, chapter, shot_index: int, local_path: Optional[str], image_url: str):
    """更新章节中的分镜图片数据"""
    db.refresh(chapter)
    latest_parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {"shots": []}
    
    if "shots" not in latest_parsed_data:
        latest_parsed_data["shots"] = []
    while len(latest_parsed_data["shots"]) < shot_index:
        latest_parsed_data["shots"].append({})
    
    if local_path:
        latest_parsed_data["shots"][shot_index - 1]["image_path"] = str(local_path)
    latest_parsed_data["shots"][shot_index - 1]["image_url"] = image_url
    
    chapter.parsed_data = json.dumps(latest_parsed_data, ensure_ascii=False)
    
    shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
    if not isinstance(shot_images, list):
        shot_images = []
    while len(shot_images) < shot_index:
        shot_images.append(None)
    shot_images[shot_index - 1] = image_url
    chapter.shot_images = json.dumps(shot_images, ensure_ascii=False)
    
    db.commit()
