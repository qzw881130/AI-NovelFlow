"""
LLM 服务封装 - 支持多厂商调用 (DeepSeek, OpenAI, Gemini, Anthropic, Azure, Custom)
"""
import httpx
import json
from typing import Dict, Any, List, Optional
from app.core.config import get_settings
from app.utils.json_parser import safe_parse_llm_json
from app.constants import (
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT,
    DEFAULT_VIDEO_DURATION,
    LOG_SYSTEM_PROMPT_MAX_LENGTH,
    LOG_USER_PROMPT_MAX_LENGTH,
    LOG_RESPONSE_MAX_LENGTH,
    LOG_ERROR_MESSAGE_MAX_LENGTH,
    NOVEL_TEXT_MAX_LENGTH,
    CHAPTER_CONTENT_MAX_LENGTH,
    DEFAULT_PARSE_CHARACTERS_PROMPT,
    CHAPTER_RANGE_PLACEHOLDER,
    DEFAULT_CHAPTER_RANGE_DESCRIPTION,
    DEFAULT_PARSE_SCENES_PROMPT,
    DEFAULT_VIDEO_PROMPT_EXPAND_SYSTEM,
    DEFAULT_CHARACTER_APPEARANCE_FALLBACK,
    DEFAULT_SCENE_SETTING_FALLBACK,
    get_character_appearance_prompt,
    get_scene_setting_prompt,
)

settings = get_settings()


def save_llm_log(
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    response: str = None,
    status: str = "success",
    error_message: str = None,
    task_type: str = None,
    novel_id: str = None,
    chapter_id: str = None,
    character_id: str = None,
    used_proxy: bool = False,
    duration: float = None
):
    """保存LLM调用日志到数据库（异步执行，不阻塞主流程）"""
    try:
        from app.core.database import SessionLocal
        from app.models.llm_log import LLMLog
        
        db = SessionLocal()
        try:
            log = LLMLog(
                provider=provider,
                model=model,
                system_prompt=system_prompt[:LOG_SYSTEM_PROMPT_MAX_LENGTH] if system_prompt else None,
                user_prompt=user_prompt[:LOG_USER_PROMPT_MAX_LENGTH] if user_prompt else None,
                response=response[:LOG_RESPONSE_MAX_LENGTH] if response else None,
                status=status,
                error_message=error_message[:LOG_ERROR_MESSAGE_MAX_LENGTH] if error_message else None,
                task_type=task_type,
                novel_id=novel_id,
                chapter_id=chapter_id,
                character_id=character_id,
                used_proxy=used_proxy,
                duration=duration
            )
            db.add(log)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[LLM Log] 保存日志失败: {e}")


