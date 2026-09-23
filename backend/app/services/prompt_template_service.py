"""
PromptTemplate Service 层

封装提示词模板相关的业务逻辑
"""
import os
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.novel import Novel
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


# 系统预设的故事世界上下文推荐模板
SYSTEM_STORY_CONTEXT_TEMPLATES: List[Dict] = [
    {
        "name": "故事世界上下文推荐",
        "description": "根据小说名称和描述推荐统一的时代、地域、文化与物质世界边界",
        "template": load_template("01_NovelFlow_StoryWorldContext_Recommender_V1.txt"),
        "type": "story_world_context_recommender",
    }
]


# 系统预设的风格提示词模板（独立类型，用于图片生成的风格描述）
SYSTEM_STYLE_TEMPLATES: List[Dict] = [
    {
        "name": "动漫风格",
        "description": "二维动漫渲染，清晰线稿、赛璐璐分层阴影与统一色彩",
        "template": """2D anime rendering with precise, clean linework and controlled line weight,
flat local colors, crisp cel-shaded shadow shapes and restrained highlights,
consistent drawn contours and shading across characters, environments and props,
readable silhouettes and material cues expressed through line and color rather than photorealistic textures.
Preserve authored identities, clothing, props, architecture and world details; change rendering only.""",
        "type": "style"
    },
    {
        "name": "写实风格",
        "description": "电影级写实质感，自然光影与可信材质，时代和世界观遵循故事",
        "template": """cinematic photorealistic rendering with physically plausible light and shadow,
believable surface textures, material-specific reflections and fine natural detail,
coherent anatomy and object construction, restrained color grading and natural tonal range,
consistent photographic realism across characters, environments and props.
Era, technology, clothing, architecture and materials follow the story, including modern or fantastical elements when authored.
Preserve authored identities, clothing, props, architecture and world details; change rendering only.""",
        "type": "style"
    },
    {
        "name": "Q版风格",
        "description": "稳定头身比的二维Q版角色，场景和道具保持原有结构与功能比例",
        "template": """2D chibi cartoon rendering with clean rounded linework, flat colors and simple cel shading,
depicted humanoid characters use stable 2.5-to-3-head-tall proportions and simplified facial features,
retain recognizable age cues, species traits, hairstyles, clothing and identity-defining details.
Environments and props share the same 2D linework and shading while retaining their authored structure, functional proportions and relative scale; do not give buildings or objects chibi anatomy.
Preserve authored identities, clothing, props, architecture and world details; stylize character proportions without redesigning the story.""",
        "type": "style"
    },
    {
        "name": "水墨风格",
        "description": "毛笔墨韵、浓淡晕染与宣纸肌理，以墨色和克制淡彩统一画面",
        "template": """Chinese ink-wash rendering with expressive brush pressure, dry-brush edges and wet ink diffusion,
layered ink values and soft wash transitions on subtly textured absorbent paper,
an ink-led palette with restrained color washes retaining identity-defining color cues,
forms and material differences described through brushwork and ink density,
consistent ink-and-paper treatment across characters, environments and props.
Preserve authored identities, clothing, props, architecture and world details; change rendering only, without adding traditional motifs or changing the story era.""",
        "type": "style"
    },
    {
        "name": "3D动画风格",
        "description": "风格化三维动画质感，清晰体积、柔和光照与统一材质表现",
        "template": """stylized 3D animation rendering with clean modeled forms and readable volumes,
smooth surface shading, soft bounced light and coherent contact shadows,
controlled material roughness and restrained specular highlights,
selective surface detail that supports the authored designs without photorealistic texture noise,
consistent three-dimensional rendering across characters, environments and props.
Preserve authored identities, proportions, clothing, props, architecture and world details; change rendering only.""",
        "type": "style"
    },
    {
        "name": "水彩绘本风格",
        "description": "透明水彩叠色、柔和边缘与纸张颗粒，呈现手绘绘本质感",
        "template": """watercolor picture-book rendering with transparent layered washes and delicate pigment granulation,
soft bleeding edges balanced with selective fine drawn contours,
visible watercolor paper texture and subtle variations in pigment density,
harmonized colors that retain identity-defining color cues and readable material differences,
consistent hand-painted treatment across characters, environments and props.
Preserve authored identities, proportions, clothing, props, architecture and world details; change rendering only.""",
        "type": "style"
    },
    {
        "name": "油画风格",
        "description": "油彩笔触、层叠罩染与画布肌理，强调色彩和明暗塑形",
        "template": """oil painting rendering with visible directional brushwork and subtle canvas grain,
layered opaque paint and translucent glazes, selective impasto highlights,
forms modeled through coherent tonal values, warm-cool color relationships and controlled edges,
material distinctions conveyed through paint handling rather than photographic texture,
consistent oil-painted treatment across characters, environments and props.
Preserve authored identities, proportions, clothing, props, architecture and world details; change rendering only.""",
        "type": "style"
    },
    {
        "name": "美式漫画风格",
        "description": "美式漫画墨线、鲜明色块、排线与半色调网点表现",
        "template": """American comic-book rendering with confident ink contours and varied line weight,
bold flat color shapes, graphic shadow masses, selective crosshatching and halftone texture,
clear silhouettes and controlled high-contrast value separation,
material differences expressed through ink marks and color rather than photographic surfaces,
consistent printed-comic treatment across characters, environments and props.
Preserve authored identities, proportions, clothing, props, architecture and world details; change rendering only, without inventing superhero costumes or exaggerated musculature.""",
        "type": "style"
    },
    {
        "name": "像素艺术风格",
        "description": "统一像素网格、有限色板与清晰像素簇，避免模糊和平滑渐变",
        "template": """pixel art rendering on a consistent square pixel grid with deliberate pixel clusters,
crisp stepped edges, a limited coordinated palette and discrete color ramps,
selective ordered dithering for tonal transitions, without smooth gradients, blur or anti-aliased contours,
readable silhouettes and essential identity details at a consistent pixel density,
the same pixel-based treatment across characters, environments and props.
Preserve authored identities, proportions, clothing, props, architecture and world details; simplify surface detail without adding game interface elements.""",
        "type": "style"
    },
    {
        "name": "剪纸艺术风格",
        "description": "剪纸轮廓、层叠色纸与轻微投影，保留主体轮廓和辨识细节",
        "template": """layered cut-paper art rendering with crisp cut edges and carefully shaped paper silhouettes,
flat colored paper surfaces, subtle paper fibers and slight shadows between overlapping layers,
forms and material differences translated into coherent paper shapes and color layers,
retain identity-defining colors and details instead of reducing every subject to a generic silhouette,
consistent paper-crafted treatment across characters, environments and props.
Preserve authored identities, proportions, clothing, props, architecture and world details; change rendering only, without adding decorative folk motifs.""",
        "type": "style"
    },
    {
        "name": "黏土定格风格",
        "description": "手工黏土定格质感，柔和体积、细微塑形痕迹与哑光表面",
        "template": """clay stop-motion aesthetic with tactile hand-sculpted surfaces and softly shaped volumes,
subtle tool marks, gentle surface irregularities and mostly matte material response,
soft light, coherent contact shadows and restrained highlights,
authored materials remain recognizable through their colors, shapes and sculpted surface cues,
consistent handcrafted clay rendering across characters, environments and props.
Preserve authored identities, proportions, clothing, props, architecture and world details; change rendering only, without turning subjects into generic toys.""",
        "type": "style"
    },
    {
        "name": "国风工笔风格",
        "description": "工笔细线勾勒、层层设色与绢纸质感，细致保留服饰和器物特征",
        "template": """Chinese gongbi fine-brush painting rendering with delicate controlled outlines,
precise contour definition, meticulous small details and evenly layered translucent color,
subtle silk or fine-paper texture, refined tonal transitions and restrained mineral-pigment richness,
material differences expressed through fine linework and careful color layering rather than loose ink splashes,
consistent fine-brush treatment across characters, environments and props.
Preserve authored identities, proportions, clothing, props, architecture and world details; change rendering only, without adding historical costumes, ornaments or a different era.""",
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
        "name": "标准角色生成",
        "description": "使用小说设定的视觉风格和角色外貌生成标准人设图",
        "template": load_template("standard_anime.txt"),
        "type": "character"
    }
]

