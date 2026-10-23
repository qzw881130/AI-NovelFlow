from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.services.prompt_builder import build_character_prompt, get_style
from app.services.prompt_template_service import PromptTemplateService


CHARACTER_TEMPLATE = "##STYLE##, {appearance}, single character, centered, clean background, professional artwork, 8k"


def test_character_system_templates_are_reduced_to_one_and_references_are_migrated(db_session):
    obsolete = PromptTemplate(
        name="写实人设",
        description="旧的写实角色模板",
        template="photorealistic, {appearance}",
        type="character",
        is_system=True,
        is_active=True,
    )
    db_session.add(obsolete)
    db_session.flush()
    novel = Novel(title="测试小说", prompt_template_id=obsolete.id)
    db_session.add(novel)
    db_session.commit()

    PromptTemplateService(db_session).init_system_templates()

    templates = db_session.query(PromptTemplate).filter(
        PromptTemplate.type == "character",
        PromptTemplate.is_system == True,
    ).all()
    db_session.refresh(novel)
    assert len(templates) == 1
    assert templates[0].template.strip() == CHARACTER_TEMPLATE
    assert novel.prompt_template_id == templates[0].id


def test_character_prompt_uses_the_novel_style_template(db_session):
    style_template = PromptTemplate(
        name="小说专属风格",
        description="测试风格",
        template="hand-painted watercolor storybook style",
        type="style",
        is_system=False,
        is_active=True,
    )
    db_session.add(style_template)
    db_session.flush()
    novel = Novel(title="测试小说", style_prompt_template_id=style_template.id)
    db_session.add(novel)
    db_session.commit()

    style, selected_template = get_style(db_session, novel, "character")
    prompt = build_character_prompt(
        "角色",
        "silver hair and a blue coat",
        template=CHARACTER_TEMPLATE,
        style=style,
    )

    assert selected_template.id == style_template.id
    assert "hand-painted watercolor storybook style" in prompt
    assert "silver hair and a blue coat" in prompt
    assert "##STYLE##" not in prompt