class LLMService:
    """多厂商 LLM API 服务封装"""
    
    def __init__(self):
        # 每次实例化时重新获取 settings，确保获取最新配置
        from app.core.config import get_settings
        current_settings = get_settings()
        
        self.provider = current_settings.LLM_PROVIDER
        self.model = current_settings.LLM_MODEL
        self.api_url = current_settings.LLM_API_URL
        self.api_key = current_settings.LLM_API_KEY
        self.max_tokens = getattr(current_settings, 'LLM_MAX_TOKENS', None)  # 从配置中获取max_tokens
        self.temperature = getattr(current_settings, 'LLM_TEMPERATURE', None)  # 从配置中获取temperature
        
        # 代理配置
        self.proxy_enabled = current_settings.PROXY_ENABLED
        self.http_proxy = current_settings.HTTP_PROXY
        self.https_proxy = current_settings.HTTPS_PROXY
        
        # 如果没有配置新的 LLM，且不是 Ollama（Ollama 可以没有 API Key），尝试兼容旧配置
        if not self.api_key and self.provider != "ollama":
            self.api_key = current_settings.DEEPSEEK_API_KEY
            self.api_url = current_settings.DEEPSEEK_API_URL
            self.provider = "deepseek"
        
        # 初始化API Key轮询机制
        self.api_keys = []
        if self.api_key:
            # 支持多API Key，逗号分隔
            self.api_keys = [key.strip() for key in self.api_key.split(',') if key.strip()]
        else:
            self.api_keys = []
        
        # 当前使用的API Key索引
        self.current_key_index = 0
    
    def _get_proxy_config(self) -> Optional[str]:
        """获取代理配置 - 返回单个代理URL (httpx 0.20+ 使用 proxy 参数)"""
        if not self.proxy_enabled:
            return None
        
        # Ollama 通常是本地/内网服务，不需要走代理
        if self.provider == "ollama":
            return None
        
        # httpx 0.20+ 使用 proxy 参数，可以是单个URL字符串
        # 优先使用 HTTPS 代理，如果没有则使用 HTTP 代理
        return self.https_proxy or self.http_proxy or None
    
    def _get_headers(self) -> Dict[str, str]:
        """获取 API 请求头"""
        headers = {
            "Content-Type": "application/json"
        }
        
        # 获取当前使用的API Key
        current_api_key = self._get_current_api_key()
        
        if self.provider == "anthropic":
            headers["x-api-key"] = current_api_key
            headers["anthropic-version"] = "2023-06-01"
        elif self.provider == "azure":
            headers["api-key"] = current_api_key
        elif self.provider == "ollama":
            # Ollama 通常不需要 API Key，但如果配置了也可以使用
            if current_api_key:
                headers["Authorization"] = f"Bearer {current_api_key}"
        else:
            headers["Authorization"] = f"Bearer {current_api_key}"
        
        return headers
    
    def _get_current_api_key(self) -> str:
        """获取当前使用的API Key，支持轮询"""
        if not self.api_keys:
            return self.api_key or ""
        
        # 获取当前API Key
        current_key = self.api_keys[self.current_key_index]
        
        # 更新索引，准备下次轮询
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        
        return current_key
    
    def _build_request_body(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        response_format: Optional[str] = None
    ) -> Dict[str, Any]:
        """构建 API 请求体（根据厂商格式）"""
        
        if self.provider == "gemini":
            # Google Gemini 格式
            body = {
                "contents": [
                    {"role": "user", "parts": [{"text": system_prompt + "\n\n" + user_content}]}
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                }
            }
            if response_format == "json_object":
                body["generationConfig"]["responseMimeType"] = "application/json"
            return body
        
        elif self.provider == "anthropic":
            # Anthropic Claude 格式
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            return body
        
        elif self.provider == "azure":
            # Azure OpenAI 格式
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            if response_format == "json_object":
                body["response_format"] = {"type": "json_object"}
            return body
        
        elif self.provider == "ollama":
            # Ollama 格式（OpenAI 兼容，但部分参数限制不同）
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                "temperature": temperature,
                # Ollama 对 max_tokens 支持不稳定，72B 大模型可能不支持太大的值
                # 不设置 max_tokens，让模型自己决定输出长度
            }
            # Ollama 的 response_format 支持不完整，通过 system_prompt 要求 JSON 更可靠
            # 不设置 response_format 参数
            return body
        
        else:
            # OpenAI / DeepSeek / Custom 格式
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            if response_format == "json_object":
                body["response_format"] = {"type": "json_object"}
            return body
    
    def _parse_response(self, response_data: Dict[str, Any]) -> str:
        """解析不同厂商的响应格式"""
        
        try:
            if self.provider == "gemini":
                # Gemini 格式
                return response_data["candidates"][0]["content"]["parts"][0]["text"]
            
            elif self.provider == "anthropic":
                # Anthropic 格式
                return response_data["content"][0]["text"]
            
            else:
                # OpenAI / DeepSeek / Azure / Custom / Ollama 格式
                # Ollama 返回的格式与 OpenAI 兼容
                if "choices" not in response_data:
                    print(f"[_parse_response] 警告: 响应中没有 'choices' 字段: {response_data}")
                    return str(response_data)
                if not response_data["choices"]:
                    print(f"[_parse_response] 警告: 'choices' 为空数组: {response_data}")
                    return str(response_data)
                
                if "message" not in response_data["choices"][0]:
                    print(f"[_parse_response] 警告: 没有 'message' 字段: {response_data['choices'][0]}")
                    return str(response_data)
                
                message = response_data["choices"][0]["message"]
                content = message.get("content", "")
                # Ollama 某些模型（如 qwen3）可能返回空的 content，但包含 reasoning
                if not content and "reasoning" in message:
                    content = message["reasoning"]
                return content
        except (KeyError, IndexError, TypeError) as e:
            print(f"[_parse_response] 解析失败: {e}")
            print(f"[_parse_response] 响应数据: {response_data}")
            raise
    
    def _get_endpoint(self) -> str:
        """获取 API 端点 URL"""
        base = self.api_url.rstrip("/")
        
        if self.provider == "gemini":
            # Gemini 使用不同的 URL 格式
            current_api_key = self._get_current_api_key()
            return f"{base}/models/{self.model}:generateContent?key={current_api_key}"
        elif self.provider == "anthropic":
            return f"{base}/messages"
        elif self.provider == "azure":
            # Azure URL 包含 deployment
            return f"{base}/chat/completions?api-version=2024-02-01"
        else:
            return f"{base}/chat/completions"
    
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
        
        Returns:
            {
                "success": bool,
                "content": str,
                "error": str (optional)
            }
        """
        import time  # 添加时间模块导入
        
        # 记录请求开始时间
        start_time = time.time()
        
        # Ollama 通常不需要 API Key
        if not self.api_keys and self.provider != "ollama":
            return {"success": False, "error": "API Key 未配置", "content": ""}
        
        # 使用配置的参数，如果提供了则覆盖默认值
        final_temperature = float(self.temperature) if self.temperature else temperature
        final_max_tokens = self.max_tokens if self.max_tokens is not None else max_tokens
        
        endpoint = self._get_endpoint()
        headers = self._get_headers()
        body = self._build_request_body(
            system_prompt, user_content, final_temperature, final_max_tokens, response_format
        )
        proxies = self._get_proxy_config()
        used_proxy = proxies is not None
        print(f"[chat_completion] 调用 API: {endpoint}，请求体: {body}，请求头: {headers}，代理: {proxies}")
        try:
            # Ollama 和自定义 API（通常是本地/内网服务）需要禁用环境变量代理
            import os
            if self.provider in ("ollama", "custom"):
                # 临时清除环境变量代理设置
                old_http_proxy = os.environ.pop('HTTP_PROXY', None)
                old_https_proxy = os.environ.pop('HTTPS_PROXY', None)
                old_http_proxy_lower = os.environ.pop('http_proxy', None)
                old_https_proxy_lower = os.environ.pop('https_proxy', None)
                
                transport = httpx.AsyncHTTPTransport(proxy=None)
                client = httpx.AsyncClient(transport=transport, timeout=DEFAULT_TIMEOUT)
            else:
                client = httpx.AsyncClient(proxy=proxies, timeout=DEFAULT_TIMEOUT)
                old_http_proxy = old_https_proxy = old_http_proxy_lower = old_https_proxy_lower = None
            
            async with client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=DEFAULT_TIMEOUT
                )
            
            # Ollama/自定义 API 请求完成后恢复环境变量
            if self.provider in ("ollama", "custom"):
                if old_http_proxy:
                    os.environ['HTTP_PROXY'] = old_http_proxy
                if old_https_proxy:
                    os.environ['HTTPS_PROXY'] = old_https_proxy
                if old_http_proxy_lower:
                    os.environ['http_proxy'] = old_http_proxy_lower
                if old_https_proxy_lower:
                    os.environ['https_proxy'] = old_https_proxy_lower
            
            # 记录请求结束时间并计算耗时
            end_time = time.time()
            duration = end_time - start_time
            
            # 处理响应（所有 provider 共用）
            if response.status_code == 200:
                data = response.json()
                content = self._parse_response(data)
                
                # 记录成功日志
                save_llm_log(
                    provider=self.provider,
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_content,
                    response=content,
                    status="success",
                    task_type=task_type,
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                    character_id=character_id,
                    used_proxy=used_proxy,
                    duration=duration
                )
                
                return {
                    "success": True,
                    "content": content,
                    "raw_response": data
                }
            else:
                error_msg = f"API 错误 ({response.status_code}): {response.text}"
                
                # 记录失败日志
                save_llm_log(
                    provider=self.provider,
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_content,
                    status="error",
                    error_message=error_msg,
                    task_type=task_type,
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                    character_id=character_id,
                    used_proxy=used_proxy,
                    duration=duration
                )
                
                return {
                    "success": False,
                    "error": error_msg,
                    "content": ""
                }
                    
        except Exception as e:
            import traceback
            error_type = type(e).__name__
            error_detail = str(e) if str(e) else "(无详细错误信息)"
            error_msg = f"请求异常: [{error_type}] {error_detail}"
            
            # 记录详细错误信息到控制台
            print(f"[LLMService] {error_msg}")
            traceback.print_exc()
            
            # 记录异常日志（即使异常也记录耗时）
            end_time = time.time()
            duration = end_time - start_time
            
            save_llm_log(
                provider=self.provider,
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_content,
                status="error",
                error_message=error_msg,
                task_type=task_type,
                novel_id=novel_id,
                chapter_id=chapter_id,
                character_id=character_id,
                used_proxy=used_proxy,
                duration=duration
            )
            
            return {
                "success": False,
                "error": error_msg,
                "content": ""
            }
    
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
            try:
                # 使用统一的 JSON 解析工具
                parsed = safe_parse_llm_json(result["content"], {})
                return parsed
            except Exception as e:
                print(f"[parse_novel_text] JSON 解析失败: {e}")
                print(f"[parse_novel_text] 原始内容: {result['content'][:500]}")
                return {"error": f"JSON 解析失败: {e}", "characters": [], "scenes": [], "shots": []}
        else:
            return {
                "error": result.get("error", "未知错误"),
                "characters": [],
                "scenes": [],
                "shots": []
            }
    
    async def split_chapter_with_prompt(
        self,
        chapter_title: str,
        chapter_content: str,
        prompt_template: str,
        word_count: int = 50,
        novel_id: str = None,
        chapter_id: str = None,
        character_names: list = None,
        scene_names: list = None,
        style: str = "anime style, high quality, detailed"
    ) -> Dict[str, Any]:
        """使用自定义提示词将章节拆分为分镜数据结构"""
        
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
        
        # 合并白名单行
        whitelist_lines = ""
        if allowed_characters_line or allowed_scenes_line:
            whitelist_lines = allowed_characters_line + allowed_scenes_line + "\n"
        
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
            try:
                content = result["content"]
                # 处理 Ollama 模型可能返回的 <think>...</think> 标签
                if "<think>" in content and "</think>" in content:
                    content = content.split("</think>")[-1].strip()
                
                # 尝试从 Markdown 代码块中提取 JSON
                if "```json" in content:
                    content = content.split("```json")[-1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[-1].split("```")[0].strip()
                
                # 尝试找到 JSON 对象
                content = content.strip()
                if not (content.startswith("{") and content.endswith("}")):
                    import re
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if json_match:
                        content = json_match.group()
                
                data = json.loads(content)
                # 确保返回格式正确
                return {
                    "chapter": data.get("chapter", chapter_title),
                    "characters": data.get("characters", []),
                    "scenes": data.get("scenes", []),
                    "shots": data.get("shots", [])
                }
            except json.JSONDecodeError as e:
                print(f"[split_chapter] JSON 解析失败: {e}")
                print(f"[split_chapter] 原始内容: {result['content'][:500]}")
                return {
                    "error": f"JSON 解析失败: {e}",
                    "chapter": chapter_title,
                    "characters": [],
                    "scenes": [],
                    "shots": []
                }
        else:
            return {
                "error": result.get("error", "未知错误"),
                "chapter": chapter_title,
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
            return result["content"].strip()
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
            return result["content"].strip()
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
            novel_id: 小说ID
            
        Returns:
            场景设定字符串（用于AI绘图的环境描述）
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
            return result["content"].strip()
        else:
            return DEFAULT_SCENE_SETTING_FALLBACK.format(scene_name=scene_name)


    async def parse_scenes(
        self,
        novel_id: str,
        chapter_content: str,
        chapter_title: str = "",
        prompt_template: str = None
    ) -> Dict[str, Any]:
        """解析场景信息
        
        Args:
            novel_id: 小说ID
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
            try:
                content = result["content"]
                # 处理 Ollama 模型可能返回的  heures...</think> 标签
                if " heures" in content and " hours" in content:
                    content = content.split(" hours")[-1].strip()
                
                # 尝试从 Markdown 代码块中提取 JSON
                if " hours```json" in content:
                    content = content.split(" hours```json")[-1].split(" hours```")[0].strip()
                elif " hours```" in content:
                    content = content.split(" hours```")[-1].split(" hours```")[0].strip()
                
                # 尝试找到 JSON 对象
                content = content.strip()
                if not (content.startswith("{") and content.endswith("}")):
                    import re
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if json_match:
                        content = json_match.group()
                
                data = json.loads(content)
                return {
                    "scenes": data.get("scenes", [])
                }
            except json.JSONDecodeError as e:
                print(f"[parse_scenes] JSON 解析失败: {e}")
                print(f"[parse_scenes] 原始内容: {result['content'][:500]}")
                return {"scenes": []}
        else:
            return {
                "error": result.get("error", "未知错误"),
                "scenes": []
            }

