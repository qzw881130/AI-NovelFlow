"""Notification presentation tests use isolated SQLite and mocked channels only."""
import copy
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.novel import Chapter, Novel
from app.models.notification import BusinessEvent, NotificationDelivery, NotificationSettings
from app.models.shot import Shot
from app.models.task import Task
from app.services.business_events import record_event
from app.services.notification_format import LABELS, format_notification, resolve_business_context
from app.services.notification_dedupe import failure_delivery_decision
from app.services.notification_registry import EVENT_REGISTRY
from app.services.notification_service import NotificationService, get_or_create_settings


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _business_rows(db):
    novel = Novel(title="皇帝的新装")
    db.add(novel)
    db.flush()
    chapter = Chapter(novel_id=novel.id, number=7, title="第七章")
    db.add(chapter)
    db.flush()
    shot = Shot(chapter_id=chapter.id, index=7)
    db.add(shot)
    db.commit()
    return novel, chapter, shot


def test_all_registered_events_have_explicit_business_titles(db):
    assert set(LABELS) == set(EVENT_REGISTRY)
    for code in EVENT_REGISTRY:
        row = record_event(db, code, {"shot_index": 7, "clip_index": 2}, is_test=True)
        message = format_notification(row)
        assert message.startswith(("✅ NovelFlow｜", "🔧 NovelFlow｜", "❌ NovelFlow｜", "⚠️ NovelFlow｜"))
        assert LABELS[code] in message.splitlines()[0]
        assert "事件：" not in message and "数据：" not in message and code not in message


def test_real_relationship_numbers_and_business_fields(db):
    novel, chapter, shot = _business_rows(db)
    row = record_event(db, "clip.generation.completed", {
        "novel_id": novel.id, "chapter_id": chapter.id, "shot_id": shot.id,
        "details": {"shot_index": 99, "clip_index": 2, "actual_duration": 8.2, "duration_ms": 155000},
    })
    message = format_notification(row, resolve_business_context(db, row))
    assert message.startswith("✅ NovelFlow｜Shot 7 · C2 视频生成完成")
    assert "📖 小说：皇帝的新装" in message
    assert "📚 章节：第 7 章" in message
    assert "⏱ 耗时：2分35秒" in message
    assert "🎞 视频时长：8.2秒" in message
    assert "Shot 99" not in message
    assert novel.id not in message and chapter.id not in message and shot.id not in message


def test_failure_uses_safe_summary_and_known_stage(db):
    row = record_event(db, "clip.prompt.optimize.failed", {
        "shot_index": 7, "clip_index": 2, "message": "角色站位保持约束未通过",
        "details": {"stage": "14", "blocking_findings": ["position"]},
    }, is_test=True)
    message = format_notification(row)
    assert "❌ NovelFlow｜Shot 7 · C2 H3 提示词优化失败" in message
    assert "阶段：H3 提示词优化" in message
    assert "原因：角色站位保持约束未通过" in message
    assert "结果：已阻止视频生成" in message


def test_standalone_prompt_failure_translates_exact_saved_ai_call(db):
    novel, chapter, shot = _business_rows(db)
    happened = datetime.now(timezone.utc).replace(tzinfo=None)
    shot.video_director_plan = json.dumps({"ai_calls": [{
        "step": "11", "status": "error", "clip_index": 1,
        "created_at": happened.isoformat(),
        "error_message": "DIALOGUE_EXACT_TEXT_OCCURRENCE_INVALID",
    }]})
    db.commit()
    row = record_event(db, "clip.prompt.build.failed", {
        "shot_id": shot.id, "chapter_id": chapter.id, "novel_id": novel.id,
        "details": {"clip_index": 1, "stage": "11"},
    }, timestamp=happened)
    message = format_notification(row, resolve_business_context(db, row))
    assert "Shot 7 · C1 Clip 提示词构建失败" in message
    assert "原因：台词出现次数不符合要求" in message
    assert "DIALOGUE_EXACT_TEXT_OCCURRENCE_INVALID" not in message


