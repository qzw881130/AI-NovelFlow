import json

import pytest
from sqlalchemy.orm import sessionmaker

from app.api import shots as shots_api
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.models.task import Task


def _create_video_batch(db_session, status="pending", child_count=2):
    novel = Novel(title="持久化批量视频测试")
    db_session.add(novel)
    db_session.commit()
    chapter = Chapter(novel_id=novel.id, number=1, title="第一章", content="内容")
    db_session.add(chapter)
    db_session.commit()
    batch = Task(
        type="shot_video_batch",
        status=status,
        name="批量生成分镜视频",
        novel_id=novel.id,
        chapter_id=chapter.id,
        metadata_json=json.dumps({"auto_complete_details": False}),
    )
    db_session.add(batch)
    db_session.flush()
    children = []
    for index in range(1, child_count + 1):
        shot = Shot(
            chapter_id=chapter.id,
            index=index,
            description=f"分镜{index}",
            characters="[]",
            props="[]",
            duration=4,
            image_url=f"/api/files/shot-{index}.png",
            image_status="completed",
            video_status="pending",
            video_director_plan=json.dumps({"selected_mode": "SINGLE_FRAME"}),
        )
        db_session.add(shot)
        db_session.flush()
        child = Task(
            type="shot_video",
            status="pending",
            name=f"生成视频: 镜{index}",
            novel_id=novel.id,
            chapter_id=chapter.id,
            shot_id=shot.id,
            parent_task_id=batch.id,
            batch_order=index,
        )
        db_session.add(child)
        children.append(child)
    db_session.commit()
    return batch, children


def test_resume_active_shot_video_batches_uses_persisted_parents(db_session, monkeypatch):
    testing_session = sessionmaker(bind=db_session.bind)
    monkeypatch.setattr(shots_api, "SessionLocal", testing_session)
    pending, _ = _create_video_batch(db_session, status="pending", child_count=1)
    running, _ = _create_video_batch(db_session, status="running", child_count=1)
    completed, _ = _create_video_batch(db_session, status="completed", child_count=1)
    enqueued = []
    monkeypatch.setattr(shots_api, "enqueue_shot_video_batch_task", enqueued.append)

    shots_api.resume_active_shot_video_batches()

    assert set(enqueued) == {pending.id, running.id}
    assert completed.id not in enqueued


@pytest.mark.asyncio
async def test_video_batch_runner_completes_persisted_children_in_order(db_session, monkeypatch):
    testing_session = sessionmaker(bind=db_session.bind)
    monkeypatch.setattr(shots_api, "SessionLocal", testing_session)
    batch, children = _create_video_batch(db_session)
    processed = []

    def complete_child(db, child, selected_mode, use_reference_audio, skip_llm_when_prompt_exists):
        processed.append(child.batch_order)
        child.status = "completed"
        child.progress = 100
        db.commit()

    monkeypatch.setattr(shots_api, "_prepare_and_enqueue_batch_video_child", complete_child)

    await shots_api.run_shot_video_batch_task(batch.id)

    db_session.expire_all()
    refreshed_batch = db_session.query(Task).filter(Task.id == batch.id).one()
    refreshed_children = db_session.query(Task).filter(
        Task.parent_task_id == batch.id,
        Task.type == "shot_video",
    ).order_by(Task.batch_order).all()
    assert processed == [1, 2]
    assert refreshed_batch.status == "completed"
    assert refreshed_batch.progress == 100
    assert [child.status for child in refreshed_children] == ["completed", "completed"]
