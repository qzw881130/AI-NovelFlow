import httpx
import json
from typing import Dict, Any, List
from app.core.config import get_settings

settings = get_settings()


class DeepSeekService:
    """DeepSeek API 服务封装"""
    
    def __init__(self):
        self.api_url = settings.DEEPSEEK_API_URL
        self.api_key = settings.DEEPSEEK_API_KEY
    
    async def check_health(self) -> bool:
        """检查 DeepSeek API 状态"""
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=5.0
                )
                return response.status_code == 200
        except Exception:
            return False
    
    async def parse_novel_text(self, text: str) -> Dict[str, Any]:
        """
        解析小说文本，提取角色、场景、分镜信息
        
        Returns:
            {
                "characters": [...],
                "scenes": [...],
                "shots": [...]
            }
        """
        system_prompt = """你是一个专业的小说解析助手。请分析我提供的小说文本，提取以下信息并以 JSON 格式返回：

1) characters：角色列表。每个角色必须包含：
- name（姓名）
- description（描述）
- appearance（外貌特征：必须是一段完整自然语言描述的"单段文字"，禁止使用结构化字段/键值对/列表/分段标题）

【角色命名唯一性与一致性（必须严格执行）】
- 所有角色 name 必须在首次解析时确定为唯一标准名称，并在后续所有步骤中严格复用该名称。
- 若同类型角色存在多个且无真实姓名，必须按首次出场顺序使用阿拉伯数字编号命名（如"骗子1""骗子2""士兵1""士兵2"）。
- 禁止使用"甲/乙""A/B""其中一人""另一人""某官员"等非唯一或会变化的称呼。
- 一旦 name 确定，后续输出不得更改、简化或替换；所有角色引用必须完全一致。

【群体称谓抽取规则（必须执行）】
当正文出现以下群体称谓：众人/群臣/士兵/百姓/侍从/随从/围观者/人群（含同义词，如"大家""围观的人""侍卫""兵丁""宫人""下人""臣子们"等），必须将其作为可出镜角色类型提取进 characters。
规则：
1) 不允许直接输出未编号的群体名称（禁止：众人、群臣、士兵、百姓、侍从、随从、围观者、人群）。
2) 必须按首次出场顺序拆分并编号命名为具体角色（默认 2 个；若文本明确人数更多，可输出到 3–5 个，最多不超过 5 个）：
   - 群臣1、群臣2…
   - 士兵1、士兵2…
   - 百姓1、百姓2…
   - 侍从1、侍从2…
   - 随从1、随从2…
   - 围观者1、围观者2…
3) 若同一段落同时出现多个群体称谓，必须分别建立编号角色（例如既有群臣又有侍从，则输出 群臣1/2 + 侍从1/2）。
4) 每个群体编号角色也必须给出 description 与 appearance；可以共享基础外观模板，但必须用细节区分（年龄/体型/服饰配色/站位/表情/动作/配饰等），确保可用于 AI 绘图。
5) 这些编号角色一旦生成，后续输出必须始终复用同名，不得改名、合并或替换。

【appearance（外貌特征）写作硬性约束 | 必须遵守】
- appearance 必须是"一段话"（单段自然语言），禁止输出 JSON 子对象、字段分组、项目符号列表、编号小节、冒号键值对。
- 每个角色的 appearance 必须描述"只包含 1 个主体"的外貌，身份必须稳定一致，禁止漂移或换脸。
- appearance 必须明确为"全身照/全身构图"（full-body shot）：从头到脚完整可见，站姿或自然姿态，四肢完整，不裁切，不缺手缺脚；同时写清鞋子/脚部外观或动物爪部细节；服装需覆盖上装/下装/鞋袜（或动物全身毛色/四肢/尾巴）。
- appearance 这段话必须覆盖并明确以下要点（必须全部写进同一段文字里）：
  A) 物种与身份：物种（人类/动物物种+品种）、性别/气质、年龄段（含大约年龄）、体型与身高/大小、2–6 个独特身份标记（必须可视化且可复现，如痣的位置、疤痕、条纹/色块分布、异色瞳、独特配饰的固定位置等）。
  B) 头部与脸型：脸型/头型、面部比例（如中庭偏长/下颌偏宽等）、额头/颧骨/下颌线/下巴特征；动物需补充口鼻长度、头骨宽窄、耳根位置。
  C) 眼睛：眼型、大小、虹膜颜色、眼角走向、眼皮类型；动物补充瞳孔形态；强调"眼型与眼睛颜色不得改变"。
  D) 鼻子/口鼻部：鼻梁/鼻尖/鼻翼宽度/鼻孔大小与角度；动物补充鼻镜颜色、胡须垫是否明显。
  E) 嘴/喙/下颌：嘴唇厚薄、嘴角走向、是否露齿；动物补充喙/尖牙可见度等。
  F) 皮肤/毛发/羽毛/鳞片：表面类型、基础颜色（皮肤含冷暖底调）、质感细节、花纹/色块"精确位置映射"（必须可复现）。
  G) 头发/鬃毛/冠羽/耳朵：发质、长度、发色、分发与发际线；动物补充耳形与耳毛簇、鬃毛/冠羽长度等。
  H) 胡须/面部毛：胡子/胡茬/胡须长度与颜色（如适用）。
  I) 与身份绑定的配饰：如眼镜/项圈/吊牌/头饰等，必须写清"类型 + 固定位置"，如指定则必须保留。
  J) 比例与解剖规则：明确"保持面部比例、头身比、耳朵大小、口鼻长度、花纹位置与所有独特标记一致；禁止改物种/品种；禁止改变年龄段与性别气质呈现"。

【负面约束（必须体现在输出约束中）】
- 禁止改变：眼睛颜色、眼型、脸型、口鼻长度、毛皮/皮肤花纹的精确位置、独特标记、发型轮廓。
- 禁止：额外主体、换脸、身份漂移、左右不对称 bug、畸形解剖、随机疤痕/纹身、无故新增配饰或标记。
- 禁止裁切：不许半身照、特写、缺腿缺脚、脚部出画、手部残缺或被遮挡导致不可见。

【输出格式要求（必须严格执行）】
- 只返回合法 JSON，不得输出任何解释性文字。
- JSON 顶层结构必须为：
{
  "characters": [
    {
      "name": "...",
      "description": "...",
      "appearance": "..."
    }
  ]
}
- appearance 必须是纯字符串的一段话（一个 string），不得是对象、数组、或多段分行结构。"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"请解析以下小说文本：\n\n{text[:8000]}"}  # 限制长度
                        ],
                        "temperature": 0.7,
                        "max_tokens": 4000,
                        "response_format": {"type": "json_object"}
                    },
                    timeout=60.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    return json.loads(content)
                else:
                    return {
                        "error": f"API返回错误: {response.status_code}",
                        "characters": [],
                        "scenes": [],
                        "shots": []
                    }
                    
        except Exception as e:
            return {
                "error": str(e),
                "characters": [],
                "scenes": [],
                "shots": []
            }
    
    async def generate_character_appearance(
        self, 
        character_name: str, 
        description: str,
        style: str = "anime"  # anime, realistic, 3d, etc.
    ) -> str:
        """
        根据角色描述生成详细的外貌描述（用于AI绘图）
        
        Args:
            character_name: 角色名称
            description: 角色背景描述
            style: 画风风格
            
        Returns:
            详细的外貌描述文本
        """
        system_prompt = f"""你是一个专业的角色设定助手。请根据提供的角色信息，生成一段详细的外貌描述，用于AI绘图生成角色形象。

