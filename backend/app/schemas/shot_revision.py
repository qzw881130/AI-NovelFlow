"""Shared client-CAS aliases for every formal Shot/Event authoring request."""
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


PROTECTED_SOURCE_FIELDS = frozenset({
    'source_contract','sourceContract','source_contract_version','sourceContractVersion',
    'source_citations','sourceCitations','source_citation_ranges','sourceCitationRanges',
    'source_ownership','sourceOwnership','source_evidence','sourceEvidence','source_ranges','sourceRanges',
    'citation_evidence','citationEvidence','citation_ranges','citationRanges',
    'ownership_evidence','ownershipEvidence','ownership_range','ownershipRange',
    'source_start','sourceStart','source_end','sourceEnd','source_hash','sourceHash',
    'source_run_id','sourceRunId','run_id','runId','evidence','ranges','bindings','assetBindings',
    'offset','offset_unit','offsetUnit','source_seal','sourceSeal','base_seal','baseSeal',
})


def normalize_revision_aliases(value):
    if not isinstance(value,dict):return value
    if set(value) & PROTECTED_SOURCE_FIELDS:
        raise ValueError('SHOT_REVISION_PROTECTED_FIELD')
    keys=('expected_revision','expectedRevision','sourceRevision')
    values=[value[k] for k in keys if k in value]
    if not values:return value
    if any(type(v) is not type(values[0]) or v!=values[0] for v in values[1:]):
        raise ValueError('SHOT_REVISION_ALIAS_CONFLICT')
    return {**{k:v for k,v in value.items() if k not in keys},'expected_revision':values[0]}


class RevisionRequest(BaseModel):
    model_config=ConfigDict(populate_by_name=True)
    expected_revision: Optional[int]=Field(None,ge=0,strict=True)

    @model_validator(mode='before')
    @classmethod
    def canonical_revision(cls,value):
        return normalize_revision_aliases(value)
