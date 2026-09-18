"""The formal authoring writer. Authorized revisions extend, never rewrite, LLM evidence."""
from copy import deepcopy
from datetime import datetime
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.novel import Chapter
from app.models.shot import Shot
from app.models.task import Task
from app.models.audio_drive import AudioEventTTSAsset, ShotAudioEvent
from app.models.chapter_shot_split import ChapterShotSplitRun, ShotSource
from app.models.shot_revision import ShotRevision, ShotRevisionHead
from app.repositories.audio_drive import AudioDriveRepository
from app.services.chapter_asset_parse_service import digest
from app.services.chapter_shot_split_service import snapshot, audio_snapshot, source_payload, checked_source, checked_run

VERSION = 'shot-authoring-revision-v1'
DEPENDENCY_VERSION = 'render-inputs-v2'
TASK_TYPE = 'shot_revision'
JSON_FIELDS = {'characters', 'props', 'dialogues'}
EDIT_FIELDS = {'description', 'video_description', 'characters', 'scene', 'props', 'estimated_duration', 'continuity_mode', 'dialogues'}
VISUAL_FIELDS = {'description', 'characters', 'scene', 'props'}
TIMING_FIELDS = {'estimated_duration', 'continuity_mode'}
IMMUTABLE_SOURCE = {'shot_id', 'run_id', 'source_start', 'source_end', 'source_hash', 'evidence', 'ranges', 'source_contract'}
MEDIA_FIELDS = ('image_url', 'image_path', 'image_status', 'image_task_id', 'shot_image_prompt', 'keyframes',
                'video_url', 'video_status', 'video_task_id', 'video_director_plan', 'video_director_plan_revision', 'audio_status')


def conflict(code, **detail):
    raise HTTPException(409, {'code': code, **detail})


def semantic(value):
    return {k: json.loads(v) if k in JSON_FIELDS else v for k, v in value.items()}


def domain_seals(previous, current, revision_id, prior_visual, prior_audio, *, dependency_version=DEPENDENCY_VERSION, prior_render=None):
    before, after = semantic(previous['snapshot']), semantic(current['snapshot'])
    visual = any(before[k] != after[k] for k in VISUAL_FIELDS) or any(
        previous['bindings'][k] != current['bindings'][k] for k in ('characters', 'scenes', 'props'))
    audio = previous['audio_snapshot'] != current['audio_snapshot']
    old_contract,new_contract=previous.get('treatment_contract') or {},current.get('treatment_contract') or {}
    def visual_intents(contract):
        return [{'source_evidence':t['source_evidence'],'targets':t.get('visual_targets') or []}
                for t in contract.get('treatments',[]) if t.get('visual_targets')]
    def audio_intents(contract):
        return {'treatments':[t for t in contract.get('treatments',[]) if t['type']!='VISUAL'],
                'bindings':contract.get('event_bindings',[]),'overrides':contract.get('text_overrides',{})}
    if dependency_version=='legacy-v1':
        # Verify immutable historical receipts by the algorithm that signed them.
        # New writers never select this version or re-sign historical records.
        visual = visual or visual_intents(old_contract)!=visual_intents(new_contract)
        audio = audio or audio_intents(old_contract)!=audio_intents(new_contract)
    elif dependency_version==DEPENDENCY_VERSION:
        identities=lambda contract:[(b['event_id'],b['order']) for b in contract.get('event_bindings',[])]
        audio = audio or identities(old_contract)!=identities(new_contract)
    else:
        conflict('SHOT_REVISION_DEPENDENCY_VERSION_INVALID')
    result = {
        'visual_seal': digest([VERSION, 'visual', revision_id, current]) if visual else prior_visual,
        'audio_seal': digest([VERSION, 'audio', revision_id, current['audio_snapshot']]) if audio else prior_audio,
        'impact': {'visual': visual, 'audio': audio,
                   'timing': audio or any(before[k] != after[k] for k in TIMING_FIELDS),
                   'video': visual or audio or before != after},
    }
    if dependency_version==DEPENDENCY_VERSION:
        if not prior_render:conflict('SHOT_REVISION_RENDER_PIN_REQUIRED')
        result.update(dependency_version=DEPENDENCY_VERSION,render_seal=digest([VERSION,'render',revision_id,
            current['snapshot'],current['audio_snapshot'],current['bindings'],identities(new_contract)]) if result['impact']['video'] else prior_render)
    return result