# 系统预设的章节拆分提示词模板
SYSTEM_CHAPTER_SPLIT_TEMPLATES: List[Dict] = [
    {
        "name": "章节分镜导演解析",
        "description": "根据章节正文和角色/场景/道具白名单规划导演 Shot 数据",
        "template": load_template("05_NovelFlow_VideoDirector_ShotDirector_V1.txt"),
        "type": "chapter_split"
    }
]

# 系统预设的分镜图提示词模板
SYSTEM_SHOT_IMAGE_PROMPT_TEMPLATES: List[Dict] = [
    {
        "name": "主分镜图生成提示词构建",
        "description": "根据 Shot 数据和正式参考资产构建 Qwen-Image-Edit 主分镜图提示词",
        "template": load_template("06_NovelFlow_QwenEdit2511_ShotImagePrompt_V1.txt"),
        "type": "shot_image_prompt"
    }
]

# 系统预设的视频导演提示词模板
SYSTEM_VIDEO_DIRECTOR_TEMPLATES: List[Dict] = [
    {
        "name": "视频生成模式推荐",
        "description": "根据 Shot 与 Workflow 能力推荐 SINGLE_FRAME / FIRST_LAST_FRAME / MULTI_KEYFRAME",
        "template": load_template("07_NovelFlow_VideoGeneration_ModeRecommender_V1.txt"),
        "type": "video_mode_recommender"
    },
    {
        "name": "关键帧过渡规划",
        "description": "根据相邻关键帧规划自然过渡的 Segment 动态导演描述",
        "template": load_template("10_NovelFlow_KeyframeTransition_Planner_V1.txt"),
        "type": "keyframe_transition"
    }
]

