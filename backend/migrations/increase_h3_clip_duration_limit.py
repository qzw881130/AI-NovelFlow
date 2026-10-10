"""Upgrade only the shipped H3 duration default; leave graphs and custom limits intact.

Run from backend: python -m migrations.increase_h3_clip_duration_limit
"""
import json
from pathlib import Path

from app.constants.capability import CLIP_MAX_DURATION
from app.constants.workflow import EXTRA_SYSTEM_WORKFLOWS


def upgraded_extension(workflow):
    defaults = {item['filename']: item for item in EXTRA_SYSTEM_WORKFLOWS
                if item.get('extension', {}).get('max_clip_duration') == CLIP_MAX_DURATION}
    default = defaults.get(Path(workflow.file_path or '').name)
    if not workflow.is_system or not default or workflow.type != default['type']:
        return None
    extension = json.loads(workflow.extension or '{}')
    if extension.get('max_clip_duration') != 15 or extension.get('max_seconds'):
        return None
    return {**extension, 'max_clip_duration': CLIP_MAX_DURATION}


def migrate(db):
    from app.models.workflow import Workflow
    changes = []
    for workflow in db.query(Workflow).all():
        extension = upgraded_extension(workflow)
        if extension is not None:
            changes.append({'workflow_id': workflow.id, 'before': workflow.extension, 'after': extension})
            workflow.extension = json.dumps(extension, ensure_ascii=False)
    db.commit()
    return changes


if __name__ == '__main__':
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        print(json.dumps(migrate(db), ensure_ascii=False, indent=2))
