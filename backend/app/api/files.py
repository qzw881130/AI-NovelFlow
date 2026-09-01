"""
文件服务 API - 提供用户故事资源的访问和上传
"""
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Query
from fastapi.responses import FileResponse, Response
from pathlib import Path
import mimetypes
import uuid
from datetime import datetime

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
        
        content_type, _ = mimetypes.guess_type(str(requested_path))
        if content_type is None:
            content_type = "application/octet-stream"
        return Response(
            status_code=200,
            media_type=content_type,
            headers={
                "Content-Length": str(requested_path.stat().st_size),
                "Accept-Ranges": "bytes",
            },
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    novel_id: str = Query(..., description="小说ID"),
    image_type: str = Query("character", description="图片类型: character, scene, shot"),
    chapter_id: str = Query(None, description="章节ID（shot类型需要）"),
    name: str = Query(None, description="名称（用于生成文件名）")
):
    """
    上传图片文件
    
    Args:
        file: 上传的文件
        novel_id: 小说ID
        image_type: 图片类型 (character, scene, shot)
        chapter_id: 章节ID（shot类型必填）
        name: 名称（用于生成文件名）
        
    Returns:
        {
            "success": bool,
            "file_path": str,  # 相对于 user_story 的路径
            "url": str  # 访问URL
        }
    """
    try:
        # 验证文件类型
        allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400, 
                detail=f"不支持的文件类型: {file.content_type}，仅支持 PNG, JPG, WEBP"
            )
        
        # 获取小说目录
        story_dir = file_storage._get_story_dir(novel_id)
        
        # 根据类型确定保存目录
        if image_type == "character":
            save_dir = story_dir / "characters"
        elif image_type == "scene":
            save_dir = story_dir / "scenes"
        elif image_type == "shot":
            if not chapter_id:
                raise HTTPException(status_code=400, detail="shot类型需要提供chapter_id")
            chapter_short = chapter_id[:8]
            save_dir = story_dir / f"chapter_{chapter_short}" / "shots"
        else:
            raise HTTPException(status_code=400, detail=f"不支持的图片类型: {image_type}")
        
        # 创建目录
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = file_storage._sanitize_filename(name) if name else "uploaded"
        
        # 获取文件扩展名
        ext = ".png"
        if file.filename:
            _, ext = Path(file.filename).suffix, Path(file.filename).suffix
            if ext.lower() not in [".png", ".jpg", ".jpeg", ".webp"]:
                ext = ".png"
        
        filename = f"{safe_name}_{timestamp}{ext}"
        file_path = save_dir / filename
        
        # 保存文件
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 计算相对路径和URL
        relative_path = file_path.relative_to(file_storage.base_dir)
        url = f"/api/files/{relative_path}"
        
        return {
            "success": True,
            "file_path": str(relative_path),
            "url": url,
            "filename": filename
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")
