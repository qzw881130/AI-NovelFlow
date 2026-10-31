"""
系统配置 API 路由

支持持久化存储到数据库
"""
from fastapi import APIRouter, HTTPException, Depends, Response
from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime, timezone
from urllib.parse import urlparse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import get_settings, update_settings
from app.core.security import encrypt_value, decrypt_value
from app.models.system_config import SystemConfig as SystemConfigModel
from app.services.generation_preflight import catalog, config_policy, normalize_policy
from app.services.grid_generation_preflight import (
    catalog as grid_catalog,
    config_policy as grid_config_policy,
    normalize_policy as normalize_grid_policy,
)
import json

router = APIRouter()


class LLMConfig(BaseModel):
    """LLM 配置"""
    provider: str
    model: str
    apiKey: Optional[str] = None
    apiUrl: str
    maxTokens: Optional[int] = None  # 最大token数
    temperature: Optional[str] = None  # 温度参数（字符串类型，支持范围0.0-2.0）
    timeout: Optional[int] = None  # 请求超时（秒）


class ProxyConfig(BaseModel):
    """代理配置"""
    enabled: bool
    httpProxy: Optional[str] = None
    httpsProxy: Optional[str] = None
    youtubeEnabled: Optional[bool] = None
    youtubeProxyUrl: Optional[str] = None


CUSTOM_VARIABLE_KEYS = tuple(f"KEY{i}" for i in range(1, 10))


class CustomVariable(BaseModel):
    value: str
    note: str = ""


class SystemConfigUpdate(BaseModel):
    """系统配置更新"""
    llm: Optional[LLMConfig] = None
    proxy: Optional[ProxyConfig] = None
    comfyUIHost: Optional[str] = None
    comfyUITimeout: Optional[int] = None
    systemStatusSource: Optional[str] = None
    outputResolution: Optional[str] = None
    outputFrameRate: Optional[int] = None
    parseCharactersPrompt: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    autoImageReviewEnabled: Optional[bool] = None
    videoPromptLanguage: Optional[Literal["en", "zh"]] = None
    nameplatePreviewMode: Optional[Literal["protagonist_first", "chapter_first"]] = None
    autoApproveFirstAppearanceNames: Optional[bool] = None
    generationQualityPolicy: Optional[dict[str, bool]] = None
    gridGenerationQualityPolicy: Optional[dict[str, bool]] = None
    coverProduction: Optional[str] = None
    customVariables: Optional[dict[str, CustomVariable]] = None


def get_or_create_config(db: Session) -> SystemConfigModel:
    """获取或创建系统配置记录"""
    inspector = inspect(db.bind)
    migrate_youtube_proxy = False
    if "system_configs" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("system_configs")}
        migrate_youtube_proxy = "youtube_proxy_enabled" not in columns or "youtube_proxy_url" not in columns
        if "youtube_proxy_enabled" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN youtube_proxy_enabled BOOLEAN NOT NULL DEFAULT 0"))
            db.commit()
        if "youtube_proxy_url" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN youtube_proxy_url VARCHAR NOT NULL DEFAULT ''"))
            db.commit()
        if "video_prompt_language" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN video_prompt_language VARCHAR NOT NULL DEFAULT 'en'"))
            db.commit()
        if "comfyui_timeout" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN comfyui_timeout INTEGER DEFAULT 3600"))
            db.commit()
        if "auto_image_review_enabled" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN auto_image_review_enabled BOOLEAN NOT NULL DEFAULT 1"))
            db.commit()
        if "auto_image_review_enabled_at" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN auto_image_review_enabled_at DATETIME"))
            db.commit()
        if "show_first_appearance_names" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN show_first_appearance_names BOOLEAN NOT NULL DEFAULT 1"))
            db.commit()
        if "nameplate_preview_mode" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN nameplate_preview_mode VARCHAR NOT NULL DEFAULT 'protagonist_first'"))
            db.commit()
        if "auto_approve_first_appearance_names" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN auto_approve_first_appearance_names BOOLEAN NOT NULL DEFAULT 1"))
            db.commit()
        if "generation_quality_policy" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN generation_quality_policy TEXT NOT NULL DEFAULT '{}'"))
            db.commit()
        if "grid_generation_quality_policy" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN grid_generation_quality_policy TEXT NOT NULL DEFAULT '{}'"))
            db.commit()
        if "cover_production" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN cover_production VARCHAR NOT NULL DEFAULT '旺仔有声小说'"))
            db.commit()
        if "custom_variables" not in columns:
            db.execute(text("ALTER TABLE system_configs ADD COLUMN custom_variables TEXT NOT NULL DEFAULT '{}'"))
            db.commit()

    config = db.query(SystemConfigModel).filter_by(id="default").first()
    if not config:
        config = SystemConfigModel(id="default", auto_image_review_enabled_at=datetime.now(timezone.utc))
        db.add(config)
        db.commit()
        db.refresh(config)
    elif config.auto_image_review_enabled and config.auto_image_review_enabled_at is None:
        config.auto_image_review_enabled_at = datetime.now(timezone.utc)
        db.commit()
    if "system_configs" in inspector.get_table_names() and migrate_youtube_proxy and "youtube_configs" in inspector.get_table_names():
        legacy = db.execute(text("SELECT proxy_enabled, proxy_url FROM youtube_configs WHERE id='default'")).first()
        if legacy:
            config.youtube_proxy_enabled = bool(legacy[0])
            config.youtube_proxy_url = legacy[1] or ""
            db.commit()
    return config


