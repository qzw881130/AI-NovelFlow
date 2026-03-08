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

    async def download_audio(self, url: str, novel_id: str, character_name: str,
                            audio_type: str = "voice") -> Optional[str]:
        """
        下载音频并保存到指定目录

        Args:
            url: 音频URL (ComfyUI 返回的 view URL)
            novel_id: 小说ID
            character_name: 角色名或文件描述
            audio_type: 音频类型 (voice, etc.)

        Returns:
            本地文件路径，失败返回 None
        """
        try:
            story_dir = self._get_story_dir(novel_id)

            # 创建音频目录
            save_dir = story_dir / "voices"
            save_dir.mkdir(parents=True, exist_ok=True)

            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = self._sanitize_filename(character_name)
            # 从URL中获取扩展名，默认为 .flac
            ext = ".flac"
            if ".mp3" in url.lower():
                ext = ".mp3"
            elif ".wav" in url.lower():
                ext = ".wav"
            filename = f"{safe_name}_{timestamp}{ext}"
            file_path = save_dir / filename

            # 下载音频
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=120.0)
                response.raise_for_status()

                # 保存文件
                with open(file_path, 'wb') as f:
                    f.write(response.content)

            print(f"[FileStorage] Audio saved: {file_path}")
            return str(file_path)

        except Exception as e:
            import traceback
            print(f"[FileStorage] Failed to download audio from {url}: {e}")
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
    
    def get_prop_image_path(self, novel_id: str, prop_name: str) -> Path:
        """获取道具图片保存路径（用于生成前）"""
        story_dir = self._get_story_dir(novel_id)
        save_dir = story_dir / "props"
        save_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self._sanitize_filename(prop_name)
        return save_dir / f"{safe_name}_{timestamp}.png"
    
    def get_shot_image_path(self, novel_id: str, chapter_id: str,
                           shot_number: int, shot_id: str = None) -> Path:
        """获取分镜图片保存路径

        Args:
            novel_id: 小说 ID
            chapter_id: 章节 ID
            shot_number: 分镜序号（用于兼容旧文件）
            shot_id: 分镜 ID（用于新文件命名）
        """
        story_dir = self._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        save_dir = story_dir / f"chapter_{chapter_short}" / "shots"
        save_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 如果有 shot_id，使用 shot_id 命名文件（前 8 位）
        if shot_id:
            return save_dir / f"shot_{shot_id[:8]}_{timestamp}.png"
        return save_dir / f"shot_{shot_number:03d}_{timestamp}.png"
    
    def delete_shot_image(self, novel_id: str, chapter_id: str, shot_number: int, shot_id: str = None) -> bool:
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
            
            # 删除该分镜的所有图片文件
            # 如果有 shot_id，优先使用 shot_id 匹配；否则使用 shot_number 匹配
            if shot_id:
                pattern = f"shot_{shot_id[:8]}_*.png"
            else:
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

    def rename_shot_image_file(self, novel_id: str, chapter_id: str,
                               old_shot_number: int, new_shot_number: int) -> bool:
        """
        重命名分镜图片文件（用于分镜 index 变化时）

        Args:
            novel_id: 小说 ID
            chapter_id: 章节 ID
            old_shot_number: 原分镜序号
            new_shot_number: 新分镜序号

        Returns:
            是否成功重命名
        """
        try:
            story_dir = self._get_story_dir(novel_id)
            chapter_short = chapter_id[:8] if chapter_id else "unknown"
            shots_dir = story_dir / f"chapter_{chapter_short}" / "shots"

            if not shots_dir.exists():
                return True

            # 查找该分镜的所有图片文件
            pattern = f"shot_{old_shot_number:03d}_*.png"
            old_files = list(shots_dir.glob(pattern))

            renamed_count = 0
            for old_file in old_files:
                try:
                    # 新文件名：替换 shot_XXX 部分
                    # 格式：shot_001_20260305_112654.png -> shot_002_20260305_112654.png
                    new_name = old_file.name.replace(f"shot_{old_shot_number:03d}", f"shot_{new_shot_number:03d}", 1)
                    new_file = shots_dir / new_name
                    old_file.rename(new_file)
                    renamed_count += 1
                    print(f"[FileStorage] Renamed shot image: {old_file.name} -> {new_file.name}")
                except Exception as e:
                    print(f"[FileStorage] Failed to rename {old_file}: {e}")

            return renamed_count > 0

        except Exception as e:
            print(f"[FileStorage] Failed to rename shot image file: {e}")
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

            # 检查各素材目录是否存在
            characters_dir = story_dir / "characters"
            scenes_dir = story_dir / "scenes"
            voices_dir = story_dir / "voices"

            # 至少有一个素材目录存在才能打包
            has_materials = (
                chapter_dir.exists() or
                characters_dir.exists() or
                scenes_dir.exists() or
                voices_dir.exists()
            )

            if not has_materials:
                print(f"[FileStorage] No materials found for chapter {chapter_id}")
                return None

            # 创建临时 ZIP 文件
            zip_filename = f"chapter_{chapter_short}_materials.zip"
            zip_path = story_dir / zip_filename

            file_count = 0

            # 打包目录
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 1. 遍历章节目录下的所有文件
                if chapter_dir.exists():
                    for item in chapter_dir.rglob('*'):
                        if item.is_file():
                            arcname = item.relative_to(story_dir)
                            zipf.write(item, arcname)
                            file_count += 1
                            print(f"[FileStorage] Added to zip: {arcname}")

                # 2. 添加小说角色图目录
                if characters_dir.exists():
                    for item in characters_dir.rglob('*'):
                        if item.is_file():
                            arcname = item.relative_to(story_dir)
                            zipf.write(item, arcname)
                            file_count += 1
                            print(f"[FileStorage] Added character to zip: {arcname}")

                # 3. 添加场景图目录
                if scenes_dir.exists():
                    for item in scenes_dir.rglob('*'):
                        if item.is_file():
                            arcname = item.relative_to(story_dir)
                            zipf.write(item, arcname)
                            file_count += 1
                            print(f"[FileStorage] Added scene to zip: {arcname}")

                # 4. 添加台词音频目录（voices）
                if voices_dir.exists():
                    for item in voices_dir.rglob('*'):
                        if item.is_file():
                            arcname = item.relative_to(story_dir)
                            zipf.write(item, arcname)
                            file_count += 1
                            print(f"[FileStorage] Added voice audio to zip: {arcname}")

            if file_count == 0:
                print(f"[FileStorage] No files to zip for chapter {chapter_id}")
                # 删除空的 zip 文件
                import os
                os.remove(zip_path)
                return None

            print(f"[FileStorage] ZIP created: {zip_path} with {file_count} files")
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

    def delete_props_dir(self, novel_id: str) -> bool:
        """
        删除小说的道具图片目录

        Args:
            novel_id: 小说ID

        Returns:
            是否成功删除
        """
        try:
            story_dir = self._get_story_dir(novel_id)
            props_dir = story_dir / "props"

            if props_dir.exists():
                shutil.rmtree(props_dir)
                print(f"[FileStorage] Deleted props directory: {props_dir}")
                return True
            else:
                print(f"[FileStorage] Props directory not found: {props_dir}")
                return True  # 目录不存在也算成功（已经不存在了）

        except Exception as e:
            print(f"[FileStorage] Failed to delete props directory: {e}")
            return False

    def save_shot_audio(
        self,
        novel_id: str,
        shot_index: int,
        character_name: str,
        content: bytes,
        ext: str = ".flac"
    ) -> Path:
        """
        保存分镜台词音频文件

        Args:
            novel_id: 小说ID
            shot_index: 分镜索引（1-based）
            character_name: 角色名称
            content: 音频文件内容
            ext: 文件扩展名（默认 .flac）

        Returns:
            保存的文件路径
        """
        story_dir = self._get_story_dir(novel_id)
        save_dir = story_dir / "shot_audio"
        save_dir.mkdir(parents=True, exist_ok=True)

        # 清理角色名中的特殊字符
        safe_name = self._sanitize_filename(character_name)
        filename = f"shot_{shot_index:03d}_{safe_name}{ext}"
        file_path = save_dir / filename

        # 如果已存在同名文件，先删除
        if file_path.exists():
            file_path.unlink()

        # 保存文件
        with open(file_path, "wb") as f:
            f.write(content)

        print(f"[FileStorage] Shot audio saved: {file_path}")
        return file_path

    def delete_shot_audio(
        self,
        novel_id: str,
        shot_index: int,
        character_name: str
    ) -> bool:
        """
        删除分镜台词音频文件

        Args:
            novel_id: 小说ID
            shot_index: 分镜索引（1-based）
            character_name: 角色名称

        Returns:
            是否成功删除
        """
        try:
            story_dir = self._get_story_dir(novel_id)
            save_dir = story_dir / "shot_audio"

            if not save_dir.exists():
                return True

            # 清理角色名中的特殊字符
            safe_name = self._sanitize_filename(character_name)

            # 查找匹配的音频文件（支持多种格式）
            deleted = False
            for ext in [".flac", ".mp3", ".wav"]:
                pattern = f"shot_{shot_index:03d}_{safe_name}{ext}"
                file_path = save_dir / pattern
                if file_path.exists():
                    file_path.unlink()
                    print(f"[FileStorage] Deleted shot audio: {file_path}")
                    deleted = True

            return True

        except Exception as e:
            print(f"[FileStorage] Failed to delete shot audio: {e}")
            return False

    def delete_shot_audio_files(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int
    ) -> bool:
        """
        删除分镜的所有音频文件（用于删除分镜时）

        Args:
            novel_id: 小说 ID
            chapter_id: 章节 ID
            shot_index: 分镜索引（1-based）

        Returns:
            是否成功删除
        """
        try:
            story_dir = self._get_story_dir(novel_id)
            save_dir = story_dir / "shot_audio"

            if not save_dir.exists():
                return True

            # 删除该分镜的所有音频文件
            deleted_count = 0
            for ext in [".flac", ".mp3", ".wav"]:
                pattern = f"shot_{shot_index:03d}_*{ext}"
                for file_path in save_dir.glob(pattern):
                    file_path.unlink()
                    deleted_count += 1
                    print(f"[FileStorage] Deleted shot audio file: {file_path}")

            return True

        except Exception as e:
            print(f"[FileStorage] Failed to delete shot audio files: {e}")
            return False

    def get_shot_audio_path(
        self,
        novel_id: str,
        shot_index: int,
        character_name: str,
        ext: str = ".flac"
    ) -> Path:
        """
        获取分镜台词音频保存路径

        Args:
            novel_id: 小说ID
            shot_index: 分镜索引（1-based）
            character_name: 角色名称
            ext: 文件扩展名

        Returns:
            音频文件路径
        """
        story_dir = self._get_story_dir(novel_id)
        save_dir = story_dir / "shot_audio"
        save_dir.mkdir(parents=True, exist_ok=True)

        safe_name = self._sanitize_filename(character_name)
        return save_dir / f"shot_{shot_index:03d}_{safe_name}{ext}"

    def save_uploaded_audio_file(
        self,
        novel_id: str,
        character_name: str,
        content: bytes,
        ext: str = ".mp3"
    ) -> Path:
        """
        保存用户上传的音频文件

        Args:
            novel_id: 小说ID
            character_name: 角色名称
            content: 音频文件内容
            ext: 文件扩展名（默认 .mp3）

        Returns:
            保存的文件路径
        """
        story_dir = self._get_story_dir(novel_id)
        save_dir = story_dir / "voices"
        save_dir.mkdir(parents=True, exist_ok=True)

        # 清理角色名中的特殊字符
        safe_name = self._sanitize_filename(character_name)

        # 生成时间戳
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 如果已存在该角色的参考音频，先删除旧的
        for old_ext in [".mp3", ".wav", ".flac", ".ogg", ".m4a"]:
            old_pattern = f"{safe_name}_voice_*{old_ext}"
            for old_file in save_dir.glob(old_pattern):
                try:
                    old_file.unlink()
                    print(f"[FileStorage] Deleted old voice file: {old_file}")
                except Exception as e:
                    print(f"[FileStorage] Failed to delete {old_file}: {e}")

        # 保存新文件
        filename = f"{safe_name}_voice_{timestamp}{ext}"
        file_path = save_dir / filename

        with open(file_path, "wb") as f:
            f.write(content)

        print(f"[FileStorage] Uploaded audio saved: {file_path}")
        return file_path


# 全局实例
file_storage = FileStorageService()
