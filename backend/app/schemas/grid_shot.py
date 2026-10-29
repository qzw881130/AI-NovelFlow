"""Versioned storage contract for a storyboard grid on one narrative Shot."""

import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator


GridLayout = Literal["2x2", "2x3", "3x3"]
ReviewStatus = Literal["pending", "passed", "warning", "failed"]


class GridPanel(BaseModel):
    index: int = Field(ge=1)
    beat: str = Field(min_length=1)
    camera: str = Field(min_length=1)
    action: str = ""
    axis: str = ""
    characters: list[str] = Field(default_factory=list)
    dialogue_indexes: list[int] = Field(default_factory=list)
    image_url: str | None = None
    image_task_id: str | None = None
    image_prompt: str | None = None
    image_reference_images: list[dict] = Field(default_factory=list)
    review_status: ReviewStatus = "pending"
    review_note: str | None = None


class GridShotData(BaseModel):
    version: Literal[1] = 1
    revision: int = Field(ge=1)
    layout: GridLayout
    seed: int = Field(ge=0)
    panel_width: int = Field(gt=0)
    panel_height: int = Field(gt=0)
    panels: list[GridPanel]
    board_image_url: str | None = None
    board_image_task_id: str | None = None
    board_prompt: str | None = None
    board_reference_images: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_grid(self):
        rows, cols = (int(value) for value in self.layout.split("x"))
        if len(self.panels) != rows * cols:
            raise ValueError("宫格子图数量必须等于版式格数，不允许空白格")
        if [panel.index for panel in self.panels] != list(range(1, rows * cols + 1)):
            raise ValueError("宫格子图必须按从左到右、从上到下的顺序编号")
        if self.panel_width * 9 != self.panel_height * 16:
            raise ValueError("每个宫格子图必须为 16:9")
        return self

    @property
    def board_size(self) -> tuple[int, int]:
        rows, cols = (int(value) for value in self.layout.split("x"))
        return cols * self.panel_width, rows * self.panel_height


def load_grid_data(raw: str | None) -> GridShotData | None:
    return GridShotData.model_validate_json(raw) if raw else None


def dump_grid_data(data: GridShotData) -> str:
    return data.model_dump_json(exclude_none=True)


def read_grid_clip_plan(raw: str | None, *, grid_revision: int) -> dict | None:
    """Keep grid Clips separate from the legacy Phase B plan shape."""
    plan = json.loads(raw or "{}")
    if not isinstance(plan, dict) or plan.get("contract") != "GRID_CLIP_PLAN_V1":
        return None
    if plan.get("grid_revision") != grid_revision:
        return None
    return plan


def dump_grid_clip_plan(data: GridShotData, clips: list[dict]) -> str:
    if not clips:
        raise ValueError("grid Clip plan must contain at least one Clip")
    valid_panels = {panel.index for panel in data.panels}
    for index, clip in enumerate(clips, 1):
        panel_indexes = clip.get("panel_indexes") if isinstance(clip, dict) else None
        if not isinstance(clip, dict) or clip.get("clip_index") != index or not isinstance(panel_indexes, list) or not panel_indexes:
            raise ValueError("grid Clips must be ordered and reference panels")
        if any(panel not in valid_panels for panel in panel_indexes):
            raise ValueError("grid Clip references an unknown panel")
    return json.dumps({
        "contract": "GRID_CLIP_PLAN_V1",
        "grid_revision": data.revision,
        "clip_plan": clips,
    }, ensure_ascii=False)
