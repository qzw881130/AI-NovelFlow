import json
from typing import Literal
from pydantic import Field, field_validator, model_validator
from app.schemas.chapter_asset_parse import StrictPayload, NonBlank, Evidence


class Dialogue(StrictPayload):
    order: int = Field(ge=1)
    character_name: NonBlank
    text: NonBlank
    emotion_prompt: str


class HistoricalAudioEvent(StrictPayload):
    order: int = Field(ge=1)
    type: Literal["DIALOGUE", "NARRATION", "INNER_MONOLOGUE"]
    voice_owner: NonBlank
    visible_speaker: NonBlank | None
    requires_visible_lipsync: bool
    text: NonBlank
    emotion_prompt: str
    pause_after: Literal["NONE", "SHORT", "MEDIUM", "LONG"]


class AudioEvent(HistoricalAudioEvent):
    treatment_ref: NonBlank


class TreatmentEvidence(StrictPayload):
    text: NonBlank
    context_before: NonBlank | None = None
    context_after: NonBlank | None = None

    @field_validator('context_before','context_after',mode='before')
    @classmethod
    def empty_context_is_absent(cls,value):
        return None if isinstance(value,str) and not value.strip() else value


class SourceTreatment(StrictPayload):
    key: NonBlank
    type: Literal['DIALOGUE', 'NARRATION', 'VISUAL']
    source_evidence: list[TreatmentEvidence] = Field(min_length=1, max_length=32)
    visual_targets: list[Literal['description', 'video_description']] = Field(default_factory=list, max_length=2)
    # Treatment.NARRATION is narrative vocal expression. The delivery below
    # preserves the distinction between Book Narrator and Character inner voice.
    audio_type: Literal['NARRATION', 'INNER_MONOLOGUE'] | None = None

    @model_validator(mode='after')
    def valid_delivery(self):
        if self.type != 'NARRATION' and self.audio_type is not None:
            raise ValueError('TREATMENT_CONFLICT: audio_type only belongs to narrative vocal treatment')
        if self.type == 'VISUAL' and not self.visual_targets:
            raise ValueError('TREATMENT_VISUAL_TARGET_MISSING')
        if len(set(self.visual_targets)) != len(self.visual_targets):
            raise ValueError('DUPLICATE_VISUAL_TARGET')
        return self


class HistoricalPlannedShot(StrictPayload):
    id: int = Field(ge=1)
    source_evidence: list[Evidence] = Field(min_length=1, max_length=32)
    description: NonBlank
    video_description: NonBlank
    characters: list[NonBlank]
    scene: NonBlank
    props: list[NonBlank]
    duration: int = Field(ge=1, le=3600)
    continuity_mode: Literal["NORMAL", "CONTINUOUS_TAKE"]
    dialogues: list[Dialogue]
    audio_events: list[HistoricalAudioEvent]


class PlannedShot(HistoricalPlannedShot):
    audio_events: list[AudioEvent]
    source_treatments: list[SourceTreatment] = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def unique_treatments(self):
        keys=[t.key for t in self.source_treatments]
        if len(keys)!=len(set(keys)):
            raise ValueError('DUPLICATE_TREATMENT_KEY')
        return self


class OwnershipEvidence(StrictPayload):
    text: NonBlank
    context_before: NonBlank | None = None
    context_after: NonBlank | None = None

    @field_validator('context_before','context_after',mode='before')
    @classmethod
    def empty_context_is_absent(cls,value):
        return None if isinstance(value,str) and not value.strip() else value


class OwnershipPlannedShot(StrictPayload):
    id: int = Field(ge=1)
    source_citations: list[OwnershipEvidence] = Field(min_length=1, max_length=32)
    source_ownership: OwnershipEvidence
    description: NonBlank
    video_description: NonBlank
    characters: list[NonBlank]
    scene: NonBlank
    props: list[NonBlank]
    duration: int = Field(ge=1, le=3600)
    continuity_mode: Literal["NORMAL", "CONTINUOUS_TAKE"]
    dialogues: list[Dialogue]
    audio_events: list[AudioEvent]
    source_treatments: list[SourceTreatment] = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def unique_treatments(self):
        keys = [t.key for t in self.source_treatments]
        if len(keys) != len(set(keys)):
            raise ValueError('DUPLICATE_TREATMENT_KEY')
        return self


class NarrationCardPlannedShot(StrictPayload):
    id: int = Field(ge=1)
    completion_disposition: Literal['DEGRADED_NARRATION_CARD']
    source_citations: list[OwnershipEvidence] = Field(min_length=1, max_length=32)
    source_ownership: OwnershipEvidence
    description: NonBlank
    video_description: NonBlank
    characters: list[NonBlank] = Field(max_length=0)
    scene: Literal['']
    props: list[NonBlank] = Field(max_length=0)
    duration: int = Field(ge=1, le=3600)
    continuity_mode: Literal['NORMAL']
    dialogues: list[Dialogue] = Field(max_length=0)
    audio_events: list[AudioEvent] = Field(min_length=1, max_length=1)
    source_treatments: list[SourceTreatment] = Field(min_length=1, max_length=1)


