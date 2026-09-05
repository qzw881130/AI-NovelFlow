import json

from sqlalchemy import create_engine, inspect, text

from app.models.audio_drive import AudioEventTTSAsset, ShotAudioEvent, ShotAudioTimeline, ShotAudioTimelineEvent
from app.models.novel import Chapter, Novel
from app.models.shot import Shot
from app.repositories.audio_drive import AudioDriveRepository
from app.repositories.shot_repository import ShotRepository
from app.services.sqlite_schema_upgrade import assert_audiodrive_integrity, audiodrive_orphan_counts, upgrade_sqlite_schema


def _create_old_sqlite_db(tmp_path):
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE novels (id VARCHAR PRIMARY KEY, title VARCHAR NOT NULL)"))
        conn.execute(text("CREATE TABLE chapters (id VARCHAR PRIMARY KEY, novel_id VARCHAR NOT NULL, number INTEGER NOT NULL, title VARCHAR NOT NULL)"))
        conn.execute(text("""
            CREATE TABLE shots (
                id VARCHAR PRIMARY KEY,
                chapter_id VARCHAR NOT NULL,
                "index" INTEGER NOT NULL,
                description TEXT,
                characters TEXT,
                scene VARCHAR,
                props TEXT,
                duration INTEGER
            )
        """))
        conn.execute(text("CREATE TABLE tasks (id VARCHAR PRIMARY KEY, type VARCHAR NOT NULL, name VARCHAR NOT NULL)"))
        conn.execute(text("CREATE TABLE llm_logs (id VARCHAR PRIMARY KEY)"))
    return engine


def _columns(engine, table_name):
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()}


def _indexes(engine, table_name):
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA index_list({table_name})")).fetchall()}


def _create_novel_graph(db_session, chapter_count=1, shots_per_chapter=1):
    novel = Novel(title="Gate D5")
    db_session.add(novel)
    db_session.commit()
    db_session.refresh(novel)
    chapters = []
    shots = []
    for chapter_index in range(1, chapter_count + 1):
        chapter = Chapter(novel_id=novel.id, number=chapter_index, title=f"Chapter {chapter_index}", content="content")
        db_session.add(chapter)
        db_session.commit()
        db_session.refresh(chapter)
        chapters.append(chapter)
        for shot_index in range(1, shots_per_chapter + 1):
            shot = Shot(
                chapter_id=chapter.id,
                index=shot_index,
                description="Shot",
                characters=json.dumps(["A"], ensure_ascii=False),
                props=json.dumps([], ensure_ascii=False),
                duration=4,
            )
            db_session.add(shot)
            db_session.commit()
            db_session.refresh(shot)
            shots.append(shot)
            _attach_audio_drive_rows(db_session, shot.id)
    return novel, chapters, shots


