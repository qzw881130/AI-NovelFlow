from pydantic import Field
from app.schemas.asset_resolution import StrictModel
from app.schemas.chapter_asset_parse import NonBlank


class GenerateAppearanceRequest(StrictModel):
    seed: int | None = Field(None, ge=0, le=18446744073709551615)
    regenerate: bool = False


class RejectAppearanceRequest(StrictModel):
    expected_generation_id: NonBlank
    expected_image_revision_id: NonBlank
    reason: NonBlank


class GenerateUsedAppearancesRequest(StrictModel):
    shot_ids: list[str] = Field(min_length=1)
