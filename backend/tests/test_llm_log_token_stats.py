from datetime import datetime

from app.models.llm_log import LLMLog


def test_llm_log_token_stats_groups_input_and_output_tokens(client, db_session):
    now = datetime.utcnow()
    db_session.add_all([
        LLMLog(
            id="token-stats-1",
            created_at=now,
            provider="openai",
            model="gpt-test",
            user_prompt="first",
            status="success",
            task_type="parse_characters",
            usage_metrics={"input_tokens": 120, "output_tokens": 30},
        ),
        LLMLog(
            id="token-stats-2",
            created_at=now,
            provider="openai",
            model="gpt-test",
            user_prompt="second",
            status="success",
            task_type="parse_characters",
            usage_metrics={"input_tokens": 80, "output_tokens": 20},
        ),
        LLMLog(
            id="token-stats-filtered",
            created_at=now,
            provider="gemini",
            model="gemini-test",
            user_prompt="filtered",
            status="success",
            task_type="parse_scenes",
            usage_metrics={"input_tokens": 999, "output_tokens": 999},
        ),
    ])
    db_session.commit()

    response = client.get(
        "/api/llm-logs/token-stats",
        params={"group_by": "hour", "range_value": 1, "provider": "openai"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_input_tokens"] == 200
    assert data["total_output_tokens"] == 50
    populated = [item for item in data["items"] if item["input_tokens"] or item["output_tokens"]]
    assert len(populated) == 1
    assert populated[0]["input_tokens"] == 200
    assert populated[0]["output_tokens"] == 50
