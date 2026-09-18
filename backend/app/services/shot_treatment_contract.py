"""Director prompt loading and publication adapters; the validator itself is pure."""
from copy import deepcopy
import json
from pathlib import Path

from app.services.narration_coverage import VERSION, validate_coverage, error_message
from app.services.chapter_asset_parse_service import digest

PROMPT_PATH=Path(__file__).resolve().parents[2]/'prompt_templates/shot_source_treatment_contract.json'


def load_director_increment():
    raw=PROMPT_PATH.read_text(encoding='utf-8');definition=json.loads(raw)
    if definition.get('version')!=VERSION or any(not isinstance(definition.get(k),str) or not definition[k].strip() for k in ('system_suffix','structure_lock_suffix')):
        raise ValueError('SOURCE_TREATMENT_PROMPT_INVALID')
    return {'file':'prompt_templates/shot_source_treatment_contract.json','hash':digest(raw),'definition':definition}


def make_contract(planned, resolved, event_ids, *, text_overrides=None, event_sources=None):
    if len(event_ids)!=len(planned['audio_events']):raise ValueError('TREATMENT_EVENT_MEMBERSHIP_CHANGED')
    return {'version':VERSION,'treatments':deepcopy(planned['source_treatments']),
            'resolved_treatments':deepcopy(resolved['treatments']),
            'event_bindings':[{'event_id':identity,'order':event['order'],'treatment_ref':event['treatment_ref'],
                               **({'source_ranges':deepcopy(event_sources[str(event['order'])])} if event_sources and str(event['order']) in event_sources else {})}
                              for identity,event in zip(event_ids,planned['audio_events'])],
            'text_overrides':deepcopy(text_overrides or {})}


def source_as_candidate(source):
    contract=source.treatment_contract
    if not isinstance(contract,dict) or contract.get('version')!=VERSION:raise ValueError('CONTRACT_UNAVAILABLE')
    stored=source.snapshot
    bindings=contract.get('event_bindings')
    if not isinstance(bindings,list) or len(bindings)!=len(source.audio_snapshot):raise ValueError('TREATMENT_EVENT_MEMBERSHIP_CHANGED')
    if len({b['event_id'] for b in bindings})!=len(bindings) or any(not b['event_id'] for b in bindings):raise ValueError('TREATMENT_EVENT_SCOPE_MISMATCH')
    events=[]
    for event,binding in zip(source.audio_snapshot,bindings):
        if event['event_order']!=binding['order']:raise ValueError('TREATMENT_EVENT_ORDER_CHANGED')
        events.append({'order':event['event_order'],'type':event['event_type'],'treatment_ref':binding['treatment_ref'],
            'voice_owner':event['voice_owner_name'],'visible_speaker':event['visible_speaker_name'],
            'requires_visible_lipsync':event['requires_visible_lipsync'],'text':event['text'],
            'emotion_prompt':event['emotion_prompt'],'pause_after':event['pause_after']})
    return {'id':stored['index'],'source_evidence':deepcopy(source.evidence),'description':stored['description'],
            'video_description':stored['video_description'],'source_treatments':deepcopy(contract['treatments']),
            'audio_events':events,'dialogues':json.loads(stored['dialogues'])}


def validate_ownership_contract(source, basis):
    from app.services.chapter_scope import OWNERSHIP_VERSION, ownership_source
    expected_version=basis.get('source_contract_version')
    contract=deepcopy(getattr(source,'source_contract',None))
    if expected_version != OWNERSHIP_VERSION:
        if contract is not None:raise ValueError('SOURCE_CONTRACT_VERSION')
        return None
    if not isinstance(contract,dict) or contract.get('version')!=OWNERSHIP_VERSION:
        raise ValueError('SOURCE_CONTRACT_VERSION')
    try:
        rebuilt=ownership_source(basis['source']['content'],{
            'source_citations':contract['citation_evidence'],
            'source_ownership':contract['ownership_evidence'],
        })
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError(f'SOURCE_OWNERSHIP_CONTRACT_INVALID: {exc}') from exc
    owner=rebuilt['ownership_range']
    if (contract!=rebuilt or source.source_start!=owner['start'] or source.source_end!=owner['end']
            or source.evidence!=[rebuilt['ownership_evidence']] or source.ranges!=[owner]):
        raise ValueError('SOURCE_OWNERSHIP_CONTRACT_CHANGED')
    return rebuilt


def validate_source_contract(source, basis):
    validate_ownership_contract(source,basis)
    candidate=source_as_candidate(source)
    positions={str(b['order']):b['source_ranges'] for b in source.treatment_contract['event_bindings'] if 'source_ranges' in b}
    report=validate_coverage({'shots':[candidate]},basis,chapter_wide=False,
        authored_texts={str(candidate['id']):source.treatment_contract.get('text_overrides',{})},
        event_sources={str(candidate['id']):positions})
    if report['status']!='PASS':raise ValueError(error_message(report))
    if report['resolved'][0]['treatments']!=source.treatment_contract['resolved_treatments']:
        raise ValueError('TREATMENT_RESOLVED_RANGES_CHANGED')
    if any(report['resolved'][0]['event_sources'].get(order)!=spans for order,spans in positions.items()):
        raise ValueError('AUDIO_EVENT_SOURCE_BINDING_CHANGED')
    return report


def saved_contract(db, shot_id):
    """Read-only display projection. Production admission still verifies Source/revision seals."""
    from app.models.shot_revision import ShotRevisionHead,ShotRevision
    from app.models.chapter_shot_split import ShotSource
    head=db.get(ShotRevisionHead,shot_id)
    if head and head.revision_id:
        revision=db.get(ShotRevision,head.revision_id)
        return deepcopy(revision.payload.get('source',{}).get('treatment_contract')) if revision else None
    source=db.get(ShotSource,shot_id)
    return deepcopy(source.treatment_contract) if source else None
