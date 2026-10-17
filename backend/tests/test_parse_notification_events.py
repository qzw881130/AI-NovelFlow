"""Parsing events follow final results from every novel/chapter entry point."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import parse_events
from app.services.notification_registry import EVENT_REGISTRY, list_events


@pytest.mark.parametrize("flow", ["story_world_context.parse", "character.parse", "scene.parse", "prop.parse"])
def test_parse_event_codes_are_enabled_and_configurable(flow):
    codes = {entry["event_code"]: entry for entry in list_events({})}
    for suffix in ("completed", "failed"):
        code = f"{flow}.{suffix}"
        assert code in EVENT_REGISTRY and codes[code]["enabled"] is True
        assert next(entry for entry in list_events({code: False}) if entry["event_code"] == code)["enabled"] is False


@pytest.mark.parametrize("flow", ["character.parse", "scene.parse", "prop.parse"])
def test_observed_parse_reports_success_empty_result_and_failure(flow, monkeypatch):
    calls = []
    monkeypatch.setattr(parse_events, "publish", lambda code, payload: calls.append((code, payload)))
    chapter = SimpleNamespace(id="chapter-1", number=3)

    class Service:
        @parse_events.observed_parse(flow)
        async def parse(self, novel_id, chapters):
            return self.result

    service = Service()
    for result in ({"success": True, "statistics": {"created": 2, "updated": 1}},
                   {"success": True, "data": []}, {"success": False, "message": "secret error"}):
        service.result = result
        assert asyncio.run(service.parse("novel-1", [chapter])) is result
    assert [code for code, _ in calls] == [f"{flow}.completed", f"{flow}.completed", f"{flow}.failed"]
    assert calls[0][1]["novel_id"] == "novel-1"
    assert calls[0][1]["chapter_id"] == "chapter-1"
    assert calls[0][1]["details"] == {"chapter_number": 3, "created_count": 2, "updated_count": 1}
    assert "secret error" not in str(calls)


def test_observed_parse_reports_exception_without_changing_it(monkeypatch):
    calls = []
    monkeypatch.setattr(parse_events, "publish", lambda code, payload: calls.append(code))

    class Service:
        @parse_events.observed_parse("scene.parse")
        async def parse(self, novel_id, chapter):
            raise RuntimeError("database failure")

    with pytest.raises(RuntimeError, match="database failure"):
        asyncio.run(Service().parse("novel-1", SimpleNamespace(id="chapter-1", number=1)))
    assert calls == ["scene.parse.failed"]


def test_notification_failure_does_not_change_parse_result(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("event database unavailable")
    monkeypatch.setattr(parse_events, "publish", unavailable)

    class Service:
        @parse_events.observed_parse("character.parse")
        async def parse(self, novel_id, chapters):
            return {"success": True, "data": ["saved character"]}

    assert asyncio.run(Service().parse("novel-1", []))["data"] == ["saved character"]


def test_legacy_direct_prop_parse_route_records_one_result_event(db_session, monkeypatch):
    from app.api.props import parse_props

    calls = []
    monkeypatch.setattr(parse_events, "publish", lambda code, payload: calls.append(code))
    novel_repo = SimpleNamespace(get_by_id=lambda _id: SimpleNamespace(prop_parse_prompt_template_id=None))
    llm = SimpleNamespace(chat_completion=AsyncMock(return_value={"success": True, "content": '{"props": []}'}))
    args = dict(novel_id="novel-1", text="故事", start_chapter=None, end_chapter=None,
                source_range=None, db=db_session, llm_service=llm,
                prop_repo=SimpleNamespace(), novel_repo=novel_repo)
    assert asyncio.run(parse_props(**args))["success"] is True
    llm.chat_completion.return_value = {"success": False, "error": "offline"}
    assert asyncio.run(parse_props(**args))["success"] is False
    assert calls == ["prop.parse.completed", "prop.parse.failed"]