def canonical_audio(db, events, names, scope):
    if not isinstance(events, list):
        conflict('SHOT_AUDIO_EVENTS_INVALID')
    actors = {b['name']: b for b in scope['characters']['bindings']}
    result = []
    seen = set()
    repo = AudioDriveRepository(db)
    for index, item in enumerate(events, 1):
        if not isinstance(item, dict):
            conflict('SHOT_AUDIO_EVENT_INVALID', order=index)
        event = repo._normalize_event_payload(item, index)
        event['event_order'] = index  # The explicitly submitted array is the authored order.
        kind, owner, visible = event['event_type'], event['voice_owner_name'], event['visible_speaker_name']
        if kind not in {'DIALOGUE', 'NARRATION', 'INNER_MONOLOGUE'} or not isinstance(event['text'], str) or not event['text'].strip():
            conflict('SHOT_AUDIO_EVENT_INVALID', order=index)
        if event['pause_after'] not in {'NONE', 'SHORT', 'MEDIUM', 'LONG'}:
            conflict('SHOT_AUDIO_PAUSE_INVALID', order=index)
        if kind == 'NARRATION':
            if owner != '旁白' or visible or event['requires_visible_lipsync'] or event['voice_owner_character_id'] or event['visible_speaker_character_id']:
                conflict('NARRATION_BINDING_INVALID', order=index)
            event['voice_owner_character_id'] = event['visible_speaker_character_id'] = None
        else:
            if owner not in actors:
                conflict('VOICE_OWNER_OUTSIDE_CHAPTER', owner=owner)
            expected = actors[owner]['assetId']
            if event['voice_owner_character_id'] not in {None, expected}:
                conflict('VOICE_OWNER_ID_MISMATCH', order=index)
            event['voice_owner_character_id'] = expected
            if kind == 'INNER_MONOLOGUE' and (visible or event['requires_visible_lipsync']):
                conflict('INNER_MONOLOGUE_LIPSYNC_INVALID', order=index)
            if visible and (visible != owner or visible not in names):
                conflict('VISIBLE_SPEAKER_OUTSIDE_SHOT', order=index)
            if bool(visible) != event['requires_visible_lipsync']:
                conflict('VISIBLE_SPEAKER_LIPSYNC_INVALID', order=index)
            visible_id = actors[visible]['assetId'] if visible else None
            if event['visible_speaker_character_id'] not in {None, visible_id}:
                conflict('VISIBLE_SPEAKER_ID_MISMATCH', order=index)
            event['visible_speaker_character_id'] = visible_id
        identity = item.get('id') or item.get('audioEventId') or item.get('audio_event_id')
        if identity and not str(identity).startswith('local-'):
            if identity in seen:
                conflict('AUDIO_EVENT_DUPLICATED', eventId=identity)
            seen.add(identity)
        elif identity:
            if identity in seen:conflict('AUDIO_EVENT_DUPLICATED',eventId=identity)
            seen.add(identity)
        result.append({'id': identity, 'treatment_ref':item.get('treatment_ref') or item.get('treatmentRef'), **event})
    return result


def dialogues_from_audio(events):
    return [{'order': index, 'character_name': event['voice_owner_name'], 'text': event['text'],
             'emotion_prompt': event['emotion_prompt']} for index, event in enumerate(
        (event for event in events if event['event_type'] == 'DIALOGUE'), 1)]


def canonical_dialogues(values):
    if not isinstance(values, list):
        conflict('SHOT_DIALOGUES_INVALID')
    result = []
    for index, value in enumerate(values, 1):
        if (not isinstance(value, dict) or not isinstance(value.get('text'), str) or not value['text'].strip()
                or not isinstance(value.get('character_name'), str) or not value['character_name'].strip()):
            conflict('SHOT_DIALOGUE_INVALID', order=index)
        result.append({'order': index, 'character_name': value['character_name'], 'text': value['text'],
                       'emotion_prompt': value.get('emotion_prompt') or '自然'})
    return result


def replace_authored_dialogues(events, dialogues, names):
    """An explicit dialogue edit updates its Audio Events; unrelated narration keeps its ID/order."""
    result, index = [], 0
    for old in events:
        if old['event_type'] != 'DIALOGUE':
            result.append(deepcopy(old)); continue
        if index < len(dialogues):
            line = dialogues[index]; owner = line['character_name']
            result.append({**old, 'voice_owner_name': owner, 'voice_owner_character_id': None,
                           'visible_speaker_name': owner if owner in names else None, 'visible_speaker_character_id': None,
                           'requires_visible_lipsync': owner in names, 'text': line['text'], 'emotion_prompt': line['emotion_prompt']})
            index += 1
    for line in dialogues[index:]:
        owner = line['character_name']
        result.append({'event_type': 'DIALOGUE', 'voice_owner_name': owner, 'visible_speaker_name': owner if owner in names else None,
                       'requires_visible_lipsync': owner in names, 'text': line['text'], 'emotion_prompt': line['emotion_prompt'], 'pause_after': 'NONE'})
    return result


