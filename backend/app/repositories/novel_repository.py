"""
小说数据仓库

封装小说相关的数据库查询逻辑
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, selectinload

from app.models.novel import Novel, Chapter
from app.models.shot import Shot
from app.constants.prompt_template import NOVEL_PROMPT_TEMPLATE_FIELDS, GRID_PROMPT_TYPES, SHARED_PROMPT_TYPES


class NovelRepository:
    """小说数据仓库"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_with_cover(self) -> List[Dict[str, Any]]:
        """
        获取小说列表，预加载关联数据避免 N+1 查询

        Returns:
            小说列表，包含封面信息
        """
        from app.schemas.grid_shot import load_grid_data

        novels = self.db.query(Novel).order_by(Novel.created_at.desc()).all()

        if not novels:
            return []

        novel_ids = [n.id for n in novels]

        # 批量查询所有小说的第一章节
        first_chapters = {}
        chapters = self.db.query(Chapter).filter(
            Chapter.novel_id.in_(novel_ids)
        ).order_by(Chapter.novel_id, Chapter.number).all()

        for chapter in chapters:
            if chapter.novel_id not in first_chapters:
                first_chapters[chapter.novel_id] = chapter

        chapter_novel_ids = {chapter.id: chapter.novel_id for chapter in chapters}
        novels_by_id = {novel.id: novel for novel in novels}
        novels_with_shots = set()
        if chapter_novel_ids:
            shot_chapters = self.db.query(Shot.chapter_id).filter(
                Shot.chapter_id.in_(chapter_novel_ids)
            ).distinct().all()
            novels_with_shots = {chapter_novel_ids[row[0]] for row in shot_chapters}

        # 批量查询所有第一章的分镜，获取第一个有图片的分镜
        first_chapter_ids = [c.id for c in first_chapters.values()]
        first_shots = {}
        if first_chapter_ids:
            shots = self.db.query(Shot).filter(
                Shot.chapter_id.in_(first_chapter_ids),
            ).order_by(Shot.chapter_id, Shot.index).all()

            for shot in shots:
                if shot.chapter_id in first_shots:
                    continue
                novel = novels_by_id.get(chapter_novel_ids[shot.chapter_id])
                if novel and novel.video_mode == "grid":
                    grid = load_grid_data(shot.grid_data)
                    if grid and grid.board_image_url:
                        first_shots[shot.chapter_id] = grid.board_image_url
                elif shot.image_url:
                    first_shots[shot.chapter_id] = shot.image_url

        # 构建结果
        result = []
        for n in novels:
            cover = n.cover
            if not cover:
                first_chapter = first_chapters.get(n.id)
                if first_chapter:
                    # 优先从 Shot 表获取第一个分镜图片
                    first_shot_image = first_shots.get(first_chapter.id)
                    if first_shot_image:
                        cover = first_shot_image
                    else:
                        # 回退：从旧的 shot_images 字段获取（兼容旧数据）
                        if first_chapter.shot_images:
                            try:
                                import json
                                shot_images = json.loads(first_chapter.shot_images)
                                if isinstance(shot_images, list) and len(shot_images) > 0:
                                    cover = shot_images[0]
                            except json.JSONDecodeError:
                                pass

            result.append({
                "id": n.id,
                "title": n.title,
                "author": n.author,
                "description": n.description,
                "cover": cover,
                "status": n.status,
                "isArchived": bool(n.is_archived),
                "chapterCount": n.chapter_count,
                "videoMode": n.video_mode or "single",
                "hasShots": n.id in novels_with_shots,
                "storyWorldContextPromptTemplateId": n.story_world_context_prompt_template_id,
                "hasStoryWorldContext": bool(n.story_world_context),
                "storyWorldContextLocked": bool(n.story_world_context_locked),
                "stylePromptTemplateId": n.style_prompt_template_id,
                "characterParsePromptTemplateId": n.character_parse_prompt_template_id,
                "sceneParsePromptTemplateId": n.scene_parse_prompt_template_id,
                "propParsePromptTemplateId": n.prop_parse_prompt_template_id,
                "promptTemplateId": n.prompt_template_id,
                "scenePromptTemplateId": n.scene_prompt_template_id,
                "propPromptTemplateId": n.prop_prompt_template_id,
                "sceneSettingPromptTemplateId": n.scene_setting_prompt_template_id,
                "propAppearancePromptTemplateId": n.prop_appearance_prompt_template_id,
                "chapterSplitPromptTemplateId": n.chapter_split_prompt_template_id,
                "keyframeDescriptionPromptTemplateId": n.keyframe_description_prompt_template_id,
                "shotImagePromptTemplateId": n.shot_image_prompt_template_id,
                "keyframePlannerPromptTemplateId": n.keyframe_planner_prompt_template_id,
                "keyframeImagePromptTemplateId": n.keyframe_image_prompt_template_id,
                "temporalReferenceSelectorPromptTemplateId": n.temporal_reference_selector_prompt_template_id,
                "imageQualityReviewPromptTemplateId": n.image_quality_review_prompt_template_id,
                "keyframeTransitionPromptTemplateId": n.keyframe_transition_prompt_template_id,
                "clipExecutionPlannerPromptTemplateId": n.clip_execution_planner_prompt_template_id,
                "h3MultiKeyframePromptTemplateId": n.h3_multi_keyframe_prompt_template_id,
                "h3MultiKeyframeDirectorPhaseBTemplateId": n.h3_multi_keyframe_director_phase_b_template_id,
                "h3ExecutionOptimizerPromptTemplateId": n.h3_execution_optimizer_prompt_template_id,
                "h3PreflightRepairPromptTemplateId": n.h3_preflight_repair_prompt_template_id,
                "gridShotPlanPromptTemplateId": n.grid_shot_plan_prompt_template_id,
                "gridImagePromptTemplateId": n.grid_image_prompt_template_id,
                "gridClipPlanPromptTemplateId": n.grid_clip_plan_prompt_template_id,
                "gridH3PhaseBPromptTemplateId": n.grid_h3_phase_b_prompt_template_id,
                "aspectRatio": n.aspect_ratio if n.aspect_ratio and n.aspect_ratio.strip() else "16:9",
                "createdAt": n.created_at.isoformat() if n.created_at else None,
                "updatedAt": n.updated_at.isoformat() if n.updated_at else None,
            })

        return result
    
    def get_by_id(self, novel_id: str) -> Optional[Novel]:
        """根据 ID 获取小说"""
        return self.db.query(Novel).filter(Novel.id == novel_id).first()
    
    def get_with_chapters(self, novel_id: str) -> Optional[Novel]:
        """获取小说及其章节（预加载）"""
        return self.db.query(Novel).options(
            selectinload(Novel.chapters)
        ).filter(Novel.id == novel_id).first()
    
    def get_with_characters(self, novel_id: str) -> Optional[Novel]:
        """获取小说及其角色（预加载）"""
        return self.db.query(Novel).options(
            selectinload(Novel.characters)
        ).filter(Novel.id == novel_id).first()
    
    def get_with_scenes(self, novel_id: str) -> Optional[Novel]:
        """获取小说及其场景（预加载）"""
        return self.db.query(Novel).options(
            selectinload(Novel.scenes)
        ).filter(Novel.id == novel_id).first()
    
    def get_full(self, novel_id: str) -> Optional[Novel]:
        """获取小说及其所有关联数据（预加载）"""
        return self.db.query(Novel).options(
            selectinload(Novel.chapters),
            selectinload(Novel.characters),
            selectinload(Novel.scenes)
        ).filter(Novel.id == novel_id).first()
    
    def create(self, title: str, author: str = None, description: str = None,
               prompt_template_id: str = None, chapter_split_prompt_template_id: str = None,
               aspect_ratio: str = "16:9") -> Novel:
        """创建小说"""
        novel = Novel(
            title=title,
            author=author,
            description=description,
            prompt_template_id=prompt_template_id,
            chapter_split_prompt_template_id=chapter_split_prompt_template_id,
            aspect_ratio=aspect_ratio,
        )
        self.db.add(novel)
        self.db.commit()
        self.db.refresh(novel)
        return novel

    def copy_with_chapters(self, source: Novel, title: str) -> Novel:
        """Copy source text, basic settings and valid prompt references only."""
        from app.services.novel_prompt_templates import resolve_novel_prompt_template
        chapters = self.db.query(Chapter).filter(
            Chapter.novel_id == source.id
        ).order_by(Chapter.number, Chapter.id).all()
        copied = Novel(
            title=title,
            author=source.author,
            description=source.description,
            aspect_ratio=source.aspect_ratio or "16:9",
            video_mode=source.video_mode or "single",
            chapter_count=len(chapters),
            chapters=[
                Chapter(number=chapter.number, title=chapter.title, content=chapter.content or "")
                for chapter in chapters
            ],
        )
        for template_type, field in NOVEL_PROMPT_TEMPLATE_FIELDS.items():
            scope = ("grid" if template_type in GRID_PROMPT_TYPES else
                     "shared" if template_type in SHARED_PROMPT_TYPES else "single")
            if scope not in ("shared", copied.video_mode):
                continue
            if getattr(source, field, None):
                selected = resolve_novel_prompt_template(self.db, source, template_type)
                # A missing/deactivated version returns to default through a null
                # reference. Do not materialize the system default in the copy.
                if selected and selected.id == getattr(source, field):
                    setattr(copied, field, selected.id)
        try:
            self.db.add(copied)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(copied)
        return copied
    
    def update(self, novel: Novel, **kwargs) -> Novel:
        """更新小说"""
        for key, value in kwargs.items():
            if hasattr(novel, key):
                setattr(novel, key, value)
        self.db.commit()
        self.db.refresh(novel)
        return novel
    
    def delete(self, novel: Novel) -> None:
        """删除小说"""
        self.db.delete(novel)
        self.db.commit()
    
    def update_chapter_count(self, novel_id: str, count: int) -> None:
        """更新小说章节数"""
        novel = self.get_by_id(novel_id)
        if novel:
            novel.chapter_count = count
            self.db.commit()
    
    def to_response(self, novel: Novel) -> Dict[str, Any]:
        """
        将小说对象转换为响应字典
        
        Args:
            novel: 小说对象
            
        Returns:
            响应字典
        """
        return {
            "id": novel.id,
            "title": novel.title,
            "author": novel.author,
            "description": novel.description,
            "cover": novel.cover,
            "status": novel.status,
            "isArchived": bool(novel.is_archived),
            "chapterCount": novel.chapter_count,
            "videoMode": novel.video_mode or "single",
            "hasShots": self.db.query(Shot.id).join(Chapter, Shot.chapter_id == Chapter.id).filter(Chapter.novel_id == novel.id).first() is not None,
            "storyWorldContextPromptTemplateId": novel.story_world_context_prompt_template_id,
            "hasStoryWorldContext": bool(novel.story_world_context),
            "storyWorldContextLocked": bool(novel.story_world_context_locked),
            "stylePromptTemplateId": novel.style_prompt_template_id,
            "characterParsePromptTemplateId": novel.character_parse_prompt_template_id,
            "sceneParsePromptTemplateId": novel.scene_parse_prompt_template_id,
            "propParsePromptTemplateId": novel.prop_parse_prompt_template_id,
            "promptTemplateId": novel.prompt_template_id,
            "scenePromptTemplateId": novel.scene_prompt_template_id,
            "propPromptTemplateId": novel.prop_prompt_template_id,
            "sceneSettingPromptTemplateId": novel.scene_setting_prompt_template_id,
            "propAppearancePromptTemplateId": novel.prop_appearance_prompt_template_id,
            "chapterSplitPromptTemplateId": novel.chapter_split_prompt_template_id,
            "keyframeDescriptionPromptTemplateId": novel.keyframe_description_prompt_template_id,
            "shotImagePromptTemplateId": novel.shot_image_prompt_template_id,
            "keyframePlannerPromptTemplateId": novel.keyframe_planner_prompt_template_id,
            "keyframeImagePromptTemplateId": novel.keyframe_image_prompt_template_id,
            "temporalReferenceSelectorPromptTemplateId": novel.temporal_reference_selector_prompt_template_id,
            "imageQualityReviewPromptTemplateId": novel.image_quality_review_prompt_template_id,
            "keyframeTransitionPromptTemplateId": novel.keyframe_transition_prompt_template_id,
            "clipExecutionPlannerPromptTemplateId": novel.clip_execution_planner_prompt_template_id,
            "h3MultiKeyframePromptTemplateId": novel.h3_multi_keyframe_prompt_template_id,
            "h3MultiKeyframeDirectorPhaseBTemplateId": novel.h3_multi_keyframe_director_phase_b_template_id,
            "h3ExecutionOptimizerPromptTemplateId": novel.h3_execution_optimizer_prompt_template_id,
            "h3PreflightRepairPromptTemplateId": novel.h3_preflight_repair_prompt_template_id,
            "gridShotPlanPromptTemplateId": novel.grid_shot_plan_prompt_template_id,
            "gridImagePromptTemplateId": novel.grid_image_prompt_template_id,
            "gridClipPlanPromptTemplateId": novel.grid_clip_plan_prompt_template_id,
            "gridH3PhaseBPromptTemplateId": novel.grid_h3_phase_b_prompt_template_id,
            "aspectRatio": novel.aspect_ratio or "16:9",
            "createdAt": novel.created_at.isoformat() if novel.created_at else None,
            "updatedAt": novel.updated_at.isoformat() if novel.updated_at else None,
        }
