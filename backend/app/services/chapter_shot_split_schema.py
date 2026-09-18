from app.models.chapter_shot_split import ChapterShotSplitRun, ShotSource
from sqlalchemy import inspect, text


def upgrade(bind):
    with bind.begin() as connection:
        for model in (ChapterShotSplitRun, ShotSource):
            model.__table__.create(connection, checkfirst=True)
        columns={c['name'] for c in inspect(connection).get_columns('shot_sources')}
        if 'treatment_contract' not in columns:
            connection.execute(text('ALTER TABLE shot_sources ADD COLUMN treatment_contract JSON'))
        if 'source_contract' not in columns:
            connection.execute(text('ALTER TABLE shot_sources ADD COLUMN source_contract JSON'))
        tables=set(inspect(connection).get_table_names())
        if 'shots' in tables:
            shot_columns={c['name'] for c in inspect(connection).get_columns('shots')}
            if 'completion_disposition' not in shot_columns:
                connection.execute(text("ALTER TABLE shots ADD COLUMN completion_disposition VARCHAR NOT NULL DEFAULT 'NORMAL'"))
            connection.execute(text('CREATE INDEX IF NOT EXISTS ix_shots_completion_disposition ON shots (completion_disposition)'))
        if 'chapters' in tables:
            chapter_columns={c['name'] for c in inspect(connection).get_columns('chapters')}
            if 'final_video_task_id' not in chapter_columns:
                connection.execute(text('ALTER TABLE chapters ADD COLUMN final_video_task_id VARCHAR'))
            connection.execute(text('CREATE INDEX IF NOT EXISTS ix_chapters_final_video_task_id ON chapters (final_video_task_id)'))
        inspector=inspect(connection)
        if ('shots' in tables and 'completion_disposition' not in {c['name'] for c in inspector.get_columns('shots')}) or (
                'chapters' in tables and 'final_video_task_id' not in {c['name'] for c in inspector.get_columns('chapters')}):
            raise RuntimeError('R_CD1_SCHEMA_UPGRADE_FAILED')