def _attach_audio_drive_rows(db_session, shot_id):
    event = ShotAudioEvent(
        shot_id=shot_id,
        event_order=1,
        event_type="DIALOGUE",
        voice_owner_name="A",
        visible_speaker_name="A",
        requires_visible_lipsync=True,
        text="hello",
        tts_status="READY",
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    asset = AudioEventTTSAsset(
        audio_event_id=event.id,
        provider="test",
        audio_url="/api/files/a.wav",
        audio_path="/tmp/a.wav",
        duration_seconds=1.0,
        revision=1,
        is_current=True,
        status="READY",
    )
    timeline = ShotAudioTimeline(
        shot_id=shot_id,
        revision=1,
        total_duration=1.0,
        audio_required_duration=1.0,
        status="READY",
        generated_from_hash="hash",
    )
    db_session.add_all([asset, timeline])
    db_session.commit()
    db_session.refresh(asset)
    db_session.refresh(timeline)
    timeline_event = ShotAudioTimelineEvent(
        timeline_id=timeline.id,
        audio_event_id=event.id,
        tts_asset_id=asset.id,
        event_order=1,
        start_time=0,
        end_time=1,
        event_type="DIALOGUE",
        voice_owner_name="A",
        visible_speaker_name="A",
        requires_visible_lipsync=True,
    )
    db_session.add(timeline_event)
    db_session.commit()
    return event, asset, timeline, timeline_event


def _assert_no_audiodrive_orphans(db_session):
    counts = assert_audiodrive_integrity(db_session.get_bind())
    assert counts
    assert all(count == 0 for count in counts.values())


def test_sqlite_schema_upgrade_creates_audio_drive_tables_columns_and_indexes_idempotently(tmp_path):
    engine = _create_old_sqlite_db(tmp_path)

    upgrade_sqlite_schema(engine)
    upgrade_sqlite_schema(engine)

    inspector = inspect(engine)
    assert {"shot_audio_events", "audio_event_tts_assets", "shot_audio_timelines", "shot_audio_timeline_events"}.issubset(set(inspector.get_table_names()))
    assert "audio_status" in _columns(engine, "shots")
    assert "estimated_duration" in _columns(engine, "shots")
    assert "video_director_plan_revision" in _columns(engine, "shots")
    assert "worker_id" in _columns(engine, "tasks")
    assert "attempt" in _columns(engine, "tasks")
    assert "audio_required_duration" in _columns(engine, "shot_audio_timelines")
    assert "ix_shot_audio_events_shot_order" in _indexes(engine, "shot_audio_events")
    assert "ix_audio_event_tts_current" in _indexes(engine, "audio_event_tts_assets")
    with engine.connect() as conn:
        counts = audiodrive_orphan_counts(conn)
    assert counts
    assert all(count == 0 for count in counts.values())


def test_sqlite_schema_upgrade_cleans_only_audiodrive_orphans(tmp_path):
    engine = _create_old_sqlite_db(tmp_path)
    upgrade_sqlite_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO shot_audio_events (id, shot_id, event_order, event_type, voice_owner_name, text) VALUES ('event-orphan', 'missing-shot', 1, 'DIALOGUE', 'A', 'hello')"))
        conn.execute(text("INSERT INTO audio_event_tts_assets (id, audio_event_id, revision) VALUES ('asset-orphan', 'event-orphan', 1)"))
        conn.execute(text("INSERT INTO shot_audio_timelines (id, shot_id, revision, total_duration) VALUES ('timeline-orphan', 'missing-shot', 1, 1.0)"))
        conn.execute(text("""
            INSERT INTO shot_audio_timeline_events
            (id, timeline_id, audio_event_id, event_order, start_time, end_time, event_type, voice_owner_name, tts_asset_id)
            VALUES ('timeline-event-orphan', 'timeline-orphan', 'event-orphan', 1, 0, 1, 'DIALOGUE', 'A', 'asset-orphan')
        """))

    upgrade_sqlite_schema(engine)

    with engine.connect() as conn:
        counts = audiodrive_orphan_counts(conn)
        assert conn.execute(text("SELECT COUNT(*) FROM shot_audio_events")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM audio_event_tts_assets")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM shot_audio_timelines")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM shot_audio_timeline_events")).scalar() == 0
    assert counts
    assert all(count == 0 for count in counts.values())


def test_delete_audio_event_cleans_tts_assets_and_timeline_references(db_session):
    _novel, _chapters, shots = _create_novel_graph(db_session)
    shot = shots[0]

    AudioDriveRepository(db_session).sync_events(shot.id, [])

    assert db_session.query(ShotAudioEvent).filter(ShotAudioEvent.shot_id == shot.id).count() == 0
    assert db_session.query(AudioEventTTSAsset).count() == 0
    assert db_session.query(ShotAudioTimelineEvent).count() == 0
    _assert_no_audiodrive_orphans(db_session)


def test_delete_shot_cleans_all_audio_drive_rows(db_session):
    _novel, _chapters, shots = _create_novel_graph(db_session)
    shot = shots[0]

    ShotRepository(db_session).delete(shot)

    assert db_session.query(ShotAudioEvent).count() == 0
    assert db_session.query(AudioEventTTSAsset).count() == 0
    assert db_session.query(ShotAudioTimeline).count() == 0
    assert db_session.query(ShotAudioTimelineEvent).count() == 0
    _assert_no_audiodrive_orphans(db_session)


def test_delete_chapter_cleans_audio_drive_rows_for_all_shots(client, db_session):
    novel, chapters, _shots = _create_novel_graph(db_session, chapter_count=1, shots_per_chapter=3)

    response = client.delete(f"/api/novels/{novel.id}/chapters/{chapters[0].id}")

    assert response.status_code == 200
    assert db_session.query(ShotAudioEvent).count() == 0
    assert db_session.query(AudioEventTTSAsset).count() == 0
    assert db_session.query(ShotAudioTimeline).count() == 0
    assert db_session.query(ShotAudioTimelineEvent).count() == 0
    _assert_no_audiodrive_orphans(db_session)


def test_delete_novel_cleans_audio_drive_rows_across_chapters(client, db_session):
    novel, _chapters, _shots = _create_novel_graph(db_session, chapter_count=2, shots_per_chapter=2)

    response = client.delete(f"/api/novels/{novel.id}")

    assert response.status_code == 200
    assert db_session.query(ShotAudioEvent).count() == 0
    assert db_session.query(AudioEventTTSAsset).count() == 0
    assert db_session.query(ShotAudioTimeline).count() == 0
    assert db_session.query(ShotAudioTimelineEvent).count() == 0
    _assert_no_audiodrive_orphans(db_session)
