"""
工作流 API 路由

只负责请求/响应处理，业务逻辑委托给 WorkflowService
"""
import json
import os
import uuid
import zipfile
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional

from app.core.database import get_db
from app.repositories import WorkflowRepository
from app.services.workflow_service import WorkflowService
from app.constants.workflow import WORKFLOW_TYPES
from app.core.workflow_extensions import validate_extension
from app.api.deps import get_workflow_repo
from app.models.workflow import Workflow

router = APIRouter()


def _safe_filename_part(value: str) -> str:
    invalid_chars = '<>:"/\\|?*\n\r\t'
    result = ''.join('_' if ch in invalid_chars else ch for ch in str(value or '').strip())
    return result.strip(' ._') or 'workflow'


def _pretty_workflow_json(value: str) -> str:
    try:
        return json.dumps(json.loads(value), ensure_ascii=False, indent=2)
    except Exception:
        return value or '{}'


def _parse_json_object(value: Any, field_name: str) -> Dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception as exc:
            raise ValueError(f"{field_name} 不是有效 JSON: {exc}")
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"{field_name} 必须是对象")


def _build_export_manifest_item(workflow: Workflow, workflow_file: str) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description or "",
        "type": workflow.type,
        "type_label": WORKFLOW_TYPES.get(workflow.type, workflow.type),
        "is_system": workflow.is_system,
        "is_active": workflow.is_active,
        "node_mapping": _parse_json_object(workflow.node_mapping, "node_mapping") if workflow.node_mapping else {},
        "extension": _parse_json_object(workflow.extension, "extension") if workflow.extension else {},
        "workflow_file": workflow_file,
        "workflow_json_format": "comfyui_object",
        "created_by": workflow.created_by,
        "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
    }


def _extract_workflow_node_ids(workflow_json: Any) -> set:
    if isinstance(workflow_json, dict):
        node_ids = {str(key) for key in workflow_json.keys()}
        nodes = workflow_json.get("nodes")
        if isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, dict) and node.get("id") is not None:
                    node_ids.add(str(node["id"]))
        return node_ids

    if isinstance(workflow_json, list):
        node_ids = set()
        for node in workflow_json:
            if isinstance(node, dict) and node.get("id") is not None:
                node_ids.add(str(node["id"]))
        return node_ids

    return set()


