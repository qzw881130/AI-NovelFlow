import json

from app.api.deps import get_llm_service
from app.main import app


def test_create_and_update_novel_story_context_prompt(client):
    created_response = client.post("/api/novels/", json={
        "title": "故事上下文测试",
        "storyWorldContextPromptTemplateId": "story-template-1",
    })
    assert created_response.status_code == 200
    created = created_response.json()["data"]
    assert created["storyWorldContextPromptTemplateId"] == "story-template-1"

    updated_response = client.put(f"/api/novels/{created['id']}/", json={
        "storyWorldContextPromptTemplateId": "story-template-2",
    })
    assert updated_response.status_code == 200
    assert updated_response.json()["data"]["storyWorldContextPromptTemplateId"] == "story-template-2"

    detail_response = client.get(f"/api/novels/{created['id']}/")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["storyWorldContextPromptTemplateId"] == "story-template-2"


def test_recommend_and_lock_story_world_context_with_title_fallback(client):
    captured = {}
    recommendation = {
        "world_type": "童话",
        "era": "时代不明确",
        "historical_period": "未明确的前现代时期",
        "geographic_scope": "欧洲文化语境的虚构王国",
        "cultural_system": "欧洲童话式宫廷文化",
        "technology_level": "前工业时代",
        "allow_time_travel": False,
        "material_culture": {
            "clothing": "欧洲童话式前现代服饰体系",
            "architecture": "欧洲童话式前现代建筑体系",
            "objects": "欧洲前现代物质文化体系",
        },
        "visual_exclusions": ["现代数字设备", "东亚古代官服与建筑"],
    }

    class FakeLLMService:
        async def chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": json.dumps(recommendation, ensure_ascii=False)}

    app.dependency_overrides[get_llm_service] = lambda: FakeLLMService()
    created = client.post("/api/novels/", json={"title": "皇帝的新装", "description": ""}).json()["data"]

    recommended_response = client.post(f"/api/novels/{created['id']}/story-world-context/recommend")
    assert recommended_response.status_code == 200
    assert recommended_response.json()["data"]["context"] == recommendation
    assert json.loads(captured["user_content"]) == {
        "novel_name": "皇帝的新装",
        "novel_description": "皇帝的新装",
    }
    assert "{{novel_name}}" not in captured["system_prompt"]
    assert captured["task_type"] == "story_world_context_recommender"

    before_save = client.get(f"/api/novels/{created['id']}/story-world-context").json()["data"]
    assert before_save == {"context": None, "locked": False, "updatedAt": None}

    saved_response = client.put(
        f"/api/novels/{created['id']}/story-world-context",
        json={"context": recommendation},
    )
    assert saved_response.status_code == 200
    saved = saved_response.json()["data"]
    assert saved["context"] == recommendation
    assert saved["locked"] is True
    assert saved["updatedAt"] is not None
