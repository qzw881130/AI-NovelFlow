"""
NovelService 单元测试
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.novel import Chapter, Character, Novel
from app.repositories.character_repository import CharacterRepository
from app.services.novel_service import NovelService


def test_full_non_incremental_parse_deletes_missing_old_characters(db_session):
    novel = Novel(title="测试小说")
    db_session.add(novel)
    db_session.commit()
    db_session.refresh(novel)

    chapter = Chapter(novel_id=novel.id, number=1, title="第一章", content="小红帽去看母亲。")
    old_character = Character(novel_id=novel.id, name="旧角色", description="旧数据")
    narrator = Character(novel_id=novel.id, name="旁白", is_narrator=True)
    db_session.add_all([chapter, old_character, narrator])
    db_session.commit()

    llm_service = MagicMock()
    llm_service.parse_novel_text = AsyncMock(return_value={
        "characters": [
            {
                "name": "母亲",
                "description": "小红帽的妈妈",
                "appearance": "温柔的年轻母亲",
                "voice_prompt": "温柔女声",
            }
        ]
    })

    service = NovelService(db_session)
    with patch.object(service, "get_llm_service", return_value=llm_service):
        result = asyncio.run(
            service.parse_characters(
                novel_id=novel.id,
                chapters=[chapter],
                is_incremental=False,
                character_repo=CharacterRepository(db_session),
            )
        )

    names = {character.name for character in CharacterRepository(db_session).list_by_novel(novel.id)}

    assert result["success"] is True
    assert result["statistics"]["created"] == 1
    assert result["statistics"]["deleted"] == 1
    assert "母亲" in names
    assert "旁白" in names
    assert "旧角色" not in names