def _iter_node_mapping_refs(value: Any):
    if isinstance(value, dict):
        for nested_value in value.values():
            yield from _iter_node_mapping_refs(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            yield from _iter_node_mapping_refs(nested_value)
    elif value not in (None, "", "auto"):
        yield str(value)


def _validate_node_mapping_refs(node_mapping: Dict[str, Any], workflow_json: Any) -> List[str]:
    errors = []
    node_ids = _extract_workflow_node_ids(workflow_json)
    if not node_ids:
        return errors
    for key, value in node_mapping.items():
        if "node" not in key:
            continue
        for node_id in _iter_node_mapping_refs(value):
            if node_id not in node_ids:
                errors.append(f"节点映射 {key} 指向不存在的节点 {node_id}")
    return errors


def _read_import_package(content: bytes) -> List[Dict[str, Any]]:
    try:
        zip_buffer = BytesIO(content)
        with zipfile.ZipFile(zip_buffer, "r") as zip_file:
            if "manifest.json" not in zip_file.namelist():
                raise ValueError("ZIP 中缺少 manifest.json")

            try:
                manifest = json.loads(zip_file.read("manifest.json").decode("utf-8"))
            except Exception as exc:
                raise ValueError(f"manifest.json 不是有效 JSON: {exc}")

            workflows = manifest.get("workflows") if isinstance(manifest, dict) else manifest
            if not isinstance(workflows, list):
                raise ValueError("manifest.json 必须包含 workflows 数组")

            parsed_items = []
            for index, item in enumerate(workflows):
                if not isinstance(item, dict):
                    parsed_items.append({"index": index, "valid": False, "errors": ["manifest 工作流条目必须是对象"]})
                    continue

                errors = []
                workflow_type = str(item.get("type") or "").strip()
                name = str(item.get("name") or "").strip()
                workflow_file = str(item.get("workflow_file") or "").strip()
                workflow_json_text = ""
                workflow_json = None

                if not name:
                    errors.append("工作流名称不能为空")
                if workflow_type not in WORKFLOW_TYPES:
                    errors.append(f"无效工作流分类: {workflow_type or '-'}")

                if not workflow_file:
                    errors.append("缺少 workflow_file")
                elif workflow_file not in zip_file.namelist():
                    errors.append(f"缺少工作流 JSON 文件: {workflow_file}")
                else:
                    try:
                        workflow_json_text = zip_file.read(workflow_file).decode("utf-8")
                        workflow_json = json.loads(workflow_json_text)
                        if not isinstance(workflow_json, (dict, list)):
                            errors.append("工作流 JSON 顶层必须是对象或节点数组")
                    except Exception as exc:
                        errors.append(f"工作流 JSON 无效: {exc}")

                node_mapping = {}
                try:
                    node_mapping = _parse_json_object(item.get("node_mapping"), "node_mapping")
                except ValueError as exc:
                    errors.append(str(exc))

                if node_mapping and isinstance(workflow_json, dict):
                    errors.extend(_validate_node_mapping_refs(node_mapping, workflow_json))

                extension = {}
                try:
                    extension = _parse_json_object(item.get("extension"), "extension")
                    if workflow_type in WORKFLOW_TYPES and extension:
                        is_valid, error_msg = validate_extension(workflow_type, extension)
                        if not is_valid:
                            errors.append(f"扩展属性不符合 {WORKFLOW_TYPES.get(workflow_type, workflow_type)} 要求: {error_msg}")
                except ValueError as exc:
                    errors.append(str(exc))

                parsed_items.append({
                    "index": index,
                    "id": item.get("id"),
                    "name": name,
                    "description": item.get("description") or "",
                    "type": workflow_type,
                    "type_label": item.get("type_label") or WORKFLOW_TYPES.get(workflow_type, workflow_type),
                    "is_system": bool(item.get("is_system")),
                    "is_active": bool(item.get("is_active")),
                    "node_mapping": node_mapping,
                    "extension": extension,
                    "workflow_file": workflow_file,
                    "workflow_json": workflow_json,
                    "workflow_json_text": json.dumps(workflow_json, ensure_ascii=False, indent=2) if workflow_json is not None else workflow_json_text,
                    "valid": not errors,
                    "errors": errors,
                })

            return parsed_items
    except zipfile.BadZipFile:
        raise ValueError("上传文件不是有效 ZIP")


def get_workflow_service(db: Session = Depends(get_db)) -> WorkflowService:
    """获取 WorkflowService 实例"""
    return WorkflowService(db)


# ==================== 工作流列表 ====================

@router.get("/", response_model=dict)
async def list_workflows(
    type: Optional[str] = None,
    db: Session = Depends(get_db),
    workflow_service: WorkflowService = Depends(get_workflow_service),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo)
):
    """获取工作流列表"""
    # 确保默认工作流已加载
    workflow_service.load_default_workflows()

    if type:
        workflows = workflow_repo.list_by_type(type)
    else:
        workflows = workflow_repo.list_all()

    return {
        "success": True,
        "data": WorkflowService.format_workflow_list(workflows)
    }


@router.get("/export-active", response_model=None)
async def export_active_workflows(
    workflow_service: WorkflowService = Depends(get_workflow_service),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
):
    """打包下载所有类别的当前工作流 JSON。"""
    workflow_service.load_default_workflows()

    zip_buffer = BytesIO()
    exported = []
    used_filenames = set()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for workflow_type, type_label in WORKFLOW_TYPES.items():
            workflow = workflow_repo.get_active_by_type(workflow_type)
            if not workflow:
                workflow = workflow_repo.get_first_system_by_type(workflow_type)
            if not workflow:
                continue

            base_name = f"{_safe_filename_part(type_label)}：{_safe_filename_part(workflow.name)}"
            filename = f"{base_name}.json"
            duplicate_index = 2
            while filename in used_filenames:
                filename = f"{base_name}_{duplicate_index}.json"
                duplicate_index += 1
            used_filenames.add(filename)

            zip_file.writestr(filename, _pretty_workflow_json(workflow.workflow_json))
            exported.append({
                "type": workflow_type,
                "type_label": type_label,
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "is_system": workflow.is_system,
                "is_active": workflow.is_active,
                "filename": filename,
            })

        zip_file.writestr("manifest.json", json.dumps(exported, ensure_ascii=False, indent=2))

    zip_buffer.seek(0)
    filename = "comfyui_active_workflows.zip"
    encoded_filename = quote(filename)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=workflows.zip; filename*=UTF-8''{encoded_filename}"},
    )


