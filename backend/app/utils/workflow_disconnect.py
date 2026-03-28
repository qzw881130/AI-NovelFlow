"""
工作流节点断开工具函数

提供断开参考图节点的工具函数，用于：
- 分镜图生成时未使用参考图
- 关键帧图片生成时未使用参考图
- 视频生成时未上传关键帧参考图
"""

from typing import Dict, Any, Optional, List


def disconnect_reference_chain(
    workflow: Dict[str, Any], start_node_id: str
) -> Dict[str, Any]:
    """
    从 LoadImage 节点开始，断开下游参考图链路的输入连接

    当参考图节点未上传图片时，应该断开下游使用 latent、pixels、image 类型输入的连接，
    而不是直接删除节点，这样可以避免工作流报错，兼容性更好。

    匹配规则：
    - latent、pixels：精确匹配
    - image：支持 image 或 image 后跟数字（如 image1, image2, image_1）

    Args:
        workflow: 工作流字典
        start_node_id: 起始节点 ID（通常是 LoadImage 节点）

    Returns:
        修改后的工作流
    """
    # 需要断开的输入类型
    EXACT_MATCH_TYPES = {"latent", "pixels"}

    # 追踪已访问的节点，避免循环
    visited = set()
    # 待处理的节点队列
    queue = [str(start_node_id)]

    while queue:
        current_node_id = queue.pop(0)

        if current_node_id in visited:
            continue
        visited.add(current_node_id)

        # 查找所有引用当前节点的下游节点
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue

            inputs = node.get("inputs", {})
            inputs_to_disconnect = []

            for input_name, input_value in inputs.items():
                # 检查是否是连接到当前节点的输入
                if isinstance(input_value, list) and len(input_value) >= 2:
                    source_node_id = str(input_value[0])
                    if source_node_id == current_node_id:
                        input_name_lower = input_name.lower()
                        should_disconnect = False

                        # 精确匹配 latent 和 pixels
                        if input_name_lower in EXACT_MATCH_TYPES:
                            should_disconnect = True
                        # image 类型：支持 image 或 image 后跟数字（如 image1, image2, image_1）
                        elif input_name_lower == "image":
                            should_disconnect = True
                        elif input_name_lower.startswith("image"):
                            suffix = input_name_lower[5:]  # 去掉 "image" 前缀
                            # 允许空字符串（即 "image"）或纯数字或 _数字
                            if suffix.isdigit() or (
                                suffix.startswith("_") and suffix[1:].isdigit()
                            ):
                                should_disconnect = True

                        if should_disconnect:
                            inputs_to_disconnect.append(input_name)
                        # 将下游节点加入队列继续追踪
                        if node_id not in visited:
                            queue.append(str(node_id))

            # 断开匹配的输入连接
            for input_name in inputs_to_disconnect:
                del inputs[input_name]
                print(
                    f"[Workflow] Disconnected input '{input_name}' from node {node_id} (source: {current_node_id})"
                )

    return workflow


def disconnect_all_reference_nodes(workflow: dict, node_mapping: dict):
    """
    断开所有参考图节点的下游连接

    Args:
        workflow: 工作流字典
        node_mapping: 节点映射
    """
    reference_node_keys = [
        key
        for key in node_mapping
        if key.endswith("_node_id") and "reference" in key.lower()
    ]
    for ref_key in reference_node_keys:
        node_id = node_mapping.get(ref_key)
        if node_id and str(node_id) in workflow:
            disconnect_reference_chain(workflow, str(node_id))
            print(
                f"[Workflow] Disconnected reference node {node_id} (key: {ref_key}) - no reference image provided"
            )


def disconnect_unuploaded_reference_nodes(
    workflow: dict,
    node_mapping: dict,
    reference_node_keys: Optional[List[str]] = None
):
    """
    检测并断开未上传图片的参考图节点的下游连接

    Args:
        workflow: 工作流字典
        node_mapping: 节点映射
        reference_node_keys: 要检查的参考图节点键名列表，如果为 None 则自动检测所有参考图节点
    """
    if reference_node_keys is None:
        # 自动检测所有参考图节点键名
        # 规则：包含"image_node" 且包含 "reference" 的键名
        reference_node_keys = [
            key
            for key in node_mapping
            if "image_node" in key.lower() and "reference" in key.lower()
        ]

    for ref_key in reference_node_keys:
        node_id = node_mapping.get(ref_key)
        if node_id and str(node_id) in workflow:
            node_id_str = str(node_id)
            # 检查该节点是否有有效的图片
            image_value = workflow[node_id_str].get("inputs", {}).get("image", "")
            # 如果没有有效图片，断开下游参考链路
            if not image_value or image_value in ["", ""]:
                disconnect_reference_chain(workflow, node_id_str)
                print(
                    f"[Workflow] Disconnected reference node {node_id_str} (key: {ref_key}) - no image uploaded"
                )


