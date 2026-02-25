"""
章节数据仓库

封装章节相关的数据库查询逻辑
"""
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
    
    def to_detail_response(self, chapter: Chapter) -> dict:
        """
        将章节对象转换为详细响应字典
        
        Args:
            chapter: 章节对象
            
        Returns:
            响应字典
        """
        import json
        
        character_images = json.loads(chapter.character_images) if chapter.character_images else []
        shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
        shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
        transition_videos = json.loads(chapter.transition_videos) if chapter.transition_videos else {}
        
        return {
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
    
    def update_parsed_data(self, chapter: Chapter, parsed_data: dict) -> None:
        """更新章节的解析数据"""
        import json
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
        import json
        
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
