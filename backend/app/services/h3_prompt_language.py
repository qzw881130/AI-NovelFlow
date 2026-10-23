"""Freeze descriptive language separately from Canonical dialogue language."""
from typing import Literal
import re

PromptLanguage = Literal["en", "zh"]
UNSET_LANGUAGE = object()
LANGUAGE_CONTRACT = "H3_PROMPT_LANGUAGE_V1"


def validate_language(value):
    if value not in ("en", "zh"):
        raise ValueError("H3_PROMPT_LANGUAGE_INVALID: expected en or zh")
    return value


def new_task_language(db, requested=None):
    """Read the saved global default once at creation, including batch creation."""
    from app.models.system_config import SystemConfig
    if requested is not None:
        return validate_language(requested)
    row = db.query(SystemConfig.video_prompt_language).filter_by(id="default").first()
    return validate_language(row[0] if row else "en")


def task_language(metadata):
    """Missing historical intent retains the original mixed-language contract."""
    value = (metadata or {}).get("video_prompt_language")
    return None if value is None else validate_language(value)


def description_sources(subject_names, appearances, picture_mapping, stable_marks, structured_features=None):
    sources = {}
    structured_features = structured_features or {}
    for subject, name in subject_names.items():
        marks = (structured_features.get(name) if name in structured_features
                 else stable_marks(appearances.get(name)))
        if marks:
            sources["identity:" + subject] = marks
    for item in picture_mapping:
        if item.get("kind") in {"SCENE", "PROP"} and item.get("source_name"):
            sources[f"{item['kind']}:{item['source_name']}"] = item['source_name']
    return sources


def validate_localized_descriptions(value, sources):
    if not isinstance(value, dict) or set(value) != set(sources):
        raise ValueError("H3_LOCALIZED_DESCRIPTION_KEYS_INVALID")
    for text in value.values():
        if (not isinstance(text, str) or not text.strip() or '\n' in text
                or re.search(r"<[^>]*>|\[\[|\b(?:S|D)\d+\b|(?i:subject_definitions:)", text)):
            raise ValueError("H3_LOCALIZED_DESCRIPTION_INVALID")
    return value


def validate_english_prose(text, canonical_names, *, blocking=True):
    """Protect the requested English boundary, allowing exact Canonical names.

    Call before speech injection (never scan or translate Canonical dialogue).
    This script check does not certify translation meaning or audiovisual quality.
    """
    for name in sorted((name for name in canonical_names if isinstance(name, str) and name),
                       key=len, reverse=True):
        text = text.replace(name, "")
    mismatch = re.search(r"[\u3400-\u9fff]+", text)
    if mismatch:
        finding = ("H3_PROMPT_LANGUAGE_MISMATCH: Chinese description in English output "
                   f"({mismatch.group(0)})")
        if blocking:
            raise ValueError(finding)
        return finding
    return None
