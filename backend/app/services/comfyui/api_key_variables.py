"""Bind configured text variables only for an image workflow submission."""

import copy
import json

from app.core.security import decrypt_value
from app.models.system_config import SystemConfig


INPUT_BY_CLASS = {"CR Text": "text", "CR Prompt Text": "prompt", "String": "value", "easy string": "value"}
VARIABLE_KEYS = {f"KEY{i}" for i in range(1, 10)}
BINDINGS = (
    ("api_key_node_id", "api_key_variable", "apiKey"),
    ("api_base_url_node_id", "api_base_url_key_variable", "apiBaseUrl"),
)


def bind_image_api_key(graph: dict, mapping: dict | None, db=None) -> dict:
    """Return a submission copy; never put the resolved value in saved workflow snapshots."""
    mapping = mapping or {}
    bindings = []
    reserved_nodes = {str(mapping.get(field) or "") for field in
                      ("prompt_node_id", "appearance_node_id", "style_node_id")}
    for node_field, key_field, label in BINDINGS:
        node_id = str(mapping.get(node_field) or "")
        key = str(mapping.get(key_field) or "")
        if not node_id and not key:
            continue
        if not node_id or key not in VARIABLE_KEYS:
            raise ValueError(f"{label} 节点和有效变量必须同时配置")
        if node_id in reserved_nodes or any(existing_id == node_id for existing_id, *_ in bindings):
            raise ValueError(f"{label} 节点不能与其他已映射的文本节点相同")
        node = graph.get(node_id)
        input_name = INPUT_BY_CLASS.get(node.get("class_type")) if isinstance(node, dict) else None
        if not input_name or not isinstance(node.get("inputs"), dict) or input_name not in node["inputs"]:
            raise ValueError(f"{label} 节点必须是带有可写输入的 CR Text、CR Prompt Text、String 或 easy string")
        bindings.append((node_id, key, input_name))
    if not bindings:
        return graph

    if db is None:
        from app.core.database import SessionLocal
        with SessionLocal() as session:
            return bind_image_api_key(graph, mapping, session)
    config = db.get(SystemConfig, "default")
    stored = json.loads(config.custom_variables or "{}") if config else {}
    submitted = copy.deepcopy(graph)
    for node_id, key, input_name in bindings:
        value = decrypt_value(stored.get(key, {}).get("value", ""))
        if not value:
            raise ValueError(f"自定义变量 {key} 没有值，请先在系统配置中填写")
        submitted[node_id]["inputs"][input_name] = value
    return submitted
