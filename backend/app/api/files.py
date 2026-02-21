"""
文件服务 API - 提供用户故事资源的访问
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pathlib import Path
import mimetypes

from app.services.file_storage import file_storage

router = APIRouter()


@router.options("/{path:path}")
async def options_file(request: Request, path: str):
    """处理 CORS 预检请求"""
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "86400",
        }
    )


@router.get("/{path:path}")
async def get_file(path: str):
    """
    获取用户故事目录下的文件
    
    路径格式: story_{novel_id}/characters/{filename}.png
              story_{novel_id}/chapter_{chapter_id}/shots/{filename}.png
              story_{novel_id}/chapter_{chapter_id}/videos/{filename}.mp4
    """
    try:
        # 安全检查：确保路径在 base_dir 内
        requested_path = file_storage.base_dir / path
        requested_path = requested_path.resolve()
        base_resolved = file_storage.base_dir.resolve()
        
        # 防止目录遍历攻击
        if not str(requested_path).startswith(str(base_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
        
        if not requested_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        
        if not requested_path.is_file():
            raise HTTPException(status_code=400, detail="Not a file")
        
        # 猜测文件类型
        content_type, _ = mimetypes.guess_type(str(requested_path))
        if content_type is None:
            content_type = "application/octet-stream"
        
        return FileResponse(
            path=str(requested_path),
            media_type=content_type,
            filename=requested_path.name
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")


@router.head("/{path:path}")
async def check_file(path: str):
    """检查文件是否存在（用于预检）"""
    try:
        requested_path = file_storage.base_dir / path
        requested_path = requested_path.resolve()
        base_resolved = file_storage.base_dir.resolve()
        
        if not str(requested_path).startswith(str(base_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
        
        if not requested_path.exists() or not requested_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        
        return {"exists": True, "size": requested_path.stat().st_size}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")
