from typing import Literal
from pydantic import Field, model_validator
from app.schemas.asset_resolution import StrictModel
from app.schemas.chapter_asset_parse import NonBlank


class TimelineBuildRequest(StrictModel):
    force: bool = False


class AppearanceReviewRequest(StrictModel):
    action: Literal["LOCATE", "CONFIRM_NEW", "IGNORE"]
    expected_source_hash: NonBlank
    expected_proposal_hash: NonBlank
    source_start: int | None = Field(None, ge=0)
    source_end: int | None = Field(None, ge=0)
    evidence_text: NonBlank | None = None
    appearance_description: NonBlank | None = None
    reason: NonBlank

    @model_validator(mode="after")
    def explicit_choice(self):
        if self.action != "IGNORE" and (self.source_start is None or self.source_end is None or not self.evidence_text):
            raise ValueError("exact source span required")
        if self.action == "CONFIRM_NEW" and not self.appearance_description:
            raise ValueError("confirmed appearance description required")
        return self