def test_uuid_clip_id_uses_exact_task_metadata_for_display(db):
    novel, chapter, shot = _business_rows(db)
    clip_uuid = "123e4567-e89b-12d3-a456-426614174001"
    task = Task(type="shot_video", status="failed", name="C1", shot_id=shot.id,
                metadata_json=json.dumps({"execution_scope": "CLIP", "clip_id": clip_uuid, "clip_index": 1}))
    db.add(task)
    db.commit()
    row = record_event(db, "clip.generation.failed", {
        "novel_id": novel.id, "chapter_id": chapter.id, "shot_id": shot.id,
        "task_id": task.id, "clip_id": clip_uuid,
        "message": "DIALOGUE_DUPLICATED_IN_PROMPT",
    })
    message = format_notification(row, resolve_business_context(db, row))
    assert "Shot 7 · C1 生成失败" in message
    assert clip_uuid not in message and f"任务 ID：{task.id}" in message and shot.id not in message


@pytest.mark.parametrize("unsafe", [
    "Traceback (most recent call last): File /app/jobs/run.py",
    "数据库异常 /Volumes/Data/private/secret.db",
    "Bot Token: 12345:abc", "API Key=sk-abc123",
    "IntegrityError: UNIQUE constraint failed: tasks.id",
    "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789",
    "internal_render_failure_code",
    "task 123e4567-e89b-12d3-a456-426614174000 failed",
    '{"error":"internal"}',
])
def test_unsafe_failure_details_are_omitted(db, unsafe):
    row = record_event(db, "clip.generation.failed", {"shot_index": 7, "message": unsafe}, is_test=True)
    message = format_notification(row)
    assert "原因：未取得可安全展示的错误摘要" in message
    assert unsafe not in message
    assert re.search(r"(?:Token|sk-abc|/Volumes|123e4567)", message) is None


def test_simulation_uses_supplied_numbers_without_touching_business_rows(db):
    novel, chapter, shot = _business_rows(db)
    original = {"shot_index": 4, "clip_index": 2, "status": "completed"}
    payload = copy.deepcopy(original)
    row = record_event(db, "clip.generation.completed", payload, is_test=True)
    message = format_notification(row, resolve_business_context(db, row))
    assert payload == original
    assert message.startswith("✅ NovelFlow｜Shot 4 · C2 视频生成完成")
    assert "开发模拟事件" in message
    assert "小说：" not in message and "章节：" not in message
    assert db.get(Shot, shot.id).index == 7
    assert db.get(Chapter, chapter.id).number == 7
    assert db.get(Novel, novel.id).title == "皇帝的新装"


def test_batch_counts_are_read_from_existing_task_result(db):
    novel, chapter, _ = _business_rows(db)
    task = Task(type="shot_video_batch", name="批量生成视频", status="failed",
                novel_id=novel.id, chapter_id=chapter.id,
                current_step="完成：成功 3，失败 1，取消 0")
    db.add(task)
    db.commit()
    row = record_event(db, "batch.generation.failed", {
        "novel_id": novel.id, "chapter_id": chapter.id, "task_id": task.id,
    })
    message = format_notification(row, resolve_business_context(db, row))
    assert "成功数量：3" in message
    assert "失败数量：1" in message
    assert "总数数量：4" not in message
    assert "总数量：4" in message
    assert "取消数量：0" in message


@pytest.mark.asyncio
async def test_channels_share_message_and_query_failure_degrades(db, monkeypatch):
    _business_rows(db)
    settings = get_or_create_settings(db)
    settings.feishu_enabled = True
    settings.telegram_enabled = True
    db.commit()
    messages = []

    async def fake_feishu(_webhook, _secret, message):
        messages.append(("feishu", message))

    async def fake_telegram(_token, _chat, message):
        messages.append(("telegram", message))

    monkeypatch.setattr("app.services.notification_service.send_feishu", fake_feishu)
    monkeypatch.setattr("app.services.notification_service.send_telegram", fake_telegram)
    monkeypatch.setattr("app.services.notification_service.decrypt_secret", lambda _: "mock")
    monkeypatch.setattr("app.services.notification_service.resolve_business_context", lambda *_: (_ for _ in ()).throw(RuntimeError("query failed")))
    row = record_event(db, "shot.planning.completed", {"details": {"shot_index": 7}})
    result = await NotificationService.dispatch_event(db, row.id)
    assert result["status"] == "processed"
    assert messages[0][1] == messages[1][1]
    assert messages[0][1].startswith("✅ NovelFlow｜Shot 7 规划完成")
    assert db.get(BusinessEvent, row.id).notification_status == "processed"
    assert db.query(NotificationSettings).count() == 1


