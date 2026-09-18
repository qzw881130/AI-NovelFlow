import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.chapter_asset_parse import ParseChapterAssetsRequest, NonBlank, CharacterCandidate, SceneCandidate, PropCandidate


class ResolveRequest(ParseChapterAssetsRequest):
    force: bool = False


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Match(StrictModel):
    asset_id: NonBlank
    canonical_name: NonBlank
    confidence: float = Field(ge=0, le=1)


class ResolutionOutput(StrictModel):
    resolution: Literal["EXISTING", "NEW", "AMBIGUOUS"]
    matched_asset_id: NonBlank | None
    canonical_name: NonBlank
    confidence: float = Field(ge=0, le=1)
    match_type: Literal["EXACT_NAME", "STRONG_ALIAS", "CONTEXTUAL_ALIAS", "SEMANTIC_MATCH", "NEW", "AMBIGUOUS"]
    needs_review: bool
    candidate_matches: list[Match]
    reason: NonBlank

    @model_validator(mode="after")
    def consistent(self):
        if self.resolution == "EXISTING":
            if not self.matched_asset_id or self.needs_review or self.match_type in {"NEW", "AMBIGUOUS"}:
                raise ValueError("invalid EXISTING decision")
        elif self.resolution == "NEW":
            if self.matched_asset_id is not None or self.candidate_matches or self.needs_review or self.match_type != "NEW":
                raise ValueError("invalid NEW decision")
        elif self.matched_asset_id is not None or not self.candidate_matches or not self.needs_review or self.match_type != "AMBIGUOUS":
            raise ValueError("invalid AMBIGUOUS decision")
        if len({item.asset_id for item in self.candidate_matches}) != len(self.candidate_matches):
            raise ValueError("duplicate candidate match")
        return self


def parse_resolution(raw, kind):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    if kind == "characters" and isinstance(value, dict):
        if "matched_asset_id" in value:
            raise ValueError("unexpected asset key in character output")
        value["matched_asset_id"] = value.pop("matched_character_id")
        for match in value.get("candidate_matches", []):
            if "asset_id" in match:
                raise ValueError("unexpected match key")
            match["asset_id"] = match.pop("character_id")
    return ResolutionOutput.model_validate(value).model_dump()


class ReviewAction(StrictModel):
    action: Literal["MATCH", "CREATE", "IGNORE"]
    asset_id: str | None = None
    canonical_name: str | None = None
    confirm_legacy_type: bool = False
    expected_catalog_hash: NonBlank


class IdentityRequest(StrictModel):
    entity_type: Literal["INDIVIDUAL", "GROUP"]
    group_size_hint: int | None = None
    context: dict = Field(default_factory=dict)


class AliasRequest(StrictModel):
    alias: NonBlank
    alias_type: Literal["STRONG", "CONTEXTUAL"]
    scope: dict = Field(default_factory=dict)


class PreviewRequest(StrictModel):
    chapter_id: NonBlank
    asset_type: Literal["characters", "scenes", "props"]
    candidate: dict

    @model_validator(mode="after")
    def candidate_shape(self):
        schema = {"characters": CharacterCandidate, "scenes": SceneCandidate, "props": PropCandidate}[self.asset_type]
        self.candidate = schema.model_validate(self.candidate).model_dump()
        return self
