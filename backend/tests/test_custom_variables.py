"""Fixed custom settings can be edited without changing their reference keys."""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.api.config import get_or_create_config
from app.core.security import decrypt_value
from app.models.system_config import SystemConfig
from app.services.comfyui.api_key_variables import bind_image_api_key
from app.services.comfyui.service import ComfyUIService


KEYS = [f"KEY{i}" for i in range(1, 10)]


def variables(value="", note=""):
    return {key: {"value": value, "note": note} for key in KEYS}


def test_custom_variables_default_persist_and_clear(client, db_session):
    endpoint = "/api/config/custom-variables"
    assert client.get(endpoint).json()["data"] == variables()

    payload = variables()
    payload["KEY1"] = {"value": "secret-api-key", "note": "zhenzhen api key"}
    payload["KEY2"] = {"value": "中" * 256, "note": ""}
    response = client.post("/api/config/", json={"customVariables": payload})
    assert response.status_code == 200, response.text
    assert client.get(endpoint).json()["data"] == payload
    assert client.get("/api/config/custom-variables/options").json()["data"] == [
        {"key": "KEY1", "note": "zhenzhen api key"}, {"key": "KEY2", "note": ""}
    ]
    assert "customVariables" not in client.get("/api/config/").json()["data"]

    stored = json.loads(db_session.get(SystemConfig, "default").custom_variables)
    assert "secret-api-key" not in db_session.get(SystemConfig, "default").custom_variables
    assert decrypt_value(stored["KEY1"]["value"]) == "secret-api-key"

    payload["KEY1"] = {"value": "", "note": ""}
    assert client.post("/api/config/", json={"customVariables": payload}).status_code == 200
    assert client.get(endpoint).json()["data"] == payload
    assert client.get("/api/config/custom-variables/options").json()["data"] == [
        {"key": "KEY2", "note": ""}
    ]


def test_image_api_key_is_bound_only_to_submission_copy(client, db_session):
    payload = variables()
    payload["KEY1"] = {"value": "secret-api-key", "note": "api"}
    payload["KEY2"] = {"value": "https://example.invalid/v1", "note": "base url"}
    assert client.post("/api/config/", json={"customVariables": payload}).status_code == 200
    for class_type, field in (("CR Text", "text"), ("CR Prompt Text", "prompt"), ("String", "value"), ("easy string", "value")):
        graph = {"7": {"class_type": class_type, "inputs": {field: "old"}}}
        mapping = {"api_key_node_id": "7", "api_key_variable": "KEY1"}
        submitted = bind_image_api_key(graph, mapping, db_session)
        assert submitted["7"]["inputs"][field] == "secret-api-key"
        assert graph["7"]["inputs"][field] == "old"
        base_mapping = {"api_base_url_node_id": "7", "api_base_url_key_variable": "KEY2"}
        submitted_base = bind_image_api_key(graph, base_mapping, db_session)
        assert submitted_base["7"]["inputs"][field] == "https://example.invalid/v1"
        assert graph["7"]["inputs"][field] == "old"

    graph = {
        "7": {"class_type": "easy string", "inputs": {"value": "original-key"}},
        "8": {"class_type": "CR Text", "inputs": {"text": "original-url"}},
    }
    both = {"api_key_node_id": "7", "api_key_variable": "KEY1",
            "api_base_url_node_id": "8", "api_base_url_key_variable": "KEY2"}
    submitted = bind_image_api_key(graph, both, db_session)
    assert submitted["7"]["inputs"]["value"] == "secret-api-key"
    assert submitted["8"]["inputs"]["text"] == "https://example.invalid/v1"
    assert graph["7"]["inputs"]["value"] == "original-key"
    assert graph["8"]["inputs"]["text"] == "original-url"

    for bad_mapping in (
        {"api_key_node_id": "7", "api_key_variable": "KEY3"},
        {"api_key_node_id": "7", "api_key_variable": "KEY10"},
        {"api_key_node_id": "7", "api_key_variable": "KEY1", "prompt_node_id": "7"},
        {"api_base_url_node_id": "8", "api_base_url_key_variable": "KEY3"},
        {"api_base_url_node_id": "8", "api_base_url_key_variable": "KEY2", "prompt_node_id": "8"},
        {"api_key_node_id": "7", "api_key_variable": "KEY1",
         "api_base_url_node_id": "7", "api_base_url_key_variable": "KEY2"},
        {"api_base_url_node_id": "8"},
    ):
        try:
            bind_image_api_key(graph, bad_mapping, db_session)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid apiKey mapping must fail")


@pytest.mark.asyncio
async def test_image_service_submits_resolved_key_without_saving_it(client, db_session, db_engine, monkeypatch):
    payload = variables()
    payload["KEY1"] = {"value": "secret-api-key", "note": "api"}
    payload["KEY2"] = {"value": "https://example.invalid/v1", "note": "base url"}
    assert client.post("/api/config/", json={"customVariables": payload}).status_code == 200
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=db_engine))
    service = ComfyUIService(runtime_mode="standalone")
    submitted = []

    async def queue_prompt(graph):
        submitted.append(graph)
        return {"success": True, "prompt_id": "prompt-1"}

    async def wait_for_result(*_args, **_kwargs):
        return {"success": True, "image_url": "test.png"}

    monkeypatch.setattr(service.client, "queue_prompt", queue_prompt)
    monkeypatch.setattr(service.client, "wait_for_result", wait_for_result)
    graph = {
        "7": {"class_type": "String", "inputs": {"value": "original"}},
        "8": {"class_type": "easy string", "inputs": {"value": "original-url"}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["7", 0]}},
    }
    result = await service.generate_shot_image_with_workflow(
        prompt="test", workflow_json="{}", workflow=graph,
        node_mapping={"api_key_node_id": "7", "api_key_variable": "KEY1",
                      "api_base_url_node_id": "8", "api_base_url_key_variable": "KEY2",
                      "save_image_node_id": "9"},
    )
    assert result["success"] is True
    assert submitted[0]["7"]["inputs"]["value"] == "secret-api-key"
    assert submitted[0]["8"]["inputs"]["value"] == "https://example.invalid/v1"
    assert result["submitted_workflow"]["7"]["inputs"]["value"] == "original"
    assert result["submitted_workflow"]["8"]["inputs"]["value"] == "original-url"


def test_custom_variables_reject_changed_keys_and_oversize_values(client):
    for invalid in (
        {key: item for key, item in variables().items() if key != "KEY9"},
        {**variables(), "KEY10": {"value": "x", "note": ""}},
        {**variables(), "KEY1": {"value": "x" * 257, "note": ""}},
    ):
        response = client.post("/api/config/", json={"customVariables": invalid})
        assert response.status_code == 400, response.text
    assert client.get("/api/config/custom-variables").json()["data"] == variables()


def test_existing_config_table_gains_custom_variables_column(db_session):
    db_session.execute(text("ALTER TABLE system_configs DROP COLUMN custom_variables"))
    db_session.commit()
    config = get_or_create_config(db_session)
    assert config.custom_variables == "{}"
    assert "custom_variables" in {
        row[1] for row in db_session.execute(text("PRAGMA table_info(system_configs)"))
    }