def clear_unset_reference_nodes(
    workflow: dict,
    node_mapping: dict,
    character_reference_path: Optional[str] = None,
    scene_reference_path: Optional[str] = None,
    prop_reference_paths: Optional[Dict[str, str]] = None,
):
    """
    清空未设置参考图的节点的 image 输入

    工作流中的 LoadImage 节点可能有默认图片数据。
    在用户未设置参考图时，需要将对应节点的 image 输入置空，
    这样后续的断开逻辑才能正确检测到未上传图片的节点。

    Args:
        workflow: 工作流字典
        node_mapping: 节点映射
        character_reference_path: 角色参考图路径（None 表示未设置）
        scene_reference_path: 场景参考图路径（None 表示未设置）
        prop_reference_paths: 道具参考图路径字典（None 或缺失项表示未设置）
    """
    # 清空未设置的角色参考图节点
    character_node_id = node_mapping.get("character_reference_image_node_id")
    if character_node_id and not character_reference_path:
        node_id_str = str(character_node_id)
        if node_id_str in workflow and "inputs" in workflow[node_id_str]:
            workflow[node_id_str]["inputs"]["image"] = ""
            print(
                f"[Workflow] Cleared character reference node {node_id_str} - no reference image provided"
            )

    # 清空未设置的场景参考图节点
    scene_node_id = node_mapping.get("scene_reference_image_node_id")
    if scene_node_id and not scene_reference_path:
        node_id_str = str(scene_node_id)
        if node_id_str in workflow and "inputs" in workflow[node_id_str]:
            workflow[node_id_str]["inputs"]["image"] = ""
            print(
                f"[Workflow] Cleared scene reference node {node_id_str} - no reference image provided"
            )

    # 清空未设置的道具参考图节点
    # 道具节点映射格式: custom_reference_image_node_<索引>
    index = 1
    while True:
        prop_node_id = node_mapping.get(f"custom_reference_image_node_{index}")
        if not prop_node_id:
            break

        # 检查该索引对应的道具是否有参考图
        has_prop_image = False
        if prop_reference_paths:
            # 按顺序检查，第 index 个道具
            prop_names = list(prop_reference_paths.keys())
            if index <= len(prop_names):
                prop_name = prop_names[index - 1]
                has_prop_image = bool(prop_reference_paths.get(prop_name))

        if not has_prop_image:
            node_id_str = str(prop_node_id)
            if node_id_str in workflow and "inputs" in workflow[node_id_str]:
                workflow[node_id_str]["inputs"]["image"] = ""
                print(
                    f"[Workflow] Cleared prop reference node {node_id_str} (index {index}) - no reference image provided"
                )

        index += 1


def clear_unset_keyframe_reference_nodes(
    workflow: dict,
    node_mapping: dict,
    reference_path: Optional[str] = None,
    secondary_reference_path: Optional[str] = None,
):
    """
    清空未设置参考图的关键帧节点

    工作流中的 LoadImage 节点可能有默认图片数据。
    在用户未设置参考图时，需要将对应节点的 image 输入置空，
    这样后续的断开逻辑才能正确检测到未上传图片的节点。

    Args:
        workflow: 工作流字典
        node_mapping: 节点映射
        reference_path: 主要参考图路径（None 表示未设置）
        secondary_reference_path: 辅助参考图路径（None 表示未设置，用于双参考图工作流）
    """
    # 清空未设置的主要参考图节点
    reference_node_id = node_mapping.get("reference_image_node_id")
    if reference_node_id and not reference_path:
        node_id_str = str(reference_node_id)
        if node_id_str in workflow and "inputs" in workflow[node_id_str]:
            workflow[node_id_str]["inputs"]["image"] = ""
            print(
                f"[Workflow] Cleared keyframe reference node {node_id_str} - no reference image provided"
            )

    # 清空未设置的辅助参考图节点（用于双参考图工作流）
    secondary_node_id = node_mapping.get("secondary_reference_image_node_id")
    if secondary_node_id and not secondary_reference_path:
        node_id_str = str(secondary_node_id)
        if node_id_str in workflow and "inputs" in workflow[node_id_str]:
            workflow[node_id_str]["inputs"]["image"] = ""
            print(
                f"[Workflow] Cleared secondary keyframe reference node {node_id_str} - no reference image provided"
            )