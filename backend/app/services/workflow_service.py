"""
工作流服务层

封装工作流相关的业务逻辑
"""
import json
import os
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.repositories import WorkflowRepository
from app.constants.workflow import (
    WORKFLOW_TYPES,
    DEFAULT_WORKFLOWS,
    DEFAULT_WORKFLOW_NODE_MAPPINGS,
    EXTRA_SYSTEM_WORKFLOWS,
    get_workflow_i18n_keys,
)
from app.core.workflow_extensions import (
    get_extension_config,
    get_default_extension,
    validate_extension,
    get_all_extension_configs
)
from app.utils.time_utils import format_datetime


class WorkflowService:
    """工作流服务"""

    def __init__(self, db: Session):
        self.db = db
        self.workflow_repo = WorkflowRepository(db)

    # ==================== 目录路径 ====================

    @staticmethod
    def get_workflows_dir() -> str:
        """获取系统工作流文件目录"""
        return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workflows")

    @staticmethod
    def get_user_workflows_dir() -> str:
        """获取用户工作流文件目录"""
        return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "user_workflows")

    # ==================== 默认工作流加载 ====================

    def load_default_workflows(self) -> None:
        """加载默认工作流到数据库"""
        workflows_dir = self.get_workflows_dir()

        # 1. 加载默认工作流
        self._load_default_workflow_files(workflows_dir)

        # 2. 加载额外的系统工作流
        self._load_extra_system_workflows(workflows_dir)

        self.db.commit()

        # 3. 确保每种类型只有一个默认激活的工作流
        self._ensure_single_active_workflow()

    def _load_default_workflow_files(self, workflows_dir: str) -> None:
        """加载默认工作流文件"""
        for wf_type, filename in DEFAULT_WORKFLOWS.items():
            file_path = os.path.join(workflows_dir, filename)

            # 检查是否已存在同名系统工作流
            existing = self.workflow_repo.get_by_file_path(file_path, is_system=True)

            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    workflow_json = f.read()

                # 获取该类型的默认节点映射
                node_mapping = DEFAULT_WORKFLOW_NODE_MAPPINGS.get(wf_type)

                # 如果已存在，检查内容是否有变化，有则更新
                if existing:
                    if existing.workflow_json != workflow_json:
                        existing.workflow_json = workflow_json
                        self.db.commit()
                        print(f"[Workflow] Updated default workflow: {wf_type}")

                    # 更新节点映射（如果配置中有且未设置）
                    if node_mapping and not existing.node_mapping:
                        existing.node_mapping = json.dumps(node_mapping, ensure_ascii=False)
                        print(f"[Workflow] Updated node mapping for default: {wf_type}")
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
                    file_path=file_path,
                    node_mapping=json.dumps(node_mapping, ensure_ascii=False) if node_mapping else None
                )
                self.db.add(workflow)

    def _load_extra_system_workflows(self, workflows_dir: str) -> None:
        """加载额外的系统工作流"""
        # 跟踪每种类型已经处理过的工作流，确保同类型只有第一个是默认激活的
        processed_types: Dict[str, int] = {}

        for wf_config in EXTRA_SYSTEM_WORKFLOWS:
            file_path = os.path.join(workflows_dir, wf_config["filename"])
            wf_type = wf_config["type"]

            if not os.path.exists(file_path):
                continue

            with open(file_path, 'r', encoding='utf-8') as f:
                workflow_json = f.read()

            # 检查是否已存在
            existing = self.workflow_repo.get_by_file_path(file_path, is_system=True)

            if existing:
                self._update_existing_workflow(existing, wf_config, workflow_json)
                continue

            # 创建新工作流
            self._create_new_workflow(wf_config, workflow_json, file_path, wf_type, processed_types)

    def _update_existing_workflow(self, existing: Workflow, wf_config: dict, workflow_json: str) -> None:
        """更新已存在的工作流"""
        # 检查内容是否有变化，有则更新
        if existing.workflow_json != workflow_json:
            existing.workflow_json = workflow_json
            existing.name = wf_config["name"]
            existing.description = wf_config["description"]
            print(f"[Workflow] Updated: {wf_config['name']}")

        # 更新节点映射（如果配置中有且未设置）
        if "node_mapping" in wf_config:
            current_mapping = self._parse_json_field(existing.node_mapping)
            if not current_mapping:
                existing.node_mapping = json.dumps(wf_config["node_mapping"], ensure_ascii=False)
                print(f"[Workflow] Updated node mapping: {wf_config['name']}")

        # 更新扩展属性（如果配置中有且未设置）
        if "extension" in wf_config:
            current_extension = self._parse_json_field(existing.extension)
            if not current_extension:
                existing.extension = json.dumps(wf_config["extension"], ensure_ascii=False)
                print(f"[Workflow] Updated extension: {wf_config['name']} -> {wf_config['extension']}")

    def _create_new_workflow(
        self,
        wf_config: dict,
        workflow_json: str,
        file_path: str,
        wf_type: str,
        processed_types: Dict[str, int]
    ) -> None:
        """创建新的工作流"""
        # 检查该类型是否已有激活的工作流（数据库中）
        has_active_in_db = self.workflow_repo.get_active_by_type(wf_type) is not None

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

        # 设置默认扩展属性（如果配置中有）
        if "extension" in wf_config:
            workflow.extension = json.dumps(wf_config["extension"], ensure_ascii=False)
            print(f"[Workflow] Added: {wf_config['name']} with extension {wf_config['extension']} (active={should_be_active})")
        elif workflow.extension:
            print(f"[Workflow] Added: {wf_config['name']} with node mapping (active={should_be_active})")
        else:
            print(f"[Workflow] Added: {wf_config['name']} (active={should_be_active})")

        self.db.add(workflow)

    def _ensure_single_active_workflow(self) -> None:
        """确保每种类型只有一个默认激活的工作流"""
        for wf_type in WORKFLOW_TYPES.keys():
            # 获取该类型所有激活的工作流，按创建时间排序
            active_workflows = self.workflow_repo.list_active_by_type(wf_type)

            if len(active_workflows) > 1:
                # 有多个激活的，只保留第一个，其余取消激活
                for wf in active_workflows[1:]:
                    wf.is_active = False
                    print(f"[Workflow] Deactivated duplicate default: {wf.name}")
                self.db.commit()
            elif not active_workflows:
                # 没有激活的，找到该类型的第一个系统工作流设为默认
                first_workflow = self.workflow_repo.get_first_system_by_type(wf_type)

                if first_workflow:
                    first_workflow.is_active = True
                    print(f"[Workflow] Set default for {wf_type}: {first_workflow.name}")
                    self.db.commit()

    # ==================== 工作流操作 ====================

    def upload_workflow(
        self,
        name: str,
        wf_type: str,
        description: Optional[str],
        extension: Optional[str],
        file_content: bytes
    ) -> Dict[str, Any]:
        """
        上传自定义工作流

        Args:
            name: 工作流名称
            wf_type: 工作流类型
            description: 描述
            extension: 扩展属性 JSON 字符串
            file_content: 文件内容

        Returns:
            上传结果
        """
        if wf_type not in WORKFLOW_TYPES:
            return {
                "success": False,
                "status_code": 400,
                "message": f"无效的工作流类型，可选: {list(WORKFLOW_TYPES.keys())}"
            }

        # 验证JSON格式
        try:
            workflow_data = json.loads(file_content)
            workflow_json = json.dumps(workflow_data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "status_code": 400,
                "message": f"无效的JSON文件: {str(e)}"
            }

        # 确保用户工作流目录存在
        user_workflows_dir = self.get_user_workflows_dir()
        os.makedirs(user_workflows_dir, exist_ok=True)

        # 保存文件到用户工作流目录
        safe_name = "".join(c for c in name if c.isalnum() or c in ('-', '_')).strip()
        filename = f"{safe_name}_{wf_type}.json"
        file_path = os.path.join(user_workflows_dir, filename)

        # 如果文件已存在，添加数字后缀
        counter = 1
        while os.path.exists(file_path):
            filename = f"{safe_name}_{wf_type}_{counter}.json"
            file_path = os.path.join(user_workflows_dir, filename)
            counter += 1

        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(workflow_json)

        # 解析并验证扩展属性
        extension_data = self._parse_and_validate_extension(wf_type, extension)
        if extension_data is None and extension is not None:
            return {
                "success": False,
                "status_code": 400,
                "message": "扩展属性必须是有效的 JSON 字符串"
            }

        # 如果没有提供扩展属性，使用默认值
        if not extension_data:
            extension_data = get_default_extension(wf_type, name)

        # 创建工作流记录
        workflow = Workflow(
            name=name,
            description=description or f"用户上传的{WORKFLOW_TYPES.get(wf_type, wf_type)}工作流",
            type=wf_type,
            workflow_json=workflow_json,
            is_system=False,
            is_active=False,
            created_by="user",
            file_path=file_path,
            extension=json.dumps(extension_data, ensure_ascii=False) if extension_data else None
        )
        self.workflow_repo.create(workflow)

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

    def update_workflow(self, workflow_id: str, data: dict) -> Dict[str, Any]:
        """
        更新工作流信息

        Args:
            workflow_id: 工作流ID
            data: 更新数据

        Returns:
            更新结果
        """
        workflow = self.workflow_repo.get_by_id(workflow_id)
        if not workflow:
            return {
                "success": False,
                "status_code": 404,
                "message": "工作流不存在"
            }

        # 根据工作流类型（系统/用户）更新不同字段
        if workflow.is_system:
            self._update_system_workflow(workflow, data)
        else:
            self._update_user_workflow(workflow, data)

        self.workflow_repo.update(workflow)

        return {
            "success": True,
            "data": self.format_workflow_detail(workflow)
        }

    def _update_system_workflow(self, workflow: Workflow, data: dict) -> None:
        """更新系统工作流"""
        if "name" in data:
            workflow.name = data["name"]
        if "description" in data:
            workflow.description = data["description"]
        if "isActive" in data:
            workflow.is_active = data["isActive"]

        # 系统工作流支持节点映射配置
        if "nodeMapping" in data:
            workflow.node_mapping = self._process_mapping_field(data["nodeMapping"])

        # 系统工作流支持扩展属性配置
        if "extension" in data:
            workflow.extension = self._process_extension_field(workflow.type, data["extension"])

    def _update_user_workflow(self, workflow: Workflow, data: dict) -> None:
        """更新用户工作流"""
        if "name" in data:
            workflow.name = data["name"]
        if "description" in data:
            workflow.description = data["description"]
        if "isActive" in data:
            workflow.is_active = data["isActive"]

        # 用户工作流可以修改JSON内容
        if "workflowJson" in data:
            self._update_workflow_json(workflow, data["workflowJson"])

        # 更新节点映射配置
        if "nodeMapping" in data:
            workflow.node_mapping = self._process_mapping_field(data["nodeMapping"])

        # 更新扩展属性配置
        if "extension" in data:
            workflow.extension = self._process_extension_field(workflow.type, data["extension"])

    def _update_workflow_json(self, workflow: Workflow, workflow_json: str) -> None:
        """更新工作流JSON内容"""
        try:
            workflow_data = json.loads(workflow_json)
            workflow.workflow_json = workflow_json

            # 同时更新文件
            if workflow.file_path and os.path.exists(workflow.file_path):
                with open(workflow.file_path, 'w', encoding='utf-8') as f:
                    json.dump(workflow_data, f, ensure_ascii=False, indent=2)
        except json.JSONDecodeError as e:
            raise ValueError(f"无效的JSON内容: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"保存文件失败: {str(e)}")

    def set_default_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        设置默认工作流

        Args:
            workflow_id: 工作流ID

        Returns:
            设置结果
        """
        workflow = self.workflow_repo.get_by_id(workflow_id)
        if not workflow:
            return {
                "success": False,
                "status_code": 404,
                "message": "工作流不存在"
            }

        # 将该类型的所有工作流设为非激活
        self.workflow_repo.deactivate_all_by_type(workflow.type)

        # 将当前工作流设为激活
        workflow.is_active = True
        self.db.commit()

        return {
            "success": True,
            "message": f"已设为默认{WORKFLOW_TYPES.get(workflow.type, workflow.type)}工作流"
        }

    def delete_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        删除工作流

        Args:
            workflow_id: 工作流ID

        Returns:
            删除结果
        """
        workflow = self.workflow_repo.get_by_id(workflow_id)
        if not workflow:
            return {
                "success": False,
                "status_code": 404,
                "message": "工作流不存在"
            }

        # 不能删除系统工作流
        if workflow.is_system:
            return {
                "success": False,
                "status_code": 403,
                "message": "系统预设工作流不能删除"
            }

        self.workflow_repo.delete(workflow)

        return {"success": True, "message": "删除成功"}

    # ==================== 扩展属性 ====================

    def get_extension_configs(self) -> Dict[str, Any]:
        """获取所有工作流类型的扩展属性配置"""
        return get_all_extension_configs()

    def get_extension_config_by_type(self, workflow_type: str) -> Optional[Dict[str, Any]]:
        """获取指定工作流类型的扩展属性配置"""
        if workflow_type not in WORKFLOW_TYPES:
            return None

        config = get_extension_config(workflow_type)
        default = get_default_extension(workflow_type)

        return {
            "type": workflow_type,
            "typeName": WORKFLOW_TYPES.get(workflow_type, workflow_type),
            "config": config,
            "default": default
        }

    # ==================== 辅助方法 ====================

    @staticmethod
    def _parse_json_field(value: Optional[str]) -> Optional[dict]:
        """解析 JSON 字段"""
        if not value:
            return None
        try:
            return json.loads(value)
        except Exception:
            return None

    def _parse_and_validate_extension(self, wf_type: str, extension: Optional[str]) -> Optional[dict]:
        """解析并验证扩展属性"""
        if not extension:
            return None

        try:
            extension_data = json.loads(extension)
            is_valid, error_msg = validate_extension(wf_type, extension_data)
            if not is_valid:
                raise ValueError(error_msg)
            return extension_data
        except json.JSONDecodeError:
            return None

    def _process_mapping_field(self, mapping: Any) -> Optional[str]:
        """处理节点映射字段"""
        if mapping is None:
            return None

        if not isinstance(mapping, dict):
            raise ValueError("nodeMapping 必须是对象")

        return json.dumps(mapping, ensure_ascii=False)

    def _process_extension_field(self, wf_type: str, extension: Any) -> Optional[str]:
        """处理扩展属性字段"""
        if extension is None:
            return None

        if not isinstance(extension, dict):
            raise ValueError("extension 必须是对象")

        is_valid, error_msg = validate_extension(wf_type, extension)
        if not is_valid:
            raise ValueError(error_msg)

        return json.dumps(extension, ensure_ascii=False)

    # ==================== 格式化响应 ====================

    @staticmethod
    def format_workflow_list(workflows: List[Workflow]) -> List[dict]:
        """格式化工作流列表响应"""
        result = []
        for w in workflows:
            # 获取翻译键（仅系统工作流）
            i18n_keys = get_workflow_i18n_keys(w.name, w.description) if w.is_system else {"nameKey": None, "descriptionKey": None}
            
            result.append({
                "id": w.id,
                "name": w.name,
                "nameKey": i18n_keys["nameKey"],
                "description": w.description,
                "descriptionKey": i18n_keys["descriptionKey"],
                "type": w.type,
                "typeName": WORKFLOW_TYPES.get(w.type, w.type),
                "isSystem": w.is_system,
                "isActive": w.is_active,
                "nodeMapping": json.loads(w.node_mapping) if w.node_mapping else None,
                "extension": json.loads(w.extension) if w.extension else None,
                "createdAt": format_datetime(w.created_at),
            })
        return result

    @staticmethod
    def format_workflow_detail(workflow: Workflow) -> dict:
        """格式化工作流详情响应"""
        # 获取翻译键（仅系统工作流）
        i18n_keys = get_workflow_i18n_keys(workflow.name, workflow.description) if workflow.is_system else {"nameKey": None, "descriptionKey": None}
        
        return {
            "id": workflow.id,
            "name": workflow.name,
            "nameKey": i18n_keys["nameKey"],
            "description": workflow.description,
            "descriptionKey": i18n_keys["descriptionKey"],
            "type": workflow.type,
            "typeName": WORKFLOW_TYPES.get(workflow.type, workflow.type),
            "workflowJson": workflow.workflow_json,
            "isSystem": workflow.is_system,
            "isActive": workflow.is_active,
            "nodeMapping": json.loads(workflow.node_mapping) if workflow.node_mapping else None,
            "extension": json.loads(workflow.extension) if workflow.extension else None,
            "createdAt": format_datetime(workflow.created_at),
        }

    @staticmethod
    def format_active_workflow(workflow: Workflow) -> dict:
        """格式化激活工作流响应"""
        return {
            "id": workflow.id,
            "name": workflow.name,
            "type": workflow.type,
            "workflowJson": workflow.workflow_json,
            "isSystem": workflow.is_system,
            "nodeMapping": json.loads(workflow.node_mapping) if workflow.node_mapping else None,
        }
