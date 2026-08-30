from sqlalchemy.orm import sessionmaker
import pytest

from app.core import database
from app.models.llm_log import LLMLog
from app.services.llm.base import create_llm_log, update_llm_log


def test_llm_log_is_created_pending_then_updated_in_place(db_engine, monkeypatch):
    testing_session = sessionmaker(bind=db_engine)
    monkeypatch.setattr(database, "SessionLocal", testing_session)

    log_id = create_llm_log(
        provider="openai",
        model="gpt-test",
        system_prompt="system",
        user_prompt="user",
        request_info={"payload": {"max_tokens": 93216}},
    )

    with testing_session() as db:
        pending = db.query(LLMLog).filter(LLMLog.id == log_id).one()
        assert pending.status == "pending"
        assert pending.duration is None

    update_llm_log(log_id, status="success", response="done", duration=1.25)

    with testing_session() as db:
        logs = db.query(LLMLog).all()
        assert len(logs) == 1
        assert logs[0].id == log_id
        assert logs[0].status == "success"
        assert logs[0].response == "done"
        assert logs[0].duration == 1.25


@pytest.mark.asyncio
async def test_configured_max_tokens_override_business_default(monkeypatch):
    from app.services.llm_service import LLMService

    captured = {}

    class FakeClient:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": "ok"}

    service = LLMService.__new__(LLMService)
    service.api_url = "https://example.test/v1"
    service.model = "gpt-test"
    service.max_tokens = 93216
    service.temperature = None
    monkeypatch.setattr(service, "_get_client", lambda: FakeClient())

    await service.chat_completion("system", "user", max_tokens=15000)

    assert captured["max_tokens"] == 93216