要求：
1. 描述要具体、详细，包含：发型、发色、眼睛、服装、配饰、表情、姿态
2. 使用英文（AI绘图模型对英文理解更好）
3. 添加画风提示词，如：{style} style, high quality, detailed
4. 避免模糊词汇，使用具体的颜色和样式描述

示例输出格式：
Young female character, long flowing silver hair with blue highlights, sharp blue eyes, delicate features, wearing traditional Chinese hanfu in white and blue colors, jade hairpin, gentle smile, standing pose, clean background, anime style, high quality, detailed, 8k"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"角色名称：{character_name}\n角色描述：{description}\n\n请生成详细的外貌描述："}
                        ],
                        "temperature": 0.8,
                        "max_tokens": 1000
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    return f"{character_name}, detailed character, high quality"
                    
        except Exception as e:
            return f"{character_name}, detailed character, high quality"
    
    async def split_chapter_with_prompt(
        self,
        chapter_title: str,
        chapter_content: str,
        prompt_template: str,
        word_count: int = 50,
        character_names: list = None,
        style: str = "anime style, high quality, detailed"
    ) -> Dict[str, Any]:
        """
        使用自定义提示词将章节拆分为分镜数据结构
        
        Args:
            chapter_title: 章节标题
            chapter_content: 章节正文内容
            prompt_template: 拆分提示词模板（包含占位符）
            word_count: 每个分镜对应的故事字数
            character_names: 当前小说的角色名称列表
            style: 风格描述，用于替换 {图像风格} 占位符
            
        Returns:
            {
                "chapter": "章节标题",
                "characters": [...],
                "scenes": [...],
                "shots": [...]
            }
        """
        # 处理提示词模板中的占位符
        system_prompt = prompt_template.replace(
            "{每个分镜对应拆分故事字数}", str(word_count)
        ).replace(
            "{图像风格}", style
        ).replace(
            "##STYLE##", style
        )
        
        # 构建 allowed_characters 行
        allowed_characters_line = ""
        if character_names:
            allowed_characters_line = f"allowed_characters: {', '.join(character_names)}\n\n"
        
        user_content = f"""{allowed_characters_line}章节标题：{chapter_title}

章节内容：
{chapter_content[:15000]}  # 限制长度避免超出token限制

请将以上章节内容拆分为分镜数据结构。"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 8000,
                        "response_format": {"type": "json_object"}
                    },
                    timeout=120.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    result = json.loads(content)
                    
                    # 确保返回格式正确
                    if "chapter" not in result:
                        result["chapter"] = chapter_title
                    if "characters" not in result:
                        result["characters"] = []
                    if "scenes" not in result:
                        result["scenes"] = []
                    if "shots" not in result:
                        result["shots"] = []
                        
                    return result
                else:
                    return {
                        "error": f"API返回错误: {response.status_code}",
                        "chapter": chapter_title,
                        "characters": [],
                        "scenes": [],
                        "shots": []
                    }
                    
        except Exception as e:
            return {
                "error": str(e),
                "chapter": chapter_title,
                "characters": [],
                "scenes": [],
                "shots": []
            }
    
    async def generate_shot_prompt(
        self,
        scene_description: str,
        characters: List[Dict[str, str]],
        shot_type: str = "medium"  # close-up, medium, wide, etc.
    ) -> str:
        """
        生成AI绘图用的分镜提示词
        
        Args:
            scene_description: 场景描述
            characters: 场景中的角色列表 [{"name": "...", "appearance": "..."}]
            shot_type: 镜头类型
            
        Returns:
            优化后的英文提示词
        """
        system_prompt = """你是一个专业的分镜描述助手。请将场景描述转换为适合AI绘图使用的英文提示词。

