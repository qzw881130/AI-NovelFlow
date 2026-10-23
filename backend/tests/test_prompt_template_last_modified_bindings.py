from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import event

from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.services import prompt_template_service as service_module
from app.services.prompt_template_service import PromptTemplateService, SYSTEM_PROMPT_TEMPLATES


def test_system_modified_time_uses_registered_file_mtime(db_session):
    registered = next(item for item in SYSTEM_PROMPT_TEMPLATES if item["type"] == "keyframe_planner" and item.get("source_file"))
    template = PromptTemplate(name=registered["name"], type=registered["type"], template=registered["template"], is_system=True)
    path = Path(service_module.TEMPLATES_DIR) / registered["source_file"]
    expected = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    template.updated_at = datetime(2000, 1, 1)
    assert PromptTemplateService.to_response(template)["lastModifiedAt"] == expected


def test_missing_or_unmapped_system_file_returns_unknown(db_session, monkeypatch):
    registered = next(item for item in SYSTEM_PROMPT_TEMPLATES if item["type"] == "keyframe_planner" and item.get("source_file"))
    template = PromptTemplate(name=registered["name"], type=registered["type"], template=registered["template"], is_system=True)

    def missing(_path):
        raise FileNotFoundError("gone")

    monkeypatch.setattr(service_module.os.path, "getmtime", missing)
    assert PromptTemplateService.to_response(template)["lastModifiedAt"] is None
    template.name = "historical/unmapped system prompt"
    assert PromptTemplateService.to_response(template)["lastModifiedAt"] is None


def test_custom_template_created_copied_and_edited_times_are_database_times(db_session):
    service = PromptTemplateService(db_session)
    custom = service.create_template("My planner", "", "first", "keyframe_planner")
    created = service.to_response(custom)["lastModifiedAt"]
    assert created == custom.updated_at.replace(tzinfo=timezone.utc).isoformat()
    custom = service.update_template(custom.id, template="second")
    assert custom.updated_at.replace(tzinfo=timezone.utc).isoformat() == service.to_response(custom)["lastModifiedAt"]
    assert service.to_response(custom)["lastModifiedAt"] >= created

    system = PromptTemplate(name="system", type="keyframe_planner", template="source", is_system=True)
    db_session.add(system)
    db_session.commit()
    copied = service.copy_template(system.id)
    assert service.to_response(copied)["lastModifiedAt"] is not None


def test_bound_novels_query_reads_only_matching_saved_field_once(client, db_session):
    service = PromptTemplateService(db_session)
    template = service.create_template("My planner", "", "text", "keyframe_planner")
    bound = Novel(title="Bound", author="Writer", keyframe_planner_prompt_template_id=template.id,
                  style_prompt_template_id=template.id)
    wrong_field = Novel(title="Wrong field", style_prompt_template_id=template.id)
    use_default = Novel(title="Use default", keyframe_planner_prompt_template_id=None)
    db_session.add_all([bound, wrong_field, use_default])
    db_session.commit()
    before = [(novel.id, novel.keyframe_planner_prompt_template_id, novel.style_prompt_template_id)
              for novel in db_session.query(Novel).order_by(Novel.id)]

    response = client.get(f"/api/prompt-templates/{template.id}/bound-novels")
    assert response.status_code == 200
    assert response.json()["data"] == [{"novel_id": bound.id, "novel_title": "Bound",
                                        "author": "Writer", "binding_type": "explicit"}]
    after = [(novel.id, novel.keyframe_planner_prompt_template_id, novel.style_prompt_template_id)
             for novel in db_session.query(Novel).order_by(Novel.id)]
    assert after == before
    assert client.get("/api/prompt-templates/missing/bound-novels").status_code == 404


def test_template_list_does_not_query_novels(client, db_engine):
    def reject_novel_query(_conn, _cursor, statement, _parameters, _context, _many):
        assert "FROM novels" not in statement

    event.listen(db_engine, "before_cursor_execute", reject_novel_query)
    try:
        response = client.get("/api/prompt-templates/?type=style")
        assert response.status_code == 200
        assert response.json()["data"]
    finally:
        event.remove(db_engine, "before_cursor_execute", reject_novel_query)


def test_auto_stored_character_and_style_defaults_are_excluded(client, db_session):
    service = PromptTemplateService(db_session)
    character = service.get_default_system_template("character")
    style = service.get_default_system_template("style")
    assert character and style
    novel = Novel(title="Implicit legacy defaults", prompt_template_id=character.id,
                  style_prompt_template_id=style.id)
    db_session.add(novel)
    db_session.commit()
    for template in [character, style]:
        result = client.get(f"/api/prompt-templates/{template.id}/bound-novels")
        assert result.status_code == 200
        assert result.json()["data"] == []

    other_style = db_session.query(PromptTemplate).filter_by(type="style", is_system=True).filter(PromptTemplate.id != style.id).first()
    assert other_style
    novel.style_prompt_template_id = other_style.id
    db_session.commit()
    result = client.get(f"/api/prompt-templates/{other_style.id}/bound-novels")
    assert result.json()["data"] == []

    custom_style = service.create_template("User style", "", "style", "style")
    novel.style_prompt_template_id = custom_style.id
    db_session.commit()
    result = client.get(f"/api/prompt-templates/{custom_style.id}/bound-novels")
    assert [item["novel_id"] for item in result.json()["data"]] == [novel.id]
