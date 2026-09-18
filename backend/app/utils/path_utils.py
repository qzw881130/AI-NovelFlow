"""
路径工具函数

封装路径转换相关的工具函数
"""
import os
from typing import Optional


def get_storage_root() -> str:
    """One root shared by API, producers and workers; default preserves existing storage.

    Isolated execution processes may explicitly select a private root via env.
    This does not move or rewrite any existing media or provenance records.
    """
    configured = os.environ.get('NOVELFLOW_STORAGE_ROOT')
    if configured:
        if not os.path.isabs(configured):
            raise ValueError('NOVELFLOW_STORAGE_ROOT_MUST_BE_ABSOLUTE')
        return os.path.realpath(configured)
    return os.path.realpath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'user_story'))


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
    
    relative_path = url[len("/api/files/"):]
    relative_path = relative_path.lstrip("\\/")
    relative_path = relative_path.replace("\\", "/")
    path_parts = relative_path.split("/")
    
    # 获取项目根目录下的 user_story 目录
    storage_root = os.path.realpath(get_storage_root())
    full_path = os.path.join(storage_root, *path_parts)
    full_path = os.path.realpath(full_path)

    try:
        if os.path.commonpath((storage_root, full_path)) != storage_root:
            return None
    except ValueError:
        return None
    if os.path.exists(full_path):
        return full_path
    return None


def local_path_to_url(path: str) -> Optional[str]:
    """将 user_story 下的本地路径转换为 /api/files/ URL。"""
    if not path:
        return None

    user_story_dir = os.path.realpath(get_storage_root())
    full_path = os.path.realpath(path)

    try:
        if os.path.commonpath((user_story_dir, full_path)) != user_story_dir:
            return None
        relative_path = os.path.relpath(full_path, user_story_dir)
    except ValueError:
        return None

    return f"/api/files/{relative_path.replace(os.sep, '/')}"
