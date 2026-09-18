"""小说业务服务；素材解析统一生成章回候选，不直接写Book资产。"""
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session
from app.models.novel import Novel, Chapter
from app.services.llm_service import LLMService
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.utils.image_utils import merge_character_images


class NovelService:
    def __init__(self, db: Session = None):
        self.db = db
        self.comfyui_service = ComfyUIService()

    def get_llm_service(self) -> LLMService:
        return LLMService()

    async def _parse_candidates(self, novel_id, chapters, kind):
        from app.services.chapter_asset_pipeline import parse_and_resolve
        results = [await parse_and_resolve(self.db, novel_id, chapter.id, [kind], self.get_llm_service()) for chapter in chapters]
        return {"success": bool(results) and all(row["success"] for row in results),
                "data": [{**row["data"], "phase2Ready": row["success"]} for row in results],
                "statistics": {"candidates": sum(row["data"]["candidateCount"] for row in results), "chapters": len(results)},
                "message": "候选及身份归并已执行，请在章回页面检查关联或歧义项"}

    async def parse_characters(self, novel_id, chapters, start_chapter=None, end_chapter=None,
                               is_incremental=False, character_repo=None):
        # Old request parameters never select a second global-asset writing path.
        return await self._parse_candidates(novel_id, chapters, "characters")

    async def parse_props(self, novel_id, chapters, start_chapter=None, end_chapter=None,
                          is_incremental=False, prop_repo=None):
        return await self._parse_candidates(novel_id, chapters, "props")

    async def parse_scenes_from_chapters(self, novel_id, chapters, mode="incremental",
                                        scene_repo=None, prompt_template_repo=None):
        return await self._parse_candidates(novel_id, chapters, "scenes")

    async def parse_scenes(self, novel_id, chapter, is_incremental=True, scene_repo=None):
        return await self._parse_candidates(novel_id, [chapter], "scenes")

    async def split_chapter(
        self,
        novel: Novel,
        chapter: Chapter,
        character_names: List[str] = None,
        scene_names: List[str] = None,
        prop_names: List[str] = None,
        source_contract_version: str = 'chapter-shot-ownership-v2',
    ) -> Dict[str, Any]:
        from app.services.chapter_shot_split_service import ChapterShotSplitService
        # Old name-array arguments cannot grant membership or bypass ChapterScope.
        return await ChapterShotSplitService(self.db, self.get_llm_service()).split(
            novel.id, chapter.id, source_contract_version=source_contract_version)

    def merge_character_images(self, novel_id: str, chapter_id: str, shot_index: int,
                               character_images: List[Tuple[str, str]]) -> Optional[str]:
        return merge_character_images(novel_id, chapter_id, shot_index, character_images, file_storage)


from app.services.media_task_service import generate_shot_task, generate_shot_video_task, generate_transition_video_task
