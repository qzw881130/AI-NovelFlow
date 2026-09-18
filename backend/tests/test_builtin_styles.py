"""Offline style regressions. Run with --noconftest; never import app.main.

Real catalog, ORM models, repository and prompt composition are loaded without
package initializers or application configuration. Only in-memory SQLite is allowed.
"""

from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import socket
import sqlite3
import sys
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base


BACKEND = Path(__file__).resolve().parents[1]
STYLE_NAMES = [
    "\u52a8\u6f2b\u98ce\u683c",
    "\u5199\u5b9e\u98ce\u683c",
    "Q\u7248\u98ce\u683c",
    "\u6c34\u58a8\u98ce\u683c",
    "3D\u52a8\u753b\u98ce\u683c",
    "\u6c34\u5f69\u7ed8\u672c\u98ce\u683c",
    "\u6cb9\u753b\u98ce\u683c",
    "\u7f8e\u5f0f\u6f2b\u753b\u98ce\u683c",
    "\u50cf\u7d20\u827a\u672f\u98ce\u683c",
    "\u526a\u7eb8\u827a\u672f\u98ce\u683c",
    "\u9ecf\u571f\u5b9a\u683c\u98ce\u683c",
    "\u56fd\u98ce\u5de5\u7b14\u98ce\u683c",
]
CHARACTER_FILES = ["standard_anime.txt", "realistic.txt", "chibi_cartoon.txt", "ink_painting.txt"]