@pytest.mark.asyncio
async def test_one_final_external_failure_for_exact_task_clip(db, monkeypatch):
    novel, chapter, shot = _business_rows(db)
    settings = get_or_create_settings(db)
    settings.feishu_enabled = settings.telegram_enabled = True
    db.commit()
    sent = []

    async def fake_feishu(_webhook, _secret, message):
        sent.append(("FEISHU", message))

    async def fake_telegram(_token, _chat, message):
        sent.append(("TELEGRAM", message))

    monkeypatch.setattr("app.services.notification_service.send_feishu", fake_feishu)
    monkeypatch.setattr("app.services.notification_service.send_telegram", fake_telegram)
    monkeypatch.setattr("app.services.notification_service.decrypt_secret", lambda _: "mock")
    started = datetime.now(timezone.utc).replace(tzinfo=None)
    task = Task(type="shot_video", name="C1", status="running", novel_id=novel.id,
                chapter_id=chapter.id, shot_id=shot.id, started_at=started,
                metadata_json=json.dumps({"execution_scope": "CLIP", "clip_index": 1,
                                          "clip_id": "clip-uuid-from-business"}))
    db.add(task)
    db.commit()
    happened = datetime.now(timezone.utc).replace(tzinfo=None)
    shot.video_director_plan = json.dumps({"ai_calls": [{
        "step": "11", "status": "error", "clip_index": 1,
        "created_at": happened.isoformat(),
        "error_message": "DIALOGUE_DUPLICATED_IN_PROMPT",
    }]})
    db.commit()
    prompt = record_event(db, "clip.prompt.build.failed", {
        "shot_id": shot.id, "chapter_id": chapter.id, "novel_id": novel.id,
        "clip_id": f"{shot.id}:clip:1", "details": {"clip_index": 1, "stage": "11"},
    }, timestamp=happened)
    result = await NotificationService.dispatch_event(db, prompt.id)
    assert result["status"] == "pending"
    assert result["channels"] == {"PAGE_SOUND": "queued", "FEISHU": "deferred", "TELEGRAM": "deferred"}
    assert not sent

    task.status = "failed"
    task.completed_at = happened + timedelta(seconds=1)
    task.current_step = "Clip 1 H3 提示词构建失败"
    task.error_message = "DIALOGUE_DUPLICATED_IN_PROMPT"
    db.commit()
    final = record_event(db, "clip.generation.failed", {
        "task_id": task.id, "shot_id": shot.id, "chapter_id": chapter.id, "novel_id": novel.id,
        "clip_id": "clip-uuid-from-business", "message": task.error_message,
        "details": {"clip_index": 1},
    }, timestamp=task.completed_at)
    assert failure_delivery_decision(db, prompt, final_subscribed=True, external_enabled=True) == "suppress"
    result = await NotificationService.dispatch_event(db, prompt.id)
    assert result["channels"]["FEISHU"] == "suppressed_duplicate"
    assert result["channels"]["TELEGRAM"] == "suppressed_duplicate"
    assert not sent
    await NotificationService.dispatch_event(db, final.id)
    assert len(sent) == 2 and sent[0][1] == sent[1][1]
    message = sent[0][1]
    assert message.startswith("❌ NovelFlow｜Shot 7 · C1 生成失败")
    assert "阶段：H3 提示词构建" in message
    assert "原因：台词重复校验未通过" in message
    assert "结果：视频未生成" in message
    assert "DIALOGUE_DUPLICATED_IN_PROMPT" not in message
    assert f"任务 ID：{task.id}" in message and shot.id not in message
    assert db.query(NotificationDelivery).filter_by(channel="PAGE_SOUND", event_code="clip.prompt.build.failed").count() == 1
    assert db.query(NotificationDelivery).filter_by(channel="PAGE_SOUND").count() == 2
    assert db.get(BusinessEvent, final.id).message == "DIALOGUE_DUPLICATED_IN_PROMPT"
    assert "DIALOGUE_DUPLICATED_IN_PROMPT" in db.get(Shot, shot.id).video_director_plan
    assert db.query(BusinessEvent).count() == 2


