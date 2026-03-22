"""
分镜数据仓库

封装分镜相关的数据库查询逻辑
"""
import json
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.shot import Shot


class ShotRepository:
    """分镜数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def get_by_chapter(self, chapter_id: str) -> List[Shot]:
        """
        获取章节的所有分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            分镜列表，按 index 排序
        """
        return self.db.query(Shot).filter(
            Shot.chapter_id == chapter_id
        ).order_by(Shot.index).all()

    def get_by_id(self, shot_id: str) -> Optional[Shot]:
        """
        根据 ID 获取分镜

        Args:
            shot_id: 分镜 ID

        Returns:
            分镜对象或 None
        """
        return self.db.query(Shot).filter(Shot.id == shot_id).first()

    def get_by_chapter_and_index(self, chapter_id: str, index: int) -> Optional[Shot]:
        """
        根据章节 ID 和分镜序号获取分镜

        Args:
            chapter_id: 章节 ID
            index: 分镜序号 (1-based)

        Returns:
            分镜对象或 None
        """
        return self.db.query(Shot).filter(
            Shot.chapter_id == chapter_id,
            Shot.index == index
        ).first()

    def create(
        self,
        chapter_id: str,
        index: int,
        description: str = "",
        characters: List[str] = None,
        scene: str = "",
        props: List[str] = None,
        duration: int = 4,
        **kwargs
    ) -> Shot:
        """
        创建分镜

        Args:
            chapter_id: 章节 ID
            index: 分镜序号 (1-based)
            description: 分镜描述
            characters: 角色名称列表
            scene: 场景名称
            props: 道具名称列表
            duration: 时长（秒）
            **kwargs: 其他字段

        Returns:
            创建的分镜对象
        """
        shot = Shot(
            chapter_id=chapter_id,
            index=index,
            description=description,
            characters=json.dumps(characters or [], ensure_ascii=False),
            scene=scene,
            props=json.dumps(props or [], ensure_ascii=False),
            duration=duration,
        )

        # 设置其他字段
        for key, value in kwargs.items():
            if hasattr(shot, key):
                if key in ('characters', 'props', 'dialogues') and isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                setattr(shot, key, value)

        self.db.add(shot)
        self.db.commit()
        self.db.refresh(shot)
        return shot

    def update(self, shot: Shot, **kwargs) -> Shot:
        """
        更新分镜

        Args:
            shot: 分镜对象
            **kwargs: 要更新的字段

        Returns:
            更新后的分镜对象
        """
        for key, value in kwargs.items():
            if hasattr(shot, key):
                # JSON 字段需要序列化
                if key in ('characters', 'props', 'dialogues', 'keyframes') and isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                setattr(shot, key, value)
        self.db.commit()
        self.db.refresh(shot)
        return shot

    def delete(self, shot: Shot) -> None:
        """
        删除分镜

        Args:
            shot: 分镜对象
        """
        self.db.delete(shot)
        self.db.commit()

    def delete_by_chapter(self, chapter_id: str) -> int:
        """
        删除章节的所有分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            删除的分镜数量
        """
        count = self.db.query(Shot).filter(Shot.chapter_id == chapter_id).count()
        self.db.query(Shot).filter(Shot.chapter_id == chapter_id).delete()
        self.db.commit()
        return count

    def bulk_create(self, shots_data: List[dict]) -> List[Shot]:
        """
        批量创建分镜

        Args:
            shots_data: 分镜数据列表，每个元素包含分镜字段

        Returns:
            创建的分镜对象列表
        """
        shots = []
        for data in shots_data:
            # 处理 JSON 字段
            for key in ('characters', 'props', 'dialogues'):
                if key in data and isinstance(data[key], (list, dict)):
                    data[key] = json.dumps(data[key], ensure_ascii=False)

            shot = Shot(**data)
            self.db.add(shot)
            shots.append(shot)

        self.db.commit()
        for shot in shots:
            self.db.refresh(shot)
        return shots

    def count_by_chapter(self, chapter_id: str) -> int:
        """
        统计章节的分镜数量

        Args:
            chapter_id: 章节 ID

        Returns:
            分镜数量
        """
        return self.db.query(Shot).filter(Shot.chapter_id == chapter_id).count()

    def get_pending_image_shots(self, chapter_id: str) -> List[Shot]:
        """
        获取章节中待生成图片的分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            待生成图片的分镜列表
        """
        return self.db.query(Shot).filter(
            Shot.chapter_id == chapter_id,
            Shot.image_status == "pending"
        ).order_by(Shot.index).all()

    def get_pending_video_shots(self, chapter_id: str) -> List[Shot]:
        """
        获取章节中待生成视频的分镜

        Args:
            chapter_id: 章节 ID

        Returns:
            待生成视频的分镜列表
        """
        return self.db.query(Shot).filter(
            Shot.chapter_id == chapter_id,
            Shot.video_status == "pending"
        ).order_by(Shot.index).all()

    def update_image_status(
        self,
        shot: Shot,
        status: str,
        image_url: str = None,
        image_path: str = None,
        task_id: str = None
    ) -> Shot:
        """
        更新分镜图片状态

        Args:
            shot: 分镜对象
            status: 状态 (pending/generating/completed/failed)
            image_url: 图片 URL
            image_path: 图片本地路径
            task_id: 任务 ID

        Returns:
            更新后的分镜对象
        """
        shot.image_status = status
        if image_url is not None:
            shot.image_url = image_url
        if image_path is not None:
            shot.image_path = image_path
        if task_id is not None:
            shot.image_task_id = task_id
        self.db.commit()
        self.db.refresh(shot)
        return shot

    def update_video_status(
        self,
        shot: Shot,
        status: str,
        video_url: str = None,
        task_id: str = None
    ) -> Shot:
        """
        更新分镜视频状态

        Args:
            shot: 分镜对象
            status: 状态 (pending/generating/completed/failed)
            video_url: 视频 URL
            task_id: 任务 ID

        Returns:
            更新后的分镜对象
        """
        shot.video_status = status
        if video_url is not None:
            shot.video_url = video_url
        if task_id is not None:
            shot.video_task_id = task_id
        self.db.commit()
        self.db.refresh(shot)
        return shot

    def update_dialogues(self, shot: Shot, dialogues: List[dict]) -> Shot:
        """
        更新分镜台词数据

        Args:
            shot: 分镜对象
            dialogues: 台词数据列表

        Returns:
            更新后的分镜对象
        """
        shot.dialogues = json.dumps(dialogues, ensure_ascii=False)
        self.db.commit()
        self.db.refresh(shot)
        return shot

    def to_response(self, shot: Shot) -> dict:
        """
        将分镜对象转换为响应字典

        Args:
            shot: 分镜对象

        Returns:
            响应字典
        """
        return {
            "id": shot.id,
            "chapterId": shot.chapter_id,
            "index": shot.index,
            "description": shot.description,
            "video_description": shot.video_description,
            "characters": json.loads(shot.characters) if shot.characters else [],
            "scene": shot.scene,
            "props": json.loads(shot.props) if shot.props else [],
            "duration": shot.duration,
            "imageUrl": shot.image_url,
            "imagePath": shot.image_path,
            "imageStatus": shot.image_status,
            "imageTaskId": shot.image_task_id,
            "videoUrl": shot.video_url,
            "videoStatus": shot.video_status,
            "videoTaskId": shot.video_task_id,
            "mergedCharacterImage": shot.merged_character_image,
            "dialogues": json.loads(shot.dialogues) if shot.dialogues else [],
            "keyframes": json.loads(shot.keyframes) if shot.keyframes else [],
            "referenceAudioUrl": shot.reference_audio_url,
            "referenceAudioType": shot.reference_audio_type or "none",
            "createdAt": shot.created_at.isoformat() if shot.created_at else None,
            "updatedAt": shot.updated_at.isoformat() if shot.updated_at else None,
        }