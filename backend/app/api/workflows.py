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
    "scene": "场景生成", 
    "shot": "分镜生图", 
    "video": "分镜生视频",
    "transition": "分镜生转场视频"
}

# 默认工作流文件名映射 (每个类型的默认工作流)
DEFAULT_WORKFLOWS = {
    "character": "character_default.json",
    "scene": "scene_default.json",
    "shot": "shot_default.json",
    "video": "video_default.json"
}

# 额外的系统工作流文件列表
# 注意：列表顺序决定默认激活优先级，每种类型的第一个工作流会成为默认激活
EXTRA_SYSTEM_WORKFLOWS = [
    {"filename": "character_single.json", "type": "character", "name": "Z-image-turbo 单图生成", "description": "Z-image-turbo【非三视图】"},
    # 双图参考工作流（角色图+场景图）作为分镜生图的默认工作流
    {"filename": "shot_flux2_klein_dual_reference.json", "type": "shot", "name": "Flux2-Klein-9B 分镜生图双图参考", "description": "Flux2-Klein-9B 双图参考工作流，支持角色参考图+场景参考图，保持场景一致性",
     "node_mapping": {"prompt_node_id": "110", "save_image_node_id": "9", "width_node_id": "123", "height_node_id": "125", "character_reference_image_node_id": "76", "scene_reference_image_node_id": "128"}},
    {"filename": "shot_flux2_klein.json", "type": "shot", "name": "Flux2-Klein-9B 分镜生图", "description": "Flux2-Klein-9B 图像编辑工作流，仅支持角色参考图"},
    {"filename": "video_ltx2_direct.json", "type": "video", "name": "LTX2 视频生成-直接版", "description": "LTX-2 图生视频，直接使用用户提示词",
     "node_mapping": {"prompt_node_id": "11", "video_save_node_id": "1", "reference_image_node_id": "12", "max_side_node_id": "36", "frame_count_node_id": "35"}},
    {"filename": "video_ltx2_expanded.json", "type": "video", "name": "LTX2 视频生成-扩写版", "description": "LTX-2 图生视频，使用 Qwen3 自动扩写提示词",
     "node_mapping": {"prompt_node_id": "15", "video_save_node_id": "1", "reference_image_node_id": "12", "max_side_node_id": "36", "frame_count_node_id": "35"}},
    {"filename": "transition_ltx2_camera.json", "type": "transition", "name": "LTX2 镜头转场视频", "description": "适合：首尾帧是同一场景不同景别/角度",
     "node_mapping": {"first_image_node_id": "98", "last_image_node_id": "106", "frame_count_node_id": "174", "video_save_node_id": "105"}},
    {"filename": "transition_ltx2_lighting.json", "type": "transition", "name": "LTX2 光线转场视频", "description": "适合：首尾帧颜色差很多，但场景/人物不变",
     "node_mapping": {"first_image_node_id": "98", "last_image_node_id": "106", "frame_count_node_id": "174", "video_save_node_id": "105"}},
    {"filename": "transition_ltx2_first_last_frame.json", "type": "transition", "name": "LTX2 遮挡转场视频", "description": "适合：两张图差异大，想自然衔接",
     "node_mapping": {"first_image_node_id": "98", "last_image_node_id": "106", "frame_count_node_id": "174", "video_save_node_id": "105"}},
    {"filename": "scene_default.json", "type": "scene", "name": "Z-image-turbo 场景生成", "description": "Z-image-turbo 场景生成工作流",
     "node_mapping": {"prompt_node_id": "133", "save_image_node_id": "9"}}
]


def get_workflows_dir():
    """获取系统工作流文件目录"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workflows")


def get_user_workflows_dir():
    """获取用户工作流文件目录"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "user_workflows")


