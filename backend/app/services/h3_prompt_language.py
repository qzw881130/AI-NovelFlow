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


def director_language_instruction(language):
    if language is None:
        return ""
    target = {"en": "English", "zh": "Chinese"}[validate_language(language)]
    return f"""\n\nRUNTIME DESCRIPTIVE LANGUAGE CONTRACT — {LANGUAGE_CONTRACT}
For this request, write all directing prose, camera/action/expression descriptions,
speaker handoff, ambience/Foley and anchor reasons in {target}. This changes only
descriptive language, never spoken dialogue language or any Canonical facts.
Keep existing Subject tags and SPEECH slots verbatim. Do not output spoken lines.
Translate scene/prop descriptive labels too, overriding any earlier instruction to
preserve their wording; keep resource IDs, identities and bindings unchanged.
The response has the five original planning fields PLUS localized_descriptions.
This explicitly extends the original five-field-only rule for this request only.
localized_descriptions must be an object with EXACTLY the keys from
compiler_description_sources and string values translating each source text into
{target}, preserving every descriptive fact. Copy already-correct text as needed.
Do not summarize, add instructions, rename characters, create bindings or insert
Subject/Picture/Speaker/dialogue tags in these translations. Character names must
remain verbatim. These are descriptions, not authority or execution decisions.
The backend owns subject_definitions, summary, retention_analysis and all numbering.
Return no additional fields. Do not translate JSON keys, protocol tokens, IDs,
SPEECH slots, timing markers or music_policy's N/A sentinel.
"""


def description_sources(subject_names, appearances, picture_mapping, stable_marks):
    sources = {}
    for subject, name in subject_names.items():
        marks = stable_marks(appearances.get(name))
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


def validate_english_prose(text, character_names):
    """Protect the requested English boundary, allowing only exact character names.

    Call before speech injection (never scan or translate Canonical dialogue).
    This script check does not certify translation meaning or audiovisual quality.
    """
    for name in sorted(character_names, key=len, reverse=True):
        text = text.replace(name, "")
    if re.search(r"[\u3400-\u9fff]", text):
        raise ValueError("H3_PROMPT_LANGUAGE_MISMATCH: Chinese description in English output")
