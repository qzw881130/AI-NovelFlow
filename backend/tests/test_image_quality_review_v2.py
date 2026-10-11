"""Completion integration and per-result quality, without ComfyUI or real LLMs."""
import asyncio
import json
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.orm import sessionmaker
from app.models.image_quality_review import ImageQualityReview
from app.models.prompt_template import PromptTemplate
from app.models.system_config import SystemConfig
from app.services.image_quality_review import create_image_review, current_image_reviews, execute_image_review, review_image_task
from app.services.image_review_worker import enqueue_automatic_review, image_generation_completed, process_review_queue
from test_image_quality_review import _task, _response

@pytest.fixture
def setup_review(db_session):
    task = _task(db_session)
    config = db_session.get(SystemConfig, "default")
    if config:
        config.auto_image_review_enabled = True
    else:
        db_session.add(SystemConfig(id="default", auto_image_review_enabled=True))
    db_session.add_all([
        PromptTemplate(id="v2-template", name="#15 AI 图片质量评审", type="image_quality_review_prompt", template="registered v15", is_system=True, is_active=True),
    ])
    db_session.commit()
    return task

def status(db, task):
    return current_image_reviews(db, [{"taskId": task.id, "imageUrl": task.result_url}])[0]["qualityStatus"]

class FakeLLM:
    provider, model = "test", "vision"
    async def chat_completion(self, **kwargs):
        return {"success": True, "content": _response(), "log_id": None}

@pytest.fixture
def fake_llm():
    with patch("app.services.image_quality_review.vision_proxy", side_effect=lambda url, **kw: {**kw, "url": url}), patch("app.services.image_quality_review.LLMService", FakeLLM):
        yield

def test_completed_event_enqueues_once_and_fail_does_not_change_generation(db_session, setup_review, fake_llm):
    task = setup_review
    with patch("app.services.image_review_worker.SessionLocal", sessionmaker(bind=db_session.bind)):
        image_generation_completed(task.id)
        image_generation_completed(task.id)
    assert db_session.query(ImageQualityReview).count() == 1
    assert status(db_session, task) == "PENDING"
    result = asyncio.run(process_review_queue(db_session))
    assert result.overall == "FAIL" and status(db_session, task) == "FAIL"
    assert asyncio.run(process_review_queue(db_session)) is None
    db_session.refresh(task)
    assert task.status == "completed" and task.result_url == "/api/files/generated.png"

def test_completion_persistence_error_is_contained(db_session, setup_review):
    with patch("app.services.image_review_worker.SessionLocal", side_effect=RuntimeError("db unavailable")):
        assert image_generation_completed(setup_review.id) is None
    db_session.refresh(setup_review)
    assert setup_review.status == "completed"

def test_old_review_finishing_after_regeneration_never_updates_new_image(db_session, setup_review, fake_llm):
    task = setup_review
    old = enqueue_automatic_review(db_session, task.id)
    old_snapshot = old.input_snapshot_json
    task.result_url = "/api/files/regenerated.png"
    task.prompt_text = "新图片原始提示词"
    db_session.commit()
    assert status(db_session, task) == "NOT_REVIEWED"
    new = enqueue_automatic_review(db_session, task.id)
    assert new.id != old.id and status(db_session, task) == "PENDING"
    asyncio.run(execute_image_review(db_session, old.id))
    assert status(db_session, task) == "PENDING"
    assert json.loads(old_snapshot)["original_prompt"] != json.loads(new.input_snapshot_json)["original_prompt"]
    asyncio.run(execute_image_review(db_session, new.id))
    assert status(db_session, task) == "FAIL"
    assert db_session.query(ImageQualityReview).count() == 2
    assert json.loads(old.input_snapshot_json)["generated_image"] == "/api/files/generated.png"

