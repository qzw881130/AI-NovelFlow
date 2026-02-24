"""系统配置 API - 支持持久化存储到数据库"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import get_settings, update_settings
from app.core.security import encrypt_value, decrypt_value
from app.models.system_config import SystemConfig as SystemConfigModel

router = APIRouter()


class LLMConfig(BaseModel):
    """LLM 配置"""
    provider: str
    model: str
    apiKey: str
    apiUrl: str
    maxTokens: Optional[int] = None  # 最大token数
    temperature: Optional[str] = None  # 温度参数（字符串类型，支持范围0.0-2.0）


class ProxyConfig(BaseModel):
    """代理配置"""
    enabled: bool
    httpProxy: Optional[str] = None
    httpsProxy: Optional[str] = None


class SystemConfigUpdate(BaseModel):
    """系统配置更新"""
    llm: Optional[LLMConfig] = None
    proxy: Optional[ProxyConfig] = None
    comfyUIHost: Optional[str] = None
    outputResolution: Optional[str] = None
    outputFrameRate: Optional[int] = None
    parseCharactersPrompt: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None


def get_or_create_config(db: Session) -> SystemConfigModel:
    """获取或创建系统配置记录"""
    config = db.query(SystemConfigModel).filter_by(id="default").first()
    if not config:
        config = SystemConfigModel(id="default")
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/")
async def get_config(db: Session = Depends(get_db)):
    """获取系统配置（不包含敏感信息）"""
    config = get_or_create_config(db)
    
    return {
        "success": True,
        "data": {
            # LLM 配置（不包含 API Key）
            "llmProvider": config.llm_provider,
            "llmModel": config.llm_model,
            "llmApiUrl": config.llm_api_url,
            "llmMaxTokens": config.llm_max_tokens,
            "llmTemperature": config.llm_temperature,
            # 代理配置
            "proxyEnabled": config.proxy_enabled,
            "httpProxy": config.http_proxy,
            "httpsProxy": config.https_proxy,
            # ComfyUI 配置
            "comfyUIHost": config.comfyui_host,
            # 输出配置
            "outputResolution": config.output_resolution,
            "outputFrameRate": config.output_frame_rate,
            # AI解析角色系统提示词
            "parseCharactersPrompt": config.parse_characters_prompt,
            # 界面配置
            "language": config.language or "zh-CN",
            "timezone": config.timezone or "Asia/Shanghai",
        }
    }


@router.get("/full")
async def get_full_config(db: Session = Depends(get_db)):
    """获取完整系统配置（包含解密后的 API Key，仅用于后端初始化）"""
    config = get_or_create_config(db)
    
    # 解密 API Key
    api_key = decrypt_value(config.llm_api_key) if config.llm_api_key else ""
    
    return {
        "success": True,
        "data": {
            "llm_provider": config.llm_provider,
            "llm_model": config.llm_model,
            "llm_api_url": config.llm_api_url,
            "llm_api_key": api_key,
            "llm_max_tokens": config.llm_max_tokens,
            "llm_temperature": config.llm_temperature,
            "proxy_enabled": config.proxy_enabled,
            "http_proxy": config.http_proxy,
            "https_proxy": config.https_proxy,
            "comfyui_host": config.comfyui_host,
            "output_resolution": config.output_resolution,
            "output_frame_rate": config.output_frame_rate,
            "parse_characters_prompt": config.parse_characters_prompt,
            "language": config.language or "zh-CN",
            "timezone": config.timezone or "Asia/Shanghai",
        }
    }


@router.post("/")
async def update_config(config: SystemConfigUpdate, db: Session = Depends(get_db)):
    """更新系统配置并持久化到数据库"""
    try:
        db_config = get_or_create_config(db)
        updates = {}
        
        if config.llm:
            db_config.llm_provider = config.llm.provider
            db_config.llm_model = config.llm.model
            db_config.llm_api_url = config.llm.apiUrl
            db_config.llm_max_tokens = config.llm.maxTokens
            db_config.llm_temperature = config.llm.temperature
            
            updates["llm_provider"] = config.llm.provider
            updates["llm_model"] = config.llm.model
            updates["llm_api_url"] = config.llm.apiUrl
            updates["llm_max_tokens"] = config.llm.maxTokens
            updates["llm_temperature"] = config.llm.temperature
            
            if config.llm.apiKey:
                # 加密存储 API Key
                encrypted_key = encrypt_value(config.llm.apiKey)
                db_config.llm_api_key = encrypted_key
                updates["llm_api_key"] = config.llm.apiKey
        
        if config.proxy:
            db_config.proxy_enabled = config.proxy.enabled
            db_config.http_proxy = config.proxy.httpProxy
            db_config.https_proxy = config.proxy.httpsProxy
            
            updates["proxy_enabled"] = config.proxy.enabled
            updates["http_proxy"] = config.proxy.httpProxy
            updates["https_proxy"] = config.proxy.httpsProxy
        
        if config.comfyUIHost:
            db_config.comfyui_host = config.comfyUIHost
            updates["comfyui_host"] = config.comfyUIHost
        
        if config.outputResolution:
            db_config.output_resolution = config.outputResolution
            updates["output_resolution"] = config.outputResolution
        
        if config.outputFrameRate:
            db_config.output_frame_rate = config.outputFrameRate
            updates["output_frame_rate"] = config.outputFrameRate
        
        if config.parseCharactersPrompt is not None:
            db_config.parse_characters_prompt = config.parseCharactersPrompt
            updates["parse_characters_prompt"] = config.parseCharactersPrompt
        
        if config.language is not None:
            db_config.language = config.language
            updates["language"] = config.language
        
        if config.timezone is not None:
            db_config.timezone = config.timezone
            updates["timezone"] = config.timezone
        
        # 提交数据库事务
        db.commit()
        db.refresh(db_config)
        
        # 同步更新内存中的配置
        update_settings(updates)
        
        return {"success": True, "message": "配置已更新"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"配置更新失败: {str(e)}")


@router.get("/llm-presets")
async def get_llm_presets():
    """获取 LLM 厂商预设配置"""
    return {
        "success": True,
        "data": [
            {
                "id": "deepseek",
                "name": "DeepSeek",
                "defaultApiUrl": "https://api.deepseek.com",
                "models": [
                    {"id": "deepseek-chat", "name": "DeepSeek Chat", "description": "通用对话模型", "maxTokens": 8192},
                    {"id": "deepseek-coder", "name": "DeepSeek Coder", "description": "代码专用模型", "maxTokens": 8192},
                    {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner", "description": "推理模型", "maxTokens": 8192},
                ],
                "apiKeyPlaceholder": "sk-...",
                "apiKeyHelp": "在 DeepSeek 控制台获取 API Key",
            },
            {
                "id": "openai",
                "name": "OpenAI",
                "defaultApiUrl": "https://api.openai.com/v1",
                "models": [
                    {"id": "gpt-4o", "name": "GPT-4o", "description": "多模态旗舰模型", "maxTokens": 128000},
                    {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "description": "轻量快速模型", "maxTokens": 128000},
                    {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "description": "高性能模型", "maxTokens": 128000},
                    {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "description": "经济实用模型", "maxTokens": 16385},
                ],
                "apiKeyPlaceholder": "sk-...",
                "apiKeyHelp": "在 OpenAI 控制台获取 API Key",
            },
            {
                "id": "gemini",
                "name": "Google Gemini",
                "defaultApiUrl": "https://generativelanguage.googleapis.com/v1beta",
                "models": [
                    {"id": "gemini-2.5-flash-preview-05-20", "name": "Gemini 2.5 Flash Preview", "description": "快速预览版", "maxTokens": 1000000},
                    {"id": "gemini-2.5-pro-preview-05-20", "name": "Gemini 2.5 Pro Preview", "description": "专业预览版", "maxTokens": 1000000},
                    {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "description": "快速模型", "maxTokens": 1000000},
                    {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash Lite", "description": "轻量快速模型", "maxTokens": 1000000},
                    {"id": "gemini-2.0-pro-exp-02-05", "name": "Gemini 2.0 Pro Exp", "description": "实验性专业版", "maxTokens": 2000000},
                ],
                "apiKeyPlaceholder": "AI...",
                "apiKeyHelp": "在 Google AI Studio 获取 API Key",
            },
            {
                "id": "anthropic",
                "name": "Anthropic Claude",
                "defaultApiUrl": "https://api.anthropic.com/v1",
                "models": [
                    {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "description": "平衡性能与速度", "maxTokens": 200000},
                    {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus", "description": "最强性能模型", "maxTokens": 200000},
                    {"id": "claude-3-sonnet-20240229", "name": "Claude 3 Sonnet", "description": "平衡模型", "maxTokens": 200000},
                    {"id": "claude-3-haiku-20240307", "name": "Claude 3 Haiku", "description": "快速轻量模型", "maxTokens": 200000},
                ],
                "apiKeyPlaceholder": "sk-ant-...",
                "apiKeyHelp": "在 Anthropic 控制台获取 API Key",
            },
            {
                "id": "azure",
                "name": "Azure OpenAI",
                "defaultApiUrl": "https://{your-resource}.openai.azure.com/openai/deployments/{deployment-id}",
                "models": [
                    {"id": "gpt-4o", "name": "GPT-4o", "description": "多模态旗舰模型"},
                    {"id": "gpt-4", "name": "GPT-4", "description": "高性能模型"},
                    {"id": "gpt-35-turbo", "name": "GPT-3.5 Turbo", "description": "经济实用模型"},
                ],
                "apiKeyPlaceholder": "...",
                "apiKeyHelp": "在 Azure Portal 获取 API Key 和 Endpoint",
            },
            {
                "id": "aliyun-bailian",
                "name": "阿里云百炼",
                "defaultApiUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "models": [
                    {"id": "qwen-max", "name": "通义千问 Max", "description": "通义千问超大规模语言模型，支持复杂任务", "maxTokens": 32000},
                    {"id": "qwen-plus", "name": "通义千问 Plus", "description": "通义千问大规模语言模型，均衡性能与速度", "maxTokens": 32000},
                    {"id": "qwen-turbo", "name": "通义千问 Turbo", "description": "通义千问轻量模型，快速响应", "maxTokens": 32000},
                    {"id": "qwen-coder-plus", "name": "通义千问 Coder Plus", "description": "代码专用模型", "maxTokens": 32000},
                    {"id": "qwen-2.5-72b-instruct", "name": "Qwen2.5-72B-Instruct", "description": "72B 参数指令模型", "maxTokens": 128000},
                    {"id": "deepseek-v3", "name": "DeepSeek-V3", "description": "DeepSeek V3 模型（通过百炼）", "maxTokens": 64000},
                    {"id": "deepseek-r1", "name": "DeepSeek-R1", "description": "DeepSeek R1 推理模型（通过百炼）", "maxTokens": 64000},
                ],
                "apiKeyPlaceholder": "sk-...",
                "apiKeyHelp": "在阿里云百炼控制台获取 API Key",
            },
            {
                "id": "ollama",
                "name": "Ollama",
                "defaultApiUrl": "http://192.168.50.1:11434/v1",
                "models": [
                    {"id": "ollama-default", "name": "自动获取模型", "description": "点击\"自动获取\"按钮获取模型列表"},
                ],
                "apiKeyPlaceholder": "可选",
                "apiKeyHelp": "Ollama 通常不需要 API Key",
            },
            {
                "id": "custom",
                "name": "自定义 API",
                "defaultApiUrl": "http://192.168.50.1/v1",
                "models": [
                    {"id": "custom-model", "name": "自定义模型", "description": "兼容 OpenAI 格式的自定义 API"},
                ],
                "apiKeyPlaceholder": "...",
                "apiKeyHelp": "支持任何兼容 OpenAI API 格式的服务",
            },
        ]
    }


def init_system_config(db: Session) -> None:
    """初始化系统配置
    
    在应用启动时调用，从数据库加载配置到内存。
    """
    from app.core.config import reload_settings_from_db
    
    config = get_or_create_config(db)
    
    # 解密 API Key
    api_key = decrypt_value(config.llm_api_key) if config.llm_api_key else ""
    
    # 加载到内存
    db_config = {
        "llm_provider": config.llm_provider,
        "llm_model": config.llm_model,
        "llm_api_url": config.llm_api_url,
        "llm_api_key": api_key,
        "llm_max_tokens": config.llm_max_tokens,
        "llm_temperature": config.llm_temperature,
        "proxy_enabled": config.proxy_enabled,
        "http_proxy": config.http_proxy,
        "https_proxy": config.https_proxy,
        "comfyui_host": config.comfyui_host,
        "output_resolution": config.output_resolution,
        "output_frame_rate": config.output_frame_rate,
        "parse_characters_prompt": config.parse_characters_prompt,
    }
    
    reload_settings_from_db(db_config)
    print(f"[Config] 已从数据库加载系统配置")
