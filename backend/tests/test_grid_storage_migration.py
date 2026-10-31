import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from app.schemas.grid_shot import (
    GridShotData, dump_grid_clip_plan, dump_grid_data, load_grid_data,
    read_grid_clip_plan,
)
from app.services.grid_storage import grid_asset_path, record_grid_task_inputs, save_grid_png
from app.models.novel import Novel
from app.models.prompt_template import PromptTemplate
from app.repositories.novel_repository import NovelRepository
from migrations.add_grid_video_mode_storage import upgrade_connection


def _grid():
    return GridShotData(
        revision=1, layout="2x2", seed=1234, panel_width=640, panel_height=360,
        panels=[{"index": index, "beat": f"Beat {index}", "camera": "近景"} for index in range(1, 5)],
    )


def test_migration_marks_existing_novels_single_and_preserves_old_shot_image():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE novels (id VARCHAR PRIMARY KEY, title VARCHAR)"))
        conn.execute(text("CREATE TABLE shots (id VARCHAR PRIMARY KEY, image_url VARCHAR)"))
        conn.execute(text("INSERT INTO novels (id, title) VALUES ('n1', '旧小说')"))
        conn.execute(text("INSERT INTO shots (id, image_url) VALUES ('s1', '/api/files/old.png')"))
        upgrade_connection(conn)
        upgrade_connection(conn)
        assert conn.execute(text("SELECT video_mode FROM novels WHERE id='n1'")).scalar_one() == "single"
        assert conn.execute(text("SELECT image_url FROM shots WHERE id='s1'")).scalar_one() == "/api/files/old.png"
        assert conn.execute(text("SELECT grid_data FROM shots WHERE id='s1'")).scalar_one() is None
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(novels)"))}
        assert "grid_h3_phase_b_prompt_template_id" in columns
        assert "grid_panel_review_prompt_template_id" in columns


def test_grid_contract_keeps_layout_seed_and_panel_order():
    data = _grid()
    assert data.board_size == (1280, 720)
    assert load_grid_data(dump_grid_data(data)) == data
    with pytest.raises(ValueError, match="空白格"):
        GridShotData(revision=1, layout="2x3", seed=1, panel_width=640, panel_height=360,
                     panels=[{"index": i, "beat": "test", "camera": "远景"} for i in range(1, 5)])
    plan = dump_grid_clip_plan(data, [{"clip_index": 1, "panel_indexes": [1, 2]}])
    assert read_grid_clip_plan(plan, grid_revision=1)["contract"] == "GRID_CLIP_PLAN_V1"
    assert read_grid_clip_plan(plan, grid_revision=2) is None


def test_grid_files_and_task_snapshot_are_isolated(tmp_path):
    novel_id, chapter_id, shot_id = (str(uuid4()) for _ in range(3))
    path = grid_asset_path(novel_id, chapter_id, shot_id, 1, panel_index=2, base_dir=tmp_path)
    url = save_grid_png(b"\x89PNG\r\n\x1a\n" + b"image", path, base_dir=tmp_path)
    assert path.read_bytes().startswith(b"\x89PNG")
    assert f"/grid/{shot_id}/r1/panel_02_" in url
    task = SimpleNamespace(metadata_json='{"clip_index": 1}', prompt_text=None, reference_images=None)
    refs = [{"picture_index": 1, "url": url}]
    record_grid_task_inputs(task, _grid(), panel_indexes=[2], reference_images=refs,
                            prompt_text="six sections", template_snapshot="template text")
    assert task.prompt_text == "six sections"
    assert json.loads(task.reference_images) == refs
    metadata = json.loads(task.metadata_json)
    assert (metadata["video_mode"], metadata["grid_revision"], metadata["grid_layout"]) == ("grid", 1, "2x2")
    assert metadata["prompt_template_snapshot"] == "template text"


def test_copy_keeps_grid_mode_and_only_compatible_template_bindings(db_session):
    grid = PromptTemplate(name="grid", type="grid_shot_plan", template="grid", is_active=True)
    single = PromptTemplate(name="single", type="chapter_split", template="single", is_active=True)
    shared = PromptTemplate(name="style", type="style", template="style", is_active=True)
    db_session.add_all([grid, single, shared])
    db_session.flush()
    source = Novel(title="宫格来源", video_mode="grid", grid_shot_plan_prompt_template_id=grid.id,
                   chapter_split_prompt_template_id=single.id, style_prompt_template_id=shared.id)
    db_session.add(source)
    db_session.commit()
    copied = NovelRepository(db_session).copy_with_chapters(source, "宫格副本")
    assert copied.video_mode == "grid"
    assert copied.grid_shot_plan_prompt_template_id == grid.id
    assert copied.style_prompt_template_id == shared.id
    assert copied.chapter_split_prompt_template_id is None
