"""File and Task snapshot helpers reserved for the grid generation path."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from app.schemas.grid_shot import GridShotData
from app.services.file_storage import file_storage


def grid_asset_path(
    novel_id: str, chapter_id: str, shot_id: str, revision: int,
    *, panel_index: int | None = None, asset_id: str | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Use a fresh asset name per attempt so previous Task inputs stay readable."""
    for value in (novel_id, chapter_id, shot_id):
        UUID(value)
    if revision < 1:
        raise ValueError("grid revision must be positive")
    if panel_index is not None and panel_index < 1:
        raise ValueError("panel index must be positive")
    asset = asset_id or str(uuid4())
    UUID(asset)
    root = Path(base_dir) if base_dir is not None else file_storage.base_dir
    folder = root / f"story_{novel_id[:8]}" / f"chapter_{chapter_id[:8]}" / "grid" / shot_id / f"r{revision}"
    name = f"panel_{panel_index:02d}_{asset}.png" if panel_index is not None else f"board_{asset}.png"
    return folder / name


def save_grid_png(data: bytes, path: Path, *, base_dir: Path | None = None) -> str:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("grid asset must be PNG data")
    root = (Path(base_dir) if base_dir is not None else file_storage.base_dir).resolve()
    target = path.resolve()
    if not target.is_relative_to(root):
        raise ValueError("grid image must be inside user_story")
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return f"/api/files/{target.relative_to(root).as_posix()}"


def record_grid_task_inputs(task, data: GridShotData, *, panel_indexes: list[int],
                            reference_images: list[dict], prompt_text: str,
                            template_snapshot: str | None = None) -> None:
    """Write the exact grid inputs into existing Task snapshot columns."""
    valid = {panel.index for panel in data.panels}
    if not panel_indexes or any(index not in valid for index in panel_indexes):
        raise ValueError("task panel indexes must belong to the saved grid")
    if any(ref.get("picture_index") != index or not ref.get("url")
           for index, ref in enumerate(reference_images, 1)):
        raise ValueError("reference images must have ordered Picture numbers and URLs")
    metadata = json.loads(task.metadata_json or "{}")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.update({
        "video_mode": "grid",
        "grid_version": data.version,
        "grid_revision": data.revision,
        "grid_layout": data.layout,
        "grid_seed": data.seed,
        "panel_indexes": list(panel_indexes),
        "prompt_template_snapshot": template_snapshot,
    })
    task.prompt_text = prompt_text
    task.reference_images = json.dumps(reference_images, ensure_ascii=False)
    task.metadata_json = json.dumps(metadata, ensure_ascii=False)
