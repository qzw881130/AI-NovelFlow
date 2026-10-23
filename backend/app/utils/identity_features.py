"""Stable character identity data is captured when a character is saved.

Prompt execution consumes the stored field. This compatibility extractor is
only for importing existing prose; an unrecognized phrase is not an error.
"""
import re


IDENTITY_CLAUSE = re.compile(
    r"(?:稳定身份标记(?:包括|为)|稳定识别特征(?:是|包括|为))\s*([^；。\n]+)[；。]"
)


def extract_identity_features(appearance: str | None) -> str | None:
    if not isinstance(appearance, str):
        return None
    match = IDENTITY_CLAUSE.search(appearance)
    value = match.group(1).strip(" ，, ") if match else ""
    return value or None


def update_identity_features(character, appearance: str | None, explicit: str | None = None) -> None:
    """Set a source-backed field; manual input wins over prose extraction."""
    if explicit is not None:
        character.stable_identity_features = explicit.strip() or None
        character.stable_identity_source = "MANUAL" if character.stable_identity_features else None
    elif character.stable_identity_source == "MANUAL":
        return
    else:
        character.stable_identity_features = extract_identity_features(appearance)
        character.stable_identity_source = "APPEARANCE_CLAUSE" if character.stable_identity_features else None