def test_error_not_retried_manual_retry_shares_history(db_session, setup_review, fake_llm):
    task = setup_review
    queued = enqueue_automatic_review(db_session, task.id)
    with patch.object(FakeLLM, "chat_completion", new_callable=AsyncMock, side_effect=RuntimeError("provider down")) as call:
        asyncio.run(process_review_queue(db_session))
        assert status(db_session, task) == "ERROR"
        assert enqueue_automatic_review(db_session, task.id).id == queued.id
        assert asyncio.run(process_review_queue(db_session)) is None
        call.assert_awaited_once()
    manual = asyncio.run(review_image_task(db_session, task.id))
    assert manual.trigger == "manual" and manual.status == "success"
    assert db_session.query(ImageQualityReview).count() == 2
    assert task.status == "completed"

def test_running_status_atomic_claim_and_template_snapshot(db_session, setup_review, fake_llm):
    queued = enqueue_automatic_review(db_session, setup_review.id)
    db_session.get(PromptTemplate, "v2-template").template = "later template"
    db_session.commit()
    calls = []
    async def reply(**kw):
        assert status(db_session, setup_review) == "RUNNING"
        calls.append(kw)
        return {"success": True, "content": _response()}
    with patch.object(FakeLLM, "chat_completion", side_effect=reply):
        asyncio.run(execute_image_review(db_session, queued.id))
        asyncio.run(execute_image_review(db_session, queued.id))
    assert len(calls) == 1 and calls[0]["system_prompt"] == "registered v15"

def test_snapshot_error_persisted_once(db_session, setup_review):
    setup_review.metadata_json = json.dumps({"reference_manifest": [{"picture": 1}]})
    db_session.commit()
    result = enqueue_automatic_review(db_session, setup_review.id)
    assert result.status == "error" and "缺失文件" in result.error_message
    assert enqueue_automatic_review(db_session, setup_review.id).id == result.id
    assert setup_review.status == "completed"

def test_batch_quality_mapping_and_result_mismatch_api(client, db_session, setup_review):
    review = create_image_review(db_session, setup_review.id)
    review.status, review.overall = "success", "WARNING"
    db_session.commit()
    result = client.post('/api/tasks/image-review-statuses', json={"images": [
        {"taskId": setup_review.id, "imageUrl": setup_review.result_url},
        {"taskId": setup_review.id, "imageUrl": "/api/files/new.png"},
        {"taskId": None, "imageUrl": "/api/files/upload.png"},
    ]})
    assert result.status_code == 200
    assert [r["qualityStatus"] for r in result.json()["data"]] == ["REVIEW", "NOT_REVIEWED", "NOT_REVIEWED"]
    history = client.get(f'/api/tasks/{setup_review.id}/image-reviews').json()["data"]
    assert history[0]["id"] == review.id

def test_http_transient_failure_has_one_attempt_for_review_only():
    from app.services.llm.http_retry import post_llm_request, single_attempt_llm_request, _request_attempt_limit, MAX_REQUEST_ATTEMPTS
    client = AsyncMock()
    client.post.return_value.status_code = 503
    async def direct(log_id, call):
        return await call
    with patch('app.services.llm.http_retry.await_cancellable_llm_request', side_effect=direct), patch('app.services.llm.http_retry.record_llm_http_attempt'):
        with single_attempt_llm_request():
            asyncio.run(post_llm_request(client, None, 'endpoint', headers={}, body={}, timeout=10))
    client.post.assert_awaited_once()
    assert _request_attempt_limit.get() == MAX_REQUEST_ATTEMPTS

def test_actual_reference_binding_and_changed_asset_error(db_session, setup_review, fake_llm):
    metadata = json.loads(setup_review.metadata_json)
    metadata['reference_manifest'][0].update(character_ids=['stable1', 'stable2'], sha256='original-hash')
    metadata['submitted_reference_bindings'] = [{'picture':1,'node_id':'510','filename':'two-people.png','sha256':'original-hash'}]
    setup_review.metadata_json = json.dumps(metadata)
    db_session.commit()
    review = enqueue_automatic_review(db_session, setup_review.id)
    saved = json.loads(review.input_snapshot_json)['references'][0]
    assert saved['character_ids'] == ['stable1', 'stable2']
    assert saved['binding']['node_id'] == '510' and saved['binding']['filename'] == 'two-people.png'
    with patch.object(FakeLLM, 'chat_completion', new_callable=AsyncMock) as llm:
        asyncio.run(execute_image_review(db_session, review.id))
    llm.assert_not_called()
    assert review.status == 'error' and '文件已变化' in review.error_message
    assert setup_review.status == 'completed'