@router.post("/export", response_model=None)
async def export_selected_workflows(
    data: dict,
    workflow_service: WorkflowService = Depends(get_workflow_service),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
):
    """按用户选择导出工作流 ZIP，包含工作流 JSON 和完整元数据。"""
    workflow_service.load_default_workflows()

    workflow_ids = data.get("workflow_ids") if isinstance(data, dict) else None
    if not isinstance(workflow_ids, list) or not workflow_ids:
        raise HTTPException(status_code=400, detail="请选择要导出的工作流")

    workflows = []
    missing_ids = []
    for workflow_id in workflow_ids:
        workflow = workflow_repo.get_by_id(str(workflow_id))
        if workflow:
            workflows.append(workflow)
        else:
            missing_ids.append(str(workflow_id))
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"工作流不存在: {', '.join(missing_ids)}")

    zip_buffer = BytesIO()
    used_filenames = set()
    manifest_items = []
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for workflow in workflows:
            base_name = f"workflows/{_safe_filename_part(WORKFLOW_TYPES.get(workflow.type, workflow.type))}_{_safe_filename_part(workflow.name)}"
            filename = f"{base_name}.json"
            duplicate_index = 2
            while filename in used_filenames:
                filename = f"{base_name}_{duplicate_index}.json"
                duplicate_index += 1
            used_filenames.add(filename)

            zip_file.writestr(filename, _pretty_workflow_json(workflow.workflow_json))
            manifest_items.append(_build_export_manifest_item(workflow, filename))

        zip_file.writestr("manifest.json", json.dumps({
            "version": 1,
            "kind": "novelflow_comfyui_workflows",
            "workflows": manifest_items,
        }, ensure_ascii=False, indent=2))

    zip_buffer.seek(0)
    filename = "comfyui_workflows_export.zip"
    encoded_filename = quote(filename)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=workflows_export.zip; filename*=UTF-8''{encoded_filename}"},
    )


@router.post("/import/preview", response_model=dict)
async def preview_import_workflows(
    file: UploadFile = File(...),
):
    """解析工作流 ZIP 并返回可选择导入的条目及校验结果。"""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 ZIP 文件")
    content = await file.read()
    try:
        items = _read_import_package(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "data": {
            "workflows": [{k: v for k, v in item.items() if k not in {"workflow_json", "workflow_json_text"}} for item in items],
            "valid_count": sum(1 for item in items if item.get("valid")),
            "invalid_count": sum(1 for item in items if not item.get("valid")),
        }
    }


