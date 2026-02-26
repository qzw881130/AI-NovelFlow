"""
转场视频生成服务

封装转场视频生成的后台任务逻辑
"""
import json
import os
import httpx
from datetime import datetime

from app.models.novel import Chapter
from app.models.task import Task
from app.models.workflow import Workflow
from app.core.database import SessionLocal
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.utils.path_utils import url_to_local_path


async def generate_transition_video_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    from_index: int,
    to_index: int,
    workflow_id: str,
    frame_count: int = 49
):
    """
    后台任务：生成转场视频（从视频提取首帧/尾帧）
    
    Args:
        task_id: 任务ID
        novel_id: 小说ID
        chapter_id: 章节ID
        from_index: 起始分镜索引
        to_index: 结束分镜索引
        workflow_id: 工作流ID
        frame_count: 帧数
    """
    db = SessionLocal()
    
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            print(f"[TransitionTask] Task {task_id} not found")
            return
        
        task.status = "running"
        task.current_step = "准备生成转场视频..."
        task.progress = 10
        db.commit()
        
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
        if not chapter:
            raise Exception("章节不存在")
        
        shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
        
        first_video_url = shot_videos[from_index - 1] if from_index <= len(shot_videos) else None
        second_video_url = shot_videos[to_index - 1] if to_index <= len(shot_videos) else None
        
        if not first_video_url or not second_video_url:
            raise Exception("分镜视频尚未生成")
        
        # 转换URL为本地路径
        first_video_path = url_to_local_path(first_video_url)
        second_video_path = url_to_local_path(second_video_url)
        
        if not first_video_path or not second_video_path:
            raise Exception("无法解析视频路径")
        
        if not os.path.exists(first_video_path) or not os.path.exists(second_video_path):
            raise Exception("视频文件不存在")
        
        from pathlib import Path
        first_video_name = Path(first_video_path).stem
        second_video_name = Path(second_video_path).stem
        
        task.current_step = "正在提取视频帧..."
        task.progress = 20
        db.commit()
        
        # 提取前一个视频的尾帧
        first_frames = await file_storage.extract_video_frames(first_video_path)
        if not first_frames.get("success") or not first_frames.get("last"):
            raise Exception(f"无法提取第一个视频的尾帧: {first_frames.get('message')}")
        
        # 提取后一个视频的首帧
        second_frames = await file_storage.extract_video_frames(second_video_path)
        if not second_frames.get("success") or not second_frames.get("first"):
            raise Exception(f"无法提取第二个视频的首帧: {second_frames.get('message')}")
        
        last_frame_path = first_frames["last"]
        first_frame_path = second_frames["first"]
        
        task.current_step = "正在调用 ComfyUI 生成转场视频..."
        task.progress = 40
        db.commit()
        
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise Exception("工作流不存在")
        
        node_mapping = {}
        if workflow.node_mapping:
            try:
                node_mapping = json.loads(workflow.node_mapping)
            except Exception:
                pass
        
        comfyui_service = ComfyUIService()
        result = await comfyui_service.generate_transition_video_with_workflow(
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            first_image_path=last_frame_path,
            last_image_path=first_frame_path,
            frame_count=frame_count
        )
        
        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]
            print(f"[TransitionTask] Saved ComfyUI prompt_id: {result['prompt_id']}")
        
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
            print(f"[TransitionTask] Saved submitted workflow to task")
        
        if result.get("success"):
            video_url = result.get("video_url")
            
            task.current_step = "正在保存视频..."
            task.progress = 80
            db.commit()
            
            transition_path = file_storage.get_transition_video_path(
                novel_id, chapter_id, first_video_name, second_video_name
            )
            
            async with httpx.AsyncClient() as client:
                response = await client.get(video_url, timeout=120.0)
                response.raise_for_status()
                
                with open(transition_path, 'wb') as f:
                    f.write(response.content)
            
            relative_path = str(transition_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
            local_url = f"/api/files/{relative_path.lstrip('/')}"
            
            transition_videos = json.loads(chapter.transition_videos) if chapter.transition_videos else {}
            if not isinstance(transition_videos, dict):
                transition_videos = {}
            
            transition_key = f"{from_index}-{to_index}"
            transition_videos[transition_key] = local_url
            chapter.transition_videos = json.dumps(transition_videos)
            
            task.status = "completed"
            task.progress = 100
            task.result_url = local_url
            task.current_step = "转场视频生成完成"
            db.commit()
            
            print(f"[TransitionTask] Completed: {from_index}->{to_index}, video: {local_url}")
        else:
            raise Exception(result.get("message", "生成失败"))
            
    except Exception as e:
        print(f"[TransitionTask] Error: {e}")
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