def test_manual_click_while_automatic_review_running_does_not_duplicate(db_session, setup_review, fake_llm):
    review = enqueue_automatic_review(db_session, setup_review.id)
    review.status = 'running'
    db_session.commit()
    with patch.object(FakeLLM, 'chat_completion', new_callable=AsyncMock) as llm:
        manual = asyncio.run(review_image_task(db_session, setup_review.id))
    llm.assert_not_called()
    assert manual.id == review.id and db_session.query(ImageQualityReview).count() == 1


def test_restart_marks_interrupted_attempt_error_without_resubmitting(db_session, setup_review):
    from app.services.image_review_worker import auto_review_loop
    review = enqueue_automatic_review(db_session, setup_review.id)
    review.status = 'running'
    db_session.commit()
    with patch('app.services.image_review_worker.SessionLocal',sessionmaker(bind=db_session.bind)), patch('app.services.image_review_worker.asyncio.sleep',new=AsyncMock(side_effect=asyncio.CancelledError)), patch('app.services.image_review_worker.execute_image_review',new_callable=AsyncMock) as execute:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(auto_review_loop())
        execute.assert_not_called()
    db_session.refresh(review)
    assert review.status == 'error' and '手动重新评审' in review.error_message
    assert setup_review.status == 'completed'

def test_activation_cutoff_applies_to_historical_completion_notifications(db_session, setup_review):
    from datetime import datetime, timedelta
    config = db_session.get(SystemConfig, 'default')
    config.auto_image_review_enabled_at = datetime.utcnow()
    setup_review.completed_at = datetime.utcnow() - timedelta(days=1)
    db_session.commit()
    assert enqueue_automatic_review(db_session, setup_review.id) is None
    assert asyncio.run(process_review_queue(db_session)) is None
    assert db_session.query(ImageQualityReview).count() == 0
    setup_review.completed_at = datetime.utcnow()
    db_session.commit()
    assert enqueue_automatic_review(db_session, setup_review.id).status == 'pending'


def test_manual_review_independent_of_switch_even_for_paused_pending_review(db_session, setup_review, fake_llm):
    queued = enqueue_automatic_review(db_session, setup_review.id)
    config = db_session.get(SystemConfig, 'default')
    config.auto_image_review_enabled = False
    db_session.commit()
    assert asyncio.run(process_review_queue(db_session)) is None
    manual_start = asyncio.run(review_image_task(db_session, setup_review.id))
    assert manual_start.id == queued.id and manual_start.status == 'success'
    rerun = asyncio.run(review_image_task(db_session, setup_review.id))
    assert rerun.trigger == 'manual' and rerun.id != queued.id
    assert db_session.query(ImageQualityReview).count() == 2


def test_config_api_persistence_default_partial_update_and_worker_refresh(client, db_session):
    from datetime import datetime
    assert client.get('/api/config/').json()['data']['autoImageReviewEnabled'] is False
    assert client.post('/api/config/',json={'autoImageReviewEnabled':True}).status_code == 200
    db_session.expire_all()
    config = db_session.get(SystemConfig,'default')
    enabled_at = config.auto_image_review_enabled_at
    assert config.auto_image_review_enabled and enabled_at is not None
    # An unrelated settings save or repeated ON save must not reset the cutoff.
    client.post('/api/config/',json={'language':'zh-CN'})
    client.post('/api/config/',json={'autoImageReviewEnabled':True})
    db_session.expire_all()
    assert db_session.get(SystemConfig,'default').auto_image_review_enabled_at == enabled_at
    # Reopening sessions emulates the worker's fresh configuration reads.
    with sessionmaker(bind=db_session.bind)() as other:
        assert other.get(SystemConfig,'default').auto_image_review_enabled is True
    client.post('/api/config/',json={'autoImageReviewEnabled':False})
    with sessionmaker(bind=db_session.bind)() as other:
        assert other.get(SystemConfig,'default').auto_image_review_enabled is False
    assert client.get('/api/config/').json()['data']['autoImageReviewEnabled'] is False
