import json
from datetime import datetime
from io import BytesIO
from zipfile import ZipFile

from app.models.llm_log import LLMLog


def test_export_selected_llm_logs_combines_params_and_response(client, db_session):
    log = LLMLog(
        id="log-export-1",
        created_at=datetime(2026, 9, 23, 0, 25, 27),
        provider="deepseek",
        model="deepseek-chat",
        prompt_template_name="标准道具解析",
        system_prompt="system prompt",
        user_prompt="user prompt",
        request_info=json.dumps({"payload": {"temperature": 0.3}}, ensure_ascii=False),
        response=json.dumps({"props": [{"name": "织机"}]}, ensure_ascii=False),
        status="success",
        task_type="parse_props",
        duration=2.5,
    )
    db_session.add(log)
    db_session.commit()

    response = client.post("/api/llm-logs/export-selected", json={"ids": [log.id]})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == [
            "2026-09-23_08-25-27--03-素材解析-解析道具--标准道具解析.txt"
        ]
        content = archive.read(archive.namelist()[0]).decode("utf-8")

    assert "LLM 参数\n" in content
    assert '"temperature": 0.3' in content
    assert "LLM 响应\n" in content
    assert '"name": "织机"' in content
