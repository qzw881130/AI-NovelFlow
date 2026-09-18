"""Lawful F07 authoring fixture; only the later Shot Director call is real."""
import hashlib
from pathlib import Path

from PIL import Image

from app.models.novel import Chapter, Novel, Scene
from app.models.prompt_template import PromptTemplate
from app.models.shot import Shot
from app.services.appearance_timeline_service import AppearanceTimelineService
from app.services.chapter_governance import register_new_chapter
from test_appearance_timeline import prepare
from test_asset_resolution import extract, resolve


SOURCE_TEXT = "🐺刘备在桃园站定。"
COMPATIBLE_TEMPLATE_HASH = "270063b5fff8a55c298a673974c7c01ad9bfd036f89e234b1cd439a60fc7ddf5"


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def selected_template(db, kind, expected_hash=None):
    templates = db.query(PromptTemplate).filter_by(type=kind, is_system=True, is_active=True).all()
    if expected_hash:
        templates = [
            row for row in templates
            if hashlib.sha256(row.template.encode("utf-8")).hexdigest() == expected_hash
        ]
    if not templates:
        raise RuntimeError(f"F07_FIXTURE_TEMPLATE_MISSING: {kind}")
    return sorted(templates, key=lambda row: row.id)[0]


def seed(db, storage_root):
    """Seed formal Binding/Appearance receipts with a labeled test upstream."""
    book = Novel(title="R2-B F07 private live ownership chain")
    db.add(book)
    db.flush()
    book.character_parse_prompt_template_id = selected_template(db, "character_parse").id
    book.scene_parse_prompt_template_id = selected_template(db, "scene_parse").id
    book.prop_parse_prompt_template_id = selected_template(db, "prop_parse").id
    split_template = selected_template(db, "chapter_split", COMPATIBLE_TEMPLATE_HASH)
    book.chapter_split_prompt_template_id = split_template.id
    chapter = Chapter(novel_id=book.id, number=1, title="F07真实链", content=SOURCE_TEXT)
    db.add(chapter)
    db.flush()
    register_new_chapter(db, chapter)
    db.commit()

    actor = prepare(db, chapter, SOURCE_TEXT, name="刘备")
    extract(db, chapter, [{
        "name": "桃园",
        "description": "桃园空地",
        "setting": "桃树环绕的开阔空地",
        "source_evidence": [{"text": "桃园"}],
    }], "scenes")
    scene_result = resolve(db, chapter, kinds=["scenes"])
    if not scene_result["success"]:
        raise RuntimeError(f"F07_SCENE_BINDING_FAILED: {scene_result}")
    extract(db, chapter, [], "props")
    prop_result = resolve(db, chapter, kinds=["props"])
    if not prop_result["success"]:
        raise RuntimeError(f"F07_PROP_BINDING_FAILED: {prop_result}")
    timeline = AppearanceTimelineService(db).build(book.id, chapter.id)
    if not timeline["success"]:
        raise RuntimeError(f"F07_TIMELINE_FAILED: {timeline}")

    relative = Path(f"story_{book.id[:8]}") / "f07_inputs"
    image_dir = Path(storage_root) / relative
    image_dir.mkdir(parents=True, exist_ok=False)
    actor_path = image_dir / "actor.png"
    scene_path = image_dir / "scene.png"
    Image.new("RGB", (192, 128), "navy").save(actor_path)
    Image.new("RGB", (192, 128), "green").save(scene_path)
    actor.image_url = "/api/files/" + str(relative / actor_path.name)
    actor.generating_status = "completed"
    scene = db.query(Scene).filter_by(novel_id=book.id, name="桃园").one()
    scene.image_url = "/api/files/" + str(relative / scene_path.name)
    scene.generating_status = "completed"
    db.commit()
    if db.query(Shot).filter_by(chapter_id=chapter.id).count():
        raise RuntimeError("F07_FIXTURE_MUST_START_WITHOUT_SHOTS")
    return {
        "novelId": book.id,
        "chapterId": chapter.id,
        "sourceText": SOURCE_TEXT,
        "sourceCodePoints": len(SOURCE_TEXT),
        "splitTemplateId": split_template.id,
        "splitTemplateHash": COMPATIBLE_TEMPLATE_HASH,
        "upstreamProvider": "test",
        "upstreamPurpose": "BINDING_AND_APPEARANCE_FIXTURE_ONLY",
        "realDirectorRequired": True,
        "rsaImageInputs": [
            {"kind": "CHARACTER_BASE", "url": actor.image_url, "sha256": file_sha(actor_path)},
            {"kind": "SCENE", "url": scene.image_url, "sha256": file_sha(scene_path)},
        ],
    }
