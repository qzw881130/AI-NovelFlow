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
