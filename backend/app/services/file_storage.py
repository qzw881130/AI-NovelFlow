"""
文件存储服务 - 管理小说相关的所有资源文件
"""
import os
import hashlib
import json
import httpx
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Awaitable
from datetime import datetime

from app.utils.path_utils import url_to_local_path, get_storage_root


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
            self.base_dir = Path(get_storage_root())
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

    def get_video_merge_signature(self, mode: str, segments: List[Dict[str, str]]) -> str:
        """根据实际参与合并的视频内容和顺序生成缓存签名。"""
        from app.services.rendered_subtitles import sidecar, fingerprint
        manifest = []
        for segment in segments:
            content_hash = hashlib.sha256()
            with open(segment["path"], "rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    content_hash.update(chunk)
            manifest.append({
                "kind": segment["kind"],
                "key": segment["key"],
                "sha256": content_hash.hexdigest(),
                "subtitle_sha256": fingerprint(sidecar(segment["path"])) if sidecar(segment["path"]).is_file() else None,
            })

        payload = json.dumps(
            {"version": 3, "mode": mode, "segments": manifest},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    
    async def download_image(self, url: str, novel_id: str, character_name: str,
                            image_type: str = "character", chapter_id: str = None, *, destination: Optional[Path] = None) -> Optional[str]:
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
        if destination is not None:
            try:
                file_path = Path(destination).resolve()
                if not file_path.is_relative_to(self.base_dir.resolve()) or file_path == self.base_dir.resolve():
                    raise ValueError("Artifact destination must be inside file storage")
                file_path.parent.mkdir(parents=True, exist_ok=True)
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, timeout=60.0)
                    response.raise_for_status()
                    with open(file_path, "xb") as output:
                        output.write(response.content)
                return str(file_path)
            except Exception as exc:
                print(f"[FileStorage] Failed to archive image: {exc}")
                return None
        try:
            story_dir = self._get_story_dir(novel_id)

            # 创建子目录
            if image_type == "character":
                save_dir = story_dir / "characters"
            elif image_type == "character_edit":
                save_dir = story_dir / "characters" / "edits"
            elif image_type == "scene":
                save_dir = story_dir / "scenes"
            elif image_type == "scene_edit":
                save_dir = story_dir / "scenes" / "edits"
            elif image_type == "prop_edit":
                save_dir = story_dir / "props" / "edits"
            elif image_type == "shot":
                # 分镜图片保存到 chapter_{chapter_id}/shots/
                chapter_short = chapter_id[:8] if chapter_id else "unknown"
                save_dir = story_dir / f"chapter_{chapter_short}" / "shots"
            elif image_type == "shot_edit":
                save_dir = story_dir / "shots" / "edits"
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
                            shot_number: int, *, destination: Optional[Path] = None) -> Optional[str]:
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
        if destination is not None:
            try:
                file_path = Path(destination).resolve()
                if not file_path.is_relative_to(self.base_dir.resolve()) or file_path == self.base_dir.resolve():
                    raise ValueError("Artifact destination must be inside file storage")
                file_path.parent.mkdir(parents=True, exist_ok=True)
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, timeout=120.0)
                    response.raise_for_status()
                    with open(file_path, "xb") as output:
                        output.write(response.content)
                return str(file_path)
            except Exception as exc:
                print(f"[FileStorage] Failed to archive video: {exc}")
                return None
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

    def delete_shot_video(self, novel_id: str, chapter_id: str, shot_number: int) -> bool:
        """删除指定分镜的旧视频文件"""
        try:
            story_dir = self._get_story_dir(novel_id)
            chapter_short = chapter_id[:8] if chapter_id else "unknown"
            videos_dir = story_dir / f"chapter_{chapter_short}" / "videos"

            if not videos_dir.exists():
                return True

            old_files = list(videos_dir.glob(f"shot_{shot_number:03d}_*.mp4"))
            for old_file in old_files:
                try:
                    old_file.unlink()
                    print(f"[FileStorage] Deleted old shot video: {old_file}")
                except Exception as e:
                    print(f"[FileStorage] Failed to delete {old_file}: {e}")

            return True
        except Exception as e:
            print(f"[FileStorage] Failed to delete shot video: {e}")
            return False
    
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

    def get_merged_props_path(self, novel_id: str, chapter_id: str,
                              shot_number: int, prop_names: list = None) -> Path:
        """获取合并道具图保存路径"""
        import hashlib

        story_dir = self._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        save_dir = story_dir / f"chapter_{chapter_short}" / "merged_props"
        save_dir.mkdir(parents=True, exist_ok=True)

        if prop_names and len(prop_names) > 0:
            sorted_names = sorted(prop_names)
            names_str = "_".join(sorted_names)
            name_hash = hashlib.md5(names_str.encode('utf-8')).hexdigest()[:8]
            filename = f"shot_{shot_number:03d}_{name_hash}_props.png"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"shot_{shot_number:03d}_{timestamp}_props.png"

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


    def zip_chapter_materials(self, novel_id: str, chapter_id: str, shots: Optional[List[Any]] = None) -> Optional[str]:
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
                voices_dir.exists() or
                bool(shots)
            )

            if not has_materials:
                print(f"[FileStorage] No materials found for chapter {chapter_id}")
                return None

            # 创建临时 ZIP 文件
            zip_filename = f"chapter_{chapter_short}_materials.zip"
            zip_path = story_dir / zip_filename

            file_count = 0
            added_files = set()

            def add_file(zipf, source: Optional[str], arcname: str) -> bool:
                nonlocal file_count
                if not source:
                    return False
                source_path = Path(source)
                if not source_path.exists() or not source_path.is_file() or arcname in added_files:
                    return False
                zipf.write(source_path, arcname)
                added_files.add(arcname)
                file_count += 1
                print(f"[FileStorage] Added to zip: {arcname}")
                return True

            def resolve_material_path(value: Optional[str]) -> Optional[str]:
                if not value:
                    return None
                local_path = url_to_local_path(value)
                if local_path:
                    return local_path
                path = Path(value)
                if path.exists():
                    return str(path)
                return None

            def parse_json_field(value: Any, default: Any) -> Any:
                if value is None:
                    return default
                if isinstance(value, (list, dict)):
                    return value
                if isinstance(value, str):
                    try:
                        return json.loads(value)
                    except json.JSONDecodeError:
                        return default
                return default

            def get_attr(obj: Any, *names: str) -> Any:
                for name in names:
                    if isinstance(obj, dict) and name in obj:
                        return obj.get(name)
                    if hasattr(obj, name):
                        return getattr(obj, name)
                return None

            def first_present(*values: Any) -> Any:
                for value in values:
                    if value:
                        return value
                return None

            def add_manifest_material(zipf, manifest_items: List[Dict[str, Any]], source: Optional[str], arcname: str, kind: str, label: str) -> Optional[str]:
                if add_file(zipf, source, arcname):
                    manifest_items.append({"kind": kind, "label": label, "path": arcname})
                    return arcname
                return None

            # 打包目录
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                manifest = {
                    "version": 2,
                    "novel_id": novel_id,
                    "chapter_id": chapter_id,
                    "generated_at": datetime.now().isoformat(),
                    "shots": [],
                    "chapter_materials": [],
                }

                # 1. 按当前数据库 Shot 数据组织新素材结构
                for shot in shots or []:
                    shot_index = int(get_attr(shot, "index") or 0)
                    shot_label = f"shot_{shot_index:03d}" if shot_index else f"shot_{get_attr(shot, 'id') or 'unknown'}"
                    plan = parse_json_field(get_attr(shot, "video_director_plan", "videoDirectorPlan"), {})
                    legacy_keyframes = parse_json_field(get_attr(shot, "keyframes"), [])
                    keyframes = plan.get("keyframes") or []
                    shot_manifest = {
                        "shot_id": get_attr(shot, "id"),
                        "index": shot_index,
                        "duration": get_attr(shot, "duration"),
                        "selected_mode": plan.get("selected_mode"),
                        "recommended_mode": plan.get("recommended_mode"),
                        "video_description": get_attr(shot, "video_description"),
                        "description": get_attr(shot, "description"),
                        "materials": [],
                        "keyframes": [],
                        "clips": [],
                    }

                    primary_path = resolve_material_path(get_attr(shot, "image_url", "imageUrl") or get_attr(shot, "image_path", "imagePath"))
                    if primary_path:
                        ext = Path(primary_path).suffix or ".png"
                        add_manifest_material(zipf, shot_manifest["materials"], primary_path, f"shot_materials/{shot_label}/primary_image{ext}", "primary_image", "主分镜图")

                    video_path = resolve_material_path(get_attr(shot, "video_url", "videoUrl") or get_attr(shot, "video_path", "videoPath"))
                    if video_path:
                        ext = Path(video_path).suffix or ".mp4"
                        add_manifest_material(zipf, shot_manifest["materials"], video_path, f"shot_materials/{shot_label}/videos/shot_video{ext}", "shot_video", "Shot 视频")

                    for keyframe in keyframes:
                        keyframe_index = keyframe.get("index")
                        image_value = first_present(
                            keyframe.get("image_url"),
                            keyframe.get("imageUrl"),
                            keyframe.get("image_path"),
                            keyframe.get("imagePath"),
                            keyframe.get("local_path"),
                            keyframe.get("localPath"),
                            keyframe.get("generated_image_url"),
                            keyframe.get("generatedImageUrl"),
                        )
                        if keyframe.get("role") == "START" and not image_value:
                            image_value = primary_path
                        if not image_value:
                            legacy_keyframe = next((item for item in legacy_keyframes if int(item.get("plan_keyframe_index") or item.get("planKeyframeIndex") or -1) == int(keyframe_index or -2)), None)
                            if legacy_keyframe:
                                image_value = first_present(
                                    legacy_keyframe.get("image_url"),
                                    legacy_keyframe.get("imageUrl"),
                                    legacy_keyframe.get("image_path"),
                                    legacy_keyframe.get("imagePath"),
                                    legacy_keyframe.get("local_path"),
                                    legacy_keyframe.get("localPath"),
                                )
                        image_path = resolve_material_path(image_value)
                        keyframe_manifest = {
                            "index": keyframe_index,
                            "role": keyframe.get("role"),
                            "time_seconds": keyframe.get("time_seconds"),
                            "description": keyframe.get("description"),
                            "image_path": None,
                        }
                        if image_path:
                            ext = Path(image_path).suffix or ".png"
                            role = (keyframe.get("role") or "KF").lower()
                            arcname = f"shot_materials/{shot_label}/keyframes/KF{int(keyframe_index or 0):03d}_{role}{ext}"
                            if add_file(zipf, image_path, arcname):
                                keyframe_manifest["image_path"] = arcname
                        shot_manifest["keyframes"].append(keyframe_manifest)

                    seen_clip_keys = set()
                    for clip in (plan.get("window_plans") or []) + (plan.get("clips") or []):
                        clip_index = int(clip.get("window_index") or clip.get("clip_index") or 0)
                        clip_key = clip.get("window_index") or clip.get("clip_index") or clip_index
                        if clip_key in seen_clip_keys:
                            continue
                        seen_clip_keys.add(clip_key)
                        clip_path = resolve_material_path(first_present(
                            clip.get("video_url"),
                            clip.get("videoUrl"),
                            clip.get("local_path"),
                            clip.get("localPath"),
                            clip.get("source_video_url"),
                            clip.get("sourceVideoUrl"),
                        ))
                        clip_manifest = {
                            "clip_index": clip_index,
                            "start_time": clip.get("start_time"),
                            "end_time": clip.get("end_time"),
                            "keyframe_indexes": clip.get("keyframe_indexes") or [],
                            "workflow_type": clip.get("workflow_type"),
                            "status": clip.get("status"),
                            "audio_status": clip.get("audio_status") or clip.get("audioStatus"),
                            "audio_timeline_id": clip.get("audio_timeline_id") or clip.get("audioTimelineId"),
                            "clip_audio_duration": clip.get("clip_audio_duration") or clip.get("clipAudioDuration"),
                            "speaker_timeline": clip.get("speaker_timeline") or clip.get("speakerTimeline") or [],
                            "video_path": None,
                            "drive_audio_path": None,
                            "final_audio_path": None,
                            "clip_audio_manifest_path": None,
                        }
                        if clip_path:
                            ext = Path(clip_path).suffix or ".mp4"
                            arcname = f"shot_materials/{shot_label}/videos/clips/C{clip_index:03d}{ext}"
                            if add_file(zipf, clip_path, arcname):
                                clip_manifest["video_path"] = arcname
                        drive_audio_path = resolve_material_path(first_present(clip.get("drive_audio_path"), clip.get("driveAudioPath"), clip.get("drive_audio_url"), clip.get("driveAudioUrl")))
                        if drive_audio_path:
                            ext = Path(drive_audio_path).suffix or ".wav"
                            arcname = f"shot_materials/{shot_label}/audio/clips/C{clip_index:03d}_drive_audio{ext}"
                            if add_file(zipf, drive_audio_path, arcname):
                                clip_manifest["drive_audio_path"] = arcname
                        final_audio_path = resolve_material_path(first_present(clip.get("final_audio_path"), clip.get("finalAudioPath"), clip.get("final_audio_url"), clip.get("finalAudioUrl")))
                        if final_audio_path:
                            ext = Path(final_audio_path).suffix or ".wav"
                            arcname = f"shot_materials/{shot_label}/audio/clips/C{clip_index:03d}_final_audio{ext}"
                            if add_file(zipf, final_audio_path, arcname):
                                clip_manifest["final_audio_path"] = arcname
                        clip_audio_manifest_path = resolve_material_path(first_present(clip.get("clip_audio_manifest_path"), clip.get("clipAudioManifestPath")))
                        if clip_audio_manifest_path:
                            arcname = f"shot_materials/{shot_label}/audio/clips/C{clip_index:03d}_clip_audio_manifest.json"
                            if add_file(zipf, clip_audio_manifest_path, arcname):
                                clip_manifest["clip_audio_manifest_path"] = arcname
                        if clip_manifest["speaker_timeline"]:
                            speaker_arcname = f"shot_materials/{shot_label}/audio/clips/C{clip_index:03d}_speaker_timeline.json"
                            zipf.writestr(speaker_arcname, json.dumps(clip_manifest["speaker_timeline"], ensure_ascii=False, indent=2))
                            clip_manifest["speaker_timeline_path"] = speaker_arcname
                            file_count += 1
                        for ref_index, reference in enumerate(clip.get("reference_images") or clip.get("referenceImages") or [], 1):
                            ref_value = reference.get("url") if isinstance(reference, dict) else reference
                            ref_path = resolve_material_path(ref_value)
                            if ref_path:
                                ext = Path(ref_path).suffix or ".png"
                                ref_arcname = f"shot_materials/{shot_label}/videos/clips/C{clip_index:03d}_reference_{ref_index:02d}{ext}"
                                if add_file(zipf, ref_path, ref_arcname):
                                    clip_manifest.setdefault("reference_image_paths", []).append(ref_arcname)
                        shot_manifest["clips"].append(clip_manifest)

                    merged_path = resolve_material_path(plan.get("merged_video_url"))
                    if merged_path:
                        ext = Path(merged_path).suffix or ".mp4"
                        add_manifest_material(zipf, shot_manifest["materials"], merged_path, f"shot_materials/{shot_label}/videos/merged_video{ext}", "merged_video", "多 Clip 合并视频")

                    manifest["shots"].append(shot_manifest)

                # 2. 遍历章节目录下的所有文件，保留原始素材目录
                if chapter_dir.exists():
                    for item in chapter_dir.rglob('*'):
                        if item.is_file():
                            arcname = item.relative_to(story_dir)
                            add_file(zipf, str(item), str(arcname))

                # 3. 添加小说角色图目录
                if characters_dir.exists():
                    for item in characters_dir.rglob('*'):
                        if item.is_file():
                            arcname = item.relative_to(story_dir)
                            if add_file(zipf, str(item), str(arcname)):
                                manifest["chapter_materials"].append({"kind": "character", "path": str(arcname)})

                # 4. 添加场景图目录
                if scenes_dir.exists():
                    for item in scenes_dir.rglob('*'):
                        if item.is_file():
                            arcname = item.relative_to(story_dir)
                            if add_file(zipf, str(item), str(arcname)):
                                manifest["chapter_materials"].append({"kind": "scene", "path": str(arcname)})

                # 5. 添加台词音频目录（voices）
                if voices_dir.exists():
                    for item in voices_dir.rglob('*'):
                        if item.is_file():
                            arcname = item.relative_to(story_dir)
                            if add_file(zipf, str(item), str(arcname)):
                                manifest["chapter_materials"].append({"kind": "voice", "path": str(arcname)})

                zipf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                file_count += 1

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


    async def _run_merge_process(self, cmd, on_time=None):
        """Drain both pipes while reporting FFmpeg's output timeline, not wall time."""
        import asyncio
        import subprocess

        if on_time is not None:
            cmd = [cmd[0], '-progress', 'pipe:1', '-nostats', *cmd[1:]]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )

        async def read_stdout():
            if on_time is None:
                return await process.stdout.read()
            while line := await process.stdout.readline():
                key, _, value = line.strip().partition(b'=')
                if key == b'out_time_us':
                    try:
                        seconds = max(0, int(value)) / 1_000_000
                    except ValueError:
                        continue
                    await on_time(seconds)
            return b''

        async def read_stderr():
            diagnostic = b''
            while chunk := await process.stderr.read(65536):
                diagnostic = (diagnostic + chunk)[-65536:]
            return diagnostic

        readers = [asyncio.create_task(read_stdout()), asyncio.create_task(read_stderr())]
        try:
            stdout, stderr = await asyncio.gather(*readers)
            await process.wait()
            return subprocess.CompletedProcess(cmd, process.returncode, stdout.decode(errors='replace'), stderr.decode(errors='replace'))
        finally:
            # Reap before the caller removes files, including on callback failure/cancellation.
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            await process.wait()

    async def merge_videos(self, video_paths: List[str], output_path: str,
                          transition_videos: List[str] = None,
                          progress_callback: Optional[Callable[[float, str], Awaitable[None]]] = None) -> Dict[str, Any]:
        """
        合并多个视频文件（使用 ffmpeg）
        
        Args:
            video_paths: 视频文件路径列表（分镜视频）
            output_path: 输出文件路径
            transition_videos: 转场视频路径列表（可选），长度应为 len(video_paths) - 1
            progress_callback: Awaited (percent, step); monotonic 0..100. Source validation
                0..15, normalization 15..65, encoding 65..95, final validation 95,
                atomic publication 99, published 100. Unknown durations advance only
                on completion. Callback failures abort; cancellation propagates.
            
        Returns:
            {
                "success": bool,
                "output_path": str,
                "message": str
            }
        """
        try:
            import tempfile
            import os
            import json
            from fractions import Fraction
            from math import ceil

            last_progress = 0.0

            async def report(percent, step):
                nonlocal last_progress
                last_progress = max(last_progress, min(100.0, percent))
                if progress_callback is not None:
                    await progress_callback(last_progress, step)
            
            if not video_paths or len(video_paths) == 0:
                return {"success": False, "message": "没有视频文件"}
            
            # 构建视频列表（插入转场视频）
            final_video_list = []
            for i, video_path in enumerate(video_paths):
                if not Path(video_path).is_file():
                    return {"success": False, "message": f"视频文件不存在: {video_path}"}
                final_video_list.append(video_path)
                # 在每个视频后插入转场（除了最后一个）
                if transition_videos and i < len(transition_videos) and i < len(video_paths) - 1:
                    trans_path = transition_videos[i]
                    if trans_path and Path(trans_path).exists():
                        final_video_list.append(trans_path)
            
            if len(final_video_list) == 0:
                return {"success": False, "message": "没有有效的视频文件"}
            
            print(f"[FileStorage] Merging {len(final_video_list)} videos: {final_video_list}")

            async def _get_video_info(video_path: str, count_frames: bool = False) -> Dict[str, Any]:
                result = await self._run_merge_process(
                    [
                        'ffprobe',
                        '-v', 'error',
                        *(['-count_frames'] if count_frames else []),
                        '-show_entries', 'stream=codec_type,width,height,start_time,duration_ts,time_base,nb_read_frames:format=duration',
                        '-of', 'json',
                        video_path,
                    ],
                )
                if result.returncode != 0:
                    raise RuntimeError(f"ffprobe failed for {video_path}: {result.stderr}")

                data = json.loads(result.stdout or '{}')
                streams = data.get('streams', [])
                if not streams:
                    raise RuntimeError(f"No video stream found in {video_path}")

                video_stream = next((stream for stream in streams if stream.get('codec_type') == 'video'), None)
                if not video_stream:
                    raise RuntimeError(f"No video stream found in {video_path}")

                audio_stream = next((stream for stream in streams if stream.get('codec_type') == 'audio'), None)
                return {
                    'width': int(video_stream.get('width') or 0),
                    'height': int(video_stream.get('height') or 0),
                    'video': video_stream,
                    'audio': audio_stream,
                    'duration': (data.get('format') or {}).get('duration'),
                }

            async def _validate_video_decode(video_path: str):
                result = await self._run_merge_process(
                    ['ffmpeg', '-v', 'error', '-xerror', '-i', video_path,
                     '-map', '0:v:0', '-map', '0:a:0?', '-f', 'null', '-'],
                )
                stderr = (result.stderr or '').strip()
                if result.returncode != 0 or stderr:
                    raise RuntimeError(f"视频解码校验失败 ({video_path}): {stderr[:300] or f'ffmpeg exit {result.returncode}'}")

            # Keep candidates on the destination filesystem for atomic publication.
            temp_normalized_dir = tempfile.mkdtemp(prefix='.novelflow_merge_', dir=str(Path(output_path).resolve().parent))
            candidate_path = os.path.join(temp_normalized_dir, 'merged.mp4')
            normalized_paths = []
            segment_frames = []
            from app.services.rendered_subtitles import load, fingerprint, compose, publish
            source_hashes = [fingerprint(path) for path in final_video_list]
            snapshots = [load(path) for path in final_video_list]
            media_segments = []

            # 创建临时文件列表
            try:
                frozen_video_list=[]
                for index,(video_path,expected_hash) in enumerate(zip(final_video_list,source_hashes)):
                    suffix=Path(video_path).suffix or '.mp4';frozen_path=os.path.join(temp_normalized_dir,f'frozen_{index:03d}{suffix}')
                    shutil.copyfile(video_path,frozen_path)
                    if fingerprint(frozen_path)!=expected_hash:raise RuntimeError('Source media changed while freezing merge inputs')
                    frozen_video_list.append(frozen_path)
                target_info = await _get_video_info(frozen_video_list[0])
                target_width,target_height=target_info['width'],target_info['height']
                if target_width<=0 or target_height<=0:return {"success":False,"message":"无法读取目标视频分辨率"}
                # Reject corrupt sources before a decoder can conceal their errors.
                count = len(final_video_list)
                for index, video_path in enumerate(frozen_video_list):
                    await report(15 * index / count, f"校验源视频 {index + 1}/{count}")
                    await _validate_video_decode(video_path)
                    await report(15 * (index + 1) / count, f"校验源视频 {index + 1}/{count}")

                for index, video_path in enumerate(frozen_video_list):
                    normalized_path = os.path.join(temp_normalized_dir, f'normalized_{index:03d}.mov')
                    video_info = await _get_video_info(video_path)
                    if not video_info['audio']:
                        snapshots[index] = {"cues": [], "lineage": {"kind": "probed_no_audio"},
                                            "media_sha256": source_hashes[index]}
                    video_start = Fraction(video_info['video'].get('start_time') or '0')
                    audio_start = Fraction((video_info['audio'] or {}).get('start_time') or video_start)
                    origin = min(video_start, audio_start)
                    # Measure the common A/V timeline, including retained start offsets.
                    durations = []
                    for stream in (video_info['video'], video_info['audio']):
                        if stream and stream.get('duration_ts') is not None and stream.get('time_base'):
                            try:
                                durations.append(float(Fraction(stream.get('start_time') or origin) - origin
                                                       + int(stream['duration_ts']) * Fraction(stream['time_base'])))
                            except (ValueError, TypeError, ZeroDivisionError):
                                pass
                    try:
                        duration = max(durations) if durations else float(video_info['duration'] or 0)
                    except (ValueError, TypeError):
                        duration = 0
                    step = f"标准化视频 {index + 1}/{count}"
                    await report(15 + 50 * index / count, step)

                    async def normalize_progress(seconds):
                        fraction = min(0.99, seconds / duration) if duration > 0 else 0
                        await report(15 + 50 * (index + fraction) / count, step)
                    normalize_cmd = [
                        'ffmpeg',
                        '-xerror',
                        '-i', video_path,
                        '-map', '0:v:0', '-map', '0:a:0?',
                    ]

                    normalize_cmd.extend([
                        '-vf', f'setpts=PTS-STARTPTS+({video_start - origin})/TB,scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=24:start_time=0:eof_action=pass,format=yuv420p',
                        '-c:v', 'libx264',
                        '-preset', 'medium',
                        '-crf', '18',
                        '-c:a', 'pcm_s16le',
                        '-ar', '48000',
                        '-ac', '2',
                    ])

                    if video_info['audio']:
                        # Fill timestamp gaps without changing speech speed; retain A/V offsets.
                        normalize_cmd.extend([
                            '-af', f'asetpts=PTS-STARTPTS+({audio_start - origin})/TB,aresample=48000:async=1:first_pts=0',
                        ])

                    normalize_cmd.extend([
                        '-movflags', '+faststart',
                        '-y',
                        normalized_path,
                    ])

                    print(f"[FileStorage] Normalizing video: {' '.join(normalize_cmd)}")

                    normalize_result = await self._run_merge_process(normalize_cmd, normalize_progress)
                    if normalize_result.returncode != 0:
                        print(f"[FileStorage] Normalize error: {normalize_result.stderr}")
                        return {
                            "success": False,
                            "message": f"视频标准化失败: {normalize_result.stderr[:200]}"
                        }

                    normalized_paths.append(normalized_path)
                    normalized_info = await _get_video_info(normalized_path, count_frames=True)
                    frames = int(normalized_info['video']['nb_read_frames'])
                    if frames <= 0:
                        raise RuntimeError(f"No normalized video frames in {video_path}")
                    audio = normalized_info['audio']
                    # PCM duration is sample-exact. Never cut speech to fit a shorter video.
                    audio_duration = Fraction(int(audio['duration_ts'])) * Fraction(audio['time_base']) if audio else 0
                    segment_frames.append((frames, max(frames, ceil(audio_duration * 24)), bool(audio)))
                    target_frames = segment_frames[-1][1]
                    media_segments.append({
                        "source_path": str(final_video_list[index]), "source_sha256": source_hashes[index],
                        "origin": str(origin), "video_start": str(video_start), "audio_start": str(audio_start),
                        "normalized_frames": frames, "target_frames": target_frames,
                        "normalized_audio_samples": int(audio_duration * 48000),
                        "target_samples": target_frames * 2000,
                        "offset_samples": sum(item[1] * 2000 for item in segment_frames[:-1]),
                    })
                    await report(15 + 50 * (index + 1) / count, step)

                # Exact frame/sample boundaries, with only one AAC encode for the chapter.
                cmd = ['ffmpeg', '-xerror']
                for video_path in normalized_paths:
                    cmd.extend(['-i', video_path])
                normalized_streams = []
                for index, (frames, target_frames, has_audio) in enumerate(segment_frames):
                    samples = target_frames * 2000  # 48000 Hz / 24 fps
                    normalized_streams.append(f'[{index}:v:0]tpad=stop_mode=clone:stop={target_frames - frames},trim=end_frame={target_frames},setpts=N/(24*TB)[v{index}]')
                    audio_input = f'[{index}:a:0]' if has_audio else 'anullsrc=channel_layout=stereo:sample_rate=48000,'
                    normalized_streams.append(f'{audio_input}apad=whole_len={samples},atrim=end_sample={samples},asetpts=N/SR/TB[a{index}]')
                concat_inputs = ''.join(f'[v{index}][a{index}]' for index in range(len(normalized_paths)))
                filter_complex = ';'.join(normalized_streams + [f'{concat_inputs}concat=n={len(normalized_paths)}:v=1:a=1[v][a]'])
                cmd.extend([
                    '-filter_complex', filter_complex,
                    '-map', '[v]',
                    '-map', '[a]',
                    '-c:v', 'libx264',
                    '-preset', 'medium',
                    '-crf', '18',
                    '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac',
                    '-ar', '48000',
                    '-ac', '2',
                    '-movflags', '+faststart',
                    '-y',  # 覆盖输出文件
                    candidate_path,
                ])

                print(f"[FileStorage] Running ffmpeg: {' '.join(cmd)}")
                
                total_duration = sum(frames for _, frames, _ in segment_frames) / 24
                await report(65, "编码合并视频")

                async def encode_progress(seconds):
                    await report(65 + 30 * min(0.99, seconds / total_duration), "编码合并视频")

                result = await self._run_merge_process(cmd, encode_progress)

                if result.returncode != 0:
                    print(f"[FileStorage] FFmpeg error: {result.stderr}")
                    return {
                        "success": False,
                        "message": f"视频合并失败: {result.stderr[:200]}"
                    }
                
                # 检查输出文件是否存在
                if not Path(candidate_path).exists():
                    return {
                        "success": False,
                        "message": "输出文件未生成"
                    }

                await report(95, "校验合并视频")
                await _validate_video_decode(candidate_path)
                decoded_seconds=0.0
                async def capture_audio_extent(seconds):
                    nonlocal decoded_seconds
                    decoded_seconds=max(decoded_seconds,seconds)
                decoded_audio=await self._run_merge_process(['ffmpeg','-v','error','-xerror','-i',candidate_path,
                    '-map','0:a:0','-ar','48000','-ac','1','-f','null','-'],capture_audio_extent)
                if decoded_audio.returncode!=0:
                    raise RuntimeError('Merged chapter audio extent could not be decoded')
                candidate_info=await _get_video_info(candidate_path,count_frames=True)
                expected_frames=sum(item[1] for item in segment_frames);expected_samples=expected_frames*2000
                actual_frames=int(candidate_info['video'].get('nb_read_frames') or 0)
                actual_samples=round(decoded_seconds*48000)
                if (actual_frames!=expected_frames or actual_samples<expected_samples or actual_samples>=expected_samples+1024
                        or candidate_info['width']!=target_width or candidate_info['height']!=target_height):
                    raise RuntimeError('Merged chapter extent differs from frozen frame/sample manifest')

                await report(99, "发布合并视频")
                if any(fingerprint(path) != expected for path, expected in zip(final_video_list, source_hashes)):
                    raise RuntimeError("Source media changed during merge; retry")
                cues, unavailable = compose(media_segments, snapshots)
                snapshot = publish(candidate_path, cues, {"kind": "merge", "fps": 24, "sample_rate": 48000,
                                   "segments": media_segments, "sources": snapshots}, unavailable=unavailable)
                os.replace(candidate_path, output_path)
                from app.services.rendered_subtitles import sidecar
                os.replace(sidecar(candidate_path), sidecar(output_path))
                await report(100, "合并视频已发布")
                print(f"[FileStorage] Video merged successfully: {output_path}")
                return {
                    "success": True,
                    "output_path": output_path,
                    "subtitle_snapshot": snapshot,
                    "media_segments": media_segments,
                    "message": f"合并完成，共 {len(final_video_list)} 个视频片段"
                }
                
            except Exception as e:
                raise e
            finally:
                shutil.rmtree(temp_normalized_dir, ignore_errors=True)
            
        except Exception as e:
            import traceback
            print(f"[FileStorage] Failed to merge videos: {e}")
            traceback.print_exc()
            return {"success": False, "message": f"合并失败: {str(e)}"}


    async def render_narration_card(self, audio_path: str, output_path: str, duration: float,
                                    profile: Dict[str, Any], lineage: Dict[str, Any], *,
                                    expected_audio_sha256: str, expected_snapshot_hash: str,
                                    progress_callback=None) -> Dict[str, Any]:
        """Render a model-free neutral card with one verified narration track."""
        import json
        import os
        import tempfile
        from app.services.rendered_subtitles import fingerprint,load,publish,sidecar
        source=Path(audio_path);destination=Path(output_path)
        if not source.is_file() or duration<=0:return {"success":False,"message":"NARRATION_CARD_AUDIO_INVALID"}
        if destination.exists() or sidecar(destination).exists():
            return {"success":False,"message":"NARRATION_CARD_DESTINATION_EXISTS"}
        destination.parent.mkdir(parents=True,exist_ok=True)
        workspace=Path(tempfile.mkdtemp(prefix='.narration_card_',dir=str(destination.parent)))
        candidate=workspace/'candidate.mp4';frozen_audio=workspace/f'source_audio{source.suffix}'
        shutil.copyfile(source,frozen_audio)
        if fingerprint(frozen_audio)!=expected_audio_sha256:
            shutil.rmtree(workspace,ignore_errors=True);return {"success":False,"message":"NARRATION_CARD_AUDIO_COPY_FAILED"}
        snapshot=load(source)
        from app.services.chapter_asset_parse_service import digest
        if not snapshot or snapshot.get('unavailable') or digest(snapshot)!=expected_snapshot_hash:
            shutil.rmtree(workspace,ignore_errors=True);return {"success":False,"message":"NARRATION_CARD_CAPTURED_AUDIO_CHANGED"}
        source_hash=expected_audio_sha256
        width,height,fps=int(profile['width']),int(profile['height']),int(profile['fps'])
        target_frames=max(1,__import__('math').ceil(float(duration)*fps));exact_duration=target_frames/fps
        cmd=['ffmpeg','-v','error','-xerror','-f','lavfi','-i',
            f"color=c={profile['color']}:s={width}x{height}:r={fps}:d={exact_duration}",
            '-i',str(frozen_audio),'-map','0:v:0','-map','1:a:0','-frames:v',str(target_frames),
            '-c:v',profile['video_codec'],'-pix_fmt',profile['pixel_format'],'-preset','medium','-crf','18',
            '-c:a',profile['audio_codec'],'-ar',str(profile['audio_rate']),'-ac',str(profile['audio_channels']),
            '-af',f"apad=whole_dur={exact_duration},atrim=end={exact_duration}",'-movflags','+faststart','-y',str(candidate)]
        try:
            rendered=await self._run_merge_process(cmd,progress_callback)
            if rendered.returncode!=0 or not candidate.is_file():
                return {"success":False,"message":"NARRATION_CARD_RENDER_FAILED: "+(rendered.stderr or '')[:300]}
            probe=await self._run_merge_process(['ffprobe','-v','error','-count_frames',
                '-show_entries','stream=codec_type,codec_name,pix_fmt,width,height,avg_frame_rate,nb_read_frames,sample_rate,channels,duration_ts,time_base:format=duration',
                '-of','json',str(candidate)])
            decoded=await self._run_merge_process(['ffmpeg','-v','error','-xerror','-i',str(candidate),
                '-map','0:v:0','-map','0:a:0','-f','null','-'])
            if probe.returncode!=0 or decoded.returncode!=0 or (decoded.stderr or '').strip():
                return {"success":False,"message":"NARRATION_CARD_VALIDATION_FAILED"}
            info=json.loads(probe.stdout or '{}');streams=info.get('streams') or []
            video=next((row for row in streams if row.get('codec_type')=='video'),None)
            audio=next((row for row in streams if row.get('codec_type')=='audio'),None)
            from fractions import Fraction
            try:audio_duration=float(Fraction(int(audio['duration_ts']))*Fraction(audio['time_base'])) if audio else 0
            except (KeyError,TypeError,ValueError,ZeroDivisionError):audio_duration=0
            if (not video or not audio or int(video.get('width') or 0)!=width or int(video.get('height') or 0)!=height
                    or int(video.get('nb_read_frames') or 0)!=target_frames
                    or video.get('codec_name')!='h264' or video.get('pix_fmt')!=profile['pixel_format']
                    or video.get('avg_frame_rate')!=f'{fps}/1'
                    or int(audio.get('sample_rate') or 0)!=int(profile['audio_rate'])
                    or int(audio.get('channels') or 0)!=int(profile['audio_channels'])
                    or audio_duration+0.001<float(duration)
                    or abs(float((info.get('format') or {}).get('duration') or 0)-exact_duration)>0.05):
                return {"success":False,"message":"NARRATION_CARD_MEDIA_CONTRACT_FAILED"}
            current_snapshot=load(source)
            if (fingerprint(source)!=source_hash or not current_snapshot
                    or digest(current_snapshot)!=expected_snapshot_hash):
                return {"success":False,"message":"NARRATION_CARD_AUDIO_CHANGED"}
            media_lineage={**deepcopy(lineage),'kind':'narration_card','profile':profile,
                'source_audio_sha256':source_hash,'source_audio_snapshot':snapshot,
                'target_frames':target_frames,'duration':exact_duration}
            published=publish(candidate,deepcopy(snapshot.get('cues') or []),media_lineage)
            os.replace(candidate,destination);os.replace(sidecar(candidate),sidecar(destination))
            return {'success':True,'output_path':str(destination),'sha256':fingerprint(destination),
                'bytes':destination.stat().st_size,'duration':exact_duration,'frames':target_frames,
                'subtitle_snapshot':published}
        finally:
            shutil.rmtree(workspace,ignore_errors=True)


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

    def get_audio_event_tts_path(
        self,
        novel_id: str,
        chapter_id: str,
        shot_id: str,
        audio_event_id: str,
        event_order: int,
        revision: int,
        ext: str = ".wav",
    ) -> Path:
        """获取 AudioDrive 单条 Audio Event TTS 资产路径。"""
        story_dir = self._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        save_dir = story_dir / f"chapter_{chapter_short}" / "audio_events" / f"shot_{shot_id[:8]}"
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir / f"event_{event_order:03d}_{audio_event_id[:8]}_rev_{revision}{ext}"

    def get_audio_timeline_manifest_path(
        self,
        novel_id: str,
        chapter_id: str,
        shot_id: str,
        revision: int,
    ) -> Path:
        """获取 AudioDrive Timeline manifest 路径。"""
        story_dir = self._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        save_dir = story_dir / f"chapter_{chapter_short}" / "audio_timeline" / f"shot_{shot_id[:8]}"
        save_dir.mkdir(parents=True, exist_ok=True)
        return save_dir / f"timeline_rev_{revision}.json"

    def get_clip_audio_path(
        self,
        novel_id: str,
        chapter_id: str,
        shot_id: str,
        window_index: int,
        kind: str,
        ext: str = ".wav",
    ) -> Path:
        """获取 AudioDrive Clip 级 drive/final 音频或 manifest 路径。"""
        story_dir = self._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        save_dir = story_dir / f"chapter_{chapter_short}" / "clip_audio" / f"shot_{shot_id[:8]}"
        save_dir.mkdir(parents=True, exist_ok=True)
        safe_kind = self._sanitize_filename(kind)
        return save_dir / f"clip_{window_index:03d}_{safe_kind}{ext}"

    def get_narration_card_video_path(self, novel_id: str, chapter_id: str, shot_id: str, attempt_id: str) -> Path:
        story_dir=self._get_story_dir(novel_id);chapter_short=chapter_id[:8] if chapter_id else 'unknown'
        save_dir=story_dir/f'chapter_{chapter_short}'/'narration_cards'/f'shot_{shot_id[:8]}'
        save_dir.mkdir(parents=True,exist_ok=True)
        return save_dir/f'card_{attempt_id}.mp4'


# 全局实例
file_storage = FileStorageService()
