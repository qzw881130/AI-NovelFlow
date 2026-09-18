"""Read-only actual #06/#09, image input log/native wire and protection evidence.

Run after r2-import-generation-live.e2e.mjs; no provider calls or business writes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def protected_rows(path, novel_id):
    with sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        return {table: [dict(row) for row in db.execute(
            f'SELECT * FROM {table} WHERE novel_id=? ORDER BY id', (novel_id,))]
            for table in ('characters', 'scenes', 'props')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--source-db', type=Path, required=True)
    parser.add_argument('--require-contract', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    ctx = json.loads((args.evidence_dir / 'execution-context.json').read_text())
    ui = json.loads((args.evidence_dir / 'f44-generation.json').read_text())
    output = args.evidence_dir / 'generation-verification.json'
    assert not output.exists(), 'Preserve the previous verification'
    os.environ['NOVELFLOW_STORAGE_ROOT'] = ctx['storageRoot']
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    sys.path.insert(0, str(root))
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from app.models.shot import Shot
    from app.models.llm_log import LLMLog
    from app.models.task import Task
    from app.models.rsa_media import RsaImageAttempt
    from app.services.chapter_governance import require_source, require_rsa
    from app.services.rsa_media_contract import artifact_proof, current_primary, verify_prompt_record
    from app.services.audio_drive_service import AudioDriveService
    from app.services.runtime_gate import audio_source_pin
    from app.utils.path_utils import url_to_local_path

    engine = create_engine(f'sqlite:///file:{ctx["database"]}?mode=ro&uri=true')
    @event.listens_for(engine, 'connect')
    def readonly(conn, _):
        conn.execute('PRAGMA query_only=ON')
    @event.listens_for(engine, 'before_cursor_execute')
    def guard(conn, cursor, statement, *rest):
        assert statement.lstrip().split()[0].upper() in {'SELECT', 'PRAGMA'}

    report = {'scope': 'R2-A' if args.require_contract else 'R2-V legacy receipt compatibility', 'artifacts': []}
    with Session(engine, autoflush=False) as db:
        shot = db.get(Shot, ctx['f44']['shotId'])
        source = require_source(db, shot.id)
        rsa = require_rsa(db, shot.id)
        assert source.revision == 3 and shot.description == ui['before']['description']
        primary = current_primary(db, shot)
        report.update(shotId=shot.id, sourceRevision=source.revision, rsaId=rsa.id, rsaHash=rsa.result_hash)
        for tid in (ui['primaryTask']['id'], ui['keyframeTask']['id']):
            attempt, task = db.get(RsaImageAttempt, tid), db.get(Task, tid)
            assert attempt.status == 'SUCCEEDED' and task.status == 'completed'
            artifact = artifact_proof(db, attempt.artifact_id, rsa_id=rsa.id, rsa_hash=rsa.result_hash)
            proof = attempt.execution['prompt']
            verify_prompt_record(db, attempt.inputs, proof)
            log = db.get(LLMLog, proof['llm_log_id'])
            assert (log.provider, log.model, log.status) == ('deepseek', 'deepseek-v4-flash-vision-exp', 'success')
            info = json.loads(log.request_info)
            if args.require_contract:
                assert attempt.inputs['prompt_log_contract'] == info['multimodal']['contract'] == 'inline-images-v1'
                assert info['multimodal']['wire_format'] == 'openai-chat'
                assert len(info['multimodal']['images']) == len(attempt.execution['manifest'])
            image = artifact.data['image']
            path = Path(url_to_local_path(image['url']))
            assert path.resolve().is_relative_to(Path(ctx['storageRoot']).resolve())
            assert sha(path) == image['sha256']
            if artifact.stage == 'KEYFRAME':
                assert artifact.data['parents'][0]['id'] == primary.id
            report['artifacts'].append({
                'stage': artifact.stage, 'taskId': tid, 'artifactId': artifact.id,
                'image': image, 'parents': artifact.data['parents'], 'logId': log.id,
                'provider': log.provider, 'model': log.model, 'requestInfo': info,
                'canonicalInput': json.loads(log.user_prompt), 'response': log.response,
                'referenceManifest': attempt.execution['manifest'],
                'promptId': attempt.execution['submit']['prompt_id'], 'graphHash': attempt.execution['submit']['graph_hash'],
            })
        audio = AudioDriveService(db)
        events = audio.repo.list_events(shot.id)
        assert [item.id for item in events] == ui['before']['eventIds']
        assert all(audio._tts_asset_eligible(item, audio.repo.current_tts_asset(item.id), audio_source_pin(db, shot.id)) for item in events)
        assert not db.query(Task).filter(Task.status.in_(['pending', 'running', 'queued'])).count()
        assert not db.new and not db.dirty and not db.deleted
        report['existingTtsStillEligible'] = True
    report['inputFilesPreserved'] = all(sha(item['source']) == item['sha256'] == sha(item['copy']) for item in ctx['inputCopies'])
    report['bookAssetsPreserved'] = protected_rows(args.source_db, ctx['f44']['novelId']) == protected_rows(ctx['database'], ctx['f44']['novelId'])
    # Every old immutable Source/Revision/Log row remains byte-for-byte identical.
    with sqlite3.connect(f'file:{args.source_db.resolve()}?mode=ro', uri=True) as before, sqlite3.connect(f'file:{ctx["database"]}?mode=ro', uri=True) as after:
        tables = ('shot_sources', 'chapter_shot_split_runs', 'shot_revisions', 'llm_logs')
        preserved = {}
        for table in tables:
            columns = [r[1] for r in before.execute(f'PRAGMA table_info({table})')]
            assert columns
            key = 'shot_id' if table == 'shot_sources' else 'id'
            count = 0
            for row in before.execute(f'SELECT * FROM {table}'):
                current = after.execute(f'SELECT * FROM {table} WHERE {key}=?', (row[columns.index(key)],)).fetchone()
                assert current == row, f'Historical {table} row changed'
                count += 1
            preserved[table] = count
        report['historicalRowsPreserved'] = preserved
    assert report['inputFilesPreserved'] and report['bookAssetsPreserved']
    report['passed'] = True
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != 'artifacts'}, ensure_ascii=False))
    print(json.dumps([{key: a[key] for key in ('stage', 'taskId', 'artifactId', 'logId')} for a in report['artifacts']]))


if __name__ == '__main__':
    main()