def bindings_for(state, audio, basis, base):
    values = semantic(state)
    from app.services.chapter_scope import derive_source_window_bindings, validate_visible_character_closure, SplitReview
    try:
        validate_visible_character_closure(values['description'], values['characters'], values['index'], values['video_description'])
    except SplitReview as exc:
        raise HTTPException(409, str(exc)) from exc
    allowed = {kind: {b['name']: b for b in group['bindings']} for kind, group in basis['scope'].items()}
    selected = {'characters': values['characters'], 'scenes': [values['scene']], 'props': values['props']}
    bindings = {}
    for kind, names in selected.items():
        if not isinstance(names, list) or any(not isinstance(n, str) for n in names) or len(set(names)) != len(names) or any(n not in allowed[kind] for n in names):
            conflict('SHOT_ASSET_OUTSIDE_CHAPTER', kind=kind, names=names)
        bindings[kind] = [deepcopy(allowed[kind][n]) for n in names]
    boundaries = {b['name']: b['segments'] for b in basis['appearance_boundaries']}
    for name in selected['characters']:
        segment = next((s for s in boundaries.get(name, []) if s['start'] <= base.source_start and base.source_end <= s['end']), None)
        if not segment or segment['logical_status'] == 'UNRESOLVED':
            conflict('SHOT_CROSSES_APPEARANCE_BOUNDARY', character=name)
    if basis.get('source_windows') is not None:
        source_windows=derive_source_window_bindings(selected['characters'],base.source_start,base.source_end,basis)
        if source_windows is None:conflict('SHOT_CROSSES_APPEARANCE_BOUNDARY')
        bindings['source_windows']=source_windows
    owners = sorted({e['voice_owner_name'] for e in audio if e['event_type'] != 'NARRATION'})
    if any(n not in allowed['characters'] for n in owners):
        conflict('VOICE_OWNER_OUTSIDE_CHAPTER')
    bindings['voice_characters'] = [deepcopy(allowed['characters'][n]) for n in owners]
    return bindings


