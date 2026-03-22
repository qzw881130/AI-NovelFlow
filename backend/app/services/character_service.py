"""
角色服务

封装角色相关的业务逻辑
"""
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from app.models.novel import Character
from app.models.task import Task
from app.models.workflow import Workflow
from app.repositories import TaskRepository, WorkflowRepository, CharacterRepository
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.services.prompt_builder import build_character_prompt, get_style


class CharacterService:
    """角色服务"""

    def __init__(self, db: Session = None):
        self.db = db
        self.comfyui_service = ComfyUIService()

    # ==================== 音色生成 ====================

    def create_character_voice_task(
        self,
        character_id: str,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        创建角色音色生成任务

        Args:
            character_id: 角色ID
            db: 数据库会话

        Returns:
            创建结果
        """
        db = db or self.db
        character_repo = CharacterRepository(db)
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)

        # 获取角色
        character = character_repo.get_by_id(character_id)
        if not character:
            return {"success": False, "message": "角色不存在"}

        # 检查角色是否有音色提示词
        if not character.voice_prompt:
            return {"success": False, "message": "角色缺少音色提示词，请先设置音色描述"}

        # 检查是否已有进行中的音色生成任务
        existing_task = task_repo.get_active_by_character_and_type(character_id, "character_voice")
        if existing_task:
            return {
                "success": True,
                "message": "已有进行中的音色生成任务",
                "data": {
                    "taskId": existing_task.id,
                    "status": existing_task.status
                }
            }

        # 获取并验证工作流
        workflow = workflow_repo.get_active_by_type("voice_design")
        if not workflow:
            return {"success": False, "message": "未找到激活的音色设计工作流"}

        # 创建任务
        task = Task(
            type="character_voice",
            name=f"生成角色音色: {character.name}",
            description=f"为角色 '{character.name}' 生成参考音频",
            novel_id=character.novel_id,
            character_id=character_id,
            status="pending"
        )
        task_repo.create(task)

        db.commit()

        # 启动后台任务
        asyncio.create_task(
            self._generate_voice_task(
                task.id,
                character_id,
                character.name,
                character.voice_prompt
            )
        )

        return {
            "success": True,
            "message": "音色生成任务已创建",
            "data": {
                "taskId": task.id,
                "status": "pending"
            }
        }

    async def _generate_voice_task(
        self,
        task_id: str,
        character_id: str,
        character_name: str,
        voice_prompt: str
    ):
        """
        后台任务：生成角色音色

        Args:
            task_id: 任务ID
            character_id: 角色ID
            character_name: 角色名称
            voice_prompt: 音色提示词
        """
        from app.core.database import SessionLocal
        db = SessionLocal()
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)
        character_repo = CharacterRepository(db)

        try:
            # 获取任务
            task = task_repo.get_by_id(task_id)
            if not task:
                return

            # 获取当前激活的 voice_design 工作流
            workflow = workflow_repo.get_active_by_type("voice_design")

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

            # 获取工作流JSON字符串
            workflow_json_str = workflow.workflow_json if workflow else None
            print(f"[VoiceTask] Workflow JSON available: {workflow_json_str is not None}")

            # 获取工作流的节点映射配置
            node_mapping = None
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                    print(f"[VoiceTask] Using node mapping: {node_mapping}")
                except Exception as e:
                    print(f"[VoiceTask] Failed to parse node_mapping: {e}")

            # 构建音色设计工作流
            # 使用标准测试文本生成参考音频
            test_text = f"大家好，我是{character_name}，很高兴认识你们。"

            submitted_workflow = self.comfyui_service.builder.build_voice_design_workflow(
                voice_prompt=voice_prompt,
                text=test_text,
                workflow_json=workflow_json_str,
                novel_id=task.novel_id,
                character_name=character_name,
                node_mapping=node_mapping
            )

            # 保存构建后的完整工作流到任务
            task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
            task.prompt_text = f"音色: {voice_prompt}\n文本: {test_text}"
            db.commit()

            # 调用 ComfyUI 生成音频
            result = await self.comfyui_service.generate_voice(
                voice_prompt=voice_prompt,
                text=test_text,
                workflow_json=workflow_json_str,
                novel_id=task.novel_id,
                character_name=character_name,
                node_mapping=node_mapping,
                workflow=submitted_workflow
            )

            print(f"[VoiceTask] Generation result: {result}")

            if result.get("success"):
                audio_url = result.get("audio_url")

                # 下载音频到本地存储
                task.current_step = "下载音频到服务器..."
                db.commit()

                try:
                    local_path = await file_storage.download_audio(
                        url=audio_url,
                        novel_id=task.novel_id or "default",
                        character_name=character_name,
                        audio_type="voice"
                    )

                    if local_path:
                        # 构建本地可访问的URL
                        relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                        local_url = f"/api/files/{relative_path.lstrip('/')}"
                        task.result_url = local_url
                        task.current_step = "生成完成，音频已保存"
                    else:
                        # 下载失败，使用原始URL
                        task.result_url = audio_url
                        task.current_step = "生成完成，使用远程音频"
                except Exception as e:
                    print(f"[VoiceTask] Failed to download audio: {e}")
                    task.result_url = audio_url
                    task.current_step = "生成完成，使用远程音频"

                task.status = "completed"
                task.progress = 100
                task.completed_at = datetime.utcnow()

                # 更新角色参考音频URL
                character = character_repo.get_by_id(character_id)
                if character:
                    character.reference_audio_url = task.result_url
            else:
                task.status = "failed"
                task.error_message = result.get("message", "生成失败")
                task.current_step = "生成失败"

            db.commit()

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"
            db.commit()
        finally:
            db.close()
    
    def create_character_portrait_task(
        self, 
        character_id: str,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        创建角色人设图生成任务
        
        Args:
            character_id: 角色ID
            db: 数据库会话
            
        Returns:
            创建结果
        """
        db = db or self.db
        character_repo = CharacterRepository(db)
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)
        
        # 获取角色
        character = character_repo.get_by_id(character_id)
        if not character:
            return {"success": False, "message": "角色不存在"}
        
        # 检查是否已有进行中的任务
        existing_task = task_repo.get_active_by_character(character_id)
        if existing_task:
            return {
                "success": True,
                "message": "已有进行中的生成任务",
                "data": {
                    "taskId": existing_task.id,
                    "status": existing_task.status
                }
            }
        
        # 检查角色生成状态
        if character.generating_status == "running":
            return {
                "success": False,
                "message": "该角色正在生成形象中，请稍后再试"
            }
        
        # 获取并验证工作流
        workflow = workflow_repo.get_active_by_type("character")
        is_valid, error_msg = self._validate_workflow_node_mapping(workflow, "character")
        if not is_valid:
            return {"success": False, "message": error_msg}
        
        # 创建任务
        task = Task(
            type="character_portrait",
            name=f"生成角色形象: {character.name}",
            description=f"为角色 '{character.name}' 生成人设图",
            novel_id=character.novel_id,
            character_id=character_id,
            status="pending"
        )
        task_repo.create(task)
        
        # 更新角色生成状态
        character.generating_status = "running"
        character.portrait_task_id = task.id
        db.commit()
        
        # 启动后台任务
        asyncio.create_task(
            self._generate_portrait_task(
                task.id,
                character_id,
                character.name,
                character.appearance,
                character.description
            )
        )
        
        return {
            "success": True,
            "message": "人设图生成任务已创建",
            "data": {
                "taskId": task.id,
                "status": "pending"
            }
        }
    
    async def _generate_portrait_task(
        self,
        task_id: str,
        character_id: str,
        name: str,
        appearance: str,
        description: str
    ):
        """
        后台任务：生成角色人设图
        
        Args:
            task_id: 任务ID
            character_id: 角色ID
            name: 角色名称
            appearance: 外貌描述
            description: 角色描述
        """
        from app.core.database import SessionLocal
        db = SessionLocal()
        task_repo = TaskRepository(db)
        workflow_repo = WorkflowRepository(db)
        character_repo = CharacterRepository(db)
        
        try:
            # 获取任务
            task = task_repo.get_by_id(task_id)
            if not task:
                return

            # 获取当前激活的 character 工作流
            workflow = workflow_repo.get_active_by_type("character")

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

            # 获取角色所属小说
            character = character_repo.get_by_id(character_id)
            from app.models.novel import Novel
            novel = db.query(Novel).filter(Novel.id == character.novel_id).first() if character else None

            # 获取角色生成提示词模板
            from app.repositories import PromptTemplateRepository
            template_repo = PromptTemplateRepository(db)
            template = None
            if novel and novel.prompt_template_id:
                template = template_repo.get_by_id(novel.prompt_template_id)

            # 如果没有指定模板，使用默认系统模板
            if not template:
                template = template_repo.get_default_system_template("character")

            # 获取风格提示词
            style, style_template = get_style(db, novel, "character")

            # 构建提示词
            prompt = build_character_prompt(name, appearance, description, template.template if template else None, style)

            task.current_step = f"使用模板: {template.name if template else '默认'}, 风格: {style_template.name if style_template else '默认'}, 提示词: {prompt[:80]}..."

            # 保存提示词
            task.prompt_text = prompt
            db.commit()

            # 获取工作流JSON字符串
            workflow_json_str = workflow.workflow_json if workflow else None
            print(
                f"[Task] Workflow JSON available: {workflow_json_str is not None}, length: {len(workflow_json_str) if workflow_json_str else 0}")

            # 获取工作流的节点映射配置
            node_mapping = None
            if workflow and workflow.node_mapping:
                try:
                    node_mapping = json.loads(workflow.node_mapping)
                    print(f"[Task] Using node mapping: {node_mapping}")
                except Exception as e:
                    print(f"[Task] Failed to parse node_mapping: {e}")

            # 构建实际提交给ComfyUI的完整工作流（注入参数后）
            print(f"[Task] Building workflow with: {workflow.name if workflow else 'default'}")
            print(f"[Task] Novel ID: {task.novel_id}, Character: {name}")

            submitted_workflow = self.comfyui_service.builder.build_character_workflow(
                prompt=prompt,
                workflow_json=workflow_json_str,
                novel_id=task.novel_id,
                character_name=name,
                aspect_ratio=novel.aspect_ratio if novel else None,
                node_mapping=node_mapping,
                style=style
            )

            # 保存构建后的完整工作流到任务，让用户可以立即查看
            task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
            db.commit()
            print(f"[Task] Saved submitted workflow to task")

            # 调用 ComfyUI 生成图片（使用已构建的工作流）
            result = await self.comfyui_service.generate_character_image(
                prompt,
                workflow_json=workflow_json_str,
                novel_id=task.novel_id,
                character_name=name,
                aspect_ratio=novel.aspect_ratio if novel else None,
                node_mapping=node_mapping,
                workflow=submitted_workflow  # 传递已构建的工作流，避免重复构建
            )

            print(f"[Task] Generation result: {result}")

            if result.get("success"):
                image_url = result.get("image_url")

                # 下载图片到本地存储
                task.current_step = "下载图片到服务器..."
                db.commit()

                try:
                    local_path = await file_storage.download_image(
                        url=image_url,
                        novel_id=task.novel_id or "default",
                        character_name=name,
                        image_type="character"
                    )

                    if local_path:
                        # 构建本地可访问的URL (通过静态文件服务)
                        relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                        local_url = f"/api/files/{relative_path.lstrip('/')}"
                        task.result_url = local_url
                        task.current_step = "生成完成，图片已保存"
                    else:
                        # 下载失败，使用原始URL
                        task.result_url = image_url
                        task.current_step = "生成完成，使用远程图片"
                except Exception as e:
                    print(f"[Task] Failed to download image: {e}")
                    task.result_url = image_url
                    task.current_step = "生成完成，使用远程图片"

                task.status = "completed"
                task.progress = 100
                task.completed_at = datetime.utcnow()

                # 更新角色图片和状态
                character = character_repo.get_by_id(character_id)
                if character:
                    character.image_url = task.result_url
                    character.generating_status = "completed"
            else:
                task.status = "failed"
                task.error_message = result.get("message", "生成失败")
                task.current_step = "生成失败"

                # 更新角色状态为失败
                character = character_repo.get_by_id(character_id)
                if character:
                    character.generating_status = "failed"

            db.commit()

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"

            # 更新角色状态为失败
            try:
                character = character_repo.get_by_id(character_id)
                if character:
                    character.generating_status = "failed"
            except:
                pass

            db.commit()
        finally:
            db.close()
    
    def _validate_workflow_node_mapping(self, workflow: Workflow, task_type: str) -> tuple[bool, str]:
        """
        验证工作流的节点映射配置是否完整
        
        Args:
            workflow: 工作流对象
            task_type: 任务类型 (character)
            
        Returns:
            (是否有效, 错误信息)
        """
        if not workflow:
            # 使用默认工作流，不需要验证
            return True, ""

        # 解析节点映射
        node_mapping = {}
        if workflow.node_mapping:
            try:
                node_mapping = json.loads(workflow.node_mapping)
            except Exception:
                return False, f"工作流 '{workflow.name}' 的节点映射配置格式无效"

        # 根据任务类型检查必需的字段
        required_fields = {
            "character": ["prompt_node_id", "save_image_node_id"],
        }

        fields = required_fields.get(task_type)
        if not fields:
            return True, ""

        missing_fields = []
        field_names = {
            "prompt_node_id": "提示词输入节点",
            "save_image_node_id": "图片保存节点",
        }

        for field in fields:
            if not node_mapping.get(field):
                missing_fields.append(field_names.get(field, field))

        if missing_fields:
            return False, f"工作流 '{workflow.name}' 的映射配置不完整，缺少以下必需字段：{', '.join(missing_fields)}。请在【系统配置-ComfyUI工作流】中配置完整后再试。"

        return True, ""

    # ==================== 旁白角色管理 ====================

    def ensure_narrator_character(self, novel_id: str, db: Session = None) -> Dict[str, Any]:
        """
        确保小说有旁白角色，不存在则创建

        Args:
            novel_id: 小说ID
            db: 数据库会话

        Returns:
            操作结果，包含旁白角色信息
        """
        db = db or self.db
        character_repo = CharacterRepository(db)

        # 查询是否已存在旁白角色
        narrator = character_repo.get_narrator(novel_id)
        if narrator:
            return {
                "success": True,
                "message": "旁白角色已存在",
                "data": {
                    "id": narrator.id,
                    "name": narrator.name,
                    "isNarrator": True
                }
            }

        # 创建旁白角色
        narrator = character_repo.create_narrator(novel_id)

        return {
            "success": True,
            "message": "旁白角色创建成功",
            "data": {
                "id": narrator.id,
                "name": narrator.name,
                "isNarrator": True
            }
        }