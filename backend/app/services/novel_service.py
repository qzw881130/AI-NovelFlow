"""
小说服务层

封装小说相关的业务逻辑和后台任务
"""
import json
import os
import asyncio
import httpx
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from sqlalchemy.orm import Session

from app.models.novel import Novel, Chapter, Character, Scene
from app.models.prompt_template import PromptTemplate
from app.models.task import Task
from app.models.workflow import Workflow
from app.core.database import SessionLocal
from app.core.utils import format_datetime
from app.services.llm_service import LLMService
from app.services.comfyui import ComfyUIService
from app.services.file_storage import file_storage


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
        
        # 获取小说配置的角色提示词模板 style
        style = "anime style, high quality, detailed"  # 默认风格
        if novel.prompt_template_id:
            character_prompt_template = self.db.query(PromptTemplate).filter(
                PromptTemplate.id == novel.prompt_template_id
            ).first()
            if character_prompt_template and character_prompt_template.template:
                style = self._extract_style_from_template(character_prompt_template.template)
                print(f"[SplitChapter] Using style from character prompt template: {style}")
        
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
    
    def _extract_style_from_template(self, template: str) -> str:
        """从模板中提取 style"""
        import re
        try:
            template_data = json.loads(template)
            if isinstance(template_data, dict) and "style" in template_data:
                return template_data["style"]
            else:
                style = template.replace("{appearance}", "").replace("{description}", "").strip(", ")
        except json.JSONDecodeError:
            style = template.replace("{appearance}", "").replace("{description}", "").strip(", ")
            style = re.sub(r',\s*,', ',', style)
            style = re.sub(r'\s+', ' ', style)
            style = style.strip(", ")
        return style
    
    # ==================== 图片合并 ====================
    
    def merge_character_images(
        self,
        novel_id: str,
        chapter_id: str,
        shot_index: int,
        character_images: List[Tuple[str, str]]
    ) -> Optional[str]:
        """
        合并多个角色图片为一个参考图
        
        Args:
            novel_id: 小说ID
            chapter_id: 章节ID
            shot_index: 分镜索引
            character_images: [(角色名, 图片路径), ...]
            
        Returns:
            合并后的图片路径，失败返回 None
        """
        if not character_images:
            return None
        
        try:
            # 删除旧的合并角色图
            story_dir = file_storage._get_story_dir(novel_id)
            chapter_short = chapter_id[:8] if chapter_id else "unknown"
            merged_dir = story_dir / f"chapter_{chapter_short}" / "merged_characters"
            if merged_dir.exists():
                import glob
                old_files = glob.glob(str(merged_dir / f"shot_{shot_index:03d}_*_characters.png"))
                for old_file in old_files:
                    try:
                        os.remove(old_file)
                        print(f"[MergeCharacters] Removed old merged character image: {old_file}")
                    except Exception as e:
                        print(f"[MergeCharacters] Failed to remove old file {old_file}: {e}")
            
            # 获取角色名列表
            character_names = [name for name, _ in character_images]
            merged_path = file_storage.get_merged_characters_path(novel_id, chapter_id, shot_index, character_names)
            
            # 计算布局
            count = len(character_images)
            if count == 1:
                cols, rows = 1, 1
            elif count <= 3:
                cols, rows = 1, count
            elif count == 4:
                cols, rows = 2, 2
            elif count <= 6:
                cols, rows = 3, 2
            else:
                cols = 3
                rows = (count + 2) // 3
            
            # 加载所有图片
            images = []
            for char_name, img_path in character_images:
                img = Image.open(img_path)
                images.append((char_name, img))
            
            # 设置布局参数
            name_height = 24
            padding = 15
            img_spacing = 10
            text_offset = 5
            
            # 使用原图，不进行缩放
            processed_images = [(char_name, img.copy()) for char_name, img in images]
            
            # 计算每列的最大宽度
            col_widths = []
            for col in range(cols):
                max_w = 0
                for idx in range(col, len(processed_images), cols):
                    _, img = processed_images[idx]
                    max_w = max(max_w, img.width)
                col_widths.append(max_w)
            
            # 计算每行的实际高度
            row_heights = []
            for row in range(rows):
                max_h = 0
                for idx in range(row * cols, min((row + 1) * cols, len(processed_images))):
                    _, img = processed_images[idx]
                    max_h = max(max_h, img.height)
                row_heights.append(max_h + name_height + text_offset)
            
            # 计算画布尺寸
            canvas_width = sum(col_widths) + (cols - 1) * img_spacing + 2 * padding
            canvas_height = sum(row_heights) + 2 * padding
            canvas = Image.new('RGB', (canvas_width, canvas_height), (255, 255, 255))
            draw = ImageDraw.Draw(canvas)
            
            # 加载字体
            font = self._load_chinese_font(16)
            
            # 绘制每个角色
            current_y = padding
            for idx, (char_name, img) in enumerate(processed_images):
                col = idx % cols
                row = idx // cols
                
                x = padding + sum(col_widths[:col]) + col * img_spacing
                y = current_y
                
                img_x = x + (col_widths[col] - img.width) // 2
                img_y = y + (row_heights[row] - name_height - text_offset - img.height) // 2
                canvas.paste(img, (img_x, img_y))
                
                text_bbox = draw.textbbox((0, 0), char_name, font=font)
                text_width = text_bbox[2] - text_bbox[0]
                text_x = x + (col_widths[col] - text_width) // 2
                text_y = img_y + img.height + text_offset
                draw.text((text_x, text_y), char_name, fill=(51, 51, 51), font=font)
                
                if col == cols - 1 or idx == len(processed_images) - 1:
                    current_y += row_heights[row]
            
            # 保存合并图片
            canvas.save(merged_path, "PNG")
            print(f"[MergeCharacters] Merged character image saved: {merged_path}")
            
            return str(merged_path)
            
        except Exception as e:
            print(f"[MergeCharacters] Failed to merge character images: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _load_chinese_font(self, size: int) -> ImageFont:
        """加载中文字体"""
        font_paths = [
            # macOS
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            # Windows
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            # Linux
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        
        for font_path in font_paths:
            try:
                return ImageFont.truetype(font_path, size)
            except:
                continue
        
        return ImageFont.load_default()
    
    # ==================== 路径转换工具 ====================
    
    @staticmethod
    def url_to_local_path(url: str) -> Optional[str]:
        """将 URL 转换为本地路径"""
        if not url or not url.startswith("/api/files/"):
            return None
        
        relative_path = url.replace("/api/files/", "")
        relative_path = relative_path.lstrip("\\/")
        relative_path = relative_path.replace("\\", "/")
        path_parts = relative_path.split("/")
        
        full_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "user_story", *path_parts
        )
        full_path = os.path.abspath(full_path)
        
        if os.path.exists(full_path):
            return full_path
        return None


# ==================== 后台任务函数 ====================

async def generate_shot_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    shot_description: str,
    workflow_id: str
):
    """
    后台任务：生成分镜图片
    """
    db = SessionLocal()
    try:
        # 获取任务
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        
        # 更新任务状态为运行中
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.current_step = "准备生成环境..."
        db.commit()
        
        # 获取章节和小说
        chapter = db.query(Chapter).filter(
            Chapter.id == chapter_id,
            Chapter.novel_id == novel_id
        ).first()
        
        if not chapter:
            task.status = "failed"
            task.error_message = "章节不存在"
            db.commit()
            return
        
        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        if not novel:
            task.status = "failed"
            task.error_message = "小说不存在"
            db.commit()
            return
        
        # 解析章节数据
        parsed_data = json.loads(chapter.parsed_data) if isinstance(chapter.parsed_data, str) else chapter.parsed_data
        shots = parsed_data.get("shots", [])
        
        if shot_index < 1 or shot_index > len(shots):
            task.status = "failed"
            task.error_message = "分镜索引超出范围"
            db.commit()
            return
        
        shot = shots[shot_index - 1]
        shot_characters = shot.get("characters", [])
        shot_scene = shot.get("scene", "")
        
        print(f"[ShotTask {task_id}] Novel: {novel_id}, Chapter: {chapter_id}, Shot: {shot_index}")
        print(f"[ShotTask {task_id}] Description: {shot_description}")
        print(f"[ShotTask {task_id}] Characters: {shot_characters}")
        
        # 获取工作流
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            task.status = "failed"
            task.error_message = "工作流不存在"
            db.commit()
            return
        
        # 获取节点映射
        node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}
        print(f"[ShotTask {task_id}] Node mapping: {node_mapping}")
        
        # 先保存提示词
        task.prompt_text = shot_description
        db.commit()
        
        # 获取小说配置的角色提示词模板 style
        style = "anime style, high quality, detailed"
        if novel.prompt_template_id:
            prompt_template = db.query(PromptTemplate).filter(
                PromptTemplate.id == novel.prompt_template_id
            ).first()
            if prompt_template and prompt_template.template:
                import re
                try:
                    template_data = json.loads(prompt_template.template)
                    if isinstance(template_data, dict) and "style" in template_data:
                        style = template_data["style"]
                    else:
                        style = prompt_template.template.replace("{appearance}", "").replace("{description}", "").strip(", ")
                except json.JSONDecodeError:
                    style = prompt_template.template.replace("{appearance}", "").replace("{description}", "").strip(", ")
                    style = re.sub(r',\s*,', ',', style)
                    style = re.sub(r'\s+', ' ', style)
                    style = style.strip(", ")
            print(f"[ShotTask {task_id}] Using style from prompt template: {style}")
        
        comfyui_service = ComfyUIService()
        service = NovelService(db)
        
        # 合并角色图片
        character_reference_path = None
        if shot_characters:
            task.current_step = f"合并角色图片: {', '.join(shot_characters)}"
            db.commit()
            
            character_images = []
            print(f"[ShotTask {task_id}] Looking for {len(shot_characters)} characters: {shot_characters}")
            for char_name in shot_characters:
                character = db.query(Character).filter(
                    Character.novel_id == novel_id,
                    Character.name == char_name
                ).first()
                print(f"[ShotTask {task_id}] Character '{char_name}': found={character is not None}, has_image={character.image_url if character else None}")
                if character and character.image_url:
                    full_path = NovelService.url_to_local_path(character.image_url)
                    if full_path:
                        character_images.append((char_name, full_path))
                        print(f"[ShotTask {task_id}] Found character image: {char_name} -> {full_path}")
            
            print(f"[ShotTask {task_id}] Total character images found: {len(character_images)}")
            if character_images:
                merged_path = service.merge_character_images(novel_id, chapter_id, shot_index, character_images)
                
                if merged_path:
                    character_reference_path = merged_path
                    
                    # 构建合并角色图的 URL 并保存到 parsed_data
                    merged_relative_path = str(merged_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
                    merged_url = f"/api/files/{merged_relative_path.lstrip('/')}"
                    
                    latest_parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {"shots": []}
                    if "shots" not in latest_parsed_data:
                        latest_parsed_data["shots"] = []
                    while len(latest_parsed_data["shots"]) < shot_index:
                        latest_parsed_data["shots"].append({})
                    latest_parsed_data["shots"][shot_index - 1]["merged_character_image"] = merged_url
                    chapter.parsed_data = json.dumps(latest_parsed_data, ensure_ascii=False)
                    
                    print(f"[ShotTask {task_id}] Merged character image saved: {merged_path}, URL: {merged_url}")
                    task.current_step = f"已合并 {len(character_images)} 个角色图片"
                    db.commit()
                else:
                    print(f"[ShotTask {task_id}] Failed to merge character images")
                    task.current_step = "角色图片合并失败，继续生成..."
                    db.commit()
        
        # 处理场景图
        scene_reference_path = None
        if shot_scene:
            task.current_step = f"查找场景图: {shot_scene}"
            db.commit()
            
            scene = db.query(Scene).filter(
                Scene.novel_id == novel_id,
                Scene.name == shot_scene
            ).first()
            
            print(f"[ShotTask {task_id}] Scene '{shot_scene}': found={scene is not None}, has_image={scene.image_url if scene else None}")
            
            if scene and scene.image_url:
                full_path = NovelService.url_to_local_path(scene.image_url)
                if full_path:
                    scene_reference_path = full_path
                    print(f"[ShotTask {task_id}] Found scene image: {shot_scene} -> {full_path}")
        
        # 构建工作流
        task.current_step = "构建工作流..."
        db.commit()
        
        submitted_workflow = comfyui_service.builder.build_shot_workflow(
            prompt=shot_description,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            style=style
        )
        
        # 上传参考图
        if character_reference_path or scene_reference_path:
            task.current_step = "上传参考图..."
            db.commit()
            print(f"[ShotTask {task_id}] Uploading reference images before submission")
            
            character_uploaded_filename = None
            if character_reference_path:
                upload_result = await comfyui_service.client.upload_image(character_reference_path)
                if upload_result.get("success"):
                    character_uploaded_filename = upload_result.get("filename")
                    print(f"[ShotTask {task_id}] Character image uploaded successfully: {character_uploaded_filename}")
                else:
                    print(f"[ShotTask {task_id}] Failed to upload character image: {upload_result.get('message')}")
            
            scene_uploaded_filename = None
            if scene_reference_path:
                upload_result = await comfyui_service.client.upload_image(scene_reference_path)
                if upload_result.get("success"):
                    scene_uploaded_filename = upload_result.get("filename")
                    print(f"[ShotTask {task_id}] Scene image uploaded successfully: {scene_uploaded_filename}")
                else:
                    print(f"[ShotTask {task_id}] Failed to upload scene image: {upload_result.get('message')}")
            
            if character_uploaded_filename or scene_uploaded_filename:
                character_node_id = node_mapping.get("character_reference_image_node_id")
                scene_node_id = node_mapping.get("scene_reference_image_node_id")
                
                print(f"[ShotTask {task_id}] Node mapping - character_node: {character_node_id}, scene_node: {scene_node_id}")
                
                if character_uploaded_filename and character_node_id:
                    node_id_str = str(character_node_id)
                    if node_id_str in submitted_workflow:
                        submitted_workflow[node_id_str]["inputs"]["image"] = character_uploaded_filename
                        print(f"[ShotTask {task_id}] Set LoadImage node {node_id_str} to character image: {character_uploaded_filename}")
                    else:
                        print(f"[ShotTask {task_id}] Warning: character_reference_image_node_id '{node_id_str}' not found in workflow")
                
                if scene_uploaded_filename and scene_node_id:
                    node_id_str = str(scene_node_id)
                    if node_id_str in submitted_workflow:
                        submitted_workflow[node_id_str]["inputs"]["image"] = scene_uploaded_filename
                        print(f"[ShotTask {task_id}] Set LoadImage node {node_id_str} to scene image: {scene_uploaded_filename}")
                    else:
                        print(f"[ShotTask {task_id}] Warning: scene_reference_image_node_id '{node_id_str}' not found in workflow")
                
                task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
                db.commit()
                print(f"[ShotTask {task_id}] Saved workflow with LoadImage replacement to task")
        else:
            task.workflow_json = json.dumps(submitted_workflow, ensure_ascii=False, indent=2)
            db.commit()
            print(f"[ShotTask {task_id}] Saved submitted workflow to task (no character reference)")
        
        # 调用 ComfyUI 生成图片
        task.current_step = "正在调用 ComfyUI 生成图片..."
        task.progress = 30
        db.commit()
        
        result = await comfyui_service.generate_shot_image_with_workflow(
            prompt=shot_description,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            character_reference_path=None,
            scene_reference_path=None,
            workflow=submitted_workflow,
            style=style
        )
        
        print(f"[ShotTask {task_id}] Generation result: {result}")
        
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
            print(f"[ShotTask {task_id}] Saved final workflow after task completion")
        
        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]
            print(f"[ShotTask {task_id}] Saved ComfyUI prompt_id: {result['prompt_id']}")
        
        if not result.get("success"):
            task.status = "failed"
            task.error_message = result.get("message", "生成失败")
            task.current_step = "生成失败"
            db.commit()
            return
        
        # 下载生成的图片
        task.current_step = "正在下载生成的图片..."
        task.progress = 80
        db.commit()
        
        image_url = result.get("image_url")
        if image_url:
            local_path = await file_storage.download_image(
                url=image_url,
                novel_id=novel_id,
                character_name=f"shot_{shot_index:03d}",
                image_type="shot",
                chapter_id=chapter_id
            )
            
            if local_path:
                relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                local_url = f"/api/files/{relative_path.lstrip('/')}"
                
                task.status = "completed"
                task.progress = 100
                task.result_url = local_url
                task.current_step = "生成完成"
                task.completed_at = datetime.utcnow()
                db.commit()
                
                db.refresh(chapter)
                latest_parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {"shots": []}
                
                if "shots" not in latest_parsed_data:
                    latest_parsed_data["shots"] = []
                while len(latest_parsed_data["shots"]) < shot_index:
                    latest_parsed_data["shots"].append({})
                
                latest_parsed_data["shots"][shot_index - 1]["image_path"] = str(local_path)
                latest_parsed_data["shots"][shot_index - 1]["image_url"] = local_url
                
                chapter.parsed_data = json.dumps(latest_parsed_data, ensure_ascii=False)
                
                shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
                if not isinstance(shot_images, list):
                    shot_images = []
                while len(shot_images) < shot_index:
                    shot_images.append(None)
                shot_images[shot_index - 1] = local_url
                chapter.shot_images = json.dumps(shot_images, ensure_ascii=False)
                
                db.commit()
                
                print(f"[ShotTask {task_id}] Completed, image saved: {local_path}")
            else:
                task.status = "completed"
                task.progress = 100
                task.result_url = image_url
                task.current_step = "生成完成（使用远程图片）"
                task.completed_at = datetime.utcnow()
                db.commit()
                
                db.refresh(chapter)
                latest_parsed_data = json.loads(chapter.parsed_data) if chapter.parsed_data else {"shots": []}
                if "shots" not in latest_parsed_data:
                    latest_parsed_data["shots"] = []
                while len(latest_parsed_data["shots"]) < shot_index:
                    latest_parsed_data["shots"].append({})
                latest_parsed_data["shots"][shot_index - 1]["image_url"] = image_url
                chapter.parsed_data = json.dumps(latest_parsed_data, ensure_ascii=False)
                
                shot_images = json.loads(chapter.shot_images) if chapter.shot_images else []
                if not isinstance(shot_images, list):
                    shot_images = []
                while len(shot_images) < shot_index:
                    shot_images.append(None)
                shot_images[shot_index - 1] = image_url
                chapter.shot_images = json.dumps(shot_images, ensure_ascii=False)
                
                db.commit()
        else:
            task.status = "failed"
            task.error_message = "未获取到图片URL"
            task.current_step = "生成失败"
            db.commit()
            
    except Exception as e:
        print(f"[ShotTask {task_id}] Error: {e}")
        import traceback
        traceback.print_exc()
        
        try:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"
            db.commit()
        except:
            pass
    finally:
        db.close()