@router.get("/generation-checks")
async def get_generation_checks(db: Session = Depends(get_db)):
    policy = config_policy(get_or_create_config(db))
    return {"success": True, "data": {"checks": catalog(policy), "policy": policy}}


@router.get("/grid-generation-checks")
async def get_grid_generation_checks(db: Session = Depends(get_db)):
    policy = grid_config_policy(get_or_create_config(db))
    return {"success": True, "data": {"checks": grid_catalog(policy), "policy": policy}}


@router.get("/custom-variables")
async def get_custom_variables(response: Response, db: Session = Depends(get_db)):
    """仅在编辑自定义变量时读取值，避免将密钥放入普通配置响应。"""
    response.headers["Cache-Control"] = "no-store"
    config = get_or_create_config(db)
    stored = json.loads(config.custom_variables or "{}")
    return {"success": True, "data": {
        key: {
            "value": decrypt_value(stored.get(key, {}).get("value", "")),
            "note": stored.get(key, {}).get("note", ""),
        }
        for key in CUSTOM_VARIABLE_KEYS
    }}


@router.get("/custom-variables/options")
async def get_custom_variable_options(db: Session = Depends(get_db)):
    """工作流映射只需要已填写的 KEY 与备注，不返回密钥。"""
    config = get_or_create_config(db)
    stored = json.loads(config.custom_variables or "{}")
    return {"success": True, "data": [
        {"key": key, "note": stored[key].get("note", "")}
        for key in CUSTOM_VARIABLE_KEYS
        if stored.get(key, {}).get("value")
    ]}


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
            "llmTimeout": config.llm_timeout,
            "autoImageReviewEnabled": bool(config.auto_image_review_enabled),
            "videoPromptLanguage": config.video_prompt_language,
            "nameplatePreviewMode": config.nameplate_preview_mode or "protagonist_first",
            "autoApproveFirstAppearanceNames": bool(config.auto_approve_first_appearance_names),
            "generationQualityPolicy": config_policy(config),
            "gridGenerationQualityPolicy": grid_config_policy(config),
            "coverProduction": config.cover_production or "旺仔有声小说",
            # 代理配置
            "proxyEnabled": config.proxy_enabled,
            "httpProxy": config.http_proxy,
            "httpsProxy": config.https_proxy,
            "youtubeProxyEnabled": bool(config.youtube_proxy_enabled),
            "youtubeProxyUrl": config.youtube_proxy_url or "",
            # ComfyUI 配置
            "comfyUIHost": config.comfyui_host,
            "comfyUITimeout": config.comfyui_timeout or 3600,
            "systemStatusSource": config.system_status_source or "comfyui",
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
            "llm_timeout": config.llm_timeout,
            "auto_image_review_enabled": bool(config.auto_image_review_enabled),
            "video_prompt_language": config.video_prompt_language,
            "nameplate_preview_mode": config.nameplate_preview_mode or "protagonist_first",
            "auto_approve_first_appearance_names": bool(config.auto_approve_first_appearance_names),
            "generation_quality_policy": config_policy(config),
            "grid_generation_quality_policy": grid_config_policy(config),
            "cover_production": config.cover_production or "旺仔有声小说",
            "proxy_enabled": config.proxy_enabled,
            "http_proxy": config.http_proxy,
            "https_proxy": config.https_proxy,
            "youtube_proxy_enabled": bool(config.youtube_proxy_enabled),
            "youtube_proxy_url": config.youtube_proxy_url or "",
            "comfyui_host": config.comfyui_host,
            "comfyui_timeout": config.comfyui_timeout or 3600,
            "system_status_source": config.system_status_source or "comfyui",
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
            db_config.llm_timeout = config.llm.timeout
            
            updates["llm_provider"] = config.llm.provider
            updates["llm_model"] = config.llm.model
            updates["llm_api_url"] = config.llm.apiUrl
            updates["llm_max_tokens"] = config.llm.maxTokens
            updates["llm_temperature"] = config.llm.temperature
            updates["llm_timeout"] = config.llm.timeout
            
            # 前端不会回显已保存的 API Key；空值表示不修改现有密钥。
            if config.llm.apiKey is not None and config.llm.apiKey.strip():
                api_key = config.llm.apiKey.strip()
                encrypted_key = encrypt_value(api_key)
                db_config.llm_api_key = encrypted_key
                updates["llm_api_key"] = api_key

        if config.autoImageReviewEnabled is not None:
            if config.autoImageReviewEnabled and (not db_config.auto_image_review_enabled or db_config.auto_image_review_enabled_at is None):
                db_config.auto_image_review_enabled_at = datetime.now(timezone.utc)
            db_config.auto_image_review_enabled = config.autoImageReviewEnabled
        if config.videoPromptLanguage is not None:
            db_config.video_prompt_language = config.videoPromptLanguage
            updates["video_prompt_language"] = config.videoPromptLanguage
        if config.nameplatePreviewMode is not None:
            db_config.nameplate_preview_mode = config.nameplatePreviewMode
        if config.autoApproveFirstAppearanceNames is not None:
            db_config.auto_approve_first_appearance_names = config.autoApproveFirstAppearanceNames
        if config.generationQualityPolicy is not None:
            try:
                db_config.generation_quality_policy = json.dumps(normalize_policy(config.generationQualityPolicy))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if config.gridGenerationQualityPolicy is not None:
            try:
                db_config.grid_generation_quality_policy = json.dumps(normalize_grid_policy(config.gridGenerationQualityPolicy))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if config.coverProduction is not None:
            production = config.coverProduction.strip()
            if not production or len(production) > 80:
                raise HTTPException(status_code=400, detail="制作名称长度必须为 1–80 个字符")
            db_config.cover_production = production
        if config.customVariables is not None:
            if set(config.customVariables) != set(CUSTOM_VARIABLE_KEYS):
                raise HTTPException(status_code=400, detail="自定义变量必须包含固定的 KEY1–KEY9")
            for key, item in config.customVariables.items():
                if len(item.value) > 256:
                    raise HTTPException(status_code=400, detail=f"{key} 的值不能超过 256 个字符")
            db_config.custom_variables = json.dumps({
                key: {"value": encrypt_value(config.customVariables[key].value),
                      "note": config.customVariables[key].note}
                for key in CUSTOM_VARIABLE_KEYS
            }, ensure_ascii=False)
        
        if config.proxy:
            db_config.proxy_enabled = config.proxy.enabled
            db_config.http_proxy = config.proxy.httpProxy
            db_config.https_proxy = config.proxy.httpsProxy
            
            updates["proxy_enabled"] = config.proxy.enabled
            updates["http_proxy"] = config.proxy.httpProxy
            updates["https_proxy"] = config.proxy.httpsProxy
            if config.proxy.youtubeProxyUrl is not None:
                proxy_url = config.proxy.youtubeProxyUrl.strip()
                if proxy_url:
                    try:
                        parsed = urlparse(proxy_url)
                        valid = parsed.scheme == "http" and bool(parsed.hostname) and bool(parsed.port)
                    except ValueError:
                        valid = False
                    if not valid or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                        raise HTTPException(status_code=400, detail="YouTube 代理地址必须是包含主机和端口的 http:// 地址")
                db_config.youtube_proxy_url = proxy_url
            if config.proxy.youtubeEnabled is not None:
                db_config.youtube_proxy_enabled = config.proxy.youtubeEnabled
            if db_config.youtube_proxy_enabled and not db_config.youtube_proxy_url:
                raise HTTPException(status_code=400, detail="启用 YouTube 代理前请填写代理地址")
        
        if config.comfyUIHost:
            db_config.comfyui_host = config.comfyUIHost
            updates["comfyui_host"] = config.comfyUIHost

        if config.comfyUITimeout is not None:
            if config.comfyUITimeout not in {900, 1200, 1800, 2700, 3600, 7200}:
                raise HTTPException(status_code=400, detail="ComfyUI 超时时间必须是 15、20、30、45、60 或 120 分钟")
            db_config.comfyui_timeout = config.comfyUITimeout
            updates["comfyui_timeout"] = config.comfyUITimeout

        if config.systemStatusSource is not None:
            db_config.system_status_source = config.systemStatusSource
            updates["system_status_source"] = config.systemStatusSource
        
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
    except HTTPException:
        db.rollback()
        raise
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
                    {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash", "description": "新一代快速模型", "maxTokens": 393216},
                    {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "description": "新一代高性能模型", "maxTokens": 393216},
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
                    {"id": "gpt-5.5", "name": "GPT-5.5", "description": "旗舰推理与编码模型", "maxTokens": 1000000},
                    {"id": "gpt-5.4", "name": "GPT-5.4", "description": "高性价比专业模型", "maxTokens": 1000000},
                    {"id": "gpt-5.4-mini", "name": "GPT-5.4 Mini", "description": "轻量高性能模型", "maxTokens": 400000},
                    {"id": "gpt-5.4-nano", "name": "GPT-5.4 Nano", "description": "超低延迟模型", "maxTokens": 400000},
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
                    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "description": "稳定专业版", "maxTokens": 1000000},
                    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "description": "稳定快速版", "maxTokens": 1000000},
                    {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash Lite", "description": "稳定轻量版", "maxTokens": 1000000},
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
                    {"id": "qwen3.6-max-preview", "name": "通义千问 3.6 Max Preview", "description": "最新旗舰预览模型"},
                    {"id": "qwen3.6-plus", "name": "通义千问 3.6 Plus", "description": "新一代均衡模型"},
                    {"id": "qwen3.6-flash", "name": "通义千问 3.6 Flash", "description": "新一代高速模型"},
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
                "defaultApiUrl": "http://127.0.0.1:11434/v1",
                "models": [
                    {"id": "ollama-default", "name": "自动获取模型", "description": "点击\"自动获取\"按钮获取模型列表"},
                ],
                "apiKeyPlaceholder": "可选",
                "apiKeyHelp": "Ollama 通常不需要 API Key",
            },
            {
                "id": "custom",
                "name": "自定义 API",
                "defaultApiUrl": "http://127.0.0.1/v1",
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
        "llm_timeout": config.llm_timeout,
        "video_prompt_language": config.video_prompt_language,
        "proxy_enabled": config.proxy_enabled,
        "http_proxy": config.http_proxy,
        "https_proxy": config.https_proxy,
        "comfyui_host": config.comfyui_host,
        "comfyui_timeout": config.comfyui_timeout or 3600,
        "system_status_source": config.system_status_source or "comfyui",
        "output_resolution": config.output_resolution,
        "output_frame_rate": config.output_frame_rate,
        "parse_characters_prompt": config.parse_characters_prompt,
    }
    
    reload_settings_from_db(db_config)
    print(f"[Config] 已从数据库加载系统配置")