@router.post("/import/execute", response_model=dict)
async def execute_import_workflows(
    selected_indexes: str = Form(...),
    file: UploadFile = File(...),
    workflow_service: WorkflowService = Depends(get_workflow_service),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo),
):
    """导入用户选择的工作流，保留名称、分类、描述、节点映射和扩展属性。"""
    try:
        selected = json.loads(selected_indexes)
    except Exception:
        raise HTTPException(status_code=400, detail="selected_indexes 必须是 JSON 数组")
    if not isinstance(selected, list) or not selected:
        raise HTTPException(status_code=400, detail="请选择要导入的工作流")
    try:
        selected_set = {int(index) for index in selected}
    except Exception:
        raise HTTPException(status_code=400, detail="selected_indexes 只能包含数字索引")

    content = await file.read()
    try:
        items = _read_import_package(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    selected_items = [item for item in items if item.get("index") in selected_set]
    if len(selected_items) != len(selected_set):
        raise HTTPException(status_code=400, detail="选择项与 ZIP 内容不匹配，请重新上传后再试")

    invalid_items = [item for item in selected_items if not item.get("valid")]
    if invalid_items:
        details = "; ".join(f"{item.get('name') or item.get('index')}: {', '.join(item.get('errors') or [])}" for item in invalid_items)
        raise HTTPException(status_code=400, detail=f"存在不符合导入条件的工作流: {details}")

    user_workflows_dir = workflow_service.get_user_workflows_dir()
    os.makedirs(user_workflows_dir, exist_ok=True)

    imported = []
    for item in selected_items:
        workflow_type = item["type"]
        name = item["name"]
        safe_name = _safe_filename_part(name)
        filename = f"{safe_name}_{workflow_type}_{uuid.uuid4().hex[:8]}.json"
        file_path = os.path.join(user_workflows_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(item["workflow_json_text"])

        workflow = Workflow(
            name=name,
            description=item.get("description") or f"导入的{WORKFLOW_TYPES.get(workflow_type, workflow_type)}工作流",
            type=workflow_type,
            workflow_json=item["workflow_json_text"],
            is_system=False,
            is_active=False,
            created_by="import",
            file_path=file_path,
            node_mapping=json.dumps(item.get("node_mapping") or {}, ensure_ascii=False) if item.get("node_mapping") else None,
            extension=json.dumps(item.get("extension") or {}, ensure_ascii=False) if item.get("extension") else None,
        )
        workflow_repo.create(workflow)
        imported.append({
            "id": workflow.id,
            "name": workflow.name,
            "type": workflow.type,
            "type_label": WORKFLOW_TYPES.get(workflow.type, workflow.type),
        })

    return {"success": True, "message": f"已导入 {len(imported)} 个工作流", "data": {"imported": imported}}


@router.get("/{workflow_id}/", response_model=dict)
async def get_workflow(
    workflow_id: str,
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo)
):
    """获取工作流详情"""
    workflow = workflow_repo.get_by_id(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    return {
        "success": True,
        "data": WorkflowService.format_workflow_detail(workflow)
    }


# ==================== 工作流上传 ====================

@router.post("/upload/", response_model=dict)
async def upload_workflow(
    name: str = Form(...),
    type: str = Form(...),
    description: Optional[str] = Form(None),
    extension: Optional[str] = Form(None),
    file: UploadFile = File(...),
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    """上传自定义工作流"""
    content = await file.read()
    result = workflow_service.upload_workflow(name, type, description, extension, content)

    if result.get("status_code"):
        raise HTTPException(status_code=result["status_code"], detail=result.get("message"))

    return result


# ==================== 工作流更新 ====================

@router.put("/{workflow_id}/", response_model=dict)
async def update_workflow(
    workflow_id: str,
    data: dict,
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    """更新工作流信息"""
    try:
        result = workflow_service.update_workflow(workflow_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if result.get("status_code"):
        raise HTTPException(status_code=result["status_code"], detail=result.get("message"))

    return result


# ==================== 工作流删除 ====================

@router.delete("/{workflow_id}/")
async def delete_workflow(
    workflow_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    """删除工作流"""
    result = workflow_service.delete_workflow(workflow_id)

    if result.get("status_code"):
        raise HTTPException(status_code=result["status_code"], detail=result.get("message"))

    return result


# ==================== 默认工作流设置 ====================

@router.post("/{workflow_id}/set-default/")
async def set_default_workflow(
    workflow_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    """设置默认工作流（将该类型的工作流设为激活状态，其他同类型的设为非激活）"""
    result = workflow_service.set_default_workflow(workflow_id)

    if result.get("status_code"):
        raise HTTPException(status_code=result["status_code"], detail=result.get("message"))

    return result


# ==================== 扩展属性配置 ====================

@router.get("/extensions/config/", response_model=dict)
async def get_extension_configs(
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    """获取所有工作流类型的扩展属性配置"""
    configs = workflow_service.get_extension_configs()
    return {
        "success": True,
        "data": configs
    }


@router.get("/extensions/{workflow_type}/", response_model=dict)
async def get_extension_config_by_type(
    workflow_type: str,
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    """获取指定工作流类型的扩展属性配置"""
    if workflow_type not in WORKFLOW_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的工作流类型，可选: {list(WORKFLOW_TYPES.keys())}")

    result = workflow_service.get_extension_config_by_type(workflow_type)
    return {
        "success": True,
        "data": result
    }


# ==================== 激活工作流 ====================

@router.get("/active/{workflow_type}", response_model=dict)
async def get_active_workflow(
    workflow_type: str,
    db: Session = Depends(get_db),
    workflow_service: WorkflowService = Depends(get_workflow_service),
    workflow_repo: WorkflowRepository = Depends(get_workflow_repo)
):
    """获取当前激活的工作流"""
    # 确保默认工作流已加载
    workflow_service.load_default_workflows()

    workflow = workflow_repo.get_active_by_type(workflow_type)

    if not workflow:
        # 如果没有激活的，返回该类型的第一个系统工作流
        workflow = workflow_repo.get_first_system_by_type(workflow_type)

    if not workflow:
        raise HTTPException(
            status_code=404,
            detail=f"没有找到{WORKFLOW_TYPES.get(workflow_type, workflow_type)}工作流"
        )

    return {
        "success": True,
        "data": WorkflowService.format_active_workflow(workflow)
    }
