"""关键帧服务

提供关键帧描述生成、图片生成、图片上传、参考图设置等功能。
"""

import json
import os
import uuid
import httpx
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.models.novel import Novel, Chapter
from app.models.prompt_template import PromptTemplate
from app.repositories.shot_repository import ShotRepository
from app.services.comfyui import ComfyUIService
from app.services.llm_service import LLMService
from app.services.file_storage import file_storage
from app.utils.path_utils import url_to_local_path


class ShotKeyframeService:
    """关键帧服务类"""

    def __init__(self):
        self.llm_service = LLMService()

    def _get_novel_id(self, db: Session, shot: Shot) -> Optional[str]:
        """通过分镜获取小说ID

        Args:
            db: 数据库会话
            shot: 分镜对象

        Returns:
            小说ID，如果获取失败返回None
        """
        chapter = db.query(Chapter).filter(Chapter.id == shot.chapter_id).first()
        return chapter.novel_id if chapter else None

    async def generate_keyframe_descriptions(
        self,
        db: Session,
        shot_id: str,
        count: int = 3
    ) -> Tuple[bool, List[dict], str]:
        """生成关键帧描述

        使用 LLM 根据分镜描述生成关键帧描述列表。
        支持使用小说级别配置的关键帧描述提示词模板。

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            count: 要生成的关键帧数量

        Returns:
            (success, keyframes, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, [], f"分镜 {shot_id} 不存在"

        # 获取小说信息以获取模板配置
        novel_id = self._get_novel_id(db, shot)
        novel = db.query(Novel).filter(Novel.id == novel_id).first() if novel_id else None

        # 构建提示词
        prompt = self._build_keyframe_prompt(db, shot, count, novel)

        try:
            # 调用 LLM 生成
            response = await self.llm_service.chat_completion(
                system_prompt="你是一个专业的视频分镜师，擅长分析镜头并拆分关键帧。请根据镜头描述生成关键帧的详细描述。",
                user_content=prompt,
                temperature=0.7,
                response_format="json_object"
            )

            content = response.get("content", "")

            # 解析 JSON
            # 尝试提取 JSON 数组
            import re
            json_match = re.search(r'\[\s*\{.*\}\s*\]', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)

            keyframes = json.loads(content)

            # 验证格式
            validated_keyframes = []
            for i, kf in enumerate(keyframes[:count]):
                validated_keyframes.append({
                    "frame_index": kf.get("frame_index", i),
                    "description": kf.get("description", ""),
                    "image_url": None,
                    "image_task_id": None,
                    "reference_image_url": None,
                    "reference_mode": "auto_select"
                })

            # 更新分镜的关键帧数据
            shot_repo.update(shot, keyframes=validated_keyframes)

            return True, validated_keyframes, f"成功生成 {len(validated_keyframes)} 个关键帧描述"

        except json.JSONDecodeError as e:
            return False, [], f"解析关键帧描述失败：{str(e)}"
        except Exception as e:
            return False, [], f"生成关键帧描述失败：{str(e)}"

    def _build_keyframe_prompt(
        self,
        db: Session,
        shot: Shot,
        count: int,
        novel: Optional[Novel]
    ) -> str:
        """构建关键帧描述生成提示词

        优先使用小说配置的关键帧描述提示词模板。

        Args:
            db: 数据库会话
            shot: 分镜对象
            count: 关键帧数量
            novel: 小说对象

        Returns:
            构建好的提示词
        """
        # 尝试获取小说配置的关键帧描述模板
        template = None
        if novel and novel.keyframe_description_prompt_template_id:
            template = db.query(PromptTemplate).filter(
                PromptTemplate.id == novel.keyframe_description_prompt_template_id
            ).first()

        # 如果没有配置模板，使用默认模板
        if not template:
            template = db.query(PromptTemplate).filter(
                PromptTemplate.type == "keyframe_description",
                PromptTemplate.is_system == True,
                PromptTemplate.is_active == True
            ).first()

        # 构建视频描述部分
        video_description = f"视频描述：{shot.video_description}" if shot.video_description else ""

        if template:
            # 使用模板生成提示词
            prompt = template.template.format(
                count=count,
                shot_description=shot.description,
                video_description=video_description
            )
        else:
            # 使用默认硬编码提示词
            prompt = f"""请根据以下分镜描述，生成 {count} 个关键帧描述。

