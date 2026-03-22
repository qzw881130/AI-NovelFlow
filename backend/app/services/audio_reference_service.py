"""
音频参考服务

负责处理视频生成的音频参考功能：
- 合并台词音频
- 上传参考音频
- 设置参考音频来源（合并台词/上传/角色音色）
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories.shot_repository import ShotRepository
from app.repositories.character_repository import CharacterRepository
from app.services.file_storage import file_storage
from app.services.audio_merge_service import AudioMergeService


class AudioReferenceService:
    """音频参考服务"""

    def __init__(self, db: Session):
        self.db = db
        self.merge_service = AudioMergeService(db)

    async def merge_dialogue_audio(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        shot_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        合并分镜的台词音频作为参考音频

        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引（1-based）
            shot_id: 可选的分镜ID，如果提供则直接使用

        Returns:
            {
                "success": bool,
                "audio_url": str,
                "message": str,
                "duration": float
            }
        """
        # 获取分镜信息
        shot_repo = ShotRepository(self.db)

        # 优先使用 shot_id，否则使用 chapter_id + shot_index 查询
        if shot_id:
            shot = shot_repo.get_by_id(shot_id)
        else:
            shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)

        if not shot:
            return {
                "success": False,
                "message": f"分镜不存在: chapter_id={chapter_id}, index={shot_index}"
            }

        # 使用 AudioMergeService 合并音频，传入 shot_id
        result = await self.merge_service.merge_dialogue_audios(
            novel_id, chapter_id, shot_index, shot_id=shot.id
        )

        if result["success"]:
            # 更新 shot 的 reference_audio_url 和 type
            shot_repo.update(shot, reference_audio_url=result["audio_url"], reference_audio_type="merged")

        return result

    async def upload_reference_audio(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        file_content: bytes,
        filename: str,
        shot_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        上传参考音频文件

        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引（1-based）
            file_content: 文件内容
            filename: 原始文件名
            shot_id: 可选的分镜ID，如果提供则直接使用

        Returns:
            {
                "success": bool,
                "audio_url": str,
                "message": str
            }
        """
        try:
            # 验证文件类型
            allowed_extensions = {'.mp3', '.wav', '.flac', '.ogg', '.m4a'}
            ext = os.path.splitext(filename)[1].lower()

            if ext not in allowed_extensions:
                return {
                    "success": False,
                    "message": f"不支持的音频格式: {ext}。支持: {', '.join(allowed_extensions)}"
                }

            # 获取保存路径
            save_path = self._get_reference_audio_path(novel_id, chapter_id, shot_index, ext)

            # 保存文件
            with open(save_path, 'wb') as f:
                f.write(file_content)

            # 生成 API URL
            relative_path = str(save_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
            audio_url = f"/api/files/{relative_path.lstrip('/')}"

            # 更新 shot 的 reference_audio_url
            shot_repo = ShotRepository(self.db)

            # 优先使用 shot_id，否则使用 chapter_id + shot_index 查询
            if shot_id:
                shot = shot_repo.get_by_id(shot_id)
            else:
                shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)

            if shot:
                shot_repo.update(shot, reference_audio_url=audio_url, reference_audio_type="uploaded")

            return {
                "success": True,
                "audio_url": audio_url,
                "message": "参考音频上传成功"
            }

        except Exception as e:
            import traceback
            print(f"[AudioReference] Upload failed: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": f"上传失败: {str(e)}"
            }

    async def set_character_voice_reference(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        character_name: str,
        shot_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        设置角色音色作为参考音频

        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引（1-based）
            character_name: 角色名称
            shot_id: 可选的分镜ID，如果提供则直接使用

        Returns:
            {
                "success": bool,
                "audio_url": str,
                "message": str
            }
        """
        try:
            # 获取角色信息
            char_repo = CharacterRepository(self.db)
            character = char_repo.get_by_name(novel_id, character_name)

            if not character:
                return {
                    "success": False,
                    "message": f"角色不存在: {character_name}"
                }

            if not character.reference_audio_url:
                return {
                    "success": False,
                    "message": f"角色 {character_name} 没有设置参考音频"
                }

            # 更新 shot 的 reference_audio_url
            shot_repo = ShotRepository(self.db)

            # 优先使用 shot_id，否则使用 chapter_id + shot_index 查询
            if shot_id:
                shot = shot_repo.get_by_id(shot_id)
            else:
                shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)

            if not shot:
                return {
                    "success": False,
                    "message": "分镜不存在"
                }

            shot_repo.update(shot, reference_audio_url=character.reference_audio_url, reference_audio_type="character")

            return {
                "success": True,
                "audio_url": character.reference_audio_url,
                "message": f"已设置角色 {character_name} 的音色作为参考音频"
            }

        except Exception as e:
            import traceback
            print(f"[AudioReference] Set character voice failed: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": f"设置失败: {str(e)}"
            }

    async def clear_reference_audio(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        shot_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        清除参考音频

        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引（1-based）
            shot_id: 可选的分镜ID，如果提供则直接使用

        Returns:
            {
                "success": bool,
                "message": str
            }
        """
        try:
            shot_repo = ShotRepository(self.db)

            # 优先使用 shot_id，否则使用 chapter_id + shot_index 查询
            if shot_id:
                shot = shot_repo.get_by_id(shot_id)
            else:
                shot = shot_repo.get_by_chapter_and_index(chapter_id, shot_index)

            if not shot:
                return {
                    "success": False,
                    "message": "分镜不存在"
                }

            shot_repo.update(shot, reference_audio_url=None, reference_audio_type="none")

            return {
                "success": True,
                "message": "已清除参考音频"
            }

        except Exception as e:
            import traceback
            print(f"[AudioReference] Clear failed: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "message": f"清除失败: {str(e)}"
            }

    def _get_reference_audio_path(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        ext: str
    ) -> Path:
        """
        获取参考音频保存路径

        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引
            ext: 文件扩展名

        Returns:
            文件保存路径
        """
        story_dir = file_storage._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        save_dir = story_dir / f"chapter_{chapter_short}" / "reference_audio"
        save_dir.mkdir(parents=True, exist_ok=True)

        # 使用时间戳生成唯一文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return save_dir / f"shot_{shot_index:03d}_ref_{timestamp}{ext}"

    def get_reference_audio_source_type(
        self,
        reference_audio_url: Optional[str],
        character_names: list[str],
        novel_id: str
    ) -> str:
        """
        推断参考音频的来源类型

        Args:
            reference_audio_url: 参考音频URL
            character_names: 分镜中的角色名称列表
            novel_id: 小说ID

        Returns:
            来源类型: "none", "merged", "uploaded", "character"
        """
        if not reference_audio_url:
            return "none"

        # 检查是否是合并音频
        if "merged_audio" in reference_audio_url:
            return "merged"

        # 检查是否是上传的参考音频
        if "reference_audio" in reference_audio_url:
            return "uploaded"

        # 检查是否匹配某个角色的参考音频
        char_repo = CharacterRepository(self.db)
        for char_name in character_names:
            character = char_repo.get_by_name(novel_id, char_name)
            if character and character.reference_audio_url == reference_audio_url:
                return "character"

        # 默认返回 uploaded
        return "uploaded"