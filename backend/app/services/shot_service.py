"""
分镜服务层

封装分镜相关的业务逻辑
"""
import json
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.models.shot import Shot
from app.repositories.shot_repository import ShotRepository


class ShotService:
    """分镜服务"""

    def __init__(self, db: Session):
        self.db = db
        self.shot_repo = ShotRepository(db)

    def get_shots_by_chapter(self, chapter_id: str) -> List[Dict[str, Any]]:
        """
        获取章节的所有分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            分镜响应列表
        """
        shots = self.shot_repo.get_by_chapter(chapter_id)
        return [self.shot_repo.to_response(shot) for shot in shots]

    def get_shot_by_id(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取分镜

        Args:
            shot_id: 分镜 ID

        Returns:
            分镜响应字典或 None
        """
        shot = self.shot_repo.get_by_id(shot_id)
        if shot:
            return self.shot_repo.to_response(shot)
        return None

    def get_shot_by_index(self, chapter_id: str, index: int) -> Optional[Dict[str, Any]]:
        """
        根据章节和序号获取分镜

        Args:
            chapter_id: 章节 ID
            index: 分镜序号

        Returns:
            分镜响应字典或 None
        """
        shot = self.shot_repo.get_by_chapter_and_index(chapter_id, index)
        if shot:
            return self.shot_repo.to_response(shot)
        return None

    def update_shot(self, shot_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        更新分镜

        Args:
            shot_id: 分镜 ID
            data: 更新数据

        Returns:
            更新后的分镜响应字典或 None
        """
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return None

        # 过滤出有效的更新字段
        valid_fields = {
            'description', 'characters', 'scene', 'props', 'duration',
            'image_url', 'image_path', 'image_status', 'image_task_id',
            'video_url', 'video_status', 'video_task_id',
            'merged_character_image', 'dialogues'
        }
        update_data = {k: v for k, v in data.items() if k in valid_fields}

        if update_data:
            self.shot_repo.update(shot, **update_data)

        return self.shot_repo.to_response(shot)

    def update_shot_image(
        self,
        shot_id: str,
        image_url: str,
        image_path: str = None,
        status: str = "completed"
    ) -> Optional[Dict[str, Any]]:
        """
        更新分镜图片

        Args:
            shot_id: 分镜 ID
            image_url: 图片 URL
            image_path: 图片本地路径
            status: 图片状态

        Returns:
            更新后的分镜响应字典或 None
        """
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return None

        self.shot_repo.update_image_status(
            shot,
            status=status,
            image_url=image_url,
            image_path=image_path
        )
        return self.shot_repo.to_response(shot)

    def update_shot_video(
        self,
        shot_id: str,
        video_url: str,
        status: str = "completed"
    ) -> Optional[Dict[str, Any]]:
        """
        更新分镜视频

        Args:
            shot_id: 分镜 ID
            video_url: 视频 URL
            status: 视频状态

        Returns:
            更新后的分镜响应字典或 None
        """
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return None

        self.shot_repo.update_video_status(
            shot,
            status=status,
            video_url=video_url
        )
        return self.shot_repo.to_response(shot)

    def update_shot_dialogues(
        self,
        shot_id: str,
        dialogues: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        更新分镜台词

        Args:
            shot_id: 分镜 ID
            dialogues: 台词数据列表

        Returns:
            更新后的分镜响应字典或 None
        """
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return None

        self.shot_repo.update_dialogues(shot, dialogues)
        return self.shot_repo.to_response(shot)

    def set_shot_image_generating(self, shot_id: str, task_id: str = None) -> Optional[Dict[str, Any]]:
        """
        设置分镜图片生成中状态

        Args:
            shot_id: 分镜 ID
            task_id: 任务 ID

        Returns:
            更新后的分镜响应字典或 None
        """
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return None

        self.shot_repo.update_image_status(shot, status="generating", task_id=task_id)
        return self.shot_repo.to_response(shot)

    def set_shot_video_generating(self, shot_id: str, task_id: str = None) -> Optional[Dict[str, Any]]:
        """
        设置分镜视频生成中状态

        Args:
            shot_id: 分镜 ID
            task_id: 任务 ID

        Returns:
            更新后的分镜响应字典或 None
        """
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return None

        self.shot_repo.update_video_status(shot, status="generating", task_id=task_id)
        return self.shot_repo.to_response(shot)

    def set_shot_image_failed(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        设置分镜图片生成失败状态

        Args:
            shot_id: 分镜 ID

        Returns:
            更新后的分镜响应字典或 None
        """
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return None

        self.shot_repo.update_image_status(shot, status="failed")
        return self.shot_repo.to_response(shot)

    def set_shot_video_failed(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        设置分镜视频生成失败状态

        Args:
            shot_id: 分镜 ID

        Returns:
            更新后的分镜响应字典或 None
        """
        shot = self.shot_repo.get_by_id(shot_id)
        if not shot:
            return None

        self.shot_repo.update_video_status(shot, status="failed")
        return self.shot_repo.to_response(shot)

    def create_shots_from_parsed_data(
        self,
        chapter_id: str,
        shots_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        从解析数据创建分镜

        Args:
            chapter_id: 章节 ID
            shots_data: 分镜数据列表

        Returns:
            创建的分镜响应列表
        """
        # 先删除现有分镜
        self.shot_repo.delete_by_chapter(chapter_id)

        # 准备批量创建数据
        create_data = []
        for idx, shot_data in enumerate(shots_data, 1):
            data = {
                "chapter_id": chapter_id,
                "index": idx,
                "description": shot_data.get("description", ""),
                "characters": shot_data.get("characters", []),
                "scene": shot_data.get("scene", ""),
                "props": shot_data.get("props", []),
                "duration": shot_data.get("duration", 4),
                "image_url": shot_data.get("image_url"),
                "image_path": shot_data.get("image_path"),
                "image_status": "completed" if shot_data.get("image_url") else "pending",
                "image_task_id": shot_data.get("image_task_id"),
                "video_url": shot_data.get("video_url"),
                "video_status": "completed" if shot_data.get("video_url") else "pending",
                "video_task_id": shot_data.get("video_task_id"),
                "merged_character_image": shot_data.get("merged_character_image"),
                "dialogues": shot_data.get("dialogues", []),
            }
            create_data.append(data)

        # 批量创建
        shots = self.shot_repo.bulk_create(create_data)
        return [self.shot_repo.to_response(shot) for shot in shots]

    def get_pending_image_shots(self, chapter_id: str) -> List[Dict[str, Any]]:
        """
        获取待生成图片的分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            待生成图片的分镜列表
        """
        shots = self.shot_repo.get_pending_image_shots(chapter_id)
        return [self.shot_repo.to_response(shot) for shot in shots]

    def get_pending_video_shots(self, chapter_id: str) -> List[Dict[str, Any]]:
        """
        获取待生成视频的分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            待生成视频的分镜列表
        """
        shots = self.shot_repo.get_pending_video_shots(chapter_id)
        return [self.shot_repo.to_response(shot) for shot in shots]

    def count_shots_by_chapter(self, chapter_id: str) -> int:
        """
        统计章节的分镜数量

        Args:
            chapter_id: 章节 ID

        Returns:
            分镜数量
        """
        return self.shot_repo.count_by_chapter(chapter_id)

    def get_shot_entity(self, shot_id: str) -> Optional[Shot]:
        """
        获取分镜实体对象（用于内部服务调用）

        Args:
            shot_id: 分镜 ID

        Returns:
            分镜实体对象或 None
        """
        return self.shot_repo.get_by_id(shot_id)