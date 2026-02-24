"""
ComfyUI 服务封装 (向后兼容层)

此文件保留是为了向后兼容。
新代码应直接使用 app.services.comfyui 模块。
"""
from app.services.comfyui import ComfyUIService, ComfyUIClient, WorkflowBuilder

__all__ = ["ComfyUIService", "ComfyUIClient", "WorkflowBuilder"]
