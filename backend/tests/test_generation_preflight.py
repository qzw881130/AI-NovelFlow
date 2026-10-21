import json

import pytest

from app.api import shots as shot_api
from app.models.novel import Chapter, Character, Novel
from app.models.shot import Shot
from app.models.task import Task
from app.repositories.character_repository import CharacterRepository
from app.repositories import NovelRepository, ChapterRepository, ShotRepository
from app.services.generation_preflight import catalog, evaluate_batch, normalize_policy


def seed(db):
    novel = Novel(id="preflight-novel", title="preflight")
    chapter = Chapter(id="preflight-chapter", novel_id=novel.id, number=1, title="chapter")
    shot = Shot(id="preflight-shot", chapter_id=chapter.id, index=1, duration=10,
                image_url="/api/files/shot.png", characters='["华老栓"]',
                video_director_plan=json.dumps({"clip_plan_revision": 1,
                    "clip_plan_validation": {"passed": True},
                    "clip_plan": [{"clip_index": 1, "capability": "GENERATE"}]}))
    db.add_all([novel, chapter, shot])
    db.commit()
    return novel, chapter, shot


def test_identity_features_are_saved_once_and_manual_value_wins(db_session):
    novel, _, _ = seed(db_session)
    repo = CharacterRepository(db_session)
    character = repo.create(novel.id, "华老栓", appearance="稳定识别特征是左眉尾浅痣、瘦长脸。基础服装为黑衣。")
    assert character.stable_identity_features == "左眉尾浅痣、瘦长脸"
    assert character.stable_identity_source == "APPEARANCE_CLAUSE"
    character = repo.update(character, stable_identity_features="右眼下浅痣")
    assert character.stable_identity_features == "右眼下浅痣"
    assert character.stable_identity_source == "MANUAL"
    character = repo.update(character, appearance="稳定识别特征是浓眉。新衣服为蓝色。")
    assert character.stable_identity_features == "右眼下浅痣"


def test_batch_preflight_reports_soft_checks_and_rejects_only_enabled_policy(db_session):
    novel, chapter, shot = seed(db_session)
    db_session.add(Character(novel_id=novel.id, name="华老栓", appearance="普通外貌描述"))
    db_session.add(Task(type="shot_video", name="finished clip", status="completed",
                        shot_id=shot.id, execution_scope="CLIP", clip_index=1,
                        parent_task_id="old-batch"))
    db_session.commit()
    default = evaluate_batch(db_session, chapter.id, [shot.id])
    assert default["ready"] is True
    missing = {item["id"]: item for item in default["checks"] if item["status"] == "FAIL"}
    assert set(missing) == {"IDENTITY_FEATURES_RECORDED", "IDENTITY_PORTRAIT_READY"}
    assert not any(item["blocking"] for item in missing.values())
    strict = evaluate_batch(db_session, chapter.id, [shot.id], policy={"IDENTITY_FEATURES_RECORDED": True})
    assert strict["ready"] is False
    assert next(item for item in strict["checks"] if item["id"] == "IDENTITY_FEATURES_RECORDED")["blocking"]
    assert all(item["blocking"] for item in catalog() if not item["configurable"])
    with pytest.raises(ValueError):
        normalize_policy({"SHOT_IMAGE_READY": False})


def test_catalog_lists_runtime_gates_without_pretending_batch_evaluated_them(db_session):
    _, chapter, shot = seed(db_session)
    all_checks = catalog()
    ids = {item['id'] for item in all_checks}
    assert {'PHASE_B_SOURCE_BINDING', 'PHASE_B_DIRECTOR_SCHEMA', 'PHASE_B_TIMING_ANCHORS',
            'PHASE_B_LANGUAGE_CONSISTENCY', 'PHASE_B_PROMPT_STRUCTURE',
            'PHASE_B_PICTURE_BINDING', 'PHASE_B_WORKFLOW_BINDING',
            'VIDEO_OUTPUT_ARTIFACT', 'CLIP_ASSEMBLY_PROVENANCE'} <= ids
    language = next(item for item in all_checks if item['id'] == 'PHASE_B_LANGUAGE_CONSISTENCY')
    assert language['stage'] == 'director' and language['configurable'] and not language['blocking']
    assert next(item for item in catalog({'PHASE_B_LANGUAGE_CONSISTENCY': True})
                if item['id'] == 'PHASE_B_LANGUAGE_CONSISTENCY')['blocking']
    report = evaluate_batch(db_session, chapter.id, [shot.id])
    assert all(item['id'] not in {entry['id'] for entry in report['checks']}
               for item in all_checks if item['stage'] != 'before_queue')