class UnresolvedAsset(StrictPayload):
    asset_type: Literal["characters", "scenes", "props"]
    name: NonBlank
    source_evidence: list[Evidence] = Field(min_length=1)
    reason: NonBlank


class ControlledDegradationOutput(StrictPayload):
    source_contract_version: Literal['chapter-shot-ownership-v2']
    chapter: str
    characters: list[NonBlank]
    scenes: list[NonBlank]
    props: list[NonBlank]
    shots: list[OwnershipPlannedShot | NarrationCardPlannedShot] = Field(min_length=1, max_length=500)
    unresolved_assets: list[UnresolvedAsset] = Field(default_factory=list)


class HistoricalSplitOutput(StrictPayload):
    chapter: str
    characters: list[NonBlank]
    scenes: list[NonBlank]
    props: list[NonBlank]
    shots: list[HistoricalPlannedShot] = Field(max_length=500)
    unresolved_assets: list[UnresolvedAsset] = Field(default_factory=list)


class SplitOutput(HistoricalSplitOutput):
    shots: list[PlannedShot] = Field(max_length=500)


class OwnershipSplitOutput(StrictPayload):
    source_contract_version: Literal['chapter-shot-ownership-v2']
    chapter: str
    characters: list[NonBlank]
    scenes: list[NonBlank]
    props: list[NonBlank]
    shots: list[OwnershipPlannedShot] = Field(max_length=500)
    unresolved_assets: list[UnresolvedAsset] = Field(default_factory=list)


class CharacterClosureRepairLine(StrictPayload):
    name: NonBlank
    visual_description: NonBlank


class ShotContractRepairItem(StrictPayload):
    shot_index: int = Field(ge=1)
    field: Literal["description"]
    characters: list[CharacterClosureRepairLine] = Field(min_length=1)


class ShotContractRepairOutput(StrictPayload):
    repair_type: Literal["SHOT_VISIBLE_CHARACTER_CLOSURE"]
    repairs: list[ShotContractRepairItem] = Field(min_length=1)


class AppearanceBoundaryResplitItem(StrictPayload):
    shot_index: int = Field(ge=1)
    replacements: list[OwnershipPlannedShot] = Field(min_length=2, max_length=16)


class AppearanceBoundaryRepairOutput(StrictPayload):
    repair_type: Literal["SHOT_CROSSES_APPEARANCE_BOUNDARY"]
    repairs: list[AppearanceBoundaryResplitItem] = Field(min_length=1)


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"DUPLICATE_JSON_KEY: {key}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f"INVALID_JSON_CONSTANT: {value}")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def parse_output(raw, expected_version=None, source_window_version=None):
    decoded = _decode(raw)
    if expected_version is None:
        return SplitOutput.model_validate(decoded).model_dump()
    if expected_version != 'chapter-shot-ownership-v2':
        raise ValueError(f'SOURCE_CONTRACT_VERSION: {expected_version}')
    if not isinstance(decoded, dict) or decoded.get('source_contract_version') != expected_version:
        raise ValueError('SOURCE_CONTRACT_VERSION: selected v2 output required')
    if source_window_version is not None:
        if source_window_version != 'appearance-source-windows-v1':
            raise ValueError(f'SOURCE_WINDOW_VERSION: {source_window_version}')
    return OwnershipSplitOutput.model_validate(decoded).model_dump()


def parse_repair_output(raw):
    decoded=_decode(raw)
    if not isinstance(decoded,dict):raise ValueError('SHOT_CONTRACT_REPAIR_OUTPUT_INVALID')
    if decoded.get('repair_type')=='SHOT_VISIBLE_CHARACTER_CLOSURE':
        return ShotContractRepairOutput.model_validate(decoded).model_dump()
    if decoded.get('repair_type')=='SHOT_CROSSES_APPEARANCE_BOUNDARY':
        return AppearanceBoundaryRepairOutput.model_validate(decoded).model_dump()
    raise ValueError('SHOT_CONTRACT_REPAIR_TYPE_UNSUPPORTED')


def parse_controlled_degradation_output(raw):
    decoded=_decode(raw)
    if not isinstance(decoded,dict):raise ValueError('CONTROLLED_DEGRADATION_OUTPUT_INVALID')
    return ControlledDegradationOutput.model_validate(decoded).model_dump()


def read_historical_output(raw):
    """Historical structural proof only. This decoder cannot grant production admission."""
    return HistoricalSplitOutput.model_validate(_decode(raw)).model_dump()