def effective_source(db, shot, base):
    """Validate an immutable revision chain, then compare the live row to its authorized head."""
    original = source_payload(base)
    head = db.get(ShotRevisionHead, shot.id)
    result, visual, audio, ordinal, revision_id, origin = original, base.seal, base.seal, 0, None, 'LLM_SPLIT'
    render=base.seal
    if head and head.revision_id:
        if head.base_run_id != base.run_id:
            conflict('SHOT_REVISION_BASE_CHANGED')
        latest = db.query(ShotRevision).filter_by(shot_id=shot.id, base_run_id=base.run_id).order_by(ShotRevision.revision.desc()).first()
        if not latest or latest.id != head.revision_id or latest.revision != head.revision:
            conflict('SHOT_REVISION_HEAD_CHANGED')
        chain, seen, row = [], set(), latest
        while row:
            if row.id in seen:
                conflict('SHOT_REVISION_CYCLE')
            seen.add(row.id); chain.append(row)
            if row.parent_id:
                row = db.get(ShotRevision, row.parent_id)
                if not row:
                    conflict('SHOT_REVISION_PARENT_MISSING')
            else:
                row = None
        parent_id, parent_seal = None, base.seal
        basis = db.get(ChapterShotSplitRun, base.run_id).inputs['basis']
        for row in reversed(chain):
            payload = row.payload
            task = db.get(Task, row.task_id)
            meta = json.loads(task.metadata_json or '{}') if task else {}
            if (row.shot_id != shot.id or row.chapter_id != shot.chapter_id or row.novel_id != basis['novel_id']
                    or row.base_run_id != base.run_id or row.origin not in {'USER_API', 'IMPORT'}
                    or row.revision != ordinal + 1 or row.parent_id != parent_id or digest(payload) != row.seal
                    or payload.get('version') != VERSION or payload.get('id') != row.id
                    or payload.get('base_seal') != base.seal or payload.get('parent_seal') != parent_seal
                    or payload.get('parent_id') != parent_id or payload.get('revision') != row.revision
                    or not task or task.type != TASK_TYPE or task.status != 'completed'
                    or task.shot_id != shot.id or task.chapter_id != shot.chapter_id or task.novel_id != row.novel_id
                    or meta != {'execution_purpose': 'production', 'shot_revision_id': row.id, 'revision_seal': row.seal}):
                conflict('SHOT_REVISION_PROOF_INVALID')
            source = payload['source']
            if any((k in source) != (k in original) or source.get(k) != original.get(k) for k in IMMUTABLE_SOURCE):
                conflict('SHOT_REVISION_SOURCE_RANGE_CHANGED')
            if source['bindings'] != bindings_for(source['snapshot'], source['audio_snapshot'], basis, base):
                conflict('SHOT_REVISION_BINDINGS_CHANGED')
            from app.services.shot_treatment_contract import validate_source_contract
            validate_source_contract(SimpleNamespace(**source),basis)
            dependency_version=payload.get('dependency_version','legacy-v1')
            domains = domain_seals(result, source, row.id, visual, audio,dependency_version=dependency_version,prior_render=render)
            if any(payload.get(k) != v for k, v in domains.items()):
                conflict('SHOT_REVISION_IMPACT_CHANGED')
            result, visual, audio, ordinal = source, domains['visual_seal'], domains['audio_seal'], row.revision
            render=row.seal if dependency_version=='legacy-v1' else domains['render_seal']
            parent_id, parent_seal, revision_id, origin = row.id, row.seal, row.id, row.origin
    elif head and (head.base_run_id != base.run_id or head.revision != 0):
        conflict('SHOT_REVISION_HEAD_CHANGED')
    if result['snapshot'] != snapshot(shot) or result['audio_snapshot'] != audio_snapshot(db, shot.id):
        conflict('SHOT_SOURCE_CHANGED_NEEDS_REBUILD')
    contract=result.get('treatment_contract')
    if not contract:conflict('CONTRACT_UNAVAILABLE')
    actual_events=AudioDriveRepository(db).list_events(shot.id)
    if [(e.id,e.event_order) for e in actual_events]!=[(b['event_id'],b['order']) for b in contract.get('event_bindings',[])]:
        conflict('TREATMENT_EVENT_SCOPE_MISMATCH')
    return SimpleNamespace(**deepcopy(result), seal=parent_seal if revision_id else base.seal,
                            visual_seal=visual, audio_seal=audio, render_seal=render, revision=ordinal, revision_id=revision_id,
                           origin=origin, base_seal=base.seal)


def approved_audio_ancestor(db, shot_id, pin, event_id):
    """Read an accepted ancestor by its explicit audio seal and Event UUID.

    This permits unchanged TTS to survive another event/visual edit without
    rewriting its original source pin, config, Task or physical media.
    """
    shot=db.get(Shot,shot_id)
    if not shot:return None
    current=checked_source(db,shot)
    expected={'version':'runtime-source-v1','shot_id':shot_id,'split_run_id':current.run_id,'source_hash':current.source_hash}
    if not isinstance(pin,dict) or {k:v for k,v in pin.items() if k!='seal'}!=expected:return None
    base=db.get(ShotSource,shot_id)
    candidates=[(base.seal,source_payload(base))]
    identity=current.revision_id
    while identity:
        revision=db.get(ShotRevision,identity)
        candidates.append((revision.payload['audio_seal'],revision.payload['source']))
        identity=revision.parent_id
    for seal,source in candidates:
        if seal!=pin.get('seal'):continue
        contract=source.get('treatment_contract') or {}
        binding=next((b for b in contract.get('event_bindings',[]) if b['event_id']==event_id),None)
        if binding:
            return next((e for e in source['audio_snapshot'] if e['event_order']==binding['order']),None)
    return None


