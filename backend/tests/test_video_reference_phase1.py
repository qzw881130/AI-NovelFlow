import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from app.models.novel import Character, Scene, Prop, Novel, Chapter
from app.models.shot import Shot
from app.models.workflow import Workflow
from app.models.task import Task
from app.services.clip_execution_compiler import (
    compile_generate_clip, compile_extend_clip, compile_temporal_extend_clip,
    TEMPORAL_DECISION_CONTRACT, EARLY_COMPOSITION_CONTRACT,
)
from app.services import shot_video_service as service
from app.services.video_director_ai import build_physical_picture_mapping


@pytest.fixture
def assets(db_session, tmp_path):
    def image(name):
        path = tmp_path / f"{name}.png"
        path.write_bytes(b"local image fixture")
        return str(path)

    novel = Novel(id="n", title="Reference test")
    chapter = Chapter(id="ch", novel_id="n", number=1, title="Chapter")
    rows = [novel, chapter, Scene(id="room-id", novel_id="n", name="Room", image_url=image("room"))]
    rows += [Character(id=f"char-{i}", novel_id="n", name=f"Person{i}", image_url=image(f"person{i}")) for i in range(1, 11)]
    rows += [Prop(id=name, novel_id="n", name=name, existence="REAL", image_url=image(name)) for name in ("Box", "Lamp", "Unused")]
    rows.append(Prop(id="imagined", novel_id="n", name="Imagined", existence="FICTIONAL_OR_NONEXISTENT", image_url=image("imagined")))
    db_session.add_all(rows)
    db_session.commit()
    return image


def fixture(assets, capability="GENERATE", visible=None):
    visible = visible or ["Person1", "Person2"]
    description = "Characters:\n" + "\n".join(f"- {name}: standing" for name in visible) + "\nProps: Box Imagined"
    states = [
        {"index": 1, "role": "START", "time_seconds": 0, "image_url": assets("director"), "description": description},
        {"index": 2, "role": "INTERMEDIATE", "time_seconds": 5, "description": description},
    ]
    clip = {"clip_index": 1 if capability == "GENERATE" else 2, "start_time": 0, "end_time": 8,
            "capability": capability, "visual_state_indexes": [1, 2], "dialogue_assignment": [{"speaker": "Person2"}],
            "continuity_to_previous": "CONTINUOUS", "previous_clip_index": 1,
            "requires_temporal_control": capability == "TEMPORAL_EXTEND"}
    plan = {"canonical_visual_plan": True, "clip_plan_revision": 1, "keyframes": states, "clip_plan": [clip],
            "clip_plan_validation": {"temporal_contract": TEMPORAL_DECISION_CONTRACT, "composition_contract": EARLY_COMPOSITION_CONTRACT},
            "transitions": [{"from_keyframe_index": 1, "to_keyframe_index": 2, "transition_description": "Switch on Lamp"},
                            {"from_keyframe_index": 2, "to_keyframe_index": 3, "transition_description": "Unused"}]}
    shot = Shot(id="s", chapter_id="ch", index=1, duration=8, scene="Room", characters=json.dumps(["Person1", "Person2", "Person3"]),
                props=json.dumps(["Unused", "Lamp", "Box", "Imagined"]), dialogues="[]", video_director_plan=json.dumps(plan))
    return shot, plan, clip


