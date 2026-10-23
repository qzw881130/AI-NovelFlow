"""
PromptTemplate Repository 层

封装提示词模板相关的数据库查询逻辑
"""
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.prompt_template import PromptTemplate
from app.constants.prompt_template import TRANSITION_V2_NAME


class PromptTemplateRepository:
    """提示词模板数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_all(self) -> List[PromptTemplate]:
        """获取所有模板（系统优先，按创建时间倒序）"""
        return self.db.query(PromptTemplate).order_by(
            PromptTemplate.is_system.desc(),
            PromptTemplate.created_at.desc()
        ).all()
    
    def list_by_type(self, template_type: str) -> List[PromptTemplate]:
        """按类型获取模板列表"""
        return self.db.query(PromptTemplate).filter(
            PromptTemplate.type == template_type
        ).order_by(
            PromptTemplate.is_system.desc(),
            PromptTemplate.created_at.desc()
        ).all()
    
    def get_by_id(self, template_id: str) -> Optional[PromptTemplate]:
        """根据 ID 获取模板"""
        return self.db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    
    def get_by_name_and_type(self, name: str, template_type: str, is_system: bool = True) -> Optional[PromptTemplate]:
        """根据名称和类型获取模板"""
        return self.db.query(PromptTemplate).filter(
            PromptTemplate.name == name,
            PromptTemplate.type == template_type,
            PromptTemplate.is_system == is_system
        ).first()
    
    def get_default_system_template(self, template_type: str = "character") -> Optional[PromptTemplate]:
        """获取同类型、已启用的系统模板；相同创建时间按 ID 稳定排序。"""
        if template_type == "keyframe_transition":
            preferred = self.get_by_name_and_type(TRANSITION_V2_NAME, template_type)
            if preferred and preferred.is_active:
                return preferred
        return self.db.query(PromptTemplate).filter(
            PromptTemplate.is_system == True,
            PromptTemplate.type == template_type,
            PromptTemplate.is_active == True,
        ).order_by(PromptTemplate.created_at.asc(), PromptTemplate.id.asc()).first()

    def resolve_for_type(self, selected_id: Optional[str], template_type: str) -> Optional[PromptTemplate]:
        """小说选择优先；失效选择仅回退到同类型的启用系统模板。"""
        selected = self.get_by_id(selected_id) if selected_id else None
        if selected and selected.type == template_type and selected.is_active:
            return selected
        return self.get_default_system_template(template_type)
    
    def create(self, template: PromptTemplate) -> PromptTemplate:
        """创建模板"""
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)
        return template
    
    def update(self, template: PromptTemplate) -> PromptTemplate:
        """更新模板"""
        self.db.commit()
        self.db.refresh(template)
        return template
    
    def delete(self, template: PromptTemplate) -> None:
        """删除模板"""
        self.db.delete(template)
        self.db.commit()
    
    def exists_by_name_and_type(self, name: str, template_type: str, is_system: bool = True) -> bool:
        """检查模板是否存在"""
        return self.db.query(PromptTemplate).filter(
            PromptTemplate.name == name,
            PromptTemplate.type == template_type,
            PromptTemplate.is_system == is_system
        ).first() is not None
