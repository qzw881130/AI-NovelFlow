"""工具函数模块"""
from datetime import datetime, timezone
from typing import Optional


def format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """
    将 datetime 对象格式化为带 UTC 时区的 ISO 8601 字符串
    
    由于数据库存储的是 UTC 时间（通过 datetime.utcnow() 写入），
    但 SQLite 不保存时区信息，所以需要在序列化时显式添加 UTC 时区标记，
    以便前端能正确转换为本地时间。
    
    Args:
        dt: datetime 对象（无时区信息，假设为 UTC）
        
    Returns:
        带时区的 ISO 8601 格式字符串，如 "2026-02-25T06:36:26+00:00"
        或 None（如果输入为 None）
    """
    if dt is None:
        return None
    # 添加 UTC 时区信息并格式化为 ISO 8601
    return dt.replace(tzinfo=timezone.utc).isoformat()
