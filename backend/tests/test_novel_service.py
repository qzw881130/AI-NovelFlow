"""Legacy API parameters must not revive the old overwrite/delete writer."""
import asyncio
from unittest.mock import patch

from app.models.novel import Character
from app.models.asset_resolution import CharacterIdentity
from app.services.novel_service import NovelService
from test_chapter_asset_parse import db_session, chapter, FakeLLM


def test_non_incremental_parse_only_persists_candidates(db_session, chapter):
    actor = db_session.query(Character).filter_by(name="刘备").one()
    db_session.add(CharacterIdentity(character_id=actor.id, novel_id=chapter.novel_id,
                                     entity_type="INDIVIDUAL", group_size_hint=1, provenance={"origin": "test"}))
    db_session.commit()
    service = NovelService(db_session)
    before = [(row.id, row.name, row.description, row.appearance, row.image_url)
              for row in db_session.query(Character).order_by(Character.id)]
    with patch.object(service, "get_llm_service", return_value=FakeLLM(db_session)):
        result = asyncio.run(service.parse_characters(chapter.novel_id, [chapter], is_incremental=False))
    assert result["success"] is True
    assert result["statistics"]["candidates"] == 1
    assert before == [(row.id, row.name, row.description, row.appearance, row.image_url)
                      for row in db_session.query(Character).order_by(Character.id)]
