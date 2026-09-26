import json
from types import SimpleNamespace

import pytest

from app.services.shot_keyframe_service import ShotKeyframeService
from app.services.prompt_template_service import PromptTemplateService


@pytest.mark.asyncio
async def test_reference_selector_filters_unknown_refs_and_limits_temporal_anchors(db_session):
    PromptTemplateService(db_session).init_system_templates()
    service = ShotKeyframeService()
    service.llm_service = SimpleNamespace(chat_completion=None)

    async def select(**_kwargs):
        return {
            "success": True,
            "content": json.dumps({
                "selected_references": [
                    {
                        "type": "TEMPORAL_ANCHOR",
                        "ref_ids": ["KF1", "KF2", "KF3", "UNKNOWN"],
                        "purpose": "preserve distinct historical states",
                    },
                    {
                        "type": "CHARACTER_IDENTITY",
                        "ref_ids": ["CHAR:hero", "MISSING"],
                        "purpose": "preserve identity",
                    },
                ]
            }),
        }

    service.llm_service.chat_completion = select
    shot = SimpleNamespace(
        id="shot-1",
        chapter_id="chapter-1",
        duration=20,
        continuity_mode="NORMAL",
        description="shot",
        characters='["hero"]',
        scene="",
        props="[]",
    )
    candidates = [
        {"ref_id": "KF1", "type": "TEMPORAL_ANCHOR"},
        {"ref_id": "KF2", "type": "TEMPORAL_ANCHOR"},
        {"ref_id": "KF3", "type": "TEMPORAL_ANCHOR"},
        {"ref_id": "CHAR:hero", "type": "CHARACTER_IDENTITY"},
    ]

    _payload, _raw, parsed = await service._select_references(
        db_session,
        SimpleNamespace(id="novel-1"),
        shot,
        {"plan_keyframe_index": 4, "time_seconds": 20, "description": "current"},
        candidates,
    )

    assert parsed["selected_references"][0]["ref_ids"] == ["KF1", "KF2"]
    assert parsed["selected_references"][1]["ref_ids"] == ["CHAR:hero"]
