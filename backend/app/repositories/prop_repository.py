from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.novel import Prop
from app.constants.prop import PROP_EXISTENCE_REAL


class PropRepository:
    """道具数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_by_novel(self, novel_id: str) -> List[Prop]:
        """获取小说的所有道具"""
        return self.db.query(Prop).filter(
            Prop.novel_id == novel_id
        ).all()
    
    def get_by_id(self, prop_id: str) -> Optional[Prop]:
        """根据 ID 获取道具"""
        return self.db.query(Prop).filter(Prop.id == prop_id).first()
    
    def get_by_name(self, novel_id: str, name: str) -> Optional[Prop]:
        """根据名称获取道具"""
        return self.db.query(Prop).filter(
            and_(Prop.novel_id == novel_id, Prop.name == name)
        ).first()
    
    def get_names_by_novel(self, novel_id: str) -> List[str]:
        """获取小说所有道具名称（优化：只查询需要的列）"""
        results = self.db.query(Prop.name).filter(
            Prop.novel_id == novel_id
        ).all()
        return [r[0] for r in results]

    def get_visual_names_by_novel(self, novel_id: str) -> List[str]:
        results = self.db.query(Prop.name).filter(
            Prop.novel_id == novel_id,
            Prop.existence == PROP_EXISTENCE_REAL,
        ).all()
        return [row[0] for row in results]
    
    def get_dict_by_novel(self, novel_id: str) -> Dict[str, Prop]:
        """
        获取道具名称到道具对象的映射
        
        注意：此方法用于道具解析时快速查找已存在的道具，
        避免在循环中重复查询数据库。
        """
        props = self.list_by_novel(novel_id)
        return {p.name: p for p in props}
    
    def create(self, novel_id: str, name: str, description: str = "", 
               appearance: str = "", start_chapter: int = None, 
               end_chapter: int = None, source_range: str = None,
               existence: str = PROP_EXISTENCE_REAL) -> Prop:
        """创建道具"""
        prop = Prop(
            novel_id=novel_id,
            name=name,
            description=description,
            appearance=appearance,
            existence=existence,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            source_range=source_range,
        )
        self.db.add(prop)
        self.db.commit()
        self.db.refresh(prop)
        return prop
    
    def update(self, prop: Prop, **kwargs) -> Prop:
        """更新道具"""
        for key, value in kwargs.items():
            if hasattr(prop, key):
                setattr(prop, key, value)
        self.db.commit()
        self.db.refresh(prop)
        return prop
    
    def delete(self, prop: Prop) -> None:
        """删除道具"""
        self.db.delete(prop)
        self.db.commit()
    
    def update_image(self, prop: Prop, image_url: str) -> Prop:
        """更新道具图片URL"""
        prop.image_url = image_url
        prop.generating_status = "completed"
        self.db.commit()
        self.db.refresh(prop)
        return prop
    
    def list_all(self) -> List[Prop]:
        """获取所有道具（按创建时间倒序）"""
        return self.db.query(Prop).order_by(Prop.created_at.desc()).all()
    
    def delete_by_novel(self, novel_id: str) -> int:
        """删除小说的所有道具，返回删除数量"""
        count = self.db.query(Prop).filter(Prop.novel_id == novel_id).delete()
        self.db.commit()
        return count
