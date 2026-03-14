"""
LLM 服务封装 - 支持多厂商调用 (DeepSeek, OpenAI, Gemini, Anthropic, Azure, Custom)

对外暴露的服务层，内部使用 LLMClient 实现底层调用。
"""
from typing import Dict, Any, List, Optional
from app.core.config import get_settings
from app.services.llm import LLMClient, LLMConfig
from app.utils.json_parser import safe_parse_llm_json, clean_llm_response
from app.constants import (
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_VIDEO_DURATION,
    NOVEL_TEXT_MAX_LENGTH,
    CHAPTER_CONTENT_MAX_LENGTH,
    DEFAULT_PARSE_CHARACTERS_PROMPT,
    CHAPTER_RANGE_PLACEHOLDER,
    DEFAULT_CHAPTER_RANGE_DESCRIPTION,
    DEFAULT_PARSE_SCENES_PROMPT,
    DEFAULT_VIDEO_PROMPT_EXPAND_SYSTEM,
    DEFAULT_CHARACTER_APPEARANCE_FALLBACK,
    DEFAULT_SCENE_SETTING_FALLBACK,
    DEFAULT_PROP_APPEARANCE_FALLBACK,
    get_character_appearance_prompt,
    get_scene_setting_prompt,
    get_prop_appearance_prompt,
)