分镜描述：
{shot.description}

{video_description}

要求：
1. 每个关键帧描述应该是该分镜中一个重要的画面瞬间
2. 描述应该详细且具有画面感，包含人物动作、表情、场景细节等
3. 关键帧应该按照时间顺序排列，展示分镜的动态过程
4. 每个描述控制在50-100字

请直接返回JSON数组格式，每个元素包含：
- frame_index: 帧序号（从0开始）
- description: 关键帧描述

示例格式：
[
  {{"frame_index": 0, "description": "第1个关键帧的描述"}},
  {{"frame_index": 1, "description": "第2个关键帧的描述"}}
]"""

        return prompt

    async def generate_keyframe_image(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        workflow_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str], str]:
        """生成关键帧图片

        使用 ComfyUI 工作流生成关键帧图片。

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号
            workflow_id: 指定的工作流 ID

        Returns:
            (success, task_id, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        keyframe = keyframes[frame_index]

        # 获取 novel_id
        novel_id = self._get_novel_id(db, shot)

        # 创建任务
        task = Task(
            id=str(uuid.uuid4()),
            type="keyframe_image",
            status="pending",
            shot_id=shot_id,
            novel_id=novel_id,
            chapter_id=shot.chapter_id,
            extra_data=json.dumps({
                "frame_index": frame_index,
                "workflow_id": workflow_id
            })
        )
        db.add(task)
        db.commit()

        # 启动后台任务
        from app.core.database import SessionLocal
        import asyncio

        async def run_background_task():
            db_bg = SessionLocal()
            try:
                await self._generate_keyframe_image_task(
                    db_bg, task.id, shot_id, frame_index, keyframe, workflow_id
                )
            except Exception as e:
                # 更新任务状态为失败
                task_bg = db_bg.query(Task).filter(Task.id == task.id).first()
                if task_bg:
                    task_bg.status = "failed"
                    task_bg.error_message = str(e)
                    db_bg.commit()
            finally:
                db_bg.close()

        asyncio.create_task(run_background_task())

        return True, task.id, f"关键帧图片生成任务已创建"

    async def _generate_keyframe_image_task(
        self,
        db: Session,
        task_id: str,
        shot_id: str,
        frame_index: int,
        keyframe: dict,
        workflow_id: Optional[str] = None
    ):
        """关键帧图片生成后台任务"""
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return

        # 更新任务状态
        task.status = "running"
        db.commit()

        try:
            shot_repo = ShotRepository(db)
            shot = shot_repo.get_by_id(shot_id)

            if not shot:
                raise ValueError(f"分镜 {shot_id} 不存在")

            # 获取小说信息
            novel_id = self._get_novel_id(db, shot)
            if not novel_id:
                raise ValueError(f"无法获取分镜 {shot_id} 对应的小说")

            novel = db.query(Novel).filter(Novel.id == novel_id).first()
            if not novel:
                raise ValueError(f"小说 {novel_id} 不存在")

            # 获取工作流
            if not workflow_id:
                # 获取默认关键帧工作流
                workflow = db.query(Workflow).filter(
                    Workflow.type == "keyframe_image",
                    Workflow.is_active == True
                ).first()
                if not workflow:
                    # 回退到分镜图片工作流
                    workflow = db.query(Workflow).filter(
                        Workflow.type == "shot",
                        Workflow.is_active == True
                    ).first()
            else:
                workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()

            if not workflow:
                raise ValueError("未找到可用的工作流")

            node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}

            comfyui_service = ComfyUIService()

            # 确定参考图
            reference_image_url = keyframe.get("reference_image_url")
            reference_path = None

            if reference_image_url:
                # 获取参考图本地路径
                reference_path = url_to_local_path(reference_image_url)

            # 获取关键帧描述作为提示词
            prompt = keyframe.get("description", shot.description)

            # 生成图片
            result = await comfyui_service.generate_shot_image_with_workflow(
                prompt=prompt,
                workflow_json=workflow.workflow_json,
                node_mapping=node_mapping,
                aspect_ratio=novel.aspect_ratio or "16:9",
                character_reference_path=reference_path
            )

            if result.get("success") and result.get("image_url"):
                image_url = result["image_url"]

                # 下载图片到本地存储
                local_path = await file_storage.download_image(
                    url=image_url,
                    novel_id=novel_id,
                    character_name=f"keyframe_{frame_index}",
                    image_type="keyframe",
                    chapter_id=shot.chapter_id
                )

                if local_path:
                    # 构建本地 URL
                    relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                    local_url = f"/api/files/{relative_path.lstrip('/')}"

                    # 更新关键帧数据
                    keyframes = json.loads(shot.keyframes) if shot.keyframes else []
                    if frame_index < len(keyframes):
                        keyframes[frame_index]["image_url"] = local_url
                        keyframes[frame_index]["image_task_id"] = task_id
                        shot_repo.update(shot, keyframes=keyframes)

                    # 更新任务状态
                    task.status = "completed"
                    task.result = json.dumps({"image_url": local_url})
                    db.commit()
                else:
                    raise ValueError("下载图片失败")
            else:
                raise ValueError(result.get("message", "图片生成失败"))

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            db.commit()
            raise

    async def upload_keyframe_image(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        file_content: bytes,
        filename: str
    ) -> Tuple[bool, Optional[str], str]:
        """上传关键帧图片

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号
            file_content: 文件内容
            filename: 文件名

        Returns:
            (success, image_url, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        # 通过 chapter 获取 novel_id
        chapter = db.query(Chapter).filter(Chapter.id == shot.chapter_id).first()
        if not chapter:
            return False, None, f"章节 {shot.chapter_id} 不存在"

        novel_id = chapter.novel_id

        try:
            # 保存图片到本地存储
            file_ext = os.path.splitext(filename)[1] or ".png"
            save_dir = file_storage.base_dir / novel_id / "keyframes" / shot_id / str(frame_index)
            save_dir.mkdir(parents=True, exist_ok=True)

            file_name = f"{uuid.uuid4()}{file_ext}"
            full_path = save_dir / file_name

            with open(full_path, "wb") as f:
                f.write(file_content)

            # 构建本地 URL
            relative_path = str(full_path.relative_to(file_storage.base_dir)).replace("\\", "/")
            image_url = f"/api/files/{relative_path}"

            # 更新关键帧数据
            keyframes[frame_index]["image_url"] = image_url
            shot_repo.update(shot, keyframes=keyframes)

            return True, image_url, "关键帧图片上传成功"

        except Exception as e:
            return False, None, f"上传失败：{str(e)}"

    async def upload_reference_image(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        file_content: bytes,
        filename: str
    ) -> Tuple[bool, Optional[str], str]:
        """上传参考图

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号
            file_content: 文件内容
            filename: 文件名

        Returns:
            (success, reference_url, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        # 通过 chapter 获取 novel_id
        chapter = db.query(Chapter).filter(Chapter.id == shot.chapter_id).first()
        if not chapter:
            return False, None, f"章节 {shot.chapter_id} 不存在"

        novel_id = chapter.novel_id

        try:
            # 保存参考图到本地存储
            file_ext = os.path.splitext(filename)[1] or ".png"
            save_dir = file_storage.base_dir / novel_id / "keyframes" / shot_id / str(frame_index) / "reference"
            save_dir.mkdir(parents=True, exist_ok=True)

            file_name = f"{uuid.uuid4()}{file_ext}"
            full_path = save_dir / file_name

            with open(full_path, "wb") as f:
                f.write(file_content)

            # 构建本地 URL
            relative_path = str(full_path.relative_to(file_storage.base_dir)).replace("\\", "/")
            reference_url = f"/api/files/{relative_path}"

            # 更新关键帧数据：同时保存 reference_image_url 和 reference_mode
            keyframes[frame_index]["reference_image_url"] = reference_url
            keyframes[frame_index]["reference_mode"] = "custom"
            shot_repo.update(shot, keyframes=keyframes)

            return True, reference_url, "参考图上传成功"

        except Exception as e:
            return False, None, f"上传失败：{str(e)}"

    async def set_reference_image(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        mode: str = "auto_select",
        reference_url: Optional[str] = None
    ) -> Tuple[bool, Optional[str], str]:
        """设置参考图

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号
            mode: 模式 ("auto_select" | "custom" | "none")
            reference_url: 自定义参考图 URL（mode 为 "custom" 时使用）

        Returns:
            (success, reference_url, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        final_reference_url = None

        if mode == "none":
            # 不使用参考图
            final_reference_url = None

        elif mode == "custom":
            # 使用自定义参考图
            final_reference_url = reference_url

        elif mode == "auto_select":
            # 自动选择参考图
            final_reference_url = self._auto_select_reference_image(
                shot, keyframes, frame_index
            )

        # 更新关键帧数据：同时保存 reference_image_url 和 reference_mode
        keyframes[frame_index]["reference_image_url"] = final_reference_url
        keyframes[frame_index]["reference_mode"] = mode
        shot_repo.update(shot, keyframes=keyframes)

        return True, final_reference_url, "参考图设置成功"

    def _auto_select_reference_image(
        self,
        shot: Shot,
        keyframes: List[dict],
        frame_index: int
    ) -> Optional[str]:
        """自动选择参考图

        选择优先级：
        1. 如果有上一关键帧且已生成图片，使用上一关键帧图片
        2. 否则使用分镜图

        Args:
            shot: 分镜对象
            keyframes: 关键帧列表
            frame_index: 当前关键帧序号

        Returns:
            参考图 URL 或 None
        """
        # 检查是否有上一关键帧
        if frame_index > 0:
            prev_keyframe = keyframes[frame_index - 1]
            prev_image_url = prev_keyframe.get("image_url")
            if prev_image_url:
                return prev_image_url

        # 使用分镜图
        if shot.image_url:
            return shot.image_url

        return None

    async def add_keyframe(
        self,
        db: Session,
        shot_id: str,
        description: str,
        insert_index: Optional[int] = None
    ) -> Tuple[bool, Optional[dict], str]:
        """添加关键帧

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            description: 关键帧描述
            insert_index: 插入位置（如果为 None 则追加到最后）

        Returns:
            (success, keyframe, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []

        new_keyframe = {
            "frame_index": 0,
            "description": description,
            "image_url": None,
            "image_task_id": None,
            "reference_image_url": None
        }

        if insert_index is not None and 0 <= insert_index <= len(keyframes):
            # 插入到指定位置
            keyframes.insert(insert_index, new_keyframe)
        else:
            # 追加到最后
            keyframes.append(new_keyframe)

        # 更新 frame_index
        for i, kf in enumerate(keyframes):
            kf["frame_index"] = i

        shot_repo.update(shot, keyframes=keyframes)

        return True, keyframes[new_keyframe["frame_index"]], "关键帧添加成功"

    async def update_keyframe(
        self,
        db: Session,
        shot_id: str,
        frame_index: int,
        description: Optional[str] = None
    ) -> Tuple[bool, Optional[dict], str]:
        """更新关键帧

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号
            description: 新的关键帧描述

        Returns:
            (success, keyframe, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        if description is not None:
            keyframes[frame_index]["description"] = description

        shot_repo.update(shot, keyframes=keyframes)

        return True, keyframes[frame_index], "关键帧更新成功"

    async def delete_keyframe(
        self,
        db: Session,
        shot_id: str,
        frame_index: int
    ) -> Tuple[bool, None, str]:
        """删除关键帧

        Args:
            db: 数据库会话
            shot_id: 分镜 ID
            frame_index: 关键帧序号

        Returns:
            (success, None, message) 元组
        """
        shot_repo = ShotRepository(db)
        shot = shot_repo.get_by_id(shot_id)

        if not shot:
            return False, None, f"分镜 {shot_id} 不存在"

        # 解析关键帧数据
        keyframes = json.loads(shot.keyframes) if shot.keyframes else []
        if frame_index >= len(keyframes):
            return False, None, f"关键帧序号 {frame_index} 超出范围"

        # 删除关键帧
        del keyframes[frame_index]

        # 更新 frame_index
        for i, kf in enumerate(keyframes):
            kf["frame_index"] = i

        shot_repo.update(shot, keyframes=keyframes)

        return True, None, "关键帧删除成功"