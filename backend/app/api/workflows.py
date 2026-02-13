import json
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.config import get_settings
from app.models.workflow import Workflow

router = APIRouter()
settings = get_settings()

# 工作流类型定义
WORKFLOW_TYPES = {
    "character": "人设生成",
    "shot": "分镜生图", 
    "video": "分镜生视频"
}

# 默认工作流文件名映射
DEFAULT_WORKFLOWS = {
    "character": "character_default.json",
    "shot": "shot_default.json",
    "video": "video_default.json"
}


def get_workflows_dir():
    """获取系统工作流文件目录"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workflows")


def get_user_workflows_dir():
    """获取用户工作流文件目录"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "user_workflows")


def load_default_workflows(db: Session):
    """加载默认工作流到数据库"""
    workflows_dir = get_workflows_dir()
    
    for wf_type, filename in DEFAULT_WORKFLOWS.items():
        file_path = os.path.join(workflows_dir, filename)
        
        # 检查是否已存在系统工作流
        existing = db.query(Workflow).filter(
            Workflow.type == wf_type,
            Workflow.is_system == True
        ).first()
        
        if existing:
            continue
        
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                workflow_json = f.read()
            
            # 解析工作流名称
            try:
                workflow_data = json.loads(workflow_json)
                name = f"系统默认-{WORKFLOW_TYPES.get(wf_type, wf_type)}"
            except:
                name = f"默认工作流-{wf_type}"
            
            workflow = Workflow(
                name=name,
                description=f"系统预设的{WORKFLOW_TYPES.get(wf_type, wf_type)}工作流",
                type=wf_type,
                workflow_json=workflow_json,
                is_system=True,
                is_active=True,
                file_path=file_path
            )
            db.add(workflow)
    
    db.commit()


@router.get("/", response_model=dict)
async def list_workflows(
    type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取工作流列表"""
    # 确保默认工作流已加载
    load_default_workflows(db)
    
    query = db.query(Workflow).order_by(Workflow.is_system.desc(), Workflow.created_at.desc())
    
    if type:
        query = query.filter(Workflow.type == type)
    
    workflows = query.all()
    
    return {
        "success": True,
        "data": [
            {
                "id": w.id,
                "name": w.name,
                "description": w.description,
                "type": w.type,
                "typeName": WORKFLOW_TYPES.get(w.type, w.type),
                "isSystem": w.is_system,
                "isActive": w.is_active,
                "createdAt": w.created_at.isoformat() if w.created_at else None,
            }
            for w in workflows
        ]
    }


@router.get("/{workflow_id}/", response_model=dict)
async def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """获取工作流详情"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    return {
        "success": True,
        "data": {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "type": workflow.type,
            "typeName": WORKFLOW_TYPES.get(workflow.type, workflow.type),
            "workflowJson": workflow.workflow_json,
            "isSystem": workflow.is_system,
            "isActive": workflow.is_active,
            "createdAt": workflow.created_at.isoformat() if workflow.created_at else None,
        }
    }


