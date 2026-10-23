"""Selected stable IDs and asset versions must describe the actual reference pixels."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from app.models.novel import Novel, Chapter, Character, Scene, Prop
from app.models.shot import Shot
from app.models.task import Task
from app.models.workflow import Workflow
from app.services.comfyui.workflows import WorkflowBuilder
from app.services.file_storage import FileStorageService
from app.services.shot_keyframe_service import ShotKeyframeService, _project_keyframe_reference_context
from app.utils.image_utils import merge_character_images
import app.services.shot_keyframe_service as service_module
import app.utils.image_utils as image_module


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def refs(db_session, tmp_path, monkeypatch):
    storage = FileStorageService(str(tmp_path))

    def to_path(url):
        if not url or not url.startswith("/api/files/"):
            return None
        path = tmp_path / url.removeprefix("/api/files/")
        return str(path) if path.exists() else None

    def to_url(path):
        return "/api/files/" + str(Path(path).relative_to(tmp_path))

    def asset(name, color):
        path = tmp_path / (name + ".png")
        Image.new("RGB", (80, 96), color).save(path)
        return to_url(path)

    monkeypatch.setattr(service_module, "file_storage", storage)
    monkeypatch.setattr(service_module, "url_to_local_path", to_path)
    monkeypatch.setattr(service_module, "local_path_to_url", to_url)
    novel = Novel(id="novel-characters", title="reference members")
    chapter = Chapter(id="chapter-characters", novel_id=novel.id, number=1, title="chapter")
    names = ["仆人1", "仆人2", "仆人3", "骗子1", "骗子2"]
    characters = [Character(id=f"character-{i}", novel_id=novel.id, name=name,
                            image_url=asset(f"character-{i}", (30 + i * 40, 60, 90)))
                  for i, name in enumerate(names)]
    shot = Shot(id="shot-characters", chapter_id=chapter.id, index=4,
                characters=json.dumps(names), scene="", props="[]", keyframes="[]")
    db_session.add_all([novel, chapter, *characters, shot])
    db_session.commit()
    legacy = merge_character_images(novel.id, chapter.id, shot.index,
                                    [(c.name, to_path(c.image_url)) for c in characters], storage)
    shot.merged_character_image = to_url(legacy)
    db_session.commit()
    service = ShotKeyframeService()

    def candidates(visible=None):
        visible = characters if visible is None else visible
        frame = {"description": "Characters:\n" + "\n".join(f"- {c.name}: listening" for c in visible) + "\nAction: wait"}
        return service._build_reference_candidates(db_session, novel, shot, [frame], 0)

    def resolve(chosen, available=None):
        available = candidates() if available is None else available
        selected = {"selected_references": [{"type": "CHARACTER_IDENTITY",
                    "ref_ids": [f"CHAR:{c.id}" for c in chosen], "purpose": "identity"}]}
        return service._resolve_reference_manifest(db_session, novel, shot, selected, available)

    return SimpleNamespace(**locals())


def assert_panels(item, selected, refs):
    with Image.open(item["path"]) as im:
        for i, c in enumerate(sorted(selected, key=lambda c: c.id)):
            # The existing merger places <=3 people in one column, unchanged pixels.
            y = 59 + i * (96 + 44)
            with Image.open(refs.to_path(c.image_url)) as source:
                assert im.crop((15, y, 95, y + 96)).tobytes() == source.tobytes()


@pytest.mark.parametrize("count", [2, 3])
def test_only_selected_members_are_merged_and_shot_cache_survives(refs, count):
    chosen = refs.characters[-count:]
    original_hash = digest(refs.legacy)
    item = refs.resolve(chosen)[0]
    assert item["character_ids"] == sorted(c.id for c in chosen)
    assert item["members"] == [c.name for c in sorted(chosen, key=lambda c: c.id)]
    assert item["path"] != refs.legacy and item["composed"]
    assert_panels(item, chosen, refs)
    assert digest(refs.legacy) == original_hash
    assert refs.shot.merged_character_image == refs.to_url(refs.legacy)
    projected = _project_keyframe_reference_context([item])[0]
    assert projected["members"] == item["members"] and projected["character_ids"] == item["character_ids"]
    assert "character_assets" not in projected  # Files/hashes are audit data, not Prompt rules.


def test_single_member_binds_selected_image_without_merge(refs, monkeypatch):
    monkeypatch.setattr(service_module, "merge_character_images", Mock(side_effect=AssertionError("must not merge")))
    c = refs.characters[3]
    item = refs.resolve([c])[0]
    assert item["url"] == c.image_url and item["path"] == refs.to_path(c.image_url)
    assert item["character_ids"] == [c.id] and not item["composed"]


def test_different_members_never_reuse_previous_state_cache(refs):
    first = refs.resolve(refs.characters[3:])[0]
    before = digest(first["path"])
    second = refs.resolve(refs.characters[:2])[0]
    assert first["path"] != second["path"]
    assert digest(first["path"]) == before
    assert_panels(second, refs.characters[:2], refs)
    # A later ordinary Shot merge must not delete keyframe cache variants.
    merge_character_images(refs.novel.id, refs.chapter.id, refs.shot.index,
                           [(c.name, refs.to_path(c.image_url)) for c in refs.characters], refs.storage)
    assert digest(first["path"]) == before and Path(second["path"]).is_file()


def test_same_members_new_selected_image_version_uses_new_cache(refs):
    selected = refs.characters[3:]
    old_candidates = refs.candidates()
    first = refs.resolve(selected, old_candidates)[0]
    original_hash = digest(first["path"])
    # Appearance/portrait image changes use the selected version, not a fixed experiment asset.
    selected[0].image_url = refs.asset("new-costume-version", (10, 230, 10))
    refs.db_session.commit()
    second = refs.resolve(selected)[0]
    assert first["path"] != second["path"]
    assert digest(first["path"]) == original_hash
    assert_panels(second, selected, refs)
    # An already-selected historical snapshot still resolves to its original image.
    assert refs.resolve(selected, old_candidates)[0]["path"] == first["path"]


def test_changed_file_at_same_url_invalidates_asset_version(refs):
    chosen = refs.characters[3:]
    snapshot = refs.candidates()
    first = refs.resolve(chosen, snapshot)[0]
    Image.new("RGB", (80, 96), "cyan").save(refs.to_path(chosen[0].image_url))
    with pytest.raises(ValueError, match="版本已变化"):
        refs.resolve(chosen, snapshot)
    second = refs.resolve(chosen)[0]
    assert second["path"] != first["path"]


def test_identical_members_and_assets_reuse_cache_even_with_reversed_order(refs, monkeypatch):
    chosen = refs.characters[3:]
    first = refs.resolve(chosen)[0]
    stat = Path(first["path"]).stat().st_mtime_ns
    monkeypatch.setattr(image_module, "_merge_labeled_images", Mock(side_effect=AssertionError("cache should be reused")))
    second = refs.resolve(chosen[::-1])[0]
    assert second["path"] == first["path"]
    assert Path(second["path"]).stat().st_mtime_ns == stat


def test_cache_without_matching_provenance_is_not_blindly_reused(refs, monkeypatch):
    chosen = refs.characters[3:]
    item = refs.resolve(chosen)[0]
    metadata = Path(item["path"]).with_suffix(".json")
    data = json.loads(metadata.read_text())
    data["identity"]["members"][0]["character_id"] = refs.characters[0].id
    metadata.write_text(json.dumps(data))
    original = image_module._merge_labeled_images
    spy = Mock(wraps=original)
    monkeypatch.setattr(image_module, "_merge_labeled_images", spy)
    refs.resolve(chosen)
    assert spy.call_count == 1
    assert json.loads(metadata.read_text())["identity"]["members"][0]["character_id"] == chosen[0].id


def test_historical_task_manifest_prompt_and_output_are_not_modified(refs):
    output = refs.asset("historical-output", "orange")
    historical = Task(id="historical", type="keyframe_image", name="old KF", status="completed",
                      shot_id=refs.shot.id, prompt_text="old prompt", result_url=output,
                      metadata_json=json.dumps({"reference_manifest": [{"path": refs.legacy, "sources": ["CHAR:骗子1", "CHAR:骗子2"]}]}),
                      workflow_json='{"510":{"inputs":{"image":"old.png"}}}')
    refs.db_session.add(historical)
    refs.db_session.commit()
    before = {c.name: getattr(historical, c.name) for c in Task.__table__.columns}
    legacy_hash, output_hash = digest(refs.legacy), digest(refs.to_path(output))
    refs.resolve(refs.characters[3:])
    refs.db_session.refresh(historical)
    assert before == {c.name: getattr(historical, c.name) for c in Task.__table__.columns}
    assert digest(refs.legacy) == legacy_hash and digest(refs.to_path(output)) == output_hash


def test_stable_id_selection_survives_display_name_change(refs):
    c = refs.characters[3]
    candidates = refs.candidates()
    c.name = "updated display name"
    refs.db_session.commit()
    item = refs.resolve([c], candidates)[0]
    assert item["character_ids"] == [c.id] and item["url"] == c.image_url
    assert item["members"] == ["骗子1"]  # The selected snapshot's label.


def test_explicit_character_block_does_not_fuzzily_include_similar_names(refs):
    c = refs.characters[0]
    c.name = "骗子10"
    refs.db_session.commit()
    refs.shot.characters = json.dumps([x.name for x in refs.characters])
    candidates = refs.candidates([c])
    assert [x["character_id"] for x in candidates] == [c.id]


def test_duplicate_legacy_names_fail_instead_of_picking_arbitrary_identity(refs):
    refs.db_session.add(Character(id="duplicate", novel_id=refs.novel.id, name="骗子1", image_url=refs.characters[3].image_url))
    refs.db_session.commit()
    with pytest.raises(ValueError, match="无法唯一解析"):
        refs.candidates()


def test_missing_selected_asset_does_not_silently_drop_a_member(refs):
    chosen = refs.characters[3:]
    snapshot = refs.candidates()
    Path(refs.to_path(chosen[0].image_url)).unlink()
    with pytest.raises(ValueError, match="图片不存在"):
        refs.resolve(chosen, snapshot)


def test_other_reference_types_and_picture_order_are_preserved(refs):
    refs.shot.image_url = refs.asset("shot", "white")
    previous = {"plan_keyframe_index": 5, "time_seconds": 13.5,
                "image_url": refs.asset("previous-kf", "purple"), "description": "previous"}
    refs.shot.keyframes = json.dumps([previous])
    scene = Scene(novel_id=refs.novel.id, name="workroom", image_url=refs.asset("scene", "gray"))
    prop = Prop(novel_id=refs.novel.id, name="chest", image_url=refs.asset("prop", "brown"), existence="REAL")
    refs.db_session.add_all([scene, prop]); refs.db_session.commit()
    refs.shot.scene = scene.name; refs.shot.props = json.dumps([prop.name])
    current = {"description": "Scene: workroom\nCharacters:\n- 骗子1: by chest\n- 骗子2: standing\nAction: chest open"}
    candidates = refs.service._build_reference_candidates(refs.db_session, refs.novel, refs.shot, [previous, current], 1)
    groups = [("DIRECTOR_VISUAL_ANCHOR", ["SHOT_IMAGE"]), ("CHARACTER_IDENTITY", [f"CHAR:{c.id}" for c in refs.characters[3:]]),
              ("SCENE", ["SCENE:workroom"]), ("PROP", ["PROP:chest"]), ("TEMPORAL_ANCHOR", ["KF5"])]
    selected = {"selected_references": [{"type": kind, "ref_ids": ids} for kind, ids in groups]}
    manifest = refs.service._resolve_reference_manifest(refs.db_session, refs.novel, refs.shot, selected, candidates)
    assert [x["picture"] for x in manifest] == [1, 2, 3, 4, 5]
    assert [x["type"] for x in manifest] == [x[0] for x in groups]
    assert [manifest[i]["url"] for i in (0, 2, 3, 4)] == [refs.shot.image_url, scene.image_url, prop.image_url, previous["image_url"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("change_after_selection", [False, True])
async def test_worker_upload_and_workflow_binding_follow_selected_manifest(refs, monkeypatch, change_after_selection):
    refs.shot.image_url = refs.asset("main-shot", "white")
    refs.shot.keyframes = json.dumps([{"frame_index": 0, "plan_keyframe_index": 6, "time_seconds": 24.25,
        "description": "Characters:\n- 骗子1: crouching\n- 骗子2: standing", "reference_mode": "auto_select"}])
    raw_workflow = {
        "1": {"class_type": "CR Prompt Text", "inputs": {"prompt": "old"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "old-shot.png"}},
        "3": {"class_type": "LoadImage", "inputs": {"image": "old-five-characters.png"}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {"prompt": ["1", 0], "images.image_1": ["2", 0], "images.image_2": ["3", 0]}},
    }
    workflow = Workflow(name="任意数量参考图", type="multi_image_edit", is_active=True,
                        workflow_json=json.dumps(raw_workflow), node_mapping=json.dumps({
                            "prompt_node_id": "1", "load_image_node_1": "2", "load_image_node_2": "3"}))
    task = Task(name="new isolated test KF", type="keyframe_image", status="pending", shot_id=refs.shot.id,
                novel_id=refs.novel.id, chapter_id=refs.chapter.id)
    refs.db_session.add_all([workflow, task]); refs.db_session.commit()
    seen = {}

    async def select(db, novel, shot, frame, candidates):
        return {"available_references": candidates}, "saved selector", {"selected_references": [
            {"type": "DIRECTOR_VISUAL_ANCHOR", "ref_ids": ["SHOT_IMAGE"]},
            {"type": "CHARACTER_IDENTITY", "ref_ids": [f"CHAR:{c.id}" for c in refs.characters[3:]]},
        ]}

    async def prompt(*args, reference_manifest, **kwargs):
        seen["manifest"] = reference_manifest
        if change_after_selection:
            Image.new("RGB", (80, 96), "pink").save(reference_manifest[1]["path"])
        return "<image_1> scene; <image_2> 骗子1 and 骗子2."

    class Submitted(Exception):
        pass

    async def upload(path):
        seen.setdefault("uploads", []).append(path)
        return {"success": True, "filename": Path(path).name}

    async def queue(submitted):
        seen["workflow"] = submitted
        raise Submitted  # Do not submit any real job in a unit test.

    monkeypatch.setattr(refs.service, "_select_references", select)
    monkeypatch.setattr(refs.service, "_build_qwen_keyframe_prompt", prompt)
    monkeypatch.setattr(service_module, "ComfyUIService", lambda: SimpleNamespace(
        builder=WorkflowBuilder(), client=SimpleNamespace(upload_image=upload, queue_prompt=queue)))
    expected = ValueError if change_after_selection else Submitted
    with pytest.raises(expected):
        await refs.service._generate_keyframe_image_task(refs.db_session, task.id, refs.shot.id, 0, workflow.id)
    if change_after_selection:
        assert "workflow" not in seen
        assert seen["uploads"] == [seen["manifest"][0]["path"]]
        return
    manifest = seen["manifest"]
    assert seen["uploads"] == [x["path"] for x in manifest]
    assert seen["workflow"]["3"]["inputs"]["image"] == Path(manifest[1]["path"]).name
    assert seen["workflow"]["2"]["inputs"]["image"] == Path(manifest[0]["path"]).name
    assert seen["workflow"]["4"] == raw_workflow["4"]
    recorded = json.loads(task.metadata_json)["submitted_reference_bindings"][1]
    assert recorded["character_ids"] == [c.id for c in refs.characters[3:]]
    assert recorded["sha256"] == digest(manifest[1]["path"])
