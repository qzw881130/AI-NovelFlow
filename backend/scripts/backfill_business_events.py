"""Explicit, idempotent import of saved facts. Never calls LLM/ComfyUI or notifies.

Run from backend: venv/bin/python scripts/backfill_business_events.py --novel-id ID [--apply]
"""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, engine
from app.models.notification import BusinessEvent
from app.models.task import Task
from app.models.shot import Shot
from app.models.novel import Chapter
from app.models.image_quality_review import ImageQualityReview
from app.services.business_events import task_events, review_event, shot_events, record_event, obj


def backfill(db, novel_id, apply=False):
    counts = Counter(); inserted = 0; existing = 0; missing_time = 0
    candidates = []
    for task in db.query(Task).filter_by(novel_id=novel_id).filter(Task.status.in_(['completed','failed'])):
        candidates.extend(task_events(task))
    for review in db.query(ImageQualityReview).join(Task, Task.id == ImageQualityReview.task_id).filter(Task.novel_id == novel_id):
        value = review_event(review, db.get(Task, review.task_id))
        if value: candidates.append(value)
    for shot in db.query(Shot).join(Chapter, Chapter.id == Shot.chapter_id).filter(Chapter.novel_id == novel_id):
        candidates.extend(shot_events(shot, {}, db))
        plan = obj(shot.video_director_plan)
        assembly = plan.get('assembled_result') or {}
        if assembly.get('status') == 'COMPLETED' and assembly.get('url') and assembly.get('assembled_at'):
            candidates.append(('shot.assembly.completed', {
                'novel_id': novel_id, 'chapter_id': shot.chapter_id, 'shot_id': shot.id,
                'source': 'shot_video.merge', 'raw_status': assembly['status'],
                'details': {'shot_index': shot.index, 'clip_count': len(plan.get('clip_plan') or []),
                            'revision': assembly.get('clip_plan_revision')},
            }, f"shot.assembly.completed:{shot.id}:{assembly['url']}:{assembly.get('clip_plan_revision')}",
                datetime.fromisoformat(assembly['assembled_at'])))
    for code, payload, key, stamp in candidates:
        if stamp is None:
            missing_time += 1
            continue
        counts[code] += 1
        if apply:
            if db.query(BusinessEvent.id).filter_by(dedupe_key=key).first():
                existing += 1
            else:
                payload['details'] = {**payload.get('details',{}), 'historical_source': payload.get('source')}
                record_event(db, code, payload, dedupe_key=key, timestamp=stamp, historical=True)
                inserted += 1
    return {'novel_id':novel_id,'apply':apply,'candidates':dict(sorted(counts.items())),
            'inserted':inserted,'existing':existing,'missing_time_skipped':missing_time,
            'notifications_sent':0,'llm_calls':0,'comfyui_submissions':0}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--novel-id',required=True); parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.apply: BusinessEvent.__table__.create(engine,checkfirst=True)
    with SessionLocal() as db:
        print(json.dumps(backfill(db,args.novel_id,args.apply),ensure_ascii=False,indent=2))
