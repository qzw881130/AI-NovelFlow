"""Resolve one registered prompt version selected by a novel."""

from app.constants.prompt_template import NOVEL_PROMPT_TEMPLATE_FIELDS
from app.repositories.prompt_template import PromptTemplateRepository


def resolve_novel_prompt_template(db, novel, template_type):
    field = NOVEL_PROMPT_TEMPLATE_FIELDS[template_type]
    repo = PromptTemplateRepository(db)
    selected_id = getattr(novel, field, None) if novel is not None else None
    selected = repo.get_by_id(selected_id) if selected_id else None
    if selected and selected.type == template_type and selected.is_active:
        return selected
    return repo.get_default_system_template(template_type)
