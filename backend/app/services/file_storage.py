"""
文件存储服务 - 管理小说相关的所有资源文件
"""
import os
import httpx
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
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
            elif image_type == "scene":
                save_dir = story_dir / "scenes"
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
    
    def get_scene_image_path(self, novel_id: str, scene_name: str) -> Path:
        """获取场景图片保存路径（用于生成前）"""
        story_dir = self._get_story_dir(novel_id)
        save_dir = story_dir / "scenes"
        save_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self._sanitize_filename(scene_name)
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
    
    def delete_shot_image(self, novel_id: str, chapter_id: str, shot_number: int) -> bool:
        """
        删除指定分镜的旧图片文件
        
        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_number: 分镜序号
            
        Returns:
            是否成功删除（文件不存在也算成功）
        """
        try:
            story_dir = self._get_story_dir(novel_id)
            chapter_short = chapter_id[:8] if chapter_id else "unknown"
            shots_dir = story_dir / f"chapter_{chapter_short}" / "shots"
            
            if not shots_dir.exists():
                return True
            
            # 查找该分镜的所有旧图片文件
            import glob
            pattern = f"shot_{shot_number:03d}_*.png"
            old_files = list(shots_dir.glob(pattern))
            
            deleted_count = 0
            for old_file in old_files:
                try:
                    old_file.unlink()
                    deleted_count += 1
                    print(f"[FileStorage] Deleted old shot image: {old_file}")
                except Exception as e:
                    print(f"[FileStorage] Failed to delete {old_file}: {e}")
            
            return True
            
        except Exception as e:
            print(f"[FileStorage] Failed to delete shot image: {e}")
            return False
    
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


    def get_transition_video_path(self, novel_id: str, chapter_id: str,
                                  first_video_filename: str, second_video_filename: str) -> Path:
        """获取转场视频保存路径
        
        Args:
            first_video_filename: 前一个视频的文件名（不含扩展名）
            second_video_filename: 后一个视频的文件名（不含扩展名）
            
        Returns:
            转场视频保存路径
        """
        story_dir = self._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        save_dir = story_dir / f"chapter_{chapter_short}" / "transition-videos"
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # 文件名格式：trans-video-{前一个视频文件名}-{后一视频文件名}.mp4
        filename = f"trans-video-{first_video_filename}-{second_video_filename}.mp4"
        return save_dir / filename
    
    def get_video_frame_path(self, video_path: str, frame_type: str = "first") -> Path:
        """获取视频帧图片保存路径
        
        Args:
            video_path: 视频文件路径
            frame_type: 帧类型 ("first" 或 "last")
            
        Returns:
            帧图片保存路径
        """
        video_path = Path(video_path)
        # 在与视频相同目录创建 frames 子目录
        frames_dir = video_path.parent / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用视频文件名 + 帧类型命名
        video_name = video_path.stem
        filename = f"{video_name}_{frame_type}_frame.png"
        return frames_dir / filename
    
    async def extract_video_frames(self, video_path: str) -> dict:
        """提取视频的首帧和尾帧
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            {"first": 首帧路径, "last": 尾帧路径, "success": bool, "message": str}
        """
        import cv2
        import asyncio
        
        try:
            video_path = Path(video_path)
            if not video_path.exists():
                return {"success": False, "message": f"视频文件不存在: {video_path}"}
            
            # 获取帧保存路径
            first_frame_path = self.get_video_frame_path(str(video_path), "first")
            last_frame_path = self.get_video_frame_path(str(video_path), "last")
            
            # 如果帧已经提取过，直接返回
            if first_frame_path.exists() and last_frame_path.exists():
                return {
                    "success": True,
                    "first": str(first_frame_path),
                    "last": str(last_frame_path),
                    "message": "帧已存在"
                }
            
            # 使用 asyncio 在线程池中执行 OpenCV 操作
            def _extract():
                cap = cv2.VideoCapture(str(video_path))
                if not cap.isOpened():
                    return {"success": False, "message": "无法打开视频文件"}
                
                # 获取视频总帧数
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if total_frames <= 0:
                    cap.release()
                    return {"success": False, "message": "视频没有帧"}
                
                result = {"success": True}
                
                # 提取首帧
                if not first_frame_path.exists():
                    ret, frame = cap.read()
                    if ret:
                        cv2.imwrite(str(first_frame_path), frame)
                        result["first"] = str(first_frame_path)
                    else:
                        result["success"] = False
                        result["message"] = "无法读取首帧"
                        cap.release()
                        return result
                else:
                    result["first"] = str(first_frame_path)
                
                # 提取尾帧
                if not last_frame_path.exists():
                    cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
                    ret, frame = cap.read()
                    if ret:
                        cv2.imwrite(str(last_frame_path), frame)
                        result["last"] = str(last_frame_path)
                    else:
                        # 如果无法读取最后一帧，尝试倒数第二帧
                        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames - 2))
                        ret, frame = cap.read()
                        if ret:
                            cv2.imwrite(str(last_frame_path), frame)
                            result["last"] = str(last_frame_path)
                        else:
                            result["success"] = False
                            result["message"] = "无法读取尾帧"
                else:
                    result["last"] = str(last_frame_path)
                
                cap.release()
                result["message"] = "帧提取成功"
                return result
            
            # 在线程池中执行
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _extract)
            
            print(f"[FileStorage] Video frames extracted: first={first_frame_path.exists()}, last={last_frame_path.exists()}")
            return result
            
        except Exception as e:
            import traceback
            print(f"[FileStorage] Failed to extract frames: {e}")
            traceback.print_exc()
            return {"success": False, "message": f"帧提取失败: {str(e)}"}


    def zip_chapter_materials(self, novel_id: str, chapter_id: str) -> Optional[str]:
        """
        打包章节素材为 ZIP 文件
        
        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            
        Returns:
            ZIP 文件路径，失败返回 None
        """
        try:
            import zipfile
            
            story_dir = self._get_story_dir(novel_id)
            chapter_short = chapter_id[:8] if chapter_id else "unknown"
            chapter_dir = story_dir / f"chapter_{chapter_short}"
            
            if not chapter_dir.exists():
                print(f"[FileStorage] Chapter directory not found: {chapter_dir}")
                return None
            
            # 创建临时 ZIP 文件
            zip_filename = f"chapter_{chapter_short}_materials.zip"
            zip_path = story_dir / zip_filename
            
            # 打包目录
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 1. 遍历章节目录下的所有文件
                for item in chapter_dir.rglob('*'):
                    if item.is_file():
                        # 计算相对路径（相对于 story_dir）
                        arcname = item.relative_to(story_dir)
                        zipf.write(item, arcname)
                        print(f"[FileStorage] Added to zip: {arcname}")
                
                # 2. 添加小说角色图目录
                characters_dir = story_dir / "characters"
                if characters_dir.exists():
                    for item in characters_dir.rglob('*'):
                        if item.is_file():
                            arcname = item.relative_to(story_dir)
                            zipf.write(item, arcname)
                            print(f"[FileStorage] Added character to zip: {arcname}")
            
            print(f"[FileStorage] ZIP created: {zip_path}")
            return str(zip_path)
            
        except Exception as e:
            import traceback
            print(f"[FileStorage] Failed to zip chapter materials: {e}")
            traceback.print_exc()
            return None


    async def merge_videos(self, video_paths: List[str], output_path: str, 
                          transition_videos: List[str] = None) -> Dict[str, Any]:
        """
        合并多个视频文件（使用 ffmpeg）
        
        Args:
            video_paths: 视频文件路径列表（分镜视频）
            output_path: 输出文件路径
            transition_videos: 转场视频路径列表（可选），长度应为 len(video_paths) - 1
            
        Returns:
            {
                "success": bool,
                "output_path": str,
                "message": str
            }
        """
        try:
            import subprocess
            import asyncio
            import tempfile
            import os
            
            if not video_paths or len(video_paths) == 0:
                return {"success": False, "message": "没有视频文件"}
            
            # 构建视频列表（插入转场视频）
            final_video_list = []
            for i, video_path in enumerate(video_paths):
                if Path(video_path).exists():
                    final_video_list.append(video_path)
                # 在每个视频后插入转场（除了最后一个）
                if transition_videos and i < len(transition_videos) and i < len(video_paths) - 1:
                    trans_path = transition_videos[i]
                    if trans_path and Path(trans_path).exists():
                        final_video_list.append(trans_path)
            
            if len(final_video_list) == 0:
                return {"success": False, "message": "没有有效的视频文件"}
            
            print(f"[FileStorage] Merging {len(final_video_list)} videos: {final_video_list}")
            
            # 创建临时文件列表
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                concat_file = f.name
                for video_path in final_video_list:
                    # 使用 file 协议，需要处理路径中的特殊字符
                    escaped_path = video_path.replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")
            
            try:
                # 使用 ffmpeg 合并视频
                # -f concat: 使用 concat 协议
                # -safe 0: 允许不安全的文件路径
                # -c copy: 直接复制流，不重新编码（速度快，质量无损）
                cmd = [
                    'ffmpeg',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_file,
                    '-c', 'copy',
                    '-y',  # 覆盖输出文件
                    output_path
                ]
                
                print(f"[FileStorage] Running ffmpeg: {' '.join(cmd)}")
                
                # 在线程池中执行
                loop = asyncio.get_event_loop()
                
                def _run_ffmpeg():
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True
                    )
                    return result
                
                result = await loop.run_in_executor(None, _run_ffmpeg)
                
                # 清理临时文件
                os.unlink(concat_file)
                
                if result.returncode != 0:
                    print(f"[FileStorage] FFmpeg error: {result.stderr}")
                    return {
                        "success": False,
                        "message": f"视频合并失败: {result.stderr[:200]}"
                    }
                
                # 检查输出文件是否存在
                if not Path(output_path).exists():
                    return {
                        "success": False,
                        "message": "输出文件未生成"
                    }
                
                print(f"[FileStorage] Video merged successfully: {output_path}")
                return {
                    "success": True,
                    "output_path": output_path,
                    "message": f"合并完成，共 {len(final_video_list)} 个视频片段"
                }
                
            except Exception as e:
                # 清理临时文件
                if os.path.exists(concat_file):
                    os.unlink(concat_file)
                raise e
            
        except Exception as e:
            import traceback
            print(f"[FileStorage] Failed to merge videos: {e}")
            traceback.print_exc()
            return {"success": False, "message": f"合并失败: {str(e)}"}


    def delete_chapter_directory(self, novel_id: str, chapter_id: str) -> bool:
        """
        删除章节的整个目录（包括所有图片、视频、转场等）
        
        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            
        Returns:
            是否成功删除
        """
        try:
            story_dir = self._get_story_dir(novel_id)
            chapter_short = chapter_id[:8] if chapter_id else "unknown"
            chapter_dir = story_dir / f"chapter_{chapter_short}"
            
            if chapter_dir.exists():
                shutil.rmtree(chapter_dir)
                print(f"[FileStorage] Deleted chapter directory: {chapter_dir}")
                return True
            else:
                print(f"[FileStorage] Chapter directory not found: {chapter_dir}")
                return True  # 目录不存在也算成功（已经不存在了）
                
        except Exception as e:
            print(f"[FileStorage] Failed to delete chapter directory: {e}")
            return False

    def delete_characters_dir(self, novel_id: str) -> bool:
        """
        删除小说的角色图片目录
        
        Args:
            novel_id: 小说ID
            
        Returns:
            是否成功删除
        """
        try:
            story_dir = self._get_story_dir(novel_id)
            characters_dir = story_dir / "characters"
            
            if characters_dir.exists():
                shutil.rmtree(characters_dir)
                print(f"[FileStorage] Deleted characters directory: {characters_dir}")
                return True
            else:
                print(f"[FileStorage] Characters directory not found: {characters_dir}")
                return True  # 目录不存在也算成功（已经不存在了）
                
        except Exception as e:
            print(f"[FileStorage] Failed to delete characters directory: {e}")
            return False
    
    def delete_scenes_dir(self, novel_id: str) -> bool:
        """
        删除小说的场景图片目录
        
        Args:
            novel_id: 小说ID
            
        Returns:
            是否成功删除
        """
        try:
            story_dir = self._get_story_dir(novel_id)
            scenes_dir = story_dir / "scenes"
            
            if scenes_dir.exists():
                shutil.rmtree(scenes_dir)
                print(f"[FileStorage] Deleted scenes directory: {scenes_dir}")
                return True
            else:
                print(f"[FileStorage] Scenes directory not found: {scenes_dir}")
                return True  # 目录不存在也算成功（已经不存在了）
                
        except Exception as e:
            print(f"[FileStorage] Failed to delete scenes directory: {e}")
            return False


# 全局实例
file_storage = FileStorageService()
