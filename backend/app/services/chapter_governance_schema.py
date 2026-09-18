import json
from datetime import datetime
from sqlalchemy import inspect,text
from app.models.chapter_governance import ChapterLifecycle,ChapterRebuildRun


def upgrade(bind):
    with bind.begin() as connection:
        for model in (ChapterLifecycle,ChapterRebuildRun):model.__table__.create(connection,checkfirst=True)
        names=set(inspect(connection).get_table_names())
        if not {'chapters','shots','shot_sources','chapter_shot_split_runs'}<=names:return
        rows=connection.execute(text('SELECT id,novel_id,parsed_data,shot_images,shot_videos,transition_videos,final_video FROM chapters WHERE id NOT IN (SELECT chapter_id FROM chapter_asset_lifecycle)')).mappings().all()
        for row in rows:
            shots=[r[0] for r in connection.execute(text('SELECT id FROM shots WHERE chapter_id=:cid'),{'cid':row['id']})]
            split=connection.execute(text('SELECT id FROM chapter_shot_split_runs WHERE chapter_id=:cid LIMIT 1'),{'cid':row['id']}).first()
            legacy=not split and (bool(shots) or any(row[k] not in (None,'','{}','[]') for k in ('parsed_data','shot_images','shot_videos','transition_videos','final_video')))
            connection.execute(ChapterLifecycle.__table__.insert().values(chapter_id=row['id'],novel_id=row['novel_id'],origin='LEGACY' if legacy else 'NEW',
                origin_evidence={'method':'PHASE8_STRUCTURAL_SNAPSHOT','legacy_derived_present':bool(legacy),'observed_shot_ids':shots,'new_split_receipt_present':bool(split)},created_at=datetime.utcnow()))
