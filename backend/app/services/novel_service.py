"""
小说服务层

封装小说相关的业务逻辑
"""
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.novel import Novel, Chapter, Character, Scene
from app.models.prompt_template import PromptTemplate
from app.core.database import SessionLocal
from app.utils.time_utils import format_datetime
from app.services.llm_service import LLMService
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage
from app.services.prompt_builder import get_style
from app.utils.path_utils import url_to_local_path
from app.utils.image_utils import load_chinese_font, merge_character_images


class NovelService:
    """小说服务"""
    
    def __init__(self, db: Session = None):
        self.db = db
        self.comfyui_service = ComfyUIService()
    
    def get_llm_service(self) -> LLMService:
        """获取 LLMService 实例（每次调用创建新实例以获取最新配置）"""
        return LLMService()
    
    # ==================== 角色解析 ====================
    
    async def parse_characters(
        self,
        novel_id: str,
        chapters: List[Chapter],
        start_chapter: int = None,
        end_chapter: int = None,
        is_incremental: bool = False,
        character_repo = None
    ) -> Dict[str, Any]:
        """
        解析小说内容，自动提取角色信息
        
        Args:
            novel_id: 小说ID
            chapters: 章节列表
            start_chapter: 起始章节号
            end_chapter: 结束章节号
            is_incremental: 是否增量更新
            character_repo: 角色仓库
            
        Returns:
            解析结果
        """
        # 构造章节范围描述
        source_range = None
        if start_chapter is not None or end_chapter is not None:
            start_desc = f"第{start_chapter}章" if start_chapter is not None else "第1章"
            end_desc = f"第{end_chapter}章" if end_chapter is not None else f"第{chapters[-1].number}章"
            source_range = f"{start_desc}至{end_desc}"
        
        full_text = "\n\n".join([c.content for c in chapters if c.content])
        if not full_text.strip():
            return {"success": False, "message": "章节内容为空"}
        
        try:
            # 调用 LLM 解析文本提取角色
            result = await self.get_llm_service().parse_novel_text(full_text, novel_id=novel_id, source_range=source_range)
            
            if "error" in result:
                return {"success": False, "message": f"解析失败: {result['error']}"}
            
            characters_data = result.get("characters", [])
            if not characters_data:
                return {"success": True, "data": [], "message": "未识别到角色"}
            
            # 创建角色记录
            created_characters = []
            updated_characters = []
            
            for char_data in characters_data:
                name = char_data.get("name", "").strip()
                if not name:
                    continue
                
                # 检查是否已存在
                existing = character_repo.get_by_name(novel_id, name)
                
                if existing:
                    # 增量更新模式：保留原有信息，只更新新解析的信息
                    if is_incremental:
                        if not existing.description and char_data.get("description"):
                            existing.description = char_data.get("description")
                        if not existing.appearance and char_data.get("appearance"):
                            existing.appearance = char_data.get("appearance")
                        if source_range:
                            if existing.source_range:
                                existing.source_range += f", {source_range}"
                            else:
                                existing.source_range = source_range
                    else:
                        # 全量更新模式：直接覆盖
                        existing.description = char_data.get("description", existing.description)
                        existing.appearance = char_data.get("appearance", existing.appearance)
                        existing.source_range = source_range
                    
                    existing.last_parsed_at = datetime.utcnow()
                    updated_characters.append(existing)
                else:
                    # 创建新角色
                    character = Character(
                        novel_id=novel_id,
                        name=name,
                        description=char_data.get("description", ""),
                        appearance=char_data.get("appearance", ""),
                        start_chapter=start_chapter,
                        end_chapter=end_chapter,
                        is_incremental=is_incremental,
                        source_range=source_range,
                        last_parsed_at=datetime.utcnow()
                    )
                    self.db.add(character)
                    created_characters.append(character)
            
            self.db.commit()
            
            # 刷新对象以获取 ID
            for char in created_characters + updated_characters:
                self.db.refresh(char)
            
            # 构造响应消息
            message_parts = []
            if created_characters:
                message_parts.append(f"新增 {len(created_characters)} 个角色")
            if updated_characters:
                message_parts.append(f"更新 {len(updated_characters)} 个角色")
            
            return {
                "success": True,
                "data": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "description": c.description,
                        "appearance": c.appearance,
                        "startChapter": c.start_chapter,
                        "endChapter": c.end_chapter,
                        "isIncremental": c.is_incremental,
                        "sourceRange": c.source_range,
                        "lastParsedAt": format_datetime(c.last_parsed_at)
                    }
                    for c in created_characters + updated_characters
                ],
                "message": "，".join(message_parts) if message_parts else "未识别到角色",
                "statistics": {
                    "created": len(created_characters),
                    "updated": len(updated_characters),
                    "total": len(created_characters) + len(updated_characters)
                }
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"解析异常: {str(e)}"}
    
    # ==================== 场景解析 ====================
    
    async def parse_scenes_from_chapters(
        self,
        novel_id: str,
        chapters: List[Chapter],
        mode: str = "incremental",
        scene_repo = None,
        prompt_template_repo = None
    ) -> Dict[str, Any]:
        """
        解析多章节内容，提取场景信息
        
        Args:
            novel_id: 小说ID
            chapters: 章节列表
            mode: 解析模式 (incremental/overwrite)
            scene_repo: 场景仓库
            prompt_template_repo: 提示词模板仓库
            
        Returns:
            解析结果
        """
        if not chapters:
            return {"success": False, "message": "没有找到章节"}
        
        # 构建章节范围说明
        if len(chapters) == 1:
            source_range = f"第{chapters[0].number}章"
        else:
            source_range = f"第{chapters[0].number}章 ~ 第{chapters[-1].number}章"
        
        # 合并章节内容
        combined_content = ""
        for chapter in chapters:
            combined_content += f"\n\n【第{chapter.number}章 {chapter.title}】\n{chapter.content or ''}"
        
        # 获取场景解析提示词模板
        prompt_template = None
        if prompt_template_repo:
            templates = prompt_template_repo.list_by_type('scene_parse')
            prompt_template = templates[0].template if templates else None
        
        try:
            # 调用 LLM 解析场景
            result = await self.get_llm_service().parse_scenes(
                novel_id=novel_id,
                chapter_content=combined_content[:150000],  # 限制长度
                chapter_title=source_range,
                prompt_template=prompt_template
            )
            
            if result.get("error"):
                return {"success": False, "message": result["error"]}
            
            scenes_data = result.get("scenes", [])
            
            # 获取现有场景
            existing_scene_names = scene_repo.get_dict_by_novel(novel_id)
            
            created_scenes = []
            updated_scenes = []
            
            for scene_data in scenes_data:
                name = scene_data.get("name", "")
                if not name:
                    continue
                
                if name in existing_scene_names:
                    # 更新现有场景
                    existing = existing_scene_names[name]
                    scene_repo.update(
                        existing,
                        description=scene_data.get("description", existing.description),
                        setting=scene_data.get("setting", existing.setting),
                        start_chapter=min(existing.start_chapter, chapters[0].number) if existing.start_chapter and mode == "incremental" else chapters[0].number,
                        end_chapter=max(existing.end_chapter, chapters[-1].number) if existing.end_chapter and mode == "incremental" else chapters[-1].number,
                        is_incremental=mode == "incremental",
                        source_range=source_range,
                        last_parsed_at=datetime.utcnow()
                    )
                    updated_scenes.append(existing)
                else:
                    # 创建新场景
                    scene = scene_repo.create(
                        novel_id=novel_id,
                        name=name,
                        description=scene_data.get("description", ""),
                        setting=scene_data.get("setting", ""),
                        start_chapter=chapters[0].number,
                        end_chapter=chapters[-1].number,
                        source_range=source_range,
                    )
                    # 更新增量标记
                    if mode == "incremental":
                        scene.is_incremental = True
                        scene.last_parsed_at = datetime.utcnow()
                        self.db.commit()
                    created_scenes.append(scene)
            
            # 构造响应消息
            message_parts = []
            if created_scenes:
                message_parts.append(f"新增 {len(created_scenes)} 个场景")
            if updated_scenes:
                message_parts.append(f"更新 {len(updated_scenes)} 个场景")
            
            return {
                "success": True,
                "data": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "setting": s.setting,
                        "startChapter": s.start_chapter,
                        "endChapter": s.end_chapter,
                        "isIncremental": s.is_incremental,
                        "sourceRange": s.source_range,
                        "lastParsedAt": format_datetime(s.last_parsed_at)
                    }
                    for s in created_scenes + updated_scenes
                ],
                "message": "，".join(message_parts) if message_parts else "未识别到场景",
                "statistics": {
                    "created": len(created_scenes),
                    "updated": len(updated_scenes),
                    "total": len(created_scenes) + len(updated_scenes)
                }
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"解析异常: {str(e)}"}
    
    async def parse_scenes(
        self,
        novel_id: str,
        chapter: Chapter,
        is_incremental: bool = True,
        scene_repo = None
    ) -> Dict[str, Any]:
        """
        解析单章节内容，提取场景信息
        
        Args:
            novel_id: 小说ID
            chapter: 章节对象
            is_incremental: 是否增量更新
            scene_repo: 场景仓库
            
        Returns:
            解析结果
        """
        if not chapter.content:
            return {"success": False, "message": "章节内容为空"}
        
        # 获取场景解析提示词模板
        template = self.db.query(PromptTemplate).filter(
            PromptTemplate.type == 'scene_parse',
            PromptTemplate.is_system == True
        ).order_by(PromptTemplate.created_at.asc()).first()
        
        prompt_template = template.template if template else None
        
        try:
            source_range = f"第{chapter.number}章"
            
            # 调用 LLM 解析场景
            result = await self.get_llm_service().parse_scenes(
                novel_id=novel_id,
                chapter_content=chapter.content[:20000],  # 限制长度
                chapter_title=source_range,
                prompt_template=prompt_template
            )
            
            if result.get("error"):
                return {"success": False, "message": result["error"]}
            
            scenes_data = result.get("scenes", [])
            
            # 获取现有场景
            existing_scene_names = scene_repo.get_dict_by_novel(novel_id)
            
            created_scenes = []
            updated_scenes = []
            
            for scene_data in scenes_data:
                name = scene_data.get("name", "")
                if not name:
                    continue
                
                if name in existing_scene_names:
                    # 更新现有场景
                    existing = existing_scene_names[name]
                    
                    if is_incremental:
                        if not existing.description and scene_data.get("description"):
                            existing.description = scene_data.get("description")
                        if not existing.setting and scene_data.get("setting"):
                            existing.setting = scene_data.get("setting")
                        if existing.source_range:
                            if source_range not in existing.source_range:
                                existing.source_range += f", {source_range}"
                        else:
                            existing.source_range = source_range
                    else:
                        existing.description = scene_data.get("description", existing.description)
                        existing.setting = scene_data.get("setting", existing.setting)
                        existing.source_range = source_range
                    
                    existing.is_incremental = is_incremental
                    existing.last_parsed_at = datetime.utcnow()
                    updated_scenes.append(existing)
                else:
                    # 创建新场景
                    scene = Scene(
                        novel_id=novel_id,
                        name=name,
                        description=scene_data.get("description", ""),
                        setting=scene_data.get("setting", ""),
                        start_chapter=chapter.number,
                        end_chapter=chapter.number,
                        is_incremental=is_incremental,
                        source_range=source_range,
                        last_parsed_at=datetime.utcnow()
                    )
                    self.db.add(scene)
                    created_scenes.append(scene)
            
            self.db.commit()
            
            # 刷新对象
            for s in created_scenes + updated_scenes:
                self.db.refresh(s)
            
            # 构造响应消息
            message_parts = []
            if created_scenes:
                message_parts.append(f"新增 {len(created_scenes)} 个场景")
            if updated_scenes:
                message_parts.append(f"更新 {len(updated_scenes)} 个场景")
            
            return {
                "success": True,
                "data": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "setting": s.setting,
                        "startChapter": s.start_chapter,
                        "endChapter": s.end_chapter,
                        "isIncremental": s.is_incremental,
                        "sourceRange": s.source_range,
                        "lastParsedAt": format_datetime(s.last_parsed_at)
                    }
                    for s in created_scenes + updated_scenes
                ],
                "message": "，".join(message_parts) if message_parts else "未识别到场景",
                "statistics": {
                    "created": len(created_scenes),
                    "updated": len(updated_scenes),
                    "total": len(created_scenes) + len(updated_scenes)
                }
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "message": f"解析异常: {str(e)}"}
    
    # ==================== 章节拆分 ====================
    
    async def split_chapter(
        self,
        novel: Novel,
        chapter: Chapter,
        character_names: List[str],
        scene_names: List[str]
    ) -> Dict[str, Any]:
        """
        使用小说配置的拆分提示词将章节拆分为分镜
        
        Args:
            novel: 小说对象
            chapter: 章节对象
            character_names: 角色名称列表
            scene_names: 场景名称列表
            
        Returns:
            拆分结果
        """
        # 检查 LLM 配置
        llm_service = self.get_llm_service()
        if not llm_service.api_key and llm_service.provider != "ollama":
            return {
                "success": False,
                "data": {
                    "error": "LLM API Key 未配置，请在系统设置中配置 API Key",
                    "chapter": chapter.title,
                    "characters": [],
                    "scenes": [],
                    "shots": []
                }
            }
        
        if not llm_service.api_url:
            return {
                "success": False,
                "data": {
                    "error": "LLM API URL 未配置，请在系统设置中配置 API URL",
                    "chapter": chapter.title,
                    "characters": [],
                    "scenes": [],
                    "shots": []
                }
            }
        
        # 获取拆分提示词模板
        prompt_template = None
        if novel.chapter_split_prompt_template_id:
            prompt_template = self.db.query(PromptTemplate).filter(
                PromptTemplate.id == novel.chapter_split_prompt_template_id
            ).first()
        
        # 如果没有配置，使用默认模板
        if not prompt_template:
            prompt_template = self.db.query(PromptTemplate).filter(
                PromptTemplate.type == "chapter_split",
                PromptTemplate.is_system == True
            ).first()
        
        if not prompt_template:
            return {"success": False, "message": "未找到章节拆分提示词模板"}
        
        # 获取风格提示词
        style, style_template = get_style(self.db, novel, "character")
        print(f"[SplitChapter] Using style: {style}")
        
        # 调用 LLM 进行拆分
        result = await llm_service.split_chapter_with_prompt(
            chapter_title=chapter.title,
            chapter_content=chapter.content or "",
            prompt_template=prompt_template.template,
            word_count=50,
            character_names=character_names,
            scene_names=scene_names,
            style=style
        )
        
        # 保存解析结果到章节
        chapter.parsed_data = json.dumps(result, ensure_ascii=False)
        self.db.commit()
        
        return {
            "success": True,
            "data": result
        }

    
    # ==================== 图片合并 ====================
    
    def merge_character_images(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        character_images: List[Tuple[str, str]]
    ) -> Optional[str]:
        """
        合并多个角色图片为一个参考图（委托给工具函数）
        
        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引
            character_images: [(角色名, 图片路径), ...]
            
        Returns:
            合并后的图片路径，失败返回 None
        """
        return merge_character_images(
            novel_id, chapter_id, shot_index, character_images, file_storage
        )


# 后台任务函数已移至独立模块
from app.services.media_task_service import (
    generate_shot_task,
    generate_shot_video_task,
    generate_transition_video_task
)