@router.post("/upload/", response_model=dict)
async def upload_workflow(
    name: str = Form(...),
    type: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """上传自定义工作流"""
    if type not in WORKFLOW_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的工作流类型，可选: {list(WORKFLOW_TYPES.keys())}")
    
    # 读取文件内容
    content = await file.read()
    try:
        # 验证JSON格式
        workflow_data = json.loads(content)
        workflow_json = json.dumps(workflow_data, ensure_ascii=False, indent=2)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"无效的JSON文件: {str(e)}")
    
    # 确保用户工作流目录存在
    user_workflows_dir = get_user_workflows_dir()
    os.makedirs(user_workflows_dir, exist_ok=True)
    
    # 保存文件到用户工作流目录
    safe_name = "".join(c for c in name if c.isalnum() or c in ('-', '_')).strip()
    filename = f"{safe_name}_{type}.json"
    file_path = os.path.join(user_workflows_dir, filename)
    
    # 如果文件已存在，添加数字后缀
    counter = 1
    original_file_path = file_path
    while os.path.exists(file_path):
        filename = f"{safe_name}_{type}_{counter}.json"
        file_path = os.path.join(user_workflows_dir, filename)
        counter += 1
    
    # 写入文件
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(workflow_json)
    
    # 创建工作流记录
    workflow = Workflow(
        name=name,
        description=description or f"用户上传的{WORKFLOW_TYPES.get(type, type)}工作流",
        type=type,
        workflow_json=workflow_json,
        is_system=False,
        is_active=False,  # 上传后不是默认，需要手动设置
        created_by="user",
        file_path=file_path
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    
    return {
        "success": True,
        "message": "工作流上传成功",
        "data": {
            "id": workflow.id,
            "name": workflow.name,
            "type": workflow.type,
            "filePath": file_path
        }
    }


@router.put("/{workflow_id}/", response_model=dict)
async def update_workflow(
    workflow_id: str,
    data: dict,
    db: Session = Depends(get_db)
):
    """更新工作流信息"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    # 系统工作流只能修改名称和描述
    if workflow.is_system:
        if "name" in data:
            workflow.name = data["name"]
        if "description" in data:
            workflow.description = data["description"]
        if "isActive" in data:
            workflow.is_active = data["isActive"]
    else:
        # 用户工作流可以修改更多
        if "name" in data:
            workflow.name = data["name"]
        if "description" in data:
            workflow.description = data["description"]
        if "isActive" in data:
            workflow.is_active = data["isActive"]
        if "workflowJson" in data:
            # 验证JSON
            try:
                workflow_data = json.loads(data["workflowJson"])
                workflow.workflow_json = data["workflowJson"]
                
                # 同时更新文件
                if workflow.file_path and os.path.exists(workflow.file_path):
                    with open(workflow.file_path, 'w', encoding='utf-8') as f:
                        json.dump(workflow_data, f, ensure_ascii=False, indent=2)
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"无效的JSON内容: {str(e)}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"保存文件失败: {str(e)}")
    
    db.commit()
    db.refresh(workflow)
    
    return {
        "success": True,
        "data": {
            "id": workflow.id,
            "name": workflow.name,
            "isActive": workflow.is_active,
        }
    }


@router.delete("/{workflow_id}/")
async def delete_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """删除工作流"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    # 不能删除系统工作流
    if workflow.is_system:
        raise HTTPException(status_code=403, detail="系统预设工作流不能删除")
    
    db.delete(workflow)
    db.commit()
    
    return {"success": True, "message": "删除成功"}


@router.post("/{workflow_id}/set-default/")
async def set_default_workflow(
    workflow_id: str,
    db: Session = Depends(get_db)
):
    """设置默认工作流（将该类型的工作流设为激活状态，其他同类型的设为非激活）"""
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    # 将该类型的所有工作流设为非激活
    db.query(Workflow).filter(
        Workflow.type == workflow.type
    ).update({"is_active": False})
    
    # 将当前工作流设为激活
    workflow.is_active = True
    db.commit()
    
    return {
        "success": True,
        "message": f"已设为默认{WORKFLOW_TYPES.get(workflow.type, workflow.type)}工作流"
    }


@router.get("/active/{workflow_type}", response_model=dict)
async def get_active_workflow(workflow_type: str, db: Session = Depends(get_db)):
    """获取当前激活的工作流"""
    # 确保默认工作流已加载
    load_default_workflows(db)
    
    workflow = db.query(Workflow).filter(
        Workflow.type == workflow_type,
        Workflow.is_active == True
    ).first()
    
    if not workflow:
        # 如果没有激活的，返回该类型的第一个系统工作流
        workflow = db.query(Workflow).filter(
            Workflow.type == workflow_type,
            Workflow.is_system == True
        ).first()
    
    if not workflow:
        raise HTTPException(status_code=404, detail=f"没有找到{WORKFLOW_TYPES.get(workflow_type, workflow_type)}工作流")
    
    return {
        "success": True,
        "data": {
            "id": workflow.id,
            "name": workflow.name,
            "type": workflow.type,
            "workflowJson": workflow.workflow_json,
            "isSystem": workflow.is_system,
        }
    }
