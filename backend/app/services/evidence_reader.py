"""Read-only evidence decoding. Missing/corrupt JSON is never a successful empty value."""
import hashlib
import json
import re
from sqlalchemy import JSON, String, cast, select
from fastapi.encoders import jsonable_encoder

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_DISPLAY_CHARS = 24000
SECRET_KEY = re.compile(r'^(?:[a-z0-9]+[_-])*(?:api[_-]?key|api[_-]?token|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|password|passwd|secret|client[_-]?secret|authorization|proxy[_-]?authorization|cookie|set-cookie)$', re.I)

TEXT_JSON_FIELDS = {
    'tasks': {'metadata_json': dict, 'workflow_json': dict, 'reference_images': list, 'video_director_clips': list},
    'shots': {'characters': list, 'props': list, 'dialogues': list, 'keyframes': list, 'video_director_plan': dict},
    'chapters': {'parsed_data': dict, 'character_images': dict, 'shot_images': dict, 'shot_videos': dict, 'transition_videos': dict},
    'audio_event_tts_assets': {'config_json': dict},
    'shot_audio_timelines': {'audio_summary_json': dict},
    'llm_logs': {'request_info': dict},
}
LIST_FIELDS = {'kinds', 'calls', 'issues', 'shortlist', 'source_evidence', 'provenance', 'ranges', 'evidence', 'audio_snapshot', 'steps'}


def sha_text(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('NON_FINITE_JSON_NUMBER')


def decode_evidence(raw, expected=None):
    if raw is None or raw == '':
        return {'state': 'MISSING', 'value': None, 'sha256': sha_text(raw) if raw is not None else None,
                'length': 0, 'error': None, 'emptyConfirmed': False}
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, allow_nan=False)
    result = {'sha256': sha_text(text), 'length': len(text), 'value': None, 'error': None, 'emptyConfirmed': False}
    if len(text.encode('utf-8')) > MAX_JSON_BYTES:
        return {**result, 'state': 'TOO_LARGE', 'error': 'JSON_DISPLAY_LIMIT'}
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, TypeError, RecursionError) as exc:
        # Do not echo an undecodable credential-bearing fragment to the UI.
        message = exc.msg if isinstance(exc, json.JSONDecodeError) else type(exc).__name__
        return {**result, 'state': 'INVALID_JSON', 'error': message,
                'position': exc.pos if isinstance(exc, json.JSONDecodeError) else None}
    if value is None:
        return {**result, 'state': 'MISSING', 'error': 'JSON_NULL'}
    if expected and not isinstance(value, expected):
        return {**result, 'state': 'WRONG_TYPE', 'error': f'EXPECTED_{expected.__name__.upper()}', 'actualType': type(value).__name__}
    return {**result, 'state': 'VALID', 'value': value, 'emptyConfirmed': value in ({}, [])}


def safe_value(value, depth=0):
    """Mask credentials in stored structured records, including embedded workflow JSON."""
    if depth > 32:
        return '[DEPTH_LIMIT]'
    if isinstance(value, dict):
        result = {str(k): '[REDACTED]' if SECRET_KEY.fullmatch(str(k)) else safe_value(v, depth+1)
                  for k, v in list(value.items())[:1000]}
        if len(value) > 1000:
            result['__display_truncated__'] = True
        return result
    if isinstance(value, (list, tuple)):
        values = [safe_value(v, depth+1) for v in value[:1000]]
        return values + (['[DISPLAY_LIMIT]'] if len(value) > 1000 else [])
    if isinstance(value, str):
        if value.startswith('data:image/'):
            return f'[IMAGE_PAYLOAD sha256={sha_text(value)} length={len(value)}]'
        if value.lstrip().startswith(('{', '[')):
            parsed = decode_evidence(value)
            if parsed['state'] == 'VALID':
                public = safe_value(parsed['value'], depth+1)
                if public != parsed['value']:
                    value = json.dumps(public, ensure_ascii=False)
            elif parsed['state'] in {'INVALID_JSON', 'TOO_LARGE'}:
                return f'[UNPARSEABLE_JSON sha256={sha_text(value)} length={len(value)}]'
        value = re.sub(r'(?i)\bBearer\s+[^\s"\\]+', 'Bearer [REDACTED]', value)
        value = re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@', r'\1[REDACTED]@', value)
        value = re.sub(r'(?i)([?&](?:api_key|api_token|access_token|token|key)=)[^&#\s]+', r'\1[REDACTED]', value)
        return value if len(value) <= MAX_DISPLAY_CHARS else value[:MAX_DISPLAY_CHARS] + f'\n[DISPLAY_TRUNCATED length={len(value)}]'
    return jsonable_encoder(value)


