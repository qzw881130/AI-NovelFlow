"""
TestCase Repository 层

封装测试用例相关的数据库查询逻辑
"""
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.test_case import TestCase


class TestCaseRepository:
    """测试用例数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_all(self) -> List[TestCase]:
        """获取所有测试用例（按创建时间倒序）"""
        return self.db.query(TestCase).order_by(TestCase.created_at.desc()).all()
    
    def list_by_type(self, test_type: str) -> List[TestCase]:
        """按类型获取测试用例"""
        return self.db.query(TestCase).filter(
            TestCase.type == test_type
        ).order_by(TestCase.created_at.desc()).all()
    
    def list_presets(self) -> List[TestCase]:
        """获取所有预设测试用例"""
        return self.db.query(TestCase).filter(
            TestCase.is_preset == True
        ).order_by(TestCase.created_at.desc()).all()
    
    def list_by_filters(
        self, 
        test_type: Optional[str] = None, 
        is_preset: Optional[bool] = None
    ) -> List[TestCase]:
        """按筛选条件获取测试用例"""
        query = self.db.query(TestCase).order_by(TestCase.created_at.desc())
        
        if test_type:
            query = query.filter(TestCase.type == test_type)
        if is_preset is not None:
            query = query.filter(TestCase.is_preset == is_preset)
        
        return query.all()
    
    def get_by_id(self, test_case_id: str) -> Optional[TestCase]:
        """根据 ID 获取测试用例"""
        return self.db.query(TestCase).filter(TestCase.id == test_case_id).first()
    
    def get_by_novel_id(self, novel_id: str) -> Optional[TestCase]:
        """根据小说ID获取测试用例"""
        return self.db.query(TestCase).filter(TestCase.novel_id == novel_id).first()
    
    def get_preset_names(self) -> List[str]:
        """获取所有预设测试用例的名称"""
        results = self.db.query(TestCase.name).filter(
            TestCase.is_preset == True
        ).all()
        return [r[0] for r in results]
    
    def create(self, test_case: TestCase) -> TestCase:
        """创建测试用例"""
        self.db.add(test_case)
        self.db.commit()
        self.db.refresh(test_case)
        return test_case
    
    def update(self, test_case: TestCase) -> TestCase:
        """更新测试用例"""
        self.db.commit()
        self.db.refresh(test_case)
        return test_case
    
    def delete(self, test_case: TestCase) -> None:
        """删除测试用例"""
        self.db.delete(test_case)
        self.db.commit()
    
    def exists_by_id(self, test_case_id: str) -> bool:
        """检查测试用例是否存在"""
        return self.db.query(TestCase).filter(TestCase.id == test_case_id).first() is not None