def compile_case(shot, plan, clip, resources, anchors=None):
    previous = {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": "previous-task", "result_url": "/api/files/previous.mp4"}
    if clip["capability"] == "GENERATE":
        return compile_generate_clip(shot, plan, clip, 1, resource_references=resources)
    if clip["capability"] == "EXTEND":
        return compile_extend_clip(shot, plan, clip, 1, previous, resource_references=resources)
    return compile_temporal_extend_clip(shot, plan, clip, 1, previous, anchors, resource_references=resources)


def test_prompt_writer_and_reader_share_canonical_entry():
    canonical = {"clip_index": 2, "start_time": 8, "end_time": 16, "capability": "EXTEND"}
    legacy = {**canonical, "prompt_text": "old legacy"}
    shot = SimpleNamespace(video_director_plan=json.dumps({"clip_plan": [canonical], "clips": [legacy]}))
    service._update_clip_prompt(shot, canonical, "saved final prompt", SimpleNamespace(commit=lambda: None))
    plan = json.loads(shot.video_director_plan)
    assert plan["clip_plan"][0]["prompt_text"] == "saved final prompt"
    assert plan["clips"][0]["prompt_text"] == "old legacy"
    assert service.get_semantic_clip_prompt(plan, plan["clip_plan"][0]) == "saved final prompt"


def test_legacy_compatibility_requires_identical_clip_and_absent_canonical_field():
    clip = {"clip_index": 2, "start_time": 8, "end_time": 16}
    plan = {"clips": [{**clip, "prompt_text": "historical"}]}
    assert service.get_semantic_clip_prompt(plan, clip) == "historical"
    assert service.get_semantic_clip_prompt(plan, {**clip, "prompt_text": "canonical"}) == "canonical"
    assert service.get_semantic_clip_prompt(plan, {**clip, "prompt_text": ""}) == ""
    assert service.get_semantic_clip_prompt(plan, {**clip, "end_time": 20}) == ""
    assert service.get_semantic_clip_prompt(plan, {**clip, "clip_index": 3}) == ""


@pytest.mark.parametrize("capability", ["GENERATE", "EXTEND", "TEMPORAL_EXTEND"])
def test_three_routes_pack_typed_resources_keep_domains_separate(db_session, assets, capability):
    shot, plan, clip = fixture(assets, capability)
    anchors = [{"anchor_id": "anchor", "time_seconds": 5, "image_url": assets("temporal"),
                "source": {"type": "KEYFRAME", "keyframe_index": 2, "id": "KF2"}}]
    original = copy.deepcopy(anchors)
    resources = service.resolve_clip_reference_resources(db_session, "n", shot, plan, clip)
    compiled = compile_case(shot, plan, clip, resources, anchors)
    refs = compiled["video_reference_manifest"]["references"]
    assert [r["kind"] for r in refs] == ["DIRECTOR_VISUAL_ANCHOR", "SCENE", "CHARACTER_IDENTITY", "CHARACTER_IDENTITY", "PROP", "PROP"]
    assert [r.get("source_name") for r in refs] == [None, "Room", "Person2", "Person1", "Box", "Lamp"]
    assert [r["slot"] for r in refs] == list(range(1, 7))
    assert not any(r["image_url"] in ["/api/files/previous.mp4", anchors[0]["image_url"]] for r in refs)
    assert anchors == original
    if capability != "GENERATE":
        assert compiled["execution_contract"]["previous_clip"]["generated_by_task_id"] == "previous-task"
    if capability == "TEMPORAL_EXTEND":
        without_resources = compile_case(shot, plan, clip, None, anchors)
        assert compiled["execution_contract"]["temporal_anchor_manifest"] == without_resources["execution_contract"]["temporal_anchor_manifest"]
    mapping = build_physical_picture_mapping(compiled["video_reference_manifest"])
    assert [m["picture_index"] for m in mapping] == [r["slot"] for r in refs]
    assert mapping[2]["source_identity"] == {"asset_id": "char-2", "name": "Person2"}
    assert mapping[2]["source_name"] == "Person2"


def test_budget_preserves_directors_scene_and_speakers_before_other_characters(db_session, assets):
    shot, plan, clip = fixture(assets, visible=[f"Person{i}" for i in range(1, 11)])
    plan["keyframes"][1]["image_url"] = assets("director2")
    clip["dialogue_assignment"] = [{"speaker": "Person10"}, {"speaker": "Person9"}]
    resources = service.resolve_clip_reference_resources(db_session, "n", shot, plan, clip)
    manifest = compile_case(shot, plan, clip, resources)["video_reference_manifest"]
    assert len(resources["references"]) == 13  # Scene + ten identities + two relevant props
    assert len(manifest["references"]) == 9
    assert [r["kind"] for r in manifest["references"][:3]] == ["DIRECTOR_VISUAL_ANCHOR", "DIRECTOR_VISUAL_ANCHOR", "SCENE"]
    assert [r["source_name"] for r in manifest["references"][3:]] == ["Person9", "Person10", "Person1", "Person2", "Person3", "Person4"]
    assert all(r["kind"] == "CHARACTER_IDENTITY" for r in manifest["references"][3:])
    assert [r["slot"] for r in manifest["references"]] == list(range(1, 10))
    assert [r["source_name"] for r in manifest["skipped_references"] if r["reason"] == "ORDINARY_REFERENCE_BUDGET"] == ["Person5", "Person6", "Person7", "Person8", "Box", "Lamp"]
    assert manifest == compile_case(shot, plan, clip, service.resolve_clip_reference_resources(db_session, "n", shot, plan, clip))["video_reference_manifest"]


def test_missing_optional_images_soft_skip_without_phantom_slots(db_session, assets):
    shot, plan, clip = fixture(assets)
    db_session.query(Scene).one().image_url = None
    db_session.query(Character).filter_by(name="Person2").one().image_url = "/api/files/missing.png"
    db_session.query(Prop).filter_by(name="Box").one().image_url = None
    db_session.commit()
    resources = service.resolve_clip_reference_resources(db_session, "n", shot, plan, clip)
    manifest = compile_case(shot, plan, clip, resources)["video_reference_manifest"]
    assert [r.get("source_name") for r in manifest["references"]] == [None, "Person1", "Lamp"]
    assert [r["slot"] for r in manifest["references"]] == [1, 2, 3]
    assert {r["source_name"]: r["reason"] for r in manifest["skipped_references"]} == {
        "Room": "IMAGE_MISSING", "Person2": "IMAGE_UNRESOLVABLE", "Box": "IMAGE_MISSING", "Imagined": "NOT_VISUAL_ELIGIBLE"}


def test_character_fallback_and_transition_scope(db_session, assets):
    shot, plan, clip = fixture(assets, "EXTEND")
    plan["keyframes"][0]["description"] = "Box"
    plan["keyframes"][1]["description"] = "Nothing changes"
    refs = service.resolve_clip_reference_resources(db_session, "n", shot, plan, clip)["references"]
    assert [r["source_name"] for r in refs] == ["Room", "Person2", "Person1", "Person3", "Box", "Lamp"]
    clip["visual_state_indexes"] = [2]
    clip["carry_in_state_index"] = 1
    refs = service.resolve_clip_reference_resources(db_session, "n", shot, plan, clip)["references"]
    assert [r["source_name"] for r in refs if r["kind"] == "PROP"] == ["Lamp"]


def test_unknown_assets_and_narrator_are_optional_not_phantom_pictures(db_session, assets):
    shot, plan, clip = fixture(assets, visible=["Unknown", "Person1"])
    shot.scene = "Missing Room"
    db_session.query(Character).filter_by(name="Person1").one().is_narrator = True
    db_session.commit()
    resources = service.resolve_clip_reference_resources(db_session, "n", shot, plan, clip)
    manifest = compile_case(shot, plan, clip, resources)["video_reference_manifest"]
    assert [r["kind"] for r in manifest["references"]] == ["DIRECTOR_VISUAL_ANCHOR", "PROP", "PROP"]
    assert [r["slot"] for r in manifest["references"]] == [1, 2, 3]
    assert {r["source_name"]: r["reason"] for r in manifest["skipped_references"]} == {
        "Missing Room": "ASSET_NOT_FOUND", "Unknown": "ASSET_NOT_FOUND",
        "Person1": "NARRATOR_NOT_VISUAL", "Imagined": "NOT_VISUAL_ELIGIBLE"}


@pytest.mark.parametrize("capability", ["GENERATE", "EXTEND", "TEMPORAL_EXTEND"])
def test_api_manifest_worker_recompile_h3_and_upload_order_agree(db_session, assets, monkeypatch, capability):
    from app.api import shots as api
    from app.repositories import NovelRepository, ChapterRepository, TaskRepository, ShotRepository

    shot, plan, clip = fixture(assets, capability)
    # The chain uses canonical readiness and physical files; only Previous AV probing is mocked.
    anchors = [{"anchor_id": "clip-2-KF2", "time_seconds": 5, "image_url": assets("temporal"),
                "source": {"type": "KEYFRAME", "keyframe_index": 2, "id": "KF2"}}]
    if capability == "TEMPORAL_EXTEND":
        plan["temporal_anchors"] = anchors
        clip["temporal_anchor_ids"] = ["clip-2-KF2"]
        clip["selected_temporal_target_ids"] = ["KF2"]
    shot.video_director_plan = json.dumps(plan)
    workflow_id = {"GENERATE": "g", "EXTEND": api.EXTEND_WORKFLOW_ID, "TEMPORAL_EXTEND": api.TEMPORAL_EXTEND_WORKFLOW_ID}[capability]
    workflow_type = {"GENERATE": "multi_reference_video", "EXTEND": "VIDEO_CONTINUATION", "TEMPORAL_EXTEND": "TEMPORAL_EXTEND"}[capability]
    workflow = Workflow(id=workflow_id, name="Mock workflow", type=workflow_type, workflow_json="{}", node_mapping="{}", is_active=True)
    db_session.add_all([shot, workflow]); db_session.commit()
    captured = {}
    monkeypatch.setattr(api.TaskService, "validate_workflow_node_mapping", lambda *_: (True, ""))
    monkeypatch.setattr(api, "enqueue_shot_video_task", lambda *args, **kwargs: captured.update(enqueue=(args, kwargs)))
    previous = {"clip_index": 1, "clip_plan_revision": 1, "generated_by_task_id": "prev", "result_url": assets("previous-av"), "local_path": assets("previous-av")}
    monkeypatch.setattr(api, "resolve_extend_previous_av", lambda *_: previous)
    monkeypatch.setattr(service, "resolve_extend_previous_av", lambda *_: previous)
    response = asyncio.run(api._execute_phase_b_semantic_clip(
        "n", "ch", "s", clip["clip_index"], api.SemanticClipGenerateRequest(clip_plan_revision=1, auto_merge=False),
        db_session, NovelRepository(db_session), ChapterRepository(db_session), TaskRepository(db_session), ShotRepository(db_session)))
    assert response["success"]
    args, kwargs = captured["enqueue"]
    task = db_session.query(Task).filter_by(id=args[0]).one()
    initial = json.loads(task.metadata_json)["video_reference_manifest"]

    async def fake_h3(**kwargs):
        captured["h3"] = copy.deepcopy(kwargs["video_reference_manifest"])
        return "final H3 prompt"

    class MockComfy:
        async def generate_shot_video_with_workflow(self, **kwargs):
            captured["physical"] = kwargs
            return {"success": False, "error": "mock stop before any generation"}

        async def generate_video_continuation_with_workflow(self, **kwargs):
            captured["physical"] = kwargs
            return {"success": False, "error": "mock stop before any generation"}

    monkeypatch.setattr(service, "build_h3_video_prompt", fake_h3)
    monkeypatch.setattr(service, "ComfyUIService", MockComfy)
    monkeypatch.setattr(service, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    asyncio.run(service.generate_shot_video_task(*args, **kwargs))
    assert "physical" in captured, task.error_message
    worker = captured["h3"]
    assert [{k: v for k, v in r.items() if k != "local_path"} for r in initial["references"]] == [{k: v for k, v in r.items() if k != "local_path"} for r in worker["references"]]
    assert captured["physical"]["reference_image_paths"] == [r["local_path"] for r in worker["references"]]
    assert [r["url"] for r in json.loads(task.reference_images)] == [r["image_url"] for r in worker["references"]]
    assert "CHARACTER_IDENTITY" in json.loads(task.reference_images)[2]["label"]
    assert len(build_physical_picture_mapping(worker)) == len(captured["physical"]["reference_image_paths"])
    assert json.loads(shot.video_director_plan)["clip_plan"][0]["prompt_text"] == "final H3 prompt"
    if capability == "TEMPORAL_EXTEND":
        assert [a["image_path"] for a in captured["physical"]["anchors"]] == [anchors[0]["image_url"]]


def test_saved_prompt_reaches_formal_api_reuse_metadata(db_session, assets, monkeypatch):
    from app.api import shots as api
    from app.repositories import NovelRepository, ChapterRepository, TaskRepository, ShotRepository
    shot, plan, clip = fixture(assets)
    shot.video_director_plan = json.dumps(plan)
    db_session.add_all([shot, Workflow(id="g", name="mock", type="multi_reference_video", workflow_json="{}", node_mapping="{}", is_active=True)])
    db_session.commit()
    service._update_clip_prompt(shot, clip, "exact saved prompt", db_session)
    captured = {}
    monkeypatch.setattr(api.TaskService, "validate_workflow_node_mapping", lambda *_: (True, ""))
    monkeypatch.setattr(api, "enqueue_shot_video_task", lambda *args, **kwargs: captured.update(kwargs))
    asyncio.run(api._execute_phase_b_semantic_clip(
        "n", "ch", "s", 1, api.SemanticClipGenerateRequest(clip_plan_revision=1, skip_llm_when_prompt_exists=True),
        db_session, NovelRepository(db_session), ChapterRepository(db_session), TaskRepository(db_session), ShotRepository(db_session)))
    assert captured["clip_metadata"]["prompt_text"] == "exact saved prompt"
    assert captured["skip_llm_when_prompt_exists"] is True