def public_evidence(field, include_value=True):
    public = {k: v for k, v in field.items() if k != 'value'}
    value = safe_value(field['value'])
    public.update(redacted=value != jsonable_encoder(field['value']), truncated=field.get('length', 0) > MAX_DISPLAY_CHARS)
    if include_value:
        public['value'] = value
    return public


def read_record(db, model, record_id):
    table = model.__table__
    columns = [(cast(c, String).label(c.name) if isinstance(c.type, JSON) else c) for c in table.columns]
    primary = list(table.primary_key.columns)[0]
    with db.no_autoflush:
        row = db.execute(select(*columns).where(primary == record_id)).mappings().first()
    if row is None:
        return None
    record, fields = dict(row), {}
    for column in table.columns:
        expected = TEXT_JSON_FIELDS.get(table.name, {}).get(column.name)
        if isinstance(column.type, JSON):
            expected = list if column.name in LIST_FIELDS else dict
            # These provenance fields are objects, while Binding provenance is a list.
            if column.name == 'provenance' and table.name in {'character_identities', 'character_aliases'}:
                expected = dict
        if expected:
            fields[column.name] = task_field(record[column.name],column.name) if table.name=='tasks' else decode_evidence(record[column.name], expected)
            record[column.name] = fields[column.name]['value']
    return {'record': record, 'jsonFields': fields}


def task_evidence(task):
    return {key: task_field(getattr(task, key, None), key) for key in TEXT_JSON_FIELDS['tasks']}


def task_field(raw, field):
    result=decode_evidence(raw,TEXT_JSON_FIELDS['tasks'][field])
    if result['state']=='VALID' and field in {'reference_images','video_director_clips'}:
        for entry in result['value']:
            valid=isinstance(entry,dict)
            if field=='reference_images' and valid:
                valid=isinstance(entry.get('url'),str) and bool(entry['url']) and (entry.get('label') is None or isinstance(entry['label'],str))
            if not valid:
                return {**result,'state':'WRONG_TYPE','error':'INVALID_COLLECTION_MEMBER','value':None,'emptyConfirmed':False}
    return result


def workflow_snapshot(task, clip_index=None):
    """Inspect saved Task fields only, never today's Shot/Workflow or remote history."""
    evidence = task_evidence(task)
    workflow, prompt, references = evidence['workflow_json'], getattr(task,'prompt_text',None), evidence['reference_images']['value']
    path = 'Task.workflow_json'
    if clip_index is not None:
        clips = evidence['video_director_clips']
        selected = [c for c in clips['value'] or [] if isinstance(c,dict)
                    and str(c.get('window_index') or c.get('clip_index')) == str(clip_index)]
        if len(selected) > 1:
            workflow = {'state':'INVALID_JSON','value':None,'error':'DUPLICATE_CLIP_INDEX','length':0,'sha256':None,'emptyConfirmed':False}
        else:
            clip = selected[0] if selected else {}
            workflow = decode_evidence(clip.get('workflow_json'),dict)
            prompt, references = clip.get('prompt_text'), task_field(clip.get('reference_images'),'reference_images')['value']
            if clips['state'] not in {'VALID','MISSING'}:
                workflow = {**clips,'value':None}
        evidence['clip_workflow'] = workflow
        path = f'Task.video_director_clips[{clip_index}].workflow_json'
    return {'workflow':safe_value(workflow['value']), 'prompt':safe_value(prompt), 'referenceImages':safe_value(references),
            'workflowSource':'recorded' if workflow['state']=='VALID' else 'not_recorded' if workflow['state']=='MISSING' else 'corrupt',
            'sourceProof':{'verified':False,'code':'RECORDED_SNAPSHOT_ONLY','path':path,
                           'message':'保存内容与当前准入分别检查；来源追踪页展示完整来源与校验结果'},
            'evidence':{k:public_evidence(v,False) for k,v in evidence.items()},
            'note':'证据损坏或类型不符，未使用当前配置或其它记录回填' if workflow['state'] not in {'VALID','MISSING'} else
                   '未记录此工作流' if workflow['state']=='MISSING' else '任务保存的工作流快照（脱敏展示）'}
