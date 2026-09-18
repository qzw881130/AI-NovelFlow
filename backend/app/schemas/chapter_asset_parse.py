"""Strict V3.1.2 wire schema; missing fields must never become empty success."""
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator, field_validator

AssetKind = Literal["characters", "scenes", "props"]
NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Evidence(StrictPayload):
    text: NonBlank


class ChapterPresence(StrictPayload):
    role: Literal["MAJOR", "SUPPORTING", "BACKGROUND"]


class AppearanceChange(StrictPayload):
    event_key: NonBlank
    change_type: Literal["new", "uncertain"]
    appearance_description: NonBlank | None
    source_evidence: list[Evidence] = Field(min_length=1)

    @model_validator(mode="after")
    def require_new_description(self):
        if self.change_type == "new" and self.appearance_description is None:
            raise ValueError("new appearance requires appearance_description")
        return self


class NamedCandidate(StrictPayload):
    name: NonBlank

    @field_validator("name")
    @classmethod
    def canonical_name(cls, value):
        if value != value.strip():
            raise ValueError("name must not contain leading/trailing whitespace")
        return value


class CharacterCandidate(NamedCandidate):
    name: NonBlank
    entity_type: Literal["INDIVIDUAL", "GROUP"]
    group_size_hint: Annotated[int, Field(ge=1)] | None
    description: NonBlank
    appearance: NonBlank
    voice_prompt: NonBlank | None
    chapter_presence: ChapterPresence
    source_evidence: list[Evidence] = Field(min_length=1)
    chapter_appearances: list[AppearanceChange]

    @field_validator("appearance")
    @classmethod
    def single_paragraph(cls, value):
        if "\n" in value or "\r" in value or value.lstrip().startswith(("{", "[", "- ", "* ")):
            raise ValueError("appearance must be a natural-language single paragraph")
        return value

    @model_validator(mode="after")
    def entity_and_events(self):
        if self.entity_type == "INDIVIDUAL" and self.group_size_hint != 1:
            raise ValueError("INDIVIDUAL group_size_hint must be 1")
        if self.entity_type == "GROUP" and self.group_size_hint == 1:
            raise ValueError("GROUP group_size_hint must be >= 2 or null")
        keys = [event.event_key for event in self.chapter_appearances]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate appearance event_key in character")
        return self


class SceneCandidate(NamedCandidate):
    name: NonBlank
    description: NonBlank
    setting: NonBlank
    source_evidence: list[Evidence] = Field(min_length=1)


class PropCandidate(NamedCandidate):
    name: NonBlank
    description: NonBlank
    appearance: NonBlank
    source_evidence: list[Evidence] = Field(min_length=1)


class CharactersOutput(StrictPayload):
    characters: list[CharacterCandidate]


class ScenesOutput(StrictPayload):
    scenes: list[SceneCandidate]


class PropsOutput(StrictPayload):
    props: list[PropCandidate]


class ParseChapterAssetsRequest(StrictPayload):
    kinds: list[AssetKind] = Field(default_factory=lambda: ["characters", "scenes", "props"], min_length=1)

    @field_validator("kinds")
    @classmethod
    def unique_kinds(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("duplicate asset kind")
        return value


def validate_output(kind: AssetKind, content: str) -> list[dict]:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"invalid JSON constant: {value}")

    value = json.loads(content, object_pairs_hook=unique_keys, parse_constant=reject_constant)
    schema = {"characters": CharactersOutput, "scenes": ScenesOutput, "props": PropsOutput}[kind]
    payload = schema.model_validate(value).model_dump()[kind]
    names = [item["name"].strip() for item in payload]
    if len(names) != len(set(names)):
        raise ValueError("duplicate canonical name in chapter output")
    return payload
