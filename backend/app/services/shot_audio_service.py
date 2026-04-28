"""
分镜台词音频服务

封装分镜台词音频生成相关的业务逻辑
"""
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories import TaskRepository
from app.repositories.character_repository import CharacterRepository
from app.repositories.shot_repository import ShotRepository
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage


class ShotAudioService:
    """分镜台词音频服务"""

    def __init__(self, db: Session = None):
        self.db = db
        self.comfyui_service = ComfyUIService()

    def create_shot_audio_tasks(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        dialogues: List[Dict[str, Any]],
        chapter_title: str,
        workflow: Workflow,
        character_repo: CharacterRepository,
        task_repo: TaskRepository,
        shot_id: str = None
    ) -> Dict[str, Any]:
        """
        为单个分镜创建音频生成任务

        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引
            dialogues: 台词列表
            chapter_title: 章节标题
            workflow: 音频工作流
            character_repo: 角色仓库
            task_repo: 任务仓库

        Returns:
            创建结果
        """
        tasks = []
        warnings = []

        for dialogue in dialogues:
            character_name = dialogue.character_name
            text = dialogue.text
            emotion_prompt = dialogue.emotion_prompt or "自然"
            dialogue_type = getattr(dialogue, 'type', 'character') or 'character'

            if not character_name or not text:
                warnings.append({
                    "character_name": character_name or "未知",
                    "reason": "缺少角色名或台词文本"
                })
                continue

            # 根据台词类型获取角色信息
            if dialogue_type == "narration":
                # 旁白台词：获取旁白角色
                character = character_repo.get_narrator(novel_id)
                if not character:
                    warnings.append({
                        "character_name": character_name,
                        "reason": "该小说尚未创建旁白角色，请先解析角色"
                    })
                    continue
            else:
                # 角色台词：获取指定角色
                character = character_repo.get_by_name(novel_id, character_name)
                if not character:
                    warnings.append({
                        "character_name": character_name,
                        "reason": f"角色 '{character_name}' 不存在于角色库中"
                    })
                    continue

            # 检查角色是否有参考音频
            if not character.reference_audio_url:
                if dialogue_type == "narration":
                    warnings.append({
                        "character_name": character_name,
                        "reason": "旁白角色尚未生成音色，请先在角色库中为旁白生成音色"
                    })
                else:
                    warnings.append({
                        "character_name": character_name,
                        "reason": f"角色 '{character_name}' 尚未生成音色，请先在角色库中生成"
                    })
                continue

            # 检查是否已有进行中的任务
            if dialogue_type == "narration":
                existing_task = task_repo.get_active_narrator_audio_task(
                    novel_id, chapter_id, shot_index
                )
            else:
                existing_task = task_repo.get_active_character_audio_task(
                    novel_id, chapter_id, shot_index, character_name
                )
            if existing_task:
                tasks.append({
                    "character_name": character_name,
                    "task_id": existing_task.id,
                    "status": existing_task.status,
                    "message": "已有进行中的任务",
                    "type": dialogue_type
                })
                continue

            # 创建任务
            if dialogue_type == "narration":
                task = task_repo.create_narrator_audio_task(
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                    shot_index=shot_index,
                    character_id=character.id,
                    text=text,
                    chapter_title=chapter_title,
                    workflow_id=workflow.id,
                    workflow_name=workflow.name,
                    shot_id=shot_id
                )
            else:
                task = task_repo.create_character_audio_task(
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                    shot_index=shot_index,
                    character_id=character.id,
                    character_name=character_name,
                    text=text,
                    chapter_title=chapter_title,
                    workflow_id=workflow.id,
                    workflow_name=workflow.name,
                    shot_id=shot_id
                )

            tasks.append({
                "character_name": character_name,
                "task_id": task.id,
                "status": "pending",
                "type": dialogue_type
            })

            # 启动后台任务
            asyncio.create_task(
                self._generate_audio_task(
                    task_id=task.id,
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                    shot_index=shot_index,
                    character_name=character_name,
                    text=text,
                    emotion_prompt=emotion_prompt,
                    reference_audio_url=character.reference_audio_url,
                    workflow_id=workflow.id,
                    dialogue_type=dialogue_type
                )
            )

        return {
            "success": True,
            "message": f"已创建 {len(tasks)} 个音频生成任务",
            "data": {
                "tasks": tasks,
                "warnings": warnings
            }
        }

    def create_batch_audio_tasks(
        self,
        novel_id: str,
        chapter_id: str,
        shots: List[Dict[str, Any]],
        chapter_title: str,
        workflow: Workflow,
        character_repo: CharacterRepository,
        task_repo: TaskRepository
    ) -> Dict[str, Any]:
        """
        批量创建章节所有分镜的音频生成任务

        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shots: 分镜列表
            chapter_title: 章节标题
            workflow: 音频工作流
            character_repo: 角色仓库
            task_repo: 任务仓库

        Returns:
            创建结果
        """
        all_tasks = []
        all_warnings = []

        for shot_index, shot in enumerate(shots, start=1):
            # 解析 dialogues JSON 字符串
            dialogues_data = shot.dialogues
            if isinstance(dialogues_data, str):
                try:
                    dialogues_data = json.loads(shot.dialogues)
                except Exception:
                    all_warnings.append({
                        "shot_index": shot_index,
                        "reason": f"分镜 {shot_index} 的 dialogues 字段格式无效"
                    })
                    continue
            if not dialogues_data:
                continue

            for dialogue in dialogues_data:
                character_name = dialogue.get("character_name")
                text = dialogue.get("text", "")
                emotion_prompt = dialogue.get("emotion_prompt", "自然")
                dialogue_type = dialogue.get("type", "character") or "character"

                if not character_name or not text:
                    all_warnings.append({
                        "shot_index": shot_index,
                        "character_name": character_name or "未知",
                        "reason": "缺少角色名或台词文本"
                    })
                    continue

                # 根据台词类型获取角色信息
                if dialogue_type == "narration":
                    # 旁白台词：获取旁白角色
                    character = character_repo.get_narrator(novel_id)
                    if not character:
                        all_warnings.append({
                            "shot_index": shot_index,
                            "character_name": character_name,
                            "reason": "该小说尚未创建旁白角色，请先解析角色"
                        })
                        continue
                else:
                    # 角色台词：获取指定角色
                    character = character_repo.get_by_name(novel_id, character_name)
                    if not character:
                        all_warnings.append({
                            "shot_index": shot_index,
                            "character_name": character_name,
                            "reason": f"角色 '{character_name}' 不存在于角色库中"
                        })
                        continue

                # 检查角色是否有参考音频
                if not character.reference_audio_url:
                    if dialogue_type == "narration":
                        all_warnings.append({
                            "shot_index": shot_index,
                            "character_name": character_name,
                            "reason": "旁白角色尚未生成音色，请先在角色库中为旁白生成音色"
                        })
                    else:
                        all_warnings.append({
                            "shot_index": shot_index,
                            "character_name": character_name,
                            "reason": f"角色 '{character_name}' 尚未生成音色"
                        })
                    continue

                # 检查是否已有进行中的任务
                if dialogue_type == "narration":
                    existing_task = task_repo.get_active_narrator_audio_task(
                        novel_id, chapter_id, shot_index
                    )
                else:
                    existing_task = task_repo.get_active_character_audio_task(
                        novel_id, chapter_id, shot_index, character_name
                    )
                if existing_task:
                    all_tasks.append({
                        "shot_index": shot_index,
                        "character_name": character_name,
                        "task_id": existing_task.id,
                        "status": existing_task.status,
                        "message": "已有进行中的任务",
                        "type": dialogue_type
                    })
                    continue

                # 创建任务
                if dialogue_type == "narration":
                    task = task_repo.create_narrator_audio_task(
                        novel_id=novel_id,
                        chapter_id=chapter_id,
                        shot_index=shot_index,
                        character_id=character.id,
                        text=text,
                        chapter_title=chapter_title,
                        workflow_id=workflow.id,
                        workflow_name=workflow.name,
                        shot_id=shot.id
                    )
                else:
                    task = task_repo.create_character_audio_task(
                        novel_id=novel_id,
                        chapter_id=chapter_id,
                        shot_index=shot_index,
                        character_id=character.id,
                        character_name=character_name,
                        text=text,
                        chapter_title=chapter_title,
                        workflow_id=workflow.id,
                        workflow_name=workflow.name,
                        shot_id=shot.id
                    )

                all_tasks.append({
                    "shot_index": shot_index,
                    "character_name": character_name,
                    "task_id": task.id,
                    "status": "pending",
                    "type": dialogue_type
                })

                # 启动后台任务
                asyncio.create_task(
                    self._generate_audio_task(
                        task_id=task.id,
                        novel_id=novel_id,
                        chapter_id=chapter_id,
                        shot_index=shot_index,
                        character_name=character_name,
                        text=text,
                        emotion_prompt=emotion_prompt,
                        reference_audio_url=character.reference_audio_url,
                        workflow_id=workflow.id,
                        dialogue_type=dialogue_type
                    )
                )

        return {
            "success": True,
            "message": f"已创建 {len(all_tasks)} 个音频生成任务",
            "data": {
                "tasks": all_tasks,
                "warnings": all_warnings,
                "total_tasks": len(all_tasks),
                "total_warnings": len(all_warnings)
            }
        }

    async def _generate_audio_task(
        self,
        task_id: str,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        character_name: str,
        text: str,
        emotion_prompt: str,
        reference_audio_url: str,
        workflow_id: str,
        dialogue_type: str = "character"
    ):
        """
        后台任务：生成角色/旁白台词音频

        Args:
            task_id: 任务ID
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引
            character_name: 角色名称
            text: 台词文本
            emotion_prompt: 情感提示词
            reference_audio_url: 参考音频URL
            workflow_id: 工作流ID
            dialogue_type: 台词类型（character 或 narration）
        """
        from app.core.database import SessionLocal
        from app.repositories import WorkflowRepository, ChapterRepository

        db = SessionLocal()
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)
        chapter_repo = ChapterRepository(db)

        try:
            # 获取任务
            task = task_repo.get_by_id(task_id)
            if not task:
                return

            # 获取工作流
            workflow = workflow_repo.get_by_id(workflow_id)

            # 记录工作流信息
            if workflow:
                task.workflow_id = workflow.id
                task.workflow_name = workflow.name
                task.current_step = f"使用工作流: {workflow.name}"
            else:
                task.current_step = "使用默认工作流"

            # 更新任务状态为运行中
            task.status = "running"
            task.started_at = datetime.utcnow()
            db.commit()

            # 获取工作流JSON和节点映射
            workflow_json_str = workflow.workflow_json if workflow else None
            node_mapping = None
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                    print(f"[AudioTask] Using node mapping: {node_mapping}")
                except Exception as e:
                    print(f"[AudioTask] Failed to parse node_mapping: {e}")

            # 下载参考音频到本地（如果需要）
            local_audio_path = await self._download_reference_audio(
                reference_audio_url, novel_id, character_name
            )

            if not local_audio_path:
                task.status = "failed"
                task.error_message = "无法下载参考音频"
                task.current_step = "下载参考音频失败"
                db.commit()
                return

            # 上传参考音频到 ComfyUI
            upload_result = await self.comfyui_service.client.upload_audio(local_audio_path)
            if not upload_result.get("success"):
                task.status = "failed"
                task.error_message = f"上传参考音频失败: {upload_result.get('message', '')}"
                task.current_step = "上传参考音频失败"
                db.commit()
                return

            reference_audio_filename = upload_result.get("filename")
            print(f"[AudioTask] Uploaded reference audio: {reference_audio_filename}")

            # 构建音频生成工作流
            submitted_workflow = self.comfyui_service.builder.build_audio_workflow(
                text=text,
                workflow_json=workflow_json_str,
                novel_id=novel_id,
                character_name=character_name,
                node_mapping=node_mapping,
                reference_audio_filename=reference_audio_filename,
                emotion_prompt=emotion_prompt
            )

            # 保存构建后的完整工作流到任务
            task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
            if dialogue_type == "narration":
                task.prompt_text = f"类型: 旁白\n台词: {text}\n情感: {emotion_prompt}"
            else:
                task.prompt_text = f"角色: {character_name}\n台词: {text}\n情感: {emotion_prompt}"
            task.current_step = "正在生成音频..."
            db.commit()

            # 提交到 ComfyUI 队列
            queue_result = await self.comfyui_service.client.queue_prompt(submitted_workflow)
            if not queue_result.get("success"):
                task.status = "failed"
                task.error_message = queue_result.get("error", "提交任务失败")
                task.current_step = "提交任务失败"
                db.commit()
                return

            prompt_id = queue_result.get("prompt_id")
            task.comfyui_prompt_id = prompt_id
            db.commit()

            # 等待结果
            save_audio_node_id = node_mapping.get("save_audio_node_id") if node_mapping else None
            result = await self.comfyui_service.client.wait_for_audio_result(
                prompt_id, submitted_workflow, save_audio_node_id, timeout=600
            )

            print(f"[AudioTask] Generation result: {json.dumps(result, ensure_ascii=True)}")

            if result.get("success"):
                audio_url = result.get("audio_url")

                # 下载音频到本地存储
                task.current_step = "下载音频到服务器..."
                db.commit()

                try:
                    local_path = await file_storage.download_audio(
                        url=audio_url,
                        novel_id=novel_id,
                        character_name=f"shot_{shot_index}_{character_name}",
                        audio_type="dialogue"
                    )

                    if local_path:
                        relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                        local_url = f"/api/files/{relative_path.lstrip('/')}"
                        task.result_url = local_url
                        task.current_step = "生成完成，音频已保存"
                    else:
                        task.result_url = audio_url
                        task.current_step = "生成完成，使用远程音频"
                except Exception as e:
                    print(f"[AudioTask] Failed to download audio: {e}")
                    task.result_url = audio_url
                    task.current_step = "生成完成，使用远程音频"

                task.status = "completed"
                task.progress = 100
                task.completed_at = datetime.utcnow()

                # 更新分镜数据中的 audio_url
                self._update_shot_dialogue_audio_url(
                    db, chapter_repo, chapter_id, novel_id,
                    shot_index, character_name, task.result_url, task.id,
                    dialogue_type=dialogue_type
                )
            else:
                task.status = "failed"
                task.error_message = result.get("message", "生成失败")
                task.current_step = "生成失败"

            db.commit()

        except Exception as e:
            print(f"[AudioTask] Error: {e}")
            import traceback
            traceback.print_exc()
            task = task_repo.get_by_id(task_id)
            if task:
                task.status = "failed"
                task.error_message = str(e)
                task.current_step = "任务异常"
                db.commit()
        finally:
            db.close()

    async def _download_reference_audio(
        self,
        reference_audio_url: str,
        novel_id: str,
        character_name: str
    ) -> Optional[str]:
        """
        下载参考音频到本地

        Args:
            reference_audio_url: 参考音频URL
            novel_id: 小说ID
            character_name: 角色名称

        Returns:
            本地文件路径，失败返回 None
        """
        import os
        import httpx

        try:
            # 如果已经是本地文件路径
            if reference_audio_url.startswith("/api/files/"):
                # 转换为本地绝对路径
                relative_path = reference_audio_url.replace("/api/files/", "")
                local_path = file_storage.base_dir / relative_path
                if local_path.exists():
                    return str(local_path)

            # 如果是远程URL，下载到临时目录
            if reference_audio_url.startswith("http"):
                temp_dir = file_storage.base_dir / f"story_{novel_id}" / "temp"
                temp_dir.mkdir(parents=True, exist_ok=True)

                safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in character_name)
                temp_path = temp_dir / f"{safe_name}_reference.flac"

                async with httpx.AsyncClient() as client:
                    response = await client.get(reference_audio_url)
                    if response.status_code == 200:
                        with open(temp_path, "wb") as f:
                            f.write(response.content)
                        return str(temp_path)

            return None

        except Exception as e:
            print(f"[AudioTask] Failed to download reference audio: {e}")
            return None

    def _update_shot_dialogue_audio_url(
        self,
        db: Session,
        chapter_repo,
        chapter_id: str,
        novel_id: str,
        shot_index: int,
        character_name: str,
        audio_url: str,
        task_id: str,
        audio_source: str = "ai_generated",
        dialogue_type: str = "character"
    ):
        """
        更新分镜台词的 audio_url 字段

        Args:
            db: 数据库会话
            chapter_repo: 章节仓库
            chapter_id: 章节ID
            novel_id: 小说ID
            shot_index: 分镜索引
            character_name: 角色名称
            audio_url: 音频URL
            task_id: 任务ID
            audio_source: 音频来源（ai_generated 或 uploaded）
            dialogue_type: 台词类型（character 或 narration）
        """
        try:
            # 使用 ShotRepository 更新 Shot 记录
            shot_repo = ShotRepository(db)
            shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)

            if not shot:
                print(f"[AudioTask] Shot not found: chapter_id={chapter_id}, index={shot_index}")
                return

            # 解析现有 dialogues
            dialogues = json.loads(shot.dialogues) if shot.dialogues else []

            # 更新对应台词的音频信息
            for dialogue in dialogues:
                if dialogue_type == "narration":
                    # 旁白台词：匹配 type="narration"
                    if dialogue.get("type") == "narration":
                        dialogue["audio_url"] = audio_url
                        dialogue["audio_task_id"] = task_id
                        dialogue["audio_source"] = audio_source
                        break
                else:
                    # 角色台词：匹配角色名称
                    if dialogue.get("character_name") == character_name:
                        dialogue["audio_url"] = audio_url
                        dialogue["audio_task_id"] = task_id
                        dialogue["audio_source"] = audio_source
                        break

            # 更新 Shot 记录
            shot_repo.update(shot, dialogues=dialogues)
            print(f"[AudioTask] Updated audio_url for shot {shot_index}, type: {dialogue_type}, source: {audio_source}")

        except Exception as e:
            print(f"[AudioTask] Failed to update shot dialogue audio_url: {e}")