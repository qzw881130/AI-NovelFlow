from hashlib import sha256
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest
from sqlalchemy.orm import sessionmaker

from app.api.llm_logs import LLM_LOG_TASK_CATEGORY_TYPES, LLM_LOG_TASK_LABELS, LLM_TASK_TEMPLATE_TYPES
from app.api.prompt_templates import export_all_prompt_templates
from app.constants.llm import (
    get_scene_setting_prompt, get_prop_appearance_prompt,
    DEFAULT_SCENE_SETTING_FALLBACK, DEFAULT_PROP_APPEARANCE_FALLBACK,
)
from app.constants.prompt_template import PROMPT_TEMPLATE_TYPES
from app.models.prompt_template import PromptTemplate
from app.repositories.prompt_template import PromptTemplateRepository
from app.services.llm_service import LLMService
from app.services.prompt_template_service import PromptTemplateService


CASES = [
    ("scene_setting", "scene_setting.txt", "场景设定描述", "generate_scene_setting", get_scene_setting_prompt,
     "fb0dae6258d72f7b465f7d7a64f95bbbdec8354d663ec9fda85a5c531560b8be"),
    ("prop_appearance", "prop_appearance.txt", "道具外观描述", "generate_prop_appearance", get_prop_appearance_prompt,
     "ec0bd87584ef9355a74c49a51157d7ec2feb3f6faa27ab293d231a7c149a5011"),
]
PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompt_templates"


@pytest.mark.parametrize("kind,filename,name,task,get_prompt,original_hash", CASES)
def test_default_getter_reads_text_file(monkeypatch, kind, filename, name, task, get_prompt, original_hash):
    def read_template(path, encoding):
        assert path == PROMPT_DIR / filename
        assert encoding == "utf-8"
        return "  file-backed template  \n"

    monkeypatch.setattr(Path, "read_text", read_template)
    assert get_prompt() == "file-backed template"


@pytest.mark.parametrize("kind,filename,name,task,get_prompt,original_hash", CASES)
def test_file_extraction_preserves_original_prompt_and_registers_logs(kind, filename, name, task, get_prompt, original_hash):
    text = (PROMPT_DIR / filename).read_text(encoding="utf-8").strip()
    assert get_prompt() == text
    assert sha256(text.encode()).hexdigest() == original_hash
    assert kind in PROMPT_TEMPLATE_TYPES
    assert task in LLM_LOG_TASK_CATEGORY_TYPES["asset_generation"]
    assert LLM_TASK_TEMPLATE_TYPES[task] == kind
    assert LLM_LOG_TASK_LABELS[task].startswith("素材生成-")


@pytest.mark.parametrize("kind,filename,name,task,get_prompt,original_hash", CASES)
def test_seed_sync_is_in_place_and_preserves_custom_templates(db_session, kind, filename, name, task, get_prompt, original_hash):
    system = PromptTemplate(name=name, type=kind, template="stale", is_system=True, is_active=True)
    custom = PromptTemplate(name="custom " + name, type=kind, template="custom body", is_system=False, is_active=True)
    db_session.add_all([system, custom]); db_session.commit()
    identity = system.id
    service = PromptTemplateService(db_session)
    service.init_system_templates()
    service.init_system_templates()
    resolved = service.get_default_system_template(kind)
    assert resolved.id == identity
    assert resolved.template.strip() == get_prompt()
    assert db_session.query(PromptTemplate).filter_by(type=kind, is_system=True).count() == 1
    assert service.to_response(resolved)["nameKey"] == "promptConfig.templateNames." + name
    db_session.refresh(custom)
    assert custom.template == "custom body"


@pytest.mark.asyncio
async def test_package_exports_both_text_templates_under_asset_generation(db_session):
    PromptTemplateService(db_session).init_system_templates()
    response = export_all_prompt_templates(repo=PromptTemplateRepository(db_session))
    parts = [part async for part in response.body_iterator]
    with ZipFile(BytesIO(b"".join(parts))) as archive:
        for kind, filename, name, *_ in CASES:
            path = f"素材生成/{name}提示词/系统-{name}.txt"
            assert archive.read(path).decode().strip() == (PROMPT_DIR / filename).read_text().strip()
            assert not any(p.startswith(f"未分类/{kind}/") for p in archive.namelist())


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,filename,name,task,get_prompt,original_hash", CASES)
@pytest.mark.parametrize("seeded", [False, True])
async def test_runtime_uses_registered_template_or_file_fallback_without_real_llm(
    db_engine, monkeypatch, kind, filename, name, task, get_prompt, original_hash, seeded
):
    from app.core import database
    sessions = sessionmaker(bind=db_engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    expected = get_prompt()
    if seeded:
        expected = "registered system body " + kind
        with sessions() as db:
            db.add(PromptTemplate(name=name, type=kind, template=expected, is_system=True, is_active=True))
            db.commit()
    service = LLMService.__new__(LLMService)
    service.chat_completion = AsyncMock(return_value={"success": True, "content": "generated description"})
    method = service.generate_scene_setting if kind == "scene_setting" else service.generate_prop_appearance
    result = await method("asset name", "asset description", novel_id="novel-id")
    assert result == "generated description"
    sent = service.chat_completion.call_args.kwargs
    assert sent["system_prompt"] == expected
    assert sent["prompt_template_name"] == name
    assert sent["task_type"] == task
    assert sent["novel_id"] == "novel-id"
    assert "asset name" in sent["user_content"] and "asset description" in sent["user_content"]
    assert sent["temperature"] == 0.8 and sent["max_tokens"] == 1000


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,filename,name,task,get_prompt,original_hash", CASES)
async def test_generation_failure_keeps_existing_description_fallback(db_engine, monkeypatch, kind, filename, name, task, get_prompt, original_hash):
    from app.core import database
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=db_engine))
    service = LLMService.__new__(LLMService)
    service.chat_completion = AsyncMock(return_value={"success": False, "error": "test failure"})
    if kind == "scene_setting":
        assert await service.generate_scene_setting("test", "description") == DEFAULT_SCENE_SETTING_FALLBACK.format(scene_name="test")
    else:
        assert await service.generate_prop_appearance("test", "description") == DEFAULT_PROP_APPEARANCE_FALLBACK.format(prop_name="test")