async def generate_shot_video_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    workflow_id: str,
    shot_image_url: str
):
    """
    后台任务：生成分镜视频
    """
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.current_step = "准备生成视频..."
        db.commit()
        
        chapter = db.query(Chapter).filter(
            Chapter.id == chapter_id,
            Chapter.novel_id == novel_id
        ).first()
        
        if not chapter:
            task.status = "failed"
            task.error_message = "章节不存在"
            db.commit()
            return
        
        novel = db.query(Novel).filter(Novel.id == novel_id).first()
        if not novel:
            task.status = "failed"
            task.error_message = "小说不存在"
            db.commit()
            return
        
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            task.status = "failed"
            task.error_message = "工作流不存在"
            db.commit()
            return
        
        node_mapping = json.loads(workflow.node_mapping) if workflow.node_mapping else {}
        print(f"[VideoTask {task_id}] Node mapping: {node_mapping}")
        
        parsed_data = json.loads(chapter.parsed_data) if isinstance(chapter.parsed_data, str) else chapter.parsed_data
        shots = parsed_data.get("shots", [])
        shot = shots[shot_index - 1]
        shot_description = shot.get("video_description") or shot.get("description", "")
        
        task.prompt_text = shot_description
        db.commit()
        
        duration = shot.get("duration", 4)
        fps = 25
        raw_frame_count = int(fps * duration)
        frame_count = ((raw_frame_count // 8) * 8) + 1
        print(f"[VideoTask {task_id}] Duration: {duration}s, FPS: {fps}, Raw frames: {raw_frame_count}, Adjusted frames: {frame_count}")
        
        character_reference_path = None
        if shot_image_url:
            full_path = NovelService.url_to_local_path(shot_image_url)
            if full_path:
                character_reference_path = full_path
                print(f"[VideoTask {task_id}] Found shot image: {full_path}")
            else:
                print(f"[VideoTask {task_id}] Shot image not found at: {shot_image_url}")
        
        task.current_step = "正在调用 ComfyUI 生成视频..."
        task.progress = 30
        db.commit()
        
        comfyui_service = ComfyUIService()
        result = await comfyui_service.generate_shot_video_with_workflow(
            prompt=shot_description,
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            aspect_ratio=novel.aspect_ratio or "16:9",
            character_reference_path=character_reference_path,
            frame_count=frame_count
        )
        
        print(f"[VideoTask {task_id}] Generation result: {result}")
        
        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]
            print(f"[VideoTask {task_id}] Saved ComfyUI prompt_id: {result['prompt_id']}")
        
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
            print(f"[VideoTask {task_id}] Saved submitted workflow to task")
        
        if not result.get("success"):
            task.status = "failed"
            task.error_message = result.get("message", "生成失败")
            task.current_step = "生成失败"
            db.commit()
            return
        
        task.current_step = "正在下载生成的视频..."
        task.progress = 80
        db.commit()
        
        video_url = result.get("video_url")
        if video_url:
            local_path = await file_storage.download_video(
                url=video_url,
                novel_id=novel_id,
                chapter_id=chapter_id,
                shot_number=shot_index
            )
            
            if local_path:
                relative_path = local_path.replace(str(file_storage.base_dir), "").replace("\\", "/")
                local_url = f"/api/files/{relative_path.lstrip('/')}"
                
                shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
                if not isinstance(shot_videos, list):
                    shot_videos = []
                
                while len(shot_videos) < shot_index:
                    shot_videos.append(None)
                
                shot_videos[shot_index - 1] = local_url
                chapter.shot_videos = json.dumps(shot_videos)
                
                task.status = "completed"
                task.progress = 100
                task.result_url = local_url
                task.current_step = "生成完成"
                task.completed_at = datetime.utcnow()
                db.commit()
                
                print(f"[VideoTask {task_id}] Video saved: {local_url}")
            else:
                task.status = "failed"
                task.error_message = "下载视频失败"
                task.current_step = "下载失败"
                db.commit()
        else:
            task.status = "failed"
            task.error_message = "未获取到视频URL"
            task.current_step = "生成失败"
            db.commit()
            
    except Exception as e:
        print(f"[VideoTask {task_id}] Error: {e}")
        import traceback
        traceback.print_exc()
        
        try:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"
            db.commit()
        except:
            pass
    finally:
        db.close()


async def generate_transition_video_task(
    task_id: str,
    novel_id: str,
    chapter_id: str,
    from_index: int,
    to_index: int,
    workflow_id: str,
    frame_count: int = 49
):
    """后台任务：生成转场视频（从视频提取首帧/尾帧）"""
    db = SessionLocal()
    
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            print(f"[TransitionTask] Task {task_id} not found")
            return
        
        task.status = "running"
        task.current_step = "准备生成转场视频..."
        task.progress = 10
        db.commit()
        
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
        if not chapter:
            raise Exception("章节不存在")
        
        shot_videos = json.loads(chapter.shot_videos) if chapter.shot_videos else []
        
        first_video_url = shot_videos[from_index - 1] if from_index <= len(shot_videos) else None
        second_video_url = shot_videos[to_index - 1] if to_index <= len(shot_videos) else None
        
        if not first_video_url or not second_video_url:
            raise Exception("分镜视频尚未生成")
        
        # 转换URL为本地路径
        first_video_path = NovelService.url_to_local_path(first_video_url)
        second_video_path = NovelService.url_to_local_path(second_video_url)
        
        if not first_video_path or not second_video_path:
            raise Exception("无法解析视频路径")
        
        if not os.path.exists(first_video_path) or not os.path.exists(second_video_path):
            raise Exception("视频文件不存在")
        
        from pathlib import Path
        first_video_name = Path(first_video_path).stem
        second_video_name = Path(second_video_path).stem
        
        task.current_step = "正在提取视频帧..."
        task.progress = 20
        db.commit()
        
        # 提取前一个视频的尾帧
        first_frames = await file_storage.extract_video_frames(first_video_path)
        if not first_frames.get("success") or not first_frames.get("last"):
            raise Exception(f"无法提取第一个视频的尾帧: {first_frames.get('message')}")
        
        # 提取后一个视频的首帧
        second_frames = await file_storage.extract_video_frames(second_video_path)
        if not second_frames.get("success") or not second_frames.get("first"):
            raise Exception(f"无法提取第二个视频的首帧: {second_frames.get('message')}")
        
        last_frame_path = first_frames["last"]
        first_frame_path = second_frames["first"]
        
        task.current_step = "正在调用 ComfyUI 生成转场视频..."
        task.progress = 40
        db.commit()
        
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise Exception("工作流不存在")
        
        node_mapping = {}
        if workflow.node_mapping:
            try:
                node_mapping = json.loads(workflow.node_mapping)
            except:
                pass
        
        comfyui_service = ComfyUIService()
        result = await comfyui_service.generate_transition_video_with_workflow(
            workflow_json=workflow.workflow_json,
            node_mapping=node_mapping,
            first_image_path=last_frame_path,
            last_image_path=first_frame_path,
            frame_count=frame_count
        )
        
        if result.get("prompt_id"):
            task.comfyui_prompt_id = result["prompt_id"]
            print(f"[TransitionTask] Saved ComfyUI prompt_id: {result['prompt_id']}")
        
        if result.get("submitted_workflow"):
            task.workflow_json = json.dumps(result["submitted_workflow"], ensure_ascii=False, indent=2)
            db.commit()
            print(f"[TransitionTask] Saved submitted workflow to task")
        
        if result.get("success"):
            video_url = result.get("video_url")
            
            task.current_step = "正在保存视频..."
            task.progress = 80
            db.commit()
            
            transition_path = file_storage.get_transition_video_path(
                novel_id, chapter_id, first_video_name, second_video_name
            )
            
            async with httpx.AsyncClient() as client:
                response = await client.get(video_url, timeout=120.0)
                response.raise_for_status()
                
                with open(transition_path, 'wb') as f:
                    f.write(response.content)
            
            relative_path = str(transition_path).replace(str(file_storage.base_dir), "").replace("\\", "/")
            local_url = f"/api/files/{relative_path.lstrip('/')}"
            
            transition_videos = json.loads(chapter.transition_videos) if chapter.transition_videos else {}
            if not isinstance(transition_videos, dict):
                transition_videos = {}
            
            transition_key = f"{from_index}-{to_index}"
            transition_videos[transition_key] = local_url
            chapter.transition_videos = json.dumps(transition_videos)
            
            task.status = "completed"
            task.progress = 100
            task.result_url = local_url
            task.current_step = "转场视频生成完成"
            db.commit()
            
            print(f"[TransitionTask] Completed: {from_index}->{to_index}, video: {local_url}")
        else:
            raise Exception(result.get("message", "生成失败"))
            
    except Exception as e:
        print(f"[TransitionTask] Error: {e}")
        import traceback
        traceback.print_exc()
        
        try:
            task.status = "failed"
            task.error_message = str(e)
            task.current_step = "任务异常"
            db.commit()
        except:
            pass
    finally:
        db.close()