class LLMService:
    """多厂商 LLM API 服务封装

    对外暴露的服务层，内部使用 LLMClient 实现底层调用。
    """

    def __init__(self):
        # 每次实例化时重新获取 settings，确保获取最新配置
        from app.core.config import get_settings
        current_settings = get_settings()

        self.provider = current_settings.LLM_PROVIDER
        self.model = current_settings.LLM_MODEL
        self.api_url = current_settings.LLM_API_URL
        self.api_key = current_settings.LLM_API_KEY
        self.max_tokens = getattr(current_settings, 'LLM_MAX_TOKENS', None)  # 从配置中获取 max_tokens
        self.temperature = getattr(current_settings, 'LLM_TEMPERATURE', None)  # 从配置中获取 temperature

        # 代理配置
        self.proxy_enabled = current_settings.PROXY_ENABLED
        self.http_proxy = current_settings.HTTP_PROXY
        self.https_proxy = current_settings.HTTPS_PROXY

        # 如果没有配置新的 LLM，且不是 Ollama（Ollama 可以没有 API Key），尝试兼容旧配置
        if not self.api_key and self.provider != "ollama":
            self.api_key = current_settings.DEEPSEEK_API_KEY
            self.api_url = current_settings.DEEPSEEK_API_URL
            self.provider = "deepseek"

        # 初始化 API Key 轮询机制
        self.api_keys = []
        if self.api_key:
            # 支持多 API Key，逗号分隔
            self.api_keys = [key.strip() for key in self.api_key.split(',') if key.strip()]
        else:
            self.api_keys = []

        # 当前使用的 API Key 索引
        self.current_key_index = 0

    def _get_client(self) -> LLMClient:
        """获取 LLMClient 实例"""
        config = LLMConfig(
            provider=self.provider,
            model=self.model,
            api_url=self.api_url,
            api_key=self.api_key,
            max_tokens=self.max_tokens,
            temperature=float(self.temperature) if self.temperature else None,
            proxy_enabled=self.proxy_enabled,
            http_proxy=self.http_proxy,
            https_proxy=self.https_proxy,
        )
        return LLMClient(config)

    async def chat_completion(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        response_format: Optional[str] = None,
        task_type: str = None,
        novel_id: str = None,
        chapter_id: str = None,
        character_id: str = None
    ) -> Dict[str, Any]:
        """
        发送对话请求

        内部使用 LLMClient 实现底层调用。

        Returns:
            {
                "success": bool,
                "content": str,
                "error": str (optional)
            }
        """
        # 使用配置的参数，如果提供了则覆盖默认值
        final_temperature = float(self.temperature) if self.temperature else temperature
        final_max_tokens = self.max_tokens if self.max_tokens is not None else max_tokens
        print(f"[chat_completion] url: {self.api_url}, model: {self.model}, temperature: {final_temperature}, max_tokens: {final_max_tokens} \n system_prompt: {system_prompt}\n user_content: {user_content}")

        client = self._get_client()
        return await client.chat_completion(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=final_temperature,
            max_tokens=final_max_tokens,
            response_format=response_format,
            task_type=task_type,
            novel_id=novel_id,
            chapter_id=chapter_id,
            character_id=character_id
        )

    async def check_health(self) -> bool:
        """检查 LLM API 状态"""
        # Ollama 通常不需要 API Key
        if not self.api_key and self.provider != "ollama":
            return False

        try:
            # 简单测试请求
            result = await self.chat_completion(
                system_prompt="You are a helpful assistant.",
                user_content="Hi",
                max_tokens=10
            )
            return result["success"]
        except Exception:
            return False

    # ============== 业务方法 ==============

    async def parse_novel_text(self, text: str, novel_id: str = None, source_range: str = None) -> Dict[str, Any]:
        """解析小说文本，提取角色、场景、分镜信息（支持章节范围）"""
        # 获取当前配置
        from app.core.config import get_settings
        settings = get_settings()
        system_prompt = settings.PARSE_CHARACTERS_PROMPT or DEFAULT_PARSE_CHARACTERS_PROMPT

        # 替换章节范围占位符
        if source_range:
            system_prompt = system_prompt.replace(CHAPTER_RANGE_PLACEHOLDER, source_range)
        else:
            system_prompt = system_prompt.replace(CHAPTER_RANGE_PLACEHOLDER, DEFAULT_CHAPTER_RANGE_DESCRIPTION)

        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=f"请解析以下小说文本：\n\n{text[:NOVEL_TEXT_MAX_LENGTH]}",
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=NOVEL_TEXT_MAX_LENGTH,
            response_format="json_object",
            task_type="parse_characters",
            novel_id=novel_id
        )

        if result["success"]:
            data = safe_parse_llm_json(result["content"], default=None)
            if not data:
                print(f"[parse_novel_text] JSON 解析失败，原始内容：{result['content'][:500]}")
                return {
                    "error": "JSON 解析失败",
                    "characters": [],
                    "scenes": [],
                    "shots": []
                }
            return {
                "characters": data.get("characters", []),
                "scenes": data.get("scenes", []),
                "shots": data.get("shots", [])
            }
        else:
            return {
                "error": result.get("error", "未知错误"),
                "characters": [],
                "scenes": [],
                "shots": []
            }

    async def generate_character_appearance(
        self,
        character_name: str,
        description: str,
        style: str = "anime",
        novel_id: str = None,
        character_id: str = None
    ) -> str:
        """生成角色外貌描述"""
        system_prompt = get_character_appearance_prompt(style)

        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=f"角色名称：{character_name}\n角色描述：{description}\n\n请生成详细的外貌描述：",
            temperature=0.8,
            max_tokens=1000,
            task_type="generate_character_appearance",
            novel_id=novel_id,
            character_id=character_id
        )

        if result["success"]:
            return clean_llm_response(result["content"]).strip()
        else:
            return DEFAULT_CHARACTER_APPEARANCE_FALLBACK.format(character_name=character_name)

    async def expand_video_prompt(self, prompt: str, duration: int = DEFAULT_VIDEO_DURATION) -> str:
        """扩写视频生成提示词"""
        user_content = f"""原始提示词：{prompt}
视频时长：{duration}秒

请扩写为详细的视频生成提示词："""

        result = await self.chat_completion(
            system_prompt=DEFAULT_VIDEO_PROMPT_EXPAND_SYSTEM,
            user_content=user_content,
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=2000
        )

        if result["success"]:
            return clean_llm_response(result["content"]).strip()
        else:
            return prompt

    async def generate_scene_setting(
        self,
        scene_name: str,
        description: str,
        style: str = "anime",
        novel_id: str = None
    ) -> str:
        """生成场景设定（环境设置）

        Args:
            scene_name: 场景名称
            description: 场景描述
            style: 画风风格
            novel_id: 小说 ID

        Returns:
            场景设定字符串（用于 AI 绘图的环境描述）
        """
        system_prompt = get_scene_setting_prompt(style)

        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=f"场景名称：{scene_name}\n场景描述：{description}\n\n请生成详细的环境设定描述：",
            temperature=0.8,
            max_tokens=1000,
            task_type="generate_scene_setting",
            novel_id=novel_id
        )

        if result["success"]:
            return clean_llm_response(result["content"]).strip()
        else:
            return DEFAULT_SCENE_SETTING_FALLBACK.format(scene_name=scene_name)

    async def generate_prop_appearance(
        self,
        prop_name: str,
        description: str,
        style: str = "anime",
        novel_id: str = None
    ) -> str:
        """生成道具外观描述

        Args:
            prop_name: 道具名称
            description: 道具描述
            style: 画风风格
            novel_id: 小说 ID

        Returns:
            道具外观描述字符串（用于 AI 绘图）
        """
        system_prompt = get_prop_appearance_prompt(style)

        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=f"道具名称：{prop_name}\n道具描述：{description}\n\n请生成详细的外观描述：",
            temperature=0.8,
            max_tokens=1000,
            task_type="generate_prop_appearance",
            novel_id=novel_id
        )

        if result["success"]:
            return clean_llm_response(result["content"]).strip()
        else:
            return DEFAULT_PROP_APPEARANCE_FALLBACK.format(prop_name=prop_name)


    async def parse_scenes(
        self,
        novel_id: str,
        chapter_content: str,
        chapter_title: str = "",
        prompt_template: str = None
    ) -> Dict[str, Any]:
        """解析场景信息

        Args:
            novel_id: 小说 ID
            chapter_content: 章节内容
            chapter_title: 章节标题
            prompt_template: 场景解析提示词模板

        Returns:
            {"scenes": [{"name": "", "description": "", "setting": ""}]}
        """
        system_prompt = prompt_template or DEFAULT_PARSE_SCENES_PROMPT

        user_content = f"""章节标题：{chapter_title}

章节内容：
{chapter_content[:CHAPTER_CONTENT_MAX_LENGTH]}

请解析以上文本中的场景信息。"""

        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=CHAPTER_CONTENT_MAX_LENGTH,
            response_format="json_object",
            task_type="parse_scenes",
            novel_id=novel_id
        )

        if result["success"]:
            data = safe_parse_llm_json(result["content"], default=None)
            if not data:
                print(f"[parse_scenes] JSON 解析失败，原始内容：{result['content'][:500]}")
                return {"scenes": []}
            return {
                "scenes": data.get("scenes", [])
            }
        else:
            return {
                "error": result.get("error", "未知错误"),
                "scenes": []
            }

    async def parse_props(
        self,
        text: str,
        prompt_template: str = None
    ) -> Dict[str, Any]:
        """
        解析小说文本中的道具信息

        Args:
            text: 小说文本
            prompt_template: 提示词模板（可选）

        Returns:
            道具解析结果
        """
        # 使用提供的模板或默认模板
        if not prompt_template:
            import os
            template_path = os.path.join(os.path.dirname(__file__), '..', 'prompt_templates', 'prop_parse.txt')
            if os.path.exists(template_path):
                with open(template_path, "r", encoding="utf-8") as f:
                    prompt_template = f.read()

        result = await self.chat_completion(
            system_prompt=prompt_template,
            user_content=text,
            temperature=0.3,
            max_tokens=4000,
            response_format="json_object",
            task_type="parse_props"
        )

        if result["success"]:
            data = safe_parse_llm_json(result["content"], default=None)
            if not data:
                print(f"[parse_props] JSON 解析失败，原始内容：{result['content'][:500]}")
                return {"props": [], "error": "JSON 解析失败"}
            return {
                "props": data.get("props", [])
            }
        else:
            return {
                "error": result.get("error", "未知错误"),
                "props": []
            }

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        response_format: Optional[str] = None
    ) -> str:
        """生成文本（兼容旧接口）"""
        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format
        )
        return result.get("content", "")

    async def split_chapter_with_prompt(
        self,
        chapter_title: str,
        chapter_content: str,
        prompt_template: str,
        word_count: int = 100,
        character_names: List[str] = None,
        scene_names: List[str] = None,
        prop_names: List[str] = None,
        style: str = "anime style, high quality, detailed",
        novel_id: str = None,
        chapter_id: str = None
    ) -> Dict[str, Any]:
        """使用自定义提示词将章节拆分为分镜数据结构"""

        # 替换提示词模板中的占位符
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
            allowed_characters_line = f"allowed_characters: {', '.join(character_names)}\n"

        # 构建 allowed_scenes 行
        allowed_scenes_line = ""
        if scene_names:
            allowed_scenes_line = f"allowed_scenes: {', '.join(scene_names)}\n"

        # 构建 allowed_props 行
        allowed_props_line = ""
        if prop_names:
            allowed_props_line = f"allowed_props: {', '.join(prop_names)}\n"

        # 合并白名单行
        whitelist_lines = ""
        if allowed_characters_line or allowed_scenes_line or allowed_props_line:
            whitelist_lines = allowed_characters_line + allowed_scenes_line + allowed_props_line + "\n"

        user_content = f"""{whitelist_lines}章节标题：{chapter_title}

章节内容：
{chapter_content[:CHAPTER_CONTENT_MAX_LENGTH]}

请将以上章节内容拆分为分镜数据结构。"""

        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=CHAPTER_CONTENT_MAX_LENGTH,
            response_format="json_object",
            task_type="split_chapter",
            novel_id=novel_id,
            chapter_id=chapter_id
        )

        if result["success"]:
            content = result["content"]
            data = safe_parse_llm_json(content)

            if not data:
                print(f"[split_chapter] JSON 解析失败")
                print(f"[split_chapter] 原始内容: {result['content'][:500]}")
                return {
                    "error": "JSON 解析失败",
                    "chapter": chapter_title,
                    "characters": [],
                    "scenes": [],
                    "shots": []
                }

            # 确保返回格式正确
            return {
                "chapter": data.get("chapter", chapter_title),
                "characters": data.get("characters", []),
                "scenes": data.get("scenes", []),
                "props": data.get("props", []),
                "shots": data.get("shots", [])
            }
        else:
            return {
                "error": result.get("error", "未知错误"),
                "chapter": chapter_title,
                "characters": [],
                "scenes": [],
                "shots": []
            }


def get_llm_service() -> LLMService:
    """获取 LLM 服务实例"""
    return LLMService()
