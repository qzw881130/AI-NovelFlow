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
                system_prompt=system_prompt[:10000] if system_prompt else None,  # 限制长度
                user_prompt=user_prompt[:20000] if user_prompt else None,  # 限制长度
                response=response[:20000] if response else None,  # 限制长度
                status=status,
                error_message=error_message[:5000] if error_message else None,
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
                client = httpx.AsyncClient(transport=transport, timeout=300.0)
            else:
                client = httpx.AsyncClient(proxy=proxies, timeout=300.0)
                old_http_proxy = old_https_proxy = old_http_proxy_lower = old_https_proxy_lower = None
            
            async with client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=300.0  # 增加到5分钟，给大模型足够加载时间
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
        # 使用数据库中保存的提示词，如果没有则使用默认提示词
        default_prompt = """你是一个专业的小说解析助手。请分析我提供的小说文本，提取以下信息并以 JSON 格式返回：

1) characters：角色列表。每个角色必须包含：
- name（姓名）
- description（描述）
- appearance（外貌特征：必须是一段完整自然语言描述的"单段文字"，禁止使用结构化字段/键值对/列表/分段标题）

【章节范围解析说明】
本次解析的文本来自：{章节范围说明}。请注意提取的角色应该是在此范围内新出现或重点描写的角色。

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
        
        # 获取当前配置
        from app.core.config import get_settings
        settings = get_settings()
        system_prompt = settings.PARSE_CHARACTERS_PROMPT or default_prompt
        
        # 替换章节范围占位符
        if source_range:
            system_prompt = system_prompt.replace("{章节范围说明}", source_range)
        else:
            system_prompt = system_prompt.replace("{章节范围说明}", "整部小说")
        
        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=f"请解析以下小说文本：\n\n{text[:15000]}",
            temperature=0.7,
            max_tokens=15000,
            response_format="json_object",
            task_type="parse_characters",
            novel_id=novel_id
        )
        
        if result["success"]:
            try:
                content = result["content"]
                # 处理 Ollama 模型可能返回的 <think>...</think> 标签
                if "<think>" in content and "</think>" in content:
                    # 提取 think 标签外的内容
                    content = content.split("</think>")[-1].strip()
                
                # 尝试从 Markdown 代码块中提取 JSON
                if "```json" in content:
                    content = content.split("```json")[-1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[-1].split("```")[0].strip()
                
                # 尝试找到 JSON 对象的开始和结束
                content = content.strip()
                if content.startswith("{") and content.endswith("}"):
                    return json.loads(content)
                
                # 尝试提取第一个 JSON 对象
                import re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    return json.loads(json_match.group())
                
                return json.loads(content)
            except json.JSONDecodeError as e:
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
{chapter_content[:15000]}

请将以上章节内容拆分为分镜数据结构。"""
        
        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=0.7,
            max_tokens=15000,
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
        system_prompt = f"""你是一个专业的场景设定助手。请根据提供的场景信息，生成一段详细的环境设定描述，用于AI绘图生成场景图。

【重要约束：场景不包含人物】
- 场景是纯粹的环境、地点、空间描述，不包含任何人物、角色、演员等元素
- 设定描述中禁止出现人物、人物动作、表情、姿态等
- 专注于环境本身：建筑、自然景观、室内布置、光线、天气、氛围等

要求：
1. 描述要具体、详细，包含：
   - 时间（白天/黄昏/夜晚）
   - 天气（晴天/雨天/雪天）
   - 光线（阳光/月光/灯光）
   - 建筑风格或自然景观特征
   - 主要物体和布局
   - 色调和氛围
   - 透视角度
2. 使用英文（AI绘图模型对英文理解更好）
3. 添加画风提示词，如：{style} style, high quality, detailed, environment design, background art
4. 避免模糊词汇，使用具体的颜色和样式描述
5. 必须添加 "no characters, empty scene" 确保不生成人物

示例输出格式：
Traditional Chinese courtyard, ancient wooden architecture with curved roofs, red pillars and golden decorations, stone pathway, blooming cherry blossom trees, soft morning sunlight filtering through leaves, peaceful atmosphere, spring season, wide angle view, anime style, high quality, detailed, environment design, no characters, empty scene"""
        
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
            return f"{scene_name}, environment design, background art, high quality, detailed, no characters, empty scene"


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
        default_prompt = """你是一个专业的小说场景解析助手。请分析我提供的小说文本，提取所有场景信息并以 JSON 格式返回。

场景是指故事发生的地点、环境或空间。同一地点在不同时间的多个事件属于同一个场景。

【场景命名唯一性与一致性（必须严格执行）】
- 所有场景 name 必须在首次解析时确定为唯一标准名称，并在后续所有步骤中严格复用该名称。
- 场景名称应简洁明确，如"萧家门口"、"萧家大厅"、"练武场"等。
- 一旦 name 确定，后续输出不得更改、简化或替换；所有场景引用必须完全一致。

【每个场景必须包含】
- name（场景名称）：简洁的唯一标识符
- description（场景描述）：描述场景的整体感觉、氛围、主要元素
- setting（环境设置）：用于AI绘图的详细环境描述，包括：
  - 时间（白天/黄昏/夜晚）
  - 天气（晴天/雨天/雪天）
  - 光线（阳光/月光/灯光）
  - 主要物体和布局
  - 色调和氛围

【输出格式要求】
只返回合法 JSON，不得输出任何解释性文字。

{
  "scenes": [
    {
      "name": "场景名称",
      "description": "场景的整体描述",
      "setting": "详细的绘图用环境描述"
    }
  ]
}"""
        
        system_prompt = prompt_template or default_prompt
        
        user_content = f"""章节标题：{chapter_title}

章节内容：
{chapter_content[:15000]}

请解析以上文本中的场景信息。"""
        
        result = await self.chat_completion(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=0.7,
            max_tokens=15000,
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


# 兼容旧导入
DeepSeekService = LLMService
