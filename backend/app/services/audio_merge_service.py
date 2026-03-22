"""
音频合并服务

负责合并多条台词音频文件

支持两种方式：
1. pydub（纯Python库，需要安装 pydub 和 audioop-lts）
2. ffmpeg（可选，如果可用则使用）
"""
import json
import asyncio
import subprocess
import tempfile
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories.shot_repository import ShotRepository
from app.services.file_storage import file_storage

# 尝试导入 pydub
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("[AudioMerge] Warning: pydub not installed, audio merge may not work")


class AudioMergeService:
    """音频合并服务"""

    def __init__(self, db: Session = None):
        self.db = db

    async def merge_dialogue_audios(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        shot_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        合并分镜中所有台词的音频

        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引 (1-based)
            shot_id: 可选的分镜ID，如果提供则直接使用

        Returns:
            {
                "success": bool,
                "audio_url": str,
                "message": str,
                "duration": float
            }
        """
        try:
            # 获取分镜数据
            shot_repo = ShotRepository(self.db)

            # 优先使用 shot_id，否则使用 chapter_id + shot_index
            if shot_id:
                shot = shot_repo.get_by_id(shot_id)
            else:
                shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)

            if not shot:
                return {
                    "success": False,
                    "message": f"分镜不存在: chapter_id={chapter_id}, index={shot_index}"
                }

            # 解析台词数据
            dialogues = json.loads(shot.dialogues) if shot.dialogues else []

            if not dialogues:
                return {
                    "success": False,
                    "message": "该分镜没有台词"
                }

            # 筛选有音频的台词，并按 order 字段排序
            dialogues_with_audio = []
            for dialogue in dialogues:
                audio_url = dialogue.get("audio_url")
                if audio_url:
                    dialogues_with_audio.append({
                        "order": dialogue.get("order", 0) or 0,
                        "audio_url": audio_url,
                        "character_name": dialogue.get("character_name", ""),
                        "type": dialogue.get("type", "character")
                    })

            if not dialogues_with_audio:
                return {
                    "success": False,
                    "message": "该分镜没有已生成的台词音频"
                }

            # 按 order 排序
            dialogues_with_audio.sort(key=lambda x: x["order"])

            # 下载音频文件到本地
            local_audio_paths = []
            for dialogue in dialogues_with_audio:
                local_path = await self._get_local_audio_path(
                    dialogue["audio_url"],
                    novel_id,
                    dialogue["character_name"]
                )
                if local_path and Path(local_path).exists():
                    local_audio_paths.append(local_path)
                else:
                    print(f"[AudioMerge] Audio file not found: {dialogue['audio_url']}")

            if not local_audio_paths:
                return {
                    "success": False,
                    "message": "无法获取音频文件"
                }

            if len(local_audio_paths) == 1:
                # 只有一个音频文件，直接返回
                relative_path = local_audio_paths[0].replace(str(file_storage.base_dir), "").replace("\\", "/")
                audio_url = f"/api/files/{relative_path.lstrip('/')}"
                return {
                    "success": True,
                    "audio_url": audio_url,
                    "message": "只有一个音频文件，无需合并",
                    "duration": await self._get_audio_duration_pydub(local_audio_paths[0])
                }

            # 生成合并后的音频文件路径
            merged_path = self._get_merged_audio_path(novel_id, chapter_id, shot_index)

            # 使用 pydub 合并音频
            result = await self._concatenate_audios_pydub(local_audio_paths, str(merged_path))

            if result["success"]:
                # 返回 API URL
                relative_path = str(merged_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
                audio_url = f"/api/files/{relative_path.lstrip('/')}"
                return {
                    "success": True,
                    "audio_url": audio_url,
                    "message": f"合并完成，共 {len(local_audio_paths)} 个音频",
                    "duration": result.get("duration", 0)
                }
            else:
                return result

        except Exception as e:
            import traceback
            print(f"[AudioMerge] Error merging audios: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": f"合并音频失败: {str(e)}"
            }

    async def _get_local_audio_path(
        self,
        audio_url: str,
        novel_id: str,
        character_name: str
    ) -> Optional[str]:
        """
        获取音频文件的本地路径

        Args:
            audio_url: 音频URL（可能是本地API路径或远程URL）
            novel_id: 小说ID
            character_name: 角色名称

        Returns:
            本地文件路径
        """
        import httpx

        try:
            # 如果已经是本地文件路径
            if audio_url.startswith("/api/files/"):
                relative_path = audio_url.replace("/api/files/", "")
                local_path = file_storage.base_dir / relative_path
                if local_path.exists():
                    return str(local_path)

            # 如果是远程URL，下载到临时目录
            if audio_url.startswith("http"):
                story_dir = file_storage._get_story_dir(novel_id)
                temp_dir = story_dir / "temp"
                temp_dir.mkdir(parents=True, exist_ok=True)

                safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in character_name)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                temp_path = temp_dir / f"{safe_name}_{timestamp}.flac"

                async with httpx.AsyncClient() as client:
                    response = await client.get(audio_url, timeout=60.0)
                    if response.status_code == 200:
                        with open(temp_path, "wb") as f:
                            f.write(response.content)
                        return str(temp_path)

            return None

        except Exception as e:
            print(f"[AudioMerge] Failed to get local audio path: {e}")
            return None

    def _get_merged_audio_path(self, novel_id: str, chapter_id: str, shot_index: int) -> Path:
        """
        获取合并音频保存路径

        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引

        Returns:
            合并音频文件路径
        """
        story_dir = file_storage._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        save_dir = story_dir / f"chapter_{chapter_short}" / "merged_audio"
        save_dir.mkdir(parents=True, exist_ok=True)

        # 使用时间戳生成唯一文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return save_dir / f"shot_{shot_index:03d}_merged_{timestamp}.flac"

    async def _concatenate_audios_pydub(
        self,
        audio_paths: List[str],
        output_path: str
    ) -> Dict[str, Any]:
        """
        使用 pydub 合并多个音频文件

        Args:
            audio_paths: 音频文件路径列表
            output_path: 输出文件路径

        Returns:
            {"success": bool, "message": str, "duration": float}
        """
        if not PYDUB_AVAILABLE:
            return {
                "success": False,
                "message": "pydub 未安装，请运行: pip install pydub audioop-lts"
            }

        try:
            loop = asyncio.get_event_loop()

            def _merge_audios():
                combined = None
                for i, audio_path in enumerate(audio_paths):
                    try:
                        # 根据文件扩展名加载音频
                        ext = Path(audio_path).suffix.lstrip('.').lower()
                        if ext == 'flac':
                            audio = AudioSegment.from_file(audio_path, format='flac')
                        elif ext == 'mp3':
                            audio = AudioSegment.from_file(audio_path, format='mp3')
                        elif ext == 'wav':
                            audio = AudioSegment.from_file(audio_path, format='wav')
                        elif ext in ['ogg', 'oga']:
                            audio = AudioSegment.from_file(audio_path, format='ogg')
                        elif ext == 'm4a':
                            audio = AudioSegment.from_file(audio_path, format='m4a')
                        else:
                            # 尝试自动检测格式
                            audio = AudioSegment.from_file(audio_path)

                        if combined is None:
                            combined = audio
                        else:
                            combined += audio

                    except Exception as e:
                        print(f"[AudioMerge] Failed to load audio {audio_path}: {e}")
                        continue

                if combined is None:
                    raise ValueError("无法加载任何音频文件")

                # 导出合并后的音频
                output_ext = Path(output_path).suffix.lstrip('.').lower()
                if output_ext == 'flac':
                    combined.export(output_path, format='flac')
                else:
                    combined.export(output_path, format=output_ext)

                return len(combined) / 1000.0  # 返回时长（秒）

            duration = await loop.run_in_executor(None, _merge_audios)

            print(f"[AudioMerge] Audio merged successfully with pydub: {output_path}")
            return {
                "success": True,
                "message": "合并成功",
                "duration": duration
            }

        except Exception as e:
            import traceback
            print(f"[AudioMerge] Failed to concatenate audios with pydub: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": f"合并失败: {str(e)}"
            }

    async def _get_audio_duration_pydub(self, audio_path: str) -> float:
        """
        使用 pydub 获取音频文件时长

        Args:
            audio_path: 音频文件路径

        Returns:
            时长（秒）
        """
        if not PYDUB_AVAILABLE:
            return 0.0

        try:
            loop = asyncio.get_event_loop()

            def _get_duration():
                ext = Path(audio_path).suffix.lstrip('.').lower()
                if ext == 'flac':
                    audio = AudioSegment.from_file(audio_path, format='flac')
                elif ext == 'mp3':
                    audio = AudioSegment.from_file(audio_path, format='mp3')
                elif ext == 'wav':
                    audio = AudioSegment.from_file(audio_path, format='wav')
                else:
                    audio = AudioSegment.from_file(audio_path)
                return len(audio) / 1000.0

            return await loop.run_in_executor(None, _get_duration)

        except Exception as e:
            print(f"[AudioMerge] Failed to get audio duration: {e}")
            return 0.0