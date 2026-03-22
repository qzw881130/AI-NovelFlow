"""
分镜视频生成服务

封装分镜视频生成的后台任务逻辑
"""
import json
from datetime import datetime

from app.models.novel import Novel, Chapter
from app.models.task import Task
from app.models.workflow import Workflow
from app.core.database import SessionLocal
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.utils.path_utils import url_to_local_path
from app.repositories.shot_repository import ShotRepository


async def generate_shot_video_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    workflow_id: str,
    shot_image_url: str,
    use_keyframes: bool = True,
    use_reference_audio: bool = True
):
    """
    后台任务：生成分镜视频

    Args:
        task_id: 任务ID
        novel_id: 小说ID
        chapter_id: 章节ID
        shot_index: 分镜索引
        workflow_id: 工作流ID
        shot_image_url: 分镜图片URL
        use_keyframes: 是否使用关键帧（如果存在），默认 True
        use_reference_audio: 是否使用参考音频（如果存在），默认 True
    """
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return

        task.status = "running"
        task.started_at = datetime.utcnow()
        task.current_step = "准备生成视频..."
        db.commit()

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

        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            task.status = "failed"
            task.error_message = "工作流不存在"
            db.commit()
            return

        node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}
        print(f"[VideoTask {task_id}] Node mapping: {node_mapping}")

        # 使用 ShotRepository 获取分镜数据
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)

        if not shot:
            task.status = "failed"
            task.error_message = "分镜不存在"
            db.commit()
            return

        # 从 Shot 模型获取分镜描述
        shot_description = shot.description or ""

        task.prompt_text = shot_description
        db.commit()

        duration = shot.duration or 4
        fps = 25
        raw_frame_count = int(fps * duration)
        frame_count = ((raw_frame_count // 8) * 8) + 1
        print(f"[VideoTask {task_id}] Duration: {duration}s, FPS: {fps}, Raw frames: {raw_frame_count}, Adjusted frames: {frame_count}")

        character_reference_path = None
        if shot_image_url:
            full_path = url_to_local_path(shot_image_url)
            if full_path:
                character_reference_path = full_path
                print(f"[VideoTask {task_id}] Found shot image: {full_path}")
            else:
                print(f"[VideoTask {task_id}] Shot image not found at: {shot_image_url}")

        # 获取占位符替换所需的资源数据
        # 从 Shot 模型直接获取角色、场景、道具
        shot_characters = json.loads(shot.characters) if shot.characters else []
        shot_scene = shot.scene or ""
        shot_props = json.loads(shot.props) if shot.props else []

        # 获取角色外貌描述（从 Character 表中获取）
        character_appearances = {}
        from app.models.novel import Character
        for char_name in shot_characters:
            character = db.query(Character).filter(
                Character.novel_id == novel_id,
                Character.name == char_name
            ).first()
            if character and character.appearance:
                character_appearances[char_name] = character.appearance

        # 获取场景环境设定（从 Scene 表中获取）
        scene_setting = None
        if shot_scene:
            from app.models.novel import Scene
            scene = db.query(Scene).filter(
                Scene.novel_id == novel_id,
                Scene.name == shot_scene
            ).first()
            if scene and scene.setting:
                scene_setting = scene.setting

        # 获取道具外观描述（从 Prop 表中获取）
        prop_appearances = {}
        if shot_props:
            from app.models.novel import Prop
            for prop_name in shot_props:
                prop = db.query(Prop).filter(
                    Prop.novel_id == novel_id,
                    Prop.name == prop_name
                ).first()
                if prop and prop.appearance:
                    prop_appearances[prop_name] = prop.appearance

        # 获取风格设置（从 PromptTemplate 中获取）
        style = ""
        if novel.style_prompt_template_id:
            from app.models.prompt_template import PromptTemplate
            template = db.query(PromptTemplate).filter(
                PromptTemplate.id == novel.style_prompt_template_id
            ).first()
            if template:
                style = template.template or ""

        print(f"[VideoTask {task_id}] Style: {style}")
        print(f"[VideoTask {task_id}] Characters: {character_appearances}")
        print(f"[VideoTask {task_id}] Scene: {scene_setting}")
        print(f"[VideoTask {task_id}] Props: {prop_appearances}")

        # 获取参考音频路径
        reference_audio_path = None
        if use_reference_audio and shot.reference_audio_url:
            audio_local_path = url_to_local_path(shot.reference_audio_url)
            if audio_local_path:
                reference_audio_path = audio_local_path
                print(f"[VideoTask {task_id}] Found reference audio: {audio_local_path}")
            else:
                print(f"[VideoTask {task_id}] Reference audio not found at: {shot.reference_audio_url}")
        elif not use_reference_audio:
            print(f"[VideoTask {task_id}] Skipping reference audio (use_reference_audio=False)")

        # 获取关键帧图片路径
        keyframe_paths = []
        if use_keyframes and shot.keyframes:
            try:
                keyframes_data = json.loads(shot.keyframes) if isinstance(shot.keyframes, str) else shot.keyframes
                if isinstance(keyframes_data, list):
                    for idx, kf in enumerate(keyframes_data):
                        if isinstance(kf, dict) and kf.get("image_url"):
                            kf_local_path = url_to_local_path(kf["image_url"])
                            if kf_local_path:
                                keyframe_paths.append(kf_local_path)
                                print(f"[VideoTask {task_id}] Found keyframe {idx + 1}: {kf_local_path}")
                            else:
                                print(f"[VideoTask {task_id}] Keyframe {idx + 1} image not found at: {kf['image_url']}")
                print(f"[VideoTask {task_id}] Total keyframes found: {len(keyframe_paths)}")
            except Exception as e:
                print(f"[VideoTask {task_id}] Error parsing keyframes: {e}")
        elif not use_keyframes:
            print(f"[VideoTask {task_id}] Skipping keyframes (use_keyframes=False)")

        task.current_step = "正在调用 ComfyUI 生成视频..."
        task.progress = 30
        db.commit()

        comfyui_service = ComfyUIService()
        result = await comfyui_service.generate_shot_video_with_workflow(
            prompt=shot_description,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            character_reference_path=character_reference_path,
            frame_count=frame_count,
            style=style,
            character_appearances=character_appearances,
            scene_setting=scene_setting,
            prop_appearances=prop_appearances,
            reference_audio_path=reference_audio_path,
            keyframe_paths=keyframe_paths
        )

        print(f"[VideoTask {task_id}] Generation result: {result}")

        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]
            print(f"[VideoTask {task_id}] Saved ComfyUI prompt_id: {result['prompt_id']}")

        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
            print(f"[VideoTask {task_id}] Saved submitted workflow to task")

        if not result.get("success"):
            task.status = "failed"
            task.error_message = result.get("message", "生成失败")
            task.current_step = "生成失败"
            db.commit()
            return

        # 下载并保存视频
        await _save_generated_video(result, task, novel_id, chapter_id, shot_index, db, task_id, shot_repo)

    except Exception as e:
        print(f"[VideoTask {task_id}] Error: {e}")
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


async def _save_generated_video(
    result: dict, task, novel_id: str, chapter_id: str,
    shot_index: int, db, task_id: str, shot_repo: ShotRepository
):
    """下载并保存生成的视频"""
    task.current_step = "正在下载生成的视频..."
    task.progress = 80
    db.commit()

    video_url = result.get("video_url")
    if not video_url:
        task.status = "failed"
        task.error_message = "未获取到视频URL"
        task.current_step = "生成失败"
        db.commit()
        return

    local_path = await file_storage.download_video(
        url=video_url,
        novel_id=novel_id,
        chapter_id=chapter_id,
        shot_number=shot_index
    )

    if local_path:
        relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
        local_url = f"/api/files/{relative_path.lstrip('/')}"

        # 更新 Shot 记录中的视频数据
        shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)
        if shot:
            shot_repo.update(shot, video_url=local_url, video_status="completed")
            print(f"[VideoTask {task_id}] Shot video updated: {local_url}")

        task.status = "completed"
        task.progress = 100
        task.result_url = local_url
        task.current_step = "生成完成"
        task.completed_at = datetime.utcnow()
        db.commit()

        print(f"[VideoTask {task_id}] Video saved: {local_url}")
    else:
        task.status = "failed"
        task.error_message = "下载视频失败"
        task.current_step = "下载失败"
        db.commit()