class ShotRevisionService:
    def __init__(self, db):
        self.db = db

    def _prepare(self, shot, patch, base, current, basis):
        from app.schemas.shot_revision import normalize_revision_aliases
        try:patch=normalize_revision_aliases(patch)
        except ValueError as exc:conflict(str(exc))
        if type(patch.get('expected_revision')) is not int or patch['expected_revision']<0:
            conflict('SHOT_REVISION_REQUIRED',shotId=shot.id)
        if patch['expected_revision'] != current.revision:
            conflict('SHOT_REVISION_CONFLICT', shotId=shot.id, expected=patch['expected_revision'], current=current.revision)
        if set(patch) & {'snapshot', 'audio_snapshot', 'seal', 'source', 'image_url', 'video_url', 'video_director_plan', 'treatment_contract', 'text_overrides'}:
            conflict('SHOT_REVISION_PROTECTED_FIELD')
        state = deepcopy(current.snapshot)
        values = semantic(state)
        patch = deepcopy(patch)
        if 'estimatedDuration' in patch and 'estimated_duration' not in patch:
            patch['estimated_duration'] = patch['estimatedDuration']
        if 'duration' in patch and 'estimated_duration' not in patch:
            patch['estimated_duration'] = patch['duration']
        for key in EDIT_FIELDS - {'dialogues'}:
            if key in patch:
                values[key] = patch[key]
        if (any(not isinstance(values[k], str) or not values[k].strip() for k in ('description', 'scene'))
                or not isinstance(values['video_description'], str)
                or type(values['estimated_duration']) is not int or not 1 <= values['estimated_duration'] <= 3600
                or values['continuity_mode'] not in {'NORMAL', 'CONTINUOUS_TAKE'}):
            conflict('SHOT_REVISION_FIELDS_INVALID')
        existing = [dict(id=e.id, **{k: getattr(e, k) for k in ('event_order', 'event_type', 'voice_owner_character_id', 'voice_owner_name',
            'visible_speaker_character_id', 'visible_speaker_name', 'requires_visible_lipsync', 'text', 'emotion_prompt', 'pause_after')})
                    for e in AudioDriveRepository(self.db).list_events(shot.id)]
        refs={b['event_id']:b['treatment_ref'] for b in current.treatment_contract['event_bindings']}
        for event in existing:event['treatment_ref']=refs[event['id']]
        has_audio = 'audio_events' in patch or 'audioEvents' in patch
        supplied=deepcopy(patch.get('audio_events',patch.get('audioEvents'))) if has_audio else existing
        if isinstance(supplied,list):
            for event in supplied:
                if isinstance(event,dict) and 'treatment_ref' not in event and 'treatmentRef' not in event and event.get('id') in refs:
                    event['treatment_ref']=refs[event['id']]  # Carry the explicit parent binding, not a name/text guess.
        events = canonical_audio(self.db, supplied, values['characters'], basis['scope'])
        old_dialogues = canonical_dialogues(values['dialogues'])
        submitted_dialogues = canonical_dialogues(patch['dialogues']) if 'dialogues' in patch else old_dialogues
        audio_changed = [{k:v for k,v in e.items() if k not in {'id','treatment_ref'}} for e in events] != current.audio_snapshot
        if submitted_dialogues != old_dialogues:
            if has_audio and audio_changed and submitted_dialogues != dialogues_from_audio(events):
                conflict('DIALOGUE_AUDIO_EVENT_MISMATCH')
            if not has_audio or not audio_changed:
                events = canonical_audio(self.db, replace_authored_dialogues(existing, submitted_dialogues, values['characters']), values['characters'], basis['scope'])
        values['dialogues'] = dialogues_from_audio(events)
        for key in EDIT_FIELDS:
            if key in JSON_FIELDS:
                if json.loads(state[key]) != values[key]:
                    state[key] = json.dumps(values[key], ensure_ascii=False)
            else:
                state[key] = values[key]
        existing_ids = {e['id'] for e in existing}
        if any(e['id'] and not str(e['id']).startswith('local-') and e['id'] not in existing_ids for e in events):
            conflict('AUDIO_EVENT_OUTSIDE_SHOT')
        audio = [{k:v for k,v in e.items() if k not in {'id','treatment_ref'}} for e in events]
        source = {**source_payload(base), 'snapshot': state, 'audio_snapshot': audio,
                  'bindings': bindings_for(state, audio, basis, base)}
        from app.schemas.chapter_shot_split import SourceTreatment
        from app.services.shot_treatment_contract import make_contract, validate_source_contract
        from app.services.narration_coverage import validate_coverage,error_message,locate,spoken_projection,texts_cover
        raw_treatments=patch.get('source_treatments',patch.get('sourceTreatments',current.treatment_contract['treatments']))
        if not isinstance(raw_treatments,list):conflict('SOURCE_TREATMENT_MISSING')
        try:treatments=[SourceTreatment.model_validate(t).model_dump() for t in raw_treatments]
        except ValueError as exc:raise HTTPException(422,{'code':'TREATMENT_SCHEMA_INVALID','message':str(exc)}) from exc
        planned={'id':state['index'],'source_evidence':source['evidence'],'description':state['description'],
                 'video_description':state['video_description'],'source_treatments':treatments,'dialogues':values['dialogues'],
                 'audio_events':[{'order':e['event_order'],'type':e['event_type'],'treatment_ref':e['treatment_ref'],
                    'voice_owner':e['voice_owner_name'],'visible_speaker':e['visible_speaker_name'],
                    'requires_visible_lipsync':e['requires_visible_lipsync'],'text':e['text'],
                    'emotion_prompt':e['emotion_prompt'],'pause_after':e['pause_after']} for e in events]}
        overrides=deepcopy(current.treatment_contract.get('text_overrides',{}))
        old_events={e['id']:e for e in existing}
        old_treatments={t['key']:t for t in current.treatment_contract['treatments']}
        parent_positions=validate_source_contract(current,basis)['resolved'][0]['event_sources']
        parent_by_id={b['event_id']:parent_positions.get(str(b['order'])) for b in current.treatment_contract['event_bindings']}
        # A local key rename preserves an authored text exception only through
        # unchanged explicit Event UUID membership and the same declaration.
        for treatment in treatments:
            linked=[e for e in events if e['treatment_ref']==treatment['key']]
            parents={refs[e['id']] for e in linked if e['id'] in refs}
            if len(parents)!=1:continue
            parent=next(iter(parents));previous=old_treatments[parent]
            if (parent in overrides and treatment['key']!=parent
                    and {k:v for k,v in previous.items() if k!='key'}=={k:v for k,v in treatment.items() if k!='key'}
                    and [e['id'] for e in linked]==[e['id'] for e in existing if e['treatment_ref']==parent]
                    and all(e['id'] in old_events and e['text']==old_events[e['id']]['text'] for e in linked)):
                overrides[treatment['key']]=overrides[parent]
        valid_keys={t['key'] for t in treatments if t['type']!='VISUAL'}
        overrides={k:v for k,v in overrides.items() if k in valid_keys}
        for treatment in treatments:
            key=treatment['key'];linked=[e for e in events if e['treatment_ref']==key]
            changed_text=any(e['id'] not in old_events or e['text']!=old_events[e['id']]['text'] for e in linked)
            regrouped_authored=all(e['id'] in old_events for e in linked) and any(
                refs[e['id']]!=key and refs[e['id']] in current.treatment_contract.get('text_overrides',{}) for e in linked if e['id'] in refs)
            if key in valid_keys and linked and (changed_text or regrouped_authored) and (has_audio or 'dialogues' in patch):
                try:
                    ranges=locate(basis['source']['content'],treatment['source_evidence'],[(base.source_start,base.source_end)])
                    expected=spoken_projection(ranges,'DIALOGUE' if treatment['type']=='DIALOGUE' else treatment.get('audio_type') or 'NARRATION')
                except ValueError:
                    continue  # The validator below reports exact source errors; no override can hide them.
                if texts_cover(expected,linked):overrides.pop(key,None)
                else:overrides[key]=''.join(e['text'] for e in linked)
        inherited={str(e['event_order']):parent_by_id[e['id']] for e in events if parent_by_id.get(e['id'])}
        # UUID-bound parent partitions, not the newly authored text or current
        # array order, retain each Event's source ownership after an edit/regroup.
        needs_partitions=any(t['key'] in overrides and sum(e['treatment_ref']==t['key'] for e in events)>1 for t in treatments)
        authored_change=(state!=current.snapshot or audio!=current.audio_snapshot or treatments!=current.treatment_contract['treatments']
                         or overrides!=current.treatment_contract.get('text_overrides',{}))
        if needs_partitions and authored_change and any(t['key'] in overrides and any(str(e['event_order']) not in inherited for e in events if e['treatment_ref']==t['key'])
                                    for t in treatments if sum(e['treatment_ref']==t['key'] for e in events)>1):
            conflict('AUTHORED_EVENT_SOURCE_BINDING_REQUIRED')
        report=validate_coverage({'shots':[planned]},basis,chapter_wide=False,authored_texts={str(state['index']):overrides},
                                event_sources={str(state['index']):inherited})
        if report['status']!='PASS':conflict('TREATMENT_VALIDATION_FAILED',issues=report['issues'],message=error_message(report))
        provisional=[e['id'] if e['id'] in existing_ids else 'pending:'+str(e['event_order']) for e in events]
        source['treatment_contract']=make_contract(planned,report['resolved'][0],provisional,text_overrides=overrides)
        keep_partitions=any('source_ranges' in b for b in current.treatment_contract['event_bindings']) or (needs_partitions and source!=source_payload(current))
        event_sources=report['resolved'][0]['event_sources'] if keep_partitions else None
        if event_sources:source['treatment_contract']=make_contract(planned,report['resolved'][0],provisional,text_overrides=overrides,event_sources=event_sources)
        return {'shot': shot, 'base': base, 'current': current, 'source': source, 'events': events, 'patch': patch,
                'planned':planned,'resolved_treatments':report['resolved'][0],'text_overrides':overrides,'event_sources':event_sources,
                'changed': source != source_payload(current), 'prompt': patch.get('shot_image_prompt')}

    def save_batch(self, novel_id, chapter_id, patches, *, origin='USER_API'):
        db = self.db
        if origin not in {'USER_API', 'IMPORT'} or not isinstance(patches, list) or not patches:
            conflict('SHOT_REVISION_REQUEST_INVALID')
        if not db.query(Chapter.id).filter_by(id=chapter_id, novel_id=novel_id).first():
            raise HTTPException(404, '章回不存在')
        ids = [p.get('id') for p in patches if isinstance(p, dict)]
        if len(ids) != len(patches) or any(not i for i in ids) or len(ids) != len(set(ids)):
            conflict('SHOT_REVISION_MEMBERSHIP_INVALID')
        try:
            # A single write fence serializes admission/publication on SQLite as well as
            # row-locking databases. All semantic validation precedes business changes.
            if db.query(Chapter).filter_by(id=chapter_id, novel_id=novel_id).update({'id': chapter_id}, synchronize_session=False) != 1:
                conflict('SHOT_REVISION_CHAPTER_CHANGED')
            db.expire_all()  # The write fence must read committed heads, not an earlier Session identity map.
            active = db.query(Task.id).filter(Task.status.in_(['pending', 'running', 'queued']),
                (Task.shot_id.in_(ids)) | ((Task.chapter_id == chapter_id) & Task.type.in_(
                    ['chapter_shot_split', 'chapter_asset_rebuild', 'shot_image_batch', 'shot_video_batch', 'chapter_video']))).first()
            if active:
                conflict('SHOT_REVISION_TASK_ACTIVE', taskId=active[0])
            prepared, bases, event_id_maps = [], {}, {}
            for patch in patches:
                shot = db.query(Shot).filter_by(id=patch['id'], chapter_id=chapter_id).populate_existing().first()
                if not shot:
                    raise HTTPException(404, '分镜不存在')
                if getattr(shot,'completion_disposition','NORMAL')=='DEGRADED_NARRATION_CARD':
                    conflict('NARRATION_CARD_IMMUTABLE',shotId=shot.id)
                base = db.get(ShotSource, shot.id)
                if not base:
                    conflict('LEGACY_SHOT_NEEDS_REBUILD', shotId=shot.id)
                if base.run_id not in bases:
                    bases[base.run_id] = checked_run(db, db.get(ChapterShotSplitRun, base.run_id))
                current = checked_source(db, shot, basis=bases[base.run_id], run_checked=True)
                prepared.append(self._prepare(shot, patch, base, current, bases[base.run_id]))
            for item in prepared:
                shot, current, base = item['shot'], item['current'], item['base']
                if not item['changed']:
                    if item['prompt'] is not None:
                        shot.shot_image_prompt = item['prompt']
                    continue
                rid, tid = str(uuid4()), str(uuid4())
                previous_media = {k: getattr(shot, k) for k in MEDIA_FIELDS}
                previous_media['chapter_final_video'] = shot.chapter.final_video
                previous_media['events'] = [{c.name: getattr(e,c.name).isoformat() if isinstance(getattr(e,c.name), datetime) else getattr(e,c.name)
                                            for c in ShotAudioEvent.__table__.columns} for e in AudioDriveRepository(db).list_events(shot.id)]
                head = db.get(ShotRevisionHead, shot.id)
                if not head:
                    head = ShotRevisionHead(shot_id=shot.id, base_run_id=base.run_id, revision=0)
                    db.add(head); db.flush()
                for key in EDIT_FIELDS:
                    setattr(shot, key, item['source']['snapshot'][key])
                provisional_domains = domain_seals(source_payload(current), item['source'], rid, current.visual_seal, current.audio_seal,prior_render=current.render_seal)
                if provisional_domains['impact']['timing']:
                    shot.duration = shot.estimated_duration
                event_repo=AudioDriveRepository(db)
                event_repo.sync_events(shot.id, item['events'], commit=False)
                if event_repo.last_sync_id_map:event_id_maps[shot.id]=event_repo.last_sync_id_map
                from app.services.shot_treatment_contract import make_contract
                item['source']['treatment_contract']=make_contract(item['planned'],item['resolved_treatments'],
                    [e.id for e in AudioDriveRepository(db).list_events(shot.id)],text_overrides=item['text_overrides'],event_sources=item['event_sources'])
                domains = domain_seals(source_payload(current), item['source'], rid, current.visual_seal, current.audio_seal,prior_render=current.render_seal)
                if any(e['event_type']=='NARRATION' for e in item['events']):
                    from app.services.narrator_profile_service import ensure_narrator
                    ensure_narrator(db, novel_id)
                if domains['impact']['visual']:
                    shot.image_status = 'pending'
                    shot.shot_image_prompt = ''
                if domains['impact']['video']:
                    if domains['impact']['timing']:
                        from app.services.invalidation_service import InvalidationService
                        InvalidationService(db).invalidate_audio_downstream(shot.id, '正式Shot时长修订，重新准备时间线', commit=False)
                    elif not domains['impact']['timing']:
                        from app.services.invalidation_service import VIDEO_FACT_KEYS
                        from app.services.video_director_plan_service import VideoDirectorPlanService
                        shot.video_url = shot.video_task_id = None
                        shot.video_status = 'pending'
                        shot.chapter.final_video = None
                        shot.chapter.final_video_task_id = None
                        def invalidate_video(plan):
                            plan.pop('merged_video_url', None); plan.pop('merged_at', None)
                            plan.update(keyframe_planning_status='STALE', invalidation_reason='正式Shot视觉/导演修订',
                                        invalidation_level='SHOT_REVISION_CHANGED')
                            for key in ('window_plans', 'execution_windows', 'clips'):
                                for window in plan.get(key) or []:
                                    for field in VIDEO_FACT_KEYS:
                                        window.pop(field, None)
                                    window['status'] = 'PENDING'
                            return plan
                        VideoDirectorPlanService(db).mutate(shot.id, invalidate_video, commit=False)
                db.flush()
                if snapshot(shot) != item['source']['snapshot'] or audio_snapshot(db, shot.id) != item['source']['audio_snapshot']:
                    conflict('SHOT_REVISION_PUBLICATION_MISMATCH')
                payload = {'version': VERSION, 'id': rid, 'revision': current.revision+1, 'base_seal': base.seal,
                           'parent_id': current.revision_id, 'parent_seal': current.seal, 'request': deepcopy(item['patch']),
                           'source': item['source'], 'previous_media': previous_media, **domains}
                seal = digest(payload)
                row = ShotRevision(id=rid, shot_id=shot.id, novel_id=novel_id, chapter_id=chapter_id, base_run_id=base.run_id,
                    task_id=tid, parent_id=current.revision_id, revision=current.revision+1, origin=origin, payload=payload, seal=seal)
                now = datetime.utcnow()
                task = Task(id=tid, type=TASK_TYPE, status='completed', name=f'保存分镜修订 · Shot {shot.index}',
                    novel_id=novel_id, chapter_id=chapter_id, shot_id=shot.id, progress=100, started_at=now, completed_at=now,
                    current_step='合法修订已发布，按影响范围准备媒体', metadata_json=json.dumps({
                        'execution_purpose':'production', 'shot_revision_id':rid, 'revision_seal':seal}, ensure_ascii=False))
                db.add_all([row, task]); db.flush()
                changed = db.query(ShotRevisionHead).filter_by(shot_id=shot.id, base_run_id=base.run_id,
                    revision=current.revision, revision_id=current.revision_id).update({
                        'revision_id':rid, 'revision':current.revision+1}, synchronize_session=False)
                if changed != 1:
                    conflict('SHOT_REVISION_CONFLICT', shotId=shot.id)
                db.expire(head)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            conflict('SHOT_REVISION_CONFLICT', detail=str(exc.orig))
        except BaseException:
            db.rollback(); raise
        from app.repositories.shot_repository import ShotRepository
        db.expire_all()
        return {'success':True, 'message':'分镜修订已保存', 'data':{'updated_count':len(ids),
            'eventIdMaps':event_id_maps,
            'shots':[ShotRepository(db).to_response(db.get(Shot,sid)) for sid in ids]}}
