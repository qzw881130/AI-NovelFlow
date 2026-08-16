"""
路径工具函数

封装路径转换相关的工具函数
"""
import os
from typing import Optional


def url_to_local_path(url: str) -> Optional[str]:
    """
    将 URL 转换为本地路径
    
    Args:
        url: 以 /api/files/ 开头的 URL
        
    Returns:
        本地文件路径，如果路径不存在则返回 None
    """
    if not url or not url.startswith("/api/files/"):
        return None
    
    relative_path = url.replace("/api/files/", "")
    relative_path = relative_path.lstrip("\\/")
    relative_path = relative_path.replace("\\", "/")
    path_parts = relative_path.split("/")
    
    # 获取项目根目录下的 user_story 目录
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    full_path = os.path.join(backend_dir, "user_story", *path_parts)
    full_path = os.path.abspath(full_path)
    
    if os.path.exists(full_path):
        return full_path
    return None


def local_path_to_url(path: str) -> Optional[str]:
    """将 user_story 下的本地路径转换为 /api/files/ URL。"""
    if not path:
        return None

    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    user_story_dir = os.path.abspath(os.path.join(backend_dir, "user_story"))
    full_path = os.path.abspath(path)

    try:
        relative_path = os.path.relpath(full_path, user_story_dir)
    except ValueError:
        return None

    if relative_path.startswith(".."):
        return None

    return f"/api/files/{relative_path.replace(os.sep, '/')}"
