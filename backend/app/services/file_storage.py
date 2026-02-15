"""
文件存储服务 - 管理小说相关的所有资源文件
"""
import os
import httpx
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime


class FileStorageService:
    """文件存储服务"""
    
    def __init__(self, base_dir: str = None):
        """
        初始化文件存储服务
        
        Args:
            base_dir: 基础存储目录，默认为 backend/user_story
        """
        if base_dir is None:
            # 默认存储在 backend/user_story
            self.base_dir = Path(__file__).parent.parent.parent / "user_story"
        else:
            self.base_dir = Path(base_dir)
        
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_story_dir(self, novel_id: str) -> Path:
        """获取小说目录"""
        # 使用 story_{novel_id[:8]} 格式避免过长路径
        story_dir = self.base_dir / f"story_{novel_id[:8]}"
        story_dir.mkdir(parents=True, exist_ok=True)
        return story_dir
    
    def _sanitize_filename(self, name: str) -> str:
        """清理文件名，移除非法字符"""
        # 替换非法字符
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name.strip()
    
    async def download_image(self, url: str, novel_id: str, character_name: str, 
                            image_type: str = "character", chapter_id: str = None) -> Optional[str]:
        """
        下载图片并保存到指定目录
        
        Args:
            url: 图片URL (ComfyUI 返回的 view URL)
            novel_id: 小说ID
            character_name: 角色名或文件描述
            image_type: 图片类型 (character, shot, video_frame)
            chapter_id: 章节ID (用于 shot 类型)
            
        Returns:
            本地文件路径，失败返回 None
        """
        try:
            story_dir = self._get_story_dir(novel_id)
            
            # 创建子目录
            if image_type == "character":
                save_dir = story_dir / "characters"
            elif image_type == "shot":
                # 分镜图片保存到 chapter_{chapter_id}/shots/
                chapter_short = chapter_id[:8] if chapter_id else "unknown"
                save_dir = story_dir / f"chapter_{chapter_short}" / "shots"
            else:
                save_dir = story_dir / "images"
            
            save_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = self._sanitize_filename(character_name)
            filename = f"{safe_name}_{timestamp}.png"
            file_path = save_dir / filename
            
            # 下载图片
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=60.0)
                response.raise_for_status()
                
                # 保存文件
                with open(file_path, 'wb') as f:
                    f.write(response.content)
            
            print(f"[FileStorage] Image saved: {file_path}")
            return str(file_path)
            
        except Exception as e:
            import traceback
            print(f"[FileStorage] Failed to download image from {url}: {e}")
            traceback.print_exc()
            return None
    
    async def download_video(self, url: str, novel_id: str, chapter_id: str,
                            shot_number: int) -> Optional[str]:
        """
        下载视频并保存到指定目录
        
        Args:
            url: 视频URL
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_number: 分镜编号
            
        Returns:
            本地文件路径，失败返回 None
        """
        try:
            story_dir = self._get_story_dir(novel_id)
            
            # 创建章节视频目录
            chapter_short = chapter_id[:8] if chapter_id else "unknown"
            save_dir = story_dir / f"chapter_{chapter_short}" / "videos"
            save_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"shot_{shot_number:03d}_{timestamp}.mp4"
            file_path = save_dir / filename
            
            # 下载视频
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=120.0)
                response.raise_for_status()
                
                with open(file_path, 'wb') as f:
                    f.write(response.content)
            
            print(f"[FileStorage] Video saved: {file_path}")
            return str(file_path)
            
        except Exception as e:
            print(f"[FileStorage] Failed to download video: {e}")
            return None
    
    def get_character_image_path(self, novel_id: str, character_name: str) -> Path:
        """获取角色图片保存路径（用于生成前）"""
        story_dir = self._get_story_dir(novel_id)
        save_dir = story_dir / "characters"
        save_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self._sanitize_filename(character_name)
        return save_dir / f"{safe_name}_{timestamp}.png"
    
    def get_shot_image_path(self, novel_id: str, chapter_id: str, 
                           shot_number: int) -> Path:
        """获取分镜图片保存路径"""
        story_dir = self._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        save_dir = story_dir / f"chapter_{chapter_short}" / "shots"
        save_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return save_dir / f"shot_{shot_number:03d}_{timestamp}.png"
    
    def get_merged_characters_path(self, novel_id: str, chapter_id: str,
                                   shot_number: int, character_names: list = None) -> Path:
        """获取合并角色图保存路径
        
        Args:
            character_names: 角色名列表，用于生成固定文件名。相同角色组合总是生成相同文件名。
        """
        import hashlib
        
        story_dir = self._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        save_dir = story_dir / f"chapter_{chapter_short}" / "merged_characters"
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # 如果有角色名，使用角色名排序后的 hash 生成固定文件名
        if character_names and len(character_names) > 0:
            sorted_names = sorted(character_names)
            names_str = "_".join(sorted_names)
            name_hash = hashlib.md5(names_str.encode('utf-8')).hexdigest()[:8]
            filename = f"shot_{shot_number:03d}_{name_hash}_characters.png"
        else:
            # 没有角色名时使用时间戳（兼容旧逻辑）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"shot_{shot_number:03d}_{timestamp}_characters.png"
        
        return save_dir / filename


# 全局实例
file_storage = FileStorageService()