# 系统预设的关键帧规划与生图提示词模板
SYSTEM_KEYFRAME_PLANNING_TEMPLATES: List[Dict] = [
    {
        "name": "关键帧时间轴规划",
        "description": "为 MULTI_KEYFRAME Shot 规划每个执行窗口的 3/4 帧关键帧时间轴",
        "template": load_template("08_NovelFlow_VideoDirector_KeyframePlanner_V2_3Frame4Frame.txt"),
        "type": "keyframe_planner"
    },
    {
        "name": "视频关键帧生图提示词构建",
        "description": "根据上一关键帧、主分镜图和参考资产构建下一关键帧生图提示词",
        "template": load_template("09_NovelFlow_QwenEdit2511_KeyframeImagePrompt_V1.txt"),
        "type": "keyframe_image_prompt"
    }
]

# 系统预设的 MiniMax H3 视频生成最终提示词模板
SYSTEM_H3_VIDEO_PROMPT_TEMPLATES: List[Dict] = [
    {
        "name": "MiniMax H3 单帧视频提示词构建",
        "description": "根据单张权威起始帧、Clip 动态意图和精确对白构建 H3 单帧视频提示词",
        "template": load_template("11_MiniMax_H3_SingleFrame_VideoPrompt_V1.txt"),
        "type": "h3_single_frame_prompt"
    },
    {
        "name": "MiniMax H3 首尾帧视频提示词构建",
        "description": "根据起止两张权威时间帧、过渡描述和精确对白构建 H3 首尾帧视频提示词",
        "template": load_template("12_MiniMax_H3_FirstLastFrame_VideoPrompt_V1.txt"),
        "type": "h3_first_last_frame_prompt"
    },
    {
        "name": "MiniMax H3 多关键帧视频提示词构建",
        "description": "根据多张时间顺序关键帧、过渡 Segment 和精确对白构建 H3 多关键帧提示词",
        "template": load_template("13_MiniMax_H3_MultiKeyframe_VideoPrompt_V1.txt"),
        "type": "h3_multi_keyframe_prompt"
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
    SYSTEM_STORY_CONTEXT_TEMPLATES +
    SYSTEM_STYLE_TEMPLATES +
    SYSTEM_CHARACTER_PARSE_TEMPLATES +
    SYSTEM_SCENE_PARSE_TEMPLATES +
    SYSTEM_PROP_PARSE_TEMPLATES +
    SYSTEM_CHARACTER_TEMPLATES +
    SYSTEM_SCENE_IMAGE_TEMPLATES +
    SYSTEM_PROP_TEMPLATES +
    SYSTEM_CHAPTER_SPLIT_TEMPLATES +
    SYSTEM_SHOT_IMAGE_PROMPT_TEMPLATES +
    SYSTEM_VIDEO_DIRECTOR_TEMPLATES +
    SYSTEM_KEYFRAME_DESCRIPTION_TEMPLATES +
    SYSTEM_KEYFRAME_PLANNING_TEMPLATES +
    SYSTEM_H3_VIDEO_PROMPT_TEMPLATES
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

        # 测试和部分脚本会关闭 autoflush，先确保新系统模板可被后续同步查询到。
        self.db.flush()

        # 角色视觉风格由小说的 style 模板注入，只保留一个通用角色生成系统模板。
        canonical_character_template = self.template_repo.get_by_name_and_type(
            SYSTEM_CHARACTER_TEMPLATES[0]["name"],
            "character",
            is_system=True,
        )
        if canonical_character_template:
            obsolete_templates = self.db.query(PromptTemplate).filter(
                PromptTemplate.type == "character",
                PromptTemplate.is_system == True,
                PromptTemplate.id != canonical_character_template.id,
            ).all()
            obsolete_ids = [template.id for template in obsolete_templates]
            if obsolete_ids:
                self.db.query(Novel).filter(
                    Novel.prompt_template_id.in_(obsolete_ids)
                ).update(
                    {Novel.prompt_template_id: canonical_character_template.id},
                    synchronize_session=False,
                )
                for template in obsolete_templates:
                    self.db.delete(template)

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
