from app.models.prompt_template import PromptTemplate
from app.services.prompt_template_service import PromptTemplateService


def test_system_style_templates_are_expanded_and_existing_rows_are_updated(db_session):
    db_session.add(PromptTemplate(
        name="动漫风格",
        description="旧描述",
        template="old anime prompt",
        type="style",
        is_system=True,
        is_active=True,
    ))
    db_session.commit()

    PromptTemplateService(db_session).init_system_templates()

    styles = db_session.query(PromptTemplate).filter(
        PromptTemplate.type == "style",
        PromptTemplate.is_system == True,
    ).all()
    by_name = {style.name: style for style in styles}

    assert len(styles) == 12
    assert "precise, clean linework" in by_name["动漫风格"].template
    assert "Era, technology, clothing" in by_name["写实风格"].template
    assert "3D动画风格" in by_name
    assert "水彩绘本风格" in by_name
    assert "油画风格" in by_name
    assert "美式漫画风格" in by_name
    assert "像素艺术风格" in by_name
    assert "剪纸艺术风格" in by_name
    assert "黏土定格风格" in by_name
    assert "国风工笔风格" in by_name

    story_context = db_session.query(PromptTemplate).filter(
        PromptTemplate.type == "story_world_context_recommender",
        PromptTemplate.is_system == True,
    ).one()
    assert story_context.name == "故事世界上下文推荐"
    assert "{{novel_name}}" in story_context.template
    assert "{{novel_description}}" in story_context.template
    assert '"allow_time_travel": false' in story_context.template

    character_template = db_session.query(PromptTemplate).filter(
        PromptTemplate.type == "character",
        PromptTemplate.is_system == True,
        PromptTemplate.name == "标准角色生成",
    ).one()
    assert character_template.template.strip() == (
        "##STYLE##, {appearance}, single character, centered, clean background, professional artwork, 8k"
    )
