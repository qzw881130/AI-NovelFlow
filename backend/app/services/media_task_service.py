"""
媒体生成任务服务

封装分镜图/视频/转场生成的后台任务

注意：具体实现已拆分到独立模块：
- shot_image_service.py: 分镜图生成
- shot_video_service.py: 分镜视频生成
- transition_service.py: 转场视频生成

本模块作为入口文件，保持向后兼容性
"""

# 从拆分后的模块导入，保持向后兼容性
from app.services.shot_image_service import generate_shot_image_task as generate_shot_task
from app.services.shot_video_service import generate_shot_video_task
from app.services.transition_service import generate_transition_video_task


# 保持向后兼容的导出
__all__ = [
    'generate_shot_task',
    'generate_shot_video_task',
    'generate_transition_video_task',
]
