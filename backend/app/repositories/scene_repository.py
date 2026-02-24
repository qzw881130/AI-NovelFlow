"""
场景数据仓库

封装场景相关的数据库查询逻辑
"""
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.novel import Scene


class SceneRepository:
    """场景数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_by_novel(self, novel_id: str) -> List[Scene]:
        """获取小说的所有场景"""
        return self.db.query(Scene).filter(
            Scene.novel_id == novel_id
        ).all()
    
    def get_by_id(self, scene_id: str) -> Optional[Scene]:
        """根据 ID 获取场景"""
        return self.db.query(Scene).filter(Scene.id == scene_id).first()
    
    def get_by_name(self, novel_id: str, name: str) -> Optional[Scene]:
        """根据名称获取场景"""
        return self.db.query(Scene).filter(
            and_(Scene.novel_id == novel_id, Scene.name == name)
        ).first()
    
    def get_names_by_novel(self, novel_id: str) -> List[str]:
        """获取小说所有场景名称（优化：只查询需要的列）"""
        results = self.db.query(Scene.name).filter(
            Scene.novel_id == novel_id
        ).all()
        return [r[0] for r in results]
    
    def get_dict_by_novel(self, novel_id: str) -> Dict[str, Scene]:
        """
        获取场景名称到场景对象的映射
        
        注意：此方法用于场景解析时快速查找已存在的场景，
        避免在循环中重复查询数据库。
        """
        scenes = self.list_by_novel(novel_id)
        return {s.name: s for s in scenes}
    
    def create(self, novel_id: str, name: str, description: str = "", 
               setting: str = "", start_chapter: int = None, 
               end_chapter: int = None, source_range: str = None) -> Scene:
        """创建场景"""
        scene = Scene(
            novel_id=novel_id,
            name=name,
            description=description,
            setting=setting,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            source_range=source_range,
        )
        self.db.add(scene)
        self.db.commit()
        self.db.refresh(scene)
        return scene
    
    def update(self, scene: Scene, **kwargs) -> Scene:
        """更新场景"""
        for key, value in kwargs.items():
            if hasattr(scene, key):
                setattr(scene, key, value)
        self.db.commit()
        self.db.refresh(scene)
        return scene
    
    def delete(self, scene: Scene) -> None:
        """删除场景"""
        self.db.delete(scene)
        self.db.commit()
