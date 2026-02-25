"""
小说数据仓库

封装小说相关的数据库查询逻辑
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, selectinload

from app.models.novel import Novel, Chapter


class NovelRepository:
    """小说数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_with_cover(self) -> List[Dict[str, Any]]:
        """
        获取小说列表，预加载关联数据避免 N+1 查询
        
        Returns:
            小说列表，包含封面信息
        """
        novels = self.db.query(Novel).order_by(Novel.created_at.desc()).all()
        
        if not novels:
            return []
        
        novel_ids = [n.id for n in novels]
        
        # 批量查询所有小说的第一章节
        first_chapters = {}
        chapters = self.db.query(Chapter).filter(
            Chapter.novel_id.in_(novel_ids)
        ).order_by(Chapter.novel_id, Chapter.number).all()
        
        for chapter in chapters:
            if chapter.novel_id not in first_chapters:
                first_chapters[chapter.novel_id] = chapter
        
        # 构建结果
        result = []
        for n in novels:
            cover = n.cover
            if not cover:
                first_chapter = first_chapters.get(n.id)
                if first_chapter and first_chapter.shot_images:
                    try:
                        import json
                        shot_images = json.loads(first_chapter.shot_images)
                        if isinstance(shot_images, list) and len(shot_images) > 0:
                            cover = shot_images[0]
                    except json.JSONDecodeError:
                        pass
            
            result.append({
                "id": n.id,
                "title": n.title,
                "author": n.author,
                "description": n.description,
                "cover": cover,
                "status": n.status,
                "chapterCount": n.chapter_count,
                "promptTemplateId": n.prompt_template_id,
                "chapterSplitPromptTemplateId": n.chapter_split_prompt_template_id,
                "aspectRatio": n.aspect_ratio if n.aspect_ratio and n.aspect_ratio.strip() else "16:9",
                "createdAt": n.created_at.isoformat() if n.created_at else None,
                "updatedAt": n.updated_at.isoformat() if n.updated_at else None,
            })
        
        return result
    
    def get_by_id(self, novel_id: str) -> Optional[Novel]:
        """根据 ID 获取小说"""
        return self.db.query(Novel).filter(Novel.id == novel_id).first()
    
    def get_with_chapters(self, novel_id: str) -> Optional[Novel]:
        """获取小说及其章节（预加载）"""
        return self.db.query(Novel).options(
            selectinload(Novel.chapters)
        ).filter(Novel.id == novel_id).first()
    
    def get_with_characters(self, novel_id: str) -> Optional[Novel]:
        """获取小说及其角色（预加载）"""
        return self.db.query(Novel).options(
            selectinload(Novel.characters)
        ).filter(Novel.id == novel_id).first()
    
    def get_with_scenes(self, novel_id: str) -> Optional[Novel]:
        """获取小说及其场景（预加载）"""
        return self.db.query(Novel).options(
            selectinload(Novel.scenes)
        ).filter(Novel.id == novel_id).first()
    
    def get_full(self, novel_id: str) -> Optional[Novel]:
        """获取小说及其所有关联数据（预加载）"""
        return self.db.query(Novel).options(
            selectinload(Novel.chapters),
            selectinload(Novel.characters),
            selectinload(Novel.scenes)
        ).filter(Novel.id == novel_id).first()
    
    def create(self, title: str, author: str = None, description: str = None,
               prompt_template_id: str = None, chapter_split_prompt_template_id: str = None,
               aspect_ratio: str = "16:9") -> Novel:
        """创建小说"""
        novel = Novel(
            title=title,
            author=author,
            description=description,
            prompt_template_id=prompt_template_id,
            chapter_split_prompt_template_id=chapter_split_prompt_template_id,
            aspect_ratio=aspect_ratio,
        )
        self.db.add(novel)
        self.db.commit()
        self.db.refresh(novel)
        return novel
    
    def update(self, novel: Novel, **kwargs) -> Novel:
        """更新小说"""
        for key, value in kwargs.items():
            if hasattr(novel, key):
                setattr(novel, key, value)
        self.db.commit()
        self.db.refresh(novel)
        return novel
    
    def delete(self, novel: Novel) -> None:
        """删除小说"""
        self.db.delete(novel)
        self.db.commit()
    
    def update_chapter_count(self, novel_id: str, count: int) -> None:
        """更新小说章节数"""
        novel = self.get_by_id(novel_id)
        if novel:
            novel.chapter_count = count
            self.db.commit()
    
    def to_response(self, novel: Novel) -> Dict[str, Any]:
        """
        将小说对象转换为响应字典
        
        Args:
            novel: 小说对象
            
        Returns:
            响应字典
        """
        return {
            "id": novel.id,
            "title": novel.title,
            "author": novel.author,
            "description": novel.description,
            "cover": novel.cover,
            "status": novel.status,
            "chapterCount": novel.chapter_count,
            "promptTemplateId": novel.prompt_template_id,
            "chapterSplitPromptTemplateId": novel.chapter_split_prompt_template_id,
            "aspectRatio": novel.aspect_ratio or "16:9",
            "createdAt": novel.created_at.isoformat() if novel.created_at else None,
            "updatedAt": novel.updated_at.isoformat() if novel.updated_at else None,
        }
