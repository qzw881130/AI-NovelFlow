"""
章节数据仓库

封装章节相关的数据库查询逻辑
"""
import json
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.novel import Chapter


class ChapterRepository:
    """章节数据仓库"""

    def __init__(self, db: Session):
        self.db = db

    def list_by_novel(self, novel_id: str) -> List[Chapter]:
        """获取小说的所有章节"""
        return self.db.query(Chapter).filter(
            Chapter.novel_id == novel_id
        ).order_by(Chapter.number).all()

    def get_by_id(self, chapter_id: str, novel_id: str = None) -> Optional[Chapter]:
        """根据 ID 获取章节"""
        query = self.db.query(Chapter).filter(Chapter.id == chapter_id)
        if novel_id:
            query = query.filter(Chapter.novel_id == novel_id)
        return query.first()

    def get_first_by_novel(self, novel_id: str) -> Optional[Chapter]:
        """获取小说的第一个章节"""
        return self.db.query(Chapter).filter(
            Chapter.novel_id == novel_id
        ).order_by(Chapter.number.asc()).first()

    def get_by_range(
        self,
        novel_id: str,
        start_chapter: int = None,
        end_chapter: int = None
    ) -> List[Chapter]:
        """获取指定章节范围的章节"""
        query = self.db.query(Chapter).filter(Chapter.novel_id == novel_id)

        if start_chapter is not None:
            query = query.filter(Chapter.number >= start_chapter)
        if end_chapter is not None:
            query = query.filter(Chapter.number <= end_chapter)

        return query.order_by(Chapter.number).all()

    def list_by_ids(self, novel_id: str, chapter_ids: List[str]) -> List[Chapter]:
        """根据 ID 列表获取章节"""
        return self.db.query(Chapter).filter(
            Chapter.novel_id == novel_id,
            Chapter.id.in_(chapter_ids)
        ).order_by(Chapter.number).all()

    def create(self, novel_id: str, number: int, title: str, content: str = "") -> Chapter:
        """创建章节"""
        chapter = Chapter(
            novel_id=novel_id,
            number=number,
            title=title,
            content=content,
        )
        self.db.add(chapter)
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def update(self, chapter: Chapter, **kwargs) -> Chapter:
        """更新章节"""
        for key, value in kwargs.items():
            if hasattr(chapter, key):
                setattr(chapter, key, value)
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def delete(self, chapter: Chapter) -> None:
        """删除章节"""
        self.db.delete(chapter)
        self.db.commit()

    def count_by_novel(self, novel_id: str) -> int:
        """统计小说的章节数"""
        return self.db.query(Chapter).filter(
            Chapter.novel_id == novel_id
        ).count()

    def to_response(self, chapter: Chapter) -> dict:
        """
        将章节对象转换为响应字典（基础信息）

        Args:
            chapter: 章节对象

        Returns:
            响应字典
        """
        return {
            "id": chapter.id,
            "number": chapter.number,
            "title": chapter.title,
            "status": chapter.status,
            "progress": chapter.progress,
            "createdAt": chapter.created_at.isoformat() if chapter.created_at else None,
        }

    def to_detail_response(self, chapter: Chapter, include_shots: bool = True) -> dict:
        """
        将章节对象转换为详细响应字典

        Args:
            chapter: 章节对象
            include_shots: 是否包含分镜数据（从 Shot 表查询）

        Returns:
            响应字典
        """
        character_images = json.loads(chapter.character_images) if chapter.character_images else []
        shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
        shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []

        # 从 parsed_data 获取 transition_videos（已迁移到 parsed_data 中）
        parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {}
        transition_videos = parsed_data.get("transition_videos", {})

        response = {
            "id": chapter.id,
            "number": chapter.number,
            "title": chapter.title,
            "content": chapter.content,
            "status": chapter.status,
            "progress": chapter.progress,
            "parsedData": chapter.parsed_data,
            "characterImages": character_images,
            "shotImages": shot_images,
            "shotVideos": shot_videos,
            "transitionVideos": transition_videos,
            "finalVideo": chapter.final_video,
            "createdAt": chapter.created_at.isoformat() if chapter.created_at else None,
        }

        # 从 Shot 表获取分镜数据
        if include_shots:
            from app.repositories.shot_repository import ShotRepository
            shot_repo = ShotRepository(self.db)
            shots = shot_repo.get_by_chapter(chapter.id)
            response["shots"] = [shot_repo.to_response(s) for s in shots]

        return response

    def update_parsed_data(self, chapter: Chapter, parsed_data: dict) -> None:
        """更新章节的解析数据"""
        chapter.parsed_data = json.dumps(parsed_data, ensure_ascii=False)
        self.db.commit()

    def update_shot_image(self, chapter: Chapter, shot_index: int, image_url: str, image_path: str = None) -> None:
        """
        更新章节的分镜图片

        Args:
            chapter: 章节对象
            shot_index: 分镜索引 (1-based)
            image_url: 图片 URL
            image_path: 图片本地路径
        """
        # 更新 shot_images 数组
        shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
        if not isinstance(shot_images, list):
            shot_images = []
        while len(shot_images) < shot_index:
            shot_images.append(None)
        shot_images[shot_index - 1] = image_url
        chapter.shot_images = json.dumps(shot_images, ensure_ascii=False)

        # 更新 parsed_data
        if chapter.parsed_data:
            parsed_data = json.loads(chapter.parsed_data) if isinstance(chapter.parsed_data, str) else chapter.parsed_data
            if "shots" in parsed_data and len(parsed_data["shots"]) >= shot_index:
                parsed_data["shots"][shot_index - 1]["image_url"] = image_url
                if image_path:
                    parsed_data["shots"][shot_index - 1]["image_path"] = image_path
                chapter.parsed_data = json.dumps(parsed_data, ensure_ascii=False)

        self.db.commit()

    def clear_resources(self, chapter: Chapter) -> None:
        """清除章节的所有生成资源"""
        chapter.parsed_data = None
        chapter.shot_images = None
        chapter.shot_videos = None
        chapter.transition_videos = None
        chapter.merged_image = None
        self.db.commit()

    def bulk_upsert(self, novel_id: str, chapters_data: list[dict]) -> dict:
        """
        批量 upsert 章节。按 number 匹配已有章节，存在则更新 title+content，不存在则新建。

        Args:
            novel_id: 小说 ID
            chapters_data: 章节数据列表，每项包含 number, title, content

        Returns:
            {created: int, updated: int, failed: int, errors: list, chapters: list}
        """
        # 1. 获取已有章节号 -> 章节映射
        existing = self.db.query(Chapter).filter(
            Chapter.novel_id == novel_id
        ).all()
        existing_by_number = {c.number: c for c in existing}

        # 2. 检测传入数据中的重复 chapter number
        seen_numbers: set[int] = set()
        created = 0
        updated = 0
        failed = 0
        errors: list[dict] = []
        result_chapters: list[dict] = []

        for ch in chapters_data:
            num = ch['number']
            if num in seen_numbers:
                failed += 1
                errors.append({
                    'number': num,
                    'title': ch['title'],
                    'reason': f'章节号 {num} 重复',
                })
                continue
            seen_numbers.add(num)

            try:
                if num in existing_by_number:
                    # 更新已有章节（仅更新 title 和 content，保留其他资源）
                    existing_ch = existing_by_number[num]
                    existing_ch.title = ch['title']
                    existing_ch.content = ch['content']
                    updated += 1
                    result_chapters.append(self.to_response(existing_ch))
                else:
                    # 新建章节
                    new_ch = Chapter(
                        novel_id=novel_id,
                        number=num,
                        title=ch['title'],
                        content=ch['content'],
                    )
                    self.db.add(new_ch)
                    created += 1
            except Exception as e:
                failed += 1
                errors.append({
                    'number': num,
                    'title': ch['title'],
                    'reason': str(e),
                })

        # 3. 批量提交
        if created > 0 or updated > 0:
            self.db.commit()
            # refresh 新建的章节以获取 ID
            for ch in chapters_data:
                if ch['number'] not in existing_by_number and ch['number'] in seen_numbers:
                    new_ch = self.db.query(Chapter).filter(
                        Chapter.novel_id == novel_id,
                        Chapter.number == ch['number']
                    ).first()
                    if new_ch:
                        result_chapters.append(self.to_response(new_ch))

            # 更新 novel.chapter_count
            from app.models.novel import Novel
            novel = self.db.query(Novel).filter(Novel.id == novel_id).first()
            if novel:
                novel.chapter_count = self.count_by_novel(novel_id)
                self.db.commit()

        return {
            'created': created,
            'updated': updated,
            'failed': failed,
            'errors': errors,
            'chapters': result_chapters,
        }