@pytest.fixture
def isolated(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Style tests must not access the network or application services")

    connect = sqlite3.dbapi2.connect

    def memory_only(database, *args, **kwargs):
        assert database == ":memory:", "Style tests must not open a database file"
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", memory_only)
    monkeypatch.setattr(sqlite3.dbapi2, "connect", memory_only)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    for name in ("app", "app.core", "app.models", "app.repositories", "app.services", "app.utils"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    for name in ("app.main", "app.core.config", "app.services.file_storage"):
        monkeypatch.setitem(sys.modules, name, None)

    database = ModuleType("app.core.database")
    database.Base = declarative_base()
    monkeypatch.setitem(sys.modules, database.__name__, database)

    def load(name):
        spec = importlib.util.spec_from_file_location(name, BACKEND / (name.replace(".", "/") + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    template = load("app.models.prompt_template").PromptTemplate
    models = load("app.models.novel")
    shot = load("app.models.shot").Shot
    repo = load("app.repositories.prompt_template").PromptTemplateRepository
    sys.modules["app.repositories"].PromptTemplateRepository = repo
    load("app.utils.time_utils")
    catalog = load("app.services.prompt_template_service")
    builder = load("app.services.prompt_builder").PromptBuilder
    engine = create_engine("sqlite:///:memory:")
    database.Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        yield SimpleNamespace(
            db=db, catalog=catalog, template=template, models=models, shot=shot, builder=builder,
            service=catalog.PromptTemplateService(db),
        )
    engine.dispose()
    database.Base.registry.dispose()


def snapshot(rows):
    return {row.id: {column.name: getattr(row, column.name) for column in row.__table__.columns} for row in rows}


def test_catalog_has_twelve_distinct_rendering_only_styles(isolated):
    styles = isolated.catalog.SYSTEM_STYLE_TEMPLATES
    assert [style["name"] for style in styles] == STYLE_NAMES
    assert len({style["template"] for style in styles}) == 12
    markers = [
        ("2D anime", "linework", "cel-shaded"),
        ("cinematic photorealistic", "physically plausible", "follow the story"),
        ("2D chibi", "2.5-to-3-head-tall", "functional proportions"),
        ("ink-wash", "brush pressure", "absorbent paper"),
        ("3D animation", "modeled forms", "roughness"),
        ("watercolor", "transparent", "granulation"),
        ("oil painting", "glazes", "canvas"),
        ("American comic", "ink contours", "halftone"),
        ("pixel art", "pixel grid", "dithering"),
        ("cut-paper", "cut edges", "paper fibers"),
        ("clay stop-motion", "hand-sculpted", "matte"),
        ("gongbi", "controlled outlines", "translucent color"),
    ]
    for style, required in zip(styles, markers):
        assert set(style) == {"name", "description", "template", "type"}
        assert style["type"] == "style"
        assert style["description"]
        text = style["template"]
        assert all(marker in text for marker in required)
        assert "Preserve authored identities" in text
        assert "clothing, props, architecture and world details" in text
        for prohibited in (
            "{", "}", "##", "json", "schema", "camera", "pose", "dialogue", "centered",
            "three kingdoms", "eastern han", "no modern", "no fantasy", "pixar", "disney", "ghibli",
        ):
            assert prohibited not in text.lower()
    assert "modern or fantastical elements when authored" in styles[1]["template"]
    assert "do not give buildings or objects chibi anatomy" in styles[2]["template"]


@pytest.mark.parametrize("autoflush", [False, True])
def test_fresh_init_is_idempotent_and_keeps_anime_fallback(isolated, autoflush):
    s = isolated
    s.db.autoflush = autoflush
    s.service.init_system_templates()
    first = snapshot(s.db.query(s.template).all())
    assert len(first) == len(s.catalog.SYSTEM_PROMPT_TEMPLATES)
    repair=s.service.get_default_system_template('shot_contract_repair')
    assert repair.name=='分镜契约自动修复 V1' and repair.is_system and repair.is_active
    assert '[version: shot-contract-auto-repair-v1]' in repair.template
    styles = s.service.list_templates("style")
    assert len(styles) == 12
    assert all(style.is_system and style.is_active for style in styles)
    assert s.service.get_default_system_template("style").name == STYLE_NAMES[0]
    for style_type in ("character", "scene", "prop"):
        text, selected = s.builder.get_style(s.db, style_type=style_type)
        assert selected.name == STYLE_NAMES[0]
        assert text == s.catalog.SYSTEM_STYLE_TEMPLATES[0]["template"]
    s.service.init_system_templates()
    s.db.expire_all()
    assert snapshot(s.db.query(s.template).all()) == first
    for style in s.service.list_templates("style"):
        response = s.service.to_response(style)
        assert response["nameKey"] == f"promptConfig.templateNames.{style.name}"
        assert response["descriptionKey"] == f"promptConfig.templateDescriptions.{style.name}"
        assert response["isSystem"] is True
        assert "isDefault" not in response


@pytest.mark.parametrize("earliest_style", range(4))
def test_upgrade_preserves_ids_bindings_customs_and_effective_fallback(isolated, earliest_style):
    s = isolated
    epoch = datetime(2020, 1, 1)
    legacy_catalog = [
        data for data in s.catalog.SYSTEM_PROMPT_TEMPLATES
        if data["type"] != "style" or data["name"] in STYLE_NAMES[:4]
    ]
    legacy_rows = []
    for index, data in enumerate(legacy_catalog):
        owned = data["type"] in ("style", "character", "scene", "prop")
        legacy_rows.append(s.template(
            **{**data, "template": "previous builtin text" if owned else data["template"],
               "description": "previous builtin description" if owned else data["description"]},
            id=f"builtin-{index}", is_system=True, is_active=index % 2 == 0,
            created_at=epoch + timedelta(seconds=index), updated_at=epoch,
        ))
    legacy_rows[earliest_style].created_at = epoch - timedelta(days=1)
    s.db.add_all(legacy_rows)

    # Include same-name customs for both old and newly added styles and all six asset templates.
    custom_data = [data for data in s.catalog.SYSTEM_PROMPT_TEMPLATES if data["type"] in ("style", "character", "scene", "prop")]
    custom_data.append({"name": "My private style", "type": "style"})
    customs = [s.template(
        id=f"custom-{index}", name=data["name"], type=data["type"],
        description="keep custom description", template=f"custom rendering {index}",
        is_system=False, is_active=False, created_at=epoch - timedelta(days=10), updated_at=epoch,
    ) for index, data in enumerate(custom_data)]
    s.db.add_all(customs)
    other_type = s.template(
        id="other-type", name=STYLE_NAMES[0], type="character_parse",
        description="unrelated system row", template="do not replace", is_system=True,
    )
    s.db.add(other_type)
    generation_ids = {
        field: next(row.id for row in legacy_rows if row.type == kind)
        for field, kind in (("prompt_template_id", "character"), ("scene_prompt_template_id", "scene"), ("prop_prompt_template_id", "prop"))
    }
    style_bindings = [row.id for row in legacy_rows[:4]] + [customs[0].id, customs[4].id, None, "deleted-style"]
    novels = [s.models.Novel(
        id=f"novel-{index}", title=f"Story {index}", style_prompt_template_id=binding, **generation_ids,
    ) for index, binding in enumerate(style_bindings)]
    s.db.add_all(novels)
    saved_assets = [
        s.models.Character(id="character", novel_id=novels[0].id, name="Engineer", appearance="authored identity", image_url="saved-character.png"),
        s.models.Scene(id="scene", novel_id=novels[0].id, name="Station", setting="authored world", image_url="saved-scene.png"),
        s.models.Prop(id="prop", novel_id=novels[0].id, name="Watch", appearance="authored prop", image_url="saved-prop.png"),
        s.models.Chapter(id="chapter", novel_id=novels[0].id, number=1, title="One", content="saved prose", final_video="saved-chapter.mp4"),
        s.shot(id="shot", chapter_id="chapter", index=1, shot_image_prompt="saved prompt", image_url="saved-shot.png", video_url="saved-shot.mp4", keyframes='[{"prompt":"saved keyframe"}]'),
    ]
    s.db.add_all(saved_assets)
    s.db.commit()
    old = snapshot(legacy_rows)
    protected = snapshot(customs + [other_type] + novels + saved_assets)
    before_selection = [s.builder.get_style(s.db, novel)[1].id for novel in novels]
    fallback_id = s.builder.get_style(s.db)[1].id
    assert fallback_id == legacy_rows[earliest_style].id

    s.service.init_system_templates()
    s.db.expire_all()
    assert len(s.service.list_templates("style")) == 12 + 13
    assert s.db.query(s.template).count() == len(legacy_rows) + len(customs) + 1 + 9
    assert snapshot(customs + [other_type] + novels + saved_assets) == protected
    catalog_by_key = {(data["name"], data["type"]): data for data in s.catalog.SYSTEM_PROMPT_TEMPLATES}
    for row in legacy_rows:
        for field in ("id", "name", "type", "is_system", "is_active", "created_at"):
            assert getattr(row, field) == old[row.id][field]
        assert row.template == catalog_by_key[(row.name, row.type)]["template"]
        assert row.description == catalog_by_key[(row.name, row.type)]["description"]
    for style_type in ("character", "scene", "prop"):
        assert [s.builder.get_style(s.db, novel, style_type)[1].id for novel in novels] == before_selection
        assert s.builder.get_style(s.db, style_type=style_type)[1].id == fallback_id
    assert s.builder.get_style(s.db, novels[1])[0] == s.catalog.SYSTEM_STYLE_TEMPLATES[1]["template"]
    assert s.builder.get_style(s.db, novels[4])[0] == customs[0].template
    assert s.builder.get_style(s.db, novels[5])[0] == customs[4].template
    assert s.service.to_response(customs[0])["nameKey"] is None
    assert s.service.to_response(customs[0])["descriptionKey"] is None

    first_upgrade = snapshot(s.db.query(s.template).all())
    s.service.init_system_templates()
    s.db.expire_all()
    assert snapshot(s.db.query(s.template).all()) == first_upgrade
    assert snapshot(customs + [other_type] + novels + saved_assets) == protected
    assert s.builder.get_style(s.db)[1].id == fallback_id


@pytest.mark.parametrize("kind", ["character", "scene", "prop"])
def test_empty_catalog_keeps_existing_literal_fallbacks(isolated, kind):
    builder = isolated.builder
    expected = getattr(builder, f"DEFAULT_{kind.upper()}_STYLE")
    for novel in (None, SimpleNamespace(style_prompt_template_id=None), SimpleNamespace(style_prompt_template_id="missing")):
        assert builder.get_style(isolated.db, novel, kind) == (expected, None)


@pytest.mark.parametrize("style_index", range(12))
@pytest.mark.parametrize("kind", ["character", "scene", "prop"])
def test_builtin_asset_composition_honors_selected_novel_style(isolated, style_index, kind):
    s = isolated
    s.service.init_system_templates()
    selected = next(row for row in s.service.list_templates("style") if row.name == STYLE_NAMES[style_index])
    style, resolved = s.builder.get_style(s.db, SimpleNamespace(style_prompt_template_id=selected.id), kind)
    assert resolved.id == selected.id
    content = {
        "character": "elderly engineer, silver braid, blue space suit, crystal-powered prosthetic hand",
        "scene": "orbital station with enchanted doors, titanium frames and a stone altar",
        "prop": "antique brass pocket watch with a holographic face",
    }[kind]
    files = CHARACTER_FILES if kind == "character" else [f"{kind}.txt"]
    templates = s.service.list_templates(kind)
    assert {row.template for row in templates} == {s.catalog.load_template(filename) for filename in files}
    for row in templates:
        assert row.template.count("##STYLE##") == 1
        assert "proportions" in row.template
        assert "reference" in row.template
        assert "product photography" not in row.template
        assert "photorealistic" not in row.template
        assert "anime style" not in row.template
        prompt = getattr(s.builder, f"build_{kind}_prompt")("Reference", content, template=row.template, style=style)
        assert content in prompt
        assert " ".join(style.split()) in prompt
        assert "##STYLE##" not in prompt
        assert "{appearance}" not in prompt and "{setting}" not in prompt
        if kind == "character":
            assert "single character" in prompt and "centered" in prompt
        elif kind == "scene":
            assert "no characters" in prompt
        else:
            assert "clean background" in prompt
    assert not s.db.dirty and not s.db.new


@pytest.mark.parametrize("kind", ["character", "scene", "prop"])
def test_custom_templates_without_style_placeholder_are_not_appended_to(isolated, kind):
    builder = getattr(isolated.builder, f"build_{kind}_prompt")
    placeholder = "{setting}" if kind == "scene" else "{appearance}"
    template = f"my authored rendering, {placeholder}, keep this exactly"
    for style in isolated.catalog.SYSTEM_STYLE_TEMPLATES:
        assert builder("Reference", "authored detail", template=template, style=style["template"]) == (
            "my authored rendering, authored detail, keep this exactly"
        )