def load_default_workflows(db: Session):
    """加载默认工作流到数据库"""
    workflows_dir = get_workflows_dir()
    
    # 1. 加载默认工作流
    for wf_type, filename in DEFAULT_WORKFLOWS.items():
        file_path = os.path.join(workflows_dir, filename)
        
        # 检查是否已存在同名系统工作流
        existing = db.query(Workflow).filter(
            Workflow.file_path == file_path,
            Workflow.is_system == True
        ).first()
        
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                workflow_json = f.read()
            
            # 如果已存在，检查内容是否有变化，有则更新
            if existing:
                if existing.workflow_json != workflow_json:
                    existing.workflow_json = workflow_json
                    db.commit()
                    print(f"[Workflow] Updated default workflow: {wf_type}")
                continue
            
            # 根据类型设置描述
            description = f"系统预设的{WORKFLOW_TYPES.get(wf_type, wf_type)}工作流"
            
            workflow = Workflow(
                name=f"系统默认-{WORKFLOW_TYPES.get(wf_type, wf_type)}",
                description=description,
                type=wf_type,
                workflow_json=workflow_json,
                is_system=True,
                is_active=True,
                file_path=file_path
            )
            db.add(workflow)
    
    # 2. 加载额外的系统工作流
    # 跟踪每种类型已经处理过的工作流，确保同类型只有第一个是默认激活的
    processed_types = {}  # type -> count
    
    for wf_config in EXTRA_SYSTEM_WORKFLOWS:
        file_path = os.path.join(workflows_dir, wf_config["filename"])
        wf_type = wf_config["type"]
        
        if not os.path.exists(file_path):
            continue
            
        with open(file_path, 'r', encoding='utf-8') as f:
            workflow_json = f.read()
        
        # 检查是否已存在
        existing = db.query(Workflow).filter(
            Workflow.file_path == file_path,
            Workflow.is_system == True
        ).first()
        
        if existing:
            # 检查内容是否有变化，有则更新
            if existing.workflow_json != workflow_json:
                existing.workflow_json = workflow_json
                existing.name = wf_config["name"]
                existing.description = wf_config["description"]
                print(f"[Workflow] Updated: {wf_config['name']}")
            # 更新节点映射（如果配置中有且未设置）
            if "node_mapping" in wf_config:
                current_mapping = None
                if existing.node_mapping:
                    try:
                        current_mapping = json.loads(existing.node_mapping)
                    except:
                        pass
                if not current_mapping:
                    existing.node_mapping = json.dumps(wf_config["node_mapping"], ensure_ascii=False)
                    print(f"[Workflow] Updated node mapping: {wf_config['name']}")
            continue
        
        # 检查该类型是否已有激活的工作流（数据库中）
        has_active_in_db = db.query(Workflow).filter(
            Workflow.type == wf_type,
            Workflow.is_active == True
        ).first() is not None
        
        # 检查该类型在本次加载中是否已设置了默认工作流
        processed_count = processed_types.get(wf_type, 0)
        is_first_in_list = processed_count == 0
        
        # 只有当数据库中没有激活的，且是列表中第一个时，才设为激活
        should_be_active = (not has_active_in_db) and is_first_in_list
        
        processed_types[wf_type] = processed_count + 1
        
        workflow = Workflow(
            name=wf_config["name"],
            description=wf_config["description"],
            type=wf_type,
            workflow_json=workflow_json,
            is_system=True,
            is_active=should_be_active,
            file_path=file_path
        )
        # 设置默认节点映射（如果配置中有）
        if "node_mapping" in wf_config:
            workflow.node_mapping = json.dumps(wf_config["node_mapping"], ensure_ascii=False)
            print(f"[Workflow] Added: {wf_config['name']} with node mapping (active={should_be_active})")
        else:
            print(f"[Workflow] Added: {wf_config['name']} (active={should_be_active})")
        db.add(workflow)
    
    db.commit()
    
    # 3. 确保每种类型只有一个默认激活的工作流
    for wf_type in WORKFLOW_TYPES.keys():
        # 获取该类型所有激活的工作流，按创建时间排序
        active_workflows = db.query(Workflow).filter(
            Workflow.type == wf_type,
            Workflow.is_active == True
        ).order_by(Workflow.created_at.asc()).all()
        
        if len(active_workflows) > 1:
            # 有多个激活的，只保留第一个，其余取消激活
            for wf in active_workflows[1:]:
                wf.is_active = False
                print(f"[Workflow] Deactivated duplicate default: {wf.name}")
            db.commit()
        elif not active_workflows:
            # 没有激活的，找到该类型的第一个系统工作流设为默认
            first_workflow = db.query(Workflow).filter(
                Workflow.type == wf_type,
                Workflow.is_system == True
            ).order_by(Workflow.created_at.asc()).first()
            
            if first_workflow:
                first_workflow.is_active = True
                print(f"[Workflow] Set default for {wf_type}: {first_workflow.name}")
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
    
    # 系统工作流名称到翻译键的映射
    WORKFLOW_NAME_KEYS = {
        "系统默认-人设生成": "tasks.workflowNames.系统默认-人设生成",
        "系统默认-场景生成": "tasks.workflowNames.系统默认-场景生成",
        "Z-image-turbo 单图生成": "tasks.workflowNames.Z-image-turbo 单图生成",
        "Flux2-Klein-9B 分镜生图": "tasks.workflowNames.Flux2-Klein-9B 分镜生图",
        "LTX2 视频生成-直接版": "tasks.workflowNames.LTX2 视频生成-直接版",
        "LTX2 视频生成-扩写版": "tasks.workflowNames.LTX2 视频生成-扩写版",
        "LTX2 镜头转场视频": "tasks.workflowNames.LTX2 镜头转场视频",
        "LTX2 光线转场视频": "tasks.workflowNames.LTX2 光线转场视频",
        "LTX2 遮挡转场视频": "tasks.workflowNames.LTX2 遮挡转场视频",
    }
    # 系统工作流描述到翻译键的映射
    WORKFLOW_DESC_KEYS = {
        "系统预设的人设生成工作流（Flux2 Klein 9B 三视图）": "tasks.workflowDescriptions.系统预设的人设生成工作流（Flux2 Klein 9B 三视图）",
        "系统预设的场景生成工作流": "tasks.workflowDescriptions.系统预设的场景生成工作流",
        "Z-image-turbo【非三视图】": "tasks.workflowDescriptions.Z-image-turbo【非三视图】",
        "Flux2-Klein-9B 图像编辑工作流，支持角色参考图": "tasks.workflowDescriptions.Flux2-Klein-9B 图像编辑工作流，支持角色参考图",
        "LTX-2 图生视频，直接使用用户提示词": "tasks.workflowDescriptions.LTX-2 图生视频，直接使用用户提示词",
        "LTX-2 图生视频，使用 Qwen3 自动扩写提示词": "tasks.workflowDescriptions.LTX-2 图生视频，使用 Qwen3 自动扩写提示词",
        "适合：首尾帧是同一场景不同景别/角度": "tasks.workflowDescriptions.适合：首尾帧是同一场景不同景别/角度",
        "适合：首尾帧颜色差很多，但场景/人物不变": "tasks.workflowDescriptions.适合：首尾帧颜色差很多，但场景/人物不变",
        "适合：两张图差异大，想自然衔接": "tasks.workflowDescriptions.适合：两张图差异大，想自然衔接",
    }
    
    return {
        "success": True,
        "data": [
            {
                "id": w.id,
                "name": w.name,
                "nameKey": WORKFLOW_NAME_KEYS.get(w.name) if w.is_system else None,
                "description": w.description,
                "descriptionKey": WORKFLOW_DESC_KEYS.get(w.description) if w.is_system and w.description else None,
                "type": w.type,
                "typeName": WORKFLOW_TYPES.get(w.type, w.type),
                "isSystem": w.is_system,
                "isActive": w.is_active,
                "nodeMapping": json.loads(w.node_mapping) if w.node_mapping else None,
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
    
    # 系统工作流名称到翻译键的映射
    WORKFLOW_NAME_KEYS = {
        "系统默认-人设生成": "tasks.workflowNames.系统默认-人设生成",
        "系统默认-场景生成": "tasks.workflowNames.系统默认-场景生成",
        "Z-image-turbo 单图生成": "tasks.workflowNames.Z-image-turbo 单图生成",
        "Flux2-Klein-9B 分镜生图": "tasks.workflowNames.Flux2-Klein-9B 分镜生图",
        "LTX2 视频生成-直接版": "tasks.workflowNames.LTX2 视频生成-直接版",
        "LTX2 视频生成-扩写版": "tasks.workflowNames.LTX2 视频生成-扩写版",
        "LTX2 镜头转场视频": "tasks.workflowNames.LTX2 镜头转场视频",
        "LTX2 光线转场视频": "tasks.workflowNames.LTX2 光线转场视频",
        "LTX2 遮挡转场视频": "tasks.workflowNames.LTX2 遮挡转场视频",
    }
    # 系统工作流描述到翻译键的映射
    WORKFLOW_DESC_KEYS = {
        "系统预设的人设生成工作流（Flux2 Klein 9B 三视图）": "tasks.workflowDescriptions.系统预设的人设生成工作流（Flux2 Klein 9B 三视图）",
        "系统预设的场景生成工作流": "tasks.workflowDescriptions.系统预设的场景生成工作流",
        "Z-image-turbo【非三视图】": "tasks.workflowDescriptions.Z-image-turbo【非三视图】",
        "Flux2-Klein-9B 图像编辑工作流，支持角色参考图": "tasks.workflowDescriptions.Flux2-Klein-9B 图像编辑工作流，支持角色参考图",
        "LTX-2 图生视频，直接使用用户提示词": "tasks.workflowDescriptions.LTX-2 图生视频，直接使用用户提示词",
        "LTX-2 图生视频，使用 Qwen3 自动扩写提示词": "tasks.workflowDescriptions.LTX-2 图生视频，使用 Qwen3 自动扩写提示词",
        "适合：首尾帧是同一场景不同景别/角度": "tasks.workflowDescriptions.适合：首尾帧是同一场景不同景别/角度",
        "适合：首尾帧颜色差很多，但场景/人物不变": "tasks.workflowDescriptions.适合：首尾帧颜色差很多，但场景/人物不变",
        "适合：两张图差异大，想自然衔接": "tasks.workflowDescriptions.适合：两张图差异大，想自然衔接",
    }
    
    return {
        "success": True,
        "data": {
            "id": workflow.id,
            "name": workflow.name,
            "nameKey": WORKFLOW_NAME_KEYS.get(workflow.name) if workflow.is_system else None,
            "description": workflow.description,
            "descriptionKey": WORKFLOW_DESC_KEYS.get(workflow.description) if workflow.is_system and workflow.description else None,
            "type": workflow.type,
            "typeName": WORKFLOW_TYPES.get(workflow.type, workflow.type),
            "workflowJson": workflow.workflow_json,
            "isSystem": workflow.is_system,
            "isActive": workflow.is_active,
            "nodeMapping": json.loads(workflow.node_mapping) if workflow.node_mapping else None,
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
    
    # 系统工作流可以修改：名称、描述、激活状态、节点映射
    if workflow.is_system:
        if "name" in data:
            workflow.name = data["name"]
        if "description" in data:
            workflow.description = data["description"]
        if "isActive" in data:
            workflow.is_active = data["isActive"]
        # 系统工作流也支持节点映射配置
        if "nodeMapping" in data:
            try:
                if data["nodeMapping"] is None:
                    workflow.node_mapping = None
                else:
                    mapping = data["nodeMapping"]
                    if not isinstance(mapping, dict):
                        raise ValueError("nodeMapping 必须是对象")
                    workflow.node_mapping = json.dumps(mapping, ensure_ascii=False)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"无效的节点映射配置: {str(e)}")
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
        
        # 更新节点映射配置
        if "nodeMapping" in data:
            try:
                if data["nodeMapping"] is None:
                    workflow.node_mapping = None
                else:
                    mapping = data["nodeMapping"]
                    if not isinstance(mapping, dict):
                        raise ValueError("nodeMapping 必须是对象")
                    workflow.node_mapping = json.dumps(mapping, ensure_ascii=False)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"无效的节点映射配置: {str(e)}")
    
    db.commit()
    db.refresh(workflow)
    
    return {
        "success": True,
        "data": {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "type": workflow.type,
            "typeName": WORKFLOW_TYPES.get(workflow.type, workflow.type),
            "isSystem": workflow.is_system,
            "isActive": workflow.is_active,
            "nodeMapping": json.loads(workflow.node_mapping) if workflow.node_mapping else None,
            "createdAt": workflow.created_at.isoformat() if workflow.created_at else None,
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
            "nodeMapping": json.loads(workflow.node_mapping) if workflow.node_mapping else None,
        }
    }
