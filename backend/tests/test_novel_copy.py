"""Copy novels through the real router against an isolated in-memory database.

Run with --noconftest to avoid the legacy application startup fixture.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, null
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.novels import router
from app.core.database import Base, get_db
from app.models.novel import Chapter, Character, Novel, Prop, Scene
from app.models.shot import Shot
from app.models.task import Task


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router, prefix="/api/novels")

    def isolated_db():
        yield db

    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def source(db):
    novel = Novel(
        title="三国演义", author="原作者", description="原简介", cover="/source-cover.png",
        status="completed", is_preset=True, chapter_count=99, aspect_ratio="9:16",
        style_prompt_template_id="source-style", character_parse_prompt_template_id="source-parser",
        prompt_template_id="source-character-prompt", shot_image_prompt_template_id="source-shot-prompt",
    )
    novel.chapters = [
        Chapter(number=7, title=" 第七回：原样标题 ", content="  原文\r\n换行与标点：‘玄德’。🐺\n" * 1500,
                status="completed", progress=100, parsed_data='{"characters":["刘备"]}',
                character_images='["/character.png"]', shot_images='["/shot.png"]',
                shot_videos='["/video.mp4"]', transition_videos='["/transition.mp4"]',
                final_video="/final.mp4", shots=[Shot(index=1, description="旧分镜", image_url="/shot.png")]),
        Chapter(number=2, title="第二回", content=""),
        Chapter(number=3, title="空正文", content=null()),
    ]
    novel.characters = [Character(name="刘备", appearance="原外观", image_url="/character.png",
                                  reference_audio_url="/voice.flac")]
    novel.scenes = [Scene(name="桃园", image_url="/scene.png")]
    novel.props = [Prop(name="木杖", image_url="/prop.png")]
    db.add(novel)
    db.flush()
    db.add(Task(type="shot_image", name="原任务", novel_id=novel.id, status="completed", result_url="/shot.png"))
    db.commit()
    return novel


def snapshot(row):
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def test_copy_preserves_all_chapter_text_but_no_assets_or_generated_state(client, db, source):
    source_before = snapshot(source)
    original_chapters = db.query(Chapter).filter_by(novel_id=source.id).order_by(Chapter.number).all()
    chapters_before = {chapter.id: snapshot(chapter) for chapter in original_chapters}

    response = client.post(f"/api/novels/{source.id}/copy", json={"title": "  三国演义测试副本  "})
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["title"] == "三国演义测试副本"
    assert payload["data"]["chapterCount"] == 3  # Actual rows, not the stale source count of 99.
    copied = db.get(Novel, payload["data"]["id"])
    assert copied.id != source.id
    assert (copied.author, copied.description, copied.cover, copied.status, copied.is_preset) == (
        "", "", None, "pending", False,
    )
    assert copied.aspect_ratio == "16:9"
    assert all(getattr(copied, column.key) is None for column in Novel.__table__.columns
               if column.key.endswith("prompt_template_id"))

    copied_chapters = db.query(Chapter).filter_by(novel_id=copied.id).order_by(Chapter.number).all()
    assert [chapter.number for chapter in copied_chapters] == [2, 3, 7]
    assert [(chapter.title, chapter.content) for chapter in copied_chapters] == [
        (chapter.title, chapter.content) for chapter in original_chapters
    ]
    assert {chapter.id for chapter in copied_chapters}.isdisjoint(chapters_before)
    for chapter in copied_chapters:
        assert (chapter.status, chapter.progress) == ("pending", 0)
        assert all(getattr(chapter, key) is None for key in (
            "parsed_data", "character_images", "shot_images", "shot_videos", "transition_videos", "final_video",
        ))
        assert chapter.shots == []
    for model in (Character, Scene, Prop, Task):
        assert db.query(model).filter_by(novel_id=copied.id).count() == 0
        assert db.query(model).filter_by(novel_id=source.id).count() == 1
    db.refresh(source)
    assert snapshot(source) == source_before
    for chapter in original_chapters:
        db.refresh(chapter)
        assert snapshot(chapter) == chapters_before[chapter.id]
    assert db.query(Shot).count() == 1


def test_same_named_sources_are_selected_by_id_and_copies_are_independent(client, db, source):
    other = Novel(title=source.title, chapters=[Chapter(number=1, title="另一部同名小说", content="不同正文")])
    db.add(other)
    db.commit()
    first = client.post(f"/api/novels/{other.id}/copy", json={"title": "三国演义copy"}).json()["data"]
    second = client.post(f"/api/novels/{other.id}/copy", json={"title": "三国演义copy"}).json()["data"]
    assert len({source.id, other.id, first["id"], second["id"]}) == 4
    for copied in (first, second):
        chapters = db.query(Chapter).filter_by(novel_id=copied["id"]).all()
        assert len(chapters) == 1
        assert chapters[0].content == "不同正文"


def test_copy_empty_novel(client, db):
    source = Novel(title="空小说", chapter_count=9)
    db.add(source)
    db.commit()
    response = client.post(f"/api/novels/{source.id}/copy", json={"title": "空小说copy"})
    assert response.status_code == 200
    copied = response.json()["data"]
    assert copied["chapterCount"] == 0
    assert db.query(Chapter).filter_by(novel_id=copied["id"]).count() == 0


@pytest.mark.parametrize("body", [{}, {"title": ""}, {"title": " \t\n "}, {"title": None}])
def test_invalid_copy_title_does_not_write(client, db, source, body):
    response = client.post(f"/api/novels/{source.id}/copy", json=body)
    assert response.status_code == 422
    assert db.query(Novel).count() == 1
    assert db.query(Chapter).count() == 3


def test_missing_source_does_not_create_empty_copy(client, db):
    response = client.post("/api/novels/missing/copy", json={"title": "副本"})
    assert response.status_code == 404
    assert db.query(Novel).count() == 0


def test_chapter_insert_failure_rolls_back_the_entire_copy(client, db, source):
    source_id = source.id

    def reject_copied_chapter(mapper, connection, chapter):
        if chapter.novel_id != source_id and chapter.number == 7:
            raise RuntimeError("simulated chapter insert failure")

    event.listen(Chapter, "before_insert", reject_copied_chapter)
    try:
        with pytest.raises(RuntimeError, match="simulated chapter insert failure"):
            client.post(f"/api/novels/{source_id}/copy", json={"title": "不能留下半成品"})
    finally:
        event.remove(Chapter, "before_insert", reject_copied_chapter)
    assert db.query(Novel).count() == 1
    assert db.query(Chapter).count() == 3
    assert db.get(Novel, source_id).chapter_count == 99
