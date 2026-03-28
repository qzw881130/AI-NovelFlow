"""
PromptTemplate Service 层

封装提示词模板相关的业务逻辑
"""
import os
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.prompt_template import PromptTemplate
from app.repositories import PromptTemplateRepository
from app.utils.time_utils import format_datetime


# 模板文件目录 (位于 backend/prompt_templates/)
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'prompt_templates')


def load_template(filename: str) -> str:
    """从文件加载模板内容"""
    filepath = os.path.join(TEMPLATES_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Template file not found: {filepath}")


# 系统预设的风格提示词模板（独立类型，用于图片生成的风格描述）
SYSTEM_STYLE_TEMPLATES: List[Dict] = [
    {
        "name": "动漫风格",
        "description": "适用于动漫风格的图片生成",
        "template": "anime style, high quality, detailed, professional artwork",
        "type": "style"
    },
    {
        "name": "写实风格",
        "description": "适用于写实风格的图片生成",
        "template": "realistic style, photorealistic, highly detailed, professional photography",
        "type": "style"
    },
    {
        "name": "Q版风格",
        "description": "适用于Q版卡通风格的图片生成",
        "template": "chibi style, cute cartoon style, kawaii, colorful",
        "type": "style"
    },
    {
        "name": "水墨风格",
        "description": "适用于中国传统水墨画风格的图片生成",
        "template": "Chinese ink painting style, traditional art, elegant, artistic",
        "type": "style"
    }
]

# 系统预设的角色解析提示词模板（从小说文本解析角色信息）
SYSTEM_CHARACTER_PARSE_TEMPLATES: List[Dict] = [
    {
        "name": "标准角色解析",
        "description": "适用于大多数小说的角色解析",
        "template": load_template("character_parse.txt"),
        "type": "character_parse"
    }
]

# 系统预设的人设提示词模板（角色生成）
SYSTEM_CHARACTER_TEMPLATES: List[Dict] = [
    {
        "name": "标准动漫人设",
        "description": "适合大多数动漫角色的标准人设生成",
        "template": load_template("standard_anime.txt"),
        "type": "character"
    },
    {
        "name": "写实人设",
        "description": "写实风格的角色人设",
        "template": load_template("realistic.txt"),
        "type": "character"
    },
    {
        "name": "Q版人设",
        "description": "可爱Q版卡通风格的角色人设",
        "template": load_template("chibi_cartoon.txt"),
        "type": "character"
    },
    {
        "name": "水墨人设",
        "description": "中国传统水墨画风格的角色人设",
        "template": load_template("ink_painting.txt"),
        "type": "character"
    }
]

# 系统预设的章节拆分提示词模板
SYSTEM_CHAPTER_SPLIT_TEMPLATES: List[Dict] = [
    {
        "name": "标准分镜拆分",
        "description": "适用于大多数小说的标准分镜拆分",
        "template": load_template("standard_chapter_split.txt"),
        "type": "chapter_split"
    },
    {
        "name": "电影风格分镜",
        "description": "电影级分镜拆分，强调画面构图和镜头语言",
        "template": load_template("cinema_style.txt"),
        "type": "chapter_split"
    }
]

# 系统预设的场景解析提示词模板（从小说文本解析场景信息）
SYSTEM_SCENE_PARSE_TEMPLATES: List[Dict] = [
    {
        "name": "标准场景解析",
        "description": "适用于大多数小说的场景解析",
        "template": load_template("scene_parse.txt"),
        "type": "scene_parse"
    }
]

# 系统预设的场景图生成提示词模板
SYSTEM_SCENE_IMAGE_TEMPLATES: List[Dict] = [
    {
        "name": "标准场景图",
        "description": "适用于大多数场景的标准图生成",
        "template": load_template("scene.txt"),
        "type": "scene"
    }
]

# 系统预设的道具解析提示词模板（从小说文本解析道具信息）
SYSTEM_PROP_PARSE_TEMPLATES: List[Dict] = [
    {
        "name": "标准道具解析",
        "description": "适用于大多数小说的道具解析",
        "template": load_template("prop_parse.txt"),
        "type": "prop_parse"
    }
]

# 系统预设的道具图生成提示词模板
SYSTEM_PROP_TEMPLATES: List[Dict] = [
    {
        "name": "标准道具图",
        "description": "适用于大多数道具的标准图生成",
        "template": load_template("prop.txt"),
        "type": "prop"
    }
]

# 系统预设的关键帧描述提示词模板
SYSTEM_KEYFRAME_DESCRIPTION_TEMPLATES: List[Dict] = [
    {
        "name": "标准关键帧描述",
        "description": "适用于大多数分镜的关键帧描述生成",
        "template": """请根据以下分镜描述，生成 {count} 个关键帧描述。

分镜描述：
{shot_description}

{video_description}

要求：
1. 每个关键帧描述应该是该分镜中一个重要的画面瞬间
2. 描述应该详细且具有画面感，包含人物动作、表情、场景细节等
3. 关键帧应该按照时间顺序排列，展示分镜的动态过程
4. 每个描述控制在50-100字

请直接返回JSON数组格式，每个元素包含：
- frame_index: 帧序号（从0开始）
- description: 关键帧描述

示例格式：
[
  {{"frame_index": 0, "description": "第1个关键帧的描述"}},
  {{"frame_index": 1, "description": "第2个关键帧的描述"}}
]""",
        "type": "keyframe_description"
    },
    {
        "name": "电影级关键帧",
        "description": "电影级关键帧描述，强调画面构图和镜头语言",
        "template": """作为专业电影分镜师，请根据以下分镜描述，生成 {count} 个电影级关键帧描述。

分镜描述：
{shot_description}

{video_description}

要求：
1. 每个关键帧应是一个具有电影感的画面瞬间
2. 描述需包含：景别（远景/全景/中景/近景/特写）、构图方式、人物调度、光线氛围
3. 重点关注情感表达和叙事节奏
4. 关键帧按时间顺序排列，形成完整的视觉叙事
5. 每个描述控制在80-150字

请直接返回JSON数组格式：
[
  {{"frame_index": 0, "description": "【景别】描述内容..."}},
  {{"frame_index": 1, "description": "【景别】描述内容..."}}
]""",
        "type": "keyframe_description"
    }
]

# 合并所有系统模板
SYSTEM_PROMPT_TEMPLATES = (
    SYSTEM_STYLE_TEMPLATES +
    SYSTEM_CHARACTER_PARSE_TEMPLATES +
    SYSTEM_SCENE_PARSE_TEMPLATES +
    SYSTEM_PROP_PARSE_TEMPLATES +
    SYSTEM_CHARACTER_TEMPLATES +
    SYSTEM_SCENE_IMAGE_TEMPLATES +
    SYSTEM_PROP_TEMPLATES +
    SYSTEM_CHAPTER_SPLIT_TEMPLATES +
    SYSTEM_KEYFRAME_DESCRIPTION_TEMPLATES
)


def get_template_name_key(name: str) -> str:
    """获取模板名称的翻译键"""
    return f"promptConfig.templateNames.{name}"


def get_template_description_key(name: str) -> str:
    """获取模板描述的翻译键"""
    return f"promptConfig.templateDescriptions.{name}"


class PromptTemplateService:
    """提示词模板服务"""

    def __init__(self, db: Session):
        self.db = db
        self.template_repo = PromptTemplateRepository(db)

    def init_system_templates(self) -> None:
        """初始化系统预设提示词模板"""
        print("[初始化] 更新系统预设提示词模板...")

        for tmpl_data in SYSTEM_PROMPT_TEMPLATES:
            # 检查是否已存在同名同类型的系统模板
            existing = self.template_repo.get_by_name_and_type(
                tmpl_data["name"],
                tmpl_data.get("type", "character"),
                is_system=True
            )

            if existing:
                # 更新现有模板内容
                existing.description = tmpl_data["description"]
                existing.template = tmpl_data["template"]
            else:
                # 创建新模板
                template = PromptTemplate(
                    name=tmpl_data["name"],
                    description=tmpl_data["description"],
                    template=tmpl_data["template"],
                    type=tmpl_data.get("type", "character"),
                    is_system=True,
                    is_active=True
                )
                self.db.add(template)

        self.db.commit()
        print("[初始化] 系统预设提示词模板更新完成")

    def list_templates(self, template_type: Optional[str] = None) -> List[PromptTemplate]:
        """获取模板列表"""
        if template_type:
            return self.template_repo.list_by_type(template_type)
        return self.template_repo.list_all()

    def get_template_by_id(self, template_id: str) -> Optional[PromptTemplate]:
        """根据 ID 获取模板"""
        return self.template_repo.get_by_id(template_id)

    def create_template(
        self,
        name: str,
        description: str,
        template: str,
        template_type: str = "character"
    ) -> PromptTemplate:
        """创建用户自定义模板"""
        new_template = PromptTemplate(
            name=name,
            description=description,
            template=template,
            type=template_type,
            is_system=False,
            is_active=True
        )
        return self.template_repo.create(new_template)

    def copy_template(self, source_id: str) -> PromptTemplate:
        """复制系统模板为用户自定义模板"""
        source = self.template_repo.get_by_id(source_id)
        if not source:
            raise ValueError("源提示词模板不存在")

        new_template = PromptTemplate(
            name=f"{source.name} (副本)",
            description=source.description,
            template=source.template,
            type=source.type or "character",
            is_system=False,
            is_active=True
        )
        return self.template_repo.create(new_template)

    def update_template(
        self,
        template_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        template: Optional[str] = None,
        template_type: Optional[str] = None
    ) -> PromptTemplate:
        """更新模板（仅用户自定义可编辑）"""
        template_obj = self.template_repo.get_by_id(template_id)
        if not template_obj:
            raise ValueError("提示词模板不存在")

        if template_obj.is_system:
            raise PermissionError("系统预设提示词不可编辑")

        if name is not None:
            template_obj.name = name
        if description is not None:
            template_obj.description = description
        if template is not None:
            template_obj.template = template
        if template_type is not None:
            template_obj.type = template_type

        return self.template_repo.update(template_obj)

    def delete_template(self, template_id: str) -> None:
        """删除模板（仅用户自定义可删除）"""
        template_obj = self.template_repo.get_by_id(template_id)
        if not template_obj:
            raise ValueError("提示词模板不存在")

        if template_obj.is_system:
            raise PermissionError("系统预设提示词不可删除")

        self.template_repo.delete(template_obj)

    def get_default_system_template(self, template_type: str = "character") -> Optional[PromptTemplate]:
        """获取默认的系统模板"""
        return self.template_repo.get_default_system_template(template_type)

    @staticmethod
    def to_response(template: PromptTemplate) -> dict:
        """将模板对象转换为响应字典"""
        return {
            "id": template.id,
            "name": template.name,
            "nameKey": get_template_name_key(template.name) if template.is_system else None,
            "description": template.description,
            "descriptionKey": get_template_description_key(template.name) if template.is_system else None,
            "template": template.template,
            "type": template.type or "character",
            "isSystem": template.is_system,
            "isActive": template.is_active,
            "createdAt": format_datetime(template.created_at),
        }