要求：
1. 使用英文描述
2. 包含镜头角度、构图、光影、氛围
3. 描述角色动作、表情、位置关系
4. 添加画风和质量提示词
5. 使用逗号分隔各个描述元素

示例输出：
Wide shot, two characters standing in ancient Chinese palace courtyard, golden hour lighting, warm atmosphere, traditional architecture in background, soft shadows, cinematic composition, anime style, high quality, detailed, 8k"""
        
        characters_info = "\n".join([
            f"- {c['name']}: {c.get('appearance', 'unknown appearance')}"
            for c in characters
        ])
        
        user_prompt = f"""场景描述：{scene_description}

角色信息：
{characters_info}

镜头类型：{shot_type}

请生成AI绘图提示词："""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 1000
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    return scene_description
                    
        except Exception as e:
            return scene_description
    
    async def enhance_prompt(self, prompt: str, prompt_type: str = "character") -> str:
        """
        优化提示词，添加质量标签
        
        Args:
            prompt: 原始提示词
            prompt_type: character（角色）| scene（场景）| shot（分镜）
        """
        quality_tags = {
            "character": "high quality, detailed, professional artwork, masterpiece",
            "scene": "high quality, detailed background, cinematic lighting, masterpiece",
            "shot": "cinematic composition, dramatic lighting, high quality, detailed, masterpiece"
        }
        
        base_tags = quality_tags.get(prompt_type, "high quality, detailed")
        
        # 确保提示词以合适的标签结尾
        enhanced = prompt.strip()
        if not any(tag in enhanced.lower() for tag in ["high quality", "detailed", "masterpiece"]):
            enhanced += f", {base_tags}"
        
        return enhanced