def test_dedupe_never_merges_another_task_or_clip(db):
    novel, chapter, shot = _business_rows(db)
    happened = datetime.now(timezone.utc).replace(tzinfo=None)
    task = Task(type="shot_video", status="running", name="C1", shot_id=shot.id,
                started_at=happened - timedelta(seconds=1),
                metadata_json=json.dumps({"execution_scope": "CLIP", "clip_index": 1}))
    db.add(task)
    db.commit()
    prompt = record_event(db, "clip.prompt.build.failed", {
        "shot_id": shot.id, "chapter_id": chapter.id, "novel_id": novel.id,
        "details": {"clip_index": 1, "stage": "11"},
    }, timestamp=happened)
    other = Task(type="shot_video", status="failed", name="retry C1", shot_id=shot.id,
                 started_at=happened + timedelta(seconds=1), completed_at=happened + timedelta(seconds=2),
                 metadata_json=json.dumps({"execution_scope": "CLIP", "clip_index": 1}))
    db.add(other)
    db.commit()
    record_event(db, "clip.generation.failed", {
        "task_id": other.id, "shot_id": shot.id, "details": {"clip_index": 1},
    }, timestamp=other.completed_at)
    record_event(db, "clip.generation.failed", {
        "task_id": task.id, "shot_id": shot.id, "details": {"clip_index": 2},
    }, timestamp=happened + timedelta(seconds=3))
    assert failure_delivery_decision(db, prompt, final_subscribed=True, external_enabled=True) == "hold"
    assert failure_delivery_decision(db, prompt, final_subscribed=False, external_enabled=True) == "send"


def test_simulated_chain_does_not_merge_different_shots(db):
    prompt = record_event(db, "clip.prompt.build.failed", {
        "shot_index": 7, "clip_index": 1, "task_id": "shared-test-id",
    }, is_test=True)
    record_event(db, "clip.generation.failed", {
        "shot_index": 8, "clip_index": 1, "task_id": "shared-test-id",
    }, is_test=True)
    assert failure_delivery_decision(db, prompt, final_subscribed=True, external_enabled=True) == "hold"


def test_missing_final_event_falls_back_to_prompt_failure(db):
    _, chapter, shot = _business_rows(db)
    happened = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2)
    task = Task(type="shot_video", status="failed", name="C1", shot_id=shot.id,
                started_at=happened - timedelta(seconds=1), completed_at=happened + timedelta(seconds=1),
                metadata_json=json.dumps({"execution_scope": "CLIP", "clip_index": 1}))
    db.add(task)
    db.commit()
    prompt = record_event(db, "clip.prompt.build.failed", {
        "shot_id": shot.id, "chapter_id": chapter.id,
        "details": {"clip_index": 1, "stage": "11"},
    }, timestamp=happened)
    assert failure_delivery_decision(db, prompt, final_subscribed=True, external_enabled=True) == "send"


@pytest.mark.asyncio
async def test_simulated_failure_pair_suppresses_intermediate_without_real_task(db, monkeypatch):
    settings = get_or_create_settings(db)
    settings.feishu_enabled = settings.telegram_enabled = True
    db.commit()
    sent = []

    async def fake_send(*args):
        sent.append(args[-1])

    monkeypatch.setattr("app.services.notification_service.send_feishu", fake_send)
    monkeypatch.setattr("app.services.notification_service.send_telegram", fake_send)
    monkeypatch.setattr("app.services.notification_service.decrypt_secret", lambda _: "mock")
    payload = {"shot_index": 7, "clip_index": 1, "task_id": "simulated-task-1",
               "error_code": "DIALOGUE_DUPLICATED_IN_PROMPT"}
    prompt = record_event(db, "clip.prompt.build.failed", payload, is_test=True)
    final = record_event(db, "clip.generation.failed", payload, is_test=True)
    assert failure_delivery_decision(db, prompt, final_subscribed=True, external_enabled=True) == "suppress"
    await NotificationService.dispatch_event(db, prompt.id)
    await NotificationService.dispatch_event(db, final.id)
    assert len(sent) == 2 and sent[0] == sent[1]
    assert sent[0].startswith("❌ NovelFlow｜Shot 7 · C1 生成失败")
    assert db.query(Task).count() == 0


