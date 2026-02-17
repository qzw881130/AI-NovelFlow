"""
LLM 服务封装 - 支持多厂商调用 (DeepSeek, OpenAI, Gemini, Anthropic, Azure, Custom)
"""
import httpx
import json
from typing import Dict, Any, List, Optional
from app.core.config import get_settings

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
    character_id: str = None
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
                system_prompt=system_prompt[:10000] if system_prompt else None,  # 限制长度
                user_prompt=user_prompt[:20000] if user_prompt else None,  # 限制长度
                response=response[:20000] if response else None,  # 限制长度
                status=status,
                error_message=error_message[:5000] if error_message else None,
                task_type=task_type,
                novel_id=novel_id,
                chapter_id=chapter_id,
                character_id=character_id
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
        
        # 代理配置
        self.proxy_enabled = current_settings.PROXY_ENABLED
        self.http_proxy = current_settings.HTTP_PROXY
        self.https_proxy = current_settings.HTTPS_PROXY
        
        # 如果没有配置新的 LLM，尝试兼容旧配置
        if not self.api_key:
            self.api_key = current_settings.DEEPSEEK_API_KEY
            self.api_url = current_settings.DEEPSEEK_API_URL
            self.provider = "deepseek"
    
    def _get_proxy_config(self) -> Optional[str]:
        """获取代理配置 - 返回单个代理URL (httpx 0.20+ 使用 proxy 参数)"""
        if not self.proxy_enabled:
            return None
        
        # httpx 0.20+ 使用 proxy 参数，可以是单个URL字符串
        # 优先使用 HTTPS 代理，如果没有则使用 HTTP 代理
        return self.https_proxy or self.http_proxy or None
    
    def _get_headers(self) -> Dict[str, str]:
        """获取 API 请求头"""
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.provider == "anthropic":
            headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = "2023-06-01"
        elif self.provider == "azure":
            headers["api-key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        return headers
    
    def _build_request_body(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
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
        
        if self.provider == "gemini":
            # Gemini 格式
            return response_data["candidates"][0]["content"]["parts"][0]["text"]
        
        elif self.provider == "anthropic":
            # Anthropic 格式
            return response_data["content"][0]["text"]
        
        else:
            # OpenAI / DeepSeek / Azure / Custom 格式
            return response_data["choices"][0]["message"]["content"]
    
    def _get_endpoint(self) -> str:
        """获取 API 端点 URL"""
        base = self.api_url.rstrip("/")
        
        if self.provider == "gemini":
            # Gemini 使用不同的 URL 格式
            return f"{base}/models/{self.model}:generateContent?key={self.api_key}"
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
        temperature: float = 0.7,
        max_tokens: int = 4000,
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
        if not self.api_key:
            return {"success": False, "error": "API Key 未配置", "content": ""}
        
        endpoint = self._get_endpoint()
        headers = self._get_headers()
        body = self._build_request_body(
            system_prompt, user_content, temperature, max_tokens, response_format
        )
        proxies = self._get_proxy_config()
        
        try:
            async with httpx.AsyncClient(proxy=proxies) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=120.0
                )
                
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
                        character_id=character_id
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
                        character_id=character_id
                    )
                    
                    return {
                        "success": False,
                        "error": error_msg,
                        "content": ""
                    }
                    
        except Exception as e:
            error_msg = f"请求异常: {str(e)}"
            
            # 记录异常日志
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
                character_id=character_id
            )
            
            return {
                "success": False,
                "error": error_msg,
                "content": ""
            }
    
    async def check_health(self) -> bool:
        """检查 LLM API 状态"""
        if not self.api_key:
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
    
    async def parse_novel_text(self, text: str, novel_id: str = None) -> Dict[str, Any]:
        """解析小说文本，提取角色、场景、分镜信息"""
        # 使用数据库中保存的提示词，如果没有则使用默认提示词
        default_prompt = """你是一个专业的小说解析助手。请分析提供的小说文本，提取以下信息并以JSON格式返回：

1. characters: 角色列表，每个角色包含 name（姓名）、description（描述）、appearance（外貌特征）
2. scenes: 场景列表，每个场景包含 title（标题）、description（描述）
3. shots: 分镜列表，每个分镜包含 scene_id（所属场景）、description（画面描述）、camera_angle（镜头角度）

注意：
- 角色外貌特征要详细，用于AI绘图
- 分镜描述要具体，包含画面构图、角色动作、环境细节
- 返回必须是合法的JSON格式
"""
        
        # 获取当前配置
        from app.core.config import get_settings
        settings = get_settings()
        system_prompt = settings.PARSE_CHARACTERS_PROMPT or default_prompt
        
        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=f"请解析以下小说文本：\n\n{text[:8000]}",
            temperature=0.7,
            max_tokens=4000,
            response_format="json_object",
            task_type="parse_characters",
            novel_id=novel_id
        )
        
        if result["success"]:
            try:
                return json.loads(result["content"])
            except json.JSONDecodeError:
                return {"error": "JSON 解析失败", "characters": [], "scenes": [], "shots": []}
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
        chapter_id: str = None
    ) -> Dict[str, Any]:
        """使用自定义提示词将章节拆分为分镜数据结构"""
        
        system_prompt = prompt_template.replace(
            "{每个分镜对应拆分故事字数}", str(word_count)
        ).replace(
            "{图像风格}", "anime style, high quality, detailed"
        )
        
        user_content = f"""章节标题：{chapter_title}

章节内容：
{chapter_content[:15000]}

请将以上章节内容拆分为分镜数据结构。"""
        
        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=0.7,
            max_tokens=8000,
            response_format="json_object",
            task_type="split_chapter",
            novel_id=novel_id,
            chapter_id=chapter_id
        )
        
        if result["success"]:
            try:
                data = json.loads(result["content"])
                # 确保返回格式正确
                return {
                    "chapter": data.get("chapter", chapter_title),
                    "characters": data.get("characters", []),
                    "scenes": data.get("scenes", []),
                    "shots": data.get("shots", [])
                }
            except json.JSONDecodeError:
                return {
                    "error": "JSON 解析失败",
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
        system_prompt = f"""你是一个专业的角色设定助手。请根据提供的角色信息，生成一段详细的外貌描述，用于AI绘图生成角色形象。

要求：
1. 描述要具体、详细，包含：发型、发色、眼睛、服装、配饰、表情、姿态
2. 使用英文（AI绘图模型对英文理解更好）
3. 添加画风提示词，如：{style} style, high quality, detailed
4. 避免模糊词汇，使用具体的颜色和样式描述

示例输出格式：
Young female character, long flowing silver hair with blue highlights, sharp blue eyes, delicate features, wearing traditional Chinese hanfu in white and blue colors, jade hairpin, gentle smile, standing pose, clean background, anime style, high quality, detailed, 8k"""
        
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
            return f"{character_name}, detailed character, high quality"
    
    async def expand_video_prompt(self, prompt: str, duration: int = 4) -> str:
        """扩写视频生成提示词"""
        system_prompt = """你是一个专业的视频生成提示词优化专家。请将用户的简短描述扩写为详细的视频生成提示词。

要求：
1. 添加画面主体、动作、场景的详细描述
2. 包含镜头运动方式（平移、推拉、旋转等）
3. 描述光线、氛围、色调
4. 添加画风和质量提示词
5. 保持描述简洁但信息丰富，适合视频生成模型

输出格式：
直接输出扩写后的提示词，不要有多余的解释。"""
        
        user_content = f"""原始提示词：{prompt}
视频时长：{duration}秒

请扩写为详细的视频生成提示词："""
        
        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=0.7,
            max_tokens=2000
        )
        
        if result["success"]:
            return result["content"].strip()
        else:
            return prompt


# 兼容旧导入
DeepSeekService = LLMService