def test_language_gate_policy_is_saved_and_exposed_in_settings(client):
    response = client.post('/api/config/', json={
        'generationQualityPolicy': {'PHASE_B_LANGUAGE_CONSISTENCY': True},
    })
    assert response.status_code == 200, response.text
    data = client.get('/api/config/generation-checks').json()['data']
    assert data['policy']['PHASE_B_LANGUAGE_CONSISTENCY'] is True
    language = next(item for item in data['checks'] if item['id'] == 'PHASE_B_LANGUAGE_CONSISTENCY')
    assert language['blocking'] is True and language['stage'] == 'director'


@pytest.mark.asyncio
async def test_batch_preflight_rejects_entire_batch_before_creating_tasks(db_session):
    novel, chapter, shot = seed(db_session)
    missing_image = Shot(id="missing-image", chapter_id=chapter.id, index=2, duration=10,
                         video_director_plan="{}")
    db_session.add(missing_image)
    db_session.commit()
    report = evaluate_batch(db_session, chapter.id, [shot.id, missing_image.id], auto_prepare=True)
    assert report["ready"] is False
    assert any(item["id"] == "SHOT_IMAGE_READY" and item["shotId"] == missing_image.id
               and item["blocking"] for item in report["checks"])
    with pytest.raises(shot_api.HTTPException) as error:
        await shot_api.generate_shot_videos_batch(
            novel.id, chapter.id,
            shot_api.BatchShotVideoRequest(shot_ids=[shot.id, missing_image.id], auto_complete_details=True),
            db_session, NovelRepository(db_session), ChapterRepository(db_session), ShotRepository(db_session))
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "GENERATION_PREFLIGHT_FAILED"
    assert db_session.query(Task).count() == 0


@pytest.mark.asyncio
async def test_failed_batch_resume_preserves_completed_shot(db_session, monkeypatch):
    _, chapter, shot = seed(db_session)
    second = Shot(id="preflight-shot-2", chapter_id=chapter.id, index=2, duration=10,
                  image_url="/api/files/shot2.png", video_director_plan="{}")
    batch = Task(id="preflight-batch", type="shot_video_batch", execution_scope="BATCH",
                 name="batch", status="failed", novel_id="preflight-novel", chapter_id=chapter.id,
                 metadata_json=json.dumps({"auto_complete_details": True}))
    done = Task(id="preflight-done", type="shot_video", execution_scope="SHOT",
                name="done", status="completed", novel_id="preflight-novel", chapter_id=chapter.id,
                shot_id=shot.id, parent_task_id=batch.id, batch_order=1,
                result_url="/api/files/done.mp4")
    failed = Task(id="preflight-failed", type="shot_video", execution_scope="SHOT",
                  name="failed", status="failed", novel_id="preflight-novel", chapter_id=chapter.id,
                  shot_id=second.id, parent_task_id=batch.id, batch_order=2,
                  error_message="pre-submit error", metadata_json="{}")
    db_session.add_all([second, batch, done, failed])
    db_session.commit()
    queued = []
    monkeypatch.setattr(shot_api, "enqueue_shot_video_batch_task", queued.append)
    response = await shot_api.resume_shot_video_batch("preflight-novel", chapter.id, batch.id, db_session)
    assert response["success"] and queued == [batch.id]
    assert done.status == "completed" and done.result_url == "/api/files/done.mp4"
    assert failed.status == "pending" and failed.error_message is None
    assert batch.status == "pending"