@pytest.mark.parametrize("code,expected", [
    ("shot.planning.completed", "Shot 7 规划完成"),
    ("clip.prompt.build.failed", "Shot 7 · C1 Clip 提示词构建失败"),
    ("clip.generation.failed", "Shot 7 · C1 生成失败"),
    ("clip.prompt.optimize.failed", "Shot 7 · C1 H3 提示词优化失败"),
    ("preflight.repair.failed", "Shot 7 · C1 Preflight 修复失败"),
])
def test_development_simulation_five_requested_events(db, code, expected):
    payload = {"shot_index": 7}
    if code != "shot.planning.completed":
        payload["clip_index"] = 1
        payload["error_code"] = "DIALOGUE_EXACT_TEXT_OCCURRENCE_INVALID"
        payload["message"] = "DIALOGUE_EXACT_TEXT_OCCURRENCE_INVALID"
    row = record_event(db, code, payload, is_test=True)
    message = format_notification(row)
    assert expected in message
    assert "🧪 开发模拟事件" in message
    assert "DIALOGUE_EXACT_TEXT_OCCURRENCE_INVALID" not in message
    assert "事件：" not in message and "数据：" not in message
    assert re.search(r"[0-9a-f]{8}-[0-9a-f-]{27,}", message) is None

@pytest.mark.parametrize('mode', ['GENERATE', 'EXTEND', 'TEMPORAL_EXTEND'])
def test_phase_b_failure_includes_reason_stage_mode_and_exact_task(db, mode):
    novel, chapter, shot = _business_rows(db)
    task = Task(type='shot_video', name='silent clip', status='failed', novel_id=novel.id,
                chapter_id=chapter.id, shot_id=shot.id,
                current_step='正在构建 H3 视频提示词...',
                error_message='PHASE_B_INPUT_NOT_COVERED: ValueError: SILENT_CLIP_NOT_COVERED',
                metadata_json=json.dumps({'clip_index':2, 'capability':mode,
                    'h3_phase_b':{'status':'FAILED','llm_call_count':0}}))
    db.add(task); db.commit()
    row = record_event(db, 'clip.generation.failed', {'task_id':task.id, 'shot_id':shot.id,
        'clip_id':f'{shot.id}:clip:2', 'message':task.error_message})
    before = (task.error_message, task.metadata_json, row.message, row.details_json)
    message = format_notification(row, resolve_business_context(db,row))
    assert '阶段：Phase B 输入准备' in message
    assert '原因：当前导演合同尚不支持无对白 Clip' in message
    assert f'任务 ID：{task.id}' in message and f'生成模式：{mode}' in message
    assert 'ValueError' not in message and 'SILENT_CLIP_NOT_COVERED' not in message
    assert before == (task.error_message, task.metadata_json, row.message, row.details_json)


@pytest.mark.parametrize('record,label', [
    ({'compiler_result':{'status':'VALIDATION_FAILED'},'preflight':{'passed':False}}, 'Phase B Compiler'),
    ({'compiler_result':{'status':'CANDIDATE_FOR_REVIEW'},'preflight':{'passed':False}}, 'Phase B Preflight'),
    ({'llm_call_count':1}, '#13 Phase B 导演规划'),
])
def test_phase_b_failure_stage_uses_existing_execution_record(db, record, label):
    task = Task(type='shot_video', name='offline', status='failed',
        metadata_json=json.dumps({'capability':'GENERATE','h3_phase_b':{'status':'FAILED',**record}}),
        error_message='Traceback: File "/private/key.py" token=secret-value')
    db.add(task); db.commit()
    row = record_event(db,'clip.generation.failed',{'task_id':task.id,'message':task.error_message})
    text=format_notification(row,resolve_business_context(db,row))
    assert f'阶段：{label}' in text
    assert 'secret-value' not in text and '/private' not in text and 'Traceback' not in text
    assert '原因：未取得可安全展示' in text


def test_historical_failure_does_not_read_new_retry_error_or_stage(db):
    task = Task(type='shot_video', name='retry', status='running',
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
        error_message='PICTURE_MAPPING_AUDIT_FAILED',
        metadata_json=json.dumps({'capability':'EXTEND','h3_phase_b':{'status':'FAILED','llm_call_count':0}}))
    db.add(task); db.commit()
    row = record_event(db,'clip.generation.failed',{'task_id':task.id,'message':'旧任务失败'},
                       timestamp=task.started_at-timedelta(minutes=2))
    text=format_notification(row,resolve_business_context(db,row))
    assert '原因：旧任务失败' in text
    assert '画面引用校验' not in text and '阶段：Phase B 输入准备' not in text
    assert '生成模式：UNKNOWN' in text
